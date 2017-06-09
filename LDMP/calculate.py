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

from PyQt4 import QtGui, uic

from PyQt4.QtCore import QSettings

from DlgCalculate import Ui_DlgCalculate as UiDialog

from api import API

class DlgCalculate(QtGui.QDialog, UiDialog):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgCalculate, self).__init__(parent)

        self.api = API()

        self.setupUi(self)

        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'data', 'scripts.json')) as script_file:
            scripts = json.load(script_file)
        self.calc_scripts = [x['scripts'] for x in scripts if x['tool'] == 'calculate'][0]
        self.calculation.addItems([x['name'] for x in self.calc_scripts])

        self.admin0 = json.loads(QSettings().value('LDMP/admin0', None))
        self.admin1 = json.loads(QSettings().value('LDMP/admin1', None))
        if not self.admin0 or not self.admin1:
            raise ValueError('Admin boundaries not available')
        self.projarea_admin0.addItems(sorted(self.admin0.keys()))
        self.populate_admin1()
        
        self.projarea_admin0.currentIndexChanged.connect(self.populate_admin1)

        self.buttonBox.accepted.connect(self.btn_ok)
        self.buttonBox.rejected.connect(self.btn_cancel)
        self.shapefile_browse.clicked.connect(self.open_shp_browse)
        self.projarea_admin.toggled.connect(self.projarea_admin_toggle)
        self.projarea_shp.toggled.connect(self.projarea_shp_toggle)

    def projarea_admin_toggle(self):
        if self.projarea_admin.isChecked():
            self.projarea_admin0.setEnabled(True)
            self.projarea_admin1.setEnabled(True)
        else:
            self.projarea_admin0.setEnabled(False)
            self.projarea_admin1.setEnabled(False)

    def projarea_shp_toggle(self):
        if self.projarea_shp.isChecked():
            self.shapefile.setEnabled(True)
            self.shapefile_browse.setEnabled(True)
        else:
            self.shapefile.setEnabled(False)
            self.shapefile_browse.setEnabled(False)

    def open_shp_browse(self):
        shpfile = QtGui.QFileDialog.getOpenFileName()
        self.shapefile.setText(shpfile)

    def populate_admin1(self):
        adm0_a3 = self.admin0[self.projarea_admin0.currentText()]['ADM0_A3']
        self.projarea_admin1.clear()
        self.projarea_admin1.addItems(['All regions'])
        self.projarea_admin1.addItems([x['NAME'] for x in self.admin1 if x['ADM0_A3'] == adm0_a3])

    def btn_cancel(self):
        self.close()

    def btn_ok(self):
        if self.projarea_admin.isChecked():
            if not self.projarea_admin0.currentText()():
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                        self.tr("Choose a first level administrative boundary."), None)
        if not self.calculation.currentText()():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("Choose a calculation to run."), None)

        # Validate chosen dates
        asdf
        api.calculate(self.calculation.currentText())
