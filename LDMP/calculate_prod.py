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
from qgis.core import QgsJSONUtils
mb = iface.messageBar()

from LDMP import log

from LDMP.gui.DlgCalculateProd import Ui_DlgCalculateProd as UiDialog

from api import API

from . import read_json

def setup_area_selection(dlg):
    dlg.admin_0 = json.loads(QSettings().value('LDMP/admin_0', None))
    dlg.admin_1 = json.loads(QSettings().value('LDMP/admin_1', None))

    if not dlg.admin_0 or not dlg.admin_1:
        raise ValueError('Admin boundaries not available')
    dlg.area_admin_0.addItems(sorted(dlg.admin_0.keys()))
    dlg.populate_admin_1()
    
    dlg.area_admin_0.currentIndexChanged.connect(dlg.populate_admin_1)

    #dlg.data_folder_browse.clicked.connect(dlg.open_data_folder_browse)
    dlg.area_fromfile_browse.clicked.connect(dlg.open_shp_browse)
    dlg.area_admin.toggled.connect(dlg.area_admin_toggle)
    dlg.area_fromfile.toggled.connect(dlg.area_fromfile_toggle)
    return

def load_admin_polys(dlg):
    adm0_a3 = dlg.admin_0[dlg.area_admin_0.currentText()]['ADM0_A3']
    if not dlg.area_admin_1.currentText() or dlg.area_admin_1.currentText() == 'All regions':
        admin_0_polys = read_json('admin_0_polys.json.gz')
        return admin_0_polys[adm0_a3]['geojson']
    else:
        admin_1_polys = read_json('admin_1_polys.json.gz')
        admin_1_code = dlg.admin_1[adm0_a3][dlg.area_admin_1.currentText()]
        return admin_1_polys[admin_1_code]['geojson']

class DlgCalculateProd(QtGui.QDialog, UiDialog):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgCalculateProd, self).__init__(parent)

        self.api = API()

        self.setupUi(self)

        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                               'data', 'scripts.json')) as script_file:
            self.scripts = json.load(script_file)['productivity_trajectory']
            
        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                               'data', 'gee_datasets.json')) as datasets_file:
            self.datasets = json.load(datasets_file)

        self.start_year_climate = 0
        self.end_year_climate = 9999

        self.dataset_ndvi.addItems(self.datasets['NDVI'].keys())
        self.dataset_ndvi_changed()

        self.traj_indic.addItems(self.scripts.keys())
        self.traj_indic.currentIndexChanged.connect(self.traj_indic_changed)

        setup_area_selection(self)

        self.dataset_ndvi.currentIndexChanged.connect(self.dataset_ndvi_changed)

        self.indic_select_traj.stateChanged.connect(self.indic_select_traj_changed)
        self.indic_select_perf.stateChanged.connect(self.indic_select_perf_changed)
        self.indic_select_state.stateChanged.connect(self.indic_select_state_changed)

        self.indic_select_traj_changed()
        self.indic_select_perf_changed()
        self.indic_select_state_changed()

        self.button_calculate.clicked.connect(self.btn_calculate)
        self.button_prev.clicked.connect(self.tab_back)
        self.button_next.clicked.connect(self.tab_forward)

        # Start on first tab so button_prev and calculate should be disabled
        self.button_prev.setEnabled(False)
        self.button_calculate.setEnabled(False)
        self.TabBox.currentChanged.connect(self.tab_changed)

    def tab_back(self):
        if self.TabBox.currentIndex() - 1 >= 0:
            self.TabBox.setCurrentIndex(self.TabBox.currentIndex() - 1)

    def tab_forward(self):
        if self.TabBox.currentIndex() + 1 < self.TabBox.count():
            self.TabBox.setCurrentIndex(self.TabBox.currentIndex() + 1)

    def tab_changed(self):
        if self.TabBox.currentIndex() > 0:
            self.button_prev.setEnabled(True)
        else:
            self.button_prev.setEnabled(False)

        if self.TabBox.currentIndex() < (self.TabBox.count() - 1):
            self.button_next.setEnabled(True)
        else:
            self.button_next.setEnabled(False)

        if self.TabBox.currentIndex() == (self.TabBox.count() - 1):
            self.button_calculate.setEnabled(True)
        else:
            self.button_calculate.setEnabled(False)


    def indic_select_traj_changed(self):
        if self.indic_select_traj.isChecked():
            self.TrajectoryTab.setEnabled(True)
        else:
            self.TrajectoryTab.setEnabled(False)

    def indic_select_perf_changed(self):
        if self.indic_select_traj.isChecked():
            self.PerformanceTab.setEnabled(True)
        else:
            self.PerformanceTab.setEnabled(False)

    def indic_select_state_changed(self):
        if self.indic_select_traj.isChecked():
            self.StateTab.setEnabled(True)
        else:
            self.StateTab.setEnabled(False)

    def traj_indic_changed(self):
        self.dataset_climate_update()

    def dataset_climate_update(self):
        self.traj_climate.clear()
        climate_types = self.scripts[self.traj_indic.currentText()]['climate types']
        for climate_type in climate_types:
            self.traj_climate.addItems(self.datasets[climate_type].keys())

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
            
    #def runon_toggle(self):
    #    if self.runon_local.isChecked():
    #        self.data_folder_label.setEnabled(True)
    #        self.data_folder_path.setEnabled(True)
    #        self.data_folder_browse.setEnabled(True)
    #        self.add_to_map.setEnabled(True)
    #        self.add_to_map_label.setEnabled(True)
    #    else:
    #        self.data_folder_label.setEnabled(False)
    #        self.data_folder_path.setEnabled(False)
    #        self.data_folder_browse.setEnabled(False)
    #        self.add_to_map.setEnabled(False)
    #        self.add_to_map_label.setEnabled(False)

    def area_admin_toggle(self):
        if self.area_admin.isChecked():
            self.area_admin_0.setEnabled(True)
            self.area_admin_1.setEnabled(True)
        else:
            self.area_admin_0.setEnabled(False)
            self.area_admin_1.setEnabled(False)

    def area_fromfile_toggle(self):
        if self.area_fromfile.isChecked():
            self.area_fromfile_file.setEnabled(True)
            self.area_fromfile_browse.setEnabled(True)
        else:
            self.area_fromfile_file.setEnabled(False)
            self.area_fromfile_browse.setEnabled(False)

    #def open_data_folder_browse(self):
    #    data_folder = QtGui.QFileDialog.getExistingDirectory()
    #    self.data_folder_path.setText(data_folder)

    def open_shp_browse(self):
        shpfile = QtGui.QFileDialog.getOpenFileName()
        self.area_fromfile_file.setText(shpfile)

    def populate_admin_1(self):
        adm0_a3 = self.admin_0[self.area_admin_0.currentText()]['ADM0_A3']
        self.area_admin_1.clear()
        self.area_admin_1.addItems(['All regions'])
        self.area_admin_1.addItems(sorted(self.admin_1[adm0_a3].keys()))

    def btn_cancel(self):
        self.close()

    def btn_calculate(self):
        if self.area_admin.isChecked():
            # Get geojson for chosen bounds
            if not self.area_admin_0.currentText():
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                        self.tr("Choose a first level administrative boundary."), None)
            geojson = load_admin_polys(self)
        if not self.indic_select_traj.isChecked() or self.indic_select_perf.isChecked() or self.indic_select_state.isChecked():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("Choose one or more indicators to calculate."), None)
            return

        #if self.runon_gee.isChecked():
        # TODO: check before submission whether this payload and script ID has 
        # been sent recently - or even whether there are results already 
        # available for it. Notify the user if this is the case to prevent, or 
        # at least reduce, repeated identical submissions.
        #
        ndvi_dataset = self.datasets['NDVI'][self.dataset_ndvi.currentText()]['GEE Dataset']

        # Calculate bounding box of input polygon and then convert back to 
        # geojson
        fields = QgsJSONUtils.stringToFields(json.dumps(geojson), QTextCodec.codecForName('UTF8'))
        features = QgsJSONUtils.stringToFeatureList(json.dumps(geojson), fields, QTextCodec.codecForName('UTF8'))
        if len(features) != 0:
            log("Found {} features in geojson - using first feature only.".format(len(features)), 2)
        bounding = json.loads(features[0].geometry().convexHull().exportToGeoJSON())

        if self.indic_select_traj.isChecked():
            self.calculate_trajectory(bounding, ndvi_dataset)

        if self.indic_select_perf.isChecked():
            self.calculate_performance(bounding, ndvi_dataset)

        if self.indic_select_state.isChecked():
            self.calculate_state(bounding, ndvi_dataset)
    
    def calculate_trajectory(self, geojson, ndvi_dataset):
        if self.traj_climate.currentText() != "":
            climate_gee_dataset = self.datasets['NDVI'][self.traj_climate.currentText()]['GEE Dataset']
        else:
            climate_gee_dataset = None

        payload = {'year_start': self.traj_year_start.date().year(),
                   'year_end': self.traj_year_end.date().year(),
                   'geojson': json.dumps(geojson),
                   'ndvi_gee_dataset': ndvi_dataset,
                   'climate_gee_dataset': climate_gee_dataset}
        payload.update(self.scripts[self.traj_indic.currentText()]['params'])

        progressMessageBar = mb.createMessage("Submitting trajectory task to Google Earth Engine...")
        spinner = QtGui.QLabel()
        movie = QtGui.QMovie(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'icons', 'spinner.gif'))
        spinner.setMovie(QtGui.QMovie())
        spinner.setAlignment(Qt.AlignLeft|Qt.AlignVCenter)
        progressMessageBar.layout().addWidget(spinner)
        mb.pushWidget(progressMessageBar, mb.INFO)
        movie.start()

        gee_script = self.scripts[self.traj_indic.currentText()]['script id']

        resp = self.api.calculate(gee_script, payload)

        mb.popWidget(progressMessageBar)
        if resp:
            mb.pushMessage("Submitted",
                    "Trajectory task submitted to Google Earth Engine.", level=0, duration=5)
            self.close()
        else:
            mb.pushMessage("Error", "Unable to submit trajectory task to Google Earth Engine.", level=1, duration=5)
