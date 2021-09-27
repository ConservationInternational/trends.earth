import os
import datetime as dt
import tempfile
from pathlib import Path

from osgeo import (
    gdal,
    osr
)

from .. import (
    calculate_lc,
    utils,
    worker,
)

from .. import log
from ..areaofinterest import AOI
from ..jobs import models


def _prepare_land_cover_inputs(job: models.Job, area_of_interest: AOI) -> Path:
    # Select the initial and final bands from initial and final datasets
    # (in case there is more than one lc band per dataset)
    lc_initial_path = job.params.params["lc_initial_path"]
    lc_initial_band_index = job.params.params["lc_initial_band_index"]
    lc_initial_vrt = utils.save_vrt(lc_initial_path, lc_initial_band_index)
    lc_final_path = job.params.params["lc_final_path"]
    lc_final_band_index = job.params.params["lc_final_band_index"]
    lc_final_vrt = utils.save_vrt(lc_final_path, lc_final_band_index)

    # Add the lc layers to a VRT in case they don't match in resolution,
    # and set proper output bounds
    in_vrt = tempfile.NamedTemporaryFile(suffix='.vrt').name
    gdal.BuildVRT(
        in_vrt,
        [lc_initial_vrt, lc_final_vrt],
        resolution='highest',
        resampleAlg=gdal.GRA_NearestNeighbour,
        outputBounds=area_of_interest.get_aligned_output_bounds_deprecated(
            lc_initial_vrt),
        separate=True
    )
    return Path(in_vrt)


def compute_land_cover(lc_job: models.Job, area_of_interest: AOI) -> models.Job:
    in_vrt = _prepare_land_cover_inputs(lc_job, area_of_interest)
    job_output_path, dataset_output_path = utils.get_local_job_output_paths(lc_job)
    trans_matrix = [
        [
            11, 12, 13, 14, 15, 16, 17,
            21, 22, 23, 24, 25, 26, 27,
            31, 32, 33, 34, 35, 36, 37,
            41, 42, 43, 44, 45, 46, 47,
            51, 52, 53, 54, 55, 56, 57,
            61, 62, 63, 64, 65, 66, 67
        ],
        lc_job.params.params["transformation_matrix"]
    ]
    # Remap the persistence classes so they are sequential, making them
    # easier to assign a clear color ramp in QGIS
    persistence_remap = [
        [
            11, 12, 13, 14, 15, 16, 17,
            21, 22, 23, 24, 25, 26, 27,
            31, 32, 33, 34, 35, 36, 37,
            41, 42, 43, 44, 45, 46, 47,
            51, 52, 53, 54, 55, 56, 57,
            61, 62, 63, 64, 65, 66, 67,
            71, 72, 73, 74, 75, 76, 77
        ],
        [
            1, 12, 13, 14, 15, 16, 17,
            21, 2, 23, 24, 25, 26, 27,
            31, 32, 3, 34, 35, 36, 37,
            41, 42, 43, 4, 45, 46, 47,
            51, 52, 53, 54, 5, 56, 57,
            61, 62, 63, 64, 65, 6, 67,
            71, 72, 73, 74, 75, 76, 7
        ]
    ]
    lc_change_worker = worker.StartWorker(
        LandCoverChangeWorker,
        'calculating land cover change',
        str(in_vrt),
        str(dataset_output_path),
        trans_matrix,
        persistence_remap
    )
    if lc_change_worker.success:
        lc_job.end_date = dt.datetime.now(dt.timezone.utc)
        lc_job.progress = 100
        lc_job.results.bands = [
            models.JobBand(
                name="Land cover (degradation)",
                metadata={
                    "year_baseline": lc_job.params.params["year_baseline"],
                    "year_target": lc_job.params.params["year_target"]
                },
            ),
            models.JobBand(
                name="Land cover (7 class)",
                metadata={
                    "year": lc_job.params.params["year_baseline"],
                }
            ),
            models.JobBand(
                name="Land cover (7 class)",
                metadata={
                    "year": lc_job.params.params["year_target"],
                }
            ),
            models.JobBand(
                name="Land cover transitions",
                metadata={
                    "year_baseline": lc_job.params.params["year_baseline"],
                    "year_target": lc_job.params.params["year_target"]
                }
            ),
        ]
        lc_job.results.data_path = dataset_output_path
    else:
        raise RuntimeError("Error calculating land cover change.")
    return lc_job


class LandCoverChangeWorker(worker.AbstractWorker):

    def __init__(self, in_f, out_f, trans_matrix, persistence_remap):
        worker.AbstractWorker.__init__(self)
        self.in_f = in_f
        self.out_f = out_f
        self.trans_matrix = trans_matrix
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
        ds_out = driver.Create(self.out_f, xsize, ysize, 4, gdal.GDT_Int16,
                               ['COMPRESS=LZW'])
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
                    log("Processing killed by user after processing {} out of {} blocks.".format(y, ysize))
                    break
                self.progress.emit(100 * (float(y) + (float(x) / xsize) * y_block_size) / ysize)
                if x + x_block_size < xsize:
                    cols = x_block_size
                else:
                    cols = xsize - x

                a_i = band_initial.ReadAsArray(x, y, cols, rows)
                a_f = band_final.ReadAsArray(x, y, cols, rows)

                a_tr = a_i * 10 + a_f
                a_tr[(a_i < 1) | (a_f < 1)] < - -32768

                a_deg = a_tr.copy()
                for value, replacement in zip(self.trans_matrix[0], self.trans_matrix[1]):
                    a_deg[a_deg == int(value)] = int(replacement)

                # Recode transitions so that persistence classes are easier to
                # map
                for value, replacement in zip(self.persistence_remap[0], self.persistence_remap[1]):
                    a_tr[a_tr == int(value)] = int(replacement)

                ds_out.GetRasterBand(1).WriteArray(a_deg, x, y)
                ds_out.GetRasterBand(2).WriteArray(a_i, x, y)
                ds_out.GetRasterBand(3).WriteArray(a_f, x, y)
                ds_out.GetRasterBand(4).WriteArray(a_tr, x, y)

                blocks += 1
        if self.killed:
            os.remove(self.out_f)
            return None
        else:
            return True
