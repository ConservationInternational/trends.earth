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
from te_schemas.land_cover import LCLegendNesting, LCTransitionDefinitionDeg

from . import calculate, lc_setup, subnational
from .jobs.manager import job_manager

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

        # Subnational units
        self.unit_matrix_widgets: dict[str, lc_setup.LCDefineDegradationWidget] = {}
        self.unit_matrix_tabs = QtWidgets.QTabWidget()
        self.unit_matrix_tabs.setVisible(False)
        self.advanced_configurations.layout().insertWidget(1, self.unit_matrix_tabs)
        self._units: list[dict] = []
        self.changed_region.connect(self._refresh_units)

        self._finish_initialization()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_units()

    def _refresh_units(self):
        units = subnational.get_subnational_units()
        self._units = units

        unit_ids = [u.get("id") for u in units]
        for unit_id in list(self.unit_matrix_widgets):
            if unit_id not in unit_ids:
                widget = self.unit_matrix_widgets.pop(unit_id)
                self.unit_matrix_tabs.removeTab(self.unit_matrix_tabs.indexOf(widget))
                widget.deleteLater()

        for index, unit in enumerate(units):
            unit_id = unit.get("id")
            label = unit.get("name") or self.tr("Unit")
            widget = self.unit_matrix_widgets.get(unit_id)
            if widget is None:
                widget = lc_setup.LCDefineDegradationWidget(unit_key=unit_id)
                self.unit_matrix_widgets[unit_id] = widget
                self.unit_matrix_tabs.insertTab(index, widget, label)
            else:
                current = self.unit_matrix_tabs.indexOf(widget)
                if current != index:
                    self.unit_matrix_tabs.removeTab(current)
                    self.unit_matrix_tabs.insertTab(index, widget, label)
                else:
                    self.unit_matrix_tabs.setTabText(index, label)

        self.lc_define_deg_widget.setVisible(not units)
        self.unit_matrix_tabs.setVisible(bool(units))

        if self.script.run_mode == AlgorithmRunMode.LOCAL:
            self.lc_setup_widget.populate_combos_for_units(units)

    def _setup_alg_help(self):
        self.alg_help.setHtml(
            self.tr(
                "<h3>Land cover</h3>"
                "<p>To assess changes in land cover users need land cover maps"
                " covering the study area for the baseline and target years. These"
                " maps need to be of acceptable accuracy and created in such a way"
                " which allows for valid comparisons. Trends.Earth uses ESA CCI land"
                " cover maps as the default dataset, but local maps can also be used."
                " The indicator is computed as follows:</p>"
                "<ol>"
                "<li>Reclassify both land cover maps to the 7 land cover classes"
                " needed for reporting to the UNCCD (forest, grassland, cropland,"
                " wetland, artificial area, bare land and water).</li>"
                "<li>Perform a land cover transition analysis to identify which pixels"
                " remained in the same land cover class, and which ones changed.</li>"
                "<li>Based on your local knowledge of the conditions in the study area"
                " and the land degradation processed occurring there, use the table"
                " below, in the advanced section, to identify which transitions"
                " correspond to degradation (- sign), improvement (+ sign), or no"
                " change in terms of land condition (zero).</li>"
                "<li>Trends.Earth will combine the information from the land cover maps"
                " and the table of degradation typologies by land cover transition to"
                " compute the land cover sub-indicator.</li>"
                "</ol>"
                "<p><a href='https://docs.trends.earth/en/latest/for_users/features/unccdreporting.html#land-cover'>"
                "More information on the Land Cover SDG 15.3.1 Sub-indicator</a></p>"
            )
        )

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super().btn_calculate()
        if not ret:
            return

        self._refresh_units()
        units = self._units

        if self.script.run_mode == AlgorithmRunMode.REMOTE:
            if units:
                self.calculate_on_GEE_subnational(units)
            else:
                self.calculate_on_GEE()
        elif self.script.run_mode == AlgorithmRunMode.LOCAL:
            if units:
                self.calculate_locally_subnational(units)
            else:
                self.calculate_locally()
        else:
            raise NotImplementedError

    def calculate_on_GEE_subnational(self, units):
        def build(unit, unit_aoi):
            matrix = self.unit_matrix_widgets[unit["id"]].get_trans_matrix_from_widget()
            return self._gee_payload(matrix)

        self.submit_subnational_remote(
            units, build, self.tr("Land cover"), on_submit=self._save_unit_matrix
        )

    def _save_unit_matrix(self, unit: dict):
        lc_setup.trans_matrix_to_settings(
            self.unit_matrix_widgets[unit["id"]].get_trans_matrix_from_widget(),
            unit["id"],
        )

    def calculate_on_GEE(self):
        self.close()
        trans_matrix = self.lc_define_deg_widget.get_trans_matrix_from_widget()
        lc_setup.trans_matrix_to_settings(trans_matrix)
        payload = self._gee_payload(trans_matrix)
        self.submit_remote_job_with_message(payload, self.tr("Land cover"))

    def _gee_payload(self, trans_matrix) -> dict:
        crosses_180th, geojsons = self.gee_bounding_box

        return {
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

    def _local_job_params(self, aoi, matrix_widget) -> dict | None:
        """Validate the selection against ``aoi``; None if it is not usable."""
        if self.lc_setup_widget.initial_year_layer_cb.show_validation_error(
            self, "initial land cover", "the calculation"
        ):
            return

        if self.lc_setup_widget.target_year_layer_cb.show_validation_error(
            self, "final land cover", "the calculation"
        ):
            return

        year_initial = self.lc_setup_widget.get_initial_year()
        year_final = self.lc_setup_widget.get_final_year()

        # Safety check - should not happen if validation above passed
        if year_initial is None or year_final is None:
            return

        if int(year_initial) >= int(year_final):
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    f"The initial year ({year_initial}) must be less than the target "
                    f"year ({year_final}). Please select a valid time period."
                ),
            )
            return

        initial_layer = self.lc_setup_widget.initial_year_layer_cb.get_layer()
        initial_extent_geom = qgis.core.QgsGeometry.fromRect(initial_layer.extent())
        if aoi.calc_frac_overlap(initial_extent_geom) < 0.99:
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
        if aoi.calc_frac_overlap(final_extent_geom) < 0.99:
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

        trans_matrix = matrix_widget.get_trans_matrix_from_widget()

        return {
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

    def calculate_locally(self):
        job_params = self._local_job_params(self.aoi, self.lc_define_deg_widget)
        if job_params is None:
            return

        self.close()
        lc_setup.trans_matrix_to_settings(
            self.lc_define_deg_widget.get_trans_matrix_from_widget()
        )
        job_manager.submit_local_job_as_qgstask(
            job_params, self.LOCAL_SCRIPT_NAME, self.aoi
        )

    def calculate_locally_subnational(self, units):
        def build(unit, unit_aoi):
            return self._local_job_params(
                unit_aoi, self.unit_matrix_widgets[unit["id"]]
            )

        self.submit_subnational_local(units, build, on_submit=self._save_unit_matrix)
