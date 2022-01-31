# Processing algorithm for generating a report

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFile
)


class ReportTaskContextAlgorithm(QgsProcessingAlgorithm):
    """
    Takes a processing job in file and generates a report (and layout
    template) based on the task information. This is primarily executed in a
    qgis_process for best UI responsiveness (of the main thread) since it
    uses a QgsProject and QgsPrintLayout which are not thread safe.
    """
    NAME = 'trends.earth:reporttask'

    def tr(self, text) -> str:
        """
        Translates given text.
        """
        return QCoreApplication.translate('ReportTaskAlgorithm', text)

    def createInstance(self) -> 'ReportTaskContextAlgorithm':
        return ReportTaskContextAlgorithm()

    def name(self) -> str:
        return self.NAME

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

    def processAlgorithm(self, parameters, context, feedback) -> dict:
        # Extract task information and generate the report
        task_file_name = self.parameterAsFile(parameters, 'INPUT', context)
        status = True

        if feedback.isCanceled():
            return {}

        return {}

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagHideFromToolbox\
               | QgsProcessingAlgorithm.FlagNoThreading

