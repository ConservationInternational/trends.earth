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
from qgis.PyQt import QtWidgets
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QDate
from qgis.PyQt.QtCore import Qt
from te_schemas.algorithms import ExecutionScript

from .calculate import (
    DlgCalculateBase,
)
from .conf import KNOWN_SCRIPTS
from .jobs.manager import job_manager
from .logger import log
from .settings import AreaWidget
from .settings import AreaWidgetSection


Ui_DlgTimeseries, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgTimeseries.ui")
)


def show_time_series(iface, parent=None, use_tool_flag=True):
    """
    Show time-series dialog.
    """
    time_series_dlg = DlgTimeseries(iface, KNOWN_SCRIPTS["time-series"], parent)
    if use_tool_flag:
        time_series_dlg.setWindowFlags(time_series_dlg.windowFlags() | Qt.Tool)
        time_series_dlg.show()
    else:
        time_series_dlg.exec_()

    return time_series_dlg


class DlgTimeseries(DlgCalculateBase, Ui_DlgTimeseries):
    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        script: ExecutionScript,
        parent: QtWidgets.QWidget = None,
    ):
        """Constructor."""
        super().__init__(iface, script, parent)
        self.setupUi(self)

        qgis.gui.QgsGui.enableAutoGeometryRestore(self)

        ndvi_datasets = [
            x
            for x in list(self.datasets["NDVI"].keys())
            if self.datasets["NDVI"][x]["Temporal resolution"] == "annual"
        ]
        self.dataset_ndvi.addItems(ndvi_datasets)
        self.dataset_ndvi.setCurrentIndex(1)

        self.start_year_climate = 0
        self.end_year_climate = 9999
        self.start_year_ndvi = 0
        self.end_year_ndvi = 9999

        self.dataset_ndvi_changed()
        self.traj_climate_changed()
        self.traj_indic.currentIndexChanged.connect(self.traj_indic_changed)

        self.dataset_climate_update()

        self.dataset_ndvi.currentIndexChanged.connect(self.dataset_ndvi_changed)
        self.traj_climate.currentIndexChanged.connect(self.traj_climate_changed)

        submit_btn = self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok)
        submit_btn.setText(self.tr("Submit request"))
        self.buttonBox.accepted.connect(self.btn_calculate)
        self.buttonBox.rejected.connect(self.hide)

        self._sync_action = None

        self.area_widget = AreaWidget()
        self.area_widget.hide_on_choose_point = False
        self.area_widget.set_section_visibility(
            AreaWidgetSection.FILE | AreaWidgetSection.NAME
        )
        self.vl_aoi.addWidget(self.area_widget)

        self.task_name.setText(self.get_plot_title())

    def traj_indic_changed(self):
        self.dataset_climate_update()
        self.task_name.setText(self.get_plot_title())

    def dataset_climate_update(self):
        self.traj_climate.clear()
        self.climate_datasets = {}
        # Can't use any of the methods but NDVI Trends on the 16 day data, so
        # don't need climate datasets
        if (
            self.datasets["NDVI"][self.dataset_ndvi.currentText()][
                "Temporal resolution"
            ]
            == "annual"
        ):
            trajectory_functions = KNOWN_SCRIPTS[
                "productivity"
            ].additional_configuration["trajectory functions"]
            current_trajectory_function = trajectory_functions[
                self.traj_indic.currentText()
            ]
            climate_types = current_trajectory_function["climate types"]
            for climate_type in climate_types:
                self.climate_datasets.update(self.datasets[climate_type])
                self.traj_climate.addItems(list(self.datasets[climate_type].keys()))

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
        self.task_name.setText(self.get_plot_title())

    def dataset_ndvi_changed(self):
        this_ndvi_dataset = self.datasets["NDVI"][self.dataset_ndvi.currentText()]
        self.start_year_ndvi = this_ndvi_dataset["Start year"]
        self.end_year_ndvi = this_ndvi_dataset["End year"]

        # Don't try to update the climate datasets while traj_indic is empty,
        # so block signals while clearing it.
        self.traj_indic.blockSignals(True)
        self.traj_indic.clear()
        self.traj_indic.blockSignals(False)
        # Can't use any of the methods but NDVI Trends on the 16 day data
        if this_ndvi_dataset["Temporal resolution"] == "16 day":
            self.traj_indic.addItems(["NDVI trends"])
        else:
            self.traj_indic.addItems(
                list(
                    KNOWN_SCRIPTS["productivity"]
                    .additional_configuration["trajectory functions"]
                    .keys()
                )
            )

        self.update_time_bounds()
        self.task_name.setText(self.get_plot_title())

    def update_time_bounds(self):
        # TODO: need to also account for GAEZ and/or CCI data dates for
        # stratification

        # Trajectory - needs to also account for climate data
        start_year_traj = QDate(
            max(self.start_year_ndvi, self.start_year_climate), 1, 1
        )
        end_year_traj = QDate(min(self.end_year_ndvi, self.end_year_climate), 12, 31)

        self.traj_year_start.setMinimumDate(start_year_traj)
        self.traj_year_start.setMaximumDate(end_year_traj)
        self.traj_year_end.setMinimumDate(start_year_traj)
        self.traj_year_end.setMaximumDate(end_year_traj)

    def btn_cancel(self):
        self.close()

    def reset_widgets(self):
        # Set default options
        if self.dataset_ndvi.count() > 0:
            self.dataset_ndvi.setCurrentIndex(1)

        self.area_widget.load_settings()

        if self.traj_indic.count() > 0:
            self.traj_indic.setCurrentIndex(0)

        self.task_name.clear()

    def hideEvent(self, event):
        # Uncheck sync action if defined.
        if self._sync_action and self._sync_action.isChecked():
            self._sync_action.setChecked(False)

        super().hideEvent(event)

    def closeEvent(self, event):
        # Uncheck sync action if defined.
        if self._sync_action and self._sync_action.isChecked():
            self._sync_action.setChecked(False)

        super().closeEvent(event)

    def showEvent(self, event):
        # Check sync action if defined.
        if self._sync_action and not self._sync_action.isChecked():
            self._sync_action.setChecked(True)

        super().showEvent(event)

    @property
    def sync_action(self) -> QtWidgets.QAction:
        """
        Returns the action that is used to sync the show/hide events.
        """
        return self._sync_action

    @sync_action.setter
    def sync_action(self, action: QtWidgets.QAction):
        """
        Set the action to sync the dialog's show/hide events.
        """
        if self._sync_action:
            return

        self._sync_action = action
        self._sync_action.toggled.connect(self._on_sync_action_toggled)

    def _on_sync_action_toggled(self, status):
        # Slot that shows/hides dialog.
        if status:
            if not self.isVisible():
                self.show()
            self.raise_()
            self.activateWindow()
        else:
            self.hide()

    def get_plot_title(self):
        if self.traj_climate.currentText() != "":
            return (
                f"{self.traj_indic.currentText()} "
                f" - {self.dataset_ndvi.currentText()}, "
                f"{self.traj_climate.currentText()}"
            )
        else:
            return (
                f"{self.traj_indic.currentText()} "
                f"- {self.dataset_ndvi.currentText()}"
            )

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        self.area_widget.save_settings()
        ret = super().btn_calculate()
        if not ret:
            return

        self.close()

        # Limit area that can be processed
        aoi_area = self.aoi.get_area() / (1000 * 1000)
        if aoi_area > 1e6:
            log("AOI area is: {:n} - blocking processing".format(aoi_area))
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "The bounding box of the requested area (approximately "
                    "{:.6n} sq km) is too large. The timeseries tool can "
                    "process a maximum area of 1 million sq km at a time. "
                    "Choose a smaller area to process.".format(aoi_area)
                ),
            )
            return False

        if self.traj_climate.currentText() != "":
            climate_gee_dataset = self.climate_datasets[
                self.traj_climate.currentText()
            ]["GEE Dataset"]
        else:
            climate_gee_dataset = None

        ndvi_dataset = self.datasets["NDVI"][self.dataset_ndvi.currentText()][
            "GEE Dataset"
        ]

        crosses_180th, geojsons = self.gee_bounding_box
        payload = {
            "year_initial": self.traj_year_start.date().year(),
            "year_final": self.traj_year_end.date().year(),
            "crosses_180th": crosses_180th,
            "geojsons": json.dumps(geojsons),
            "crs": self.aoi.get_crs_dst_wkt(),
            "ndvi_gee_dataset": ndvi_dataset,
            "task_name": self.task_name.text(),
            "task_notes": self.options_tab.task_notes.toPlainText(),
            "climate_gee_dataset": climate_gee_dataset,
        }

        # This will add in the method parameter
        payload.update(
            KNOWN_SCRIPTS["productivity"].additional_configuration[
                "trajectory functions"
            ][self.traj_indic.currentText()]["params"]
        )

        resp = job_manager.submit_remote_job(payload, self.script.id)

        self.reset_widgets()

        if resp:
            self.mb.pushMessage(
                self.tr("Submitted"),
                self.tr(
                    "Time series calculation task submitted to Trends.Earth server."
                ),
                level=0,
                duration=5,
            )
        else:
            self.mb.pushMessage(
                self.tr("Error"),
                self.tr(
                    "Unable to submit time series calculation task to Trends.Earth "
                    "server"
                ),
                level=1,
                duration=5,
            )
