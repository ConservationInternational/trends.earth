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

from LDMP.calculate import ldn_make_prod5
from LDMP.calculate import ldn_recode_state
from LDMP.calculate import ldn_recode_traj
from LDMP.calculate import ldn_total_by_trans
from LDMP.calculate import ldn_total_deg_f
from LDMP.calculate_ldn import DlgCalculateLDNSummaryTableAdmin
from LDMP.calculate_ldn import ldn_total_by_trans_merge
from LDMP.test import add_default_bands_to_map


LDN_TESTDATA = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "fixtures/Nepal_Narayani_15_3_1_TE_One_Step.tif"
    )
)


class DlgCalculateLDNSummaryTableAdminWorkerTests(unittest.TestCase):
    def setUp(self):
        add_default_bands_to_map(LDN_TESTDATA)

        self.d = DlgCalculateLDNSummaryTableAdmin()
        # Need to show the summary table to run the setup code in that method
        self.d.show()
        out_tif_metadata = tempfile.NamedTemporaryFile(suffix=".json").name
        out_tif = os.path.splitext(out_tif_metadata)[0] + ".tif"
        out_table = tempfile.NamedTemporaryFile(suffix=".xlsx").name
        self.d.output_file_layer.setText(out_tif_metadata)
        self.d.output_file_table.setText(out_table)
        self.d.area_tab.area_admin_0.setCurrentIndex(
            self.d.area_tab.area_admin_0.findText("Nepal")
        )
        self.d.area_tab.secondLevel_area_admin_1.setCurrentIndex(
            self.d.area_tab.secondLevel_area_admin_1.findText("Narayani")
        )

    def testBands(self):
        # Ensure that the bands have loaded into the dialog box
        self.assertEqual(
            self.d.combo_layer_traj.currentText(),
            "Productivity trajectory degradation (2001 to 2015)",
        )
        self.assertEqual(
            self.d.combo_layer_perf.currentText(),
            "Productivity performance degradation (2001 to 2015)",
        )
        self.assertEqual(
            self.d.combo_layer_state.currentText(),
            "Productivity state degradation (2001-2012 to 2013-2015)",
        )
        self.assertEqual(
            self.d.combo_layer_lc.currentText(), "Land cover degradation (2001 to 2015)"
        )
        self.assertEqual(
            self.d.combo_layer_soc.currentText(),
            "Soil organic carbon degradation (2001 to 2015)",
        )

    def testWorker(self):
        ret = self.d.btn_calculate()
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
    suite.addTests(
        unittest.makeSuite(DlgCalculateLDNSummaryTableAdminWorkerTests, "test")
    )
    suite.addTests(
        unittest.makeSuite(DlgCalculateLDNSummaryTableAdminOutputTests, "test")
    )
    return suite


def run_all():
    _suite = unittest.TestSuite()
    _suite.addTest(CalculateLDNIntegrationSuite())
    unittest.TextTestRunner(verbosity=3, stream=sys.stdout).run(_suite)
