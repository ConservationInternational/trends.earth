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
import json

from pathlib import Path

from osgeo import (
    gdal,
    ogr,
    osr,
)

from PyQt5 import (
    QtCore,
    QtWidgets,
    uic,
)

import qgis.gui
from qgis.core import QgsGeometry
from qgis.utils import iface

from . import (
    conf,
    data_io,
    worker,
)
from .algorithms import models
from .calculate import (
    DlgCalculateBase,
    ldn_recode_state,
    ldn_recode_traj,
    ldn_make_prod5,
    ldn_total_deg,
    ldn_total_by_trans,
)
from .jobs.manager import job_manager
from .lc_setup import (
    LCSetupWidget,
    LCDefineDegradationWidget,
)
from .localexecution import ldn
from .summary import *

DlgCalculateOneStepUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateOneStep.ui"))
DlgCalculateLdnSummaryTableAdminUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateLDNSummaryTableAdmin.ui"))

mb = iface.messageBar()


class tr_calculate_ldn(object):
    def tr(message):
        return QtCore.QCoreApplication.translate("tr_calculate_ldn", message)


class DlgCalculateOneStep(DlgCalculateBase, DlgCalculateOneStepUi):

    def __init__(
            self,
            iface: qgis.gui.QgisInterface,
            script: models.ExecutionScript,
            parent: QtWidgets.QWidget = None
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)
        self.update_time_bounds()
        self.mode_te_prod.toggled.connect(self.update_time_bounds)
        self.lc_setup_widget = LCSetupWidget()
        self.lc_define_deg_widget = LCDefineDegradationWidget()

        self.initiliaze_settings()

    def update_time_bounds(self):
        if self.mode_te_prod.isChecked():
            ndvi_dataset = conf.REMOTE_DATASETS["NDVI"]["MODIS (MOD13Q1, annual)"]
            # ndvi_dataset = self.datasets['NDVI']['MODIS (MOD13Q1, annual)']
            start_year_ndvi = ndvi_dataset['Start year']
            end_year_ndvi = ndvi_dataset['End year']
        else:
            start_year_ndvi = 2000
            end_year_ndvi = 2015

        lc_dataset = conf.REMOTE_DATASETS["Land cover"]["ESA CCI"]
        start_year_lc = lc_dataset['Start year']
        end_year_lc = lc_dataset['End year']

        
        start_year = QtCore.QDate(max(start_year_ndvi, start_year_lc), 1, 1)
        end_year = QtCore.QDate(min(end_year_ndvi, end_year_lc), 1, 1)

        self.year_initial.setMinimumDate(start_year)
        self.year_initial.setMaximumDate(end_year)
        self.year_final.setMinimumDate(start_year)
        self.year_final.setMaximumDate(end_year)
        
    def showEvent(self, event):
        super(DlgCalculateOneStep, self).showEvent(event)
        # TODO: Temporarily hide these boxes until custom LC support for SOC is 
        # implemented on GEE
        self.lc_setup_widget.use_esa.setChecked(True)
        self.lc_setup_widget.use_custom.hide()
        self.lc_setup_widget.groupBox_custom_bl.hide()
        self.lc_setup_widget.groupBox_custom_tg.hide()
        
        # Hide the land cover ESA period box, since only one period is used in 
        # this dialog - the one on the main setup tab
        self.lc_setup_widget.groupBox_esa_period.hide()

        if self.land_cover_contents.layout() is None:
            layout = QtWidgets.QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(1)
            layout.addWidget(self.lc_setup_widget)
            self.land_cover_contents.setFrameShape(0)
            self.land_cover_contents.setLayout(layout)

        if self.scroll_area.layout() is None:
            scroll_container = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(1)
            layout.addWidget(self.lc_define_deg_widget)
            scroll_container.setLayout(layout)
            self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
            self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            self.scroll_area.setWidgetResizable(True)
            self.scroll_area.setWidget(scroll_container)


        #######################################################################
        #######################################################################
        # Hack to calculate multiple countries at once for workshop preparation
        #######################################################################
        #######################################################################
        # from qgis.PyQt.QtCore import QTimer, Qt
        # from qgis.PyQt.QtWidgets import QMessageBox, QApplication
        # from qgis.PyQt.QtTest import QTest
        # from LDMP.download import read_json
        # from LDMP.worker import AbstractWorker, StartWorker
        # from time import sleep
        #
        # class SleepWorker(AbstractWorker):
        #     def __init__(self, time):
        #         super(SleepWorker, self).__init__()
        #         self.sleep_time = time
        #
        #     def work(self):
        #         for n in range(100):
        #             if not self.killed:
        #                 sleep(self.sleep_time / float(100))
        #                 self.progress.emit(n)
        #             else:
        #                 return False
        #         return True
        #
        # # Use Trends.Earth for calculation
        # self.mode_te_prod.setChecked(True)
        #
        # # Ensure any message boxes that open are closed within 1 second
        # def close_msg_boxes():
        #     for w in QApplication.topLevelWidgets():
        #         if isinstance(w, QMessageBox):
        #             print('Closing message box')
        #             QTest.keyClick(w, Qt.Key_Enter)
        # timer = QTimer()
        # timer.timeout.connect(close_msg_boxes)
        # timer.start(1000)
        #
        # first_row = self.area_tab.area_admin_0.findText('Burundi')
        # last_row = self.area_tab.area_admin_0.findText('Portugal')
        # log('First country: {}'.format(self.area_tab.area_admin_0.itemText(first_row)))
        # log('Last country: {}'.format(self.area_tab.area_admin_0.itemText(last_row)))
        #
        # # First make sure all admin boundaries are pre-downloaded
        # for row in range(first_row, last_row):
        #     index = self.area_tab.area_admin_0.model().index(row, 0)
        #     country = self.area_tab.area_admin_0.model().data(index)
        #     adm0_a3 = self.area_tab.admin_bounds_key[country]['code']
        #     admin_polys = read_json('admin_bounds_polys_{}.json.gz'.format(adm0_a3), verify=False)
        #
        # for row in range(first_row, last_row):
        #     self.area_tab.area_admin_0.setCurrentIndex(row)
        #     index = self.area_tab.area_admin_0.model().index(row, 0)
        #     country = self.area_tab.area_admin_0.model().data(index)
        #     name = u'{}_All_Indicators_TE'.format(country)
        #     log(name)
        #     # self.options_tab.task_name.setText(name)
        #     # self.btn_calculate()
        #     
        #     # Sleep without freezing interface
        #     sleep_worker = StartWorker(SleepWorker, 'sleeping', 60)
        #     if not deg_lc_clip_worker.success:
        #         break
        #
        #######################################################################
        #######################################################################
        # End hack
        #######################################################################
        #######################################################################

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateOneStep, self).btn_calculate()
        if not ret:
            return

        if (self.year_final.date().year() - self.year_initial.date().year()) < 10:
            QtWidgets.QMessageBox.warning(None, self.tr("Error"),
                                       self.tr("Initial and final year are less 10 years apart - more reliable results will be given if more data (years) are included in the analysis."))
        #     return

        self.close()

        #######################################################################
        # Online

        prod_traj_year_initial = self.year_initial.date().year()
        prod_traj_year_final = self.year_final.date().year()

        prod_perf_year_initial = self.year_initial.date().year()
        prod_perf_year_final = self.year_final.date().year()

        # Have productivity state consider the last 3 years for the current 
        # period, and the years preceding those last 3 for the baseline
        prod_state_year_bl_start = self.year_initial.date().year()
        prod_state_year_bl_end = self.year_final.date().year() - 3
        prod_state_year_tg_start = prod_state_year_bl_end + 1
        prod_state_year_tg_end = prod_state_year_bl_end + 3
        assert (prod_state_year_tg_end == self.year_final.date().year())

        lc_year_initial = self.year_initial.date().year()
        lc_year_final = self.year_final.date().year()

        soc_year_initial = self.year_initial.date().year()
        soc_year_final = self.year_final.date().year()

        if self.mode_te_prod.isChecked():
            prod_mode = 'Trends.Earth productivity'
        else:
            prod_mode = 'JRC LPD'

        crosses_180th, geojsons = self.gee_bounding_box
        payload = {'prod_mode': prod_mode,
                   'prod_traj_year_initial': prod_traj_year_initial,
                   'prod_traj_year_final': prod_traj_year_final,
                   'prod_perf_year_initial': prod_perf_year_initial,
                   'prod_perf_year_final': prod_perf_year_final,
                   'prod_state_year_bl_start': prod_state_year_bl_start,
                   'prod_state_year_bl_end': prod_state_year_bl_end,
                   'prod_state_year_tg_start': prod_state_year_tg_start,
                   'prod_state_year_tg_end': prod_state_year_tg_end,
                   'lc_year_initial': lc_year_initial,
                   'lc_year_final': lc_year_final,
                   'soc_year_initial': soc_year_initial,
                   'soc_year_final': soc_year_final,
                   'geojsons': json.dumps(geojsons),
                   'crs': self.aoi.get_crs_dst_wkt(),
                   'crosses_180th': crosses_180th,
                   'prod_traj_method': 'ndvi_trend',
                   'ndvi_gee_dataset': 'users/geflanddegradation/toolbox_datasets/ndvi_modis_2001_2019',
                   'climate_gee_dataset': None,
                   'fl': .80,
                   'trans_matrix': self.lc_define_deg_widget.trans_matrix_get(),
                   'remap_matrix': self.lc_setup_widget.dlg_esa_agg.get_agg_as_list(),
                   'task_name': self.execution_name_le.text()}

        resp = job_manager.submit_remote_job(payload, self.script.id)

        if resp:
            main_msg = "Submitted"
            description = "SDG sub-indicator task submitted to Google Earth Engine."
        else:
            main_msg = "Error"
            description = (
                "Unable to submit SDG sub-indicator task to Google Earth Engine.")
        mb.pushMessage(
            self.tr(main_msg),
            self.tr(description),
            level=0,
            duration=5
        )

#TODO: Get this working in the jitted version in Numba
def ldn_total_by_trans_merge(total1, trans1, total2, trans2):
    """Calculates a total table for an array"""
    # Combine past totals with these totals
    trans = np.unique(np.concatenate((trans1, trans2)))
    totals = np.zeros(trans.size, dtype=np.float32)
    for i in range(trans.size):
        trans1_loc = np.where(trans1 == trans[i])[0]
        trans2_loc = np.where(trans2 == trans[i])[0]
        if trans1_loc.size > 0:
            totals[i] = totals[i] + total1[trans1_loc[0]]
        if trans2_loc.size > 0:
            totals[i] = totals[i] + total2[trans2_loc[0]]
    return trans, totals


class DegradationSummaryWorkerSDG(worker.AbstractWorker):
    def __init__(self, src_file, prod_band_nums, prod_mode, prod_out_file, 
                 lc_band_nums, soc_band_nums, mask_file):
        worker.AbstractWorker.__init__(self)
        
        self.src_file = src_file
        self.prod_band_nums = [int(x) for x in prod_band_nums]
        self.prod_mode = prod_mode
        self.prod_out_file = prod_out_file
        # Note the first entry in the lc_band_nums, and soc_band_nums lists is
        # the degradation layer for that dataset
        self.lc_band_nums = [int(x) for x in lc_band_nums]
        self.soc_band_nums = [int(x) for x in soc_band_nums]
        self.mask_file = mask_file

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        src_ds = gdal.Open(self.src_file)

        band_lc_deg = src_ds.GetRasterBand(self.lc_band_nums[0])
        band_lc_bl = src_ds.GetRasterBand(self.lc_band_nums[1])
        band_lc_tg = src_ds.GetRasterBand(self.lc_band_nums[-1])
        band_soc_deg = src_ds.GetRasterBand(self.soc_band_nums[0])

        mask_ds = gdal.Open(self.mask_file)
        band_mask = mask_ds.GetRasterBand(1)

        if self.prod_mode == 'Trends.Earth productivity':
            traj_band = src_ds.GetRasterBand(self.prod_band_nums[0])
            perf_band = src_ds.GetRasterBand(self.prod_band_nums[1])
            state_band = src_ds.GetRasterBand(self.prod_band_nums[2])
            block_sizes = traj_band.GetBlockSize()
            xsize = traj_band.XSize
            ysize = traj_band.YSize
            # Save the combined productivity indicator as well, in the second  
            # layer in the deg file
            n_out_bands = 2
        else:
            lpd_band = src_ds.GetRasterBand(self.prod_band_nums[0])
            block_sizes = band_lc_deg.GetBlockSize()
            xsize = band_lc_deg.XSize
            ysize = band_lc_deg.YSize
            n_out_bands = 1

        x_block_size = block_sizes[0]
        y_block_size = block_sizes[1]

        # Setup output file for SDG degradation indicator and combined 
        # productivity bands
        driver = gdal.GetDriverByName("GTiff")
        dst_ds_deg = driver.Create(self.prod_out_file, xsize, ysize, n_out_bands, 
                                   gdal.GDT_Int16, options=['COMPRESS=LZW'])
        src_gt = src_ds.GetGeoTransform()
        dst_ds_deg.SetGeoTransform(src_gt)
        dst_srs = osr.SpatialReference()
        dst_srs.ImportFromWkt(src_ds.GetProjectionRef())
        dst_ds_deg.SetProjection(dst_srs.ExportToWkt())

        # Width of cells in longitude
        long_width = src_gt[1]
        # Set initial lat ot the top left corner latitude
        lat = src_gt[3]
        # Width of cells in latitude
        pixel_height = src_gt[5]

        # log('long_width: {}'.format(long_width))
        # log('lat: {}'.format(lat))
        # log('pixel_height: {}'.format(pixel_height))

        xt = None
        # The first array in each row stores transitions, the second stores SOC 
        # totals for each transition
        soc_totals_table = [[np.array([], dtype=np.int16), np.array([], dtype=np.float32)] for i in range(len(self.soc_band_nums) - 1)]
        # The 8 below is for eight classes plus no data, and the minus one is 
        # because one of the bands is a degradation layer
        lc_totals_table = np.zeros((len(self.lc_band_nums) - 1, 8))
        sdg_tbl_overall = np.zeros((1, 4))
        sdg_tbl_prod = np.zeros((1, 4))
        sdg_tbl_soc = np.zeros((1, 4))
        sdg_tbl_lc = np.zeros((1, 4))

        # pr = cProfile.Profile()
        # pr.enable()

        blocks = 0
        for y in range(0, ysize, y_block_size):
            if y + y_block_size < ysize:
                rows = y_block_size
            else:
                rows = ysize - y
            for x in range(0, xsize, x_block_size):
                if self.killed:
                    log("Processing killed by user after processing {} out of {} blocks.".format(y, ysize))
                    break
                self.progress.emit(100 * (float(y) + (float(x)/xsize)*y_block_size) / ysize)
                if x + x_block_size < xsize:
                    cols = x_block_size
                else:
                    cols = xsize - x

                mask_array = band_mask.ReadAsArray(x, y, cols, rows)

                # Calculate cell area for each horizontal line
                # log('y: {}'.format(y))
                # log('x: {}'.format(x))
                # log('rows: {}'.format(rows))
                cell_areas = np.array([calc_cell_area(lat + pixel_height*n, lat + pixel_height*(n + 1), long_width) for n in range(rows)])
                cell_areas.shape = (cell_areas.size, 1)
                # Make an array of the same size as the input arrays containing 
                # the area of each cell (which is identical for all cells ina 
                # given row - cell areas only vary among rows)
                cell_areas_array = np.repeat(cell_areas, cols, axis=1).astype(np.float32)

                if self.prod_mode == 'Trends.Earth productivity':
                    traj_recode = ldn_recode_traj(traj_band.ReadAsArray(x, y, cols, rows))

                    state_recode = ldn_recode_state(state_band.ReadAsArray(x, y, cols, rows))

                    perf_array = perf_band.ReadAsArray(x, y, cols, rows)
                    prod5 = ldn_make_prod5(traj_recode, state_recode, perf_array, mask_array)

                    # Save combined productivity indicator for later visualization
                    dst_ds_deg.GetRasterBand(2).WriteArray(prod5, x, y)
                else:
                    lpd_array = lpd_band.ReadAsArray(x, y, cols, rows)
                    prod5 = lpd_array
                    # TODO: Below is temporary until missing data values are 
                    # fixed in LPD layer on GEE and missing data values are 
                    # fixed in LPD layer made by UNCCD for SIDS
                    prod5[(prod5 == 0) | (prod5 == 15)] = -32768
                    # Mask areas outside of AOI
                    prod5[mask_array == -32767] = -32767

                # Recode prod5 as stable, degraded, improved (prod3)
                prod3 = prod5.copy()
                prod3[(prod5 >= 1) & (prod5 <= 3)] = -1
                prod3[prod5 == 4] = 0
                prod3[prod5 == 5] = 1

                ################
                # Calculate SDG
                deg_sdg = prod3.copy()

                lc_array = band_lc_deg.ReadAsArray(x, y, cols, rows)
                deg_sdg[lc_array == -1] = -1

                a_lc_bl = band_lc_bl.ReadAsArray(x, y, cols, rows)
                a_lc_bl[mask_array == -32767] = -32767
                a_lc_tg = band_lc_tg.ReadAsArray(x, y, cols, rows)
                a_lc_tg[mask_array == -32767] = -32767
                water = a_lc_tg == 7
                water = water.astype(bool, copy=False)

                # Note SOC array is coded in percent change, so change of 
                # greater than 10% is improvement or decline.
                soc_array = band_soc_deg.ReadAsArray(x, y, cols, rows)
                deg_sdg[(soc_array <= -10) & (soc_array >= -100)] = -1

                
                # Allow improvements by lc or soc, only where one of the other 
                # two indicators doesn't indicate a decline
                deg_sdg[(deg_sdg == 0) & (lc_array == 1)] = 1
                deg_sdg[(deg_sdg == 0) & (soc_array >= 10) & (soc_array <= 100)] = 1

                
                # Ensure all NAs are carried over - note this was already done 
                # for the productivity layer above but need to do it again in 
                # case values from another layer overwrote those missing value 
                # indicators.
                
                # No data
                deg_sdg[(prod3 == -32768) | (lc_array == -32768) | (soc_array == -32768)] = -32768

                # Masked
                deg_sdg[mask_array == -32767] = -32767

                dst_ds_deg.GetRasterBand(1).WriteArray(deg_sdg, x, y)

                ###########################################################
                # Tabulate SDG 15.3.1 indicator
                # log('deg_sdg.dtype: {}'.format(str(deg_sdg.dtype)))
                # log('water.dtype: {}'.format(str(water.dtype)))
                # log('cell_areas.dtype: {}'.format(str(cell_areas.dtype)))
                
                sdg_tbl_overall = sdg_tbl_overall + ldn_total_deg(deg_sdg, water, cell_areas_array)
                sdg_tbl_prod = sdg_tbl_prod + ldn_total_deg(prod3, water, cell_areas_array)
                sdg_tbl_lc = sdg_tbl_lc + ldn_total_deg(lc_array,
                                                          np.array((mask_array == -32767) | water).astype(bool),
                                                          cell_areas_array)

                ###########################################################
                # Calculate SOC totals by transition, on annual basis
                a_trans_bl_tg = a_lc_bl*10 + a_lc_tg
                a_trans_bl_tg[np.logical_or(a_lc_bl < 1, a_lc_tg < 1)] = -32768
                a_trans_bl_tg[mask_array == -32767] = -32767

                # Calculate SOC totals). Note final units of soc_totals tables 
                # are tons C (summed over the total area of each class). Start 
                # at one because the first soc band is the degradation layer.
                for i in range(1, len(self.soc_band_nums)):
                    band_soc = src_ds.GetRasterBand(self.soc_band_nums[i])
                    a_soc = band_soc.ReadAsArray(x, y, cols, rows)
                    # Convert soilgrids data from per ha to per meter since 
                    # cell_area is in meters
                    a_soc = a_soc.astype(np.float32) / (100 * 100) # From per ha to per m
                    a_soc[mask_array == -32767] = -32767

                    this_trans, this_totals = ldn_total_by_trans(a_soc,
                                                                 a_trans_bl_tg,
                                                                 cell_areas_array)

                    new_trans, totals = ldn_total_by_trans_merge(this_totals, this_trans,
                                                                 soc_totals_table[i - 1][1], soc_totals_table[i - 1][0])
                    soc_totals_table[i - 1][0] = new_trans
                    soc_totals_table[i - 1][1] = totals
                    if i == 1:
                        # This is the baseline SOC - save it for later
                        a_soc_bl = a_soc.copy()
                    elif i == (len(self.soc_band_nums) - 1):
                        # This is the target (tg) SOC - save it for later
                        a_soc_tg = a_soc.copy()

                ###########################################################
                # Calculate transition crosstabs for productivity indicator
                this_rh, this_ch, this_xt = xtab(prod5, a_trans_bl_tg, cell_areas_array)
                # Don't use this transition xtab if it is empty (could 
                # happen if take a xtab where all of the values are nan's)
                if this_rh.size != 0:
                    if xt is None:
                        rh = this_rh
                        ch = this_ch
                        xt = this_xt
                    else:
                        rh, ch, xt = merge_xtabs(this_rh, this_ch, this_xt, rh, ch, xt)

                a_soc_frac_chg = a_soc_tg / a_soc_bl
                # Degradation in terms of SOC is defined as a decline of more 
                # than 10% (and improving increase greater than 10%)
                a_deg_soc = a_soc_frac_chg.astype(np.int16)
                a_deg_soc[(a_soc_frac_chg >= 0) & (a_soc_frac_chg <= .9)] = -1
                a_deg_soc[(a_soc_frac_chg > .9) & (a_soc_frac_chg < 1.1)] = 0
                a_deg_soc[a_soc_frac_chg >= 1.1] = 1
                # Mark areas that were no data in SOC
                a_deg_soc[a_soc_tg == -32768] = -32768 # No data
                # Carry over areas that were 1) originally masked, or 2) are 
                # outside the AOI, or 3) are water
                sdg_tbl_soc = sdg_tbl_soc + ldn_total_deg(a_deg_soc,
                                                            water,
                                                            cell_areas_array)

                # Start at one because remember the first lc band is the 
                # degradation layer
                for i in range(1, len(self.lc_band_nums)):
                    band_lc = src_ds.GetRasterBand(self.lc_band_nums[i])
                    a_lc = band_lc.ReadAsArray(x, y, cols, rows)
                    a_lc[mask_array == -32767] = -32767
                    lc_totals_table[i - 1] = np.add([np.sum((a_lc == c) * cell_areas_array) for c in [1, 2, 3, 4, 5, 6, 7, -32768]], lc_totals_table[i - 1])

                blocks += 1
            lat += pixel_height * rows
        self.progress.emit(100)

        # pr.disable()
        # pr.dump_stats('calculate_ldn_stats')
        
        if self.killed:
            del dst_ds_deg
            os.remove(self.prod_out_file)
            return None
        else:
            # Convert all area tables from meters into square kilometers
            return list((soc_totals_table,
                         lc_totals_table * 1e-6,
                         ((rh, ch), xt * 1e-6),
                         sdg_tbl_overall * 1e-6,
                         sdg_tbl_prod * 1e-6,
                         sdg_tbl_soc * 1e-6,
                         sdg_tbl_lc * 1e-6))


class DlgCalculateLDNSummaryTableAdmin(
    DlgCalculateBase,
    DlgCalculateLdnSummaryTableAdminUi
):
    SCRIPT_NAME: str = "final-sdg-15-3-1"

    mode_te_prod_rb: QtWidgets.QRadioButton
    mode_lpd_jrc: QtWidgets.QRadioButton
    combo_layer_traj: data_io.WidgetDataIOSelectTELayerExisting
    combo_layer_perf: data_io.WidgetDataIOSelectTELayerExisting
    combo_layer_state: data_io.WidgetDataIOSelectTELayerExisting
    combo_layer_lpd: data_io.WidgetDataIOSelectTELayerImport
    combo_layer_lc: data_io.WidgetDataIOSelectTELayerExisting
    combo_layer_soc: data_io.WidgetDataIOSelectTELayerExisting
    button_prev: QtWidgets.QPushButton
    button_next: QtWidgets.QPushButton
    button_calculate: QtWidgets.QPushButton

    def __init__(
            self,
            iface: qgis.gui.QgisInterface,
            script: models.ExecutionScript,
            parent: QtWidgets.QWidget = None
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)
        # self.add_output_tab(['.json', '.tif', '.xlsx'])
        self.mode_lpd_jrc.toggled.connect(self.mode_lpd_jrc_toggled)
        self.mode_lpd_jrc_toggled()
        self.initiliaze_settings()

    def mode_lpd_jrc_toggled(self):
        if self.mode_lpd_jrc.isChecked():
            self.combo_layer_lpd.setEnabled(True)
            self.combo_layer_traj.setEnabled(False)
            self.combo_layer_traj_label.setEnabled(False)
            self.combo_layer_perf.setEnabled(False)
            self.combo_layer_perf_label.setEnabled(False)
            self.combo_layer_state.setEnabled(False)
            self.combo_layer_state_label.setEnabled(False)
        else:
            self.combo_layer_lpd.setEnabled(False)
            self.combo_layer_traj.setEnabled(True)
            self.combo_layer_traj_label.setEnabled(True)
            self.combo_layer_perf.setEnabled(True)
            self.combo_layer_perf_label.setEnabled(True)
            self.combo_layer_state.setEnabled(True)
            self.combo_layer_state_label.setEnabled(True)

    def showEvent(self, event):
        super(DlgCalculateLDNSummaryTableAdmin, self).showEvent(event)
        self.combo_layer_lpd.populate()
        self.combo_layer_traj.populate()
        self.combo_layer_perf.populate()
        self.combo_layer_state.populate()
        self.combo_layer_lc.populate()
        self.combo_layer_soc.populate()

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super().btn_calculate()
        if not ret:
            return

        if self.mode_te_prod.isChecked():
            prod_mode = 'Trends.Earth productivity'
        else:
            prod_mode = 'JRC LPD'


        ######################################################################
        # Check that all needed input layers are selected
        if prod_mode == 'Trends.Earth productivity':
            if len(self.combo_layer_traj.layer_list) == 0:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(
                        "You must add a productivity trajectory indicator layer to "
                        "your map before you can use the SDG calculation tool."
                    )
                )
                return
            if len(self.combo_layer_state.layer_list) == 0:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(
                        "You must add a productivity state indicator layer to your "
                        "map before you can use the SDG calculation tool."
                    )
                )
                return
            if len(self.combo_layer_perf.layer_list) == 0:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(
                        "You must add a productivity performance indicator layer to "
                        "your map before you can use the SDG calculation tool."
                    )
                )
                return

        else:
            if len(self.combo_layer_lpd.layer_list) == 0:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(
                        "You must add a land productivity dynamics indicator layer to "
                        "your map before you can use the SDG calculation tool."
                    )
                )
                return

        if len(self.combo_layer_lc.layer_list) == 0:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "You must add a land cover indicator layer to your map before you "
                    "can use the SDG calculation tool."
                )
            )
            return

        if len(self.combo_layer_soc.layer_list) == 0:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "You must add a soil organic carbon indicator layer to your map "
                    "before you can use the SDG calculation tool."
                )
            )
            return

        #######################################################################
        # Check that the layers cover the full extent needed
        if prod_mode == 'Trends.Earth productivity':
            trajectory_layer_extent = self.combo_layer_traj.get_layer().extent()
            extent_geom = QgsGeometry.fromRect(trajectory_layer_extent)
            overlaps_by = self.aoi.calc_frac_overlap(extent_geom)
            if overlaps_by < 0.99:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(
                        "Area of interest is not entirely within the trajectory layer."
                    )
                )
                return
            if self.aoi.calc_frac_overlap(QgsGeometry.fromRect(self.combo_layer_perf.get_layer().extent())) < .99:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(
                        "Area of interest is not entirely within the "
                        "performance layer."
                    )
                )
                return
            if self.aoi.calc_frac_overlap(QgsGeometry.fromRect(self.combo_layer_state.get_layer().extent())) < .99:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr("Area of interest is not entirely within the state layer.")
                )
                return
        else:
            if self.aoi.calc_frac_overlap(QgsGeometry.fromRect(self.combo_layer_lpd.get_layer().extent())) < .99:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(
                        "Area of interest is not entirely within the land "
                        "productivity dynamics layer."
                    )
                )
                return

        if self.aoi.calc_frac_overlap(QgsGeometry.fromRect(self.combo_layer_lc.get_layer().extent())) < .99:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Area of interest is not entirely within the land cover layer.")
            )
            return
        if self.aoi.calc_frac_overlap(QgsGeometry.fromRect(self.combo_layer_soc.get_layer().extent())) < .99:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Area of interest is not entirely within the soil organic "
                    "carbon layer."
                )
            )
            return

        #######################################################################
        # Check that all of the productivity layers have the same resolution 
        # and CRS
        def res(layer):
            return (
                round(layer.rasterUnitsPerPixelX(), 10),
                round(layer.rasterUnitsPerPixelY(), 10)
            )

        if prod_mode == 'Trends.Earth productivity':
            if res(self.combo_layer_traj.get_layer()) != res(self.combo_layer_state.get_layer()):
                QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Resolutions of trajectory layer and state layer do not match."))
                return
            if res(self.combo_layer_traj.get_layer()) != res(self.combo_layer_perf.get_layer()):
                QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Resolutions of trajectory layer and performance layer do not match."))
                return

            if self.combo_layer_traj.get_layer().crs() != self.combo_layer_state.get_layer().crs():
                QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Coordinate systems of trajectory layer and state layer do not match."))
                return
            if self.combo_layer_traj.get_layer().crs() != self.combo_layer_perf.get_layer().crs():
                QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Coordinate systems of trajectory layer and performance layer do not match."))
                return

        self.close()

        params = ldn.get_main_sdg_15_3_1_job_params(
            task_name=self.options_tab.task_name.text(),
            aoi=self.aoi,
            prod_mode=prod_mode,
            combo_layer_lc=self.combo_layer_lc,
            combo_layer_soc=self.combo_layer_soc,
            combo_layer_traj=self.combo_layer_traj,
            combo_layer_perf=self.combo_layer_perf,
            combo_layer_state=self.combo_layer_state,
            combo_layer_lpd=self.combo_layer_lpd,
            task_notes=self.options_tab.task_notes.toPlainText()
        )
        job_manager.submit_local_job(
            params, script_name=self.SCRIPT_NAME, area_of_interest=self.aoi)
