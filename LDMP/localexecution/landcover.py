import datetime as dt
import os
import tempfile
from pathlib import Path

from osgeo import gdal
from osgeo import osr
from te_schemas.land_cover import LCLegendNesting
from te_schemas.land_cover import LCTransitionDefinitionDeg
from te_schemas.results import Band as JobBand
from te_schemas.results import DataType
from te_schemas.results import Raster
from te_schemas.results import RasterFileType
from te_schemas.results import RasterResults
from te_schemas.results import URI

from .. import calculate_lc
from .. import utils
from .. import worker
from ..areaofinterest import AOI
from ..jobs.models import Job
from ..logger import log


def _prepare_land_cover_inputs(job: Job, area_of_interest: AOI) -> Path:
    # Select the initial and final bands from initial and final datasets
    # (in case there is more than one lc band per dataset)
    lc_initial_path = job.params["lc_initial_path"]
    lc_initial_band_index = job.params["lc_initial_band_index"]
    lc_initial_vrt = utils.save_vrt(lc_initial_path, lc_initial_band_index)
    lc_final_path = job.params["lc_final_path"]
    lc_final_band_index = job.params["lc_final_band_index"]
    lc_final_vrt = utils.save_vrt(lc_final_path, lc_final_band_index)

    # Add the lc layers to a VRT in case they don't match in resolution,
    # and set proper output bounds
    in_vrt = tempfile.NamedTemporaryFile(suffix=".vrt").name
    gdal.BuildVRT(
        in_vrt,
        [lc_initial_vrt, lc_final_vrt],
        resolution="highest",
        resampleAlg=gdal.GRA_NearestNeighbour,
        outputBounds=area_of_interest.get_aligned_output_bounds_deprecated(
            lc_initial_vrt
        ),
        separate=True,
    )

    return Path(in_vrt)


def compute_land_cover(
    lc_job: Job, area_of_interest: AOI, job_output_path: Path, dataset_output_path: Path
) -> Job:
    in_vrt = _prepare_land_cover_inputs(lc_job, area_of_interest)
    trans_matrix = LCTransitionDefinitionDeg.Schema().loads(
        lc_job.params["trans_matrix"]
    )
    nesting = LCLegendNesting.Schema().loads(lc_job.params["legend_nesting"])

    class_codes = sorted([c.code for c in nesting.child.key])
    class_positions = [*range(1, len(class_codes) + 1)]

    lc_change_worker = worker.StartWorker(
        LandCoverChangeWorker,
        "calculating land cover change",
        str(in_vrt),
        str(dataset_output_path),
        trans_matrix.get_list(),
        (class_codes, class_positions),
        nesting.child.get_multiplier(),
        trans_matrix.get_persistence_list(),
    )

    if lc_change_worker.success:
        lc_job.end_date = dt.datetime.now(dt.timezone.utc)
        lc_job.progress = 100
        bands = [
            JobBand(
                name="Land cover (degradation)",
                metadata={
                    "year_initial": lc_job.params["year_initial"],
                    "year_final": lc_job.params["year_final"],
                    "trans_matrix": LCTransitionDefinitionDeg.Schema().dumps(
                        trans_matrix
                    ),
                    "nesting": LCLegendNesting.Schema().dumps(nesting),
                },
            ),
            JobBand(
                name="Land cover",
                metadata={
                    "year": lc_job.params["year_initial"],
                    "nesting": LCLegendNesting.Schema().dumps(nesting),
                },
            ),
            JobBand(
                name="Land cover",
                metadata={
                    "year": lc_job.params["year_final"],
                    "nesting": LCLegendNesting.Schema().dumps(nesting),
                },
            ),
            JobBand(
                name="Land cover transitions",
                metadata={
                    "year_initial": lc_job.params["year_initial"],
                    "year_final": lc_job.params["year_final"],
                    "nesting": LCLegendNesting.Schema().dumps(nesting),
                },
            ),
        ]
        lc_job.results = RasterResults(
            name="land_cover",
            uri=URI(uri=dataset_output_path, type="local"),
            rasters={
                DataType.INT16.value: Raster(
                    uri=URI(uri=dataset_output_path, type="local"),
                    bands=bands,
                    datatype=DataType.INT16,
                    filetype=RasterFileType.GEOTIFF,
                ),
            },
        )
    else:
        raise RuntimeError("Error calculating land cover change.")

    return lc_job


class LandCoverChangeWorker(worker.AbstractWorker):
    def __init__(
        self, in_f, out_f, trans_matrix, class_recode, multiplier, persistence_remap
    ):
        worker.AbstractWorker.__init__(self)
        self.in_f = in_f
        self.out_f = out_f
        self.trans_matrix = trans_matrix
        # class_recode is key for recoding classes from raw codes to ordinal codes
        # used for calculating transitions
        self.class_recode = class_recode
        self.multiplier = multiplier
        self.persistence_remap = persistence_remap

    def work(self):
        ds_in = gdal.Open(self.in_f)

        band_initial = ds_in.GetRasterBand(1)
        band_final = ds_in.GetRasterBand(2)

        block_sizes = band_initial.GetBlockSize()
        x_block_size = block_sizes[0]
        y_block_size = block_sizes[1]
        xsize = band_initial.XSize
        ysize = band_initial.YSize

        driver = gdal.GetDriverByName("GTiff")
        ds_out = driver.Create(
            self.out_f, xsize, ysize, 4, gdal.GDT_Int16, ["COMPRESS=LZW"]
        )
        src_gt = ds_in.GetGeoTransform()
        ds_out.SetGeoTransform(src_gt)
        out_srs = osr.SpatialReference()
        out_srs.ImportFromWkt(ds_in.GetProjectionRef())
        ds_out.SetProjection(out_srs.ExportToWkt())

        blocks = 0

        for y in range(0, ysize, y_block_size):
            if y + y_block_size < ysize:
                rows = y_block_size
            else:
                rows = ysize - y

            for x in range(0, xsize, x_block_size):
                if self.killed:
                    log(
                        "Processing killed by user after processing {} out of {} blocks.".format(
                            y, ysize
                        )
                    )

                    break
                self.progress.emit(
                    100 * (float(y) + (float(x) / xsize) * y_block_size) / ysize
                )

                if x + x_block_size < xsize:
                    cols = x_block_size
                else:
                    cols = xsize - x

                a_i = band_initial.ReadAsArray(x, y, cols, rows)
                a_f = band_final.ReadAsArray(x, y, cols, rows)

                ds_out.GetRasterBand(2).WriteArray(a_i, x, y)
                ds_out.GetRasterBand(3).WriteArray(a_f, x, y)

                # Recode bands from raw codes to ordinal values prior to
                # calculating transitions
                for value, replacement in zip(
                    self.class_recode[0], self.class_recode[1]
                ):
                    a_i[a_i == int(value)] = int(replacement)
                    a_f[a_f == int(value)] = int(replacement)

                a_tr = a_i * self.multiplier + a_f
                a_tr[(a_i < 1) | (a_f < 1)] < -32768

                a_deg = a_tr.copy()

                for value, replacement in zip(
                    self.trans_matrix[0], self.trans_matrix[1]
                ):
                    a_deg[a_deg == int(value)] = int(replacement)

                # Recode transitions so that persistence classes are easier to
                # map

                for value, replacement in zip(
                    self.persistence_remap[0], self.persistence_remap[1]
                ):
                    a_tr[a_tr == int(value)] = int(replacement)

                ds_out.GetRasterBand(1).WriteArray(a_deg, x, y)
                ds_out.GetRasterBand(4).WriteArray(a_tr, x, y)

                blocks += 1

        if self.killed:
            os.remove(self.out_f)

            return None
        else:
            return True
