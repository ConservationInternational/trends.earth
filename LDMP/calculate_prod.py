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

import os
import json
from urllib import quote_plus

from PyQt4 import QtGui
from PyQt4.QtCore import QSettings, QDate, Qt, QTextCodec

from qgis.utils import iface
from qgis.core import QgsJSONUtils, QgsVectorLayer, QgsGeometry
mb = iface.messageBar()

from LDMP import log
from LDMP.calculate import DlgCalculateBase
from LDMP.gui.DlgCalculateProd import Ui_DlgCalculateProd as UiDialog
from LDMP.api import run_script


class DlgCalculateProd(DlgCalculateBase, UiDialog):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgCalculateProd, self).__init__(parent)

        self.setupUi(self)

        self.traj_indic.addItems(self.scripts['productivity-trajectory']['functions'].keys())
        self.traj_indic.currentIndexChanged.connect(self.traj_indic_changed)

        self.dataset_climate_update()
        ndvi_datasets = [x for x in self.datasets['NDVI'].keys() if self.datasets['NDVI'][x]['Temporal resolution'] == 'annual']
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

        self.mode_lpd_custom.toggled.connect(self.mode_lpd_custom_toggled)

        self.mode_lpd_custom_toggled()

        self.resize(self.width(), 711)

    def traj_indic_changed(self):
        self.dataset_climate_update()

    def mode_lpd_custom_toggled(self):
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
        climate_types = self.scripts['productivity-trajectory']['functions'][self.traj_indic.currentText()]['climate types']
        for climate_type in climate_types:
            self.climate_datasets.update(self.datasets[climate_type])
            self.traj_climate.addItems(self.datasets[climate_type].keys())

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
        if not (self.groupBox_traj.isChecked() or
                self.groupBox_perf.isChecked() or
                self.groupBox_state.isChecked()):
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Choose one or more indicators to calculate."), None)
            return

        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateProd, self).btn_calculate()
        if not ret:
            return

        self.close()

        ndvi_dataset = self.datasets['NDVI'][self.dataset_ndvi.currentText()]['GEE Dataset']

        if self.groupBox_traj.isChecked():
            self.calculate_trajectory(self.aoi.bounding_box_geojson, ndvi_dataset)

        if self.groupBox_perf.isChecked():
            self.calculate_performance(self.aoi.bounding_box_geojson, ndvi_dataset)

        if self.groupBox_state.isChecked():
            self.calculate_state(self.aoi.bounding_box_geojson, ndvi_dataset)

    def calculate_trajectory(self, geojson, ndvi_dataset):
        if self.traj_climate.currentText() != "":
            climate_gee_dataset = self.climate_datasets[self.traj_climate.currentText()]['GEE Dataset']
            log('climate_gee_dataset {}'.format(climate_gee_dataset))
        else:
            climate_gee_dataset = None

        payload = {'year_start': self.traj_year_start.date().year(),
                   'year_end': self.traj_year_end.date().year(),
                   'geojson': json.dumps(self.aoi.bounding_box_geojson),
                   'ndvi_gee_dataset': ndvi_dataset,
                   'climate_gee_dataset': climate_gee_dataset,
                   'task_name': self.options_tab.task_name.text(),
                   'task_notes': self.options_tab.task_notes.toPlainText()}
        # This will add in the method parameter
        payload.update(self.scripts['productivity-trajectory']['functions'][self.traj_indic.currentText()]['params'])

        # All of the productivity trajectory indicators are within the same
        # script - the "functions" are all within a single GEE script so they
        # all have the same script id.
        gee_script = 'productivity-trajectory' + '-' + self.scripts['productivity-trajectory']['script version']

        resp = run_script(gee_script, payload)

        if resp:
            mb.pushMessage(QtGui.QApplication.translate("LDMP", "Submitted"),
                           QtGui.QApplication.translate("LDMP", "Productivity trajectory task submitted to Google Earth Engine."),
                           level=0, duration=5)
        else:
            mb.pushMessage(QtGui.QApplication.translate("LDMP", "Error"),
                           QtGui.QApplication.translate("LDMP", "Unable to submit productivity trajectory task to Google Earth Engine."),
                           level=0, duration=5)

    def calculate_performance(self, geojson, ndvi_dataset):
        payload = {'year_start': self.perf_year_start.date().year(),
                   'year_end': self.perf_year_end.date().year(),
                   'geojson': json.dumps(geojson),
                   'ndvi_gee_dataset': ndvi_dataset,
                   'task_name': self.options_tab.task_name.text(),
                   'task_notes': self.options_tab.task_notes.toPlainText()}

        gee_script = 'productivity-performance' + '-' + self.scripts['productivity-performance']['script version']

        resp = run_script(gee_script, payload)

        if resp:
            mb.pushMessage(QtGui.QApplication.translate("LDMP", "Submitted"),
                           QtGui.QApplication.translate("LDMP", "Productivity performance task submitted to Google Earth Engine."),
                           level=0, duration=5)
        else:
            mb.pushMessage(QtGui.QApplication.translate("LDMP", "Error"),
                           QtGui.QApplication.translate("LDMP", "Unable to submit productivity performance task to Google Earth Engine."),
                           level=0, duration=5)

    def calculate_state(self, geojson, ndvi_dataset):
        payload = {'year_bl_start': self.state_year_bl_start.date().year(),
                   'year_bl_end': self.state_year_bl_end.date().year(),
                   'year_tg_start': self.state_year_tg_start.date().year(),
                   'year_tg_end': self.state_year_tg_end.date().year(),
                   'geojson': json.dumps(geojson),
                   'ndvi_gee_dataset': ndvi_dataset,
                   'task_name': self.options_tab.task_name.text(),
                   'task_notes': self.options_tab.task_notes.toPlainText()}

        gee_script = 'productivity-state' + '-' + self.scripts['productivity-state']['script version']

        resp = run_script(gee_script, payload)

        if resp:
            mb.pushMessage(QtGui.QApplication.translate("LDMP", "Submitted"),
                           QtGui.QApplication.translate("LDMP", "Productivity state task submitted to Google Earth Engine."),
                           level=0, duration=5)
        else:
            mb.pushMessage(QtGui.QApplication.translate("LDMP", "Error"),
                           QtGui.QApplication.translate("LDMP", "Unable to submit productivity state task to Google Earth Engine."),
                           level=0, duration=5)
