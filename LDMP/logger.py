import typing

import qgis.core
from qgis.core import Qgis
from qgis.PyQt.QtCore import QTimer


def to_message_level(level: int):
    """Convert int level to Qgis.MessageLevel enum for QGIS 4."""
    try:
        return Qgis.MessageLevel(level)
    except (TypeError, AttributeError):
        return level


def log(message: str, level: typing.Optional[int] = 0):
    """
    Thread-safe logging function that can be called from any thread.
    Uses QTimer.singleShot to ensure logging happens on the main thread.
    This prevents segfaults when called from background threads on Windows.
    """
    qgis_level = to_message_level(level)
    # Use QTimer.singleShot with 0ms delay to queue the log message on the main thread
    QTimer.singleShot(
        0,
        lambda: qgis.core.QgsMessageLog.logMessage(
            message, tag="trends.earth", level=qgis_level
        ),
    )
