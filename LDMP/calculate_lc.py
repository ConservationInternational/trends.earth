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
mb = iface.messageBar()

from LDMP import log
from LDMP.calculate import DlgCalculateBase
from LDMP.gui.DlgCalculateLC import Ui_DlgCalculateLC as UiDialog
from LDMP.api import run_script

class DlgCalculateLC(DlgCalculateBase, UiDialog):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgCalculateLC, self).__init__(parent)

        self.setupUi(self)

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

        self.setup_dialog()

    #TODO: Get the prevention of empty cells working
    # def trans_matrix_text_changed(text):
    #     if text not in ["-1", "0", "1"]:
    #         QtGui.QMessageBox.critical(None, self.tr("Error"),
    #                 self.tr("Enter -1 (degradation), 0 (stable), or 1 (improvement)."), None)
    #     self.transMatrix.setCurrentItem(current)

    def btn_calculate(self):
        self.close()

        # Note that the super class has several tests in it - if they fail it 
        # returns False, which would mean this function should stop execution 
        # as well.
        ret = super(DlgCalculateLC, self).btn_calculate()
        if not ret:
            return

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
                   'geojson': json.dumps(self.bbox),
                   'trans_matrix': trans_matrix,
                   'task_name': self.task_name.text(),
                   'task_notes': self.task_notes.toPlainText()}

        gee_script = self.scripts['land_cover']['Land cover']['script id']

        resp = run_script(gee_script, payload)

        if resp:
            mb.pushMessage(QtGui.QApplication.translate("LDMP", "Submitted"), 
                    QtGui.QApplication.translate("LDMP", "Land cover task submitted to Google Earth Engine."),
                    level=0, duration=5)
        else:
            mb.pushMessage(QtGui.QApplication.translate("LDMP", "Error"), 
                    QtGui.QApplication.translate("LDMP", "Unable to submit land cover task to Google Earth Engine."),
                    level=0, duration=5)
