﻿"""
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
from qgis.core import QgsGeometry
from qgis.PyQt import QtCore
from qgis.PyQt import QtWidgets
from qgis.PyQt import uic
from te_schemas.algorithms import ExecutionScript
from te_schemas.land_cover import LCLegendNesting
from te_schemas.land_cover import LCTransitionDefinitionDeg
from te_schemas.productivity import ProductivityMode

from . import conf
from . import data_io
from . import lc_setup
from .calculate import DlgCalculateBase
from .jobs.manager import job_manager
from .localexecution import ldn
from .logger import log

DlgCalculateOneStepUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateOneStep.ui")
)
DlgCalculateLdnSummaryTableAdminUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateLDNSummaryTableAdmin.ui")
)


class tr_calculate_ldn(object):
    def tr(self, message):
        return QtCore.QCoreApplication.translate("tr_calculate_ldn", message)


class DlgCalculateOneStep(DlgCalculateBase, DlgCalculateOneStepUi):
    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        script: ExecutionScript,
        parent: QtWidgets.QWidget = None
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)

        jrc_lpd_datasets = []

        for ds_name, ds_details in conf.REMOTE_DATASETS[
            "Land Productivity Dynamics (JRC)"].items():
            jrc_lpd_datasets.append(ds_name)
        self.cb_jrc_baseline.addItems(jrc_lpd_datasets)
        self.cb_jrc_baseline.setCurrentIndex(1)
        self.cb_jrc_progress.addItems(jrc_lpd_datasets)
        self.cb_jrc_progress.setCurrentIndex(2)

        self.year_final_baseline.dateChanged.connect(self.update_progress_year)
        self.update_progress_year()
        self.year_initial_progress.setReadOnly(True)

        self.update_time_bounds_baseline()
        self.update_time_bounds_progress()
        self.toggle_lpd_options()

        self.cb_jrc_baseline.currentIndexChanged.connect(
            self.update_time_bounds_baseline
        )
        self.cb_jrc_progress.currentIndexChanged.connect(
            self.update_time_bounds_progress
        )

        self.radio_te_prod.toggled.connect(self.toggle_lpd_options)

        self.lc_setup_widget = lc_setup.LandCoverSetupRemoteExecutionWidget(
            self, hide_min_year=True, hide_max_year=True
        )

        self.lc_define_deg_widget = lc_setup.LCDefineDegradationWidget()

        self.checkBox_progress_period.toggled.connect(
            self.toggle_progress_period
        )
        self.toggle_progress_period()

        self._finish_initialization()

    def toggle_lpd_options(self):
        self.update_time_bounds_baseline()
        self.update_time_bounds_progress()

        if self.radio_lpd_jrc.isChecked():
            self.label_lpd_warning.show()
            self.jrc_frame_baseline.show()
            self.jrc_frame_progress.show()
        else:
            self.jrc_frame_baseline.hide()
            self.jrc_frame_progress.hide()
            self.label_lpd_warning.hide()

    def update_progress_year(self):
        self.year_initial_progress.setDate(self.year_final_baseline.date())

    def update_time_bounds_baseline(self):
        if self.radio_te_prod.isChecked():
            prod_dataset = conf.REMOTE_DATASETS["NDVI"][
                "MODIS (MOD13Q1, annual)"]
            start_year_prod = prod_dataset['Start year']
            end_year_prod = prod_dataset['End year']
        else:
            prod_dataset = conf.REMOTE_DATASETS[
                "Land Productivity Dynamics (JRC)"][
                    self.cb_jrc_baseline.currentText()]
            start_year_prod = prod_dataset['Start year']
            end_year_prod = prod_dataset['End year']

        lc_dataset = conf.REMOTE_DATASETS["Land cover"]["ESA CCI"]
        start_year_lc = lc_dataset['Start year']
        end_year_lc = lc_dataset['End year']

        start_year = QtCore.QDate(max(start_year_prod, start_year_lc), 1, 1)
        end_year = QtCore.QDate(min(end_year_prod, end_year_lc), 1, 1)

        self.year_initial_baseline.setMinimumDate(start_year)
        self.year_initial_baseline.setMaximumDate(end_year)
        self.year_final_baseline.setMinimumDate(start_year)
        self.year_final_baseline.setMaximumDate(end_year)

    def update_time_bounds_progress(self):
        if self.radio_te_prod.isChecked():
            prod_dataset = conf.REMOTE_DATASETS["NDVI"][
                "MODIS (MOD13Q1, annual)"]
            start_year_prod = prod_dataset['Start year']
            end_year_prod = prod_dataset['End year']
        else:
            prod_dataset = conf.REMOTE_DATASETS[
                "Land Productivity Dynamics (JRC)"][
                    self.cb_jrc_progress.currentText()]
            start_year_prod = prod_dataset['Start year']
            end_year_prod = prod_dataset['End year']

        lc_dataset = conf.REMOTE_DATASETS["Land cover"]["ESA CCI"]
        start_year_lc = lc_dataset['Start year']
        end_year_lc = lc_dataset['End year']

        start_year = QtCore.QDate(max(start_year_prod, start_year_lc), 1, 1)
        end_year = QtCore.QDate(min(end_year_prod, end_year_lc), 1, 1)

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
            prod_mode = ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value
        else:
            prod_mode = ProductivityMode.JRC_5_CLASS_LPD.value

        periods = {
            'baseline': {
                'period_year_initial':
                self.year_initial_baseline.date().year(),
                'period_year_final': self.year_final_baseline.date().year(),
            }
        }

        if self.checkBox_progress_period.isChecked():
            periods.update(
                {
                    'progress': {
                        'period_year_initial':
                        self.year_initial_progress.date().year(),
                        'period_year_final':
                        self.year_final_progress.date().year(),
                    }
                }
            )

        crosses_180th, geojsons = self.gee_bounding_box

        payloads = []

        for period, values in periods.items():
            payload = {}
            year_initial = values['period_year_initial']
            year_final = values['period_year_final']

            payload['productivity'] = {'mode': prod_mode}

            if prod_mode == ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value:
                if (year_final - year_initial) < 10:
                    QtWidgets.QMessageBox.warning(
                        None, self.tr("Warning"),
                        self.tr(
                            "Initial and final year are less 10 years "
                            "apart in {} period - results will be more "
                            "reliable if more data (years) are included "
                            "in the analysis.".format(period)
                        )
                    )

                # Have productivity state consider the last 3 years for the
                # current
                # period, and the years preceding those last 3 for the baseline
                prod_state_year_bl_start = year_initial
                prod_state_year_bl_end = year_final - 3
                prod_state_year_tg_start = prod_state_year_bl_end + 1
                prod_state_year_tg_end = prod_state_year_bl_end + 3
                assert prod_state_year_tg_end == year_final

                payload['productivity'].update(
                    {
                        'asset_productivity':
                        conf.REMOTE_DATASETS["NDVI"]["MODIS (MOD13Q1, annual)"]
                        ["GEE Dataset"],
                        'traj_method':
                        'ndvi_trend',
                        'traj_year_initial':
                        year_initial,
                        'traj_year_final':
                        year_final,
                        'perf_year_initial':
                        year_initial,
                        'perf_year_final':
                        year_final,
                        'state_year_bl_start':
                        prod_state_year_bl_start,
                        'state_year_bl_end':
                        prod_state_year_bl_end,
                        'state_year_tg_start':
                        prod_state_year_tg_start,
                        'state_year_tg_end':
                        prod_state_year_tg_end,
                        'asset_climate':
                        None,
                    }
                )
            elif prod_mode == ProductivityMode.JRC_5_CLASS_LPD.value:
                if period == 'baseline':
                    prod_dataset = conf.REMOTE_DATASETS[
                        "Land Productivity Dynamics (JRC)"][
                            self.cb_jrc_baseline.currentText()]
                else:
                    prod_dataset = conf.REMOTE_DATASETS[
                        "Land Productivity Dynamics (JRC)"][
                            self.cb_jrc_progress.currentText()]
                prod_asset = prod_dataset['GEE Dataset']
                prod_start_year = prod_dataset['Start year']
                prod_end_year = prod_dataset['End year']
                payload['productivity'].update(
                    {
                        'asset': prod_asset,
                        'year_initial': prod_start_year,
                        'year_final': prod_end_year
                    }
                )
            payload['land_cover'] = {
                'year_initial':
                year_initial,
                'year_final':
                year_final,
                'legend_nesting':
                LCLegendNesting.Schema().dump(
                    self.lc_setup_widget.aggregation_dialog.nesting
                ),
                'trans_matrix':
                LCTransitionDefinitionDeg.Schema().dump(
                    self.lc_define_deg_widget.trans_matrix
                ),
            }
            payload['soil_organic_carbon'] = {
                'year_initial':
                year_initial,
                'year_final':
                year_final,
                'fl':
                .80,
                'legend_nesting':
                LCLegendNesting.Schema().dump(
                    self.lc_setup_widget.aggregation_dialog.nesting
                ),  # TODO: Use SOC matrix for the above once defined
                'trans_matrix':
                LCTransitionDefinitionDeg.Schema().dump(
                    self.lc_define_deg_widget.trans_matrix
                ),  # TODO: Use SOC matrix for the above once defined
            }

            payload['population'] = {
                'year': year_final,
                'asset':
                "users/geflanddegradation/toolbox_datasets/worldpop_mf_v1_300m",
                'source': "WorldPop (gender breakdown)"
            }

            task_name = self.execution_name_le.text()

            if len(periods.items()) == 2:
                if task_name:
                    task_name = f'{task_name} - {period}'
                else:
                    task_name = f'{period}'

            payload.update(
                {
                    'geojsons': geojsons,
                    'crs': self.aoi.get_crs_dst_wkt(),
                    'crosses_180th': crosses_180th,
                    'task_name': task_name,
                    'task_notes': self.task_notes.toPlainText(),
                    'script': ExecutionScript.Schema().dump(self.script),
                    'period': {
                        'name': period,
                        'year_initial': year_initial,
                        'year_final': year_final
                    }
                }
            )

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
                self.tr(main_msg), self.tr(description), level=0, duration=5
            )


class DlgCalculateLDNSummaryTableAdmin(
    DlgCalculateBase, DlgCalculateLdnSummaryTableAdminUi
):
    LOCAL_SCRIPT_NAME: str = "sdg-15-3-1-summary"

    button_calculate: QtWidgets.QPushButton
    combo_boxes: typing.Dict[str, ldn.SummaryTableLDWidgets] = {}

    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        script: ExecutionScript,
        parent: QtWidgets.QWidget = None
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)

        self.checkBox_progress_period.toggled.connect(
            self.toggle_progress_period
        )

        self._finish_initialization()

        self.combo_boxes['baseline'] = ldn.SummaryTableLDWidgets(
            combo_datasets=self.combo_datasets_baseline,
            combo_layer_traj=self.combo_layer_traj_baseline,
            combo_layer_traj_label=self.combo_layer_traj_label_baseline,
            combo_layer_perf=self.combo_layer_perf_baseline,
            combo_layer_perf_label=self.combo_layer_perf_label_baseline,
            combo_layer_state=self.combo_layer_state_baseline,
            combo_layer_state_label=self.combo_layer_state_label_baseline,
            combo_layer_lpd=self.combo_layer_lpd_baseline,
            combo_layer_lpd_label=self.combo_layer_lpd_label_baseline,
            combo_layer_lc=self.combo_layer_lc_baseline,
            combo_layer_soc=self.combo_layer_soc_baseline,
            combo_layer_pop_total=self.combo_layer_population_baseline_total,
            combo_layer_pop_male=self.combo_layer_population_baseline_male,
            combo_layer_pop_female=self.combo_layer_population_baseline_female,
            radio_lpd_jrc=self.radio_lpd_jrc
        )
        self.combo_boxes['progress'] = ldn.SummaryTableLDWidgets(
            combo_datasets=self.combo_datasets_progress,
            combo_layer_traj=self.combo_layer_traj_progress,
            combo_layer_traj_label=self.combo_layer_traj_label_progress,
            combo_layer_perf=self.combo_layer_perf_progress,
            combo_layer_perf_label=self.combo_layer_perf_label_progress,
            combo_layer_state=self.combo_layer_state_progress,
            combo_layer_state_label=self.combo_layer_state_label_progress,
            combo_layer_lpd=self.combo_layer_lpd_progress,
            combo_layer_lpd_label=self.combo_layer_lpd_label_progress,
            combo_layer_lc=self.combo_layer_lc_progress,
            combo_layer_soc=self.combo_layer_soc_progress,
            combo_layer_pop_total=self.combo_layer_population_progress_total,
            combo_layer_pop_male=self.combo_layer_population_progress_male,
            combo_layer_pop_female=self.combo_layer_population_progress_female,
            radio_lpd_jrc=self.radio_lpd_jrc
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

    def validate_layer_selections(self, combo_boxes, prod_mode):
        '''validate all needed layers are selected'''

        if prod_mode == 'Trends.Earth productivity':
            if len(combo_boxes.combo_layer_traj.layer_list) == 0:
                QtWidgets.QMessageBox.critical(
                    None, self.tr("Error"),
                    self.tr(
                        "You must add a productivity trajectory indicator layer to "
                        "your map before you can use the SDG calculation tool."
                    )
                )

                return False

            if len(combo_boxes.combo_layer_state.layer_list) == 0:
                QtWidgets.QMessageBox.critical(
                    None, self.tr("Error"),
                    self.tr(
                        "You must add a productivity state indicator layer to your "
                        "map before you can use the SDG calculation tool."
                    )
                )

                return False

            if len(combo_boxes.combo_layer_perf.layer_list) == 0:
                QtWidgets.QMessageBox.critical(
                    None, self.tr("Error"),
                    self.tr(
                        "You must add a productivity performance indicator layer to "
                        "your map before you can use the SDG calculation tool."
                    )
                )

                return False

        else:
            if len(combo_boxes.combo_layer_lpd.layer_list) == 0:
                QtWidgets.QMessageBox.critical(
                    None, self.tr("Error"),
                    self.tr(
                        "You must add a land productivity dynamics indicator layer to "
                        "your map before you can use the SDG calculation tool."
                    )
                )

                return False

        if len(combo_boxes.combo_layer_lc.layer_list) == 0:
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"),
                self.tr(
                    "You must add a land cover indicator layer to your map before you "
                    "can use the SDG calculation tool."
                )
            )

            return False

        if len(combo_boxes.combo_layer_soc.layer_list) == 0:
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"),
                self.tr(
                    "You must add a soil organic carbon indicator layer to your map "
                    "before you can use the SDG calculation tool."
                )
            )

            return False

        return True

    def validate_layer_extents(self, combo_boxes, prod_mode):
        '''Check that the layers cover the full extent of the AOI'''

        if prod_mode == 'Trends.Earth productivity':
            if self.aoi.calc_frac_overlap(
                QgsGeometry.fromRect(
                    combo_boxes.combo_layer_traj.get_layer().extent()
                )
            ) < 0.99:
                QtWidgets.QMessageBox.critical(
                    None, self.tr("Error"),
                    self.tr(
                        "Area of interest is not entirely within the trajectory layer."
                    )
                )

                return False

            if self.aoi.calc_frac_overlap(
                QgsGeometry.fromRect(
                    combo_boxes.combo_layer_perf.get_layer().extent()
                )
            ) < .99:
                QtWidgets.QMessageBox.critical(
                    None, self.tr("error"),
                    self.tr(
                        "area of interest is not entirely within the "
                        "performance layer."
                    )
                )

                return False

            if self.aoi.calc_frac_overlap(
                QgsGeometry.fromRect(
                    combo_boxes.combo_layer_state.get_layer().extent()
                )
            ) < .99:
                QtWidgets.QMessageBox.critical(
                    None, self.tr("Error"),
                    self.tr(
                        "Area of interest is not entirely within the state layer."
                    )
                )

                return False
        else:
            if self.aoi.calc_frac_overlap(
                QgsGeometry.fromRect(
                    combo_boxes.combo_layer_lpd.get_layer().extent()
                )
            ) < .99:
                QtWidgets.QMessageBox.critical(
                    None, self.tr("Error"),
                    self.tr(
                        "Area of interest is not entirely within the land "
                        "productivity dynamics layer."
                    )
                )

                return False

        if self.aoi.calc_frac_overlap(
            QgsGeometry.fromRect(
                combo_boxes.combo_layer_lc.get_layer().extent()
            )
        ) < .99:
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"),
                self.tr(
                    "Area of interest is not entirely within the land cover layer."
                )
            )

            return False

        if self.aoi.calc_frac_overlap(
            QgsGeometry.fromRect(
                combo_boxes.combo_layer_soc.get_layer().extent()
            )
        ) < .99:
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"),
                self.tr(
                    "Area of interest is not entirely within the soil organic "
                    "carbon layer."
                )
            )

            return False

        return True

    def validate_layer_crs(self, combo_boxes, prod_mode):
        '''check all layers have the same resolution and CRS'''
        def res(layer):
            return (
                round(layer.rasterUnitsPerPixelX(),
                      10), round(layer.rasterUnitsPerPixelY(), 10)
            )

        if prod_mode == ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value:
            if res(combo_boxes.combo_layer_traj.get_layer()
                   ) != res(combo_boxes.combo_layer_state.get_layer()):
                QtWidgets.QMessageBox.critical(
                    None, self.tr("Error"),
                    self.tr(
                        "Resolutions of trajectory layer and state layer do not match."
                    )
                )

                return False

            if res(combo_boxes.combo_layer_traj.get_layer()
                   ) != res(combo_boxes.combo_layer_perf.get_layer()):
                QtWidgets.QMessageBox.critical(
                    None, self.tr("Error"),
                    self.tr(
                        "Resolutions of trajectory layer and performance layer do not match."
                    )
                )

                return False

            if combo_boxes.combo_layer_traj.get_layer().crs(
            ) != combo_boxes.combo_layer_state.get_layer().crs():
                QtWidgets.QMessageBox.critical(
                    None, self.tr("Error"),
                    self.tr(
                        "Coordinate systems of trajectory layer and state layer do not match."
                    )
                )

                return False

            if combo_boxes.combo_layer_traj.get_layer().crs(
            ) != combo_boxes.combo_layer_perf.get_layer().crs():
                QtWidgets.QMessageBox.critical(
                    None, self.tr("Error"),
                    self.tr(
                        "Coordinate systems of trajectory layer and performance layer do not match."
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

        if self.radio_te_prod.isChecked():
            prod_mode = ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value
        else:
            prod_mode = ProductivityMode.JRC_5_CLASS_LPD.value

        ##########
        # Baseline

        if (
            not self.
            validate_layer_selections(self.combo_boxes['baseline'], prod_mode)
            or not self.
            validate_layer_crs(self.combo_boxes['baseline'], prod_mode)
            or not self.
            validate_layer_extents(self.combo_boxes['baseline'], prod_mode)
        ):
            log('failed baseline layer validation')

            return

        params = {
            'baseline':
            ldn.get_main_sdg_15_3_1_job_params(
                task_name=self.options_tab.task_name.text(),
                aoi=self.aoi,
                prod_mode=prod_mode,
                combo_layer_lc=self.combo_boxes['baseline'].combo_layer_lc,
                combo_layer_soc=self.combo_boxes['baseline'].combo_layer_soc,
                combo_layer_traj=self.combo_boxes['baseline'].combo_layer_traj,
                combo_layer_perf=self.combo_boxes['baseline'].combo_layer_perf,
                combo_layer_state=self.combo_boxes['baseline'].
                combo_layer_state,
                combo_layer_lpd=self.combo_boxes['baseline'].combo_layer_lpd,
                combo_layer_pop_total=self.combo_boxes['baseline'].
                combo_layer_pop_total,
                combo_layer_pop_male=self.combo_boxes['baseline'].
                combo_layer_pop_male,
                combo_layer_pop_female=self.combo_boxes['baseline'].
                combo_layer_pop_female,
                task_notes=self.options_tab.task_notes.toPlainText()
            )
        }

        ##########
        # Progress

        if self.checkBox_progress_period.isChecked():
            if (
                not self.validate_layer_selections(
                    self.combo_boxes['progress'], prod_mode
                ) or not self.
                validate_layer_crs(self.combo_boxes['progress'], prod_mode)
                or not self.validate_layer_extents(
                    self.combo_boxes['progress'], prod_mode
                )
            ):
                log('failed progress layer validation')

                return

            params.update(
                {
                    'progress':
                    ldn.get_main_sdg_15_3_1_job_params(
                        task_name=self.options_tab.task_name.text(),
                        aoi=self.aoi,
                        prod_mode=prod_mode,
                        combo_layer_lc=self.combo_boxes['progress'].
                        combo_layer_lc,
                        combo_layer_soc=self.combo_boxes['progress'].
                        combo_layer_soc,
                        combo_layer_traj=self.combo_boxes['progress'].
                        combo_layer_traj,
                        combo_layer_perf=self.combo_boxes['progress'].
                        combo_layer_perf,
                        combo_layer_state=self.combo_boxes['progress'].
                        combo_layer_state,
                        combo_layer_lpd=self.combo_boxes['progress'].
                        combo_layer_lpd,
                        combo_layer_pop_total=self.combo_boxes['progress'].
                        combo_layer_pop_total,
                        combo_layer_pop_male=self.combo_boxes['progress'].
                        combo_layer_pop_male,
                        combo_layer_pop_female=self.combo_boxes['progress'].
                        combo_layer_pop_female,
                        task_notes=self.options_tab.task_notes.toPlainText()
                    )
                }
            )

        params['task_name'] = self.options_tab.task_name.text()
        params['task_notes'] = self.options_tab.task_notes.toPlainText()

        self.close()

        job_manager.submit_local_job(
            params,
            script_name=self.LOCAL_SCRIPT_NAME,
            area_of_interest=self.aoi
        )
