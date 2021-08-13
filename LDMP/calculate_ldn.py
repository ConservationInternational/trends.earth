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
from .localexecution import ldn
from .logger import log

DlgCalculateOneStepUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateOneStep.ui"))
DlgCalculateLdnSummaryTableAdminUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateLDNSummaryTableAdmin.ui"))


class tr_calculate_ldn(object):
    def tr(self, message):
        return QtCore.QCoreApplication.translate("tr_calculate_ldn", message)


class DlgCalculateOneStep(DlgCalculateBase, DlgCalculateOneStepUi):

    def __init__(
            self,
            iface: qgis.gui.QgisInterface,
            script: models.ExecutionScript,
            parent: QtWidgets.QWidget = None
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)
        self.update_time_bounds()
        self.radio_te_prod.toggled.connect(self.update_time_bounds)
        self.lc_setup_widget = lc_setup.LandCoverSetupRemoteExecutionWidget(
            self,
            hide_min_year=True,
            hide_max_year=True
        )

        self.lc_define_deg_widget = lc_setup.LCDefineDegradationWidget()

        self.checkBox_progress_period.toggled.connect(self.toggle_progress_period)
        self.toggle_progress_period()

        self._finish_initialization()

    def update_time_bounds(self):
        if self.radio_te_prod.isChecked():
            prod_dataset = conf.REMOTE_DATASETS["NDVI"]["MODIS (MOD13Q1, annual)"]
            start_year_prod = prod_dataset['Start year']
            end_year_prod = prod_dataset['End year']
        else:
            start_year_prod = 2000
            end_year_prod = 2015

        lc_dataset = conf.REMOTE_DATASETS["Land cover"]["ESA CCI"]
        start_year_lc = lc_dataset['Start year']
        end_year_lc = lc_dataset['End year']

        start_year = QtCore.QDate(max(start_year_prod, start_year_lc), 1, 1)
        end_year = QtCore.QDate(min(end_year_prod, end_year_lc), 1, 1)

        self.year_initial_baseline.setMinimumDate(start_year)
        self.year_initial_baseline.setMaximumDate(end_year)
        self.year_final_baseline.setMinimumDate(start_year)
        self.year_final_baseline.setMaximumDate(end_year)

        self.year_initial_progress.setMinimumDate(start_year)
        self.year_initial_progress.setMaximumDate(end_year)
        self.year_final_progress.setMinimumDate(start_year)
        self.year_final_progress.setMaximumDate(end_year)

    def showEvent(self, event):
        super(DlgCalculateOneStep, self).showEvent(event)

        if self.land_cover_content.layout() is None:
            layout = QtWidgets.QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(1)
            layout.addWidget(self.lc_setup_widget)
            self.land_cover_content.setLayout(layout)

        if self.effects_content.layout() is None:
            layout = QtWidgets.QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(1)
            layout.addWidget(self.lc_define_deg_widget)
            self.effects_content.setLayout(layout)

    def toggle_progress_period(self):
        if self.checkBox_progress_period.isChecked():
            self.groupBox_progress_period.setVisible(True)
        else:
            self.groupBox_progress_period.setVisible(False)

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateOneStep, self).btn_calculate()

        if not ret:
            return

        if self.radio_te_prod.isChecked():
            prod_mode = 'Trends.Earth productivity'
        else:
            prod_mode = 'JRC LPD'

        periods = {'baseline': {
            'period_year_start': self.year_initial_baseline.date().year(),
            'period_year_final': self.year_final_baseline.date().year(),
            }
        }

        if self.checkBox_progress_period.isChecked():
            periods.update({
                'progress': {
                    'period_year_start': self.year_initial_progress.date().year(),
                    'period_year_final': self.year_final_progress.date().year(),
                }
            })

        crosses_180th, geojsons = self.gee_bounding_box

        payloads = []
        for period, values in periods.items():
            payload = {}
            year_start = values['period_year_start']
            year_final = values['period_year_final']

            if (year_final - year_start) < 10:
                QtWidgets.QMessageBox.warning(
                    None,
                    self.tr("Error"),
                    self.tr(
                        "Initial and final year are less 10 years "
                        "apart in {} period - results will be more "
                        "reliable if more data (years) are included "
                        "in the analysis.".format(period)
                    )
                )

                return

            # Have productivity state consider the last 3 years for the current
            # period, and the years preceding those last 3 for the baseline
            prod_state_year_bl_start = year_start
            prod_state_year_bl_end = year_final - 3
            prod_state_year_tg_start = prod_state_year_bl_end + 1
            prod_state_year_tg_end = prod_state_year_bl_end + 3
            assert prod_state_year_tg_end == year_final

            if prod_mode == 'Trends.Earth productivity':
                prod_asset = conf.REMOTE_DATASETS["NDVI"]["MODIS (MOD13Q1, annual)"]["GEE Dataset"]
            elif prod_mode == 'JRC LPD':
                if period == 'baseline':
                    prod_asset = conf.REMOTE_DATASETS["Land productivity"]["Land Productivity Dynamics (LPD)"]["GEE Dataset"]
                else:
                    prod_asset = conf.REMOTE_DATASETS["Land productivity"]["Land Productivity Dynamics (LPD), 2021 update"]["GEE Dataset"]

            payload['productivity'] = {
                'mode': prod_mode,
                'prod_asset': prod_asset,
                'traj_method': 'ndvi_trend',
                'traj_year_initial': year_start,
                'traj_year_final': year_final,
                'perf_year_initial': year_start,
                'perf_year_final': year_final,
                'state_year_bl_start': prod_state_year_bl_start,
                'state_year_bl_end': prod_state_year_bl_end,
                'state_year_tg_start': prod_state_year_tg_start,
                'state_year_tg_end': prod_state_year_tg_end,
                'climate_asset': None,
            }
            payload['land_cover'] = {
                'year_initial': year_start,
                'year_final': year_final,
                'legend_nesting': LCLegendNesting.Schema().dump(
                    self.lc_setup_widget.aggregation_dialog.nesting
                ),
                'trans_matrix': LCTransitionDefinitionDeg.Schema().dump(
                    self.lc_define_deg_widget.trans_matrix
                ),
            }
            payload['soil_organic_carbon'] = {
                'year_initial': year_start,
                'year_final': year_final,
                'fl': .80,
                'legend_nesting': LCLegendNesting.Schema().dump(
                    self.lc_setup_widget.aggregation_dialog.nesting
                ), # TODO: Use SOC matrix for the above once defined
                'trans_matrix': LCTransitionDefinitionDeg.Schema().dump(
                    self.lc_define_deg_widget.trans_matrix
                ), # TODO: Use SOC matrix for the above once defined
            }

            task_name = self.execution_name_le.text()
            if period == 'progress':
                task_name = f'{task_name} - progress'

            payload.update({
                'geojsons': geojsons,
                'crs': self.aoi.get_crs_dst_wkt(),
                'crosses_180th': crosses_180th,
                'task_name': task_name,
                'task_notes': self.task_notes.toPlainText(),
                'period': period
            })

            payloads.append(payload)

        self.close()

        for payload in payloads:
            resp = job_manager.submit_remote_job(payload, self.script.id)

            if resp:
                main_msg = "Submitted"
                description = "SDG sub-indicator task submitted to Google Earth Engine."
            else:
                main_msg = "Error"
                description = "Unable to submit SDG sub-indicator task to Google Earth Engine."
            self.mb.pushMessage(
                self.tr(main_msg),
                self.tr(description),
                level=0,
                duration=5
            )

class DlgCalculateLDNSummaryTableAdmin(
    DlgCalculateBase,
    DlgCalculateLdnSummaryTableAdminUi
):
    LOCAL_SCRIPT_NAME: str = "final-sdg-15-3-1"

    button_calculate: QtWidgets.QPushButton
    combo_boxes: typing.Dict[str, ldn.SummaryTableWidgets] = {}

    def __init__(
            self,
            iface: qgis.gui.QgisInterface,
            script: models.ExecutionScript,
            parent: QtWidgets.QWidget = None
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)

        self.checkBox_progress_period.toggled.connect(self.toggle_progress_period)

        self._finish_initialization()

        self.combo_boxes['baseline'] = ldn.SummaryTableWidgets(
            combo_datasets=self.combo_datasets_baseline,
            combo_layer_traj=self.combo_layer_traj_baseline,
            combo_layer_perf=self.combo_layer_perf_baseline,
            combo_layer_state=self.combo_layer_state_baseline,
            combo_layer_lpd=self.combo_layer_lpd_baseline,
            combo_layer_lc=self.combo_layer_lc_baseline,
            combo_layer_soc=self.combo_layer_soc_baseline,
            radio_te_prod=self.radio_te_prod_baseline,
            radio_lpd_jrc=self.radio_lpd_jrc_baseline
        )
        self.combo_boxes['progress'] = ldn.SummaryTableWidgets(
            combo_datasets=self.combo_datasets_progress,
            combo_layer_traj=self.combo_layer_traj_progress,
            combo_layer_perf=self.combo_layer_perf_progress,
            combo_layer_state=self.combo_layer_state_progress,
            combo_layer_lpd=self.combo_layer_lpd_progress,
            combo_layer_lc=self.combo_layer_lc_progress,
            combo_layer_soc=self.combo_layer_soc_progress,
            radio_te_prod=self.radio_te_prod_progress,
            radio_lpd_jrc=self.radio_lpd_jrc_progress
        )

    def showEvent(self, event):
        super().showEvent(event)
        self.combo_boxes['baseline'].populate()
        self.combo_boxes['progress'].populate()
        self.toggle_progress_period()

    def toggle_progress_period(self):
        if self.checkBox_progress_period.isChecked():
            self.groupBox_progress_period.setVisible(True)
            self.advanced_configuration_progress.setVisible(True)
        else:
            self.groupBox_progress_period.setVisible(False)
            self.advanced_configuration_progress.setVisible(False)

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super().btn_calculate()

        if not ret:
            return

        if self.radio_te_prod.isChecked():
            prod_mode = 'Trends.Earth productivity'
        else:
            prod_mode = 'JRC LPD'

        ######################################################################
        # Check that all needed input layers are selected

        if prod_mode == 'Trends.Earth productivity':
            if len(self.combo_layer_traj.layer_list) == 0:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(
                        "You must add a productivity trajectory indicator layer to "
                        "your map before you can use the SDG calculation tool."
                    )
                )

                return

            if len(self.combo_layer_state.layer_list) == 0:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(
                        "You must add a productivity state indicator layer to your "
                        "map before you can use the SDG calculation tool."
                    )
                )

                return

            if len(self.combo_layer_perf.layer_list) == 0:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(
                        "You must add a productivity performance indicator layer to "
                        "your map before you can use the SDG calculation tool."
                    )
                )

                return

        else:
            if len(self.combo_layer_lpd.layer_list) == 0:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(
                        "You must add a land productivity dynamics indicator layer to "
                        "your map before you can use the SDG calculation tool."
                    )
                )

                return

        if len(self.combo_layer_lc.layer_list) == 0:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "You must add a land cover indicator layer to your map before you "
                    "can use the SDG calculation tool."
                )
            )

            return

        if len(self.combo_layer_soc.layer_list) == 0:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "You must add a soil organic carbon indicator layer to your map "
                    "before you can use the SDG calculation tool."
                )
            )

            return

        #######################################################################
        # Check that the layers cover the full extent needed

        if prod_mode == 'Trends.Earth productivity':
            trajectory_layer_extent = self.combo_layer_traj.get_layer().extent()
            extent_geom = QgsGeometry.fromRect(trajectory_layer_extent)
            overlaps_by = self.aoi.calc_frac_overlap(extent_geom)

            if overlaps_by < 0.99:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(
                        "Area of interest is not entirely within the trajectory layer."
                    )
                )

                return

            if self.aoi.calc_frac_overlap(QgsGeometry.fromRect(self.combo_layer_perf.get_layer().extent())) < .99:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(
                        "Area of interest is not entirely within the "
                        "performance layer."
                    )
                )

                return

            if self.aoi.calc_frac_overlap(QgsGeometry.fromRect(self.combo_layer_state.get_layer().extent())) < .99:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr("Area of interest is not entirely within the state layer.")
                )

                return
        else:
            if self.aoi.calc_frac_overlap(QgsGeometry.fromRect(self.combo_layer_lpd.get_layer().extent())) < .99:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(
                        "Area of interest is not entirely within the land "
                        "productivity dynamics layer."
                    )
                )

                return

        if self.aoi.calc_frac_overlap(QgsGeometry.fromRect(self.combo_layer_lc.get_layer().extent())) < .99:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Area of interest is not entirely within the land cover layer.")
            )

            return

        if self.aoi.calc_frac_overlap(QgsGeometry.fromRect(self.combo_layer_soc.get_layer().extent())) < .99:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Area of interest is not entirely within the soil organic "
                    "carbon layer."
                )
            )

            return

        #######################################################################
        # Check that all of the productivity layers have the same resolution
        # and CRS
        def res(layer):
            return (
                round(layer.rasterUnitsPerPixelX(), 10),
                round(layer.rasterUnitsPerPixelY(), 10)
            )

        if prod_mode == 'Trends.Earth productivity':
            if res(self.combo_layer_traj.get_layer()) != res(self.combo_layer_state.get_layer()):
                QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Resolutions of trajectory layer and state layer do not match."))

                return

            if res(self.combo_layer_traj.get_layer()) != res(self.combo_layer_perf.get_layer()):
                QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Resolutions of trajectory layer and performance layer do not match."))

                return

            if self.combo_layer_traj.get_layer().crs() != self.combo_layer_state.get_layer().crs():
                QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Coordinate systems of trajectory layer and state layer do not match."))

                return

            if self.combo_layer_traj.get_layer().crs() != self.combo_layer_perf.get_layer().crs():
                QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Coordinate systems of trajectory layer and performance layer do not match."))

                return

        self.close()

        params = ldn.get_main_sdg_15_3_1_job_params(
            task_name=self.options_tab.task_name.text(),
            aoi=self.aoi,
            prod_mode=prod_mode,
            combo_layer_lc=self.combo_layer_lc,
            combo_layer_soc=self.combo_layer_soc,
            combo_layer_traj=self.combo_layer_traj,
            combo_layer_perf=self.combo_layer_perf,
            combo_layer_state=self.combo_layer_state,
            combo_layer_lpd=self.combo_layer_lpd,
            task_notes=self.options_tab.task_notes.toPlainText()
        )
        job_manager.submit_local_job(
            params, script_name=self.LOCAL_SCRIPT_NAME, area_of_interest=self.aoi)
