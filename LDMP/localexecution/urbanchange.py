import datetime as dt
import tempfile
from pathlib import Path

import numpy as np
import openpyxl
import qgis.core
from osgeo import gdal

from .. import (
    areaofinterest,
    calculate,
    calculate_urban,
    log,
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
        log(u'Saving indicator VRT to: {}'.format(indic_vrt))
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

        log(f'Saving urban clipped files to {output_indicator_tif}')
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
            log('Calculating summary table...')
            urban_summary_worker = worker.StartWorker(
                calculate_urban.UrbanSummaryWorker,
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
    urban_change_job.results.local_paths = [output_path]
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
        log(u'Summary table saved to {}'.format(out_file))

    except IOError:
        error_message = (
            f"Error saving output table - check that {out_file!r} is accessible and "
            f"not already open."
        )
        log(error_message)
