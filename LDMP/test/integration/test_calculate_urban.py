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

import logging

from qgis.testing import unittest

from LDMP.calculate_urban import DlgCalculateUrbanSummaryTable

from LDMP.test import add_default_bands_to_map


URBAN_TESTDATA = os.path.abspath(os.path.join(os.path.dirname(__file__), 'fixtures/Surinam_Paramaribo_11_3_1_Urban_10km.tif'))


class DlgCalculateUrbanSummaryTableWorkerTests(unittest.TestCase):
    def setUp(self):
        add_default_bands_to_map(URBAN_TESTDATA)

    def testWorker(self):
        d = DlgCalculateUrbanSummaryTable()
        # Need to show the summary table to run the setup code in that method
        d.show()
        out_tif_metadata = tempfile.NamedTemporaryFile(suffix='.json').name
        out_tif = os.path.splitext(out_tif_metadata)[0] + 'tif'
        out_table = tempfile.NamedTemporaryFile(suffix='.xlsx').name
        d.output_file_layer.setText(out_tif_metadata)
        d.output_file_table.setText(out_table)
        d.area_tab.area_admin_0.setCurrentIndex(d.area_tab.area_admin_0.findText('Suriname'))
        d.area_tab.radioButton_secondLevel_city.setChecked(True)
        d.area_tab.groupBox_buffer.setChecked(True)
        d.area_tab.secondLevel_city.setCurrentIndex(d.area_tab.secondLevel_city.findText('Paramaribo (Paramaribo)'))
        d.area_tab.buffer_size_km.setValue(10)

        ret = d.btn_calculate()
        self.assertTrue(ret)

    def test_table(self):
        self.assertTrue(True)
        
    def test_tif(self):
        self.assertTrue(True)


def CalculateUrbanIntegrationSuite():
    suite = unittest.TestSuite()
    suite.addTests(unittest.makeSuite(DlgCalculateUrbanSummaryTableWorkerTests, 'test'))
    return suite


def run_all():
    _suite = unittest.TestSuite()
    _suite.addTest(CalculateUrbanIntegrationSuite())
    unittest.TextTestRunner(verbosity=3, stream=sys.stdout).run(_suite)
