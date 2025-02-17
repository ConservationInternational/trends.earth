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

import qgis.core
import qgis.gui
from qgis.PyQt import QtWidgets, uic
from te_schemas.algorithms import AlgorithmRunMode, ExecutionScript

from . import calculate, data_io
from .jobs.manager import job_manager
from .localexecution import biomassrestoration
from .tasks import create_task

DlgCalculateRestBiomassDataUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateRestBiomassData.ui")
)
DlgCalculateRestBiomassSummaryTableUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateRestBiomassSummaryTable.ui")
)


class DlgCalculateRestBiomassData(
    calculate.DlgCalculateBase, DlgCalculateRestBiomassDataUi
):
    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        script: ExecutionScript,
        parent: QtWidgets.QWidget,
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)
        self.first_show = True
        self._finish_initialization()

    def showEvent(self, event):
        super().showEvent(event)

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super().btn_calculate()
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
            "length_yr": self.spinBox_years.value(),
            "rest_type": self.get_rest_type(),
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
            description = "Restoration biomass change submitted to Trends.Earth server."
        else:
            main_msg = "Error"
            description = (
                "Unable to submit restoration biomass change task to Google Earth "
                "Engine."
            )
        self.mb.pushMessage(
            self.tr(main_msg), self.tr(description), level=0, duration=5
        )


class DlgCalculateRestBiomassSummaryTable(
    calculate.DlgCalculateBase, DlgCalculateRestBiomassSummaryTableUi
):
    LOCAL_SCRIPT_NAME = "change-biomass-summary-table"

    combo_layer_biomass_diff: data_io.WidgetDataIOSelectTELayerExisting

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
                ),
            )
            return
        #######################################################################
        # Check that the layers cover the full extent needed
        layer_biomass = self.combo_layer_biomass_diff.get_layer()
        layer_biomass_extent_geometry = qgis.core.QgsGeometry.fromRect(
            layer_biomass.extent()
        )
        if self.aoi.calc_frac_overlap(layer_biomass_extent_geometry) < 0.99:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Area of interest is not entirely within the biomass layer."),
            )
            return

        params = biomassrestoration.get_main_restoration_job_params(
            self.combo_layer_biomass_diff
        )

        params["task_name"] = self.options_tab.task_name.text()
        params["task_notes"] = self.options_tab.task_notes.toPlainText()

        self.close()

        job_manager.submit_local_job(params, self.LOCAL_SCRIPT_NAME, self.aoi)
