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

from PyQt4 import QtGui
from PyQt4.QtCore import QSettings, QTextCodec

from qgis.core import QgsGeometry, QgsJSONUtils, QgsVectorLayer, QgsCoordinateTransform, QgsCoordinateReferenceSystem

from LDMP import read_json, log
from LDMP.gui.DlgCalculate import Ui_DlgCalculate as UiDialog

class DlgCalculate(QtGui.QDialog, UiDialog):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgCalculate, self).__init__(parent)

        self.setupUi(self)

        self.dlg_calculate_prod = DlgCalculateProd()
        self.dlg_calculate_lc = DlgCalculateLC()

        self.btn_prod.clicked.connect(self.btn_prod_clicked)
        self.btn_lc.clicked.connect(self.btn_lc_clicked)
        self.btn_soc.clicked.connect(self.btn_soc_clicked)

    def btn_prod_clicked(self):
        self.close()
        result = self.dlg_calculate_prod.exec_()

    def btn_lc_clicked(self):
        self.close()
        result = self.dlg_calculate_lc.exec_()

    def btn_soc_clicked(self):
        QtGui.QMessageBox.critical(None, self.tr("Error"),
                self.tr("SOC indicator calculation coming soon!"), None)

class DlgCalculateBase(QtGui.QDialog):
    """Base class for individual indicator calculate dialogs"""
    def __init__(self, parent=None):
        super(DlgCalculateBase, self).__init__(parent)
        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                               'data', 'scripts.json')) as script_file:
            self.scripts = json.load(script_file)
            
        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                               'data', 'gee_datasets.json')) as datasets_file:
            self.datasets = json.load(datasets_file)

    def setup_dialog(self):
        self.button_calculate.clicked.connect(self.btn_calculate)
        self.button_prev.clicked.connect(self.tab_back)
        self.button_next.clicked.connect(self.tab_forward)

        # Start on first tab so button_prev and calculate should be disabled
        self.button_prev.setEnabled(False)
        self.button_calculate.setEnabled(False)
        self.TabBox.currentChanged.connect(self.tab_changed)

        self.setup_area_selection()

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

    def btn_cancel(self):
        self.close()

    def setup_area_selection(self):
        self.admin_0 = json.loads(QSettings().value('LDMP/admin_0', None))
        self.admin_1 = json.loads(QSettings().value('LDMP/admin_1', None))

        if not self.admin_0 or not self.admin_1:
            raise ValueError('Admin boundaries not available')
        self.area_admin_0.addItems(sorted(self.admin_0.keys()))
        self.populate_admin_1()
        
        self.area_admin_0.currentIndexChanged.connect(self.populate_admin_1)

        self.area_fromfile_browse.clicked.connect(self.open_shp_browse)
        self.area_admin.toggled.connect(self.area_admin_toggle)
        self.area_fromfile.toggled.connect(self.area_fromfile_toggle)

    def load_admin_polys(self):
        adm0_a3 = self.admin_0[self.area_admin_0.currentText()]['ADM0_A3']
        if not self.area_admin_1.currentText() or self.area_admin_1.currentText() == 'All regions':
            admin_0_polys = read_json('admin_0_polys.json.gz')
            if not admin_0_polys:
                return None
            else:
                return admin_0_polys[adm0_a3]['geojson']
        else:
            admin_1_polys = read_json('admin_1_polys.json.gz')
            if not admin_1_polys:
                return None
            else:
                admin_1_code = self.admin_1[adm0_a3][self.area_admin_1.currentText()]
                return admin_1_polys[admin_1_code]['geojson']

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

    def btn_calculate(self):
        if self.area_admin.isChecked():
            if not self.area_admin_0.currentText():
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                        self.tr("Choose a first level administrative boundary."), None)
                return False
            self.button_calculate.setEnabled(False)
            geojson = self.load_admin_polys()
            self.button_calculate.setEnabled(True)
            if not geojson:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                        self.tr("Unable to load administrative boundaries."), None)
                return False
        else:
            if not self.area_fromfile_file.text():
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                        self.tr("Choose a file to define the area of interest."), None)
                return False
            layer = QgsVectorLayer(self.area_fromfile_file.text(), 'calculation boundary', 'ogr')
            crs_source = layer.crs()
            crs_dest = QgsCoordinateReferenceSystem(4326)
            extent = layer.extent()
            extent_transformed = QgsCoordinateTransform(crs_source, crs_dest).transform(extent)
            geojson = json.loads(QgsGeometry.fromRect(extent_transformed).exportToGeoJSON())

        # Calculate bounding box of input polygon and then convert back to 
        # geojson
        fields = QgsJSONUtils.stringToFields(json.dumps(geojson), QTextCodec.codecForName('UTF8'))
        features = QgsJSONUtils.stringToFeatureList(json.dumps(geojson), fields, QTextCodec.codecForName('UTF8'))
        if len(features) > 1:
            log("Found {} features in geojson - using first feature only.".format(len(features)))
        #self.bbox = json.loads(features[0].geometry().convexHull().exportToGeoJSON())
        self.bbox = json.loads(QgsGeometry.fromRect(features[0].geometry().boundingBox()).exportToGeoJSON())

        return True

from LDMP.calculate_prod import DlgCalculateProd
from LDMP.calculate_lc import DlgCalculateLC
