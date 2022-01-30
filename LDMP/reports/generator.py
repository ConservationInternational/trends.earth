"""Report generator"""

from enum import Enum
import os
import typing
from uuid import uuid4

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsLayoutExporter,
    QgsPrintLayout,
    QgsProject,
    QgsRasterLayer,
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

from te_schemas.results import Band as JobBand

from ..jobs.models import Job
from ..layers import get_band_title, styles
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
        self._is_layout_orientation_set = False
        self.messages = dict()

    def run(self) -> bool:
        # Confirm template paths exist
        pt_path, ls_path = self._ti.absolute_template_paths
        if not os.path.exists(pt_path) and not os.path.exists(ls_path):
            msg = 'Templates not found.'
            self._add_warning_msg(f'{msg}: {pt_path, ls_path}')
            return False

        # Determine orientation

        proj = QgsProject()
        proj.setFileName('D:/Dev/QGIS/QgsProject/TestLoad.qgs')
        # QgsProject.setInstance(proj)
        self._layout = QgsPrintLayout(proj)
        # Load template
        status, document = self._get_template_document(pt_path)
        if not status:
            return False

        _, load_status = self._layout.loadFromTemplate(
            document,
            QgsReadWriteContext()
        )
        if not load_status:
            self._add_warning_msg('Could not load template.')

        # Process jobs
        for j in self._ctx.jobs:
            self._process_scope_items(j)

        if not self._export_layout():
            return False

        return True

    def _process_scope_items(self, job: Job) -> bool:
        # Update layout items in the given scope
        alg_name = job.script.name
        scope_mappings = self._ti.scope_mappings_by_name(alg_name)
        if len(scope_mappings) == 0:
            self._add_warning_msg(
                f'Could not find \'{alg_name}\' scope definition.'
            )
            return False

        item_scope = scope_mappings[0]
        map_ids = item_scope.map_ids()
        if len(map_ids) == 0:
            self._add_info_msg(f'No map ids found in \'{alg_name}\' scope.')

        self._update_map_items(map_ids, job)

        return True

    def _update_map_items(self, map_ids: typing.List[str], job: Job):
        # Update map items
        # Create layer set
        layers = []
        bands = job.results.get_bands()
        for band_idx, band in enumerate(bands, start=1):
            if band.add_to_map:
                layer_path = str(job.results.uri.uri)
                band_info = JobBand.Schema().dump(band)
                title = get_band_title(band_info)
                layer = QgsRasterLayer(layer_path, title)
                layers.append(layer)

        for mid in map_ids:
            map_item = self._layout.itemById(mid)
            if map_item is not None:
                map_item.setLayers(layers)
                map_item.refresh()

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





