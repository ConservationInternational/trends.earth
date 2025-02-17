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
import qgis.core
import qgis.gui
from osgeo import gdal, osr
from qgis.PyQt import QtCore, QtWidgets, uic
from te_schemas.algorithms import AlgorithmRunMode, ExecutionScript
from te_schemas.schemas import BandInfo

from . import GetTempFilename, calculate, conf, data_io, worker
from .jobs.manager import job_manager
from .logger import log
from .summary import calc_cell_area
from .tasks import create_task

DlgCalculateTcDataUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateTCData.ui")
)
DlgCalculateTcSummaryTableUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateTCSummaryTable.ui")
)


# TODO: Still need to code below for local calculation of Total Carbon change
class TCWorker(worker.AbstractWorker):
    def __init__(self, in_vrt, out_f, lc_band_nums, lc_years):
        worker.AbstractWorker.__init__(self)
        self.in_vrt = in_vrt
        self.out_f = out_f
        self.lc_years = lc_years
        self.lc_band_nums = [int(x) for x in lc_band_nums]

    def work(self):
        ds_in = gdal.Open(self.in_vrt)

        soc_band = ds_in.GetRasterBand(1)
        # clim_band = ds_in.GetRasterBand(2)

        block_sizes = soc_band.GetBlockSize()
        x_block_size = block_sizes[0]
        y_block_size = block_sizes[1]
        xsize = soc_band.XSize
        ysize = soc_band.YSize

        driver = gdal.GetDriverByName("GTiff")
        # Need a band for SOC degradation, plus bands for annual SOC, and for
        # annual LC
        ds_out = driver.Create(
            self.out_f,
            xsize,
            ysize,
            1 + len(self.lc_years) * 2,
            gdal.GDT_Int16,
            ["COMPRESS=LZW"],
        )
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
                    log(
                        "Processing of {} killed by user after processing {} out of {} blocks.".format(
                            self.prod_out_file, y, ysize
                        )
                    )
                    break
                self.progress.emit(
                    100 * (float(y) + (float(x) / xsize) * y_block_size) / ysize
                )
                if x + x_block_size < xsize:
                    cols = x_block_size
                else:
                    cols = xsize - x

                # Write initial soc to band 2 of the output file. Read SOC in
                # as float so the soc change calculations won't accumulate
                # error due to repeated truncation of ints
                soc = np.array(soc_band.ReadAsArray(x, y, cols, rows)).astype(
                    np.float32
                )
                ds_out.GetRasterBand(2).WriteArray(soc, x, y)

                blocks += 1

        if self.killed:
            del ds_in
            del ds_out
            os.remove(self.out_f)
            return None
        else:
            return True


class DlgCalculateTCData(calculate.DlgCalculateBase, DlgCalculateTcDataUi):
    groupBox_custom_bl: QtWidgets.QGroupBox
    groupBox_custom_tg: QtWidgets.QGroupBox
    use_hansen: QtWidgets.QRadioButton
    hansen_bl_year: QtWidgets.QDateEdit
    hansen_tg_year: QtWidgets.QDateEdit
    hansen_fc_threshold: QtWidgets.QSpinBox
    use_custom: QtWidgets.QRadioButton
    use_custom_initial: data_io.WidgetDataIOSelectTELayerImport
    use_custom_final: data_io.WidgetDataIOSelectTELayerImport
    radioButton_carbon_woods_hole: QtWidgets.QRadioButton
    radioButton_carbon_geocarbon: QtWidgets.QRadioButton
    radioButton_carbon_custom: QtWidgets.QRadioButton
    combo_layer_traj: data_io.WidgetDataIOSelectTELayerExisting
    radioButton_rootshoot_mokany: QtWidgets.QRadioButton
    radioButton_rootshoot_ipcc: QtWidgets.QRadioButton

    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        script: ExecutionScript,
        parent: QtWidgets.QWidget,
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)

        # # hack to allow add HiddenOutputpTab that automatically set
        # # out files in case of local process
        # self.add_output_tab(['.json', '.tif'])
        self.first_show = True
        self._finish_initialization()

    def showEvent(self, event):
        super().showEvent(event)
        self.use_custom_initial.populate()
        self.use_custom_final.populate()
        self.radioButton_carbon_custom.setEnabled(False)
        if self.first_show:
            self.first_show = False
            # Ensure the special value text (set to " ") is displayed by
            # default
            self.hansen_fc_threshold.setSpecialValueText(" ")
            self.hansen_fc_threshold.setValue(int(self.hansen_fc_threshold.minimum()))
        self.use_hansen.toggled.connect(self.lc_source_changed)
        self.use_custom.toggled.connect(self.lc_source_changed)
        # Ensure that dialogs are enabled/disabled as appropriate
        self.lc_source_changed()

        # Setup bounds for Hansen data
        hansen_start_year = conf.REMOTE_DATASETS["Forest cover"]["Hansen"]["Start year"]
        hansen_end_year = conf.REMOTE_DATASETS["Forest cover"]["Hansen"]["End year"]
        start_year = QtCore.QDate(hansen_start_year, 1, 1)
        end_year = QtCore.QDate(hansen_end_year, 12, 31)
        # TODO: remove this when local calculations are ready to be enabled
        self._disable_local_calculation_gui_elements()
        self.hansen_bl_year.setMinimumDate(start_year)
        self.hansen_bl_year.setMaximumDate(end_year)
        self.hansen_tg_year.setMinimumDate(start_year)
        self.hansen_tg_year.setMaximumDate(end_year)

    def _disable_local_calculation_gui_elements(self):
        self.use_custom.setHidden(True)
        self.groupBox_custom_bl.setHidden(True)
        self.groupBox_custom_tg.setHidden(True)

    def lc_source_changed(self):
        if self.use_hansen.isChecked():
            self.groupBox_hansen_period.setEnabled(True)
            self.groupBox_hansen_threshold.setEnabled(True)
            self.groupBox_custom_bl.setEnabled(False)
            self.groupBox_custom_tg.setEnabled(False)
        elif self.use_custom.isChecked():
            QtWidgets.QMessageBox.information(
                None,
                self.tr("Coming soon!"),
                self.tr("Custom forest cover data support is coming soon!"),
            )
            self.use_hansen.setChecked(True)
            # self.groupBox_hansen_period.setEnabled(False)
            # self.groupBox_hansen_threshold.setEnabled(False)
            # self.groupBox_custom_bl.setEnabled(True)
            # self.groupBox_custom_tg.setEnabled(True)

    def get_biomass_dataset(self):
        if self.radioButton_carbon_woods_hole.isChecked():
            return "woodshole"
        elif self.radioButton_carbon_geocarbon.isChecked():
            return "geocarbon"
        elif self.radioButton_carbon_custom.isChecked():
            return "custom"
        else:
            return None

    def get_method(self):
        if self.radioButton_rootshoot_ipcc.isChecked():
            return "ipcc"
        elif self.radioButton_rootshoot_mokany.isChecked():
            return "mokany"
        else:
            return None

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super().btn_calculate()
        if not ret:
            return
        if (
            self.hansen_fc_threshold.text()
            == self.hansen_fc_threshold.specialValueText()
        ) and self.use_hansen.isChecked():
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Enter a value for percent cover that is considered forest."),
            )
            return

        method = self.get_method()
        if not method:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Choose a method for calculating the root to shoot ratio."),
            )
            return

        biomass_data = self.get_biomass_dataset()
        if not method:
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"), self.tr("Choose a biomass dataset.")
            )
            return

        if self.use_custom.isChecked():
            self.calculate_locally(method, biomass_data)
        else:
            self.calculate_on_GEE(method, biomass_data)

    def calculate_locally(self, method, biomass_data):
        if not self.use_custom.isChecked():
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Due to the options you have chosen, this calculation must occur offline. You MUST select a custom land cover dataset."
                ),
            )
            return

        year_initial = self.lc_setup_tab.get_initial_year()
        year_final = self.lc_setup_tab.get_final_year()
        if int(year_initial) >= int(year_final):
            QtWidgets.QMessageBox.information(
                None,
                self.tr("Warning"),
                self.tr(
                    f"The initial year ({year_initial}) is greater than or "
                    "equal to the final year ({year_final}) - this analysis "
                    "might generate strange results."
                ),
            )

        if (
            self.aoi.calc_frac_overlap(
                qgis.core.QgsGeometry.fromRect(
                    self.lc_setup_tab.use_custom_initial.get_layer().extent()
                )
            )
            < 0.99
        ):
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Area of interest is not entirely within the initial land cover layer."
                ),
            )
            return

        if (
            self.aoi.calc_frac_overlap(
                qgis.core.QgsGeometry.fromRect(
                    self.lc_setup_tab.use_custom_final.get_layer().extent()
                )
            )
            < 0.99
        ):
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Area of interest is not entirely within the final land cover layer."
                ),
            )
            return

        # out_f = self.get_save_raster()
        # if not out_f:
        #     return
        out_f = self.output_tab.output_basename + ".tif"

        self.close()

        # Select the initial and final bands from initial and final datasets
        # (in case there is more than one lc band per dataset)
        lc_initial_vrt = self.lc_setup_widget.use_custom_initial.get_vrt()
        lc_final_vrt = self.lc_setup_tab.use_custom_final.get_vrt()
        lc_files = [lc_initial_vrt, lc_final_vrt]
        lc_years = [
            self.lc_setup_tab.get_initial_year(),
            self.lc_setup_tab.get_final_year(),
        ]
        lc_vrts = []
        for i in range(len(lc_files)):
            f = GetTempFilename(".vrt")
            # Add once since band numbers don't start at zero
            gdal.BuildVRT(
                f,
                lc_files[i],
                bandList=[i + 1],
                outputBounds=self.aoi.get_aligned_output_bounds_deprecated(
                    lc_initial_vrt
                ),
                resolution="highest",
                resampleAlg=gdal.GRA_NearestNeighbour,
                separate=True,
            )
            lc_vrts.append(f)

        climate_zones = os.path.join(
            os.path.dirname(__file__), "data", "ipcc_climate_zones.tif"
        )
        in_files = [climate_zones]
        in_files.extend(lc_vrts)

        in_vrt = GetTempFilename(".vrt")
        log("Saving SOC input files to {}".format(in_vrt))
        gdal.BuildVRT(
            in_vrt,
            in_files,
            resolution="highest",
            resampleAlg=gdal.GRA_NearestNeighbour,
            outputBounds=self.aoi.get_aligned_output_bounds_deprecated(lc_initial_vrt),
            separate=True,
        )
        # Lc bands start on band 3 as band 1 is initial soc, and band 2 is
        # climate zones
        lc_band_nums = np.arange(len(lc_files)) + 3
        # Remove temporary files
        for f in lc_vrts:
            os.remove(f)

        log("Saving total carbon to {}".format(out_f))
        tc_task = worker.StartWorker(
            TCWorker,
            "calculating change in total carbon",
            in_vrt,
            out_f,
            lc_band_nums,
            lc_years,
        )
        os.remove(in_vrt)

        if not tc_task.success:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Error calculating change in toal carbon."),
            )
            return

        band_infos = [
            BandInfo(
                "Total carbon (change)",
                add_to_map=True,
                metadata={"year_initial": lc_years[0], "year_final": lc_years[-1]},
            )
        ]
        for year in lc_years:
            if (year == lc_years[0]) or (year == lc_years[-1]):
                # Add first and last years to map
                add_to_map = True
            else:
                add_to_map = False
            band_infos.append(
                BandInfo("Total carbon", add_to_map=add_to_map, metadata={"year": year})
            )
        for year in lc_years:
            band_infos.append(BandInfo("Land cover", metadata={"year": year}))

        os.path.splitext(out_f)[0] + ".json"
        # TODO: finish implementation
        # - create payload
        # use job_manager to submit a local job

    def calculate_on_GEE(self, method, biomass_data):
        self.close()
        crosses_180th, geojsons = self.gee_bounding_box
        payload = {
            "year_initial": self.hansen_bl_year.date().year(),
            "year_final": self.hansen_tg_year.date().year(),
            "fc_threshold": int(self.hansen_fc_threshold.text().replace("%", "")),
            "method": method,
            "biomass_data": biomass_data,
            "geojsons": json.dumps(geojsons),
            "crs": self.aoi.get_crs_dst_wkt(),
            "crosses_180th": crosses_180th,
            "task_name": self.execution_name_le.text(),
            "task_notes": self.task_notes.toPlainText(),
        }

        resp = create_task(
            job_manager,
            payload, 
            self.script.id, 
            AlgorithmRunMode.REMOTE,
        )

        if resp:
            main_msg = "Submitted"
            description = "Total carbon submitted to Trends.Earth server."
        else:
            main_msg = "Error"
            description = "Unable to submit total carbon task to Trends.Earth server."
        self.mb.pushMessage(
            self.tr(main_msg), self.tr(description), level=0, duration=5
        )


class TCSummaryWorker(worker.AbstractWorker):
    def __init__(self, src_file, year_initial, year_final):
        worker.AbstractWorker.__init__(self)

        self.src_file = src_file
        self.year_initial = year_initial
        self.year_final = year_final

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        src_ds = gdal.Open(self.src_file)

        band_f_loss = src_ds.GetRasterBand(1)
        band_tc = src_ds.GetRasterBand(2)

        block_sizes = band_f_loss.GetBlockSize()
        xsize = band_f_loss.XSize
        ysize = band_f_loss.YSize

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
        forest_loss = np.zeros(self.year_final - self.year_initial)
        carbon_loss = np.zeros(self.year_final - self.year_initial)

        blocks = 0
        for y in range(0, ysize, y_block_size):
            if y + y_block_size < ysize:
                rows = y_block_size
            else:
                rows = ysize - y
            for x in range(0, xsize, x_block_size):
                if self.killed:
                    log(
                        "Processing of {} killed by user after processing {} out of {} blocks.".format(
                            self.prod_out_file, y, ysize
                        )
                    )
                    break
                self.progress.emit(
                    100 * (float(y) + (float(x) / xsize) * y_block_size) / ysize
                )
                if x + x_block_size < xsize:
                    cols = x_block_size
                else:
                    cols = xsize - x

                f_loss_array = band_f_loss.ReadAsArray(x, y, cols, rows)
                tc_array = band_tc.ReadAsArray(x, y, cols, rows)

                # Caculate cell area for each horizontal line
                cell_areas = np.array(
                    [
                        calc_cell_area(
                            lat + pixel_height * n,
                            lat + pixel_height * (n + 1),
                            long_width,
                        )
                        for n in range(rows)
                    ]
                )
                cell_areas.shape = (cell_areas.size, 1)
                # Make an array of the same size as the input arrays containing
                # the area of each cell (which is identicalfor all cells ina
                # given row - cell areas only vary among rows)
                cell_areas_array = np.repeat(cell_areas, cols, axis=1)

                initial_forest_pixels = (f_loss_array == 0) | (
                    f_loss_array > (self.year_initial - 2000)
                )
                # The site area includes everything that isn't masked
                area_missing = area_missing + np.sum(
                    ((f_loss_array == -32768) | (tc_array == -32768)) * cell_areas_array
                )
                area_water = area_water + np.sum(
                    (f_loss_array == -2) * cell_areas_array
                )
                area_non_forest = area_non_forest + np.sum(
                    (f_loss_array == -1) * cell_areas_array
                )
                area_site = area_site + np.sum(
                    (f_loss_array != -32767) * cell_areas_array
                )
                initial_forest_area = initial_forest_area + np.sum(
                    initial_forest_pixels * cell_areas_array
                )
                initial_carbon_total = initial_carbon_total + np.sum(
                    initial_forest_pixels
                    * tc_array
                    * (tc_array >= 0)
                    * cell_areas_array
                )

                for n in range(self.year_final - self.year_initial):
                    # Note the codes are year - 2000
                    forest_loss[n] = forest_loss[n] + np.sum(
                        (f_loss_array == self.year_initial - 2000 + n + 1)
                        * cell_areas_array
                    )
                    # Check units here - is tc_array in per m or per ha?
                    carbon_loss[n] = carbon_loss[n] + np.sum(
                        (f_loss_array == self.year_initial - 2000 + n + 1)
                        * tc_array
                        * (tc_array >= 0)
                        * cell_areas_array
                    )

                blocks += 1
            lat += pixel_height * rows
        self.progress.emit(100)

        if self.killed:
            return None
        else:
            # Convert all area tables from meters into hectares
            forest_loss = forest_loss * 1e-4
            # Note that carbon is scaled by 10
            carbon_loss = carbon_loss * 1e-4 / 10
            area_missing = area_missing * 1e-4
            area_water = area_water * 1e-4
            area_non_forest = area_non_forest * 1e-4
            area_site = area_site * 1e-4
            initial_forest_area = initial_forest_area * 1e-4
            # Note that carbon is scaled by 10
            initial_carbon_total = initial_carbon_total * 1e-4 / 10

        return list(
            (
                forest_loss,
                carbon_loss,
                area_missing,
                area_water,
                area_non_forest,
                area_site,
                initial_forest_area,
                initial_carbon_total,
            )
        )


class DlgCalculateTCSummaryTable(
    calculate.DlgCalculateBase, DlgCalculateTcSummaryTableUi
):
    LOCAL_SCRIPT_NAME = "total-carbon-summary"

    combo_layer_f_loss: data_io.WidgetDataIOSelectTELayerExisting
    combo_layer_tc: data_io.WidgetDataIOSelectTELayerExisting

    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        script: ExecutionScript,
        parent: QtWidgets.QWidget,
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)
        self._finish_initialization()

    def showEvent(self, event):
        super().showEvent(event)

        self.combo_layer_f_loss.populate()
        self.combo_layer_tc.populate()

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super().btn_calculate()
        if not ret:
            return

        ######################################################################
        # Check that all needed input layers are selected
        if len(self.combo_layer_f_loss.layer_list) == 0:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "You must add a forest loss layer to your map before you can use "
                    "the carbon change summary tool."
                ),
            )
            return
        if len(self.combo_layer_tc.layer_list) == 0:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "You must add a total carbon layer to your map before you can "
                    "use the carbon change summary tool."
                ),
            )
            return
        #######################################################################
        # Check that the layers cover the full extent needed
        layer_f_loss = self.combo_layer_f_loss.get_layer()
        layer_f_loss_extent_geom = qgis.core.QgsGeometry.fromRect(layer_f_loss.extent())
        if self.aoi.calc_frac_overlap(layer_f_loss_extent_geom) < 0.99:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Area of interest is not entirely within the forest loss layer."
                ),
            )
            return
        layer_tc = self.combo_layer_tc.get_layer()
        layer_tc_extent_geom = qgis.core.QgsGeometry.fromRect(layer_tc.extent())
        if self.aoi.calc_frac_overlap(layer_tc_extent_geom) < 0.99:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Area of interest is not entirely within the total carbon layer."
                ),
            )
            return

        #######################################################################
        # Check that all of the productivity layers have the same resolution
        # and CRS
        def res(layer):
            return (
                round(layer.rasterUnitsPerPixelX(), 10),
                round(layer.rasterUnitsPerPixelY(), 10),
            )

        if res(layer_f_loss) != res(layer_tc):
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Resolutions of forest loss and total carbon layers do not match."
                ),
            )
            return

        self.close()

        f_loss_usable = self.combo_layer_f_loss.get_current_band()
        tc_usable = self.combo_layer_tc.get_current_band()
        job_params = {
            "task_name": self.options_tab.task_name.text(),
            "task_notes": self.options_tab.task_notes.toPlainText(),
            "f_loss_path": str(f_loss_usable.path),
            "f_loss_band_index": f_loss_usable.band_index,
            "tc_path": str(tc_usable.path),
            "tc_band_index": tc_usable.band_index,
            "year_initial": f_loss_usable.band_info.metadata["year_initial"],
            "year_final": f_loss_usable.band_info.metadata["year_final"],
        }
        job_manager.submit_local_job(job_params, self.LOCAL_SCRIPT_NAME, self.aoi)
