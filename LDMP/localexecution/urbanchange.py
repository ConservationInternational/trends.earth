import datetime as dt
import tempfile
from pathlib import Path

import numpy as np
import openpyxl
import qgis.core
from osgeo import gdal

import LDMP.logger
from .. import (
    areaofinterest,
    calculate,
    calculate_urban,
    summary,
    utils,
    worker,
)
from ..jobs import models


def compute_urban_change_summary_table(
        urban_change_job: models.Job,
        area_of_interest: areaofinterest.AOI
) -> models.Job:
    urban_files = []
    for band_index in urban_change_job.params.params["urban_layer_band_indexes"]:
        urban_file_vrt_path = utils.save_vrt(
            urban_change_job.params.params["urban_layer_path"], band_index)
        urban_files.append(urban_file_vrt_path)
    pop_files = []
    for band_index in urban_change_job.params.params["urban_layer_pop_band_indexes"]:
        pop_file_vrt_path = utils.save_vrt(
            urban_change_job.params.params["urban_layer_path"], band_index)
        pop_files.append(pop_file_vrt_path)
    in_files = urban_files + pop_files
    urban_band_nums = np.arange(len(urban_files)) + 1
    pop_band_nums = np.arange(len(pop_files)) + 1 + urban_band_nums.max()
    _, wkts = area_of_interest.meridian_split('layer', 'wkt', warn=False)
    bbs = area_of_interest.get_aligned_output_bounds(urban_files[1])
    job_output_path, _ = utils.get_local_job_output_paths(urban_change_job)
    for n in range(len(wkts)):
        # Compute the pixel-aligned bounding box (slightly larger than
        # aoi). Use this instead of croptocutline in gdal.Warp in order to
        # keep the pixels aligned with the chosen productivity layer.
        indic_vrt = tempfile.NamedTemporaryFile(suffix='.vrt').name
        LDMP.logger.log(u'Saving indicator VRT to: {}'.format(indic_vrt))
        gdal.BuildVRT(
            indic_vrt,
            in_files,
            outputBounds=bbs[n],
            resolution='highest',
            resampleAlg=gdal.GRA_NearestNeighbour,
            separate=True
        )

        output_indicator_tifs = []
        if len(wkts) > 1:
            output_indicator_tif = (
                    job_output_path.parent / f"{job_output_path.stem}_{n}.tif")
        else:
            output_indicator_tif = (
                    job_output_path.parent / f"{job_output_path.stem}.tif")
        output_indicator_tifs.append(output_indicator_tif)

        LDMP.logger.log(f'Saving urban clipped files to {output_indicator_tif}')
        geojson = calculate.json_geom_to_geojson(
            qgis.core.QgsGeometry.fromWkt(wkts[n]).asJson()
        )
        clip_worker = worker.StartWorker(
            calculate.ClipWorker,
            'masking layers (part {} of {})'.format(n + 1, len(wkts)),
            indic_vrt,
            str(output_indicator_tif),
            geojson,
            bbs[n]
        )
        if clip_worker.success:
            LDMP.logger.log('Calculating summary table...')
            urban_summary_worker = worker.StartWorker(
                UrbanSummaryWorker,
                'calculating summary table (part {} of {})'.format(n + 1, len(wkts)),
                str(output_indicator_tif),
                urban_band_nums,
                pop_band_nums,
                9
            )
            if urban_summary_worker.success:
                if n == 0:
                    areas, populations = urban_summary_worker.get_return()
                else:
                    these_areas, these_populations = urban_summary_worker.get_return()
                    areas = areas + these_areas
                    populations = populations + these_populations
            else:
                raise RuntimeError("Error calculating urban change summary table.")
        else:
            raise RuntimeError("Error masking urban change input layers.")

    summary_table_output_path = job_output_path.parent / f"{job_output_path.stem}.xlsx"
    save_summary_table(areas, populations, summary_table_output_path)

    urban_change_job.end_date = dt.datetime.now(dt.timezone.utc)
    urban_change_job.progress = 100
    bands = []
    for name in ("Urban", "Population"):
        # TODO: NOTE to A. Zvoleff: seems weird to hardcode years in this, but I'm following the previous implementation, so not going to change it
        for year in range(2000, 2016, 5):
            bands.append(
                models.JobBand(
                    name=name,
                    metadata={
                        "year": year
                    }
                ),
            )
    urban_change_job.results.bands = bands
    if len(output_indicator_tifs) == 1:
        output_path = output_indicator_tifs[0]
    else:
        output_path = job_output_path.parent / f"{job_output_path.stem}.vrt"
        gdal.BuildVRT(str(output_path), [str(path) for path in output_indicator_tifs])
    urban_change_job.results.data_path = output_path
    return urban_change_job


def save_summary_table(areas, populations, out_file):
    template_summary_table_path = Path(
        __file__).parents[1] / "data/summary_table_urban.xlsx"
    workbook = openpyxl.load_workbook(str(template_summary_table_path))
    sheet = workbook['SDG 11.3.1 Summary Table']
    summary.write_table_to_sheet(sheet, areas, 23, 2)
    summary.write_table_to_sheet(sheet, populations, 37, 2)
    utils.maybe_add_image_to_sheet('trends_earth_logo_bl_300width.png', sheet)
    try:
        workbook.save(out_file)
        LDMP.logger.log(u'Summary table saved to {}'.format(out_file))

    except IOError as exc:
        raise RuntimeError(
            f"Error saving output table - check that {out_file!r} is accessible and "
            f"not already open. - {str(exc)}"
        )


class UrbanSummaryWorker(worker.AbstractWorker):

    def __init__(self, src_file, urban_band_nums, pop_band_nums, n_classes):
        worker.AbstractWorker.__init__(self)

        self.src_file = src_file
        self.urban_band_nums = [int(x) for x in urban_band_nums]
        self.pop_band_nums = [int(x) for x in pop_band_nums]
        self.n_classes = n_classes

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        src_ds = gdal.Open(self.src_file)

        urban_bands = [src_ds.GetRasterBand(b) for b in self.urban_band_nums]
        pop_bands = [src_ds.GetRasterBand(b) for b in self.pop_band_nums]

        block_sizes = urban_bands[1].GetBlockSize()
        xsize = urban_bands[1].XSize
        ysize = urban_bands[1].YSize

        x_block_size = block_sizes[0]
        y_block_size = block_sizes[1]

        src_gt = src_ds.GetGeoTransform()

        # Width of cells in longitude
        long_width = src_gt[1]
        # Set initial lat ot the top left corner latitude
        lat = src_gt[3]
        # Width of cells in latitude
        pixel_height = src_gt[5]

        areas = np.zeros((self.n_classes, len(self.urban_band_nums)))
        populations = np.zeros((self.n_classes, len(self.pop_band_nums)))

        blocks = 0
        for y in range(0, ysize, y_block_size):
            if y + y_block_size < ysize:
                rows = y_block_size
            else:
                rows = ysize - y
            for x in range(0, xsize, x_block_size):
                if self.killed:
                    LDMP.logger.log("Processing of {} killed by user after processing {} out of {} blocks.".format(self.prod_out_file, y, ysize))
                    break
                self.progress.emit(100 * (float(y) + (float(x)/xsize)*y_block_size) / ysize)
                if x + x_block_size < xsize:
                    cols = x_block_size
                else:
                    cols = xsize - x

                # Caculate cell area for each horizontal line
                cell_areas = np.array([summary.calc_cell_area(lat + pixel_height*n, lat + pixel_height*(n + 1), long_width) for n in range(rows)])
                # Convert areas from meters into hectares
                cell_areas = cell_areas * 1e-4
                cell_areas.shape = (cell_areas.size, 1)
                # Make an array of the same size as the input arrays containing
                # the area of each cell (which is identicalfor all cells ina
                # given row - cell areas only vary among rows)
                cell_areas_array = np.repeat(cell_areas, cols, axis=1)

                # Loop over the bands (years)
                for i in range(len(self.urban_band_nums)):
                    urban_array = urban_bands[i].ReadAsArray(x, y, cols, rows)
                    pop_array = pop_bands[i].ReadAsArray(x, y, cols, rows)
                    pop_array[pop_array == -32768] = 0
                    # Now loop over the classes
                    for c in range(1, self.n_classes + 1):
                        areas[c - 1, i] += np.sum((urban_array == c) * cell_areas_array)
                        pop_masked = pop_array.copy() * (urban_array == c)
                        # Convert population densities to persons per hectare
                        # from persons per sq km
                        pop_masked = pop_masked / 100
                        populations[c - 1, i] += np.sum(pop_masked * cell_areas_array)

                blocks += 1
            lat += pixel_height * rows
        self.progress.emit(100)

        if self.killed:
            return None
        else:
            return list((areas, populations))
