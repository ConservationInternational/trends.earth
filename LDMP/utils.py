import importlib
import tempfile
import typing
from pathlib import Path
from datetime import datetime, timezone

import qgis.core
from osgeo import gdal
from PyQt5 import (
    QtWidgets,
)

from .jobs import manager
from .jobs.models import Job

from te_schemas import jobs


def utc_to_local(utc_dt):
    return utc_dt.replace(tzinfo=timezone.utc).astimezone(tz=None)


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


def get_local_job_output_paths(job: Job) -> typing.Tuple[Path, Path]:
    """Retrieve output path for a job so that it can be sent to the local processor"""
    # NOTE: temporarily setting the status as the final value in order to determine
    # the target filepath for the processing's outputs
    previous_status = job.status
    job.status = jobs.JobStatus.GENERATED_LOCALLY
    job_output_path = manager.job_manager.get_job_file_path(job)
    job_output_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_output_path = job_output_path.parent / f"{job_output_path.stem}.tif"
    job.status = previous_status
    return job_output_path, dataset_output_path


def maybe_add_image_to_sheet(image_filename: str, sheet, place="H1"):
    from openpyxl.drawing.image import Image
    try:
        image_path = Path(__file__).parent / "data" / image_filename
        logo = Image(image_path)
        sheet.add_image(logo, place)
    except ImportError:
        # add_image will fail on computers without PIL installed (this will be
        # an issue on some Macs, likely others). it is only used here to add
        # our logo, so no big deal.
        pass


def delete_dataset(job: Job) -> int:
    message_box = QtWidgets.QMessageBox()

    separator = "_"
    name_fragments = []
    if job.task_name:
        name_fragments.append(job.params.get('task_name'))
    name_fragments.extend([
        job.script.name,
        job.local_context.area_of_interest_name,
        job.start_date.strftime("%Y%m%d%H%M"),
        str(job.id)
    ])

    message_box.setText(
        f"You are about to delete job {separator.join(name_fragments)!r}")
    message_box.setInformativeText("Confirm?")
    message_box.setStandardButtons(
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel)
    message_box.setDefaultButton(QtWidgets.QMessageBox.Cancel)
    message_box.setIcon(QtWidgets.QMessageBox.Information)
    result = QtWidgets.QMessageBox.Res = message_box.exec_()
    if result == QtWidgets.QMessageBox.Yes:
        if job.results is not None:
            remove_layer_from_qgis(job.results.data_path)
        manager.job_manager.delete_job(job)
    return result


def remove_layer_from_qgis(path: Path):
    project = qgis.core.QgsProject.instance()
    for layer_id in project.mapLayers():
        layer = project.mapLayer(layer_id)
        layer_source = Path(layer.source()).absolute()
        if layer_source == path:
            project.removeMapLayer(layer_id)
            break
