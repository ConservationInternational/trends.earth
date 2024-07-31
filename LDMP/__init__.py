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

import json
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

try:
    with open(os.path.join(plugin_dir, "version.json")) as f:
        version_info = json.load(f)
except FileNotFoundError:
    # Will happen for a dev version if user downloads directly from github and installs
    # without using invoke script
    version_info = {
        "version": "99.99.99",
        "revision": "unknown",
        "release_date": "2099/01/01 00:00:00Z",
    }
__version__ = version_info["version"]
__version_major__ = re.sub(r"([0-9]+)(\.[0-9]+)+$", r"\g<1>", __version__)
__revision__ = version_info["revision"]
__release_date__ = version_info["release_date"]


def _add_at_front_of_path(d):
    """add a folder at front of path"""
    sys.path, remainder = sys.path[:1], sys.path[1:]
    site.addsitedir(d)
    sys.path.extend(remainder)


# Put binaries folder (if available) near the front of the path (important on
# Linux)
binaries_folder = QtCore.QSettings().value(
    "trends_earth/advanced/binaries_folder", None
)
te_version = __version__.replace(".", "-")
qgis_version = re.match(r"^[0-9]*\.[0-9]*", Qgis.QGIS_VERSION)[0].replace(".", "-")
binaries_name = f"trends_earth_binaries_{te_version}_{qgis_version}"

if binaries_folder:
    binaries_path = Path(binaries_folder) / f"{binaries_name}"
    logger.log(f"Adding {binaries_path} to path")
    _add_at_front_of_path(str(binaries_path))

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


def binaries_available():
    ret = True
    debug_enabled = conf.settings_manager.get_value(conf.Setting.DEBUG)
    try:
        from trends_earth_binaries import ldn_numba  # noqa: E402, F401

        if debug_enabled:
            logger.log("Numba-compiled version of ldn_numba available.")
    except (ModuleNotFoundError, ImportError, RuntimeError) as e:
        if debug_enabled:
            logger.log(
                "Numba-compiled version of ldn_numba not available: {}".format(e)
            )
        ret = False

    return ret


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
