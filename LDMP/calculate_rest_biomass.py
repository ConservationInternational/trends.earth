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

import openpyxl
from openpyxl.drawing.image import Image

from qgis.utils import iface
from qgis.core import QgsGeometry
mb = iface.messageBar()

from PyQt4 import QtGui
from PyQt4.QtCore import QSettings, QDate

from LDMP import log
from LDMP.api import run_script
from LDMP.calculate import DlgCalculateBase, get_script_slug, ClipWorker
from LDMP.layers import add_layer, create_local_json_metadata
from LDMP.worker import AbstractWorker, StartWorker
from LDMP.gui.DlgCalculateRestBiomassData import Ui_DlgCalculateRestBiomassData
from LDMP.gui.DlgCalculateRestBiomassSummaryTable import Ui_DlgCalculateRestBiomassSummaryTable
from LDMP.schemas.schemas import BandInfo, BandInfoSchema
from LDMP.summary import *


class DlgCalculateRestBiomassData(DlgCalculateBase, Ui_DlgCalculateRestBiomassData):
    def __init__(self, parent=None):
        super(DlgCalculateRestBiomassData, self).__init__(parent)

        self.setupUi(self)

        self.first_show = True

    def showEvent(self, event):
        super(DlgCalculateRestBiomassData, self).showEvent(event)

        self.use_custom_initial.populate()
        self.use_custom_final.populate()

        self.radioButton_carbon_custom.setEnabled(False)

        if self.reset_tab_on_showEvent:
            self.TabBox.setCurrentIndex(0)

        if self.first_show:
            self.first_show = False
            # Ensure the special value text (set to " ") is displayed by 
            # default
            self.hansen_fc_threshold.setSpecialValueText(' ')
            self.hansen_fc_threshold.setValue(self.hansen_fc_threshold.minimum())

        self.use_hansen.toggled.connect(self.lc_source_changed)
        self.use_custom.toggled.connect(self.lc_source_changed)
        # Ensure that dialogs are enabled/disabled as appropriate
        self.lc_source_changed()

        # Setup bounds for Hansen data
        start_year = QDate(self.datasets['Forest cover']['Hansen']['Start year'], 1, 1)
        end_year = QDate(self.datasets['Forest cover']['Hansen']['End year'], 12, 31)
        self.hansen_bl_year.setMinimumDate(start_year)
        self.hansen_bl_year.setMaximumDate(end_year)
        self.hansen_tg_year.setMinimumDate(start_year)
        self.hansen_tg_year.setMaximumDate(end_year)

    def lc_source_changed(self):
        if self.use_hansen.isChecked():
            self.groupBox_hansen_period.setEnabled(True)
            self.groupBox_hansen_threshold.setEnabled(True)
            self.groupBox_custom_bl.setEnabled(False)
            self.groupBox_custom_tg.setEnabled(False)
        elif self.use_custom.isChecked():
            QtGui.QMessageBox.information(None, self.tr("Coming soon!"),
                                       self.tr("Custom forest cover data support is coming soon!"), None)
            self.use_hansen.setChecked(True)
            # self.groupBox_hansen_period.setEnabled(False)
            # self.groupBox_hansen_threshold.setEnabled(False)
            # self.groupBox_custom_bl.setEnabled(True)
            # self.groupBox_custom_tg.setEnabled(True)


    def get_biomass_dataset(self):
        if self.radioButton_carbon_woods_hole.isChecked():
            return 'woodshole'
        elif self.radioButton_carbon_geocarbon.isChecked():
            return 'geocarbon'
        elif self.radioButton_carbon_custom.isChecked():
            return 'custom'
        else:
            return None

    def get_method(self):
        if self.radioButton_rootshoot_ipcc.isChecked():
            return 'ipcc'
        elif self.radioButton_rootshoot_mokany.isChecked():
            return 'mokany'
        else:
            return None

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateRestBiomassData, self).btn_calculate()
        if not ret:
            return
        if (self.hansen_fc_threshold.text() == self.hansen_fc_threshold.specialValueText()) and \
                self.use_hansen.isChecked():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr(u"Enter a value for percent cover that is considered forest."))
            return

        method = self.get_method()
        if not method:
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr(u"Choose a method for calculating the root to shoot ratio."))
            return

        biomass_data = self.get_biomass_dataset()
        if not method:
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr(u"Choose a biomass dataset."))
            return


        if self.use_custom.isChecked():
            self.calculate_locally(method, biomass_data)
        else:
            self.calculate_on_GEE(method, biomass_data)

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

    def calculate_locally(self, method, biomass_data):
        if not self.use_custom.isChecked():
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

        # TODO: Code this - see the SOC code for a model

    def calculate_on_GEE(self, method, biomass_data):
        self.close()

        crosses_180th, geojsons = self.aoi.bounding_box_gee_geojson()
        payload = {'year_start': self.hansen_bl_year.date().year(),
                   'year_end': self.hansen_tg_year.date().year(),
                   'fc_threshold': int(self.hansen_fc_threshold.text().replace('%', '')),
                   'method': method,
                   'biomass_data': biomass_data,
                   'geojsons': json.dumps(geojsons),
                   'crs': self.aoi.get_crs_dst_wkt(),
                   'crosses_180th': crosses_180th,
                   'task_name': self.options_tab.task_name.text(),
                   'task_notes': self.options_tab.task_notes.toPlainText()}

        resp = run_script(get_script_slug('total-carbon'), payload)

        if resp:
            mb.pushMessage(QtGui.QApplication.translate("LDMP", "Submitted"),
                           QtGui.QApplication.translate("LDMP", "Total carbon submitted to Google Earth Engine."),
                           level=0, duration=5)
        else:
            mb.pushMessage(QtGui.QApplication.translate("LDMP", "Error"),
                           QtGui.QApplication.translate("LDMP", "Unable to submit total carbon task to Google Earth Engine."),
                           level=0, duration=5)

class RestBiomassSummaryWorker(AbstractWorker):
    def __init__(self, src_file, year_start, year_end):
        AbstractWorker.__init__(self)

        self.src_file = src_file
        self.year_start = year_start
        self.year_end = year_end

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        src_ds = gdal.Open(self.src_file)

        band_f_loss = src_ds.GetRasterBand(1)
        band_tc = src_ds.GetRasterBand(2)

        block_sizes = band_f_loss.GetBlockSize()
        xsize = band_f_loss.XSize
        ysize = band_f_loss.YSize
        n_out_bands = 1

        x_block_size = block_sizes[0]
        y_block_size = block_sizes[1]

        src_gt = src_ds.GetGeoTransform()

        # Width of cells in longitude
        long_width = src_gt[1]
        # Set initial lat ot the top left corner latitude
        lat = src_gt[3]
        # Width of cells in latitude
        pixel_height = src_gt[5]

        area_missing = 0
        area_non_forest = 0
        area_water = 0
        area_site = 0
        initial_forest_area = 0
        initial_carbon_total = 0
        forest_change = np.zeros((self.year_end - self.year_start, 1))
        carbon_change = np.zeros((self.year_end - self.year_start, 1))

        blocks = 0
        for y in xrange(0, ysize, y_block_size):
            if self.killed:
                log("Processing of {} killed by user after processing {} out of {} blocks.".format(self.prod_out_file, y, ysize))
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

                f_loss_array = band_f_loss.ReadAsArray(x, y, cols, rows)
                tc_array = band_tc.ReadAsArray(x, y, cols, rows)

                # Caculate cell area for each horizontal line
                cell_areas = np.array([calc_cell_area(lat + pixel_height*n, lat + pixel_height*(n + 1), long_width) for n in range(rows)])
                cell_areas.shape = (cell_areas.size, 1)
                # Make an array of the same size as the input arrays containing 
                # the area of each cell (which is identicalfor all cells ina 
                # given row - cell areas only vary among rows)
                cell_areas_array = np.repeat(cell_areas, cols, axis=1)

                initial_forest_pixels = (f_loss_array == 0) | (f_loss_array > (self.year_start - 2000))
                # The site area includes everything that isn't masked
                area_missing = area_missing + np.sum(((f_loss_array == -32768) | (tc_array == -32768)) * cell_areas_array)
                area_water = area_water + np.sum((f_loss_array == -2) * cell_areas_array)
                area_non_forest = area_non_forest + np.sum((f_loss_array == -1) * cell_areas_array)
                area_site = area_site + np.sum((f_loss_array != -32767) * cell_areas_array)
                initial_forest_area = initial_forest_area + np.sum(initial_forest_pixels * cell_areas_array)
                initial_carbon_total = initial_carbon_total +  np.sum(initial_forest_pixels * tc_array * (tc_array >= 0) * cell_areas_array)

                for n in range(self.year_end - self.year_start):
                    # Note the codes are year - 2000
                    forest_change[n] = forest_change[n] - np.sum((f_loss_array == self.year_start - 2000 + n + 1) * cell_areas_array)
                    # Check units here - is tc_array in per m or per ha?
                    carbon_change[n] = carbon_change[n] - np.sum((f_loss_array == self.year_start - 2000 + n + 1) * tc_array * cell_areas_array)

                blocks += 1
            lat += pixel_height * rows
        self.progress.emit(100)

        if self.killed:
            return None
        else:
            # Convert all area tables from meters into hectares
            forest_change = forest_change * 1e-4
            # Note that carbon is scaled by 10
            carbon_change = carbon_change * 1e-4 / 10
            area_missing = area_missing * 1e-4
            area_water = area_water * 1e-4
            area_non_forest = area_non_forest * 1e-4
            area_site = area_site * 1e-4
            initial_forest_area = initial_forest_area * 1e-4
            # Note that carbon is scaled by 10
            initial_carbon_total = initial_carbon_total * 1e-4 / 10

        return list((forest_change, carbon_change, area_missing, area_water, 
                     area_non_forest, area_site, initial_forest_area, 
                     initial_carbon_total))

class DlgCalculateRestBiomassSummaryTable(DlgCalculateBase, Ui_DlgCalculateRestBiomassSummaryTable):
    def __init__(self, parent=None):
        super(DlgCalculateRestBiomassSummaryTable, self).__init__(parent)

        self.setupUi(self)

        self.browse_output_file_table.clicked.connect(self.select_output_file_table)

    def showEvent(self, event):
        super(DlgCalculateRestBiomassSummaryTable, self).showEvent(event)

        self.combo_layer_f_loss.populate()
        self.combo_layer_tc.populate()

    def select_output_file_table(self):
        f = QtGui.QFileDialog.getSaveFileName(self,
                                              self.tr('Choose a filename for the summary table'),
                                              QSettings().value("LDMP/output_dir", None),
                                              self.tr('Summary table file (*.xlsx)'))
        if f:
            if os.access(os.path.dirname(f), os.W_OK):
                QSettings().setValue("LDMP/output_dir", os.path.dirname(f))
                self.output_file_table.setText(f)
            else:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr(u"Cannot write to {}. Choose a different file.".format(f), None))

    def btn_calculate(self):
        ######################################################################
        # Check that all needed output files are selected
        if not self.output_file_table.text():
            QtGui.QMessageBox.information(None, self.tr("Error"),
                                          self.tr("Choose an output file for the summary table."), None)
            return

        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateRestBiomassSummaryTable, self).btn_calculate()
        if not ret:
            return

        ######################################################################
        # Check that all needed input layers are selected
        if len(self.combo_layer_f_loss.layer_list) == 0:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("You must add a forest loss layer to your map before you can use the carbon change summary tool."), None)
            return
        if len(self.combo_layer_tc.layer_list) == 0:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("You must add a total carbon layer to your map before you can use the carbon change summary tool."), None)
            return
        #######################################################################
        # Check that the layers cover the full extent needed
            if self.aoi.calc_frac_overlap(QgsGeometry.fromRect(self.combo_layer_f_loss.get_layer().extent())) < .99:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Area of interest is not entirely within the forest loss layer."), None)
                return
            if self.aoi.calc_frac_overlap(QgsGeometry.fromRect(self.combo_layer_tc.get_layer().extent())) < .99:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Area of interest is not entirely within the total carbon layer."), None)
                return

        #######################################################################
        # Check that all of the productivity layers have the same resolution 
        # and CRS
        def res(layer):
            return (round(layer.rasterUnitsPerPixelX(), 10), round(layer.rasterUnitsPerPixelY(), 10))

        if res(self.combo_layer_f_loss.get_layer()) != res(self.combo_layer_tc.get_layer()):
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Resolutions of forest loss and total carbon layers do not match."), None)
            return

        self.close()

        #######################################################################
        # Load all datasets to VRTs (to select only the needed bands)
        f_loss_vrt = self.combo_layer_f_loss.get_vrt()
        tc_vrt = self.combo_layer_tc.get_vrt()

        # Figure out start and end dates
        year_start = self.combo_layer_f_loss.get_band_info()['metadata']['year_start']
        year_end = self.combo_layer_f_loss.get_band_info()['metadata']['year_end']

        # Remember the first value is an indication of whether dataset is 
        # wrapped across 180th meridian
        wkts = self.aoi.meridian_split('layer', 'wkt', warn=False)[1]
        bbs = self.aoi.get_aligned_output_bounds(f_loss_vrt)

        for n in range(len(wkts)):
            # Compute the pixel-aligned bounding box (slightly larger than 
            # aoi). Use this instead of croptocutline in gdal.Warp in order to 
            # keep the pixels aligned with the chosen productivity layer.
        
            # Combines SDG 15.3.1 input raster into a VRT and crop to the AOI
            indic_vrt = tempfile.NamedTemporaryFile(suffix='.vrt').name
            log(u'Saving indicator VRT to: {}'.format(indic_vrt))
            # The plus one is because band numbers start at 1, not zero
            gdal.BuildVRT(indic_vrt,
                          [f_loss_vrt, tc_vrt],
                          outputBounds=bbs[n],
                          resolution='highest',
                          resampleAlg=gdal.GRA_NearestNeighbour,
                          separate=True)

            masked_vrt = tempfile.NamedTemporaryFile(suffix='.tif').name
            log(u'Saving forest loss/carbon clipped file to {}'.format(masked_vrt))
            clip_worker = StartWorker(ClipWorker, 'masking layers (part {} of {})'.format(n + 1, len(wkts)), 
                                      indic_vrt, masked_vrt, 
                                      json.loads(QgsGeometry.fromWkt(wkts[n]).exportToGeoJSON()),
                                      bbs[n])
            if not clip_worker.success:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Error masking carbon change input layers."), None)
                return

            ######################################################################
            #  Calculate carbon change table
            log('Calculating summary table...')
            tc_summary_worker = StartWorker(RestBiomassSummaryWorker,
                                            'calculating summary table (part {} of {})'.format(n + 1, len(wkts)),
                                            masked_vrt,
                                            year_start,
                                            year_end)
            if not tc_summary_worker.success:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Error calculating carbon change summary table."), None)
                return
            else:
                if n == 0:
                     forest_change, \
                             carbon_change, \
                             area_missing, \
                             area_water, \
                             area_non_forest, \
                             area_site, \
                             initial_forest_area, \
                             initial_carbon_total = tc_summary_worker.get_return()
                else:
                     this_forest_change, \
                             this_carbon_change, \
                             this_area_missing, \
                             this_area_water, \
                             this_area_non_forest, \
                             this_area_site, \
                             this_initial_forest_area, \
                             this_initial_carbon_total = tc_summary_worker.get_return()
                     forest_change = forest_change + this_forest_change
                     carbon_change = carbon_change + this_carbon_change
                     area_missing = area_missing + this_area_missing
                     area_water = area_water + this_area_water
                     area_non_forest = area_non_forest + this_area_non_forest
                     area_site = area_site + this_area_site
                     initial_forest_area = initial_forest_area + this_initial_forest_area
                     initial_carbon_total = initial_carbon_total + this_initial_carbon_total

        log('area_missing: {}'.format(area_missing))
        log('area_water: {}'.format(area_water))
        log('area_non_forest: {}'.format(area_non_forest))
        log('area_site: {}'.format(area_site))
        log('initial_forest_area: {}'.format(initial_forest_area))
        log('initial_carbon_total: {}'.format(initial_carbon_total))
        log('forest loss: {}'.format(forest_change))
        log('carbon loss: {}'.format(carbon_change))

        make_summary_table(forest_change, carbon_change, area_missing, area_water, 
                           area_non_forest, area_site, initial_forest_area, 
                           initial_carbon_total, year_start, year_end, 
                           self.output_file_table.text())

def make_summary_table(forest_change, carbon_change, area_missing, area_water, 
                       area_non_forest, area_site, initial_forest_area, 
                       initial_carbon_total, year_start, year_end, out_file):
                          
    def tr(s):
        return QtGui.QApplication.translate("LDMP", s)

    wb = openpyxl.load_workbook(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'data', 'summary_table_rest_biomass.xlsx'))

    ##########################################################################
    # SDG table
    ws_summary = wb.get_sheet_by_name('Total Carbon Summary Table')
    ws_summary.cell(6, 3).value = initial_forest_area
    ws_summary.cell(7, 3).value = area_non_forest
    ws_summary.cell(8, 3).value = area_water
    ws_summary.cell(9, 3).value = area_missing
    #ws_summary.cell(10, 3).value = area_site

    ws_summary.cell(18, 2).value = initial_forest_area
    ws_summary.cell(18, 4).value = initial_carbon_total
    write_col_to_sheet(ws_summary, np.arange(year_start, year_end + 1), 1, 18) # Years
    write_table_to_sheet(ws_summary, forest_change, 19, 3)
    write_table_to_sheet(ws_summary, carbon_change, 19, 5)

    try:
        ws_summary_logo = Image(os.path.join(os.path.dirname(__file__), 'data', 'trends_earth_logo_bl_300width.png'))
        ws_summary.add_image(ws_summary_logo, 'E1')
    except ImportError:
        # add_image will fail on computers without PIL installed (this will be 
        # an issue on some Macs, likely others). it is only used here to add 
        # our logo, so no big deal.
        pass

    try:
        wb.save(out_file)
        log(u'Summary table saved to {}'.format(out_file))
        QtGui.QMessageBox.information(None, QtGui.QApplication.translate("LDMP", "Success"),
                                      QtGui.QApplication.translate("LDMP", u'Summary table saved to {}'.format(out_file)))

    except IOError:
        log(u'Error saving {}'.format(out_file))
        QtGui.QMessageBox.critical(None, QtGui.QApplication.translate("LDMP", "Error"),
                                   QtGui.QApplication.translate("LDMP", u"Error saving output table - check that {} is accessible and not already open.".format(out_file)), None)
