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

from LDMP.test import regular_keys, admin_keys, add_default_bands_to_map


LDN_TESTDATA = 'data/Nepal_Narayani_15_3_1_TE_One_Step.tif'


class DegradationSummaryWorkerSDG(unittest.TestCase):
    def setUp(self):
        add_default_bands_to_map(LDN_TESTDATA)

    def testWorker(self):
        # deg_worker = StartWorker(DegradationSummaryWorkerSDG,
        #                         'calculating summary table (part {} of {})'.format(n + 1, len(wkts)),
        #                          indic_vrt,
        #                          prod_band_nums,
        #                          prod_mode, 
        #                          output_sdg_tif,
        #                          lc_band_nums, 
        #                          soc_band_nums,
        #                          mask_vrt)
        #
        self.assertEquals(0, 0)


def CalculateLDNSuite():
    suite = unittest.TestSuite()
    suite.addTests(unittest.makeSuite(DegradationSummaryWorkerSDG, 'test'))
    return suite
