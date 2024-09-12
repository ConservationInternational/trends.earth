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

import functools
import json
from pathlib import Path

import qgis.core
import qgis.gui
from qgis.PyQt import QtWidgets, uic
from te_schemas.algorithms import AlgorithmRunMode, ExecutionScript
from te_schemas.land_cover import LCLegendNesting, LCTransitionDefinitionDeg

from . import calculate, lc_setup
from .jobs.manager import job_manager
from .tasks import create_task

DlgCalculateLcUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateLC.ui")
)


class DlgCalculateLC(calculate.DlgCalculateBase, DlgCalculateLcUi):
    LOCAL_SCRIPT_NAME = "local-land-cover"

    advanced_configurations: qgis.gui.QgsCollapsibleGroupBox
    scrollAreaWidgetContents: QtWidgets.QWidget

    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        script: ExecutionScript,
        parent: QtWidgets.QWidget,
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)

        if self.script.run_mode == AlgorithmRunMode.LOCAL:
            self.lc_setup_widget = lc_setup.LandCoverSetupLocalExecutionWidget(
                parent=self
            )
            self.changed_region.connect(self.lc_setup_widget.populate_combos)
        elif self.script.run_mode == AlgorithmRunMode.REMOTE:
            self.lc_setup_widget = lc_setup.LandCoverSetupRemoteExecutionWidget(
                parent=self
            )

        self.lc_define_deg_widget = lc_setup.LCDefineDegradationWidget()
        self.advanced_configurations.setCollapsed(True)
        self.scrollAreaWidgetContents.layout().insertWidget(0, self.lc_setup_widget)
        self.advanced_configurations.layout().insertWidget(0, self.lc_define_deg_widget)
        self._finish_initialization()

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super().btn_calculate()
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

        trans_matrix = self.lc_define_deg_widget.get_trans_matrix_from_widget()
        lc_setup.trans_matrix_to_settings(trans_matrix)

        payload = {
            "year_initial": self.lc_setup_widget.initial_year_de.date().year(),
            "year_final": self.lc_setup_widget.target_year_de.date().year(),
            "geojsons": json.dumps(geojsons),
            "crs": self.aoi.get_crs_dst_wkt(),
            "crosses_180th": crosses_180th,
            "legend_nesting_esa_to_custom": LCLegendNesting.Schema().dump(
                lc_setup.esa_lc_nesting_from_settings()
            ),
            "legend_nesting_custom_to_ipcc": LCLegendNesting.Schema().dump(
                lc_setup.ipcc_lc_nesting_from_settings()
            ),
            "trans_matrix": LCTransitionDefinitionDeg.Schema().dump(trans_matrix),
            "task_name": self.execution_name_le.text(),
            "task_notes": self.task_notes.toPlainText(),
        }

        create_task(
            job_manager,
            payload,
            self.script.id,
            AlgorithmRunMode.REMOTE,
            self.job_submitted,
        )

    def job_submitted(self, exception, result=None):
        if result is not None:
            main_msg = "Submitted"
            description = "Land cover task submitted to Trends.Earth server."
        else:
            main_msg = "Error"
            description = "Unable to submit land cover task to Trends.Earth server."
        self.mb.pushMessage(
            self.tr(main_msg), self.tr(description), level=0, duration=5
        )

    def calculate_locally(self):
        if len(self.lc_setup_widget.initial_year_layer_cb.layer_list) == 0:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "You must add an initial land cover layer to your map before you "
                    "can run the calculation."
                ),
            )
            return

        if len(self.lc_setup_widget.target_year_layer_cb.layer_list) == 0:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "You must add a final land cover layer to your map before you "
                    "can run the calculation."
                ),
            )
            return

        year_initial = self.lc_setup_widget.get_initial_year()
        year_final = self.lc_setup_widget.get_final_year()

        if int(year_initial) >= int(year_final):
            QtWidgets.QMessageBox.information(
                None,
                self.tr("Warning"),
                self.tr(
                    "The initial year ({}) is greater than or equal to the target "
                    "year ({}) - this analysis might generate strange "
                    "results.".format(year_initial, year_final)
                ),
            )

        initial_layer = self.lc_setup_widget.initial_year_layer_cb.get_layer()
        initial_extent_geom = qgis.core.QgsGeometry.fromRect(initial_layer.extent())
        if self.aoi.calc_frac_overlap(initial_extent_geom) < 0.99:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Area of interest is not entirely within the initial land cover "
                    "layer."
                ),
            )
            return

        final_layer = self.lc_setup_widget.target_year_layer_cb.get_layer()
        final_extent_geom = qgis.core.QgsGeometry.fromRect(final_layer.extent())
        if self.aoi.calc_frac_overlap(final_extent_geom) < 0.99:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Area of interest is not entirely within the final land "
                    "cover layer."
                ),
            )
            return

        initial_usable = self.lc_setup_widget.initial_year_layer_cb.get_current_band()
        final_usable = self.lc_setup_widget.target_year_layer_cb.get_current_band()
        # TODO: Fix for case where nesting varies between initial and final
        # bands
        initial_nesting = initial_usable.band_info.metadata.get("nesting")
        final_nesting = final_usable.band_info.metadata.get("nesting")
        if (initial_nesting and final_nesting) and (initial_nesting != final_nesting):
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Nesting of land cover legends for "
                    "initial and final land cover layer must be identical."
                ),
            )
            return

        self.close()

        trans_matrix = self.lc_define_deg_widget.get_trans_matrix_from_widget()
        lc_setup.trans_matrix_to_settings(trans_matrix)

        job_params = {
            "task_name": self.execution_name_le.text(),
            "task_notes": self.task_notes.toPlainText(),
            "year_initial": year_initial,
            "year_final": year_final,
            "lc_initial_path": str(initial_usable.path),
            "lc_initial_band_index": initial_usable.band_index,
            "lc_final_path": str(final_usable.path),
            "lc_final_band_index": final_usable.band_index,
            "legend_nesting": initial_nesting,
            "trans_matrix": LCTransitionDefinitionDeg.Schema().dumps(trans_matrix),
        }

        create_task(
            job_manager,
            job_params,
            self.LOCAL_SCRIPT_NAME,
            AlgorithmRunMode.LOCAL,
            self.aoi,
        )
