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

from PyQt4.QtCore import QSettings

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

        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'data', 'scripts.json')) as script_file:
            scripts = json.load(script_file)
            self.scripts = [x['scripts'] for x in scripts if x['tool'] == 'calculate'][0]
        self.calculation.addItems(sorted(self.scripts.keys()))

        setup_area_selection(self)

        self.buttonBox.accepted.connect(self.btn_ok)
        self.buttonBox.rejected.connect(self.btn_cancel)

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

        gee_script = self.scripts[self.calculation.currentText()]['script']

        # TODO:Validate chosen dates
        
        resp = self.api.calculate(gee_script, {'geojson': geojson})
        QtGui.QMessageBox.information(None, self.tr("Success"), self.tr("Task submitted to Google Earth Engine."), None)
        self.close()
