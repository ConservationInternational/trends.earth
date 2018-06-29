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

import numpy as np

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
from LDMP.gui.DlgCalculateTC import Ui_DlgCalculateTC
from LDMP.schemas.schemas import BandInfo, BandInfoSchema


def remap(a, remap_list):
    for value, replacement in zip(remap_list[0], remap_list[1]):
        a[a == value] = replacement
    return a


class TCWorker(AbstractWorker):
    def __init__(self, in_vrt, out_f, lc_band_nums, lc_years):
        AbstractWorker.__init__(self)
        self.in_vrt = in_vrt
        self.out_f = out_f
        self.lc_years = lc_years
        self.lc_band_nums = lc_band_nums

    def work(self):
        ds_in = gdal.Open(self.in_vrt)

        soc_band = ds_in.GetRasterBand(1)
        clim_band = ds_in.GetRasterBand(2)

        block_sizes = soc_band.GetBlockSize()
        x_block_size = block_sizes[0]
        y_block_size = block_sizes[1]
        xsize = soc_band.XSize
        ysize = soc_band.YSize

        driver = gdal.GetDriverByName("GTiff")
        # Need a band for SOC degradation, plus bands for annual SOC, and for 
        # annual LC
        ds_out = driver.Create(self.out_f, xsize, ysize,
                1 + len(self.lc_years)*2, gdal.GDT_Int16, 
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

                # Write initial soc to band 2 of the output file. Read SOC in 
                # as float so the soc change calculations won't accumulate 
                # error due to repeated truncation of ints
                soc = np.array(soc_band.ReadAsArray(x, y, cols, rows)).astype(np.float32)
                ds_out.GetRasterBand(2).WriteArray(soc, x, y)

                blocks += 1

        if self.killed:
            del ds_in
            del ds_out
            os.remove(self.out_f)
            return None
        else:
            return True

class DlgCalculateTC(DlgCalculateBase, Ui_DlgCalculateTC):
    def __init__(self, parent=None):
        super(DlgCalculateTC, self).__init__(parent)

        self.setupUi(self)
        
    def showEvent(self, event):
        super(DlgCalculateTC, self).showEvent(event)

        self.lc_setup_tab = lc_setup_widget
        self.TabBox.insertTab(0, self.lc_setup_tab, self.tr('Land Cover Setup'))

        # These boxes may have been hidden if this widget was last shown on the 
        # SDG one step dialog
        self.lc_setup_tab.groupBox_esa_period.show()
        self.lc_setup_tab.use_custom.show()
        self.lc_setup_tab.groupBox_custom_bl.show()
        self.lc_setup_tab.groupBox_custom_tg.show()

        self.lc_setup_tab.use_custom_initial.populate()
        self.lc_setup_tab.use_custom_final.populate()

        # Ensure the special value text (set to " ") is displayed by default
        self.lc_setup_tab.use_hansen_fc.setSpecialValueText(' ')
        self.lc_setup_tab.use_hansen_fc.setValue(self.lc_setup_tab.use_hansen_fc.minimum())

        if self.reset_tab_on_showEvent:
            self.TabBox.setCurrentIndex(0)

        # Show hansen selector 
        self.lc_setup_tab.show_hansen_toggle(True)

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateTC, self).btn_calculate()
        if not ret:
            return
        if self.lc_setup_tab.use_hansen_fc.text() == self.lc_setup_tab.use_hansen_fc.specialValueText():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr(u"Enter a value for percent cover that is considered forest."))
            return


        if self.lc_setup_tab.use_custom.isChecked():
            self.calculate_locally()
        else:
            self.calculate_on_GEE()

    def get_save_raster(self):
        raster_file = QtGui.QFileDialog.getSaveFileName(self,
                                                        self.tr('Choose a name for the output file'),
                                                        QSettings().value("LDMP/output_dir", None),
                                                        self.tr('Raster file (*.tif)'))
        if raster_file:
            if os.access(os.path.dirname(raster_file), os.W_OK):
                QSettings().setValue("LDMP/output_dir", os.path.dirname(raster_file))
                return raster_file
            else:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr(u"Cannot write to {}. Choose a different file.".format(raster_file)))
                return False

    def calculate_locally(self):
        if not self.lc_setup_tab.use_custom.isChecked():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Due to the options you have chosen, this calculation must occur offline. You MUST select a custom land cover dataset."), None)
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
        lc_years = [self.lc_setup_tab.get_initial_year(), self.lc_setup_tab.get_final_year()]
        lc_vrts = []
        for i in range(len(lc_files)):
            f = tempfile.NamedTemporaryFile(suffix='.vrt').name
            # Add once since band numbers don't start at zero
            gdal.BuildVRT(f,
                          lc_files[i],
                          bandList=[i + 1],
                          outputBounds=self.aoi.get_aligned_output_bounds_deprecated(lc_initial_vrt),
                          resolution='highest', 
                          resampleAlg=gdal.GRA_NearestNeighbour,
                          separate=True)
            lc_vrts.append(f)

        climate_zones = os.path.join(os.path.dirname(__file__), 'data', 'IPCC_Climate_Zones.tif')
        in_files = [climate_zones]
        in_files.extend(lc_vrts)
        in_vrt = tempfile.NamedTemporaryFile(suffix='.vrt').name
        log(u'Saving SOC input files to {}'.format(in_vrt))
        gdal.BuildVRT(in_vrt,
                      in_files,
                      resolution='highest', 
                      resampleAlg=gdal.GRA_NearestNeighbour,
                      outputBounds=self.aoi.get_aligned_output_bounds_deprecated(lc_initial_vrt),
                      separate=True)
        # Lc bands start on band 3 as band 1 is initial soc, and band 2 is 
        # climate zones
        lc_band_nums = np.arange(len(lc_files)) + 3

        log(u'Saving soil organic carbon to {}'.format(out_f))
        soc_worker = StartWorker(SOCWorker,
                                 'calculating change in soil organic carbon', 
                                 in_vrt,
                                 out_f,
                                 lc_band_nums,
                                 lc_years)

        if not soc_worker.success:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Error calculating change in soil organic carbon."), None)
            return

        band_infos = [BandInfo("Soil organic carbon (degradation)", add_to_map=True, metadata={'year_start': lc_years[0], 'year_end': lc_years[-1]})]
        for year in lc_years:
            if (year == lc_years[0]) or (year == lc_years[-1]):
                # Add first and last years to map
                add_to_map = True
            else:
                add_to_map = False
            band_infos.append(BandInfo("Soil organic carbon", add_to_map=add_to_map, metadata={'year': year}))
        for year in lc_years:
            band_infos.append(BandInfo("Land cover (7 class)", metadata={'year': year}))

        out_json = os.path.splitext(out_f)[0] + '.json'
        create_local_json_metadata(out_json, out_f, band_infos)
        schema = BandInfoSchema()
        for band_number in xrange(len(band_infos)):
            b = schema.dump(band_infos[band_number])
            if b['add_to_map']:
                # The +1 is because band numbers start at 1, not zero
                add_layer(out_f, band_number + 1, b)

    def calculate_on_GEE(self):
        self.close()

        crosses_180th, geojsons = self.aoi.bounding_box_gee_geojson()
        payload = {'year_start': self.lc_setup_tab.use_esa_bl_year.date().year(),
                   'year_end': self.lc_setup_tab.use_esa_tg_year.date().year(),
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
