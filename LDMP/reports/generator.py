"""Report generator"""

from enum import Enum
import os
import typing
from uuid import uuid4

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsLayout,
    QgsLayoutExporter,
    QgsProject,
    QgsReadWriteContext,
    QgsTask
)
from qgis.PyQt.QtCore import (
    pyqtSignal,
    QFile,
    QIODevice,
    QObject
)
from qgis.PyQt.QtXml import (
    QDomDocument
)

from ..logger import log

from .models import (
    OutputFormat,
    ReportTaskContext
)
from .utils import (
    build_report_name,
    build_template_name
)


class TaskStatus(Enum):
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'
    PENDING = 'pending'
    STARTED = 'started'


class ReportTask(QgsTask):
    def __init__(self, task_id: str, ctx: ReportTaskContext):
        super().__init__(f'Report task {task_id}')
        self._status = TaskStatus.PENDING
        self._ctx = ctx
        self._ti = self._ctx.report_configuration.template_info
        self._options = self._ctx.report_configuration.output_options
        self._task_id = task_id
        self._layout = None
        self.messages = dict()

    def run(self) -> bool:
        # Confirm template paths exist
        pt_path, ls_path = self._ti.absolute_template_paths
        if not os.path.exists(pt_path) and not os.path.exists(ls_path):
            msg = 'Templates not found.'
            self._add_warning_msg(f'{msg}: {pt_path, ls_path}')

            return False

        # Determine orientation

        self._layout = QgsLayout(QgsProject.instance())
        # Load template
        status, document = self._get_template_document(pt_path)
        if not status:
            return False

        load_status = self._layout.loadFromTemplate(
            document,
            QgsReadWriteContext()
        )
        if not load_status:
            self._add_warning_msg('Could not load template.')

        if not self._export_layout():
            return False

        return True

    def _get_template_document(self, path) -> typing.Tuple[bool, QDomDocument]:
        # Load template to the given layout
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

    def finished(self, result):
        # Even though QgsMessageLogger is thread safe, it is preferable to
        # log messages once the task has finished.
        for level, msgs in self.messages.items():
            for msg in msgs:
                log(msg, level)

        # Summarize
        desc = self.description()
        if result:
            log(f'{desc} ran successfully!')
        else:
            log(
                f'{desc} failed. See preceding logs for '
                f'details.', Qgis.Warning
            )

    def _add_message(self, level, message):
        if level not in self.messages:
            self.messages[level] = []

        level_msgs = self.messages[level]
        level_msgs.append(f'{self.description()}: {message}')

    def _add_warning_msg(self, msg):
        self._add_message(Qgis.Warning, msg)

    def _add_info_msg(self, msg):
        self._add_message(Qgis.Info, msg)

    def _export_layout(self) -> bool:
        """
        Export layout and template based on the settings defined in the
        options object.
        """
        if self._layout is None:
            return False

        # Report path. Need to refactor for multiscope reports
        rpt_name, rpt_path = build_report_name(self._ctx.jobs[0], self._options)

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
            # Need to refactor
            temp_name, temp_dir = build_template_name(self._ctx.jobs[0])
            self._add_info_msg(temp_dir)
            status = self._layout.saveAsTemplate(
                temp_dir,
                QgsReadWriteContext()
            )
            if not status:
                self._add_warning_msg('Could not export template file.')
                return False

        return True

    @property
    def layout(self):
        """
        Returns the layout produced by the task. It should be accessed
        after the task has finished otherwise it will return None.
        """
        return self._layout

    @property
    def id(self) -> str:
        """Returns the task id."""
        return self._task_id


class ReportGenerator(QObject):
    """
    Generates reports from job outputs using preset QGIS templates.
    """
    task_started = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks = dict()

    def process_report_task(self, ctx: ReportTaskContext) -> str:
        """
        Initiates report generation, emits 'task_started' signal and return
        the task id.
        """
        if len(ctx.jobs) == 1:
            task_id = str(ctx.jobs[0].id)
        else:
            task_id = uuid4()

        rpt_task = ReportTask(task_id, ctx)
        self._tasks[task_id] = rpt_task
        QgsApplication.instance().taskManager().addTask(rpt_task)
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





