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

# pylint: disable=import-error
import typing
from pathlib import Path

import qgis.gui
from qgis.PyQt import QtCore, QtWidgets, uic
from te_schemas.algorithms import AlgorithmRunMode, ExecutionScript

from . import conf
from .calculate import DlgCalculateBase
from .jobs.manager import job_manager
from .localexecution import unccd
from .logger import log
from .tasks import create_task

DlgCalculateUNCCDUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateUNCCD.ui")
)
DlgCalculateUNCCDReportUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateUNCCDReport.ui")
)


class DlgCalculateUNCCD(DlgCalculateBase, DlgCalculateUNCCDUi):
    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        script: ExecutionScript,
        parent: QtWidgets.QWidget = None,
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)

        self.population_dataset_name = "Gridded Population Count"
        self.population_dataset = conf.REMOTE_DATASETS["WorldPop"][
            self.population_dataset_name
        ]

        self.spi_dataset_name = "GPCC V6 (Global Precipitation Climatology Centre)"
        self.spi_dataset = conf.REMOTE_DATASETS["SPI"][self.spi_dataset_name]

        self.update_time_bounds()

        self._finish_initialization()

    def update_time_bounds(self):
        start_year_pop = self.population_dataset["Start year"]
        end_year_pop = self.population_dataset["End year"]
        start_year_spi = self.spi_dataset["Start year"]
        end_year_spi = self.spi_dataset["End year"]

        start_year = QtCore.QDate(max(start_year_pop, start_year_spi), 1, 1)
        end_year = QtCore.QDate(min(end_year_pop, end_year_spi), 1, 1)

        self.year_initial_baseline.setMinimumDate(start_year)
        self.year_initial_baseline.setMaximumDate(end_year)
        self.year_final_baseline.setMinimumDate(start_year)
        self.year_final_baseline.setMaximumDate(end_year)

        self.year_initial_progress.setMinimumDate(start_year)
        self.year_initial_progress.setMaximumDate(end_year)
        self.year_final_progress.setMinimumDate(start_year)
        self.year_final_progress.setMaximumDate(end_year)

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.

        QtWidgets.QMessageBox.information(
            None, self.tr("Coming soon!"), self.tr("This function coming soon!")
        )
        self.close()
        return

        ret = super().btn_calculate()

        if not ret:
            return

        crosses_180th, geojsons = self.gee_bounding_box

        year_initial = self.year_initial_de.date().year()
        year_final = self.year_final_de.date().year()

        if (year_final - year_initial) < 5:
            QtWidgets.QMessageBox.warning(
                None,
                self.tr("Error"),
                self.tr(
                    "Initial and final year are less 5 years "
                    "apart in - results will be more reliable "
                    "if more data (years) are included in the analysis."
                ),
            )

            return

        payload = {}
        payload["population"] = {
            "asset": self.population_dataset["GEE Dataset"],
            "source": self.population_dataset_name,
        }

        payload["spi"] = {
            "asset": self.spi_dataset["GEE Dataset"],
            "source": self.spi_dataset_name,
            "lag": int(self.lag_cb.currentText()),
        }

        payload.update(
            {
                "geojsons": geojsons,
                "crs": self.aoi.get_crs_dst_wkt(),
                "crosses_180th": crosses_180th,
                "task_name": self.execution_name_le.text(),
                "task_notes": self.task_notes.toPlainText(),
                "script": ExecutionScript.Schema().dump(self.script),
                "year_initial": year_initial,
                "year_final": year_final,
            }
        )

        self.close()

        resp = create_task(
            job_manager,
            payload,
            self.script.id,
            AlgorithmRunMode.REMOTE,
        )

        if resp:
            main_msg = "Submitted"
            description = "UNCCD default data task submitted to Trends.Earth server."
        else:
            main_msg = "Error"
            description = "Unable to UNCCD default data task to Trends.Earth server."
        self.mb.pushMessage(
            self.tr(main_msg), self.tr(description), level=0, duration=5
        )


class DlgCalculateUNCCDReport(DlgCalculateBase, DlgCalculateUNCCDReportUi):
    LOCAL_SCRIPT_NAME: str = "unccd-report"

    button_calculate: QtWidgets.QPushButton
    combo_boxes: typing.Dict[str, unccd.UNCCDReportWidgets] = {}

    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        script: ExecutionScript,
        parent: QtWidgets.QWidget = None,
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)

        self._finish_initialization()

        self.combo_boxes = unccd.UNCCDReportWidgets(
            combo_dataset_so1_so2=self.combo_dataset_so1_so2,
            combo_dataset_error_recode=self.combo_dataset_error_recode,
            combo_dataset_so3=self.combo_dataset_so3,
        )

        self.changed_region.connect(self.combo_boxes.populate)

    def showEvent(self, event):
        super().showEvent(event)
        self.combo_boxes.populate()

    def _validate_dataset_selection(self, combo_box, dataset_name):
        if len(combo_box.dataset_list) == 0:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    f"You must select a {dataset_name} layer "
                    "before you can use the UNCCD reporting tool."
                ),
            )
            return False
        else:
            return True

    def _validate_layer_selection(self, combo_box, layer_name):
        if len(combo_box.layer_list) == 0:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    f"You must select a {layer_name} layer "
                    "before you can use the UNCCD reporting tool."
                ),
            )
            return False
        else:
            return True

    def validate_data_selections(self, combo_boxes):
        """validate all needed datasets are selected"""
        if self.groupbox_so1_so2.isChecked() and not self._validate_dataset_selection(
            combo_boxes.combo_dataset_so1_so2, self.tr("SO1 and SO2")
        ):
            return False
        elif self.groupbox_so3.isChecked() and not self._validate_dataset_selection(
            combo_boxes.combo_dataset_so3, self.tr("SO3 (hazard and exposure)")
        ):
            return False
        else:
            return True

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super().btn_calculate()

        if not ret:
            return

        if not self.validate_data_selections(self.combo_boxes):
            log("failed dataset validation")

            return

        params = {
            "task_name": self.options_tab.task_name.text(),
            "task_notes": self.options_tab.task_notes.toPlainText(),
            "include_so1_so2": self.groupbox_so1_so2.isChecked(),
            "include_so3": self.groupbox_so3.isChecked(),
            "include_error_recode": self.error_recode_gb.isChecked(),
            "affected_only": self.checkBox_affected_areas_only.isChecked(),
        }
        params.update(
            unccd.get_main_unccd_report_job_params(
                task_name=self.options_tab.task_name.text(),
                combo_dataset_so1_so2=self.combo_boxes.combo_dataset_so1_so2,
                combo_dataset_so3=self.combo_boxes.combo_dataset_so3,
                combo_dataset_error_recode=self.combo_boxes.combo_dataset_error_recode,
                include_so1_so2=self.groupbox_so1_so2.isChecked(),
                include_so3=self.groupbox_so3.isChecked(),
                include_error_recode=self.error_recode_gb.isChecked(),
                task_notes=self.options_tab.task_notes.toPlainText(),
            )
        )

        self.close()

        job_manager.submit_local_job_as_qgstask(
            params, script_name=self.LOCAL_SCRIPT_NAME, area_of_interest=None
        )
