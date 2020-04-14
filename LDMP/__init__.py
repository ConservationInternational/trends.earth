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

import sys
import os
import requests
import site
import json
from tempfile import NamedTemporaryFile

from qgis.PyQt.QtCore import QSettings, QTranslator, qVersion
from qgis.PyQt.QtWidgets import QApplication

from qgis.core import QgsMessageLog
from qgis.utils import iface

plugin_dir = os.path.dirname(os.path.realpath(__file__))

# Ensure that the ext-libs for the plugin are near the front of the path
# (important on Linux)
dirpath = os.path.join(plugin_dir, 'ext-libs')
sys.path, remainder = sys.path[:1], sys.path[1:]
site.addsitedir(dirpath)
sys.path.extend(remainder)

debug = QSettings().value('LDMP/debug', True)


with open(os.path.join(plugin_dir, 'version.json')) as f:
    version_info = json.load(f)
__version__ = version_info['version']
__revision__ = version_info['revision']
__release_date__ = version_info['release_date']


def log(message, level=0):
    if debug:
        QgsMessageLog.logMessage(message, tag="trends.earth", level=level)


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

# initialize locale and translation
locale = QSettings().value('locale/userLocale')[0:2]
locale_path = os.path.join(plugin_dir, 'i18n', u'LDMP_{}.qm'.format(locale))
log(u'Starting trends.earth version {} (rev: {}, released {})) using locale "{}" in path {}.'.format(__version__, __revision__, __release_date__, locale, locale_path))

if os.path.exists(locale_path):
    translator = QTranslator()
    ret = translator.load(locale_path)
    if ret:
        log('Loaded {}'.format(locale_path))
    else:
        log('Failed while trying to load {}'.format(locale_path))
    if qVersion() > '4.3.3':
        ret = QApplication.installTranslator(translator)
        if ret:
            log("Translator installed.")
        else:
            log('Failed while trying to install translator')
