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

from qgis.PyQt.QtCore import (QSettings, QTranslator, qVersion, 
        QLocale, QCoreApplication)

from qgis.core import QgsMessageLog, QgsApplication
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

# initialize translation
i18n_dir = os.path.join(plugin_dir, 'i18n')
log(u'Starting trends.earth version {} (rev: {}, released {}).'.format(__version__, __revision__, __release_date__))

translator = QTranslator()
locale = QLocale(QgsApplication.locale())
log('Trying to load locale {} from {}.'.format(locale.name(), i18n_dir))
translator.load(locale, 'LDMP', prefix='.', directory=i18n_dir, suffix='.qm')
ret = QCoreApplication.installTranslator(translator)
if ret:
    log("Translator installed for {}.".format(locale.name()))
else:
    log("FAILED while trying to install translator for {}.".format(locale.name()))
