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
import typing
from pathlib import Path

import qgis.gui
from qgis.PyQt import QtCore, QtWidgets, uic
from te_schemas.algorithms import AlgorithmRunMode, ExecutionScript
from te_schemas.productivity import ProductivityMode

from . import calculate, conf
from .jobs.manager import job_manager
from .logger import log
from .tasks import create_task

DlgCalculateProdUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateProd.ui")
)


class DlgCalculateProd(calculate.DlgCalculateBase, DlgCalculateProdUi):
    mb: qgis.gui.QgsMessageBar

    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        script: ExecutionScript,
        parent: QtWidgets.QWidget = None,
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)
        self.mb = iface.messageBar()
        self.traj_indic.addItems(list(self.trajectory_functions.keys()))
        self.traj_indic.currentIndexChanged.connect(self.traj_indic_changed)
        self.dataset_climate_update()
        ndvi_datasets = []

        for ds_name, ds_details in conf.REMOTE_DATASETS["NDVI"].items():
            if ds_details["Temporal resolution"] == "annual":
                ndvi_datasets.append(ds_name)
        self.dataset_ndvi.addItems(ndvi_datasets)
        self.dataset_ndvi.setCurrentIndex(1)
        self.start_year_climate = 0
        self.end_year_climate = 9999
        self.start_year_ndvi = 0
        self.end_year_ndvi = 9999
        self.dataset_ndvi_changed()
        self.traj_climate_changed()
        self.dataset_ndvi.currentIndexChanged.connect(self.dataset_ndvi_changed)
        self.traj_climate.currentIndexChanged.connect(self.traj_climate_changed)
        self.mode_te_prod.toggled.connect(self.mode_te_prod_toggled)
        self.mode_te_prod_toggled()
        self.resize(self.width(), 711)
        self._finish_initialization()

        self.combo_lpd.addItems(
            [*conf.REMOTE_DATASETS["Land Productivity Dynamics"].keys()]
        )

        self.advance_configurations.setCollapsed(True)

    @property
    def trajectory_functions(self) -> typing.Dict:
        return self.script.additional_configuration["trajectory functions"]

    def traj_indic_changed(self):
        self.dataset_climate_update()

    def mode_te_prod_toggled(self):
        if self.mode_lpd_jrc.isChecked():
            self.combo_lpd.setEnabled(True)
            self.advance_configurations.setEnabled(False)
            self.groupBox_ndvi_dataset.setEnabled(False)
            self.groupBox_traj.setEnabled(False)
            self.groupBox_perf.setEnabled(False)
            self.groupBox_state.setEnabled(False)
            self.advance_configurations.setCollapsed(True)
        else:
            self.combo_lpd.setEnabled(False)
            self.advance_configurations.setEnabled(True)
            self.groupBox_ndvi_dataset.setEnabled(True)
            self.groupBox_traj.setEnabled(True)
            self.groupBox_perf.setEnabled(True)
            self.groupBox_state.setEnabled(True)
            self.advance_configurations.setCollapsed(True)

    def dataset_climate_update(self):
        self.traj_climate.clear()
        self.climate_datasets = {}
        climate_types = self.trajectory_functions[self.traj_indic.currentText()][
            "climate types"
        ]

        for climate_type in climate_types:
            self.climate_datasets.update(conf.REMOTE_DATASETS[climate_type])
            self.traj_climate.addItems(list(conf.REMOTE_DATASETS[climate_type].keys()))

    def traj_climate_changed(self):
        if self.traj_climate.currentText() == "":
            self.start_year_climate = 0
            self.end_year_climate = 9999
        else:
            self.start_year_climate = self.climate_datasets[
                self.traj_climate.currentText()
            ]["Start year"]
            self.end_year_climate = self.climate_datasets[
                self.traj_climate.currentText()
            ]["End year"]
        self.update_time_bounds()

    def dataset_ndvi_changed(self):
        this_ndvi_dataset = conf.REMOTE_DATASETS["NDVI"][
            self.dataset_ndvi.currentText()
        ]
        self.start_year_ndvi = this_ndvi_dataset["Start year"]
        self.end_year_ndvi = this_ndvi_dataset["End year"]

        self.update_time_bounds()

    def update_time_bounds(self):
        # State and performance depend only on NDVI data
        # TODO: need to also account for GAEZ and/or CCI data dates for
        # stratification
        start_year = QtCore.QDate(self.start_year_ndvi, 1, 1)
        end_year = QtCore.QDate(self.end_year_ndvi, 12, 31)

        # State
        self.perf_year_start.setMinimumDate(start_year)
        self.perf_year_start.setMaximumDate(end_year)
        self.perf_year_end.setMinimumDate(start_year)
        self.perf_year_end.setMaximumDate(end_year)

        # Performance
        self.state_year_bl_start.setMinimumDate(start_year)
        self.state_year_bl_start.setMaximumDate(end_year)
        self.state_year_bl_end.setMinimumDate(start_year)
        self.state_year_bl_end.setMaximumDate(end_year)
        self.state_year_tg_start.setMinimumDate(start_year)
        self.state_year_tg_start.setMaximumDate(end_year)
        self.state_year_tg_end.setMinimumDate(start_year)
        self.state_year_tg_end.setMaximumDate(end_year)

        # Trajectory - needs to also account for climate data
        start_year_traj = QtCore.QDate(
            max(self.start_year_ndvi, self.start_year_climate), 1, 1
        )
        end_year_traj = QtCore.QDate(
            min(self.end_year_ndvi, self.end_year_climate), 12, 31
        )

        self.traj_year_start.setMinimumDate(start_year_traj)
        self.traj_year_start.setMaximumDate(end_year_traj)
        self.traj_year_end.setMinimumDate(start_year_traj)
        self.traj_year_end.setMaximumDate(end_year_traj)

    def btn_cancel(self):
        self.close()

    def _get_prod_mode(self, radio_lpd_te, cb_lpd):
        if radio_lpd_te.isChecked():
            return ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value
        else:
            if "FAO-WOCAT" in cb_lpd.currentText():
                return ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value
            elif "JRC" in cb_lpd.currentText():
                return ProductivityMode.JRC_5_CLASS_LPD.value
        return None

    def btn_calculate(self):
        if self.mode_te_prod.isChecked() and not (
            self.groupBox_traj.isChecked()
            or self.groupBox_perf.isChecked()
            or self.groupBox_state.isChecked()
        ):
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Choose one or more productivity sub-indicator to calculate."),
            )

            return

        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super().btn_calculate()

        if not ret:
            return

        self.close()

        ndvi_dataset = conf.REMOTE_DATASETS["NDVI"][self.dataset_ndvi.currentText()][
            "GEE Dataset"
        ]

        if self.traj_climate.currentText() != "":
            climate_gee_dataset = self.climate_datasets[
                self.traj_climate.currentText()
            ]["GEE Dataset"]
            log("climate_gee_dataset {}".format(climate_gee_dataset))
        else:
            climate_gee_dataset = None

        crosses_180th, geojsons = self.gee_bounding_box
        payload = {
            "geojsons": json.dumps(geojsons),
            "task_name": self.execution_name_le.text(),
            "task_notes": self.task_notes.toPlainText(),
        }

        prod_mode = self._get_prod_mode(self.mode_te_prod, self.combo_lpd)

        if prod_mode == ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value:
            payload.update(
                {
                    "prod_mode": prod_mode,
                    "calc_traj": self.groupBox_traj.isChecked(),
                    "calc_perf": self.groupBox_perf.isChecked(),
                    "calc_state": self.groupBox_state.isChecked(),
                    "prod_traj_year_initial": self.traj_year_start.date().year(),
                    "prod_traj_year_final": self.traj_year_end.date().year(),
                    "prod_perf_year_initial": self.perf_year_start.date().year(),
                    "prod_perf_year_final": self.perf_year_end.date().year(),
                    "prod_state_year_bl_start": self.state_year_bl_start.date().year(),
                    "prod_state_year_bl_end": self.state_year_bl_end.date().year(),
                    "prod_state_year_tg_start": self.state_year_tg_start.date().year(),
                    "prod_state_year_tg_end": self.state_year_tg_end.date().year(),
                    "crs": self.aoi.get_crs_dst_wkt(),
                    "ndvi_gee_dataset": ndvi_dataset,
                    "climate_gee_dataset": climate_gee_dataset,
                }
            )
            # This will add in the trajectory-method parameter for productivity
            # trajectory
            current_trajectory_function = self.trajectory_functions[
                self.traj_indic.currentText()
            ]
            payload.update(current_trajectory_function["params"])

        elif prod_mode in (
            ProductivityMode.JRC_5_CLASS_LPD.value,
            ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value,
        ):
            prod_dataset = conf.REMOTE_DATASETS["Land Productivity Dynamics"][
                self.combo_lpd.currentText()
            ]
            prod_asset = prod_dataset["GEE Dataset"]
            prod_start_year = prod_dataset["Start year"]
            prod_end_year = prod_dataset["End year"]
            payload.update(
                {
                    "prod_mode": prod_mode,
                    "prod_asset": prod_asset,
                    "year_initial": prod_start_year,
                    "year_final": prod_end_year,
                }
            )
        else:
            raise ValueError("Unknown prod_mode {prod_mode}")

        resp = create_task(
            job_manager,
            payload,
            self.script.id,
            AlgorithmRunMode.REMOTE,
        )

        if resp:
            main_msg = "Submitted"
            description = "Productivity task submitted to Trends.Earth server."

        else:
            main_msg = "Error"
            description = "Unable to submit productivity task to Trends.Earth server."
        self.mb.pushMessage(
            self.tr(main_msg), self.tr(description), level=0, duration=5
        )
