"""
/***************************************************************************
 LDMP - A QGIS plugin
 This plugin supports monitoring and reporting of land degradation to the UNCCD
 and in support of the SDG Land Degradation Neutrality (LDN) target.
                              -------------------
        begin                : 2017-05-23
        git sha              : $Format:%H$
        copyright            : (C) 2017 by Conservation International
        email                : trends.earth@conservation.org
 ***************************************************************************/
"""

import os
import re
import site
import subprocess
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

from qgis.core import Qgis, QgsApplication
from qgis.PyQt import QtCore
from qgis.utils import iface

from . import logger

# initialize translation
plugin_dir = os.path.dirname(os.path.realpath(__file__))
i18n_dir = os.path.join(plugin_dir, "i18n")
translator = QtCore.QTranslator()
locale = QtCore.QLocale(QgsApplication.locale())
translator.load(locale, "LDMP", "_", directory=i18n_dir, suffix=".qm")
trans_result = QtCore.QCoreApplication.installTranslator(translator)

# Get version and git information from setuptools-scm generated file
try:
    from LDMP._version import __git_date__, __git_sha__, __version__

    __revision__ = __git_sha__
    __release_date__ = __git_date__
    __version_major__ = re.sub(r"([0-9]+)(\.[0-9]+)+.*$", r"\g<1>", __version__)
except ImportError:
    # _version.py doesn't exist - likely running from source without building
    __version__ = "unknown"
    __revision__ = "unknown"
    __git_sha__ = "unknown"
    __git_date__ = "unknown"
    __release_date__ = "unknown"
    __version_major__ = "0"

    # Show user-friendly error message in QGIS
    from qgis.core import Qgis, QgsMessageLog

    QgsMessageLog.logMessage(
        "Trends.Earth plugin version could not be determined. "
        "If you're running from source, please run 'invoke set-version' to generate version information. "
        "See SETUPTOOLS_SCM_GUIDE.md for details.",
        "Trends.Earth",
        Qgis.Warning,
    )


def _add_at_front_of_path(d):
    """Add a folder at the very front of sys.path while honoring .pth files."""

    if not d:
        return

    resolved = os.path.realpath(os.fspath(Path(d)))

    # site.addsitedir processes .pth files and ensures the directory exists.
    site.addsitedir(resolved)

    # Remove any duplicate entries to force our entry to the front of the path
    def _canonical(path_entry):
        try:
            return os.path.realpath(path_entry)
        except OSError:
            return path_entry

    sys.path[:] = [p for p in sys.path if _canonical(p) != resolved]
    sys.path.insert(0, resolved)


# Put ext-libs folder near the front of the path (important on Linux)
_add_at_front_of_path(str(Path(plugin_dir) / "ext-libs"))


def tr(message):
    return QtCore.QCoreApplication.translate("trends.earth", message)


def classFactory(iface):  # pylint: disable=invalid-name
    """Load LDMPPlugin class from file LDMP.
    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """

    from LDMP.plugin import LDMPPlugin  # noqa: E402

    return LDMPPlugin(iface)


# Function to get a temporary filename that handles closing the file created by
# NamedTemporaryFile - necessary when the file is for usage in another process
# (i.e. GDAL)
def GetTempFilename(suffix):
    f = NamedTemporaryFile(suffix=suffix, delete=False)
    f.close()

    return f.name


logger.log(
    f"Starting trends.earth version {__version__} (rev: {__revision__}, "
    f"released {__release_date__})."
)

if trans_result:
    logger.log("Translator installed for {}.".format(locale.name()))
else:
    logger.log(
        "FAILED while trying to install translator for {}.".format(locale.name())
    )

from . import conf  # noqa: E402

if conf.settings_manager.get_value(conf.Setting.DEBUG):
    import logging  # noqa: E402

    formatter = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    logfilename = (
        Path(conf.settings_manager.get_value(conf.Setting.BASE_DIR))
        / "trends_earth_log.txt"
    )
    Path(logfilename).parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(filename=logfilename, level=logging.DEBUG, format=formatter)


def openFolder(path):
    if not path:
        return

    # check path exist and readable

    if not os.path.exists(path):
        message = tr("Path do not exist: ") + path
        iface.messageBar().pushCritical("Trends.Earth", message)

        return

    if not os.access(path, mode=os.R_OK | os.W_OK):
        message = tr("No read or write permission on path: ") + path
        iface.messageBar().pushCritical("Trends.Earth", message)

        return

    if sys.platform == "darwin":
        subprocess.check_call(["open", path])
    elif sys.platform == "linux":
        subprocess.check_call(["xdg-open", path])
    elif sys.platform == "win32":
        res = subprocess.run(["explorer", path])
        # For some reason windows "explorer" often returns 1 on success (as
        # apparently do other windows GUI programs...)

        if res.returncode not in [0, 1]:
            raise subprocess.CalledProcessError
