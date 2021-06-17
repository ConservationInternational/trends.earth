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

from PyQt5 import (
    QtWidgets,
    uic
)

import qgis.core
from osgeo import (
    gdal,
    osr
)
import qgis.gui

from . import (
    calculate,
    lc_setup,
    log,
    worker,
)
from .algorithms.models import (
    AlgorithmRunMode,
    ExecutionScript,
)
from .jobs.manager import job_manager

DlgCalculateLcUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateLC.ui"))


class LandCoverChangeWorker(worker.AbstractWorker):
    def __init__(self, in_f, out_f, trans_matrix, persistence_remap):
        worker.AbstractWorker.__init__(self)
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
        y_block_size = block_sizes[1]
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


class DlgCalculateLC(calculate.DlgCalculateBase, DlgCalculateLcUi):
    LOCAL_SCRIPT_NAME = "local-land-cover"

    advanced_configurations: qgis.gui.QgsCollapsibleGroupBox
    scrollAreaWidgetContents: QtWidgets.QWidget

    def __init__(
            self,
            iface: qgis.gui.QgisInterface,
            script: ExecutionScript,
            parent: QtWidgets.QWidget
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)

        lc_widget_class = {
            AlgorithmRunMode.LOCAL: lc_setup.LandCoverSetupLocalExecutionWidget,
            AlgorithmRunMode.REMOTE: lc_setup.LandCoverSetupRemoteExecutionWidget,
        }[self.script.run_mode]
        self.lc_setup_widget = lc_widget_class(parent=self)
        self.lc_define_deg_widget = lc_setup.LCDefineDegradationWidget()
        self.advanced_configurations.setCollapsed(True)
        self.scrollAreaWidgetContents.layout().insertWidget(0, self.lc_setup_widget)
        self.advanced_configurations.layout().insertWidget(0, self.lc_define_deg_widget)
        self._finish_initialization()

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateLC, self).btn_calculate()
        if not ret:
            return

        if self.script.run_mode == AlgorithmRunMode.REMOTE:
            self.calculate_on_GEE()
        elif self.script.run_mode == AlgorithmRunMode.LOCAL:
            self.calculate_locally()
        else:
            raise NotImplementedError

    def calculate_on_GEE(self):
        self.close()
        crosses_180th, geojsons = self.gee_bounding_box

        payload = {
            "year_baseline": self.lc_setup_widget.initial_year_de.date().year(),
            "year_target": self.lc_setup_widget.target_year_de.date().year(),
            "geojsons": json.dumps(geojsons),
            "crs": self.aoi.get_crs_dst_wkt(),
            "crosses_180th": crosses_180th,
            "trans_matrix": self.lc_define_deg_widget.trans_matrix_get(),
            "remap_matrix": self.lc_setup_widget.aggregation_dialog.get_agg_as_list(),
            "task_name": self.execution_name_le.text(),
            "task_notes": self.task_notes.toPlainText()
        }
        job = job_manager.submit_remote_job(payload, self.script.id)

        if job is not None:
            main_msg = "Submitted"
            description = "Land cover task submitted to Google Earth Engine."
        else:
            main_msg = "Error"
            description = "Unable to submit land cover task to Google Earth Engine."
        self.mb.pushMessage(
            self.tr(main_msg),
            self.tr(description),
            level=0,
            duration=5
        )

    def calculate_locally(self):

        if len(self.lc_setup_widget.initial_year_layer_cb.layer_list) == 0:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "You must add an initial land cover layer to your map before you "
                    "can run the calculation."
                )
            )
            return

        if len(self.lc_setup_widget.target_year_layer_cb.layer_list) == 0:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "You must add a final land cover layer to your map before you "
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
                    'The initial year ({}) is greater than or equal to the target '
                    'year ({}) - this analysis might generate strange '
                    'results.'.format(year_baseline, year_target)
                )
            )

        initial_layer = self.lc_setup_widget.initial_year_layer_cb.get_layer()
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
        final_extent_geom = qgis.core.QgsGeometry.fromRect(final_layer.extent())
        if self.aoi.calc_frac_overlap(final_extent_geom) < .99:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Area of interest is not entirely within the final land "
                    "cover layer."
                )
            )
            return

        self.close()

        initial_usable = (
            self.lc_setup_widget.initial_year_layer_cb.get_usable_band_info())
        final_usable = self.lc_setup_widget.target_year_layer_cb.get_usable_band_info()
        job_params = {
            "task_name": self.execution_name_le.text(),
            "task_notes": self.task_notes.toPlainText(),
            "year_baseline": year_baseline,
            "year_target": year_target,
            "lc_initial_path": str(initial_usable.path),
            "lc_initial_band_index": initial_usable.band_index,
            "lc_final_path": str(final_usable.path),
            "lc_final_band_index": final_usable.band_index,
            "transformation_matrix": self.lc_define_deg_widget.trans_matrix_get()
        }
        job_manager.submit_local_job(job_params, self.LOCAL_SCRIPT_NAME, self.aoi)
