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

from qgis.testing import unittest

import sys

from qgis.core import *
from qgis.PyQt.QtCore import *
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtGui import QApplication

from LDMP.calculate_ldn import DlgCalculateOneStep

from LDMP.test import regular_keys, admin_keys


def setup_lpd_layers(self):
    add_layer(lc)
    add_layer(soc)
    add_layer(lpd)
    
class DialogCalculateOneStep(unittest.TestCase):
    def testAdminBoundsLoad(self):
        d = DlgCalculateOneStep()
        d.area_tab.
        country = self.area_tab.area_admin_0.model().data(index)
        index = self.area_tab.area_admin_0.model().index(row, 0)

class DialogCalculateSummaryTableAdmin(unittest.TestCase):
    def testAdminBoundsLoad(self):

def SettingsSuite():
    suite = unittest.TestSuite()
    suite.addTests(unittest.makeSuite(DialogCalculateBaseTests, 'test'))
    return suite
