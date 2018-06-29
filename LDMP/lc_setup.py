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
        email                : trends.earth@conservation.org
 ***************************************************************************/
"""

import os
import json

from PyQt4 import QtGui
from PyQt4.QtCore import QSettings, QDate, Qt, QSize, QAbstractTableModel, \
    QRegExp, QPyNullVariant

from qgis.utils import iface
mb = iface.messageBar()

from LDMP import log
from LDMP.gui.DlgCalculateLCSetAggregation import Ui_DlgCalculateLCSetAggregation
from LDMP.gui.WidgetLCDefineDegradation import Ui_WidgetLCDefineDegradation
from LDMP.gui.WidgetLCSetup import Ui_WidgetLCSetup


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, QPyNullVariant):
        return None
    raise TypeError("Type {} not serializable".format(type(obj)))


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
            self.setStyleSheet('QLineEdit {background: #AB2727;} QLineEdit:hover {border: 1px solid gray; background: #AB2727;}')
        elif self.text() == '+':
            self.setStyleSheet('QLineEdit {background: #45A146;} QLineEdit:hover {border: 1px solid gray; background: #45A146;}')
        else:
            self.setStyleSheet('QLineEdit {background: #FFFFE0;} QLineEdit:hover {border: 1px solid gray; background: #FFFFE0;}')

    def focusInEvent(self, e):
        super(TransMatrixEdit, self).focusInEvent(e)
        self.selectAll()


class LCAggTableModel(QAbstractTableModel):
    def __init__(self, datain, parent=None, *args):
        QAbstractTableModel.__init__(self, parent, *args)
        self.classes = datain
        
        # Column names as tuples with json name in [0], pretty name in [1]
        # Note that the columns with json names set to to INVALID aren't loaded
        # into the shell, but shown from a widget.
        colname_tuples = [('Initial_Code', QtGui.QApplication.translate('DlgCalculateLCSetAggregation', 'Input code')),
                          ('Initial_Label', QtGui.QApplication.translate('DlgCalculateLCSetAggregation', 'Input class')),
                          ('Final_Label', QtGui.QApplication.translate('DlgCalculateLCSetAggregation', 'Output class'))]
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


# Function to read a file defining land cover aggegation
def read_class_file(f):
    if not os.access(f, os.R_OK):
        QtGui.QMessageBox.critical(None,
                QtGui.QApplication.translate("Error"),
                QtGui.QApplication.translate(u"Cannot read {}.".format(f), None))
        return None

    with open(f) as class_file:
        classes = json.load(class_file)
    if (not isinstance(classes, list)
            or not len(classes) > 0
            or not isinstance(classes[0], dict)
            or not classes[0].has_key('Initial_Code')
            or not classes[0].has_key('Final_Code')
            or not classes[0].has_key('Final_Label')):

        QtGui.QMessageBox.critical(None,
                                   QtGui.QApplication.translate('DlgCalculateLCSetAggregation', "Error"),
                                   QtGui.QApplication.translate('DlgCalculateLCSetAggregation',
                                                                u"{} does not appear to contain a valid class definition.".format(f)))
        return None
    else:
        log(u'Loaded class definition from {}'.format(f))
        return classes


class DlgCalculateLCSetAggregation(QtGui.QDialog, Ui_DlgCalculateLCSetAggregation):
    def __init__(self, default_classes, parent=None):
        super(DlgCalculateLCSetAggregation, self).__init__(parent)

        self.default_classes = default_classes

        self.setupUi(self)

        self.final_classes = {'No data': -32768,
                              'Tree-covered': 1,
                              'Grassland': 2,
                              'Cropland': 3,
                              'Wetland': 4,
                              'Artificial': 5,
                              'Other land': 6,
                              'Water body': 7}

        self.btn_save.clicked.connect(self.btn_save_pressed)
        self.btn_load.clicked.connect(self.btn_load_pressed)
        self.btn_reset.clicked.connect(self.reset_class_table)
        self.btn_close.clicked.connect(self.btn_close_pressed)

        # Setup the class table so that the table is defined when a user first 
        # loads the dialog
        self.reset_class_table()

    def btn_close_pressed(self):
        self.close()

    def btn_load_pressed(self):
        f = QtGui.QFileDialog.getOpenFileName(self,
                                              self.tr('Select a land cover definition file'),
                                              QSettings().value("LDMP/lc_def_dir", None),
                                              self.tr('Land cover definition (*.json)'))
        if f:
            if os.access(f, os.R_OK):
                QSettings().setValue("LDMP/lc_def_dir", os.path.dirname(f))
            else:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr(u"Cannot read {}. Choose a different file.".format(f), None))
        else:
            return
        classes = read_class_file(f)

        if classes:
            self.setup_class_table(classes)

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
                                           self.tr(u"Cannot write to {}. Choose a different file.".format(f), None))
                return

            class_def = self.get_agg_as_dict_list()
            with open(f, 'w') as outfile:
                json.dump(class_def, outfile, sort_keys=True, indent=4, 
                          separators=(',', ': '), default=json_serial)

    def get_agg_as_dict(self):
        '''Returns the chosen land cover definition as a dictionary'''
        out = {}
        for row in range(0, self.remap_view.model().rowCount()):
            initial_code = self.remap_view.model().index(row, 0).data()
            label_widget_index = self.remap_view.model().index(row, self.remap_view.model().columnCount() - 1)
            label_widget = self.remap_view.indexWidget(label_widget_index)
            out[initial_code] = self.final_classes[label_widget.currentText()]
        return out

    def get_agg_as_dict_list(self):
        '''Returns the chosen land cover definition as a list of dictionaries'''
        out = []
        for row in range(0, self.remap_view.model().rowCount()):
            this_out = {}
            initial_code = self.remap_view.model().index(row, 0).data()
            this_out['Initial_Code'] = initial_code
            initial_label = self.remap_view.model().index(row, 1).data()
            this_out['Initial_Label'] = initial_label
            # Get the currently assigned label for this code
            label_widget_index = self.remap_view.model().index(row, self.remap_view.model().columnCount() - 1)
            label_widget = self.remap_view.indexWidget(label_widget_index)
            this_out['Final_Label'] = label_widget.currentText()
            this_out['Final_Code'] = self.final_classes[this_out['Final_Label']]

            out.append(this_out)
        # Sort output by initial code
        out = sorted(out, key=lambda k: k['Initial_Code'])
        return out

    def get_agg_as_list(self):
        '''Returns a list describing how to aggregate the land cover data'''
        out = [[], []]
        for row in range(0, self.remap_view.model().rowCount()):
            initial_code = self.remap_view.model().index(row, 0).data()

            # Get the currently assigned label for this code
            label_widget_index = self.remap_view.model().index(row, 2)
            label_widget = self.remap_view.indexWidget(label_widget_index)
            final_code = self.final_classes[label_widget.currentText()]
            out[0].append(initial_code)
            out[1].append(final_code)
        return out

    def setup_class_table(self, classes):
        default_codes = sorted([c['Initial_Code'] for c in self.default_classes])
        input_codes = sorted([c['Initial_Code'] for c in classes])
        new_codes = [c for c in input_codes if c not in default_codes]
        missing_codes = [c for c in default_codes if c not in input_codes]
        if len(new_codes) > 0:
            QtGui.QMessageBox.warning(None, self.tr("Warning"),
                                      self.tr(u"Some of the class codes ({}) in the definition file do not appear in the chosen data file.".format(', '.join([str(c) for c in new_codes]), None)))
        if len(missing_codes) > 0:
            QtGui.QMessageBox.warning(None, self.tr("Warning"),
                                      self.tr(u"Some of the class codes ({}) in the data file do not appear in the chosen definition file.".format(', '.join([str(c) for c in missing_codes]), None)))

        # Setup a new classes list with the new class codes for all classes 
        # included in default calsses, and and any other class codes that are 
        # missing added from the default class list
        classes = [c for c in classes if c['Initial_Code'] in default_codes]
        classes.extend([c for c in self.default_classes if c['Initial_Code'] not in input_codes])

        table_model = LCAggTableModel(classes, parent=self)
        proxy_model = QtGui.QSortFilterProxyModel()
        proxy_model.setSourceModel(table_model)
        self.remap_view.setModel(proxy_model)

        # Add selector in cell
        for row in range(0, len(classes)):
            lc_classes = QtGui.QComboBox()
            lc_classes.currentIndexChanged.connect(self.lc_class_combo_changed)
            # Add the classes in order of their codes
            lc_classes.addItems(sorted(self.final_classes.keys(), key=lambda k: self.final_classes[k]))
            ind = lc_classes.findText(classes[row]['Final_Label'])
            if ind != -1:
                lc_classes.setCurrentIndex(ind)
            self.remap_view.setIndexWidget(proxy_model.index(row, self.remap_view.model().columnCount() - 1), lc_classes)

        self.remap_view.setSelectionBehavior(QtGui.QAbstractItemView.SelectRows)
        self.remap_view.setColumnWidth(1, 450)
        self.remap_view.horizontalHeader().setStretchLastSection(True)
        return True

    def lc_class_combo_changed(self, index):
        if self.sender().currentText() == self.tr('No data'):
            class_color = "#000000"
        elif self.sender().currentText() == self.tr('Tree-covered'):
            class_color = "#787F1B"
        elif self.sender().currentText() == self.tr('Grassland'):
            class_color = "#FFAC42"
        elif self.sender().currentText() == self.tr('Cropland'):
            class_color = "#FFFB6E"
        elif self.sender().currentText() == self.tr('Wetland'):
            class_color = "#00DB84"
        elif self.sender().currentText() == self.tr('Artificial'):
            class_color = "#E60017"
        elif self.sender().currentText() == self.tr('Other land'):
            class_color = "#FFF3D7"
        elif self.sender().currentText() == self.tr('Water body'):
            class_color = "#0053C4"
        else:
            class_color = "#d7d6d5"
        # Note double brackets to escape for string.format
        self.sender().setStyleSheet('''QComboBox {{background: qlineargradient(x1:1, y1:.5, x2:.6, y2:.5,
                                                                               stop:0 {class_color},
                                                                               stop:0.6 {class_color},
                                                                               stop:0.8 #d7d6d5,
                                                                               stop:1 #d7d6d5);}}'''.format(class_color=class_color))

    def reset_class_table(self):
        self.setup_class_table(self.default_classes)


class LCDefineDegradationWidget(QtGui.QWidget, Ui_WidgetLCDefineDegradation):
    def __init__(self, parent=None):
        super(LCDefineDegradationWidget, self).__init__(parent)

        self.setupUi(self)

        self.classes = [self.tr("Tree-covered"),
                        self.tr("Grassland"),
                        self.tr("Cropland"),
                        self.tr("Wetland"),
                        self.tr("Artificial"),
                        self.tr("Bare land"),
                        self.tr("Water body")]
        self.deg_def_matrix.setRowCount(len(self.classes))
        self.deg_def_matrix.setColumnCount(len(self.classes))
        self.deg_def_matrix.setHorizontalHeaderLabels(self.classes)
        self.deg_def_matrix.setVerticalHeaderLabels(self.classes)

        self.trans_matrix_default = [0, -1, -1, -1, -1, -1, 0, # Tree-covered
                                     1, 0, 1, -1, -1, -1, 0, # grassland
                                     1, -1, 0, -1, -1, -1, 0, # cropland
                                     -1, -1, -1, 0, -1, -1, 0, # wetland
                                     1, 1, 1, 1, 0, 1, 0, # artificial
                                     1, 1, 1, 1, -1, 0, 0, # Other land
                                     0, 0, 0, 0, 0, 0, 0] # water body
        for row in range(0, self.deg_def_matrix.rowCount()):
            for col in range(0, self.deg_def_matrix.columnCount()):
                line_edit = TransMatrixEdit()
                line_edit.setValidator(QtGui.QRegExpValidator(QRegExp("[-0+]")))
                line_edit.setAlignment(Qt.AlignHCenter)
                self.deg_def_matrix.setCellWidget(row, col, line_edit)
        self.trans_matrix_set()

        # Setup the vertical label for the rows of the table
        label_lc_baseline_year = VerticalLabel(self)
        label_lc_baseline_year.setText(QtGui.QApplication.translate("DlgCalculateLC", "Land cover in initial year ", None))
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

        self.deg_def_matrix.setStyleSheet('QTableWidget {border: 0px;}')
        self.deg_def_matrix.horizontalHeader().setStyleSheet('QHeaderView::section {background-color: white;border: 0px;}')
        self.deg_def_matrix.verticalHeader().setStyleSheet('QHeaderView::section {background-color: white;border: 0px;}')

        self.deg_def_matrix.horizontalHeader().setResizeMode(QtGui.QHeaderView.Stretch)
        self.deg_def_matrix.verticalHeader().setResizeMode(QtGui.QHeaderView.Stretch)

        self.btn_transmatrix_reset.clicked.connect(self.trans_matrix_set)
        self.btn_transmatrix_loadfile.clicked.connect(self.trans_matrix_loadfile)
        self.btn_transmatrix_savefile.clicked.connect(self.trans_matrix_savefile)

        self.legend_deg.setStyleSheet('QLineEdit {background: #AB2727;} QLineEdit:hover {border: 1px solid gray; background: #AB2727;}')
        self.legend_imp.setStyleSheet('QLineEdit {background: #45A146;} QLineEdit:hover {border: 1px solid gray; background: #45A146;}')
        self.legend_stable.setStyleSheet('QLineEdit {background: #FFFFE0;} QLineEdit:hover {border: 1px solid gray; background: #FFFFE0;}')

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
                                           self.tr(u"Cannot read {}. Choose a different file.".format(f), None))
        else:
            return None

        with open(f) as matrix_file:
            matrix = json.load(matrix_file)

        flag = False
        if isinstance(matrix, list) and len(matrix) == (len(self.classes) * len(self.classes)):
            flag = self.trans_matrix_set(matrix)

        if not flag:
            QtGui.QMessageBox.critical(None,
                                       QtGui.QApplication.translate('DlgCalculateLC', "Error"),
                                       QtGui.QApplication.translate('DlgCalculateLC',
                                                                    u"{} does not appear to contain a valid matrix definition.".format(f)))
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
                                           self.tr(u"Cannot write to {}. Choose a different file.".format(f), None))
                return

            matrix = self.trans_matrix_get()
            with open(f, 'w') as outfile:
                json.dump(matrix, outfile, sort_keys=True, indent=4, separators=(',', ': '))

    def trans_matrix_set(self, matrix=None):
        if not matrix:
            matrix = self.trans_matrix_default
        for row in range(0, self.deg_def_matrix.rowCount()):
            for col in range(0, self.deg_def_matrix.columnCount()):
                # Matrix is actually a list of length NUM_CLASSES * NUM_CLASSES
                val = matrix[len(self.classes) * row + col]
                if val == 0:
                    val_str = '0'
                elif val == -1:
                    val_str = '-'
                elif val == 1:
                    val_str = '+'
                else:
                    log('unrecognized value "{}" when setting transition matrix'.format(val))
                    return False
                self.deg_def_matrix.cellWidget(row, col).setText(val_str)
        return True

    def trans_matrix_get(self):
        # Extract trans_matrix from the QTableWidget
        trans_matrix = []
        for row in range(0, self.deg_def_matrix.rowCount()):
            for col in range(0, self.deg_def_matrix.columnCount()):
                val = self.deg_def_matrix.cellWidget(row, col).text()
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


class LCSetupWidget(QtGui.QWidget, Ui_WidgetLCSetup):
    def __init__(self, parent=None):
        super(LCSetupWidget, self).__init__(parent)

        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                               'data', 'gee_datasets.json')) as datasets_file:
            self.datasets = json.load(datasets_file)

        self.setupUi(self)

        default_class_file = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                         'data', 'land_cover_classes.json')
        self.dlg_esa_agg = DlgCalculateLCSetAggregation(read_class_file(default_class_file), parent=self)

        lc_start_year = QDate(self.datasets['Land cover']['ESA CCI']['Start year'], 1, 1)
        lc_end_year = QDate(self.datasets['Land cover']['ESA CCI']['End year'], 12, 31)
        self.use_esa_bl_year.setMinimumDate(lc_start_year)
        self.use_esa_bl_year.setMaximumDate(lc_end_year)
        self.use_esa_tg_year.setMinimumDate(lc_start_year)
        self.use_esa_tg_year.setMaximumDate(lc_end_year)

        self.use_esa.toggled.connect(self.use_esa_toggled)

        # Below is a bugfix for checkable group boxes created in QtDesigner - 
        # if they aren't checked by default in Qt Designer then checking them 
        # in the final gui doesn't enable their children. 
        self.groupBox_esa_agg.setChecked(False)

        self.use_esa_agg_edit.clicked.connect(self.esa_agg_custom_edit)

        # Make sure the custom data boxes are turned off by default
        self.use_esa_toggled()

        # Ensure that if a LC layer is loaded in one box it shows up also in 
        # the other
        #self.use_custom_initial.layers_added.connect(self.use_custom_final.populate)
        #self.use_custom_final.layers_added.connect(self.use_custom_initial.populate)

    def showEvent(self, event):
        super(LCSetupWidget, self).showEvent(event)

        # By default, don't show hansen selector 
        self.show_hansen_toggle(False)

    def show_hansen_toggle(self, enable):
        if enable:
            self.hansen_enabled = True
            self.groupBox_hansen.show()
            self.use_hansen.show()
            self.use_hansen.setEnabled(True)
        else:
            self.hansen_enabled = False
            self.groupBox_hansen.hide()
            self.use_hansen.hide()
            self.use_hansen.setEnabled(False)

    def use_esa_toggled(self):
        if self.use_esa.isChecked():
            self.groupBox_esa_period.setEnabled(True)
            self.groupBox_esa_agg.setEnabled(True)
            self.groupBox_custom_bl.setEnabled(False)
            self.groupBox_custom_tg.setEnabled(False)
        else:
            self.groupBox_esa_period.setEnabled(False)
            self.groupBox_esa_agg.setEnabled(False)
            self.groupBox_custom_bl.setEnabled(True)
            self.groupBox_custom_tg.setEnabled(True)

    def get_initial_year(self):
        return self.use_custom_initial.get_band_info()['metadata']['year']

    def get_final_year(self):
        return self.use_custom_final.get_band_info()['metadata']['year']

    def esa_agg_custom_edit(self):
        self.dlg_esa_agg.exec_()

# LC widgets shared across dialogs
lc_define_deg_widget = LCDefineDegradationWidget()
lc_setup_widget = LCSetupWidget()
