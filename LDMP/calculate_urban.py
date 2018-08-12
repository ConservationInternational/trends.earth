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
from LDMP.schemas.schemas import BandInfo, BandInfoSchema
from LDMP.summary import *


class TCSummaryWorker(AbstractWorker):
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

def make_summary_table(forest_change, carbon_change, area_missing, area_water, 
                       area_non_forest, area_site, initial_forest_area, 
                       initial_carbon_total, year_start, year_end, out_file):
                          
    def tr(s):
        return QtGui.QApplication.translate("LDMP", s)

    wb = openpyxl.load_workbook(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'data', 'CarbonSummaryTable.xlsx'))

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
