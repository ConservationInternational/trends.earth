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

import json
import os
from pathlib import Path

import numpy as np
import qgis.gui
from osgeo import (
    gdal,
    osr,
)
from PyQt5 import (
    QtGui,
    QtWidgets,
    uic,
)

from . import (
    calculate,
    data_io,
    lc_setup,
    log,
    worker,
)

from .algorithms import models
from .jobs.manager import job_manager

DlgCalculateSocUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateSOC.ui"))


def remap(a, remap_list):
    for value, replacement in zip(remap_list[0], remap_list[1]):
        a[a == value] = replacement
    return a


class SOCWorker(worker.AbstractWorker):
    def __init__(self, in_vrt, out_f, lc_band_nums, lc_years, fl):
        worker.AbstractWorker.__init__(self)
        self.in_vrt = in_vrt
        self.out_f = out_f
        self.lc_years = lc_years
        self.lc_band_nums = lc_band_nums
        self.fl = fl

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
        ds_out = driver.Create(self.out_f, xsize, ysize, 1 + len(self.lc_years) * 2, gdal.GDT_Int16,
                               ['COMPRESS=LZW'])
        src_gt = ds_in.GetGeoTransform()
        ds_out.SetGeoTransform(src_gt)
        out_srs = osr.SpatialReference()
        out_srs.ImportFromWkt(ds_in.GetProjectionRef())
        ds_out.SetProjection(out_srs.ExportToWkt())

        # Setup a raster of climate regimes to use for coding Fl automatically
        clim_fl_map = np.array([[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
                                [0, .69, .8, .69, .8, .69, .8, .69, .8, .64, .48, .48, .58]])

        # stock change factor for land use - note the 99 and -99 will be 
        # recoded using the chosen Fl option
        lc_tr_fl_0_map = np.array([[11, 12, 13, 14, 15, 16, 17,
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
                                    1, 1, 1, 1, 1, 1, 1]])

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
        for y in range(0, ysize, y_block_size):
            if self.killed:
                log("Processing killed by user after processing {} out of {} blocks.".format(y, ysize))
                break
            self.progress.emit(100 * float(y) / ysize)
            if y + y_block_size < ysize:
                rows = y_block_size
            else:
                rows = ysize - y
            for x in range(0, xsize, x_block_size):
                if x + x_block_size < xsize:
                    cols = x_block_size
                else:
                    cols = xsize - x

                # Write initial soc to band 2 of the output file. Read SOC in 
                # as float so the soc change calculations won't accumulate 
                # error due to repeated truncation of ints
                soc = np.array(soc_band.ReadAsArray(x, y, cols, rows)).astype(np.float32)
                ds_out.GetRasterBand(2).WriteArray(soc, x, y)

                if self.fl == 'per pixel':
                    clim = np.array(clim_band.ReadAsArray(x, y, cols, rows)).astype(np.float32)
                    # Setup a raster of climate regimes to use for coding Fl 
                    # automatically
                    clim_fl = remap(clim, clim_fl_map)

                tr_year = np.zeros(np.shape(soc))
                soc_chg = np.zeros(np.shape(soc))
                for n in range(len(self.lc_years) - 1):
                    t0 = float(self.lc_years[n])
                    t1 = float(self.lc_years[n + 1])

                    log(u'self.lc_band_nums: {}'.format(self.lc_band_nums))
                    lc_t0 = ds_in.GetRasterBand(self.lc_band_nums[n]).ReadAsArray(x, y, cols, rows)
                    lc_t1 = ds_in.GetRasterBand(self.lc_band_nums[n + 1]).ReadAsArray(x, y, cols, rows)

                    nodata = (lc_t0 == -32768) | (lc_t1 == -32768) | (soc == - 32768)
                    if self.fl == 'per pixel':
                        nodata[clim == -128] = True

                    # compute transition map (first digit for baseline land 
                    # cover, and second digit for target year land cover), but 
                    # only update where changes actually ocurred.
                    lc_tr = lc_t0 * 10 + lc_t1
                    lc_tr[(lc_t0 < 1) | (lc_t1 < 1)] < - -32768

                    ######################################################
                    # If more than one year has elapsed, need to split the 
                    # period into two parts, and account for any requried 
                    # changes in soc due to past lc transitions over the 
                    # first part of the period, and soc changes due to lc 
                    # changes that occurred during the period over the 

                    # Calculate middle of period. Take the floor so that a 
                    # transition that occurs when two lc layers are one 
                    # year apart gets the full new soc_chg factor applied 
                    # (rather than half), and none of the old soc_chg factor.
                    t_mid = t0 + np.floor((t1 - t0) / 2)

                    # Assume any lc transitions occurred in the middle of the 
                    # period since we don't know the actual year of transition. 
                    # Apply old soc change for appropriate number of years for 
                    # pixels that had a transition > tr_year ago but less than 
                    # 20 years prior to the middle of this period. Changes 
                    # occur over a twenty year period, and then change stops.
                    if n > 0:
                        # Don't consider transition in lc at beginning of the 
                        # period for the first period (as there is no data on 
                        # what lc was prior to the first period, so soc_chg is 
                        # undefined)
                        yrs_lc_0 = t_mid - tr_year
                        yrs_lc_0[yrs_lc_0 > 20] = 20
                        soc = soc - soc_chg * yrs_lc_0
                        soc_chg[yrs_lc_0 == 20] = 0

                    ######################################################
                    # Calculate new soc_chg and apply it over the second 
                    # half of the period

                    # stock change factor for land use
                    lc_tr_fl = remap(np.array(lc_tr).astype(np.float32), lc_tr_fl_0_map)
                    if self.fl == 'per pixel':
                        lc_tr_fl[lc_tr_fl == 99] = clim_fl[lc_tr_fl == 99]
                        lc_tr_fl[lc_tr_fl == -99] = 1. / clim_fl[lc_tr_fl == -99]
                    else:
                        lc_tr_fl[lc_tr_fl == 99] = self.fl
                        lc_tr_fl[lc_tr_fl == -99] = 1. / self.fl

                    # stock change factor for management regime
                    lc_tr_fm = remap(lc_tr, lc_tr_fm_map)

                    # stock change factor for input of organic matter
                    lc_tr_fo = remap(lc_tr, lc_tr_fo_map)

                    # Set the transition year to the middle of the period for 
                    # pixels that had a change in cover
                    tr_year[lc_t0 != lc_t1] = t_mid

                    # Calculate a new soc change for pixels that changed
                    soc_chg[lc_t0 != lc_t1] = (soc[lc_t0 != lc_t1] - \
                                               soc[lc_t0 != lc_t1] * \
                                               lc_tr_fl[lc_t0 != lc_t1] * \
                                               lc_tr_fm[lc_t0 != lc_t1] * \
                                               lc_tr_fo[lc_t0 != lc_t1]) / 20

                    yrs_lc_1 = t1 - tr_year
                    # Subtract the length of the first half of the period from 
                    # yrs_lc_1 for pixels that weren't changed - these pixels 
                    # have already had soc_chg applied for the first portion of 
                    # the period
                    yrs_lc_1[lc_t0 == lc_t1] = yrs_lc_1[lc_t0 == lc_t1] - (t_mid - t0)
                    yrs_lc_1[yrs_lc_1 > 20] = 20
                    soc = soc - soc_chg * yrs_lc_1
                    soc_chg[yrs_lc_1 == 20] = 0

                    # Write out this SOC layer. Note the first band of ds_out 
                    # is soc degradation, and the second band is the initial 
                    # soc. As n starts at 0, need to add 3 so that the first 
                    # soc band derived from LC change soc band is written to 
                    # band 3 of the output file
                    soc[nodata] = -32768
                    ds_out.GetRasterBand(n + 3).WriteArray(soc, x, y)

                # Write out the percent change in SOC layer
                soc_initial = ds_out.GetRasterBand(2).ReadAsArray(x, y, cols, rows)
                soc_final = ds_out.GetRasterBand(2 + len(self.lc_band_nums) - 1).ReadAsArray(x, y, cols, rows)
                soc_initial = np.array(soc_initial).astype(np.float32)
                soc_final = np.array(soc_final).astype(np.float32)
                soc_pch = ((soc_final - soc_initial) / soc_initial) * 100
                soc_pch[nodata] = -32768
                ds_out.GetRasterBand(1).WriteArray(soc_pch, x, y)

                # Write out the initial and final lc layers
                lc_bl = ds_in.GetRasterBand(self.lc_band_nums[0]).ReadAsArray(x, y, cols, rows)
                ds_out.GetRasterBand(1 + len(self.lc_band_nums) + 1).WriteArray(lc_bl, x, y)
                lc_tg = ds_in.GetRasterBand(self.lc_band_nums[-1]).ReadAsArray(x, y, cols, rows)
                ds_out.GetRasterBand(1 + len(self.lc_band_nums) + 2).WriteArray(lc_tg, x, y)

                blocks += 1

        if self.killed:
            del ds_in
            del ds_out
            os.remove(self.out_f)
            return None
        else:
            return True


class DlgCalculateSOC(calculate.DlgCalculateBase, DlgCalculateSocUi):
    TabBox: QtWidgets.QTabWidget
    fl_radio_default: QtWidgets.QRadioButton
    fl_radio_chooseRegime: QtWidgets.QRadioButton
    fl_radio_custom: QtWidgets.QRadioButton
    fl_chooseRegime_comboBox: QtWidgets.QComboBox
    fl_custom_lineEdit: QtWidgets.QLineEdit
    download_annual_lc: QtWidgets.QCheckBox
    groupBox_custom_SOC: QtWidgets.QGroupBox
    comboBox_custom_soc: data_io.WidgetDataIOSelectTELayerImport

    LOCAL_SCRIPT_NAME = "local-soil-organic-carbon"

    def __init__(
            self,
            iface: qgis.gui.QgisInterface,
            script: models.ExecutionScript,
            parent: QtWidgets.QWidget = None,
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)

        self.regimes = [
            ('Temperate dry (Fl = 0.80)', .80),
            ('Temperate moist (Fl = 0.69)', .69),
            ('Tropical dry (Fl = 0.58)', .58),
            ('Tropical moist (Fl = 0.48)', .48),
            ('Tropical montane (Fl = 0.64)', .64)
        ]

        lc_setup_widget_class = {
            models.AlgorithmRunMode.LOCAL: lc_setup.LandCoverSetupLocalExecutionWidget,
            models.AlgorithmRunMode.REMOTE: (
                lc_setup.LandCoverSetupRemoteExecutionWidget),
        }[self.script.run_mode]
        self.lc_setup_widget = lc_setup_widget_class(self)

        # self.lc_setup_widget = lc_setup.LCSetupWidget()

        self.splitter_collapsed = False

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
        self._finish_initialization()

    def showEvent(self, event):
        super().showEvent(event)

        if self.setup_frame.layout() is None:
            setup_layout = QtWidgets.QVBoxLayout(self.setup_frame)
            setup_layout.setContentsMargins(0, 0, 0, 0)
            setup_layout.addWidget(self.lc_setup_widget)
            self.setup_frame.setLayout(setup_layout)

        # self.lc_setup_widget.groupBox_esa_period.show()
        # self.lc_setup_widget.groupBox_custom_bl.show()
        # self.lc_setup_widget.groupBox_custom_tg.show()

        self.comboBox_custom_soc.populate()
        # self.lc_setup_widget.use_custom_initial.populate()
        # self.lc_setup_widget.use_custom_final.populate()

        # self.lc_setup_widget.default_frame.setVisible(
        #     self.script.run_mode == models.AlgorithmRunMode.REMOTE
        # )
        # self.lc_setup_widget.custom_frame.setVisible(
        #     self.script.run_mode == models.AlgorithmRunMode.LOCAL
        # )

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
        ret = super().btn_calculate()
        if not ret:
            return

        if self.script.run_mode == models.AlgorithmRunMode.LOCAL or \
                self.groupBox_custom_SOC.isChecked():
            self.calculate_locally()
        else:
            self.calculate_on_GEE()

    def calculate_locally(self):
        if not self.groupBox_custom_SOC.isChecked():
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Due to the options you have chosen, this calculation must occur "
                    "offline. You MUST select a custom soil organic carbon dataset."
                )
            )
            return
        if self.script.run_mode != models.AlgorithmRunMode.LOCAL:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Due to the options you have chosen, this calculation must occur "
                    "offline. You MUST select a custom land cover dataset."
                )
            )
            return

        if len(self.comboBox_custom_soc.layer_list) == 0:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "You must add a soil organic carbon layer to your map before you "
                    "can run the calculation."
                )
            )
            return

        year_baseline = self.lc_setup_widget.get_initial_year()
        year_target = self.lc_setup_widget.get_final_year()
        if int(year_baseline) >= int(year_target):
            QtWidgets.QMessageBox.information(
                None,
                self.tr("Warning"),
                self.tr(
                    f'The baseline year ({year_baseline}) is greater than or equal to the target '
                    f'year ({year_target}) - this analysis might generate strange '
                    f'results.'
                )
            )

        initial_layer = self.lc_setup_widget.initial_year_layer_cb.get_layer()
        # initial_layer = self.lc_setup_widget.use_custom_initial.get_layer()
        initial_extent_geom = qgis.core.QgsGeometry.fromRect(initial_layer.extent())
        if self.aoi.calc_frac_overlap(initial_extent_geom) < .99:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Area of interest is not entirely within the initial land cover "
                    "layer."
                )
            )
            return

        final_layer = self.lc_setup_widget.target_year_layer_cb.get_layer()
        # final_layer = self.lc_setup_widget.use_custom_final.get_layer()
        final_extent_geom = qgis.core.QgsGeometry.fromRect(final_layer.extent())
        if self.aoi.calc_frac_overlap(final_extent_geom) < .99:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Area of interest is not entirely within the final land cover "
                    "layer."
                )
            )
            return

        self.close()

        initial_usable = (
            self.lc_setup_widget.initial_year_layer_cb.get_usable_band_info())
        final_usable = self.lc_setup_widget.target_year_layer_cb.get_usable_band_info()
        # initial_usable = self.lc_setup_widget.use_custom_initial.get_usable_band_info()
        # final_usable = self.lc_setup_widget.use_custom_final.get_usable_band_info()
        soc_usable = self.comboBox_custom_soc.get_usable_band_info()

        job_params = {
            "task_name": self.execution_name_le.text(),
            "task_notes": self.task_notes.toPlainText(),
            "lc_initial_path": str(initial_usable.path),
            "lc_initial_band_index": initial_usable.band_index,
            "lc_final_path": str(final_usable.path),
            "lc_final_band_index": final_usable.band_index,
            "custom_soc_path": str(soc_usable.path),
            "custom_soc_band_index": soc_usable.band_index,
            "lc_years": [
                initial_usable.band_info.metadata["year"],
                final_usable.band_info.metadata["year"],
            ],
            "fl": self.get_fl(),
        }
        job_manager.submit_local_job(job_params, self.LOCAL_SCRIPT_NAME, self.aoi)

    def calculate_on_GEE(self):
        log("inside calculate_on_GEE...")
        self.close()

        crosses_180th, geojsons = self.gee_bounding_box
        payload = {
            "year_start": self.lc_setup_widget.initial_year_de.date().year(),
            "year_end": self.lc_setup_widget.target_year_de.date().year(),
            'fl': self.get_fl(),
            'download_annual_lc': self.download_annual_lc.isChecked(),
            'geojsons': json.dumps(geojsons),
            'crs': self.aoi.get_crs_dst_wkt(),
            'crosses_180th': crosses_180th,
            "remap_matrix": self.lc_setup_widget.aggregation_dialog.get_agg_as_list(),
            'task_name': self.execution_name_le.text(),
            'task_notes': self.options_tab.task_notes.toPlainText()
        }

        resp = job_manager.submit_remote_job(payload, self.script.id)
        if resp:
            main_msg = "Submitted"
            description = "Soil organic carbon task submitted to Google Earth Engine."

        else:
            main_msg = "Error"
            description = (
                "Unable to submit Soil organic carbon task to Google Earth Engine.")
        self.mb.pushMessage(
            self.tr(main_msg),
            self.tr(description),
            level=0,
            duration=5
        )
        log("leaving calculate_on_GEE...")
