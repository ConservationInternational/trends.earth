# Processing algorithm for generating a report
import json
import os
from datetime import datetime

from qgis.core import QgsProcessingAlgorithm
from qgis.core import QgsProcessingContext
from qgis.core import QgsProcessingFeedback
from qgis.core import QgsProcessingOutputBoolean
from qgis.core import QgsProcessingParameterFile
from qgis.core import QgsProject
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtCore import QFileInfo

from ..conf import Setting
from ..conf import settings_manager
from ..reports.generator import ReportTaskProcessor
from ..reports.models import ReportTaskContext


class ReportTaskContextAlgorithm(QgsProcessingAlgorithm):
    """
    Takes a processing job in file and generates a report (and layout
    template) based on the task information. This is primarily executed in a
    qgis_process for best UI responsiveness (of the main thread) since it
    uses a QgsProject and QgsPrintLayout which are not thread safe.
    """

    NAME = "reporttask"

    def tr(self, text) -> str:
        """
        Translates given text.
        """
        return QCoreApplication.translate("ReportTaskAlgorithm", text)

    def createInstance(self) -> "ReportTaskContextAlgorithm":
        return ReportTaskContextAlgorithm()

    def name(self) -> str:
        return self.NAME

    def shortHelpString(self) -> str:
        return self.tr(
            "Runs a report generation task based on information provided "
            "in a JSON file."
        )

    def displayName(self) -> str:
        return self.tr("Generate Report from Task")

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFile(
                "INPUT",
                self.tr("File containing report context task information"),
                QgsProcessingParameterFile.File,
                "json",
            )
        )

        self.addOutput(
            QgsProcessingOutputBoolean(
                "STATUS", self.tr("Summary result status of the algorithm.")
            )
        )

    def processAlgorithm(
        self,
        parameters: dict,
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict:
        # Extract task information and generate the report
        status = False
        task_file_name = self.parameterAsFile(parameters, "INPUT", context)

        if feedback.isCanceled():
            return {"STATUS": status}

        if not os.path.exists(task_file_name):
            feedback.pushConsoleInfo(self.tr("Task file not found."))
            return {"STATUS": status}

        rpt_task_ctx = None
        with open(task_file_name) as rtf:
            ctx_data = json.load(rtf)
            rpt_task_ctx = ReportTaskContext.Schema().load(ctx_data)

        if rpt_task_ctx is None:
            feedback.pushConsoleInfo(self.tr("Could not read report task context file"))
            return {"STATUS": status}

        # Update template paths
        base_dir = settings_manager.get_value(Setting.BASE_DIR)
        data_temp_dir = f"{base_dir}/reports/templates"
        user_temp_dir = settings_manager.get_value(Setting.REPORT_TEMPLATE_SEARCH_PATH)
        rpt_task_ctx.report_configuration.template_info.update_paths(
            data_temp_dir, user_temp_dir
        )

        proj = context.project()
        if proj is None:
            proj = QgsProject().instance()

        # Create report processor
        rpt_processor = ReportTaskProcessor(rpt_task_ctx, proj, feedback)
        status = rpt_processor.run()

        self.save_log_file(task_file_name, feedback)

        return {"STATUS": status}

    @classmethod
    def save_log_file(cls, task_path: str, feedback: QgsProcessingFeedback):
        # Save warning messages in a log file.
        # Check if user has enabled log messages
        log_warnings = settings_manager.get_value(Setting.REPORT_LOG_WARNING)
        if not log_warnings:
            return

        task_file_info = QFileInfo(task_path)
        task_dir_path = task_file_info.dir().path()

        # Append current date/time
        dt_str = datetime.now().strftime("%Y%m%d%H%M%S")

        log_file_path = f"{task_dir_path}/warning_logs_{dt_str}.html"

        # Check write permissions
        if not os.access(task_dir_path, os.W_OK):
            feedback.pushConsoleInfo(
                f"User does not have write permissions for {log_file_path}"
            )
            return

        html_log = feedback.htmlLog()
        # If there are no errors/warnings then indicate this in the log file
        if len(html_log) == 0:
            html_log = "No warnings or errors to report. Process was successful."

        with open(log_file_path, "w") as lf:
            lf.write(html_log)

    def flags(self):
        """
        Will be flagged as a deprecated algorithm due to hiding from
        modeler and toolbox.
        """
        return (
            super().flags()
            | QgsProcessingAlgorithm.FlagNoThreading
            | QgsProcessingAlgorithm.FlagHideFromModeler
            | QgsProcessingAlgorithm.FlagHideFromToolbox
        )
