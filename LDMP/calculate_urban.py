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
from LDMP.gui.DlgCalculateUrbanData import Ui_DlgCalculateUrbanData
from LDMP.gui.DlgCalculateUrbanSummaryTable import Ui_DlgCalculateUrbanSummaryTable
from LDMP.layers import add_layer, create_local_json_metadata
from LDMP.worker import AbstractWorker, StartWorker
from LDMP.schemas.schemas import BandInfo, BandInfoSchema
from LDMP.summary import *


class UrbanWorker(AbstractWorker):
    def __init__(self, src_filed):
        AbstractWorker.__init__(self)

        self.src_file = src_file

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        src_ds = gdal.Open(self.src_file)

        band_f_loss = src_ds.GetRasterBand(1)

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


                # Process: Con
                arcpy.gp.Con_sa(Band_1__2_, Input_true_raster_or_constant_value__2_, r01_urb2000_tif, Input_false_raster_or_constant_value__2_, "\"Value\" = 1")
                # Process: Focal Statistics (2)
                arcpy.gp.FocalStatistics_sa(r01_urb2000_tif, r02_urb2000_mean_tif, "Circle 17 CELL", "MEAN", "DATA")
                # Process: Reclassify (4)
                arcpy.Reclassify_3d(r02_urb2000_mean_tif, "VALUE", "0 0.250000 1;0.250000 0.500000 2;0.500000 1 3", r03_urb2000_mean_class_tif, "DATA")
                # Process: Con (18)
                arcpy.gp.Con_sa(r01_urb2000_tif, r03_urb2000_mean_class_tif, r04_urb2000_3cl_tif, Input_false_raster_or_constant_value__11_, "Value = 1")
                # Process: Set Null (2)
                arcpy.gp.SetNull_sa(r04_urb2000_3cl_tif, Input_false_raster_or_constant_value__12_, r05_urb2000_tif, "Value IN (0,1)")
                # Process: Euclidean Distance (2)
                arcpy.gp.EucDistance_sa(r05_urb2000_tif, r06_urb2000_eudist_tif, "", "2.69494585235857E-04", Output_direction_raster__2_)
                # Process: Raster Calculator (7)
                arcpy.gp.RasterCalculator_sa("Con((\"%r06_urb2000_eudist.tif%\" < 0.000898315)  & (\"%r04_urb2000_3cl.tif%\" == 0),4,0)", r12_fringe_2010_tif)
                # Process: Set Null (5)
                arcpy.gp.SetNull_sa(r06_urb2000_eudist_tif, Input_false_raster_or_constant_value__14_, r08_open2000_tif, "Value < 0.000898315")
                # Process: Region Group (2)
                arcpy.gp.RegionGroup_sa(r08_open2000_tif, r09_open2000_regions_tif, "FOUR", "WITHIN", "ADD_LINK", "")
                # Process: Con (19)
                arcpy.gp.Con_sa(r06_urb2000_eudist_tif, Input_true_raster_or_constant_value__7_, r07_open2000_bin_tif, Input_false_raster_or_constant_value__13_, Lenght_of_the_longest_open_space_in_your_city)
                # Process: Zonal Statistics (2)
                arcpy.gp.ZonalStatistics_sa(r09_open2000_regions_tif, "Value", r07_open2000_bin_tif, r10_open2000_mean_tif, "MEAN", "DATA")
                # Process: Reclassify (5)
                arcpy.gp.Reclassify_sa(r10_open2000_mean_tif, "VALUE", "0 0.999990 0;1 5;NODATA 0", r11_captured_2000_tif, "DATA")
                # Process: Raster Calculator (4)
                arcpy.gp.RasterCalculator_sa("\"%r04_urb2000_3cl.tif%\"+\"%r12_fringe_2010.tif%\"+\"%r11_captured_2000.tif%\"", r13_city2000_tif)




















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


class DlgCalculateUrbanData(DlgCalculateBase, Ui_DlgCalculateUrbanData):
    def __init__(self, parent=None):
        super(DlgCalculateUrbanData, self).__init__(parent)

        self.setupUi(self)

        self.urban_thresholds_updated()

        self.spinBox_pct_urban.valueChanged.connect(self.urban_thresholds_updated)
        self.spinBox_pct_suburban.valueChanged.connect(self.urban_thresholds_updated)

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateUrbanData, self).btn_calculate()
        if not ret:
            return

        self.calculate_on_GEE()

    def urban_thresholds_updated(self):
        self.spinBox_pct_suburban.setRange(0, self.spinBox_pct_urban.value() - 1)
        self.spinBox_pct_urban.setRange(self.spinBox_pct_suburban.value() + 1, 100)

    def get_pop_def_is_un(self):
        if self.pop_adjusted.isChecked():
            return True
        elif self.pop_unadjusted.isChecked():
            return False
        else:
            # Should never get here
            raise

    def calculate_on_GEE(self):
        self.close()

        crosses_180th, geojsons = self.aoi.bounding_box_gee_geojson()
        payload = {'un_adju': self.get_pop_def_is_un(),
                   'isi_thr': self.spinBox_isi_thr.value(),
                   'ntl_thr': self.spinBox_ntl_thr.value(),
                   'wat_thr': self.spinBox_wat_thr.value(),
                   'cap_ope': self.spinBox_cap_ope.value(),
                   'pct_suburban': self.spinBox_pct_suburban.value()/100.,
                   'pct_urban': self.spinBox_pct_urban.value()/100.,
                   'geojsons': json.dumps(geojsons),
                   'crs': self.aoi.get_crs_dst_wkt(),
                   'crosses_180th': crosses_180th,
                   'task_name': self.options_tab.task_name.text(),
                   'task_notes': self.options_tab.task_notes.toPlainText()}

        resp = run_script(get_script_slug('urban-area'), payload)

        if resp:
            mb.pushMessage(QtGui.QApplication.translate("LDMP", "Submitted"),
                           QtGui.QApplication.translate("LDMP", "Urban area change calculation submitted to Google Earth Engine."),
                           level=0, duration=5)
        else:
            mb.pushMessage(QtGui.QApplication.translate("LDMP", "Error"),
                           QtGui.QApplication.translate("LDMP", "Unable to submit urban area task to Google Earth Engine."),
                           level=0, duration=5)


class DlgCalculateUrbanSummaryTable(DlgCalculateBase, Ui_DlgCalculateUrbanSummaryTable):
    def __init__(self, parent=None):
        super(DlgCalculateUrbanSummaryTable, self).__init__(parent)

        self.setupUi(self)

        self.browse_output_file_table.clicked.connect(self.select_output_file_table)

    def showEvent(self, event):
        super(DlgCalculateUrbanSummaryTable, self).showEvent(event)

        self.combo_layer_urban_series.populate()

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
        ret = super(DlgCalculateUrbanSummaryTable, self).btn_calculate()
        if not ret:
            return

        ######################################################################
        # Check that all needed input layers are selected
        if len(self.combo_layer_urban_series.layer_list) == 0:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("You must add an urban series layer to your map before you can use the urban change summary tool."), None)
            return

        #######################################################################
        # Check that the layers cover the full extent needed
            if self.aoi.calc_frac_overlap(QgsGeometry.fromRect(self.combo_layer_urban_series.get_layer().extent())) < .99:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Area of interest is not entirely within the urban series layer."), None)
                return

        #######################################################################
        # Load all datasets to VRTs (to select only the needed bands)
        band_infos = get_band_infos(self.combo_layer_urban_series.get_data_file())

        urban_annual_band_indices = [i for i, bi in enumerate(band_infos) if bi['name'] == 'Urban']
        urban_annual_band_indices.sort(key=lambda i: band_infos[i]['metadata']['year'])
        urban_years = [bi['metadata']['year'] for bi in band_infos if bi['name'] == 'Urban']
        urban_files = []
        for i in urban_annual_band_indices:
            f = tempfile.NamedTemporaryFile(suffix='.vrt').name
            # Add once since band numbers don't start at zero
            gdal.BuildVRT(f,
                          self.combo_layer_urban_series.get_data_file(),
                          bandList=[i + 1])
            urban_files.append(f)


        pop_annual_band_indices = [i for i, bi in enumerate(band_infos) if bi['name'] == 'Population']
        pop_annual_band_indices.sort(key=lambda i: band_infos[i]['metadata']['year'])
        pop_years = [bi['metadata']['year'] for bi in band_infos if bi['name'] == 'Population']
        pop_files = []
        for i in pop_annual_band_indices:
            f = tempfile.NamedTemporaryFile(suffix='.vrt').name
            # Add once since band numbers don't start at zero
            gdal.BuildVRT(f,
                          self.combo_layer_pop_series.get_data_file(),
                          bandList=[i + 1])
            pop_files.append(f)

        assert (len(pop_files) == len(urban_files))
        assert (urban_years == pop_years)

        in_files = list(urban_files)
        in_files.extend(pop_files)
        urban_band_nums = np.arange(len(urban_files)) + 1
        pop_band_nums = np.arange(len(pop_files)) + 1 + urban_band_nums.max()

        # Remember the first value is an indication of whether dataset is 
        # wrapped across 180th meridian
        wkts = self.aoi.meridian_split('layer', 'wkt', warn=False)[1]
        bbs = self.aoi.get_aligned_output_bounds(urban_files[1])

        ######################################################################
        # Process the wkts using a summary worker
        for n in range(len(wkts)):
            # Compute the pixel-aligned bounding box (slightly larger than 
            # aoi). Use this instead of croptocutline in gdal.Warp in order to 
            # keep the pixels aligned with the chosen productivity layer.
        
            # Combines SDG 15.3.1 input raster into a VRT and crop to the AOI
            indic_vrt = tempfile.NamedTemporaryFile(suffix='.vrt').name
            log(u'Saving indicator VRT to: {}'.format(indic_vrt))
            # The plus one is because band numbers start at 1, not zero
            gdal.BuildVRT(indic_vrt,
                          in_files,
                          outputBounds=bbs[n],
                          resolution='highest',
                          resampleAlg=gdal.GRA_NearestNeighbour,
                          separate=True)

            masked_vrt = tempfile.NamedTemporaryFile(suffix='.tif').name
            log(u'Saving urban clipped files to {}'.format(masked_vrt))
            clip_worker = StartWorker(ClipWorker, 'masking layers (part {} of {})'.format(n + 1, len(wkts)), 
                                      indic_vrt, masked_vrt, 
                                      json.loads(QgsGeometry.fromWkt(wkts[n]).exportToGeoJSON()),
                                      bbs[n])
            if not clip_worker.success:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Error masking urban change input layers."), None)
                return

            ######################################################################
            #  Calculate urban change table
            log('Calculating summary table...')
            urban_summary_worker = StartWorker(UrbanSummaryWorker,
                                               'calculating summary table (part {} of {})'.format(n + 1, len(wkts)),
                                               masked_vrt,
                                               urban_band_nums, pop_band_nums)
            if not urban_summary_worker.success:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Error calculating urban change summary table."), None)
                return
            else:
                if n == 0:
                     areas, \
                             populations = urban_summary_worker.get_return()
                else:
                     these_areas, \
                             these_populations = urban_summary_worker.get_return()
                     areas = areas + these_areas
                     populations = populations + these_populations

        log('aresa: {}'.format(areas))
        log('populations: {}'.format(populations))

        make_summary_table(areas, populations, self.output_file_table.text())


def make_summary_table(areas, populations, out_file):
                          
    def tr(s):
        return QtGui.QApplication.translate("LDMP", s)

    wb = openpyxl.load_workbook(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'data', 'UrbanSummaryTable.xlsx'))

    ##########################################################################
    # SDG table
    ws_summary = wb.get_sheet_by_name('SDG 11.3.1 Summary Table')
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
