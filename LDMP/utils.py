import importlib
import tempfile
import typing
from pathlib import Path

from osgeo import gdal

from .jobs import (
    manager,
    models,
)


def load_object(python_path: str) -> typing.Any:
    module_path, object_name = python_path.rpartition(".")[::2]
    loaded_module = importlib.import_module(module_path)
    return getattr(loaded_module, object_name)


def save_vrt(source_path: Path, source_band_index: int) -> str:
    temporary_file = tempfile.NamedTemporaryFile(suffix=".vrt", delete=False)
    temporary_file.close()
    gdal.BuildVRT(
        temporary_file.name,
        str(source_path),
        bandList=[source_band_index]
    )
    return temporary_file.name


def get_local_job_output_paths(job: models.Job) -> typing.Tuple[Path, Path]:
    """Retrieve output path for a job so that it can be sent to the local processor"""
    # NOTE: temporarily setting the status as the final value in order to determine
    # the target filepath for the processing's outputs
    previous_status = job.status
    job.status = models.JobStatus.GENERATED_LOCALLY
    job_output_path = manager.job_manager.get_job_file_path(job)
    dataset_output_path = job_output_path.parent / f"{job_output_path.stem}.tif"
    job.status = previous_status
    return job_output_path, dataset_output_path
