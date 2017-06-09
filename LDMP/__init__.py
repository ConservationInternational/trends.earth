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
import site
import json
from PyQt4.QtCore import QSettings

site.addsitedir(os.path.abspath(os.path.dirname(__file__) + '/ext-libs'))

# On first load need to read the country lists into Qsettings
admin0 = QSettings().value('LDMP/admin0', None)
admin1 = QSettings().value('LDMP/admin1', None)
# TODO: Below is commented out just for debugging:
#if not admin0 or not admin1:
with open(os.path.join('C:/Users/azvol/Code/LandDegradation/ldmp-qgis-plugin/LDMP', 'data', 'admin0.json')) as admin0_file:
    admin0 = json.load(admin0_file)
QSettings().setValue('LDMP/admin0', json.dumps(admin0))

with open(os.path.join('C:/Users/azvol/Code/LandDegradation/ldmp-qgis-plugin/LDMP', 'data', 'admin1.json')) as admin1_file:
    admin1 = json.load(admin1_file)
QSettings().setValue('LDMP/admin1', json.dumps(admin1))

# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load LDMP class from file LDMP.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """

    from .ldmp import LDMP
    return LDMP(iface)
