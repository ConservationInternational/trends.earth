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

from pathlib import Path
import datetime
import typing

from PyQt5 import (
    QtCore,
    QtWidgets,
    uic,
)

import qgis.gui
from qgis.core import QgsGeometry

from te_schemas.land_cover import LCTransitionDefinitionDeg, LCLegendNesting

from . import (
    conf,
    data_io,
    lc_setup,
)
from .algorithms import models
from .calculate import (
    DlgCalculateBase,
)
from .jobs.manager import job_manager
from .localexecution import unccd
from .logger import log

DlgCalculateUNCCDUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateUNCCD.ui"))
DlgCalculateUNCCDReportUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateUNCCDReport.ui"))


class tr_calculate_unccd(object):
    def tr(self, message):
        return QtCore.QCoreApplication.translate("tr_calculate_unccd", message)


class DlgCalculateUNCCD(DlgCalculateBase, DlgCalculateUNCCDUi):

    def __init__(
            self,
            iface: qgis.gui.QgisInterface,
            script: models.ExecutionScript,
            parent: QtWidgets.QWidget = None
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)

        # TODO: add an option of different population and SPI datasets...
        self.population_dataset_name = "Gridded Population Count"
        self.population_dataset = conf.REMOTE_DATASETS["WorldPop"][self.population_dataset_name]

        self.spi_dataset_name = "GPCC V6 (Global Precipitation Climatology Centre)"
        self.spi_dataset = conf.REMOTE_DATASETS["SPI"][self.spi_dataset_name]

        self.precip_chirps_radio.toggled.connect(self.update_time_bounds)
        self.update_time_bounds()
        self.populate_spi_lags()

        self._finish_initialization()

    def populate_spi_lags(self):
        self.lag_cb.addItems([str(lag) for lag in self.spi_dataset['Lags']])

    def update_time_bounds(self):
        start_year_pop = self.population_dataset['Start year']
        end_year_pop = self.population_dataset['End year']
        start_year_spi = self.spi_dataset['Start year']
        end_year_spi = self.spi_dataset['End year']

        start_year = QtCore.QDate(max(start_year_pop, start_year_spi), 1, 1)
        end_year = QtCore.QDate(min(end_year_pop, end_year_spi), 1, 1)

        self.year_initial_de.setMinimumDate(start_year)
        self.year_initial_de.setMaximumDate(end_year)
        self.year_final_de.setMinimumDate(start_year)
        self.year_final_de.setMaximumDate(end_year)

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateUNCCD, self).btn_calculate()

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
                )
            )

            return

        payload = {}
        payload['population'] = {
            'asset': self.population_dataset['GEE Dataset'],
            'source': self.population_dataset_name
        }

        payload['spi'] = {
            'asset': self.spi_dataset['GEE Dataset'],
            'source': self.spi_dataset_name,
            'lag': int(self.lag_cb.currentText())
        }

        payload.update({
            'geojsons': geojsons,
            'crs': self.aoi.get_crs_dst_wkt(),
            'crosses_180th': crosses_180th,
            'task_name': self.execution_name_le.text(),
            'task_notes': self.task_notes.toPlainText(),
            'script': models.ExecutionScript.Schema().dump(self.script),
            'year_initial': year_initial,
            'year_final': year_final
        })

        self.close()

        resp = job_manager.submit_remote_job(payload, self.script.id)

        if resp:
            main_msg = "Submitted"
            description = "UNCCD default data task submitted to Google Earth Engine."
        else:
            main_msg = "Error"
            description = "Unable to UNCCD default data task to Google Earth Engine."
        self.mb.pushMessage(
            self.tr(main_msg),
            self.tr(description),
            level=0,
            duration=5
        )


class DlgCalculateUNCCDReport(
    DlgCalculateBase,
    DlgCalculateUNCCDReportUi
):
    LOCAL_SCRIPT_NAME: str = "unccd-report"

    button_calculate: QtWidgets.QPushButton
    combo_boxes: typing.Dict[str, unccd.UNCCDReportWidgets] = {}

    def __init__(
            self,
            iface: qgis.gui.QgisInterface,
            script: models.ExecutionScript,
            parent: QtWidgets.QWidget = None
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)

        self._finish_initialization()

        self.region_widget.setVisible(False)

        self.combo_boxes = unccd.UNCCDReportWidgets(
            combo_dataset_so1_so2=self.combo_dataset_so1_so2,
            combo_dataset_so3=self.combo_dataset_so3,
            combo_layer_jrc_vulnerability=self.combo_layer_jrc_vulnerability
        )

    def showEvent(self, event):
        super().showEvent(event)
        self.combo_boxes.populate()

    def validate_dataset_selections(self, combo_boxes):
        '''validate all needed datasets are selected'''
        if combo_boxes.combo_dataset_so1_so2.currentText == '':
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "You must choose a dataset for SO1 and SO2 before using "
                    "the UNCCD report generation tool."
                )
            )

            return False

        if combo_boxes.combo_dataset_so3.currentText == '':
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "You must choose a dataset for SO3 before using "
                    "the UNCCD report generation tool."
                )
            )

            return False

        return True

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super().btn_calculate()

        if not ret:
            return

        if (
            not self.validate_dataset_selections(self.combo_boxes)
        ):
            log('failed dataset validation')
            return

        params = {
            'task_name': self.options_tab.task_name.text(),
            'task_notes': self.options_tab.task_notes.toPlainText()
        }
        params.update(
            unccd.get_main_unccd_report_job_params(
                task_name=self.options_tab.task_name.text(),
                combo_dataset_so1_so2=self.combo_boxes.combo_dataset_so1_so2,
                combo_dataset_so3=self.combo_boxes.combo_dataset_so3,
                combo_layer_jrc_vulnerability=self.combo_boxes.combo_layer_jrc_vulnerability,
                task_notes=self.options_tab.task_notes.toPlainText()
            )
        )

        job_manager.submit_local_job(
            params,
            script_name=self.LOCAL_SCRIPT_NAME,
            area_of_interest=None
        )

        self.close()
