import datetime as dt
import tempfile
import typing
from pathlib import Path

from osgeo import gdal

from .. import (
    calculate_lc,
    data_io,
    utils,
    worker,
)

from ..areaofinterest import AOI
from ..jobs import (
    models,
    manager,
)


def get_land_cover_job_params(
        task_name: str,
        aoi: AOI,
        year_baseline: int,
        year_target: int,
        combo_initial_layer: data_io.WidgetDataIOSelectTELayerImport,
        combo_final_layer: data_io.WidgetDataIOSelectTELayerImport,
        transformation_matrix: typing.List,
        task_notes: typing.Optional[str] = "",
) -> typing.Dict:
    initial_path_band_info = combo_initial_layer.get_usable_band_info()
    final_path_band_info = combo_final_layer.get_usable_band_info()
    return {
        "task_name": task_name,
        "task_notes": task_notes,
        "year_baseline": year_baseline,
        "year_target": year_target,
        "lc_initial_path": str(initial_path_band_info.path),
        "lc_initial_band_index": initial_path_band_info.band_index,
        "lc_final_path": str(final_path_band_info.path),
        "lc_final_band_index": final_path_band_info.band_index,
        "transformation_matrix": transformation_matrix
    }


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

    # NOTE: temporarily setting the status as the final value in order to determine
    # the target filepath for the processing's outputs
    previous_status = lc_job.status
    lc_job.status = models.JobStatus.GENERATED_LOCALLY
    job_output_path = manager.job_manager.get_job_file_path(lc_job)
    dataset_output_path = job_output_path.parent / f"{job_output_path.stem}.tif"
    lc_job.status = previous_status


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
        calculate_lc.LandCoverChangeWorker,
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
        lc_job.results.local_paths = [dataset_output_path]
    else:
        raise RuntimeError("Error calculating land cover change.")
    return lc_job



