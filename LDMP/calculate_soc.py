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
from qgis.PyQt import (
    QtGui,
    QtWidgets,
    uic,
)

from . import (
    calculate,
    data_io,
    lc_setup,
)

from .algorithms import models
from .jobs.manager import job_manager
from .logger import log

DlgCalculateSocUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateSOC.ui"))


from te_schemas.schemas import BandInfo, BandInfoSchema


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
