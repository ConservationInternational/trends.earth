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
        email                : GEF-LDMP@conservation.org
 ***************************************************************************/
"""

import os
import requests
import site

from PyQt4 import QtGui, QtCore, uic

from qgis.core import QgsMessageLog
from qgis.utils import iface

site.addsitedir(os.path.abspath(os.path.dirname(__file__) + '/ext-libs'))

debug = QtCore.QSettings().value('LDMP/debug', True)

def log(message, level=QgsMessageLog.INFO):
    if debug:
        QgsMessageLog.logMessage(message, tag="LDMP", level=level)

# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load LDMPPlugin class from file LDMP.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """

    from LDMP.ldmp import LDMPPlugin
    return LDMPPlugin(iface)
