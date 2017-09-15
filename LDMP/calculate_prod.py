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
        email                : GEF-LDMP@conservation.org
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

class DlgCalculateProd(DlgCalculateBase, UiDialog):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgCalculateProd, self).__init__(parent)

        self.setupUi(self)

        self.start_year_climate = 0
        self.end_year_climate = 9999

        self.dataset_ndvi.addItems(self.datasets['NDVI'].keys())
        self.dataset_ndvi_changed()

        self.traj_indic.addItems(self.scripts['productivity_trajectory'].keys())
        self.traj_indic.currentIndexChanged.connect(self.traj_indic_changed)

        self.dataset_ndvi.currentIndexChanged.connect(self.dataset_ndvi_changed)

        self.indic_select_traj.stateChanged.connect(self.indic_select_traj_changed)
        self.indic_select_perf.stateChanged.connect(self.indic_select_perf_changed)
        self.indic_select_state.stateChanged.connect(self.indic_select_state_changed)

        self.indic_select_traj_changed()
        self.indic_select_perf_changed()
        self.indic_select_state_changed()
        self.StateTab.setEnabled(False)
        self.PerformanceTab.setEnabled(False)

        self.setup_dialog()

    def indic_select_traj_changed(self):
        if self.indic_select_traj.isChecked():
            self.TrajectoryTab.setEnabled(True)
        else:
            self.TrajectoryTab.setEnabled(False)

    def indic_select_perf_changed(self):
        if self.indic_select_perf.isChecked():
            self.PerformanceTab.setEnabled(True)
            QtGui.QMessageBox.critical(None, self.tr("Warning"),
                    self.tr("Productivity performance calculation code is still being tested. Use results at your own risk."), None)
        else:
            self.PerformanceTab.setEnabled(False)

    def indic_select_state_changed(self):
        if self.indic_select_state.isChecked():
            self.StateTab.setEnabled(True)
            QtGui.QMessageBox.critical(None, self.tr("Warning"),
                    self.tr("Productivity state calculation code is still being tested. Use results at your own risk."), None)
        else:
            self.StateTab.setEnabled(False)

    def traj_indic_changed(self):
        self.dataset_climate_update()

    def dataset_climate_update(self):
        self.traj_climate.clear()
        self.climate_datasets = {}
        climate_types = self.scripts['productivity_trajectory'][self.traj_indic.currentText()]['climate types']
        for climate_type in climate_types:
            self.traj_climate.addItems(self.datasets[climate_type].keys())
            self.climate_datasets.update(self.datasets[climate_type])

    def dataset_ndvi_changed(self):
        this_ndvi_dataset = self.datasets['NDVI'][self.dataset_ndvi.currentText()]
        self.start_year_ndvi = this_ndvi_dataset['Start year']
        self.end_year_ndvi = this_ndvi_dataset['End year']

        self.update_time_bounds()

    def update_time_bounds(self):
        start_year = QDate(max(self.start_year_ndvi, self.start_year_climate), 1, 1)
        end_year = QDate(min(self.end_year_ndvi, self.end_year_climate), 12, 31)

        # Trajectory
        self.traj_year_start.setMinimumDate(start_year)
        self.traj_year_start.setMaximumDate(end_year)
        self.traj_year_end.setMinimumDate(start_year)
        self.traj_year_end.setMaximumDate(end_year)

        # State
        self.perf_year_start.setMinimumDate(start_year)
        self.perf_year_start.setMaximumDate(end_year)
        self.perf_year_end.setMinimumDate(start_year)
        self.perf_year_end.setMaximumDate(end_year)

        # Performance
        self.state_existdeg_early_year_start.setMinimumDate(start_year)
        self.state_existdeg_early_year_start.setMaximumDate(end_year)
        self.state_existdeg_early_year_end.setMinimumDate(start_year)
        self.state_existdeg_early_year_end.setMaximumDate(end_year)
        self.state_existdeg_late_year_start.setMinimumDate(start_year)
        self.state_existdeg_late_year_start.setMaximumDate(end_year)
        self.state_existdeg_late_year_end.setMinimumDate(start_year)
        self.state_existdeg_late_year_end.setMaximumDate(end_year)
        self.state_emergedeg_base_year_start.setMinimumDate(start_year)
        self.state_emergedeg_base_year_start.setMaximumDate(end_year)
        self.state_emergedeg_base_year_end.setMinimumDate(start_year)
        self.state_emergedeg_base_year_end.setMaximumDate(end_year)
        self.state_emergedeg_comp_year_start.setMinimumDate(start_year)
        self.state_emergedeg_comp_year_start.setMaximumDate(end_year)
        self.state_emergedeg_comp_year_end.setMinimumDate(start_year)
        self.state_emergedeg_comp_year_end.setMaximumDate(end_year)
            
    def btn_cancel(self):
        self.close()

    def btn_calculate(self):
        super(DlgCalculateProd, self).btn_calculate()

        if not (self.indic_select_traj.isChecked() or 
                self.indic_select_perf.isChecked() or 
                self.indic_select_state.isChecked()):
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("Choose one or more indicators to calculate."), None)
            return

        ndvi_dataset = self.datasets['NDVI'][self.dataset_ndvi.currentText()]['GEE Dataset']

        if self.indic_select_traj.isChecked():
            self.calculate_trajectory(self.bbox, ndvi_dataset)

        if self.indic_select_perf.isChecked():
            self.calculate_performance(self.bbox, ndvi_dataset)

        if self.indic_select_state.isChecked():
            self.calculate_state(self.bbox, ndvi_dataset)
    
    def calculate_trajectory(self, geojson, ndvi_dataset):
        if self.traj_climate.currentText() != "":
            log('self.climate_datasets {}'.format(self.climate_datasets))
            climate_gee_dataset = self.climate_datasets[self.traj_climate.currentText()]['GEE Dataset']
            log('climate_gee_dataset {}'.format(climate_gee_dataset))
        else:
            climate_gee_dataset = None

        payload = {'year_start': self.traj_year_start.date().year(),
                   'year_end': self.traj_year_end.date().year(),
                   'geojson': json.dumps(self.bbox),
                   'ndvi_gee_dataset': ndvi_dataset,
                   'climate_gee_dataset': climate_gee_dataset,
                   'task_name': self.task_name.text(),
                   'task_notes': self.task_notes.toPlainText()}
        payload.update(self.scripts['productivity_trajectory'][self.traj_indic.currentText()]['params'])

        progressMessageBar = mb.createMessage("Submitting trajectory task to Google Earth Engine...")
        spinner = QtGui.QLabel()
        movie = QtGui.QMovie(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'icons', 'spinner.gif'))
        spinner.setMovie(QtGui.QMovie())
        spinner.setAlignment(Qt.AlignLeft|Qt.AlignVCenter)
        progressMessageBar.layout().addWidget(spinner)
        mb.pushWidget(progressMessageBar, mb.INFO)
        movie.start()

        gee_script = self.scripts['productivity_trajectory'][self.traj_indic.currentText()]['script id']

        resp = self.api.calculate(gee_script, payload)

        mb.popWidget(progressMessageBar)
        if resp:
            mb.pushMessage("Submitted",
                    "Trajectory task submitted to Google Earth Engine.", level=0, duration=5)
            self.close()
        else:
            mb.pushMessage("Error", "Unable to submit trajectory task to Google Earth Engine.", level=1, duration=5)

    def calculate_performance(self, geojson, ndvi_dataset):
        payload = {'year_start': self.perf_year_start.date().year(),
                   'year_end': self.perf_year_end.date().year(),
                   'geojson': json.dumps(geojson),
                   'ndvi_gee_dataset': ndvi_dataset,
                   'task_name': self.task_name.text(),
                   'task_notes': self.task_notes.toPlainText()}

        progressMessageBar = mb.createMessage("Submitting productivity performance task to Google Earth Engine...")
        spinner = QtGui.QLabel()
        movie = QtGui.QMovie(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'icons', 'spinner.gif'))
        spinner.setMovie(QtGui.QMovie())
        spinner.setAlignment(Qt.AlignLeft|Qt.AlignVCenter)
        progressMessageBar.layout().addWidget(spinner)
        mb.pushWidget(progressMessageBar, mb.INFO)
        movie.start()

        gee_script = self.scripts['productivity_performance']['script id']

        resp = self.api.calculate(gee_script, payload)

        mb.popWidget(progressMessageBar)
        if resp:
            mb.pushMessage("Submitted",
                    "Productivity performance task submitted to Google Earth Engine.", level=0, duration=5)
            self.close()
        else:
            mb.pushMessage("Error", "Unable to submit productivity performance task to Google Earth Engine.", level=1, duration=5)

    def calculate_state(self, geojson, ndvi_dataset):
        payload = {'year_bl_start': self.perf_year_start.date().year(),
                   'year_bl_end': self.perf_year_end.date().year(),
                   'geojson': json.dumps(geojson),
                   'ndvi_gee_dataset': ndvi_dataset,
                   'task_name': self.task_name.text(),
                   'task_notes': self.task_notes.toPlainText()}

        progressMessageBar = mb.createMessage("Submitting productivity state task to Google Earth Engine...")
        spinner = QtGui.QLabel()
        movie = QtGui.QMovie(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'icons', 'spinner.gif'))
        spinner.setMovie(QtGui.QMovie())
        spinner.setAlignment(Qt.AlignLeft|Qt.AlignVCenter)
        progressMessageBar.layout().addWidget(spinner)
        mb.pushWidget(progressMessageBar, mb.INFO)
        movie.start()

        gee_script = self.scripts['productivity_state']['script id']

        resp = self.api.calculate(gee_script, payload)

        mb.popWidget(progressMessageBar)
        if resp:
            mb.pushMessage("Submitted",
                    "Productivity state task submitted to Google Earth Engine.", level=0, duration=5)
            self.close()
        else:
            mb.pushMessage("Error", "Unable to submit productivity state task to Google Earth Engine.", level=1, duration=5)
