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

from gui.DlgCalculateLC import Ui_DlgCalculateLC as UiDialog

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
    if not dlg.area_admin_1.currentText() == 'All regions':
        admin_0_polys = read_json('admin_0_polys.json.gz')
        return admin_0_polys[adm0_a3]['geojson']
    else:
        admin_1_polys = read_json('admin_1_polys.json.gz')
        admin_1_code = dlg.admin_1[adm0_a3][dlg.area_admin_1.currentText()]
        return admin_1_polys[admin_1_code]['geojson']

class DlgCalculateLC(QtGui.QDialog, UiDialog):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgCalculateLC, self).__init__(parent)

        self.api = API()

        self.setupUi(self)

        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                               'data', 'scripts.json')) as script_file:
            self.script = json.load(script_file)['land_cover']
            
        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                               'data', 'gee_datasets.json')) as datasets_file:
            self.datasets = json.load(datasets_file)

        setup_area_selection(self)

        self.button_calculate.clicked.connect(self.btn_calculate)
        self.button_prev.clicked.connect(self.tab_back)
        self.button_next.clicked.connect(self.tab_forward)

        # TODO: Rotate the column label on the transition matrix tab
        # label_pixmap = self.label_lc_baseline_year.pixmap()
        # rm = QtGui.QMatrix()
        # rm.rotate(90)
        # label_pixmap = label_pixmap.transformed(rm)
        # self.label_lc_baseline_year.setPixmap(pixmap)
        
        #TODO: Use setCellWidget to assign QLineEdit and validator to each item
        # Extract trans_matrix from the QTableWidget
        trans_matrix_default = [[0,   1,  1,  1, -1,  0],
                                [-1,  0, -1, -1, -1, -1],
                                [-1,  1,  0,  0, -1, -1],
                                [-1, -1, -1,  0, -1, -1],
                                [ 1,  1,  1,  1,  0,  0],
                                [ 1,  1,  1,  1, -1,  0]]
        for row in range(0, self.transMatrix.rowCount()):
            for col in range(0, self.transMatrix.columnCount()):
                line_edit = QtGui.QLineEdit()
                line_edit.setValidator(QtGui.QIntValidator(-1, 1))
                line_edit.setAlignment(Qt.AlignHCenter)
                line_edit.setText(str(trans_matrix_default[row][col]))
                #TODO: Get the prevention of empty cells working
                #line_edit.textChanged.connect(self.trans_matrix_text_changed)
                self.transMatrix.setCellWidget(row, col, line_edit)

        #self.transMatrix.currentItemChanged.connect(self.trans_matrix_current_item_changed)

        # Start on first tab so button_prev and calculate should be disabled
        self.button_prev.setEnabled(False)
        self.button_calculate.setEnabled(False)
        self.TabBox.currentChanged.connect(self.tab_changed)

    #TODO: Get the prevention of empty cells working
    # def trans_matrix_text_changed(text):
    #     if text not in ["-1", "0", "1"]:
    #         QtGui.QMessageBox.critical(None, self.tr("Error"),
    #                 self.tr("Enter -1 (degradation), 0 (stable), or 1 (improvement)."), None)
    #     self.transMatrix.setCurrentItem(current)

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

        #if self.runon_gee.isChecked():
        # TODO: check before submission whether this payload and script ID has 
        # been sent recently - or even whether there are results already 
        # available for it. Notify the user if this is the case to prevent, or 
        # at least reduce, repeated identical submissions.
        #

        # Calculate bounding box of input polygon and then convert back to 
        # geojson
        fields = QgsJSONUtils.stringToFields(json.dumps(geojson), QTextCodec.codecForName('UTF8'))
        features = QgsJSONUtils.stringToFeatureList(json.dumps(geojson), fields, QTextCodec.codecForName('UTF8'))
        if len(features) != 0:
            log("Found {} features in geojson - using first feature only.".format(len(features)), 2)
        bounding = json.loads(features[0].geometry().convexHull().exportToGeoJSON())

        # Extract trans_matrix from the QTableWidget
        trans_matrix = []
        for row in range(0, self.transMatrix.rowCount()):
            for col in range(0, self.transMatrix.columnCount()):
                val = self.transMatrix.cellWidget(row, col).text()
                if val == "":
                    val = 0
                else:
                    val = int(val)
                trans_matrix.append(val)

        payload = {'year_bl_start': self.year_bl_start.date().year(),
                   'year_bl_end': self.year_bl_end.date().year(),
                   'year_target': self.year_target.date().year(),
                   'geojson': json.dumps(bounding),
                   'trans_matrix': trans_matrix,
                   'task_name': self.task_name.text(),
                   'task_notes': self.task_notes.toPlainText()}

        progressMessageBar = mb.createMessage("Submitting land cover task to Google Earth Engine...")
        spinner = QtGui.QLabel()
        movie = QtGui.QMovie(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'icons', 'spinner.gif'))
        spinner.setMovie(QtGui.QMovie())
        spinner.setAlignment(Qt.AlignLeft|Qt.AlignVCenter)
        progressMessageBar.layout().addWidget(spinner)
        mb.pushWidget(progressMessageBar, mb.INFO)
        movie.start()

        gee_script = self.script['Land cover']['script id']

        resp = self.api.calculate(gee_script, payload)

        mb.popWidget(progressMessageBar)
        if resp:
            mb.pushMessage("Submitted",
                    "Land cover task submitted to Google Earth Engine.", level=0, duration=5)
            self.close()
        else:
            mb.pushMessage("Error", "Unable to submit land cover task to Google Earth Engine.", level=1, duration=5)
