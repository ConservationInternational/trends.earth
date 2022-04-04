from datetime import datetime, timezone
from functools import reduce
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import typing

import qgis.core
from osgeo import gdal
from qgis.PyQt import (
    QtGui,
    QtWidgets
)

from .jobs import manager
from .jobs.models import Job
from .logger import log
from .reports.models import slugify


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
            remove_layer_from_qgis(job.results.uri)

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


def qgis_bin_dir() -> str:
    """
    Returns the directory containing qgis' scripts and executables depending
    on the platform. Returns an empty string if the path cannot be
    determined.
    """
    app = qgis.core.QgsApplication.instance()
    platform_name = sys.platform
    lib_path = app.libexecPath()
    rt_path = ''
    warning, info = qgis.core.Qgis.Warning, qgis.core.Qgis.Info
    msg = 'QGIS \'bin\' directory could not be determined.'

    if platform_name == 'win32':
        rt_path, sep, sub_path = lib_path.partition('apps')
        if not sep:
            log(msg, warning)
            return ''

    elif platform_name == 'darwin':
        rt_path, sep, sub_path = lib_path.partition('lib')
        if not sep:
            log(msg, warning)
            return ''

    elif platform_name in ('linux', 'freebsd'):
        rt_path = '/usr/'

    if rt_path:
        return f'{rt_path}bin'

    return rt_path


def qgis_exec_path() -> str:
    """
    Returns the absolute path to the main QGIS executable otherwise an
    empty string if the installation path could not be determined.
    """
    rt_bin_dir = qgis_bin_dir()
    if not rt_bin_dir:
        log('QGIS installation not found.', qgis.core.Qgis.Warning)
        return ''

    platform_name = sys.platform
    if platform_name == 'win32':
        exec_name = 'qgis-bin.exe'
    else:
        exec_name = 'qgis'

    return f'{rt_bin_dir}/{exec_name}'


def open_qgis_project(project_path: str) -> bool:
    """
    Opens a qgs or qgz project given its path. Returns True if succeeded,
    else False if the QGIS executable could not be found or if the project
    path does not exist.
    """
    warning = qgis.core.Qgis.Warning

    exec_path = qgis_exec_path()
    if not exec_path:
        log('Cannot open project. QGIS executable not found.', warning)
        return False

    if not os.path.exists(project_path):
        log(f'QGIS project \'{project_path}\' does not exist.', warning)
        return False

    params = [exec_path, '--project', project_path]
    subprocess.Popen(params, shell=True)

    return True


def qgis_process_path() -> str:
    """
    Use heuristic approach in determining the location of the
    'qgis_process' program (or script in Windows). Returns an
    empty string if platform is not supported or if the program
    (or script) could not be found.
    """
    platform_name = sys.platform
    warning, info = qgis.core.Qgis.Warning, qgis.core.Qgis.Info
    proc_script_path = ''

    rt_bin_dir = qgis_bin_dir()
    if not rt_bin_dir:
        log('QGIS installation not found.', warning)
        return ''

    if platform_name == 'win32':
        proc_scripts = [
            'qgis_process-qgis.bat',
            'qgis_process-qgis-dev.bat',
            'qgis_process-qgis-ltr.bat'
        ]
        for pc in proc_scripts:
            proc_script_path = f'{rt_bin_dir}/{pc}'
            if os.path.exists(proc_script_path):
                break

    elif platform_name == 'darwin' or \
            platform_name in ('linux', 'freebsd'):
        proc_script_path = f'{rt_bin_dir}/qgis_process'

    if not proc_script_path:
        log('Unable to determine the system platform.', warning)
        return ''

    if not os.path.exists(proc_script_path):
        log('QGIS processing program/script not found.', warning)
        return ''

    # Check execution permissions
    if not os.access(proc_script_path, os.X_OK):
        log(f'User does not have execute permission '
            f'for \'{proc_script_path}\'.')
        return ''

    return proc_script_path

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
    def project_path_from_report_task(
            report_task,
            root_output_dir: str
    ) -> str:
        task_name = slugify(report_task.display_name())
        # Get QGIS project path from the corresponding report path
        return f'{root_output_dir}/{task_name}.qgz'

    @staticmethod
    def open_project(
            report_task,
            root_output_dir: str
    ) -> bool:
        """
        Opens a project from a report task process. True if the operation
        succeeded, else False.
        """
        proj_path = FileUtils.project_path_from_report_task(
            report_task,
            root_output_dir
        )
        return open_qgis_project(proj_path)

    @staticmethod
    def get_icon(icon_name: str) -> QtGui.QIcon:
        # Assumes icon_name includes the file extension.
        icon_path = os.path.normpath(
            f'{FileUtils.plugin_dir()}/icons/{icon_name}'
        )

        if not os.path.exists(icon_path):
            return QtGui.QIcon()

        return QtGui.QIcon(icon_path)

    @staticmethod
    def get_icon_pixmap(icon_name: str) -> QtGui.QPixmap:
        """
        Returns icon as a QPixmap object.
        """
        icon_path = os.path.normpath(
            f'{FileUtils.plugin_dir()}/icons/{icon_name}'
        )

        if not os.path.exists(icon_path):
            return QtGui.QPixmap()

        im = QtGui.QImage(icon_path)
        return QtGui.QPixmap.fromImage(im)

    @staticmethod
    def te_logo_path() -> str:
        """
        Returns the paths to the trends earth logo in the plugin directory.
        """
        logo_file_name = 'trends_earth_logo_bl_small.png'
        return f'{FileUtils.plugin_dir()}/icons/{logo_file_name}'
