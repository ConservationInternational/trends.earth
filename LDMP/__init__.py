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
from qgis.core import QgsApplication
from qgis.utils import iface

import LDMP.logger
from . import (
    conf,
    utils,
)

plugin_dir = os.path.dirname(os.path.realpath(__file__))

with open(os.path.join(plugin_dir, 'version.json')) as f:
    version_info = json.load(f)
__version__ = version_info['version']
__version_major__ = re.sub(r'([0-9]+)(\.[0-9]+)+$', r'\g<1>', __version__)
__revision__ = version_info['revision']
__release_date__ = version_info['release_date']


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
LDMP.logger.log(
    f'Starting trends.earth version {__version__} (rev: {__revision__}, '
    f'released {__release_date__}).'
)

translator = QtCore.QTranslator()
locale = QtCore.QLocale(QgsApplication.locale())
LDMP.logger.log('Trying to load locale {} from {}.'.format(locale.name(), i18n_dir))
translator.load(locale, 'LDMP', prefix='.', directory=i18n_dir, suffix='.qm')
ret = QtCore.QCoreApplication.installTranslator(translator)
if ret:
    LDMP.logger.log("Translator installed for {}.".format(locale.name()))
else:
    LDMP.logger.log("FAILED while trying to install translator for {}.".format(locale.name()))

# Ensure that the ext-libs, and binaries folder (if available) are near the 
# front of the path (important on Linux)
ext_libs_path = os.path.join(plugin_dir, 'ext-libs')
binaries_folder = conf.settings_manager.get_value(conf.Setting.BINARIES_DIR)
sys.path, remainder = sys.path[:1], sys.path[1:]
site.addsitedir(ext_libs_path)
if binaries_folder:
    LDMP.logger.log('Adding {} to path for binaries.'.format(binaries_folder))
    site.addsitedir(os.path.join(binaries_folder,
        'trends_earth_binaries_{}'.format(__version__.replace('.', '_'))))
sys.path.extend(remainder)


def binaries_available():
    ret = True
    debug_enabled = conf.settings_manager.get_value(conf.Setting.DEBUG)
    try:
        from trends_earth_binaries import summary_numba
        if debug_enabled:
            LDMP.logger.log("Numba-compiled version of summary_numba available.")
    except (ModuleNotFoundError, ImportError) as e:
        if debug_enabled:
            LDMP.logger.log("Numba-compiled version of summary_numba not available.")
        ret = False
    try:
        from trends_earth_binaries import calculate_numba
        if debug_enabled:
            LDMP.logger.log("Numba-compiled version of calculate_numba available.")
    except (ModuleNotFoundError, ImportError) as e:
        if debug_enabled:
            LDMP.logger.log("Numba-compiled version of calculate_numba not available.")
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
        subprocess.check_call(['explorer', path])
