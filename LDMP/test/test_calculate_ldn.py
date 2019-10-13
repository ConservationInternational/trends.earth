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

import os
import sys
import tempfile

import numpy as np

from qgis.testing import unittest

from LDMP.calculate_ldn import DlgCalculateLDNSummaryTableAdmin

from LDMP.test import regular_keys, admin_keys, add_default_bands_to_map

from LDMP.calculate_numba import ldn_make_prod5, ldn_recode_state, \
    ldn_recode_traj, ldn_total_by_trans, ldn_total_deg_f


LDN_TESTDATA = os.path.abspath(os.path.join(os.path.dirname(__file__), 'fixtures/Nepal_Narayani_15_3_1_TE_One_Step.tif'))


class recode_stateTests(unittest.TestCase):
    def recode_to_deg(self):
        out = recode_state(np.array((-10, -2), dtype=np.int16))
        self.assertEquals(out, np.array((-1, 1), dtype=np.int16))

    def recode_to_stable(self):
        out = recode_state(np.array((-1, 1), dtype=np.int16))
        self.assertEquals(out, np.array((0, 0), dtype=np.int16))

    def recode_to_improve(self):
        out = recode_state(np.array((2, 10), dtype=np.int16))
        self.assertEquals(out, np.array((1, 1), dtype=np.int16))


class ldn_total_by_transTests(unittest.TestCase):
    def test_zero_array(self):
        transitions = np.array((11, 12, 33, 44), dtype=np.int16, ndmin=2)
        total = ldn_total_by_trans(np.zeros((10, 10), dtype=np.float64),
                                   np.zeros((10, 10), dtype=np.int16),
                                   transitions,
                                   np.zeros((10, 10), dtype=np.float64))
        self.assertEquals(np.sum(total), 0.0)


class ldn_total_deg_fTests(unittest.TestCase):
    def test_zero_array(self):
        total = ldn_total_deg_f(np.zeros((10, 10), dtype=np.int16), np.zeros((10, 10), dtype=np.bool), np.zeros((10, 10), dtype=np.float64))
        self.assertEquals(np.shape(total), (4,))
        self.assertEquals(np.sum(total), 0.0)


class DlgCalculateLDNSummaryTableAdminIntegrationTests(unittest.TestCase):
    def setUp(self):
        add_default_bands_to_map(LDN_TESTDATA)

    def testWorker(self):
        d = DlgCalculateLDNSummaryTableAdmin()
        # Need to show the summary table in order to run the setup code in that
        # method
        d.show()

        self.out_tif_metadata = tempfile.NamedTemporaryFile(suffix='.json').name
        self.out_tif = os.path.splitext(self.out_tif_metadata)[0] + 'tif'
        self.out_table = tempfile.NamedTemporaryFile(suffix='.xlsx').name
        d.output_file_layer.setText(self.out_tif_metadata)
        d.output_file_table.setText(self.out_table)

        d.area_tab.area_admin_0.setCurrentIndex(d.area_tab.area_admin_0.findText('Nepal'))
        d.area_tab.secondLevel_area_admin_1.setCurrentIndex(d.area_tab.secondLevel_area_admin_1.findText('Narayani'))

        ret = d.btn_calculate()
        self.assertTrue(ret)


def CalculateLDNSuite():
    suite = unittest.TestSuite()
    suite.addTests(unittest.makeSuite(recode_stateTests, 'test'))
    suite.addTests(unittest.makeSuite(ldn_total_deg_fTests, 'test'))
    suite.addTests(unittest.makeSuite(ldn_total_by_transTests, 'test'))
    suite.addTests(unittest.makeSuite(DlgCalculateLDNSummaryTableAdminIntegrationTests, 'test'))
    return suite


def run_all():
    _suite = unittest.TestSuite()
    _suite.addTest(CalculateLDNSuite())
    unittest.TextTestRunner(verbosity=3, stream=sys.stdout).run(_suite)
