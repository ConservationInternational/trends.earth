import typing

import qgis.core


def log(message: str, level: typing.Optional[int] = 0):
    qgis.core.QgsMessageLog.logMessage(message, tag='trends.earth', level=level)
