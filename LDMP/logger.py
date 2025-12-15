import typing

import qgis.core
from qgis.PyQt.QtCore import QTimer


def log(message: str, level: typing.Optional[int] = 0):
    """
    Thread-safe logging function that can be called from any thread.
    Uses QTimer.singleShot to ensure logging happens on the main thread.
    This prevents segfaults when called from background threads on Windows.
    """
    # Use QTimer.singleShot with 0ms delay to queue the log message on the main thread
    QTimer.singleShot(
        0,
        lambda: qgis.core.QgsMessageLog.logMessage(
            message, tag="trends.earth", level=level
        ),
    )
