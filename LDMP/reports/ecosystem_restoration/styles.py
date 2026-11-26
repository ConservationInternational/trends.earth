from qgis.PyQt.QtCore import QCoreApplication, QObject


class tr_ecosystem_restoration(QObject):
    def tr(self, txt):
        return QCoreApplication.translate(self.__class__.__name__, txt)


tr_ecosystem_restoration = tr_ecosystem_restoration()

TARGET_COLOR = "#18365D"
REPORTED_COLOR = "#02A6A6"
SPATIAL_COLOR = "#66A61E"
TEXT_COLOR = "#2A2A2A"
AXIS_COLOR = "#2A2A2A"
GRID_COLOR = "#DCDCDC"
FONT_FAMILY = "DejaVu Sans, Arial, Helvetica, sans-serif"
