"""Report generator"""

from enum import Enum
import json
import os
import typing
from uuid import uuid4

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsFeedback,
    QgsLayoutExporter,
    QgsPrintLayout,
    QgsProject,
    QgsRasterLayer,
    QgsReadWriteContext,
    QgsTask
)
from qgis.gui import (
    QgsMessageBar
)
from qgis.PyQt.QtCore import (
    pyqtSignal,
    QFile,
    QFileInfo,
    QIODevice,
    QObject,
    QProcess
)
from qgis.PyQt.QtXml import (
    QDomDocument
)

from te_schemas.results import Band as JobBand

from ..jobs.models import Job
from ..layers import get_band_title, styles
from ..logger import log

from .models import (
    OutputFormat,
    ReportTaskContext
)

from ..utils import qgis_process_path


class TaskStatus(Enum):
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'
    PENDING = 'pending'
    STARTED = 'started'


class ReportProcessHandlerTask(QgsTask):
    """
    Bridge for communicating with the report task algorithm to run in
    'qgis_process'.
    """
    def __init__(
            self,
            ctx_file_path: str,
            task_id: str,
            qgis_proc_path: str
    ):
        super().__init__(task_id)
        self._ctx_file = ctx_file_path
        self._task_id = task_id
        self._qgs_proc_path = qgis_proc_path
        self._proc = QProcess(self)
        self._proc.errorOccurred.connect(self._on_process_error)
        self._proc.finished.connect(self._on_process_finished)

    @property
    def context_file(self) -> str:
        """
        Returns the path to the report context JSON file.
        """
        return self._ctx_file

    def run(self) -> bool:
        # Launch qgis_process and execute algorithm.
        if self.isCanceled():
            self._proc.kill()
            return False

        input_file = f'INPUT={self._ctx_file}'
        args = ['run', 'trendsearth:reporttask', '--', input_file]
        status = self._proc.startDetached(self._qgs_proc_path, args)
        log(str(status))

        return True

    def _on_process_error(self, error):
        # Log error information
        log('A reporting error occurred')
        self.cancel()

    def _on_process_finished(self, code, status):
        # When process has finished
        log(f'On process finished: {str(code)}')

    def finished(self, result):
        pass


class ReportTaskProcessor:
    """
    Produces a QGIS project, template and resulting report
    (in image or PDF format) based on information in a
    ReportTaskContext object.
    """
    def __init__(
            self,
            ctx: ReportTaskContext,
            proj: QgsProject,
            feedback: QgsFeedback=None
    ):
        self._ctx = ctx
        self._ti = self._ctx.report_configuration.template_info
        self._options = self._ctx.report_configuration.output_options
        self._proj = proj
        self._feedback = feedback
        self._layout = None
        self._messages = dict()
        self._jobs_layers = dict()

    @property
    def context(self) -> ReportTaskContext:
        """
        Returns the report task context used in the class.
        """
        return self._ctx

    @property
    def project(self) -> QgsProject:
        """
        Returns the QGIS project used for rendering the layers.
        """
        return self._proj

    @property
    def messages(self) -> dict:
        """
        Returns warning and information messages generated during the process.
        """
        return self._messages

    def _add_message(self, level, message):
        if level not in self.messages:
            self._messages[level] = []

        level_msgs = self._messages[level]
        level_msgs.append(message)

    def _add_warning_msg(self, msg):
        self._add_message(Qgis.Warning, msg)

    def _add_info_msg(self, msg):
        self._add_message(Qgis.Info, msg)

    def _process_cancelled(self) -> bool:
        # Check if there is a request to cancel the process, True to cancel.
        if self._feedback and self._feedback.isCanceled():
            return True

        return False

    def _create_layers(self, add_to_project=True):
        # Iterator the layers in each job.
        for j in self._ctx.jobs:
            layers = []
            bands = j.results.get_bands()
            for band_idx, band in enumerate(bands, start=1):
                if band.add_to_map:
                    layer_path = str(j.results.uri.uri)
                    band_info = JobBand.Schema().dump(band)
                    title = get_band_title(band_info)
                    layer = QgsRasterLayer(layer_path, title)
                    if layer.isValid():
                        layers.append(layer)

            # Just to ensure we don't have empty lists
            if len(layers) > 0:
                self._jobs_layers[j.id] = layers
                if add_to_project:
                    self._proj.addMapLayers(layers)

    def _export_layout(self) -> bool:
        """
        Export layout and template based on the settings defined in the
        options object.
        """
        if self._layout is None:
            return False

        rpt_path, temp_path = self._ctx.output_paths

        exporter = QgsLayoutExporter(self._layout)
        if self._options.output_format == OutputFormat.PDF:
            settings = QgsLayoutExporter.PdfExportSettings()
            res = exporter.exportToPdf(rpt_path, settings)
        else:
            settings = QgsLayoutExporter.ImageExportSettings()
            res = exporter.exportToImage(rpt_path, settings)

        if res != QgsLayoutExporter.Success:
            self._add_warning_msg('Failed to export the report.')
            return False

        # Export template if defined
        if self._options.include_qpt:
            status = self._layout.saveAsTemplate(
                temp_path,
                QgsReadWriteContext()
            )
            if not status:
                self._add_warning_msg('Failed to export template file.')
                return False

        return True

    def run(self) -> bool:
        """
        Start the report generation process.
        """
        if self._process_cancelled():
            return False

        # Confirm template paths exist
        pt_path, ls_path = self._ti.absolute_template_paths
        if not os.path.exists(pt_path) and not os.path.exists(ls_path):
            msg = 'Templates not found.'
            self._add_warning_msg(f'{msg}: {pt_path, ls_path}')
            return False

        # Create map layers
        self._create_layers()
        if len(self._jobs_layers) == 0:
            self._add_warning_msg('No map layers could be created.')
            return False

        # Determine orientation using first layer in our collection
        job_id = next(iter(self._jobs_layers))
        orientation_layer = self._jobs_layers[job_id][0]
        extent = orientation_layer.extent()
        w, h = extent.width(), extent.height()
        ref_temp_path = ls_path if w > h else pt_path

        if self._process_cancelled():
            return False

        self._layout = QgsPrintLayout(self._proj)
        status, document = self._get_template_document(ref_temp_path)
        if not status:
            return False

        _, load_status = self._layout.loadFromTemplate(
            document,
            QgsReadWriteContext()
        )
        if not load_status:
            self._add_warning_msg('Could not load template.')

        # Export layout
        if not self._export_layout():
            return False

        return True

    def _get_template_document(self, path) -> typing.Tuple[bool, QDomDocument]:
        # Get template contents
        template_file = QFile(path)
        try:
            if not template_file.open(QIODevice.ReadOnly):
                self._add_warning_msg(f'Cannot read \'{path}\'.')
                return False, None

            doc = QDomDocument()
            if not doc.setContent(template_file):
                self._add_warning_msg(
                    'Failed to parse template file contents.'
                )
                return False, None

        finally:
            template_file.close()

        return True, doc


class ReportGenerator(QObject):
    """
    Generates reports from job outputs using preset QGIS templates.
    """
    task_started = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.iface = None
        self._tasks = dict()

    @property
    def message_bar(self) -> QgsMessageBar:
        """Returns the main application's message bar."""
        if self.iface:
            return self.iface.messageBar()

        return None

    def _push_message(self, msg, level):
        if not self.message_bar:
            return

        self.message_bar.pushMessage(
            self.tr('Report Status'),
            msg,
            level
        )

    def _push_info_message(self, msg):
        self._push_message(msg, Qgis.Info)

    def _push_warning_message(self, msg):
        self._push_message(msg, Qgis.Warning)

    def _push_success_message(self, msg):
        self._push_message(msg, Qgis.Success)

    def write_context_to_file(self, ctx, task_id: str) -> str:
        # Write report task context to file.
        rpt_fi = QFileInfo(ctx.output_paths[0])
        output_dir = rpt_fi.dir().path()
        ctx_file_path = f'{output_dir}/report_{task_id}.json'

        # Check if there is an existing file
        if os.path.exists(ctx_file_path):
            return ctx_file_path

        # Check write permissions
        if not os.access(output_dir, os.W_OK):
            tr_msg = self.tr(
                'Cannot process report due to write permission to'
            )
            self._push_warning_message(f'{tr_msg} {output_dir}')
            return ''

        with open(ctx_file_path, 'w') as cf:
            ctx_data = ReportTaskContext.Schema().dump(ctx)
            json.dump(ctx_data, cf, indent=2)

        return ctx_file_path

    def process_report_task(self, ctx: ReportTaskContext) -> str:
        """
        Initiates report generation, emits 'task_started' signal and return
        the task id.
        """
        # Assert if qgis_process path could be found
        qgis_proc_path = qgis_process_path()
        if not qgis_proc_path:
            tr_msg = self.tr(
                'could not be found in your system. Unable to generate reports.'
            )
            self._push_warning_message(f'\'qgis_process\' {tr_msg}')
            return ''

        if len(ctx.jobs) == 1:
            task_id = str(ctx.jobs[0].id)
        else:
            task_id = uuid4()

        # Write task to file for subsequent use by the task
        file_path = self.write_context_to_file(ctx, task_id)
        tr_msg = self.tr(f'Submitted report task')
        self._push_info_message(f'{tr_msg} {task_id}')

        # Create report handler task
        rpt_handler_task = ReportProcessHandlerTask(
            file_path,
            task_id,
            qgis_proc_path
        )
        QgsApplication.instance().taskManager().addTask(rpt_handler_task)
        self._tasks[task_id] = rpt_handler_task

        self.task_started.emit()

        return task_id

    def task_status(self, task_id: str) -> TaskStatus:
        # Assumes task is in the tasks collection.
        pass

    def is_task_running(self, task_id: str) -> bool:
        # Check whether the task with the given id is running.
        if not task_id in self._tasks:
            return False

        return True


report_generator = ReportGenerator()





