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

        # TODO: Get list of admin0 from shapefile
        self.admin0.addItems(['Kenya',
            'Senegal',
            'Tanzania',
            'Uganda'])
        
        self.admin0.currentIndexChanged.connect(self.populate_admin1)

        self.buttonBox.accepted.connect(self.btn_ok)
        self.buttonBox.rejected.connect(self.btn_cancel)

    def populate_admin1(self):
        # TODO: Get list of admin1 from shapefile, populate admin1 on change of 
        # admin0 selection
        pass

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
