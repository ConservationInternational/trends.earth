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

import json
from pathlib import Path

import numpy as np
import qgis.core
from osgeo import gdal

from PyQt5 import (
    QtCore,
    QtWidgets,
    uic,
)

from . import (
    calculate,
    data_io,
    log,
    summary,
    worker,
)
from .algorithms.models import ExecutionScript
from .jobs.manager import job_manager


DlgCalculateRestBiomassDataUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateRestBiomassData.ui"))
DlgCalculateRestBiomassSummaryTableUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateRestBiomassSummaryTable.ui"))


class tr_calculate_rest_biomass(object):
    def tr(message):
        return QtCore.QCoreApplication.translate("tr_calculate_rest_biomass", message)


class DlgCalculateRestBiomassData(
    calculate.DlgCalculateBase,
    DlgCalculateRestBiomassDataUi
):

    def __init__(
            self,
            iface: qgis.gui.QgisInterface,
            script: ExecutionScript,
            parent: QtWidgets.QWidget
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)
        self.first_show = True
        self.initiliaze_settings()

    def showEvent(self, event):
        super(DlgCalculateRestBiomassData, self).showEvent(event)

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateRestBiomassData, self).btn_calculate()
        if not ret:
            return
        self.calculate_on_GEE()

    def get_rest_type(self):
        if self.radioButton_rest_type_terrestrial.isChecked():
            return "terrestrial"
        elif self.radioButton_rest_type_coastal.isChecked():
            return "coastal"
        else:
            # Should never get here
            raise

    def calculate_on_GEE(self):
        self.close()
        crosses_180th, geojsons = self.gee_bounding_box
        payload = {
            'length_yr': self.spinBox_years.value(),
            'rest_type': self.get_rest_type(),
            'geojsons': json.dumps(geojsons),
            'crs': self.aoi.get_crs_dst_wkt(),
            'crosses_180th': crosses_180th,
            'task_name': self.execution_name_le.text(),
            'task_notes': self.task_notes.toPlainText()
        }

        resp = job_manager.submit_remote_job(payload, self.script.id)
        if resp:
            main_msg = "Submitted"
            description = "Restoration biomass change submitted to Google Earth Engine."
        else:
            main_msg = "Error"
            description = (
                "Unable to submit restoration biomass change task to Google Earth "
                "Engine."
            )
        self.mb.pushMessage(
            self.tr(main_msg),
            self.tr(description),
            level=0,
            duration=5
        )


class RestBiomassSummaryWorker(worker.AbstractWorker):
    def __init__(self, src_file):
        worker.AbstractWorker.__init__(self)

        self.src_file = src_file

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        src_ds = gdal.Open(self.src_file)

        band_biomass_initial = src_ds.GetRasterBand(1)
        # First band is initial biomass, and all other bands are for different 
        # types of restoration
        n_types = src_ds.RasterCount - 1

        block_sizes = band_biomass_initial.GetBlockSize()
        xsize = band_biomass_initial.XSize
        ysize = band_biomass_initial.YSize

        x_block_size = block_sizes[0]
        y_block_size = block_sizes[1]

        src_gt = src_ds.GetGeoTransform()

        # Width of cells in longitude
        long_width = src_gt[1]
        # Set initial lat ot the top left corner latitude
        lat = src_gt[3]
        # Width of cells in latitude
        pixel_height = src_gt[5]

        area_site = 0
        biomass_initial = 0
        biomass_change = np.zeros(n_types)

        blocks = 0
        for y in range(0, ysize, y_block_size):
            if y + y_block_size < ysize:
                rows = y_block_size
            else:
                rows = ysize - y
            for x in range(0, xsize, x_block_size):
                if self.killed:
                    log("Processing of {} killed by user after processing {} out of {} blocks.".format(self.prod_out_file, y, ysize))
                    break
                self.progress.emit(100 * (float(y) + (float(x)/xsize)*y_block_size) / ysize)
                if x + x_block_size < xsize:
                    cols = x_block_size
                else:
                    cols = xsize - x

                biomass_initial_array = band_biomass_initial.ReadAsArray(x, y, cols, rows)

                # Caculate cell area for each horizontal line
                cell_areas = np.array([summary.calc_cell_area(lat + pixel_height*n, lat + pixel_height*(n + 1), long_width) for n in range(rows)])
                cell_areas.shape = (cell_areas.size, 1)
                # Make an array of the same size as the input arrays containing 
                # the area of each cell (which is identicalfor all cells in a 
                # given row - cell areas only vary among rows)
                cell_areas_array = np.repeat(cell_areas, cols, axis=1)
                # Convert cell areas to hectares
                cell_areas_array = cell_areas_array * 1e-4

                # The site area includes everything that isn't masked
                site_pixels = biomass_initial_array != -32767
                
                area_site = area_site + np.sum(site_pixels * cell_areas_array)
                biomass_initial = biomass_initial + np.sum(site_pixels * cell_areas_array * biomass_initial_array)

                for n in range(n_types):
                    biomass_rest_array = src_ds.GetRasterBand(n + 2).ReadAsArray(x, y, cols, rows)
                    biomass_change[n] = biomass_change[n] + np.sum((biomass_rest_array) * cell_areas_array * site_pixels)

                blocks += 1
            lat += pixel_height * rows
        self.progress.emit(100)

        if self.killed:
            return None

        return list((biomass_initial, biomass_change, area_site))


class DlgCalculateRestBiomassSummaryTable(
    calculate.DlgCalculateBase,
    DlgCalculateRestBiomassSummaryTableUi
):
    LOCAL_SCRIPT_NAME = "change-biomass-summary-table"

    combo_layer_biomass_diff: data_io.WidgetDataIOSelectTELayerExisting

    def __init__(
            self,
            iface: qgis.gui.QgisInterface,
            script: ExecutionScript,
            parent: QtWidgets.QWidget
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)
        self.initiliaze_settings()

    def showEvent(self, event):
        super().showEvent(event)
        self.combo_layer_biomass_diff.populate()

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super().btn_calculate()
        if not ret:
            return

        ######################################################################
        # Check that all needed input layers are selected
        if len(self.combo_layer_biomass_diff.layer_list) == 0:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "You must add a biomass layer to your map before you can use "
                    "the summary tool."
                )
            )
            return
        #######################################################################
        # Check that the layers cover the full extent needed
        layer_biomass = self.combo_layer_biomass_diff.get_layer()
        layer_biomass_extent_geometry = qgis.core.QgsGeometry.fromRect(
            layer_biomass.extent())
        if self.aoi.calc_frac_overlap(layer_biomass_extent_geometry) < .99:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Area of interest is not entirely within the biomass layer.")
            )
            return

        self.close()
        usable_in_file = self.combo_layer_biomass_diff.get_usable_band_info()
        restoration_types = []
        for band in usable_in_file.job.results.bands[1:]:
            restoration_types.append(band.metadata["type"])
        serialized_bands = [b.serialize() for b in usable_in_file.job.results.bands]
        job_params = {
            "task_name": self.options_tab.task_name.text(),
            "task_notes": self.options_tab.task_notes.toPlainText(),
            "in_file_path": str(usable_in_file.path),
            "restoration_years": usable_in_file.job.results.bands[2].metadata["years"],
            "restoration_types": restoration_types,
            "in_file_band_infos": serialized_bands,
        }
        job_manager.submit_local_job(job_params, self.LOCAL_SCRIPT_NAME, self.aoi)
