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

from LDMP.calculate_ldn import DlgCalculateLDNSummaryTableAdmin, \
    ldn_total_by_trans_merge

from LDMP.test import add_default_bands_to_map

from LDMP.calculate_numba import ldn_make_prod5, ldn_recode_state, \
    ldn_recode_traj, ldn_total_by_trans, ldn_total_deg_f


LDN_TESTDATA = os.path.abspath(os.path.join(os.path.dirname(__file__), 'fixtures/Nepal_Narayani_15_3_1_TE_One_Step.tif'))


class DlgCalculateLDNSummaryTableAdminWorkerTests(unittest.TestCase):
    def setUp(self):
        add_default_bands_to_map(LDN_TESTDATA)

    def testWorker(self):
        d = DlgCalculateLDNSummaryTableAdmin()
        # Need to show the summary table to run the setup code in that method
        d.show()
        out_tif_metadata = tempfile.NamedTemporaryFile(suffix='.json').name
        out_tif = os.path.splitext(out_tif_metadata)[0] + 'tif'
        out_table = tempfile.NamedTemporaryFile(suffix='.xlsx').name
        d.output_file_layer.setText(out_tif_metadata)
        d.output_file_table.setText(out_table)
        d.area_tab.area_admin_0.setCurrentIndex(d.area_tab.area_admin_0.findText('Nepal'))
        d.area_tab.secondLevel_area_admin_1.setCurrentIndex(d.area_tab.secondLevel_area_admin_1.findText('Narayani'))

        ret = d.btn_calculate()
        self.assertTrue(ret)
        

class DlgCalculateLDNSummaryTableAdminOutputTests(unittest.TestCase):
    # def setUp(self):
    #     add_default_bands_to_map(LDN_TESTDATA)
    #
    #     d = DlgCalculateLDNSummaryTableAdmin()
    #     # Need to show the summary table to run the setup code in that method
    #     d.show()
    #     out_tif_metadata = tempfile.NamedTemporaryFile(suffix='.json').name
    #     out_tif = os.path.splitext(out_tif_metadata)[0] + 'tif'
    #     out_table = tempfile.NamedTemporaryFile(suffix='.xlsx').name
    #     d.output_file_layer.setText(out_tif_metadata)
    #     d.output_file_table.setText(out_table)
    #     d.area_tab.area_admin_0.setCurrentIndex(d.area_tab.area_admin_0.findText('Nepal'))
    #     d.area_tab.secondLevel_area_admin_1.setCurrentIndex(d.area_tab.secondLevel_area_admin_1.findText('Narayani'))
    #
    #     ret = d.btn_calculate()
        
    def test_table(self):
        self.assertTrue(True)
        
    def test_tif(self):
        self.assertTrue(True)


def CalculateLDNIntegrationSuite():
    suite = unittest.TestSuite()
    suite.addTests(unittest.makeSuite(DlgCalculateLDNSummaryTableAdminWorkerTests, 'test'))
    suite.addTests(unittest.makeSuite(DlgCalculateLDNSummaryTableAdminOutputTests, 'test'))
    return suite


def run_all():
    _suite = unittest.TestSuite()
    _suite.addTest(CalculateLDNIntegrationSuite())
    unittest.TextTestRunner(verbosity=3, stream=sys.stdout).run(_suite)
