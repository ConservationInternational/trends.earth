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
    QgsLayerDefinition,
    QgsLayoutExporter,
    QgsLayoutItem,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemRegistry,
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
    ReportTaskContext,
    TemplateType
)
from .utils import build_report_paths
from ..utils import (
    qgis_process_path,
    FileUtils
)
from ..visualization import download_base_map


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
        self._ctx_file_path = ctx_file_path
        self._qgs_proc_path = qgis_proc_path
        self._completed_process = None

    @property
    def context_file_path(self) -> str:
        """
        Returns the path to the report context JSON file.
        """
        return self._ctx_file_path

    def run(self) -> bool:
        # Launch qgis_process and execute algorithm.
        if self.isCanceled():
            return False

        input_file = f'INPUT={self._ctx_file_path}'
        args = [
            self._qgs_proc_path, 'run', 'trendsearth:reporttask',
            '--', input_file
        ]
        self._completed_process = subprocess.run(
            args,
            shell=True
        )
        if self._completed_process.returncode == 0:
            return True

        return False

    def finished(self, result):
        # Remove context file if process run was successful.
        log(f'Report handler report: {result!s}')
        if result:
            ctx_file = QFile(self._ctx_file_path)
            status = ctx_file.remove()
            log(f'Remove status of report task file: {status!s}')


class ReportTaskProcessor:
    """
    Produces a QGIS project, template and resulting report
    (in image and/or PDF format) based on information in a
    ReportTaskContext object.
    """
    BAND_INDEX = 'sourceBandIndex'

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
        self._should_add_basemap = True
        self._basemap_layers = []
        self._output_root_dir = ''

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
        # Creates map layers for each job.
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
                            # Append source band index as a custom property.
                            # We use this to retrieve the corresponding report
                            # path.
                            band_layer.setCustomProperty(
                                self.BAND_INDEX,
                                band_idx
                            )
                            layers.append(band_layer)

            # Just to ensure that we don't have empty lists
            if len(layers) > 0:
                self._jobs_layers[j.id] = layers
                self._proj.addMapLayers(layers)

        # Add basemap
        if self._should_add_basemap:
            self._add_base_map()

    def _add_base_map(self):
        # Add basemap
        status, document = download_base_map(use_mask=False)
        if status:
            root = self._proj.layerTreeRoot().insertGroup(0, 'Basemap')
            QgsLayerDefinition.loadLayerDefinition(
                document,
                self._proj,
                root,
                QgsReadWriteContext()
            )

            # Get associated child layers
            child_layers = root.findLayers()
            for cl in child_layers:
                self._basemap_layers.append(cl.layer())

    def _save_project(self) -> bool:
        # Save project file to disk.
        if not self._output_root_dir:
            self._add_warning_msg(
                'Root output directory could not be determined. The project '
                'could not be saved.'
            )
            return False

        # Add open project macro to show layout manager.
        self._add_open_layout_macro()

        proj_file = FileUtils.project_path_from_report_task(
            self._ctx,
            self._output_root_dir
        )
        self._proj.write(proj_file)

    def _export_layout(self, report_path, name) -> bool:
        """
        Export layout to the given file path.
        """
        if self._layout is None:
            return False

        self._layout.setName(name)

        #self._update_project_metadata_extents()

        exporter = QgsLayoutExporter(self._layout)
        if 'pdf' in report_path:
            settings = QgsLayoutExporter.PdfExportSettings()
            res = exporter.exportToPdf(report_path, settings)

        # Assume everything else is an image
        else:
            settings = QgsLayoutExporter.ImageExportSettings()
            res = exporter.exportToImage(report_path, settings)

        if res != QgsLayoutExporter.Success:
            self._add_warning_msg(
                f'Failed to export report to {report_path}.'
            )

        # Add layout to project
        layout_mgr = self._proj.layoutManager()
        layout_mgr.addLayout(self._layout)

        return True

    def _update_project_metadata_extents(self, layer=None, title=None):
        # Update the extents and metadata of the project
        description = ''
        if layer is None:
            template_info = self._ctx.report_configuration.template_info
            title = template_info.name
            description = template_info.description
            proj_extent = QgsRectangle()
            for j in self._ctx.jobs:
                job_rect = self._get_job_layers_extent(j)
                proj_extent.combineExtentWith(job_rect)
        else:
            title = title or ''
            proj_extent = layer.extent()

        md = self._proj.metadata()
        md.setTitle(title)
        md.setAuthor('trends.earth QGIS Plugin')
        md.setAbstract(description)
        md.setCreationDateTime(QDateTime.currentDateTime())
        self._proj.setMetadata(md)

        # View settings
        crs = QgsCoordinateReferenceSystem.fromEpsgId(4326)
        default_extent = QgsReferencedRectangle(proj_extent, crs)
        self._proj.viewSettings().setDefaultViewExtent(default_extent)

    def _add_open_layout_macro(self):
        # Add macro that shows the layout manager when the project is opened.
        macro = 'from qgis.utils import iface\r\ndef openProject():' \
                '\r\n\tiface.showLayoutManager()\r\n\r\n' \
                'def saveProject():\r\n\tpass\r\n\r\n' \
                'def closeProject():\r\n\tpass\r\n'
        self._proj.writeEntry("Macros", "/pythonCode", macro)

    def run(self) -> bool:
        """
        Initiate the report generation process.
        """
        if self._process_cancelled():
            return False

        # Get template paths
        abs_paths = self._ti.absolute_template_paths
        simple_pt_path = abs_paths.simple_portrait
        simple_ls_path = abs_paths.simple_landscape
        full_pt_path = abs_paths.full_portrait
        full_ls_path = abs_paths.full_landscape

        # Check if the templates exist depending on user configuration
        # Simple layout
        if self._options.template_type == TemplateType.SIMPLE \
                or self._options.template_type == TemplateType.ALL:
            if not abs_paths.simple_landscape_exists() \
                    and not abs_paths.simple_portrait_exists():
                msg = 'Simple report templates not found.'
                self._add_warning_msg(
                    f'{msg}: {simple_pt_path, simple_ls_path}'
                )
                return False

        # Full layout
        if self._options.template_type == TemplateType.FULL \
                or self._options.template_type == TemplateType.ALL:
            if not abs_paths.full_portrait_exists() \
                    and not abs_paths.full_landscape_exists():
                msg = 'Full report templates not found.'
                self._add_warning_msg(
                    f'{msg}: {full_pt_path, full_ls_path}'
                )
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
        use_landscape = True if w > h else False
        ref_simple_temp = simple_ls_path if use_landscape else simple_pt_path
        ref_full_temp = full_ls_path if use_landscape else full_pt_path

        if self._process_cancelled():
            return False

        # Simple
        if self._options.template_type == TemplateType.SIMPLE \
                or self._options.template_type == TemplateType.ALL:
            self._generate_reports(ref_simple_temp, True)

        if self._process_cancelled():
            return False

        # Full
        if self._options.template_type == TemplateType.FULL \
                or self._options.template_type == TemplateType.ALL:
            self._generate_reports(ref_full_temp, False)

        # Update general metadata and save project
        self._update_project_metadata_extents()
        self._save_project()

        return True

    def _generate_reports(
            self,
            template_path: str,
            is_simple: bool
    ) -> bool:
        # Creates layout and generates reports based on the given template
        self._layout = QgsPrintLayout(self._proj)

        status, document = self._get_template_document(template_path)
        if not status:
            return False

        _, load_status = self._layout.loadFromTemplate(
            document,
            QgsReadWriteContext()
        )
        if not load_status:
            self._add_warning_msg(
                f'Could not load template: {template_path}.'
            )
            return False

        # Key for fetching report output path
        report_path_key = 'simple' if is_simple else 'full'

        # Process scope items for each job
        for job in self._ctx.jobs:
            # Layers are the basis of the layout with a 1:1 mapping
            job_layers = self._jobs_layers.get(job.id, None)
            if job_layers is None:
                continue

            rpt_root_dir, job_report_paths = build_report_paths(
                job,
                self._options,
                self._ctx.root_report_dir
            )
            # Set root output directory
            if not self._output_root_dir:
                self._output_root_dir = rpt_root_dir

            for jl in job_layers:
                '''
                (re)load layout and load the template. It would have been 
                better to clone the layout object but we will lose the 
                expressions in the label items.
                '''
                if not self._create_layout(template_path):
                    return False

                # Update layout items
                if not self._process_scope_items(job, jl):
                    continue

                # Update custom report variables from the settings
                ReportExpressionUtils.register_report_settings_variables(
                    self._layout
                )

                # Fetch report output path
                band_idx = jl.customProperty(self.BAND_INDEX, -1)
                if band_idx == -1:
                    continue
                if band_idx not in job_report_paths:
                    continue
                band_paths = job_report_paths[band_idx]
                rpt_paths = band_paths.get(report_path_key, '')
                if len(rpt_paths) == 0:
                    continue

                layout_name = f'{report_path_key.capitalize()} - {jl.name()}'

                # Update project metadata (relevant for PDF or SVG document
                # properties)
                self._update_project_metadata_extents(jl, layout_name)

                # Export layout based on file types in report paths list
                for rp in rpt_paths:
                    self._export_layout(rp, layout_name)

        return True

    def _create_layout(self, template_path: str) -> bool:
        # Creates a new instance of the print layout and loads items in the
        # given template.
        self._layout = QgsPrintLayout(self._proj)

        status, document = self._get_template_document(template_path)
        if not status:
            return False

        _, load_status = self._layout.loadFromTemplate(
            document,
            QgsReadWriteContext()
        )
        if not load_status:
            self._add_warning_msg(
                f'Could not load template from {template_path!r}.'
            )
            return False

        return True

    def _process_scope_items(
            self,
            job: Job,
            job_layer: QgsRasterLayer
    ) -> bool:
        # Update layout items in the given scope/job
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
        if not self._update_map_items(map_ids, job_layer):
            return False

        # Label items
        label_ids = item_scope.label_ids()
        if len(label_ids) == 0:
            self._add_info_msg(f'No label ids found in \'{alg_name}\' scope.')
        if not self._update_label_items(label_ids, job):
            return False

        return True

    def _update_map_items(self, map_ids, layer: QgsRasterLayer) -> bool:
        # Update map items with the given layer
        map_item_layers = []
        map_item_layers.extend(self._basemap_layers)
        map_item_layers.append(layer)
        for mid in map_ids:
            map_item = self._layout.itemById(mid)
            if map_item is not None:
                map_item.setLayers(map_item_layers)
                map_item.zoomToExtent(layer.extent())
                # self._refresh_map_legends(map_item)

        return True

    def _refresh_map_legends(self, map_item: QgsLayoutItemMap):
        # Refresh legend items linked to the given map item to only show the
        # visible layers in the map item.
        if self._layout is None:
            return

        layout_model = self._layout.itemsModel()
        for i in range(1, layout_model.rowCount()):
            item_idx = layout_model.index(i, 0)
            item = layout_model.itemFromIndex(item_idx)
            if item.type() == QgsLayoutItemRegistry.LayoutLegend:
                if item.linkedMap().uuid() == map_item.uuid():
                    item.setLegendFilterByMapEnabled(True)
                    self._remove_base_map_legend_items(item)

    def _remove_base_map_legend_items(self, legend: QgsLayoutItemLegend):
        # Remove basemap nodes so that we only have band entries.
        model = legend.model()
        layer_root = self._proj.layerTreeRoot()
        for base_layer in self._basemap_layers:
            layer_node = layer_root.findLayer(base_layer)
            if layer_node is not None:
                base_layer_index = model.node2index(layer_node)
                if not base_layer_index.isValid():
                    continue
                model.removeRow(
                    base_layer_index.row(),
                    base_layer_index.parent()
                )

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

        return True

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


class ReportGeneratorManager(QObject):
    """
    Generates reports for single or multi-datasets based on custom layouts.
    """
    task_started = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.iface = iface
        self._qgis_proc_path = qgis_process_path()

        # key: ReportTaskContext, value: QgsTask id
        self._submitted_tasks = dict()
        '''
        QgsApplication.instance().taskManager().statusChanged.connect(
            self.on_task_status_changed
        )
        '''

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
        if ctx.root_report_dir is not None:
            root_dir = ctx.root_report_dir
        else:
            jobs = ctx.jobs
            if len(jobs) == 0:
                return ''
            root_dir, _ = build_report_paths(
                jobs[0],
                ctx.report_configuration.output_options
            )
        ctx_file_path = f'{root_dir}/report_{task_id}.json'

        # Check if there is an existing file
        if os.path.exists(ctx_file_path):
            return ctx_file_path

        # Check write permissions
        if not os.access(root_dir, os.W_OK):
            tr_msg = self.tr(
                'Cannot process report due to write permission to'
            )
            self._push_warning_message(f'{tr_msg} {root_dir}')
            return ''

        with open(ctx_file_path, 'w') as cf:
            ctx_data = ReportTaskContext.Schema().dump(ctx)
            json.dump(ctx_data, cf, indent=2)

        return ctx_file_path

    def process_report_task(self, ctx: ReportTaskContext) -> bool:
        """
        Initiates report generation, emits 'task_started' signal and return
        the submission result.
        """
        # If task is already in list of submissions then return
        if self.is_task_running(ctx):
            return False

        # Assert if qgis_process path could be found
        if not self._qgis_proc_path:
            tr_msg = self.tr(
                'could not be found in your system. Unable to run the '
                'report generator.'
            )
            self._push_warning_message(f'\'qgis_process\' {tr_msg}')
            return False

        if len(ctx.jobs) == 1:
            file_suffix = str(ctx.jobs[0].id)
        else:
            file_suffix = uuid4()

        # Write task file for subsequent use by the report handler task
        file_path = self._write_context_to_file(ctx, file_suffix)

        ctx_display_name = ctx.display_name()

        # Create report handler task
        rpt_handler_task = ReportProcessHandlerTask(
            file_path,
            self._qgis_proc_path,
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

        # Only interested in terminated or completed tasks
        if status != QgsTask.Complete and status != QgsTask.Terminated:
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


report_generator_manager = ReportGeneratorManager()





