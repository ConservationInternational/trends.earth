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
from PyQt4.QtCore import QSettings, QDate, Qt, QTextCodec, QSize, QRect, QPoint, QAbstractTableModel, pyqtSignal, QRegExp

from qgis.utils import iface
mb = iface.messageBar()

from LDMP import log
from LDMP.calculate import DlgCalculateBase
from LDMP.gui.DlgCalculateLC import Ui_DlgCalculateLC
from LDMP.gui.DlgCalculateLCSetAggregation import Ui_DlgCalculateLCSetAggregation
from LDMP.api import run_script

# Number of classes in land cover dataset
NUM_CLASSES = 7

class VerticalLabel(QtGui.QLabel):
    def __init__(self, parent=None):
        super(VerticalLabel, self).__init__(parent)

    def paintEvent(self, paint_event):
        painter = QtGui.QPainter(self)
        painter.translate(self.sizeHint().width(), self.sizeHint().height())
        painter.rotate(270)
        painter.drawText(0, 0, self.text())

    def minimumSizeHint(self):
        s = QtGui.QLabel.minimumSizeHint(self)
        return QSize(s.height(), s.width())

    def sizeHint(self):
        s = QtGui.QLabel.sizeHint(self)
        return QSize(s.height(), s.width())


class TransMatrixEdit(QtGui.QLineEdit):
    def __init__(self, parent=None):
        super(TransMatrixEdit, self).__init__(parent)

        self.textChanged.connect(self.transition_cell_changed)

    def transition_cell_changed(self, text):
        if self.text() == '-':
            self.setStyleSheet('QLineEdit {background: #BB7757;} QLineEdit:hover {border: 1px solid gray; background: #BB7757;}')
        elif self.text() == '+':
            self.setStyleSheet('QLineEdit {background: #55B2A5;} QLineEdit:hover {border: 1px solid gray; background: #55B2A5;}')
        else:
            self.setStyleSheet('QLineEdit {background: #F6F6EA;} QLineEdit:hover {border: 1px solid gray; background: #F6F6EA;}')

    def focusInEvent(self, e):
        super(TransMatrixEdit, self).focusInEvent(e)
        self.selectAll()


class DlgCalculateLCBase(DlgCalculateBase):
    def __init__(self, parent=None):
        super(DlgCalculateLCBase, self).__init__(parent)

        self.dlg_remap = DlgCalculateLCSetAggregation(self)

    def showEvent(self, event):
        super(DlgCalculateLCBase, self).showEvent(event)

        self.setup_dialog()

        # Setup the aggregation table functions
        self.remap_default.toggled.connect(self.remap_default_toggled)
        self.remap_custom_file_browse.clicked.connect(self.open_remap_file)
        self.remap_custom_create.clicked.connect(self.remap_create)

        self.dlg_remap.remap_file_updated.connect(self.remap_file_update)
        self.dlg_remap.remap_matrix_changed.connect(self.remap_matrix_update)

        # Setup the class table so that the table is defined if a user uses the 
        # default and never accesses that dialog
        self.dlg_remap.setup_class_table()

    def remap_matrix_update(self, remap_matrix):
        self.remap_matrix = remap_matrix

    def remap_file_update(self, f):
        self.remap_custom_file.setText(f)

    def remap_create(self):
        if self.remap_custom_file.text():
            self.dlg_remap.setup_class_table(self.remap_custom_file.text())
        f = self.dlg_remap.exec_()
        if f:
            self.remap_file_update(f)

    def remap_default_toggled(self):
        if self.remap_custom.isChecked():
            self.dlg_remap.setup_class_table(self.remap_custom_file.text())
            self.remap_custom_create.setEnabled(True)
            self.remap_custom_file.setEnabled(True)
            self.remap_custom_file_browse.setEnabled(True)
            self.remap_label_new.setEnabled(True)
            self.remap_label_saved.setEnabled(True)
        else:
            self.dlg_remap.setup_class_table()
            self.remap_custom_create.setEnabled(False)
            self.remap_custom_file.setEnabled(False)
            self.remap_custom_file_browse.setEnabled(False)
            self.remap_label_new.setEnabled(False)
            self.remap_label_saved.setEnabled(False)

    def open_remap_file(self):
        f = QtGui.QFileDialog.getOpenFileName(self,
                                              self.tr('Select a land cover definition file'),
                                              QSettings().value("LDMP/lc_def_dir", None),
                                              self.tr('Land cover definition (*.json)'))
        if f:
            if os.access(f, os.R_OK):
                QSettings().setValue("LDMP/lc_def_dir", os.path.dirname(f))
            else:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Cannot read {}. Choose a different file.".format(f), None))

        ret = self.dlg_remap.setup_class_table(f)

        if ret:
            self.remap_custom_file.setText(f)

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateLCBase, self).btn_calculate()
        if not ret:
            return

        return True

class DlgCalculateLC(DlgCalculateLCBase, Ui_DlgCalculateLC):
    def __init__(self, parent=None):
        super(DlgCalculateLC, self).__init__(parent)

        self.setupUi(self)

        # Extract trans_matrix from the QTableWidget
        self.trans_matrix_default = [ 0,  1, -1, -1, -1, -1, -1, # forest
                                      1,  0,  1, -1, -1, -1, -1, # grassland
                                      1, -1,  0, -1, -1, -1, -1, # cropland
                                     -1, -1, -1,  0, -1, -1, -1, # wetland
                                      1,  1,  1,  1,  0, -1, -1, # artificial areas
                                      1,  1,  1,  1,  1,  0, -1, # bare land
                                      1,  1,  0,  0,  0,  0,  0] # water body
        for row in range(0, self.transMatrix.rowCount()):
            for col in range(0, self.transMatrix.columnCount()):
                line_edit = TransMatrixEdit()
                line_edit.setValidator(QtGui.QRegExpValidator(QRegExp("[-0+]")))
                line_edit.setAlignment(Qt.AlignHCenter)
                self.transMatrix.setCellWidget(row, col, line_edit)
        self.trans_matrix_set()

        # Setup the verical label for the rows of the table
        label_lc_baseline_year = VerticalLabel(self.TransitionMatrixTab)
        label_lc_baseline_year.setText(QtGui.QApplication.translate("DlgCalculateLC", "Land cover in baseline year ", None))
        sizePolicy = QtGui.QSizePolicy(QtGui.QSizePolicy.Preferred, QtGui.QSizePolicy.Minimum)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.label_lc_target_year.sizePolicy().hasHeightForWidth())
        label_lc_baseline_year.setSizePolicy(sizePolicy)
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        label_lc_baseline_year.setFont(font)
        self.lc_trans_table_layout.addWidget(label_lc_baseline_year, 1, 0, 1, 1, Qt.AlignCenter)

        self.transMatrix.setStyleSheet('QTableWidget {border: 0px;}')
        self.transMatrix.horizontalHeader().setStyleSheet('QHeaderView::section {background-color: white;border: 0px;}')
        self.transMatrix.verticalHeader().setStyleSheet('QHeaderView::section {background-color: white;border: 0px;}')

        self.transMatrix.horizontalHeader().setResizeMode(QtGui.QHeaderView.Stretch)
        self.transMatrix.verticalHeader().setResizeMode(QtGui.QHeaderView.Stretch)

        self.btn_transmatrix_reset.clicked.connect(self.trans_matrix_set)
        self.btn_transmatrix_loadfile.clicked.connect(self.trans_matrix_loadfile)
        self.btn_transmatrix_savefile.clicked.connect(self.trans_matrix_savefile)

        self.legend_deg.setStyleSheet('QLineEdit {background: #BB7757;} QLineEdit:hover {border: 1px solid gray; background: #BB7757;}')
        self.legend_imp.setStyleSheet('QLineEdit {background: #55B2A5;} QLineEdit:hover {border: 1px solid gray; background: #55B2A5;}')
        self.legend_stable.setStyleSheet('QLineEdit {background: #F6F6EA;} QLineEdit:hover {border: 1px solid gray; background: #F6F6EA;}')

    def trans_matrix_loadfile(self):
        f = QtGui.QFileDialog.getOpenFileName(self,
                                              self.tr('Select a transition matrix definition file'),
                                              QSettings().value("LDMP/lc_def_dir", None),
                                              self.tr('Transition matrix definition (*.json)'))
        if f:
            if os.access(f, os.R_OK):
                QSettings().setValue("LDMP/lc_def_dir", os.path.dirname(f))
            else:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Cannot read {}. Choose a different file.".format(f), None))
        else:
            return None

        with open(f) as matrix_file:
            matrix = json.load(matrix_file)
        
        flag = False
        if isinstance(matrix, list) and len(matrix) == NUM_CLASSES*NUM_CLASSES:
            flag = self.trans_matrix_set(matrix)

        if not flag:
            QtGui.QMessageBox.critical(None,
                                       QtGui.QApplication.translate('DlgCalculateLC', "Error"),
                                       QtGui.QApplication.translate('DlgCalculateLC',
                                                                    "{} does not appear to contain a valid matrix definition.".format(f)))
            return None
        else:
            return True

    def trans_matrix_savefile(self):
        f = QtGui.QFileDialog.getSaveFileName(self,
                                              QtGui.QApplication.translate('DlgCalculateLC',
                                                                           'Choose where to save this transition matrix definition'),
                                              QSettings().value("LDMP/lc_def_dir", None),
                                              QtGui.QApplication.translate('DlgCalculateLC',
                                                                           'Transition matrix definition (*.json)'))
        if f:
            if os.access(os.path.dirname(f), os.W_OK):
                QSettings().setValue("LDMP/lc_def_dir", os.path.dirname(f))
            else:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Cannot write to {}. Choose a different file.".format(f), None))
                return

            matrix = self.trans_matrix_get()
            with open(f, 'w') as outfile:
                json.dump(matrix, outfile, sort_keys=True, indent=4, separators=(',', ': '))

    def trans_matrix_set(self, matrix=None):
        if not matrix:
            matrix = self.trans_matrix_default
        for row in range(0, self.transMatrix.rowCount()):
            for col in range(0, self.transMatrix.columnCount()):
                # Matrix is actually a list of length NUM_CLASSES * NUM_CLASSES
                val = matrix[NUM_CLASSES * row + col]
                if val == 0:
                    val_str = '0'
                elif val == -1:
                    val_str = '-'
                elif val == 1:
                    val_str = '+'
                else:
                    log('unrecognized value "{}" when setting transition matrix'.format(val))
                    return False
                self.transMatrix.cellWidget(row, col).setText(val_str)
        return True

    def trans_matrix_get(self):
        # Extract trans_matrix from the QTableWidget
        trans_matrix = []
        for row in range(0, self.transMatrix.rowCount()):
            for col in range(0, self.transMatrix.columnCount()):
                val = self.transMatrix.cellWidget(row, col).text()
                if val == "" or val == "0":
                    val = 0
                elif val == "-":
                    val = -1
                elif val == "+":
                    val = 1
                else:
                    log('unrecognized value "{}" when getting transition matrix'.format(val))
                    raise ValueError('unrecognized value "{}" in transition matrix'.format(val))
                trans_matrix.append(val)
        return trans_matrix

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateLC, self).btn_calculate()
        if not ret:
            return

        self.close()

        payload = {'year_bl_start': self.year_bl_start.date().year(),
                   'year_bl_end': self.year_bl_end.date().year(),
                   'year_target': self.year_target.date().year(),
                   'geojson': json.dumps(self.bbox),
                   'trans_matrix': self.trans_matrix_get(),
                   'remap_matrix': self.remap_matrix,
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


class LCAggTableModel(QAbstractTableModel):
    def __init__(self, datain, parent=None, *args):
        QAbstractTableModel.__init__(self, parent, *args)
        self.classes = datain

        # Column names as tuples with json name in [0], pretty name in [1]
        # Note that the columns with json names set to to INVALID aren't loaded
        # into the shell, but shown from a widget.
        colname_tuples = [('Initial_Label', QtGui.QApplication.translate('DlgCalculateLCSetAggregation', 'Input cover class')),
                          ('Final_Label', QtGui.QApplication.translate('DlgCalculateLCSetAggregation', 'Output cover class'))]
        self.colnames_json = [x[0] for x in colname_tuples]
        self.colnames_pretty = [x[1] for x in colname_tuples]

    def rowCount(self, parent):
        return len(self.classes)

    def columnCount(self, parent):
        return len(self.colnames_json)

    def data(self, index, role):
        if not index.isValid():
            return None
        elif role != Qt.DisplayRole:
            return None
        return self.classes[index.row()].get(self.colnames_json[index.column()], '')

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.colnames_pretty[section]
        return QAbstractTableModel.headerData(self, section, orientation, role)


class DlgCalculateLCSetAggregation(QtGui.QDialog, Ui_DlgCalculateLCSetAggregation):
    remap_file_updated = pyqtSignal(str)
    remap_matrix_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super(DlgCalculateLCSetAggregation, self).__init__(parent)

        self.setupUi(self)

        self.final_classes = {'Forest': 1,
                              'Grassland': 2,
                              'Cropland': 3,
                              'Wetland': 4,
                              'Artificial area': 5,
                              'Bare land': 6,
                              'Water body': 7}

        self.btn_save.clicked.connect(self.btn_save_pressed)
        self.btn_reset.clicked.connect(self.reset_class_table)

    def btn_save_pressed(self):
        f = QtGui.QFileDialog.getSaveFileName(self,
                                              QtGui.QApplication.translate('DlgCalculateLCSetAggregation',
                                                                           'Choose where to save this land cover definition'),
                                              QSettings().value("LDMP/lc_def_dir", None),
                                              QtGui.QApplication.translate('DlgCalculateLCSetAggregation',
                                                                           'Land cover definition (*.json)'))
        if f:
            if os.access(os.path.dirname(f), os.W_OK):
                QSettings().setValue("LDMP/lc_def_dir", os.path.dirname(f))
            else:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Cannot write to {}. Choose a different file.".format(f), None))
                return

            class_def = self.get_definition()
            with open(f, 'w') as outfile:
                json.dump(class_def, outfile, sort_keys=True, indent=4, separators=(',', ': '))

            self.update_remap_matrix()

            # Emit the filename so it can be used to update the filename field 
            # in the parent dialog
            self.lc_def_file_updated.emit(f)

            self.close()

    def update_remap_matrix(self):
        '''Returns a list describing how to aggregate the land cover data'''
        out = [[], []]
        for row in range(0, len(self.classes)):
            initial_label = self.remap_view.model().index(row, 0).data()
            initial_code = [i['Initial_Code'] for i in self.classes if i['Initial_Label'] == initial_label]
            if len(initial_code) > 1:
                raise ValueError("more than one match found for initial label {}".format(initial_label))
            initial_code = initial_code[0]

            # Get the currently assigned label for this code
            label_widget_index = self.remap_view.model().index(row, 1)
            label_widget = self.remap_view.indexWidget(label_widget_index)
            final_code = self.final_classes[label_widget.currentText()]
            out[0].append(initial_code)
            out[1].append(final_code)
        self.remap_matrix_changed.emit(out)

    def get_definition(self):
        '''Returns the chosen land cover definition as a dictionary'''
        out = []
        for row in range(0, len(self.classes)):
            this_out = {}
            initial_label = self.remap_view.model().index(row, 0).data()
            this_out['Initial_Label'] = initial_label
            initial_code = [i['Initial_Code'] for i in self.classes if i['Initial_Label'] == initial_label]
            if len(initial_code) > 1:
                raise ValueError("more than one match found for initial label {}".format(initial_label))
            this_out['Initial_Code'] = initial_code[0]
            # Get the currently assigned label for this code
            label_widget_index = self.remap_view.model().index(row, 1)
            label_widget = self.remap_view.indexWidget(label_widget_index)
            this_out['Final_Label'] = label_widget.currentText()
            this_out['Final_Code'] = self.final_classes[this_out['Final_Label']]
            out.append(this_out)
        # Sort output by initial code
        out = sorted(out, key=lambda k: k['Initial_Code'])
        return out

    def setup_class_table(self, f=None):
        default_class_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), 
                                          'data', 'land_cover_classes.json')
        if not f:
            f = default_class_file
        with open(f) as class_file:
            classes = json.load(class_file)
        
        if (not isinstance(classes, list)
                or not len(classes) > 0
                or not isinstance(classes[0], dict)
                or not classes[0].has_key('Initial_Code')
                or not classes[0].has_key('Initial_Label')
                or not classes[0].has_key('Final_Code')
                or not classes[0].has_key('Final_Label')):

            QtGui.QMessageBox.critical(None,
                                       QtGui.QApplication.translate('DlgCalculateLCSetAggregation', "Error"),
                                       QtGui.QApplication.translate('DlgCalculateLCSetAggregation',
                                                                    "{} does not appear to contain a valid class definition.".format(f)))
            return None
        else:
            self.classes = classes

        log('Loaded class definition from {}'.format(f))

        table_model = LCAggTableModel(self.classes, self)
        proxy_model = QtGui.QSortFilterProxyModel()
        proxy_model.setSourceModel(table_model)
        self.remap_view.setModel(proxy_model)

        # Add selector in cell
        for row in range(0, len(self.classes)):
            lc_classes = QtGui.QComboBox()
            # Add the classes in order of their codes
            lc_classes.addItems(sorted(self.final_classes.keys(), key=lambda k: self.final_classes[k]))
            ind = lc_classes.findText(self.classes[row]['Final_Label'])
            if ind != -1:
                lc_classes.setCurrentIndex(ind)
            self.remap_view.setIndexWidget(proxy_model.index(row, 1), lc_classes)

        self.remap_view.setSelectionBehavior(QtGui.QAbstractItemView.SelectRows)
        self.remap_view.setColumnWidth(0, 500)
        self.remap_view.horizontalHeader().setStretchLastSection(True)

        # Load and emit the new remap matrix
        self.update_remap_matrix()

        return True

    def reset_class_table(self):
        self.setup_class_table()
        self.lc_def_file_updated.emit(None)
