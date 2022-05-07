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
from dataclasses import dataclass

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
DlgCalculateLdnErrorRecodeUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateLDNErrorRecode.ui")
)

class tr_calculate_ldn(object):
    def tr(self, message):
        return QtCore.QCoreApplication.translate("tr_calculate_ldn", message)


@dataclass
class TimePeriodWidgets:
    radio_time_period_same: QtWidgets.QRadioButton
    radio_lpd_jrc: QtWidgets.QRadioButton
    cb_jrc: QtWidgets.QRadioButton
    year_initial: QtWidgets.QDateEdit
    year_final: QtWidgets.QDateEdit
    label_prod: QtWidgets.QLabel
    year_initial_prod: QtWidgets.QDateEdit
    year_final_prod: QtWidgets.QDateEdit
    label_lc: QtWidgets.QLabel
    year_initial_lc: QtWidgets.QDateEdit
    year_final_lc: QtWidgets.QDateEdit
    label_soc: QtWidgets.QLabel
    year_initial_soc: QtWidgets.QDateEdit
    year_final_soc: QtWidgets.QDateEdit


class DlgCalculateOneStep(DlgCalculateBase, DlgCalculateOneStepUi):
    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        script: ExecutionScript,
        parent: QtWidgets.QWidget = None
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)

        self.widgets_baseline = TimePeriodWidgets(
            self.radio_time_period_same_baseline,
            self.radio_lpd_jrc,
            self.cb_jrc_baseline,
            self.year_initial_baseline,
            self.year_final_baseline,
            self.label_baseline_prod,
            self.year_initial_baseline_prod,
            self.year_final_baseline_prod,
            self.label_baseline_lc,
            self.year_initial_baseline_lc,
            self.year_final_baseline_lc,
            self.label_baseline_soc,
            self.year_initial_baseline_soc,
            self.year_final_baseline_soc,
        )
        self.widgets_progress = TimePeriodWidgets(
            self.radio_time_period_same_progress,
            self.radio_lpd_jrc,
            self.cb_jrc_progress,
            self.year_initial_progress,
            self.year_final_progress,
            self.label_progress_prod,
            self.year_initial_progress_prod,
            self.year_final_progress_prod,
            self.label_progress_lc,
            self.year_initial_progress_lc,
            self.year_final_progress_lc,
            self.label_progress_soc,
            self.year_initial_progress_soc,
            self.year_final_progress_soc,
        )

        self.cb_jrc_baseline.addItems(
            [*conf.REMOTE_DATASETS["Land Productivity Dynamics (JRC)"].keys()]
        )
        self.cb_jrc_baseline.setCurrentIndex(1)
        self.cb_jrc_progress.addItems(
            [*conf.REMOTE_DATASETS["Land Productivity Dynamics (JRC)"].keys()]
        )
        self.cb_jrc_progress.setCurrentIndex(2)

        self.toggle_lpd_options()

        self.cb_jrc_baseline.currentIndexChanged.connect(
            lambda: self.update_time_bounds(self.widgets_baseline)
        )
        self.cb_jrc_progress.currentIndexChanged.connect(
            lambda: self.update_time_bounds(self.widgets_progress)
        )
        self.radio_time_period_same_baseline.toggled.connect(
            lambda: self.toggle_time_period(self.widgets_baseline)
        )
        self.radio_time_period_same_progress.toggled.connect(
            lambda: self.toggle_time_period(self.widgets_progress)
        )

        self.lc_setup_widget = lc_setup.LandCoverSetupRemoteExecutionWidget(
            self, hide_min_year=True, hide_max_year=True
        )

        self.year_initial_baseline.dateChanged.connect(
            lambda: self.update_start_dates(self.widgets_baseline)
        )
        self.year_final_baseline.dateChanged.connect(
            lambda: self.update_end_dates(self.widgets_baseline)
        )
        self.year_initial_progress.dateChanged.connect(
            lambda: self.update_start_dates(self.widgets_progress)
        )
        self.year_final_progress.dateChanged.connect(
            lambda: self.update_end_dates(self.widgets_progress)
        )

        self.radio_lpd_te.toggled.connect(self.toggle_lpd_options)

        self.lc_define_deg_widget = lc_setup.LCDefineDegradationWidget()

        self.checkBox_progress_period.toggled.connect(
            self.toggle_progress_period
        )
        self.toggle_progress_period()

        self.button_preset_unccd_default_jrc.clicked.connect(self.set_preset_unccd_default_jrc)
        self.button_preset_unccd_default_te.clicked.connect(self.set_preset_unccd_default_te)

        self._finish_initialization()

    def set_preset_unccd_default_jrc(self):
        self.checkBox_progress_period.setChecked(True)
        self.radio_lpd_jrc.setChecked(True)
        self.cb_jrc_baseline.setCurrentIndex(self.cb_jrc_baseline.findText(
            'JRC Land Productivity Dynamics (2000-2015)'))
        self.cb_jrc_progress.setCurrentIndex(self.cb_jrc_baseline.findText(
            'JRC Land Productivity Dynamics (2005-2019)'))
        self.radio_time_period_same_baseline.setChecked(True)
        self.radio_time_period_vary_progress.setChecked(True)
        self.year_initial_baseline.setDate(QtCore.QDate(2000, 1, 1))
        self.year_final_baseline.setDate(QtCore.QDate(2015, 1, 1))
        self.year_initial_progress.setDate(QtCore.QDate(2005, 1, 1))
        self.year_final_progress.setDate(QtCore.QDate(2019, 1, 1))
        self.year_initial_progress_lc.setDate(QtCore.QDate(2015, 1, 1))
        self.year_final_progress_lc.setDate(QtCore.QDate(2019, 1, 1))
        self.year_initial_progress_soc.setDate(QtCore.QDate(2015, 1, 1))
        self.year_final_progress_soc.setDate(QtCore.QDate(2019, 1, 1))

        self.lc_setup_widget.aggregation_dialog.reset_nesting_table()
        self.lc_define_deg_widget.set_trans_matrix(get_default=True)

    def set_preset_unccd_default_te(self):
        self.checkBox_progress_period.setChecked(True)
        self.radio_lpd_te.setChecked(True)
        self.radio_time_period_same_baseline.setChecked(True)
        self.radio_time_period_vary_progress.setChecked(True)
        self.year_initial_baseline.setDate(QtCore.QDate(2001, 1, 1))
        self.year_final_baseline.setDate(QtCore.QDate(2015, 1, 1))
        self.year_initial_progress.setDate(QtCore.QDate(2005, 1, 1))
        self.year_final_progress.setDate(QtCore.QDate(2019, 1, 1))
        self.year_initial_progress_lc.setDate(QtCore.QDate(2015, 1, 1))
        self.year_final_progress_lc.setDate(QtCore.QDate(2019, 1, 1))
        self.year_initial_progress_soc.setDate(QtCore.QDate(2015, 1, 1))
        self.year_final_progress_soc.setDate(QtCore.QDate(2019, 1, 1))

        self.lc_setup_widget.aggregation_dialog.reset_nesting_table()
        self.lc_define_deg_widget.set_trans_matrix(get_default=True)

    def update_start_dates(self, widgets):
        widgets.year_initial_prod.setDate(widgets.year_initial.date())
        widgets.year_initial_lc.setDate(widgets.year_initial.date())
        widgets.year_initial_soc.setDate(widgets.year_initial.date())

    def update_end_dates(self, widgets):
        widgets.year_final_prod.setDate(widgets.year_final.date())
        widgets.year_final_lc.setDate(widgets.year_final.date())
        widgets.year_final_soc.setDate(widgets.year_final.date())

    def toggle_time_period(self, widgets):
        if widgets.radio_time_period_same.isChecked():
            widgets.label_lc.setEnabled(False)
            widgets.year_initial_lc.setEnabled(False)
            widgets.year_final_lc.setEnabled(False)

            widgets.label_soc.setEnabled(False)
            widgets.year_initial_soc.setEnabled(False)
            widgets.year_final_soc.setEnabled(False)

            widgets.year_initial.setEnabled(True)
            widgets.year_final.setEnabled(True)

            widgets.label_prod.setEnabled(False)
            widgets.year_initial_prod.setEnabled(False)
            widgets.year_final_prod.setEnabled(False)

            widgets.year_initial.setEnabled(True)
        else:
            widgets.label_lc.setEnabled(True)
            widgets.year_initial_lc.setEnabled(True)
            widgets.year_final_lc.setEnabled(True)

            widgets.label_soc.setEnabled(True)
            widgets.year_initial_soc.setEnabled(True)
            widgets.year_final_soc.setEnabled(True)

            widgets.year_initial.setEnabled(False)
            widgets.year_final.setEnabled(False)

            if not widgets.radio_lpd_jrc.isChecked():
                widgets.label_prod.setEnabled(True)
                widgets.year_initial_prod.setEnabled(True)
                widgets.year_final_prod.setEnabled(True)

    def toggle_lpd_options(self):
        if self.radio_lpd_jrc.isChecked():
            self.cb_jrc_baseline.show()
            self.label_jrc_baseline.show()
            self.cb_jrc_progress.show()
            self.label_jrc_progress.show()
        else:
            self.cb_jrc_baseline.hide()
            self.label_jrc_baseline.hide()
            self.cb_jrc_progress.hide()
            self.label_jrc_progress.hide()

        self.update_time_bounds(self.widgets_baseline)
        self.update_time_bounds(self.widgets_progress)

        self.toggle_time_period(self.widgets_baseline)
        self.toggle_time_period(self.widgets_progress)


    def update_time_bounds(self, widgets):
        lc_dataset = conf.REMOTE_DATASETS["Land cover"]["ESA CCI"]
        start_year_lc = lc_dataset['Start year']
        end_year_lc = lc_dataset['End year']
        start_year_lc = QtCore.QDate(start_year_lc, 1, 1)
        end_year_lc = QtCore.QDate(end_year_lc, 1, 1)

        if self.radio_lpd_te.isChecked():
            prod_dataset = conf.REMOTE_DATASETS["NDVI"][
                "MODIS (MOD13Q1, annual)"]
            start_year_prod = prod_dataset['Start year']
            end_year_prod = prod_dataset['End year']

            start_year_prod = QtCore.QDate(start_year_prod, 1, 1)
            end_year_prod = QtCore.QDate(end_year_prod, 1, 1)
            start_year = max(start_year_prod, start_year_lc)
            end_year = min(end_year_prod, end_year_lc)

        else:
            prod_dataset = conf.REMOTE_DATASETS[
                "Land Productivity Dynamics (JRC)"][
                    widgets.cb_jrc.currentText()]
            start_year_prod = prod_dataset['Start year']
            end_year_prod = prod_dataset['End year']

            # Don't need to consider prod dates in below lims when using JRC, but do use
            # them to set default time period
            start_year = start_year_lc
            end_year = end_year_lc
            start_year_prod = QtCore.QDate(start_year_prod, 1, 1)
            end_year_prod = QtCore.QDate(end_year_prod, 1, 1)

        widgets.year_initial.setMinimumDate(start_year)
        widgets.year_initial.setMaximumDate(end_year)
        widgets.year_final.setMinimumDate(start_year)
        widgets.year_final.setMaximumDate(end_year)

        if widgets.radio_lpd_jrc.isChecked():
            widgets.year_initial_prod.setDate(start_year_prod)
            widgets.year_final_prod.setDate(end_year_prod)
            widgets.year_initial_prod.setMinimumDate(start_year_prod)
            widgets.year_initial_prod.setMaximumDate(start_year_prod)
            widgets.year_final_prod.setMinimumDate(end_year_prod)
            widgets.year_final_prod.setMaximumDate(end_year_prod)
        else:
            widgets.year_initial_prod.setDate(start_year_prod)
            widgets.year_final_prod.setDate(end_year_prod)
            widgets.year_initial_prod.setMinimumDate(start_year_prod)
            widgets.year_initial_prod.setMaximumDate(end_year_prod)
            widgets.year_final_prod.setMinimumDate(start_year_prod)
            widgets.year_final_prod.setMaximumDate(end_year_prod)

        widgets.year_initial_lc.setMinimumDate(start_year_lc)
        widgets.year_initial_lc.setMaximumDate(end_year_lc)
        widgets.year_final_lc.setMinimumDate(start_year_lc)
        widgets.year_final_lc.setMaximumDate(end_year_lc)

        widgets.year_initial_soc.setMinimumDate(start_year_lc)
        widgets.year_initial_soc.setMaximumDate(end_year_lc)
        widgets.year_final_soc.setMinimumDate(start_year_lc)
        widgets.year_final_soc.setMaximumDate(end_year_lc)

        widgets.year_initial.setDate(start_year_prod)
        widgets.year_final.setDate(end_year_prod)


        self.update_start_dates(widgets)
        self.update_end_dates(widgets)

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

    def _get_period_years(self, widgets):
        return {
            'period_year_initial': widgets.year_initial_prod.date().year(),
            'period_year_final': widgets.year_final_prod.date().year()
        }

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateOneStep, self).btn_calculate()

        if not ret:
            return

        if self.radio_lpd_te.isChecked():
            prod_mode = ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value
        else:
            prod_mode = ProductivityMode.JRC_5_CLASS_LPD.value

        periods = {
            'baseline': self._get_period_years(self.widgets_baseline)
        }

        if self.checkBox_progress_period.isChecked():
            periods.update({
                'progress': self._get_period_years(self.widgets_progress)
            })

        crosses_180th, geojsons = self.gee_bounding_box

        payloads = []

        for (period, values), widgets in zip(
            periods.items(), (self.widgets_progress, self.widgets_baseline)
        ):
            payload = {}
            year_initial = values['period_year_initial']
            year_final = values['period_year_final']

            log(f'Setting parameters for {period} period ({year_initial} - {year_final})')

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
                prod_dataset = conf.REMOTE_DATASETS[
                    "Land Productivity Dynamics (JRC)"][widgets.cb_jrc.currentText()]
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
                widgets.year_initial_lc.date().year(),
                'year_final':
                widgets.year_final_lc.date().year(),
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
                widgets.year_initial_soc.date().year(),
                'year_final':
                widgets.year_final_soc.date().year(),
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

        self.combo_datasets_baseline.NO_DATASETS_MESSAGE =  self.tr(
            'No datasets available in this region (see advanced)'
        )
        self.combo_datasets_progress.NO_DATASETS_MESSAGE =  self.tr(
            'No datasets available in this region (see advanced)'
        )
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

        self.radio_population_baseline_bysex.toggled.connect(
            self.toggle_pop_options_baseline
        )
        self.toggle_pop_options_baseline()

        self.radio_population_progress_bysex.toggled.connect(
            self.toggle_pop_options_progress
        )
        self.toggle_pop_options_progress()
        self.changed_region.connect(self.populate_combos)

    def populate_combos(self):
        self.combo_boxes['baseline'].populate()
        self.combo_boxes['progress'].populate()

    def showEvent(self, event):
        super().showEvent(event)
        self.populate_combos()
        self.toggle_progress_period()

    def toggle_pop_options_baseline(self):
        if self.radio_population_baseline_bysex.isChecked():
            self.combo_layer_population_baseline_male.setEnabled(True)
            self.combo_layer_population_baseline_female.setEnabled(True)
            self.label_male_population_baseline.setEnabled(True)
            self.label_female_population_baseline.setEnabled(True)
            self.combo_layer_population_baseline_total.setEnabled(False)
            self.label_total_population_baseline.setEnabled(False)
        else:
            self.combo_layer_population_baseline_male.setEnabled(False)
            self.combo_layer_population_baseline_female.setEnabled(False)
            self.label_male_population_baseline.setEnabled(False)
            self.label_female_population_baseline.setEnabled(False)
            self.combo_layer_population_baseline_total.setEnabled(True)
            self.label_total_population_baseline.setEnabled(True)

    def toggle_pop_options_progress(self):
        if self.radio_population_progress_bysex.isChecked():
            self.combo_layer_population_progress_male.setEnabled(True)
            self.combo_layer_population_progress_female.setEnabled(True)
            self.label_male_population_progress.setEnabled(True)
            self.label_female_population_progress.setEnabled(True)
            self.combo_layer_population_progress_total.setEnabled(False)
            self.label_total_population_progress.setEnabled(False)
        else:
            self.combo_layer_population_progress_male.setEnabled(False)
            self.combo_layer_population_progress_female.setEnabled(False)
            self.label_male_population_progress.setEnabled(False)
            self.label_female_population_progress.setEnabled(False)
            self.combo_layer_population_progress_total.setEnabled(True)
            self.label_total_population_progress.setEnabled(True)

    def toggle_progress_period(self):
        if self.checkBox_progress_period.isChecked():
            self.groupBox_progress_period.setVisible(True)
            self.advanced_configuration_progress.setVisible(True)
        else:
            self.groupBox_progress_period.setVisible(False)
            self.advanced_configuration_progress.setVisible(False)

    def _validate_layer_selection(self, combo_box, layer_name):
        if len(combo_box.layer_list) == 0:
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"),
                self.tr(
                    f"You must select a {layer_name} layer "
                    "before you can use the SDG calculation tool."
                )
            )
            return False
        else:
            return True


    def validate_layer_selections(self, combo_boxes, prod_mode, pop_mode):
        '''validate all needed layers are selected'''

        if prod_mode == ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value:
            if not self._validate_layer_selection(combo_boxes.combo_layer_traj, 'trend'):
                return False
            if not self._validate_layer_selection(combo_boxes.combo_layer_state, 'state'):
                return False
            if not self._validate_layer_selection(combo_boxes.combo_layer_perf, 'performance'):
                return False

        else:
            if not self._validate_layer_selection(combo_boxes.combo_layer_lpd, 'Land Productivity Dynamics'):
                return False

        if not self._validate_layer_selection(combo_boxes.combo_layer_lc, 'land cover'):
            return False

        if not self._validate_layer_selection(combo_boxes.combo_layer_soc, 'soil organic carbon'):
            return False

        if pop_mode == ldn.PopulationMode.BySex.value:
            if not self._validate_layer_selection(combo_boxes.combo_layer_pop_male, 'population (male)'):
                return False
            if not self._validate_layer_selection(combo_boxes.combo_layer_pop_female, 'population (female)'):
                return False
        else:
            if not self._validate_layer_selection(combo_boxes.combo_layer_pop_total, 'population (total)'):
                return False

        return True

    def _validate_layer_extent(self, check_layer, check_layer_name):
        log(f'fraction of overlap is {self.aoi.calc_frac_overlap(QgsGeometry.fromRect(check_layer.extent()))}')
        if self.aoi.calc_frac_overlap(
            QgsGeometry.fromRect(check_layer.extent())
        ) < 0.99:
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"),
                self.tr(
                    f"Area of interest is not entirely within the {check_layer_name} layer."
                )
            )
            return False
        else:
            return True

    def validate_layer_extents(self, combo_boxes, prod_mode, pop_mode):
        '''Check that the layers cover the full extent of the AOI'''

        if prod_mode == ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value:
            if not self._validate_layer_extent(combo_boxes.combo_layer_traj.get_layer(), 'trend'):
                return False

            if not self._validate_layer_extent(combo_boxes.combo_layer_perf.get_layer(), 'performance'):
                return False

            if not self._validate_layer_extent(combo_boxes.combo_layer_state.get_layer(), 'state'):
                return False

        else:
            if not self._validate_layer_extent(combo_boxes.combo_layer_lpd.get_layer(), 'Land Productivity Dynamics'):
                return False

        if not self._validate_layer_extent(combo_boxes.combo_layer_lc.get_layer(), 'land cover'):
            return False

        if not self._validate_layer_extent(combo_boxes.combo_layer_soc.get_layer(), 'soil organic carbon'):
            return False

        if pop_mode == ldn.PopulationMode.BySex.value:
            if not self._validate_layer_extent(combo_boxes.combo_layer_pop_male.get_layer(), 'population (male)'):
                return False
            if not self._validate_layer_extent(combo_boxes.combo_layer_pop_female.get_layer(), 'population (male)'):
                return False
        else:
            if not self._validate_layer_extent(combo_boxes.combo_layer_pop_total.get_layer(), 'population (total)'):
                return False

        return True

    def _validate_crs(self, model_layer, model_layer_name, check_layer, check_layer_name, check_res=True):
        def _res(layer):
            return (
                round(layer.rasterUnitsPerPixelX(),
                      10), round(layer.rasterUnitsPerPixelY(), 10)
            )

        if check_res and _res(model_layer) != _res(check_layer):
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"),
                self.tr(
                    f"Resolutions of {model_layer_name} layer and {check_layer_name} layer do not match."
                )
            )
            return False
        elif model_layer.crs() != check_layer.crs():
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"),
                self.tr(
                    f"Coordinate systems of {model_layer_name} layer and {check_layer_name} layer do not match."
                )
            )
            return False
        else:
            return True


    def validate_layer_crs(self, combo_boxes, prod_mode, pop_mode):
        '''check all layers have the same resolution and CRS'''
        if prod_mode == ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value:
            model_layer = combo_boxes.combo_layer_traj.get_layer()
            model_layer_name = 'trend'

            if not self._validate_crs(
                model_layer, model_layer_name,
                combo_boxes.combo_layer_state.get_layer(), 'state'
            ):
                return False

            if not self._validate_crs(
                model_layer, model_layer_name,
                combo_boxes.combo_layer_perf.get_layer(), 'performance'
            ):
                return False

        if pop_mode == ldn.PopulationMode.BySex.value:
            if not self._validate_crs(
                combo_boxes.combo_layer_pop_male.get_layer(), 'population (male)',
                combo_boxes.combo_layer_pop_female.get_layer(), 'population (female)'
            ):
                return False

        return True

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super().btn_calculate()

        if not ret:
            return

        if self.radio_lpd_te.isChecked():
            prod_mode = ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value
        else:
            prod_mode = ProductivityMode.JRC_5_CLASS_LPD.value

        ##########
        # Baseline
        #

        if self.radio_population_baseline_bysex.isChecked():
            pop_mode_baseline = ldn.PopulationMode.BySex.value
        else:
            pop_mode_baseline = ldn.PopulationMode.Total.value

        if (
            not self.validate_layer_selections(
                self.combo_boxes['baseline'], prod_mode, pop_mode_baseline
            ) or not self.validate_layer_crs(
                self.combo_boxes['baseline'], prod_mode, pop_mode_baseline
            ) or not self.validate_layer_extents(
                self.combo_boxes['baseline'], prod_mode, pop_mode_baseline
            )
        ):
            log('failed baseline layer validation')

            return

        params = {
            'baseline':
            ldn.get_main_sdg_15_3_1_job_params(
                task_name=self.options_tab.task_name.text(),
                aoi=self.aoi,
                prod_mode=prod_mode,
                pop_mode=pop_mode_baseline,
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
            if self.radio_population_progress_bysex.isChecked():
                pop_mode_progress = ldn.PopulationMode.BySex.value
            else:
                pop_mode_progress = ldn.PopulationMode.Total.value

            if (
                not self.validate_layer_selections(
                    self.combo_boxes['progress'], prod_mode, pop_mode_progress
                ) or not self.validate_layer_crs(
                    self.combo_boxes['progress'], prod_mode, pop_mode_progress
                ) or not self.validate_layer_extents(
                    self.combo_boxes['progress'], prod_mode, pop_mode_progress
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
                        pop_mode=pop_mode_progress,
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

        job_manager.submit_local_job_as_qgstask(
            params,
            script_name=self.LOCAL_SCRIPT_NAME,
            area_of_interest=self.aoi
        )


class DlgCalculateLDNErrorRecode(DlgCalculateBase, DlgCalculateLdnErrorRecodeUi):
    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        script: ExecutionScript,
        parent: QtWidgets.QWidget = None,
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)

        self.changed_region.connect(self.combo_dataset_error_recode.populate)

        self._finish_initialization()

    def showEvent(self, event):
        super().showEvent(event)
        self.combo_dataset_error_recode.populate()


    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.

        QtWidgets.QMessageBox.information(
            None, self.tr("Coming soon!"), self.tr("This function coming soon!")
        )
        self.close()
        return

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

        resp = job_manager.submit_remote_job(payload, self.script.id)

        if resp:
            main_msg = "Submitted"
            description = "UNCCD default data task submitted to Google Earth Engine."
        else:
            main_msg = "Error"
            description = "Unable to UNCCD default data task to Google Earth Engine."
        self.mb.pushMessage(
            self.tr(main_msg), self.tr(description), level=0, duration=5
        )
