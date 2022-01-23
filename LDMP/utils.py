from datetime import datetime, timezone
import importlib
import os
from pathlib import Path
import re
import tempfile
import typing
import unicodedata

import qgis.core
from osgeo import gdal
from qgis.PyQt import (
    QtGui,
    QtWidgets
)

from .jobs import manager
from .jobs.models import Job
from .logger import log

from te_schemas import jobs


def utc_to_local(utc_dt):
    return utc_dt.astimezone(tz=None)


def slugify(value, allow_unicode=False):
    """
    Taken from https://github.com/django/django/blob/master/django/utils/text.py
    Convert to ASCII if 'allow_unicode' is False. Convert spaces or repeated
    dashes to single dashes. Remove characters that aren't alphanumerics,
    underscores, or hyphens. Convert to lowercase. Also strip leading and
    trailing whitespace, dashes, and underscores.
    """
    value = str(value)

    if allow_unicode:
        value = unicodedata.normalize('NFKC', value)
    else:
        value = unicodedata.normalize('NFKD',
                                      value).encode('ascii',
                                                    'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value.lower())

    return re.sub(r'[-\s]+', '-', value).strip('-_')


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
        name_fragments.append(job.task_name)
    if job.script.name:
        name_fragments.append(job.script.name)
    if job.local_context.area_of_interest_name:
        name_fragments.append(job.local_context.area_of_interest_name)
    if job.start_date:
        name_fragments.append(job.start_date.strftime("%Y%m%d%H%M"))
    name_fragments.append(str(job.id))
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


class FileUtils:
    """
    Provides functionality for commonly used file-related operations.
    """
    @staticmethod
    def plugin_dir() -> str:
        return os.path.join(os.path.dirname(os.path.realpath(__file__)))

    @staticmethod
    def report_templates_dir() -> str:
        return os.path.normpath(
            f'{FileUtils.plugin_dir()}/data/reports'
        )

    @staticmethod
    def get_icon(icon_name: str) -> QtGui.QIcon:
        # Assumes icon_name includes the file extension
        icon_path = os.path.normpath(
            f'{FileUtils.plugin_dir()}/icons/{icon_name}'
        )

        if not os.path.exists(icon_path):
            return None

        return QtGui.QIcon(icon_path)

