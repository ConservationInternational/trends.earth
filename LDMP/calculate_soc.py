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

import qgis.gui
from qgis.PyQt import QtGui, QtWidgets, uic
from te_schemas.algorithms import AlgorithmRunMode, ExecutionScript
from te_schemas.land_cover import LCLegendNesting, LCTransitionDefinitionDeg

from . import calculate, data_io, lc_setup
from .jobs.manager import job_manager
from .lc_setup import get_trans_matrix
from .logger import log
from .tasks import create_task

DlgCalculateSocUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateSOC.ui")
)


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
        script: ExecutionScript,
        parent: QtWidgets.QWidget = None,
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)

        self.regimes = [
            ("Temperate dry (Fl = 0.80)", 0.80),
            ("Temperate moist (Fl = 0.69)", 0.69),
            ("Tropical dry (Fl = 0.58)", 0.58),
            ("Tropical moist (Fl = 0.48)", 0.48),
            ("Tropical montane (Fl = 0.64)", 0.64),
        ]

        if self.script.run_mode == AlgorithmRunMode.LOCAL:
            self.lc_setup_widget = lc_setup.LandCoverSetupLocalExecutionWidget(self)
            self.changed_region.connect(self.lc_setup_widget.populate_combos)
        elif self.script.run_mode == AlgorithmRunMode.REMOTE:
            self.lc_setup_widget = lc_setup.LandCoverSetupRemoteExecutionWidget(
                parent=self
            )

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
        #     self.script.run_mode == AlgorithmRunMode.REMOTE
        # )
        # self.lc_setup_widget.custom_frame.setVisible(
        #     self.script.run_mode == AlgorithmRunMode.LOCAL
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
            return [
                r[1]
                for r in self.regimes
                if r[0] == self.fl_chooseRegime_comboBox.currentText()
            ][0]
        else:
            return "per pixel"

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super().btn_calculate()
        if not ret:
            return

        if (
            self.script.run_mode == AlgorithmRunMode.LOCAL
            or self.groupBox_custom_SOC.isChecked()
        ):
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
                ),
            )
            return
        if self.script.run_mode != AlgorithmRunMode.LOCAL:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Due to the options you have chosen, this calculation must occur "
                    "offline. You MUST select a custom land cover dataset."
                ),
            )
            return

        if len(self.comboBox_custom_soc.layer_list) == 0:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "You must add a soil organic carbon layer to your map before you "
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
                    f"The initial year ({year_initial}) is greater than or "
                    "equal to the final year ({year_final}) - this analysis "
                    "might generate strange results."
                ),
            )

        initial_layer = self.lc_setup_widget.initial_year_layer_cb.get_layer()
        # initial_layer = self.lc_setup_widget.use_custom_initial.get_layer()
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
        # final_layer = self.lc_setup_widget.use_custom_final.get_layer()
        final_extent_geom = qgis.core.QgsGeometry.fromRect(final_layer.extent())
        if self.aoi.calc_frac_overlap(final_extent_geom) < 0.99:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Area of interest is not entirely within the final land cover "
                    "layer."
                ),
            )
            return

        self.close()

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
        # initial_usable = self.lc_setup_widget.use_custom_initial.get_current_band()
        # final_usable = self.lc_setup_widget.use_custom_final.get_current_band()
        soc_usable = self.comboBox_custom_soc.get_current_band()

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
            "legend_nesting_custom_to_ipcc": LCLegendNesting.Schema().dump(
                lc_setup.ipcc_lc_nesting_from_settings()
            ),
            "trans_matrix": LCTransitionDefinitionDeg.Schema().dump(get_trans_matrix()),
            "fl": self.get_fl(),
        }
        job_manager.submit_local_job(job_params, self.LOCAL_SCRIPT_NAME, self.aoi)

    def calculate_on_GEE(self):
        log("inside calculate_on_GEE...")
        self.close()

        crosses_180th, geojsons = self.gee_bounding_box
        payload = {
            "year_initial": self.lc_setup_widget.initial_year_de.date().year(),
            "year_final": self.lc_setup_widget.target_year_de.date().year(),
            "fl": self.get_fl(),
            "download_annual_lc": self.download_annual_lc.isChecked(),
            "geojsons": json.dumps(geojsons),
            "crs": self.aoi.get_crs_dst_wkt(),
            "crosses_180th": crosses_180th,
            "legend_nesting_esa_to_custom": LCLegendNesting.Schema().dump(
                lc_setup.esa_lc_nesting_from_settings()
            ),
            "legend_nesting_custom_to_ipcc": LCLegendNesting.Schema().dump(
                lc_setup.ipcc_lc_nesting_from_settings()
            ),
            "trans_matrix": LCTransitionDefinitionDeg.Schema().dump(get_trans_matrix()),
            "task_name": self.execution_name_le.text(),
            "task_notes": self.options_tab.task_notes.toPlainText(),
        }

        resp = create_task(
            job_manager,
            payload, 
            self.script.id, 
            AlgorithmRunMode.REMOTE,
        )
        if resp:
            main_msg = "Submitted"
            description = "Soil organic carbon task submitted to Trends.Earth server."

        else:
            main_msg = "Error"
            description = (
                "Unable to submit Soil organic carbon task to Trends.Earth server."
            )
        self.mb.pushMessage(
            self.tr(main_msg), self.tr(description), level=0, duration=5
        )
        log("leaving calculate_on_GEE...")
