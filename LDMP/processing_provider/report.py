# Processing algorithm for generating a report

import json
import os

from qgis.PyQt.QtCore import (
    QCoreApplication
)
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingOutputBoolean,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProcessingParameterFile,
    QgsProject
)


from ..reports.generator import ReportTaskProcessor
from ..reports.models import ReportTaskContext

from ..utils import FileUtils


class ReportTaskContextAlgorithm(QgsProcessingAlgorithm):
    """
    Takes a processing job in file and generates a report (and layout
    template) based on the task information. This is primarily executed in a
    qgis_process for best UI responsiveness (of the main thread) since it
    uses a QgsProject and QgsPrintLayout which are not thread safe.
    """
    NAME = 'reporttask'

    def tr(self, text) -> str:
        """
        Translates given text.
        """
        return QCoreApplication.translate('ReportTaskAlgorithm', text)

    def createInstance(self) -> 'ReportTaskContextAlgorithm':
        return ReportTaskContextAlgorithm()

    def name(self) -> str:
        return self.NAME

    def shortHelpString(self) -> str:
        return self.tr(
            'Runs a report generation task based on information provided '
            'in a JSON file.'
        )

    def displayName(self) -> str:
        return self.tr('Generate Report from Task')

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                'INPUT',
                self.tr('File containing report context task information'),
                QgsProcessingParameterFile.File,
                'json'
            )
        )

        self.addOutput(
            QgsProcessingOutputBoolean(
                'STATUS',
                self.tr('Summary result status of the algorithm.')
            )
        )

    def processAlgorithm(
            self,
            parameters: dict,
            context: QgsProcessingContext,
            feedback: QgsProcessingFeedback
    ) -> dict:
        # Extract task information and generate the report
        status = False
        task_file_name = self.parameterAsFile(parameters, 'INPUT', context)

        if feedback.isCanceled():
            return {'STATUS': status}

        if not os.path.exists(task_file_name):
            feedback.pushConsoleInfo(self.tr('Task file not found.'))
            return {'STATUS': status}

        rpt_task_ctx = None
        with open(task_file_name) as rtf:
            ctx_data = json.load(rtf)
            rpt_task_ctx = ReportTaskContext.Schema().load(ctx_data)

        if rpt_task_ctx is None:
            feedback.pushConsoleInfo(
                self.tr('Could not read report task context file')
            )
            return {'STATUS': status}

        # Update template paths
        rpt_task_ctx.report_configuration.template_info.update_paths(
            FileUtils.report_templates_dir()
        )

        proj = context.project()
        if proj is None:
            proj = QgsProject().instance()

        # Create report processor
        rpt_processor = ReportTaskProcessor(
            rpt_task_ctx,
            proj,
            feedback
        )
        status = rpt_processor.run()

        return {'STATUS': status}

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading | \
               QgsProcessingAlgorithm.FlagHideFromModeler | \
               QgsProcessingAlgorithm.FlagHideFromToolbox

