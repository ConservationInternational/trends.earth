"""Report generator"""

from enum import Enum
import json
import os
import subprocess
import typing
from uuid import uuid4

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsExpression,
    QgsExpressionContext,
    QgsFeedback,
    QgsLayoutExporter,
    QgsLayoutItem,
    QgsPrintLayout,
    QgsProject,
    QgsRasterLayer,
    QgsReadWriteContext,
    QgsRectangle,
    QgsReferencedRectangle,
    QgsTask
)
from qgis.gui import (
    QgsMessageBar
)
from qgis.utils import iface

from qgis.PyQt.QtCore import (
    pyqtSignal,
    QCoreApplication,
    QDateTime,
    QFile,
    QFileInfo,
    QIODevice,
    QObject
)
from qgis.PyQt.QtXml import (
    QDomDocument
)

from te_schemas.results import Band as JobBand

from ..jobs.models import Job
from ..layers import (
    get_band_title,
    styles,
    style_layer
)
from ..logger import log

from .expressions import ReportExpressionUtils
from .models import (
    ReportTaskContext
)
from ..utils import (
    qgis_process_path,
    FileUtils
)


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
            qgis_proc_path: str,
            description
    ):
        super().__init__(description)
        self._ctx_file = ctx_file_path
        self._qgs_proc_path = qgis_proc_path
        self._completed_process = None

    @property
    def context_file(self) -> str:
        """
        Returns the path to the report context JSON file.
        """
        return self._ctx_file

    def run(self) -> bool:
        # Launch qgis_process and execute algorithm.
        input_file = f'INPUT={self._ctx_file}'
        args = [self._qgs_proc_path, 'run', 'trendsearth:reporttask', '--', input_file]
        self._completed_process = subprocess.run(
            args,
            shell=True
        )
        if self._completed_process.returncode == 0:
            return True

        return False

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

    def tr(self, message) -> str:
        return QCoreApplication.translate('ReportTaskProcessor', message)

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

    def _create_layers(self):
        # Creates layers in each job.
        for j in self._ctx.jobs:
            layers = []
            bands = j.results.get_bands()
            for band_idx, band in enumerate(bands, start=1):
                if band.add_to_map:
                    layer_path = str(j.results.uri.uri)
                    band_info = JobBand.Schema().dump(band)

                    # Get corresponding style
                    band_info_name = band_info['name']
                    band_style = styles.get(band_info_name, None)
                    if band_style is None:
                        self._add_warning_msg(
                            f'Styles for {band_info_name} not found for '
                            f'band {band_idx!s} in {layer_path}.'
                        )
                        continue

                    # Create raster layer and style it
                    title = get_band_title(band_info)
                    band_layer = QgsRasterLayer(layer_path, title)
                    if band_layer.isValid():
                        # Style layer
                        if style_layer(
                                layer_path,
                                band_layer,
                                band_idx,
                                band_style,
                                band_info,
                                in_process_alg=True,
                                processing_feedback=self._feedback
                        ):
                            layers.append(band_layer)

            # Just to ensure we don't have empty lists
            if len(layers) > 0:
                self._jobs_layers[j.id] = layers
                self._proj.addMapLayers(layers)

    def _export_layout(self) -> bool:
        """
        Export project, layout and template based on the settings defined
        in the options object.
        """
        if self._layout is None:
            return False

        rpt_paths = self._ctx.report_paths
        temp_path = self._ctx.template_path

        # Update project info so that they can be written to the output file
        self._update_project_metadata_extents()

        exporter = QgsLayoutExporter(self._layout)

        for rp in rpt_paths:
            if 'pdf' in rp:
                settings = QgsLayoutExporter.PdfExportSettings()
                res = exporter.exportToPdf(rp, settings)

            # Assume everything else is an image
            else:
                settings = QgsLayoutExporter.ImageExportSettings()
                res = exporter.exportToImage(rp, settings)

            if res != QgsLayoutExporter.Success:
                self._add_warning_msg(f'Failed to export report to {rp}.')

        # Export template if defined
        if self._options.include_qpt:
            status = self._layout.saveAsTemplate(
                temp_path,
                QgsReadWriteContext()
            )
            if not status:
                self._add_warning_msg('Failed to export template file.')
                return False

            # Add layout to project
            layout_mgr = self._proj.layoutManager()
            layout_mgr.addLayout(self._layout)

            #Add open project macro
            self._add_open_layout_macro()

            # Export project
            if len(rpt_paths) == 0:
                self._add_warning_msg(
                    'No report paths found, cannot save report project.'
                )
                return False

            proj_file = FileUtils.project_path_from_report_path(rpt_paths[0])
            self._proj.write(proj_file)

        return True

    def _update_project_metadata_extents(self):
        # Update the extents and metadata of the project before exporting
        template_info = self._ctx.report_configuration.template_info
        md = self._proj.metadata()
        md.setTitle(template_info.name)
        md.setAuthor('trends.earth QGIS Plugin')
        md.setAbstract(template_info.description)
        md.setCreationDateTime(QDateTime.currentDateTime())
        self._proj.setMetadata(md)

        # View settings
        all_layers_rect = QgsRectangle()
        for j in self._ctx.jobs:
            job_rect = self._get_job_layers_extent(j)
            all_layers_rect.combineExtentWith(job_rect)

        crs = QgsCoordinateReferenceSystem.fromEpsgId(4326)
        default_extent = QgsReferencedRectangle(all_layers_rect, crs)
        self._proj.viewSettings().setDefaultViewExtent(default_extent)

    def _add_open_layout_macro(self):
        # Add macro that open the layout when the project is opened.
        template_name = self._ti.name
        err_title = self.tr('Layout Error')
        err_msg_tr = self.tr('layout cannot be found')
        err_msg = f'{template_name} {err_msg_tr}'
        macro = f'from qgis.core import Qgis, QgsProject\r\nfrom qgis.utils ' \
                f'import iface\r\ndef openProject():\r\n\tlayout_mgr = ' \
                f'QgsProject.instance().layoutManager()\r\n\tlayout = ' \
                f'layout_mgr.layoutByName(\'{template_name}\')\r\n\t' \
                f'if layout is None:\r\n\t\tiface.messageBar().pushMessage' \
                f'(\'{err_title}\', \'{err_msg}\', Qgis.Warning, 10)\r\n\telse:' \
                f'\r\n\t\t_ = iface.openLayoutDesigner(layout)\r\n\r\n' \
                f'def saveProject():\r\n\tpass\r\n\r\ndef closeProject():' \
                f'\r\n\tpass\r\n'
        self._proj.writeEntry("Macros", "/pythonCode", macro)

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
        self._layout.setName(self._ti.name)

        status, document = self._get_template_document(ref_temp_path)
        if not status:
            return False

        _, load_status = self._layout.loadFromTemplate(
            document,
            QgsReadWriteContext()
        )
        if not load_status:
            self._add_warning_msg('Could not load template.')

        # Process scope items
        for j in self._ctx.jobs:
            self._process_scope_items(j)

        # Update custom report variables from the settings
        ReportExpressionUtils.register_report_settings_variables(self._layout)

        # Export layout
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

        # Map items
        map_ids = item_scope.map_ids()
        if len(map_ids) == 0:
            self._add_info_msg(f'No map ids found in \'{alg_name}\' scope.')
        if not self._update_map_items(map_ids, job):
            return False

        # Label items
        label_ids = item_scope.label_ids()
        if len(label_ids) == 0:
            self._add_info_msg(f'No label ids found in \'{alg_name}\' scope.')
        if not self._update_label_items(label_ids, job):
            return False

        return True

    def _update_map_items(self, map_ids, job) -> bool:
        # Update map items for the current job/scope
        job_layers = self._jobs_layers.get(job.id, None)
        if job_layers is None:
            return False

        extent = self._get_job_layers_extent(job)
        for mid in map_ids:
            map_item = self._layout.itemById(mid)
            if map_item is not None:
                map_item.setLayers(job_layers)
                map_item.zoomToExtent(extent)

        return True
    
    @classmethod
    def update_item_expression_ctx(
            cls, 
            item: QgsLayoutItem,
            job
    ) -> QgsExpressionContext:
        # Update the expression context based on the given job.
        item_exp_ctx = item.createExpressionContext()

        return ReportExpressionUtils.update_job_expression_context(
            item_exp_ctx,
            job
        )

    def _update_label_items(self, labels_ids, job) -> bool:
        # Evaluate expressions for label items matching the given ids.
        for lid in labels_ids:
            label_item = self._layout.itemById(lid)
            if label_item is not None:
                lbl_exp_ctx = self.update_item_expression_ctx(
                    label_item,
                    job
                )
                evaluated_txt = QgsExpression.replaceExpressionText(
                    label_item.text(),
                    lbl_exp_ctx
                )
                label_item.setText(evaluated_txt)

    def _get_job_layers_extent(self, job) -> QgsRectangle:
        # Get the combined extent of all the layers for the given job.
        rect = QgsRectangle()
        job_layers = self._jobs_layers.get(job.id, None)
        if job_layers is None:
            return rect

        for l in job_layers:
            rect.combineExtentWith(l.extent())

        return rect

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
    Generates reports for single or multi-datasets based on custom layouts.
    """
    task_started = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.iface = iface

        # key: ReportTaskContext, value: QgsTask id
        self._submitted_tasks = dict()
        QgsApplication.instance().taskManager().statusChanged.connect(
            self.on_task_status_changed
        )

    @property
    def message_bar(self) -> QgsMessageBar:
        """Returns the main application's message bar."""
        if self.iface is None:
            self.iface = iface

        return self.iface.messageBar()

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

    def _write_context_to_file(self, ctx, task_id: str) -> str:
        # Write report task context to file.
        rpt_fi = QFileInfo(ctx.report_paths[0])
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
        the submission result.
        """
        # If task is already in list of submissions then return
        if self.is_task_running(ctx):
            return False

        # Assert if qgis_process path could be found
        qgis_proc_path = qgis_process_path()
        if not qgis_proc_path:
            tr_msg = self.tr(
                'could not be found in your system. Unable to generate reports.'
            )
            self._push_warning_message(f'\'qgis_process\' {tr_msg}')
            return False

        if len(ctx.jobs) == 1:
            file_suffix = str(ctx.jobs[0].id)
        else:
            file_suffix = uuid4()

        # Write task to file for subsequent use by the report handler task
        file_path = self._write_context_to_file(ctx, file_suffix)

        ctx_display_name = ctx.display_name()

        # Create report handler task
        rpt_handler_task = ReportProcessHandlerTask(
            file_path,
            qgis_proc_path,
            ctx_display_name
        )
        task_id = QgsApplication.instance().taskManager().addTask(
            rpt_handler_task
        )

        self._submitted_tasks[ctx] = task_id

        # Notify user
        tr_msg = self.tr(f'report is being processed...')
        self._push_info_message(f'{ctx_display_name} {tr_msg}')

        return True

    @classmethod
    def task_status(cls, task_id: str) -> QgsTask.TaskStatus:
        # Returns -1 if the task with the given id could not be found.
        task = QgsApplication.instance().taskManager().task(task_id)
        if not task:
            return -1

        return task.status()

    def is_task_running(self, ctx: ReportTaskContext) -> bool:
        # Check whether the task with the given id is running.
        if ctx not in self._submitted_tasks:
            return False

        return True

    def handler_task_from_context(
            self,
            ctx: ReportTaskContext
    ) -> ReportProcessHandlerTask:
        # Retrieves the handler task corresponding to the given context.
        task_id = self._submitted_tasks.get(ctx, -1)
        if task_id == -1:
            return None

        return QgsApplication.instance().taskManager().task(task_id)

    def remove_task_context(self, ctx: ReportTaskContext) -> bool:
        """
        Remove the task context from the list of submitted tasks. If not
        complete, the task will be cancelled.
        """
        if not self.is_task_running(ctx):
            return False

        handler = self.handler_task_from_context(ctx)
        if handler is None:
            return False

        if handler.status() != QgsTask.Complete or \
                handler.status() != QgsTask.Terminated:
            handler.cancel()

        _ = self._submitted_tasks.pop(ctx)

    def task_context_by_id(self, task_id: int) -> ReportTaskContext:
        """
        Returns the ReportTaskContext in submitted jobs based on the
        QgsTask id.
        """
        ctxs = [
            ctx for ctx, tid in self._submitted_tasks.items()
            if tid == task_id
        ]
        if len(ctxs) == 0:
            return None

        return ctxs[0]

    def on_task_status_changed(
            self,
            task_id:int,
            status: QgsTask.TaskStatus
    ):
        # Slot raised when the status of a task has changed.
        ctx = self.task_context_by_id(task_id)
        if ctx is None:
            return

        if status != QgsTask.Complete or status != QgsTask.Terminated:
            return

        ctx_name = ctx.display_name()
        if status == QgsTask.Complete:
            tr_msg = self.tr('report is ready!')
            msg = f'{ctx_name} {tr_msg}'
            self._push_success_message(msg)
        elif status == QgsTask.Terminated:
            tr_msg = f'report could not be generated. See log file ' \
                     f'for details.'
            msg = f'{ctx_name} {tr_msg}'
            self._push_warning_message(msg)

        # Remove from list of submitted tasks
        self.remove_task_context(ctx)


report_generator = ReportGenerator()





