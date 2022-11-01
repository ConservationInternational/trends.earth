import os
from pathlib import Path

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .carbon import TCSummary
from .report import ReportTaskContextAlgorithm
from .utilities import ClipRaster
from .utilities import GenerateMask

ICON_PATH = os.path.join(os.path.dirname(__file__), "icons")


class Provider(QgsProcessingProvider):
    def loadAlgorithms(self, *args, **kwargs):
        self.addAlgorithm(TCSummary())
        self.addAlgorithm(GenerateMask())
        self.addAlgorithm(ClipRaster())
        self.addAlgorithm(ReportTaskContextAlgorithm())

    def id(self, *args, **kwargs):
        return "trendsearth"

    def name(self, *args, **kwargs):
        return self.tr("Trends.Earth")

    def icon(self):
        """Should return a QIcon which is used for your provider inside
        the Processing toolbox.
        """
        return QIcon(os.path.join(ICON_PATH, "trends_earth_logo_square_32x32.png"))
