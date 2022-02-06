from datetime import datetime, timezone
from functools import reduce
import importlib
import os
from pathlib import Path
import tempfile
import typing

import qgis.core
from osgeo import gdal
from qgis.PyQt import (
    QtCore,
    QtGui,
    QtWidgets
)

from .jobs import manager
from .jobs.models import Job
from .logger import log


def utc_to_local(utc_dt):
    return utc_dt.astimezone(tz=None)


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


def qgis_process_path() -> str:
    """
    Use heuristic approach in determining the location of the
    'qgis_process' program (or script in Windows). Returns an
    empty string if platform is not supported or if the program
    (or script) could not be found.
    """
    app = qgis.core.QgsApplication.instance()
    os_name = app.osName()
    proc_script_path = ''
    warning, info = qgis.core.Qgis.Warning, qgis.core.Qgis.Info

    if os_name == 'windows':
        lib_path = app.libexecPath()
        rt_path, sep, sub_path = lib_path.partition('apps')
        if not sep:
            log('QGIS installation path not found.', warning)
            return ''

        proc_scripts = [
            'qgis_process-qgis.bat',
            'qgis_process-qgis-dev.bat',
            'qgis_process-qgis-ltr.bat'
        ]
        for pc in proc_scripts:
            proc_script_path = f'{rt_path}bin/{pc}'
            if os.path.exists(proc_script_path):
                break

    if not proc_script_path:
        log('QGIS processing program/script not found.', warning)
        return ''

    # Check execution permissions
    if not os.access(proc_script_path, os.X_OK):
        log(f'User does not have execution permission '
            f'for \'{proc_script_path}\'.')
        return ''

    return proc_script_path


def deep_get_attr(obj, attr):
    # Gets attribute value of inner objects e.g. job.script.name
	return reduce(getattr, attr.split('.'), obj)


def deep_has_attr(obj, attr):
    # Check whether the object and nested objects have the given attribute.
    try:
        _ = deep_get_attr(obj, attr)
        return True
    except AttributeError:
        return False


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
    def project_path_from_report_path(report_path) -> str:
        # Get QGIS project path from the corresponding report path
        fi = QtCore.QFileInfo(report_path)
        proj_file_name = fi.completeBaseName().replace(
            'report',
            'project'
        )
        return f'{fi.dir().path()}/{proj_file_name}.qgs'

    @staticmethod
    def get_icon(icon_name: str) -> QtGui.QIcon:
        # Assumes icon_name includes the file extension.
        icon_path = os.path.normpath(
            f'{FileUtils.plugin_dir()}/icons/{icon_name}'
        )

        if not os.path.exists(icon_path):
            return None

        return QtGui.QIcon(icon_path)




