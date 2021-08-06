# -*- coding: utf-8 -*-

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
# pylint: disable=import-error

import sys
import os
import re
import site
import json
import subprocess
from tempfile import NamedTemporaryFile

from PyQt5 import (
    QtCore,
)
from qgis.core import QgsApplication, QgsSettings
from qgis.utils import iface

from . import logger


plugin_dir = os.path.dirname(os.path.realpath(__file__))
with open(os.path.join(plugin_dir, 'version.json')) as f:
    version_info = json.load(f)
__version__ = version_info['version']
__version_major__ = re.sub(r'([0-9]+)(\.[0-9]+)+$', r'\g<1>', __version__)
__revision__ = version_info['revision']
__release_date__ = version_info['release_date']


def _add_at_front_of_path(d):
    '''add a folder at front of path'''
    sys.path, remainder = sys.path[:1], sys.path[1:]
    site.addsitedir(d)
    sys.path.extend(remainder)


# Ensure that the ext-libs, and binaries folder (if available) are near the 
# front of the path (important on Linux)
binaries_folder = QtCore.QSettings().value(
    "trends_earth/advanced/binaries_folder",
    None
)
# TODO: Fix this
# if binaries_folder:
#     logger.log('Adding {} to path for binaries.'.format(binaries_folder))
#     _add_at_front_of_path(os.path.join(
#         binaries_folder,
#         'trends_earth_binaries_{}'.format(__version__.replace('.', '_')))
#     )
_add_at_front_of_path(os.path.join(plugin_dir, 'ext-libs'))


def tr(message):
    return QtCore.QCoreApplication.translate('trends.earth', message)


def classFactory(iface):  # pylint: disable=invalid-name
    """Load LDMPPlugin class from file LDMP.
    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """

    from LDMP.plugin import LDMPPlugin
    return LDMPPlugin(iface)

# Function to get a temporary filename that handles closing the file created by 
# NamedTemporaryFile - necessary when the file is for usage in another process 
# (i.e. GDAL)
def GetTempFilename(suffix):
    f = NamedTemporaryFile(suffix=suffix, delete=False)
    f.close()
    return f.name

# initialize translation
i18n_dir = os.path.join(plugin_dir, 'i18n')
logger.log(
    f'Starting trends.earth version {__version__} (rev: {__revision__}, '
    f'released {__release_date__}).'
)

translator = QtCore.QTranslator()
locale = QtCore.QLocale(QgsApplication.locale())
logger.log('Trying to load locale {} from {}.'.format(locale.name(), i18n_dir))
translator.load(locale, 'LDMP', prefix='.', directory=i18n_dir, suffix='.qm')
ret = QtCore.QCoreApplication.installTranslator(translator)
if ret:
    logger.log("Translator installed for {}.".format(locale.name()))
else:
    logger.log("FAILED while trying to install translator for {}.".format(locale.name()))


from . import (
    conf,
    utils,
)


def binaries_available():
    ret = True
    debug_enabled = conf.settings_manager.get_value(conf.Setting.DEBUG)
    try:
        from trends_earth_binaries import summary_numba
        if debug_enabled:
            logger.log("Numba-compiled version of summary_numba available.")
    except (ModuleNotFoundError, ImportError, RuntimeError) as e:
        if debug_enabled:
            logger.log("Numba-compiled version of summary_numba not available: {}".format(e))
        ret = False
    try:
        from trends_earth_binaries import calculate_numba
        if debug_enabled:
            logger.log("Numba-compiled version of calculate_numba available.")
    except (ModuleNotFoundError, ImportError, RuntimeError) as e:
        if debug_enabled:
            logger.log("Numba-compiled version of calculate_numba not available: {}".format(e))
        ret = False
    return ret


def openFolder(path):
    if not path:
        return

    # check path exist and readable
    if not os.path.exists(path):
        message = tr('Path do not exist: ') + path
        iface.messageBar().pushCritical('Trends.Earth', message)
        return

    if not os.access(path, mode=os.R_OK|os.W_OK):
        message = tr('No read or write permission on path: ') + path
        iface.messageBar().pushCritical('Trends.Earth', message)
        return

    if sys.platform == 'darwin':
        subprocess.check_call(['open', path])
    elif sys.platform == 'linux':
        subprocess.check_call(['xdg-open', path])
    elif sys.platform == 'win32':
        res = subprocess.run(['explorer', path])
        # For some reason windows "explorer" often returns 1 on success (as
        # apparently do other windows GUI programs...)
        if res.returncode not in [0, 1]:
            raise subprocess.CalledProcessError
        
