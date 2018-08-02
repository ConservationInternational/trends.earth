# -*- coding: utf-8 -*-
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

from future import standard_library
standard_library.install_aliases()
import os
import json
from urllib.parse import quote_plus

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QSettings, QDate, Qt, QTextCodec

from qgis.utils import iface
from qgis.core import QgsJSONUtils, QgsVectorLayer, QgsGeometry
mb = iface.messageBar()

from LDMP import log
from LDMP.calculate import DlgCalculateBase, get_script_slug
from LDMP.gui.DlgCalculateProd import Ui_DlgCalculateProd as UiDialog
from LDMP.api import run_script


class DlgCalculateProd(DlgCalculateBase, UiDialog):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgCalculateProd, self).__init__(parent)

        self.setupUi(self)

        self.traj_indic.addItems(list(self.scripts['productivity']['trajectory functions'].keys()))
        self.traj_indic.currentIndexChanged.connect(self.traj_indic_changed)

        self.dataset_climate_update()
        ndvi_datasets = [x for x in list(self.datasets['NDVI'].keys()) if self.datasets['NDVI'][x]['Temporal resolution'] == 'annual']
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


    def showEvent(self, event):
        super(DlgCalculateProd, self).showEvent(event)

        #######################################################################
        #######################################################################
        # Hack to calculate multiple countries at once for workshop preparation
        #######################################################################
        #######################################################################
        # from PyQt4.QtCore import QTimer, Qt
        # from PyQt4.QtWidgets import QMessageBox, QApplication
        # from PyQt4.QtTest import QTest
        # from LDMP.download import read_json
        # from LDMP.worker import AbstractWorker, StartWorker
        # from time import sleep
        #
        # class SleepWorker(AbstractWorker):
        #     def __init__(self, time):
        #         super(SleepWorker, self).__init__()
        #         self.sleep_time = time
        #
        #     def work(self):
        #         for n in range(100):
        #             if self.killed:
        #                 return None
        #             else:
        #                 sleep(self.sleep_time / float(100))
        #                 self.progress.emit(n)
        #         return True
        #
        # # Use Trends.Earth for calculation
        # self.mode_te_prod.setChecked(True)
        #
        # # Ensure any message boxes that open are closed within 1 second
        # def close_msg_boxes():
        #     for w in QApplication.topLevelWidgets():
        #         if isinstance(w, QMessageBox):
        #             print('Closing message box')
        #             QTest.keyClick(w, Qt.Key_Enter)
        # timer = QTimer()
        # timer.timeout.connect(close_msg_boxes)
        # timer.start(1000)
        #
        # first_row = 0
        # # first_row = self.area_tab.area_admin_0.findText('Turkey') + 1
        # last_row = self.area_tab.area_admin_0.count()
        # # last_row = self.area_tab.area_admin_0.findText('Portugal')
        # log(u'First country: {}'.format(self.area_tab.area_admin_0.itemText(first_row)))
        # log(u'Last country: {}'.format(self.area_tab.area_admin_0.itemText(last_row - 1)))
        #
        # # First make sure all admin boundaries are pre-downloaded
        # for row in range(first_row, last_row):
        #     index = self.area_tab.area_admin_0.model().index(row, 0)
        #     country = self.area_tab.area_admin_0.model().data(index)
        #     adm0_a3 = self.area_tab.admin_bounds_key[country]['code']
        #     admin_polys = read_json('admin_bounds_polys_{}.json.gz'.format(adm0_a3), verify=False)
        #
        # for row in range(first_row, last_row):
        #     self.area_tab.area_admin_0.setCurrentIndex(row)
        #     index = self.area_tab.area_admin_0.model().index(row, 0)
        #     country = self.area_tab.area_admin_0.model().data(index)
        #     name = u'{}_TE_Land_Productivity'.format(country)
        #     log(name)
        #     self.options_tab.task_name.setText(name)
        #     self.btn_calculate()
        #
        #     # Sleep without freezing interface
        #     sleep_worker = StartWorker(SleepWorker, 'sleeping', 90)
        #     if not sleep_worker.success:
        #         log(u'Processing error on: {}'.format(name))
        #         #break
        #######################################################################
        #######################################################################
        # End hack
        #######################################################################
        #######################################################################

    def traj_indic_changed(self):
        self.dataset_climate_update()

    def mode_te_prod_toggled(self):
        if self.mode_lpd_jrc.isChecked():
            self.groupBox_ndvi_dataset.setEnabled(False)
            self.groupBox_traj.setEnabled(False)
            self.groupBox_perf.setEnabled(False)
            self.groupBox_state.setEnabled(False)
        else:
            self.groupBox_ndvi_dataset.setEnabled(True)
            self.groupBox_traj.setEnabled(True)
            self.groupBox_perf.setEnabled(True)
            self.groupBox_state.setEnabled(True)

    def dataset_climate_update(self):
        self.traj_climate.clear()
        self.climate_datasets = {}
        climate_types = self.scripts['productivity']['trajectory functions'][self.traj_indic.currentText()]['climate types']
        for climate_type in climate_types:
            self.climate_datasets.update(self.datasets[climate_type])
            self.traj_climate.addItems(list(self.datasets[climate_type].keys()))

    def traj_climate_changed(self):
        if self.traj_climate.currentText() == "":
            self.start_year_climate = 0
            self.end_year_climate = 9999
        else:
            self.start_year_climate = self.climate_datasets[self.traj_climate.currentText()]['Start year']
            self.end_year_climate = self.climate_datasets[self.traj_climate.currentText()]['End year']
        self.update_time_bounds()

    def dataset_ndvi_changed(self):
        this_ndvi_dataset = self.datasets['NDVI'][self.dataset_ndvi.currentText()]
        self.start_year_ndvi = this_ndvi_dataset['Start year']
        self.end_year_ndvi = this_ndvi_dataset['End year']

        self.update_time_bounds()

    def update_time_bounds(self):
        # State and performance depend only on NDVI data
        # TODO: need to also account for GAEZ and/or CCI data dates for
        # stratification
        start_year = QDate(self.start_year_ndvi, 1, 1)
        end_year = QDate(self.end_year_ndvi, 12, 31)

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
        start_year_traj = QDate(max(self.start_year_ndvi, self.start_year_climate), 1, 1)
        end_year_traj = QDate(min(self.end_year_ndvi, self.end_year_climate), 12, 31)

        self.traj_year_start.setMinimumDate(start_year_traj)
        self.traj_year_start.setMaximumDate(end_year_traj)
        self.traj_year_end.setMinimumDate(start_year_traj)
        self.traj_year_end.setMaximumDate(end_year_traj)

    def btn_cancel(self):
        self.close()

    def btn_calculate(self):
        if self.mode_te_prod.isChecked() \
                and not (self.groupBox_traj.isChecked() or
                         self.groupBox_perf.isChecked() or
                         self.groupBox_state.isChecked()):
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Choose one or more productivity sub-indicator to calculate."), None)
            return

        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateProd, self).btn_calculate()
        if not ret:
            return

        self.close()

        ndvi_dataset = self.datasets['NDVI'][self.dataset_ndvi.currentText()]['GEE Dataset']

        if self.traj_climate.currentText() != "":
            climate_gee_dataset = self.climate_datasets[self.traj_climate.currentText()]['GEE Dataset']
            log(u'climate_gee_dataset {}'.format(climate_gee_dataset))
        else:
            climate_gee_dataset = None

        if self.mode_te_prod.isChecked():
            prod_mode = 'Trends.Earth productivity'
        else:
            prod_mode = 'JRC LPD'

        crosses_180th, geojsons = self.aoi.bounding_box_gee_geojson()
        payload = {'prod_mode': prod_mode,
                   'calc_traj': self.groupBox_traj.isChecked(),
                   'calc_perf': self.groupBox_perf.isChecked(),
                   'calc_state': self.groupBox_state.isChecked(),
                   'prod_traj_year_initial': self.traj_year_start.date().year(),
                   'prod_traj_year_final': self.traj_year_end.date().year(),
                   'prod_perf_year_initial': self.perf_year_start.date().year(),
                   'prod_perf_year_final': self.perf_year_end.date().year(),
                   'prod_state_year_bl_start': self.state_year_bl_start.date().year(),
                   'prod_state_year_bl_end': self.state_year_bl_end.date().year(),
                   'prod_state_year_tg_start': self.state_year_tg_start.date().year(),
                   'prod_state_year_tg_end': self.state_year_tg_end.date().year(),
                   'geojsons': json.dumps(geojsons),
                   'crs': self.aoi.get_crs_dst_wkt(),
                   'crosses_180th': crosses_180th,
                   'ndvi_gee_dataset': ndvi_dataset,
                   'climate_gee_dataset': climate_gee_dataset,
                   'task_name': self.options_tab.task_name.text(),
                   'task_notes': self.options_tab.task_notes.toPlainText()}

        # This will add in the trajectory-method parameter for productivity 
        # trajectory
        payload.update(self.scripts['productivity']['trajectory functions'][self.traj_indic.currentText()]['params'])

        resp = run_script(get_script_slug('productivity'), payload)

        if resp:
            mb.pushMessage(QtWidgets.QApplication.translate("LDMP", "Submitted"),
                           QtWidgets.QApplication.translate("LDMP", "Productivity task submitted to Google Earth Engine."),
                           level=0, duration=5)
        else:
            mb.pushMessage(QtWidgets.QApplication.translate("LDMP", "Error"),
                           QtWidgets.QApplication.translate("LDMP", "Unable to submit productivity task to Google Earth Engine."),
                           level=0, duration=5)
