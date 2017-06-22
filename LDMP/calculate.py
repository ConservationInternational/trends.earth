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

from PyQt4 import QtGui, uic
from PyQt4.QtCore import QSettings, QDate

from DlgCalculate import Ui_DlgCalculate as UiDialog

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

    dlg.data_folder_browse.clicked.connect(dlg.open_data_folder_browse)
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

class DlgCalculate(QtGui.QDialog, UiDialog):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgCalculate, self).__init__(parent)

        self.api = API()

        self.setupUi(self)

        # GEE needs to know resolutions in meters, but using m and km is more 
        # friendly to users. This key will convert the user input into meters 
        # for GEE.
        self.resolution_key = {'250 m': 250,
                               '500 m': 500,
                               '1 km': 1000,
                               '2 km': 2000,
                               '4 km':4000,
                               '8 km':8000,
                               '16 km': 16000,
                               '32 km': 32000}

        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'data', 'scripts.json')) as script_file:
            scripts = json.load(script_file)
            self.scripts = scripts['calculate']
        self.calculation.addItems(sorted(self.scripts.keys()))

        self.dataset.addItems(sorted(['AVHRR', 'MODIS']))
        self.dataset_changed()

        setup_area_selection(self)

        self.dataset.currentIndexChanged.connect(self.dataset_changed)
        self.buttonBox.accepted.connect(self.btn_ok)
        self.buttonBox.rejected.connect(self.btn_cancel)
        self.runon_gee.toggled.connect(self.runon_toggle)

    def dataset_changed(self):
        if self.dataset.currentText() == 'AVHRR':
            self.sp_resolution.clear()
            self.sp_resolution.addItems(['8 km', '16 km', '32 km'])
            self.year_start.setMinimumDate(QDate(1982, 1, 1))
            self.year_start.setMaximumDate(QDate(2010, 1, 1))
            self.year_end.setMinimumDate(QDate(1987, 12, 31))
            self.year_end.setMaximumDate(QDate(2015, 12, 31))
        elif self.dataset.currentText() == 'MODIS':
            self.sp_resolution.clear()
            self.sp_resolution.addItems(['250 m', '500 m', '1 km', '2 km', '4 km', '8 km', '16 km', '32 km'])
            self.year_start.setMinimumDate(QDate(2001, 1, 1))
            self.year_start.setMaximumDate(QDate(2010, 1, 1))
            self.year_end.setMinimumDate(QDate(2005, 12, 31))
            self.year_end.setMaximumDate(QDate(2015, 12, 31))
        else:
            raise ValueError('Unknown dataset')
            
    def runon_toggle(self):
        if self.runon_local.isChecked():
            self.data_folder_label.setEnabled(True)
            self.data_folder_path.setEnabled(True)
            self.data_folder_browse.setEnabled(True)
            self.add_to_map.setEnabled(True)
            self.add_to_map_label.setEnabled(True)
        else:
            self.data_folder_label.setEnabled(False)
            self.data_folder_path.setEnabled(False)
            self.data_folder_browse.setEnabled(False)
            self.add_to_map.setEnabled(False)
            self.add_to_map_label.setEnabled(False)

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

    def open_data_folder_browse(self):
        data_folder = QtGui.QFileDialog.getExistingDirectory()
        self.data_folder_path.setText(data_folder)

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

    def btn_ok(self):
        if self.area_admin.isChecked():
            # Get geojson for chosen bounds
            if not self.area_admin_0.currentText():
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                        self.tr("Choose a first level administrative boundary."), None)
            geojson = load_admin_polys(self)
        if not self.calculation.currentText():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("Choose a calculation to run."), None)
            return

        gee_script = self.scripts[self.calculation.currentText()]['id']

        payload = {'geojson': geojson,
                   'dataset': self.dataset.currentText(),
                   'year_start': self.year_start.date().year(),
                   'year_end': self.year_end.date().year(),
                   'resolution': self.resolution_key[self.sp_resolution.currentText()]}

        # TODO: check before submission whether this payload and script ID has 
        # been sent recently - or even whether there are results already 
        # available for it. Notify the user if this is the case to prevent, or 
        # at least reduce, repeated identical submissions.
        
        if self.runon_gee.isChecked():
            resp = self.api.calculate(gee_script, payload)
            QtGui.QMessageBox.information(None, self.tr("Success"), self.tr("Task submitted to Google Earth Engine."), None)
            self.close()
        else:
            QtGui.QMessageBox.Critical(None, self.tr("Coming soon!"), self.tr("Support for local processing coming soon!"), None)
