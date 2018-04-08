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
from qgis.core import QgsGeometry
mb = iface.messageBar()

from PyQt4 import QtGui
from PyQt4.QtCore import QSettings

from LDMP import log
from LDMP.api import run_script
from LDMP.calculate import DlgCalculateBase, get_script_slug
from LDMP.layers import add_layer, create_local_json_metadata
from LDMP.lc_setup import lc_setup_widget
from LDMP.worker import AbstractWorker, StartWorker
from LDMP.gui.DlgCalculateSOC import Ui_DlgCalculateSOC

def remap(a, remap_list):
    for value, replacement in zip(remap_list[0], remap_list[1]):
        a[a == int(value)] = int(replacement)
    return a

class SOCWorker(AbstractWorker):
    def __init__(self, in_vrt, out_f, lc_years, lc_band_nums, fl, remap_matrix):
        AbstractWorker.__init__(self)
        self.in_f = in_f
        self.out_f = out_f
        self.trans_matrix = trans_matrix
        self.persistence_remap = persistence_remap

    def work(self):
        ds_in = gdal.Open(self.in_f)

        soc_band = ds_in.GetRasterBand(1)
        clim_band = ds_in.GetRasterBand(2)

        block_sizes = soc_band.GetBlockSize()
        x_block_size = block_sizes[0]
        # Need to process y line by line so that pixel area calculation can be
        # done based on latitude, which varies by line
        y_block_size = 1
        xsize = soc_band.XSize
        ysize = soc_band.YSize

        driver = gdal.GetDriverByName("GTiff")
        ds_out = driver.Create(self.out_f, xsize, ysize, 4, gdal.GDT_Int16, 
                               ['COMPRESS=LZW'])
        src_gt = ds_in.GetGeoTransform()
        ds_out.SetGeoTransform(src_gt)
        out_srs = osr.SpatialReference()
        out_srs.ImportFromWkt(ds_in.GetProjectionRef())
        ds_out.SetProjection(out_srs.ExportToWkt())

        # Setup a raster of climate regimes to use for coding Fl automatically
        clim_fl_map = [[0, 1, 2, 3, 4, 5, 6,
                        7, 8, 9, 10, 11, 12],
                       [0, .69, .8, .69, .8, .69, .8,
                        .69, .8, .64, .48, .48, .58]]

        # stock change factor for land use - note the 99 and -99 will be 
        # recoded using the chosen Fl option
        lc_tr_fl_0_map = [[11, 12, 13, 14, 15, 16, 17,
                           21, 22, 23, 24, 25, 26, 27,
                           31, 32, 33, 34, 35, 36, 37,
                           41, 42, 43, 44, 45, 46, 47,
                           51, 52, 53, 54, 55, 56, 57,
                           61, 62, 63, 64, 65, 66, 67,
                           71, 72, 73, 74, 75, 76, 77],
                          [1, 1, 99, 1, 0.1, 0.1, 1,
                           1, 1, 99, 1, 0.1, 0.1, 1,
                           -99, -99, 1, 1 / 0.71, 0.1, 0.1, 1,
                           1, 1, 0.71, 1, 0.1, 0.1, 1,
                           2, 2, 2, 2, 1, 1, 1,
                           2, 2, 2, 2, 1, 1, 1,
                           1, 1, 1, 1, 1, 1, 1]]

        # stock change factor for management regime
        lc_tr_fm_map = [[11, 12, 13, 14, 15, 16, 17,
                         21, 22, 23, 24, 25, 26, 27,
                         31, 32, 33, 34, 35, 36, 37,
                         41, 42, 43, 44, 45, 46, 47,
                         51, 52, 53, 54, 55, 56, 57,
                         61, 62, 63, 64, 65, 66, 67,
                         71, 72, 73, 74, 75, 76, 77],
                        [1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1]]

        # stock change factor for input of organic matter
        lc_tr_fo_map = [[11, 12, 13, 14, 15, 16, 17,
                         21, 22, 23, 24, 25, 26, 27,
                         31, 32, 33, 34, 35, 36, 37,
                         41, 42, 43, 44, 45, 46, 47,
                         51, 52, 53, 54, 55, 56, 57,
                         61, 62, 63, 64, 65, 66, 67,
                         71, 72, 73, 74, 75, 76, 77],
                        [1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1,
                         1, 1, 1, 1, 1, 1, 1]]

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

                soc = soc_band.ReadAsArray(x, y, cols, rows)
                soc = ds_out.GetRasterBand(1).WriteArray(soc, x, y)

                if fl == 'per pixel':
                    clim = clim_band.ReadAsArray(x, y, cols, rows)
                    # Setup a raster of climate regimes to use for coding Fl 
                    # automatically
                    clim_fl = remap(clim, clim_fl_map)

                tr_time = np.zeros(soc.shape)
                for n in range(len(self.lc_years) - 1):
                    year = self.lc_years[n]

                    lc_t0 = src_ds.GetRasterBand(self.lc_band_nums[n]).ReadAsArray(x, y, cols, rows)
                    lc_t1 = src_ds.GetRasterBand(self.lc_band_nums[n + 1]).ReadAsArray(x, y, cols, rows)

                    # compute transition map (first digit for baseline land 
                    # cover, and second digit for target year land cover), but 
                    # only update where changes actually ocurred.
                    lc_tr = lc_t0*10 + lc_t1
                    lc_tr[(lc_t0 < 1) | (lc_t1 < 1)] <- -32768

                    # Set transition time to zero for pixels that DID change
                    tr_time[lc_t0 != lc_t1] = 0
                    # Add one to transition time for pixels that DID NOT change 
                    tr_time[lc_t0 == lc_t1] = tr_time[lc_t0 == lc_t1] + 1

                    # stock change factor for land use
                    lc_tr_fl = remap(lc_tr.copy(), lc_tr_fl_0_map)
                    if fl == 'per_pixel':
                        lc_tr_fl[lc_tr_fl == 99] = clim_fl[lc_tr_fl == 99]
                        lc_tr_fl[lc_tr_fl == 99] = 1 / clim_fl[lc_tr_fl == 99]
                    else:
                        lc_tr_fl[lc_tr_fl == 99] = fl
                        lc_tr_fl[lc_tr_fl == 99] = 1 / fl

                    # stock change factor for management regime
                    lc_tr_fm = remap(lc_tr, lc_tr_fm_map)

                    # stock change factor for input of organic matter
                    lc_tr_fo = remap(lc_tr, lc_tr_fo_map)

                    soc_chg = soc - (soc * lc_tr_fl * lc_tr_fm * lc_tr_fo) / 20
                    soc_chg[tr_time > 20] = 0
                    soc_chg[lc_t0 == lc_t1] = 0

                    soc = soc - soc_chg

                    # Write out this SOC layer. Note the first band of ds_out 
                    # is soc degradation, and as n starts at 0, need to add one 
                    # so that the first soc band is written to band 2 of the 
                    # output file
                    ds_out.GetRasterBand(n + 2).WriteArray(soc, x, y)

                # Write out the percent change in SOC layer
                soc_initial = ds_out.GetRasterBand(2).ReadAsArray(x, y, cols, rows)
                soc_final = ds_out.GetRasterBand(2 + len(lc_band_nums)).ReadAsArray(x, y, cols, rows)
                soc_pch = ((soc_final - soc_initial) / soc_initial) * 100
                ds_out.GetRasterBand(1).WriteArray(soc_pch, x, y)

                # Write out the initial and final lc layers
                lc_bl = src_ds.GetRasterBand(self.lc_band_nums[1]).ReadAsArray(x, y, cols, rows)
                ds_out.GetRasterBand(2 + len(lc_band_nums) + 1).WriteArray(soc_pch, x, y)
                lc_tg = src_ds.GetRasterBand(self.lc_band_nums[-1]).ReadAsArray(x, y, cols, rows)
                ds_out.GetRasterBand(2 + len(lc_band_nums) + 2).WriteArray(soc_pch, x, y)

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

        self.comboBox_custom_soc.populate()
        self.lc_setup_tab.use_custom_initial.populate()
        self.lc_setup_tab.use_custom_final.populate()


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

        if self.lc_setup_tab.use_custom.isChecked() or \
                self.groupBox_custom_SOC.isChecked():
            QtGui.QMessageBox.information(None, self.tr("Coming soon!"),
                                       self.tr("Custom SOC calculation coming soon!"), None)
            #self.calculate_locally()
        else:
            self.calculate_on_GEE()

    def get_save_raster(self):
        raster_file = QtGui.QFileDialog.getSaveFileName(self,
                                                        self.tr('Choose a name for the output file'),
                                                        QSettings().value("LDMP/output_dir", None),
                                                        self.tr('Raster file (*.tif)'))
        if raster_file:
            if os.access(os.path.dirname(raster_file), os.W_OK):
                QSettings().setValue("LDMP/input_dir", os.path.dirname(raster_file))
                return raster_file
            else:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr(u"Cannot write to {}. Choose a different file.".format(raster_file)))
                return False

    def calculate_locally(self):
        if not self.groupBox_custom_SOC.isChecked():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Due to the options you have chosen, this calculation must occur offline. You MUST select a custom soil organic carbon dataset."), None)
            return
        if not self.lc_setup_tab.use_custom.isChecked():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Due to the options you have chosen, this calculation must occur offline. You MUST select a custom land cover dataset."), None)
            return


        if len(self.comboBox_custom_soc.layer_list) == 0:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("You must add a soil organic carbon layer to your map before you can run the calculation."), None)
            return

        year_baseline = self.lc_setup_tab.get_initial_year()
        year_target = self.lc_setup_tab.get_final_year()
        if int(year_baseline) >= int(year_target):
            QtGui.QMessageBox.information(None, self.tr("Warning"),
                self.tr('The baseline year ({}) is greater than or equal to the target year ({}) - this analysis might generate strange results.'.format(year_baseline, year_target)))

        if self.aoi.calc_frac_overlap(QgsGeometry.fromRect(self.lc_setup_tab.use_custom_initial.get_layer().extent())) < .99:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Area of interest is not entirely within the initial land cover layer."), None)
            return

        if self.aoi.calc_frac_overlap(QgsGeometry.fromRect(self.lc_setup_tab.use_custom_final.get_layer().extent())) < .99:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Area of interest is not entirely within the final land cover layer."), None)
            return

        out_f = self.get_save_raster()
        if not out_f:
            return

        self.close()

        # Select the initial and final bands from initial and final datasets 
        # (in case there is more than one lc band per dataset)
        lc_initial_vrt = self.lc_setup_tab.use_custom_initial.get_vrt()
        lc_final_vrt = self.lc_setup_tab.use_custom_final.get_vrt()
        lc_files = [lc_initial_vrt, lc_final_vrt]
        lc_vrt = tempfile.NamedTemporaryFile(suffix='.vrt').name
        log('Saving LC files to {}'.format(lc_vrt))
        gdal.BuildVRT(lc_vrt,
                      lc_files,
                      outputBounds=self.aoi.get_aligned_output_bounds(lc_initial_vrt),
                      resolution='lowest',
                      resampleAlg=gdal.GRA_Mode,
                      separate=True)
        lc_years = [self.lc_setup_tab.get_initial_year(), self.lc_setup_tab.get_final_year()]

        soc_vrt = self.comboBox_custom_soc.get_vrt()
        climate_zones = os.path.join(os.path.dirname(__file__), 'data', 'IPCC_Climate_Zones.tif')
        in_files = [soc_vrt, climate_zones, lc_vrt], 
        in_vrt = tempfile.NamedTemporaryFile(suffix='.vrt').name
        log('SOC input files {}'.format(in_files))
        log('Saving SOC input files to {}'.format(in_vrt))
        gdal.BuildVRT(in_vrt,
                      in_files,
                      resolution='highest', 
                      resampleAlg=gdal.GRA_NearestNeighbour,
                      outputBounds=self.aoi.get_aligned_output_bounds(lc_initial_vrt),
                      separate=True)
        lc_band_nums = np.arange(len(lc_files)) + 2

        log(u'Saving soil organic carbon to {}'.format(out_f))
        soc_worker = StartWorker(SOCWorker,
                                 'calculating change in soil organic carbon', 
                                 in_vrt,
                                 out_f,
                                 lc_band_nums,
                                 lc_years,
                                 fl,
                                 remap_matrix)

        if not soc_worker.success:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Error calculating change in soil organic carbon."), None)
            return

        band_info = [BandInfo("Land cover (degradation)", add_to_map=True, metadata={'year_baseline': year_baseline, 'year_target': year_target}),
                     BandInfo("Land cover (7 class)", metadata={'year': year_baseline})]
        out_json = os.path.splitext(out_f)[0] + '.json'
        create_local_json_metadata(out_json, out_f, band_info)
        schema = BandInfoSchema()
        for band_number in xrange(len(band_info)):
            b = schema.dump(band_info[band_number])
            if b['add_to_map']:
                # The +1 is because band numbers start at 1, not zero
                add_layer(out_f, band_number + 1, b)

    def calculate_on_GEE(self):
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
