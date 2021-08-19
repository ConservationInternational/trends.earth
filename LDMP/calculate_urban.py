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

from pathlib import Path
import json

import numpy as np
import qgis.gui
import qgis.core
from osgeo import gdal
from qgis.PyQt import (
    QtCore,
    QtWidgets,
    uic
)

from . import (
    calculate,
    data_io,
    summary,
    worker,
)
from .algorithms.models import ExecutionScript
from .jobs.manager import job_manager
from .logger import log

DlgCalculateUrbanDataUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateUrbanData.ui"))
DlgCalculateUrbanSummaryTableUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateUrbanSummaryTable.ui"))


class tr_calculate_urban(object):
    def tr(message):
        return QtCore.QCoreApplication.translate("tr_calculate_urban", message)


# class UrbanSummaryWorker(worker.AbstractWorker):
#     def __init__(self, src_file, urban_band_nums, pop_band_nums, n_classes):
#         worker.AbstractWorker.__init__(self)
#
#         self.src_file = src_file
#         self.urban_band_nums = [int(x) for x in urban_band_nums]
#         self.pop_band_nums = [int(x) for x in pop_band_nums]
#         self.n_classes = n_classes
#
#     def work(self):
#         self.toggle_show_progress.emit(True)
#         self.toggle_show_cancel.emit(True)
#
#         src_ds = gdal.Open(self.src_file)
#
#         urban_bands = [src_ds.GetRasterBand(b) for b in self.urban_band_nums]
#         pop_bands = [src_ds.GetRasterBand(b) for b in self.pop_band_nums]
#
#         block_sizes = urban_bands[1].GetBlockSize()
#         xsize = urban_bands[1].XSize
#         ysize = urban_bands[1].YSize
#
#         x_block_size = block_sizes[0]
#         y_block_size = block_sizes[1]
#
#         src_gt = src_ds.GetGeoTransform()
#
#         # Width of cells in longitude
#         long_width = src_gt[1]
#         # Set initial lat ot the top left corner latitude
#         lat = src_gt[3]
#         # Width of cells in latitude
#         pixel_height = src_gt[5]
#
#         areas = np.zeros((self.n_classes, len(self.urban_band_nums)))
#         populations = np.zeros((self.n_classes, len(self.pop_band_nums)))
#
#         blocks = 0
#         for y in range(0, ysize, y_block_size):
#             if y + y_block_size < ysize:
#                 rows = y_block_size
#             else:
#                 rows = ysize - y
#             for x in range(0, xsize, x_block_size):
#                 if self.killed:
#                     log("Processing of {} killed by user after processing {} out of {} blocks.".format(self.prod_out_file, y, ysize))
#                     break
#                 self.progress.emit(100 * (float(y) + (float(x)/xsize)*y_block_size) / ysize)
#                 if x + x_block_size < xsize:
#                     cols = x_block_size
#                 else:
#                     cols = xsize - x
#
#                 # Caculate cell area for each horizontal line
#                 cell_areas = np.array([summary.calc_cell_area(lat + pixel_height*n, lat + pixel_height*(n + 1), long_width) for n in range(rows)])
#                 # Convert areas from meters into hectares
#                 cell_areas = cell_areas * 1e-4
#                 cell_areas.shape = (cell_areas.size, 1)
#                 # Make an array of the same size as the input arrays containing
#                 # the area of each cell (which is identicalfor all cells ina
#                 # given row - cell areas only vary among rows)
#                 cell_areas_array = np.repeat(cell_areas, cols, axis=1)
#
#                 # Loop over the bands (years)
#                 for i in range(len(self.urban_band_nums)):
#                     urban_array = urban_bands[i].ReadAsArray(x, y, cols, rows)
#                     pop_array = pop_bands[i].ReadAsArray(x, y, cols, rows)
#                     pop_array[pop_array == -32768] = 0
#                     # Now loop over the classes
#                     for c in range(1, self.n_classes + 1):
#                         areas[c - 1, i] += np.sum((urban_array == c) * cell_areas_array)
#                         pop_masked = pop_array.copy() * (urban_array == c)
#                         # Convert population densities to persons per hectare
#                         # from persons per sq km
#                         pop_masked = pop_masked / 100
#                         populations[c - 1, i] += np.sum(pop_masked * cell_areas_array)
#
#                 blocks += 1
#             lat += pixel_height * rows
#         self.progress.emit(100)
#
#         if self.killed:
#             return None
#         else:
#             return list((areas, populations))


class DlgCalculateUrbanData(calculate.DlgCalculateBase, DlgCalculateUrbanDataUi):

    def __init__(
            self,
            iface: qgis.gui.QgisInterface,
            script: ExecutionScript,
            parent: QtWidgets.QWidget = None,
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)
        self.urban_thresholds_updated()

        self.spinBox_pct_urban.valueChanged.connect(self.urban_thresholds_updated)
        self.spinBox_pct_suburban.valueChanged.connect(self.urban_thresholds_updated)
        self._finish_initialization()

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateUrbanData, self).btn_calculate()
        if not ret:
            return

        # Limit area that can be processed
        aoi_area = self.aoi.get_area() / (1000 * 1000)
        log(u'AOI area is: {:n}'.format(aoi_area))
        if aoi_area > 25000:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("The bounding box of the requested area (approximately {:.6n} sq km) is too large. The urban area change tool can process a maximum area of 25,000 sq. km at a time. Choose a smaller area to process.".format(aoi_area)))
            return False

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

        crosses_180th, geojsons = self.gee_bounding_box

        payload = {
            'un_adju': self.get_pop_def_is_un(),
            'isi_thr': self.spinBox_isi_thr.value(),
            'ntl_thr': self.spinBox_ntl_thr.value(),
            'wat_thr': self.spinBox_wat_thr.value(),
            'cap_ope': self.spinBox_cap_ope.value(),
            'pct_suburban': self.spinBox_pct_suburban.value()/100.,
            'pct_urban': self.spinBox_pct_urban.value()/100.,
            'geojsons': json.dumps(geojsons),
            'crs': self.aoi.get_crs_dst_wkt(),
            'crosses_180th': crosses_180th,
            'task_name': self.execution_name_le.text(),
            'task_notes': self.options_tab.task_notes.toPlainText()
        }

        resp = job_manager.submit_remote_job(payload, self.script.id)

        if resp:
            main_msg = "Submitted"
            description = (
                "Urban area change calculation submitted to Google Earth Engine.")

        else:
            main_msg = "Error"
            description = "Unable to submit urban area task Google Earth Engine."
        self.mb.pushMessage(
            self.tr(main_msg),
            self.tr(description),
            level=0,
            duration=5
        )


class DlgCalculateUrbanSummaryTable(
    calculate.DlgCalculateBase, DlgCalculateUrbanSummaryTableUi
):
    LOCAL_SCRIPT_NAME = "urban-change-summary-table"

    combo_layer_urban_series: data_io.WidgetDataIOSelectTELayerExisting

    def __init__(
            self,
            iface: qgis.gui.QgisInterface,
            script: ExecutionScript,
            parent: QtWidgets.QWidget
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)
        self._finish_initialization()

    def showEvent(self, event):
        super().showEvent(event)
        self.combo_layer_urban_series.populate()

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super().btn_calculate()
        if not ret:
            return

        ######################################################################
        # Check that all needed input layers are selected
        if len(self.combo_layer_urban_series.layer_list) == 0:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "You must add an urban series layer to your map before you can "
                    "use the urban change summary tool."
                )
            )
            return

        #######################################################################
        # Check that the layers cover the full extent needed
        urban_layer = self.combo_layer_urban_series.get_layer()
        urban_layer_extent_geom = qgis.core.QgsGeometry.fromRect(urban_layer.extent())
        if self.aoi.calc_frac_overlap(urban_layer_extent_geom) < .99:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Area of interest is not entirely within the urban series layer.")
            )
            return

        self.close()

        urban_usable_info = self.combo_layer_urban_series.get_usable_band_info()
        urban_annual_band_indices = []
        pop_annual_band_indices = []

        urban_indices_years = []
        pop_indices_years = []

        for index, band in enumerate(urban_usable_info.job.results.bands):
            band_index = index + 1
            band_year = band.metadata.get("year")
            if band.name.lower() == "urban":
                urban_annual_band_indices.append(band_index)
                urban_indices_years.append((band_index, band_year))
            elif band.name.lower() == "population":
                pop_annual_band_indices.append(band_index)
                pop_indices_years.append((band_index, band_year))
        urban_indices_years.sort(key=lambda entry: entry[1])
        pop_indices_years.sort(key=lambda entry: entry[1])
        if len(urban_indices_years) != len(pop_indices_years):
            raise RuntimeError("Urban files and pop files do not have the same length")
        job_params = {
            "task_name": self.options_tab.task_name.text(),
            "task_notes": self.options_tab.task_notes.toPlainText(),
            "urban_layer_path": str(urban_usable_info.path),
            "urban_layer_band_indexes": [entry[0] for entry in urban_indices_years],
            "urban_layer_pop_band_indexes": [entry[0] for entry in pop_indices_years],
        }
        job_manager.submit_local_job(job_params, self.LOCAL_SCRIPT_NAME, self.aoi)
