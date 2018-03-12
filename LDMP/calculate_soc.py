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
import tempfile
import json

from osgeo import gdal, osr

from qgis.utils import iface
mb = iface.messageBar()

from PyQt4 import QtGui

from LDMP import log
from LDMP.calculate import DlgCalculateBase, get_script_slug
from LDMP.calculate_lc import lc_setup_widget
from LDMP.gui.DlgCalculateSOC import Ui_DlgCalculateSOC
from LDMP.api import run_script
from LDMP.worker import AbstractWorker, StartWorker


class SOCWorker(AbstractWorker):
    def __init__(self, soc_f, lc_f, lc_years, fl, remap_matrix):
        AbstractWorker.__init__(self)
        self.in_f = in_f
        self.out_f = out_f
        self.trans_matrix = trans_matrix
        self.persistence_remap = persistence_remap

    def work(self):
        ds_in = gdal.Open(self.in_f)

        band_initial = ds_in.GetRasterBand(1)
        band_final = ds_in.GetRasterBand(2)

        block_sizes = band_initial.GetBlockSize()
        x_block_size = block_sizes[0]
        # Need to process y line by line so that pixel area calculation can be
        # done based on latitude, which varies by line
        y_block_size = 1
        xsize = band_initial.XSize
        ysize = band_initial.YSize

        driver = gdal.GetDriverByName("GTiff")
        ds_out = driver.Create(self.out_f, xsize, ysize, 4, gdal.GDT_Int16, 
                               ['COMPRESS=LZW'])
        src_gt = ds_in.GetGeoTransform()
        ds_out.SetGeoTransform(src_gt)
        out_srs = osr.SpatialReference()
        out_srs.ImportFromWkt(ds_in.GetProjectionRef())
        ds_out.SetProjection(out_srs.ExportToWkt())

        blocks = 0
        for y in xrange(0, ysize, y_block_size):
            if self.killed:
                log("Processing killed by user after processing {} out of {} blocks.".format(y, ysize))
                break
            self.progress.emit(100 * float(y) / ysize)
            if y + y_block_size < ysize:
                rows = y_block_size
            else:
                rows = ysize - y
            for x in xrange(0, xsize, x_block_size):
                if x + x_block_size < xsize:
                    cols = x_block_size
                else:
                    cols = xsize - x

                a_i = band_initial.ReadAsArray(x, y, cols, rows)
                a_f = band_final.ReadAsArray(x, y, cols, rows)

                a_tr = a_i*10 + a_f
                a_tr[(a_i < 1) | (a_f < 1)] <- -32768

                a_deg = a_tr.copy()
                for value, replacement in zip(self.trans_matrix[0], self.trans_matrix[1]):
                    a_deg[a_deg == int(value)] = int(replacement)
                
                # Recode transitions so that persistence classes are easier to 
                # map
                for value, replacement in zip(self.persistence_remap[0], self.persistence_remap[1]):
                    a_tr[a_tr == int(value)] = int(replacement)

                ds_out.GetRasterBand(1).WriteArray(a_deg, x, y)
                ds_out.GetRasterBand(2).WriteArray(a_i, x, y)
                ds_out.GetRasterBand(3).WriteArray(a_f, x, y)
                ds_out.GetRasterBand(4).WriteArray(a_tr, x, y)

                blocks += 1
        if self.killed:
            os.remove(out_file)
            return None
        else:
            return True

class DlgCalculateSOC(DlgCalculateBase, Ui_DlgCalculateSOC):
    def __init__(self, parent=None):
        super(DlgCalculateSOC, self).__init__(parent)

        self.setupUi(self)
        
        self.regimes = [('Temperate dry (Fl = 0.80)', .80),
                        ('Temperate moist (Fl = 0.69)', .69),
                        ('Tropical dry (Fl = 0.58)', .58),
                        ('Tropical moist (Fl = 0.48)', .48),
                        ('Tropical montane (Fl = 0.64)', .64)]

        self.fl_chooseRegime_comboBox.addItems([r[0] for r in self.regimes])
        self.fl_chooseRegime_comboBox.setEnabled(False)
        self.fl_custom_lineEdit.setEnabled(False)
        # Setup validator for lineedit entries
        validator = QtGui.QDoubleValidator()
        validator.setBottom(0)
        validator.setDecimals(3)
        self.fl_custom_lineEdit.setValidator(validator)
        self.fl_radio_default.toggled.connect(self.fl_radios_toggled)
        self.fl_radio_chooseRegime.toggled.connect(self.fl_radios_toggled)
        self.fl_radio_custom.toggled.connect(self.fl_radios_toggled)

    def showEvent(self, event):
        super(DlgCalculateSOC, self).showEvent(event)

        self.lc_setup_tab = lc_setup_widget
        self.TabBox.insertTab(0, self.lc_setup_tab, self.tr('Land Cover Setup'))

        # Hide boxes that are coming soon
        self.groupBox_custom_SOC.hide()
        self.lc_setup_tab.use_custom.hide()
        self.lc_setup_tab.groupBox_custom_bl.hide()
        self.lc_setup_tab.groupBox_custom_tg.hide()

        if self.reset_tab_on_showEvent:
            self.TabBox.setCurrentIndex(0)

    def fl_radios_toggled(self):
        if self.fl_radio_custom.isChecked():
            self.fl_chooseRegime_comboBox.setEnabled(False)
            self.fl_custom_lineEdit.setEnabled(True)
        elif self.fl_radio_chooseRegime.isChecked():
            self.fl_chooseRegime_comboBox.setEnabled(True)
            self.fl_custom_lineEdit.setEnabled(False)
        else:
            self.fl_chooseRegime_comboBox.setEnabled(False)
            self.fl_custom_lineEdit.setEnabled(False)

    def get_fl(self):
        if self.fl_radio_custom.isChecked():
            return float(self.fl_custom_lineEdit.text())
        elif self.fl_radio_chooseRegime.isChecked():
            return [r[1] for r in self.regimes if r[0] == self.fl_chooseRegime_comboBox.currentText()][0]
        else:
            return 'per pixel'

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateSOC, self).btn_calculate()
        if not ret:
            return

        self.close()

        crosses_180th, geojsons = self.aoi.bounding_box_gee_geojson()
        payload = {'year_start': self.lc_setup_tab.use_esa_bl_year.date().year(),
                   'year_end': self.lc_setup_tab.use_esa_tg_year.date().year(),
                   'fl': self.get_fl(),
                   'download_annual_lc': self.download_annual_lc.isChecked(),
                   'geojsons': json.dumps(geojsons),
                   'crs': self.aoi.get_crs_dst_wkt(),
                   'crosses_180th': crosses_180th,
                   'remap_matrix': self.lc_setup_tab.dlg_esa_agg.get_agg_as_list(),
                   'task_name': self.options_tab.task_name.text(),
                   'task_notes': self.options_tab.task_notes.toPlainText()}

        resp = run_script(get_script_slug('soil-organic-carbon'), payload)

        if resp:
            mb.pushMessage(QtGui.QApplication.translate("LDMP", "Submitted"),
                           QtGui.QApplication.translate("LDMP", "Soil organic carbon submitted to Google Earth Engine."),
                           level=0, duration=5)
        else:
            mb.pushMessage(QtGui.QApplication.translate("LDMP", "Error"),
                           QtGui.QApplication.translate("LDMP", "Unable to submit soil organic carbon task to Google Earth Engine."),
                           level=0, duration=5)
