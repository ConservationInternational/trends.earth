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

from builtins import str
from builtins import range
import os
import json

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtGui import (QColor, QRegExpValidator, QFont, QPainter)
from qgis.PyQt.QtCore import (QSettings, QDate, Qt, QSize, QAbstractTableModel, 
        QRegExp, QJsonValue, QSortFilterProxyModel, QAbstractListModel, 
        QCoreApplication)

from qgis.utils import iface
mb = iface.messageBar()

from LDMP import log
from LDMP.gui.DlgCalculateLCSetAggregation import Ui_DlgCalculateLCSetAggregation
from LDMP.gui.WidgetLCDefineDegradation import Ui_WidgetLCDefineDegradation
from LDMP.gui.WidgetLCSetup import Ui_WidgetLCSetup
from LDMP.layers import tr_style_text

from LDMP.schemas.land_cover import *

from marshmallow.exceptions import ValidationError
class tr_lc_setup(object):
    def tr(message):
        return QCoreApplication.translate("tr_lc_setup", message)


def get_lc_nesting():
    nesting = QSettings().value("LDMP/land_cover_nesting", None)
    if nesting is None:
        nesting = read_lc_nesting_file(os.path.join(os.path.dirname(os.path.realpath(__file__)),
            'data', 'land_cover_nesting_UNCCD_ESA.json'))
        QSettings().setValue("LDMP/land_cover_nesting", LCLegendNesting.Schema().dumps(nesting))
    else:
        nesting = LCLegendNesting.Schema().loads(nesting)
    return nesting

def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    #TODO: This was QPyNullVariant under pyqt4 - check the below works on pyqt5
    if isinstance(obj, QJsonValue.Null):
        return None
    raise TypeError("Type {} not serializable".format(type(obj)))


class VerticalLabel(QtWidgets.QLabel):
    def __init__(self, parent=None):
        super(VerticalLabel, self).__init__(parent)

    def paintEvent(self, paint_event):
        painter = QPainter(self)
        painter.translate(self.sizeHint().width(), self.sizeHint().height())
        painter.rotate(270)
        painter.drawText(0, 0, self.text())

    def minimumSizeHint(self):
        s = QtWidgets.QLabel.minimumSizeHint(self)
        return QSize(s.height(), s.width())

    def sizeHint(self):
        s = QtWidgets.QLabel.sizeHint(self)
        return QSize(s.height(), s.width())


class TransMatrixEdit(QtWidgets.QLineEdit):
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


class LCClassComboBox(QtWidgets.QComboBox):
    def __init__(self, classes, parent=None, *args):
        super(LCClassComboBox, self).__init__(parent)
        self.classes = classes

        # Add the translations of the item labels in order of their codes
        self.addItems([c.name_long for c in classes.orderByCode().key])

        for n in range(0, len(classes.key)):
            color = classes.classByNameLong(self.itemData(n, Qt.DisplayRole)).color
            self.setItemData(n, QColor(color), Qt.BackgroundRole)
            if color == '#000000':
                self.setItemData(n, QColor('#FFFFFF'), Qt.ForegroundRole)
            else:
                self.setItemData(n, QColor('#000000'), Qt.ForegroundRole)

        self.index_changed()
        self.currentIndexChanged.connect(self.index_changed)

    def index_changed(self):
        color = self.classes.classByNameLong(self.currentText()).color
        if color == '#000000':
            self.setStyleSheet('QComboBox:editable {{background-color: {}; color: #FFFFFF;}}'.format(color))
        else:
            self.setStyleSheet('QComboBox:editable {{background-color: {};}}'.format(color))

class LCAggTableModel(QAbstractTableModel):
    def __init__(self, datain, parent=None, *args):
        QAbstractTableModel.__init__(self, parent, *args)
        self.nesting = datain
        
        # Column names as tuples with json name in [0], pretty name in [1]
        # Note that the columns with json names set to to INVALID aren't loaded
        # into the shell, but shown from a widget.
        colname_tuples = [('Initial_Code', tr_lc_setup.tr('Input code')),
                          ('Initial_Label', tr_lc_setup.tr('Input class')),
                          ('Final_Label', tr_lc_setup.tr('Output class'))]
        self.colnames_json = [x[0] for x in colname_tuples]
        self.colnames_pretty = [x[1] for x in colname_tuples]

    def rowCount(self, parent):
        return len(self.nesting.parent.key)

    def columnCount(self, parent):
        return len(self.colnames_json)

    def data(self, index, role):
        log('getting data for index row {} and role {}'.format(index.row(), role))
        if not index.isValid():
            log('index not valid')
            return None
        elif role == Qt.TextAlignmentRole and index.column() in [0, 2, 3]:
            log('qt align center')
            return Qt.AlignCenter
        elif role != Qt.DisplayRole:
            log('not display role')
            return None
        log('here')
        log('data for index {} and role {}: {}'.format(index, role, self.nesting.parent.key[index.row()].get(self.colnames_json[index.column()], '')))
        return self.nesting.parent.key[index.row()].get(self.colnames_json[index.column()], '')

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.colnames_pretty[section]
        return QAbstractTableModel.headerData(self, section, orientation, role)


# Function to read a file defining land cover aggregation
def read_lc_nesting_file(f):
    if not os.access(f, os.R_OK):
        QtWidgets.QMessageBox.critical(None,
                tr_lc_setup.tr("Error"),
                tr_lc_setup.tr(u"Cannot read {}.".format(f)))
        return None

    log('class file: {}'.format(f))

    try:
        with open(f) as class_file:
            j = LCLegendNesting.Schema().loads(class_file.read())
    except ValidationError as e:
        log(u'Error loading land cover legend nesting definition from {}: {}'.format(f, e))
        QtWidgets.QMessageBox.critical(None,
                                       tr_lc_setup.tr("Error"),
                                       tr_lc_setup.tr("{} does not appear to contain a valid land cover legend nesting definition.".format(f)))
        return None
    else:
        log(u'Loaded land cover legend nesting definition from {}'.format(f))
        return j


class DlgCalculateLCSetAggregation(QtWidgets.QDialog, Ui_DlgCalculateLCSetAggregation):
    def __init__(self, nesting, parent=None):
        super(DlgCalculateLCSetAggregation, self).__init__(parent)

        self.nesting = nesting

        self.setupUi(self)

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
        f, _ = QtWidgets.QFileDialog.getOpenFileName(self,
                                              self.tr('Select a land cover definition file'),
                                              QSettings().value("LDMP/lc_def_dir", None),
                                              self.tr('Land cover definition (*.json)'))
        if f:
            if os.access(f, os.R_OK):
                QSettings().setValue("LDMP/lc_def_dir", os.path.dirname(f))
            else:
                QtWidgets.QMessageBox.critical(None,
                                               self.tr("Error"),
                                               self.tr(u"Cannot read {}. Choose a different file.".format(f)))
        else:
            return
        nesting = read_lc_nesting_file(f)

        if nesting:
            self.setup_class_table(nesting)

    def btn_save_pressed(self):
        f, _ = QtWidgets.QFileDialog.getSaveFileName(self,
                                                     self.tr('Choose where to save this land cover definition'),
                                                     QSettings().value("LDMP/lc_def_dir", None),
                                                     self.tr('Land cover definition (*.json)'))
        if f:
            if os.access(os.path.dirname(f), os.W_OK):
                QSettings().setValue("LDMP/lc_def_dir", os.path.dirname(f))
            else:
                QtWidgets.QMessageBox.critical(None,
                                               self.tr("Error"),
                                               self.tr(u"Cannot write to {}. Choose a different file.".format(f)))
                return

            with open(f, 'w') as outfile:
                json.dump(LCLegend.Schema().dump(self.get_LCLegendNesting()), 
                        outfile, sort_keys=True, indent=4,
                        separators=(',', ':'), default=json_serial)


    def get_LCLegendNesting(self):
        '''Returns a json describing how to aggregate the land cover data'''
        #TODO: store this in "self.nesting"
        lc_classes_custom = []
        lc_classes_unccd = []
        lc_nesting = {}
        for item in lc_def:
            lc_class_custom = LCClass(item['Initial_Code'], item['Initial_Label'], color=styles_custom[item['Initial_Code']])
            if lc_class_custom not in lc_classes_custom:
                lc_classes_custom.append(lc_class_custom)

            lc_class_unccd = LCClass(item['Final_Code'], item['Final_Label'], color=styles_unccd[item['Final_Code']])
            if lc_class_unccd not in lc_classes_unccd:
                lc_classes_unccd.append(lc_class_unccd)

            if lc_class_unccd.code in lc_nesting:
                lc_nesting[lc_class_unccd.code].append(lc_class_custom.code)
            else:
                lc_nesting[lc_class_unccd.code] = [lc_class_custom.code]

        lc_legend_unccd = LCLegend('UNCCD Land Cover', lc_classes_unccd)
        lc_legend_custom = LCLegend('ESA CCI Land Cover', lc_classes_custom) #TODO: allow user to set this name

        # with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
        #                        'data', 'land_cover_legend_unccd.json'), 'w') as f:
        #     j = json.loads(LCLegend.Schema().dumps(lc_legend_unccd))
        #     json.dump(j, f, indent=4)
        # with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
        #                        'data', 'land_cover_legend_esa.json'), 'w') as f:
        #     j = json.loads(LCLegend.Schema().dumps(lc_legend_custom))
        #     json.dump(j, f, indent=4)
        # with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
        #                        'data', 'land_cover_nesting_unccd_esa.json'), 'w') as f:
        #     j = json.loads(LCLegendNesting.Schema().dumps(LCLegendNesting(lc_legend_unccd, lc_legend_custom, lc_nesting)))
        #     json.dump(j, f, indent=4)
        #
        return LCLegendNesting(lc_legend_unccd, lc_legend_custom, lc_nesting)


    def setup_class_table(self, nesting=None):
        # Load the codes each class will be recoded to.
        # 
        # The "nesting" parameter will include any mappings derived from a 
        # class definition file, or, in the case or reading in user land cover 
        # files, nesting from the file itself.
        # 
        # The default codes stored in self.nesting are derived either 
        # from the data/land_cover_nesting_UNCCD_ESA.json file when this class 
        # is instantiated from the LCSetupWidget, or from the values within a 
        # custom user data file when this class is instantiated from the 
        # DlgDataIOImportLC class.
        if nesting:
            input_codes = sorted([c['Initial_Code'] for c in nesting])
            default_codes = sorted([c['Initial_Code'] for c in self.nesting])
            new_codes = [c for c in input_codes if c not in default_codes]
            missing_codes = [c for c in default_codes if c not in input_codes]
            if len(new_codes) > 0:
                QtWidgets.QMessageBox.warning(None,
                                              self.tr("Warning"),
                                              self.tr(u"Some of the class codes ({}) in the definition file do not appear in the chosen data file.".format(', '.join([str(c) for c in new_codes]))))
            if len(missing_codes) > 0:
                QtWidgets.QMessageBox.warning(None,
                                              self.tr("Warning"),
                                              self.tr(u"Some of the class codes ({}) in the data file do not appear in the chosen definition file.".format(', '.join([str(c) for c in missing_codes]))))

            # Setup a new nesting list with the new class codes for all classes 
            # included in default classes, and any other class codes that are 
            # missing added from the default class list
            nesting = [c for c in nesting if c['Initial_Code'] in default_codes]
            nesting.extend([c for c in self.nesting if c['Initial_Code'] not in input_codes])
        else:
            nesting = self.nesting

        table_model = LCAggTableModel(nesting, parent=self)
        proxy_model = QSortFilterProxyModel()
        proxy_model.setSourceModel(table_model)
        self.remap_view.setModel(proxy_model)

        # Add selector in cell
        for row in range(0, len(nesting.child.key)):
            lc_class_combo = LCClassComboBox(nesting.parent)

            # Now Set the default final codes for each row. Note that the 
            # QComboBox entries are potentially translated, so need to link the 
            # translated names back to a particular code.
            
            # Get the input code for this row and the final label it should map 
            # to by default
            input_code = table_model.index(row, 0).data()
            log('input code: {}'.format(input_code))
            final_label = [nesting.parentCodeForChild(c.code) for c in nesting.child.key if c.code == input_code][0]

            # Figure out which label translation this Final_Label (in English) 
            # is equivalent to
            label_to_label_tr = {nesting[key]['label']: key for key in nesting.keys()}
            final_label_tr = label_to_label_tr[final_label]

            # Now find the index in the combo box of this translated final 
            # label
            ind = lc_class_combo.findText(final_label_tr)
            if ind != -1:
                lc_class_combo.setCurrentIndex(ind)
            self.remap_view.setIndexWidget(proxy_model.index(row, 2), lc_class_combo)

        self.remap_view.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.remap_view.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.remap_view.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        
        self.remap_view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)

        return True

    def reset_class_table(self):
        self.setup_class_table()


class LCDefineDegradationWidget(QtWidgets.QWidget, Ui_WidgetLCDefineDegradation):
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
                line_edit.setValidator(QRegExpValidator(QRegExp("[-0+]")))
                line_edit.setAlignment(Qt.AlignHCenter)
                self.deg_def_matrix.setCellWidget(row, col, line_edit)
        self.trans_matrix_set()

        # Setup the vertical label for the rows of the table
        label_lc_baseline_year = VerticalLabel(self)
        label_lc_baseline_year.setText(self.tr("Land cover in initial year "))
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Minimum)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.label_lc_target_year.sizePolicy().hasHeightForWidth())
        label_lc_baseline_year.setSizePolicy(sizePolicy)
        font = QFont()
        font.setBold(True)
        font.setWeight(75)
        label_lc_baseline_year.setFont(font)
        self.lc_trans_table_layout.addWidget(label_lc_baseline_year, 1, 0, 1, 1, Qt.AlignCenter)

        self.deg_def_matrix.setStyleSheet('QTableWidget {border: 0px;}')
        self.deg_def_matrix.horizontalHeader().setStyleSheet('QHeaderView::section {background-color: white;border: 0px;}')
        self.deg_def_matrix.verticalHeader().setStyleSheet('QHeaderView::section {background-color: white;border: 0px;}')

        for row in range(0, self.deg_def_matrix.rowCount()):
            self.deg_def_matrix.horizontalHeader().setSectionResizeMode(row, QtWidgets.QHeaderView.Stretch)
        for col in range(0, self.deg_def_matrix.columnCount()):
            self.deg_def_matrix.verticalHeader().setSectionResizeMode(col, QtWidgets.QHeaderView.Stretch)

        self.btn_transmatrix_reset.clicked.connect(self.trans_matrix_set)
        self.btn_transmatrix_loadfile.clicked.connect(self.trans_matrix_loadfile)
        self.btn_transmatrix_savefile.clicked.connect(self.trans_matrix_savefile)

        self.legend_deg.setStyleSheet('QLineEdit {background: #AB2727;} QLineEdit:hover {border: 1px solid gray; background: #AB2727;}')
        self.legend_imp.setStyleSheet('QLineEdit {background: #45A146;} QLineEdit:hover {border: 1px solid gray; background: #45A146;}')
        self.legend_stable.setStyleSheet('QLineEdit {background: #FFFFE0;} QLineEdit:hover {border: 1px solid gray; background: #FFFFE0;}')

    def trans_matrix_loadfile(self):
        f, _ = QtWidgets.QFileDialog.getOpenFileName(self,
                                              self.tr('Select a transition matrix definition file'),
                                              QSettings().value("LDMP/lc_def_dir", None),
                                              self.tr('Transition matrix definition (*.json)'))
        if f:
            if os.access(f, os.R_OK):
                QSettings().setValue("LDMP/lc_def_dir", os.path.dirname(f))
            else:
                QtWidgets.QMessageBox.critical(None,
                                               self.tr("Error"),
                                               self.tr(u"Cannot read {}. Choose a different file.".format(f)))
        else:
            return None

        with open(f) as matrix_file:
            matrix = json.load(matrix_file)

        flag = False
        if isinstance(matrix, list) and len(matrix) == (len(self.classes) * len(self.classes)):
            flag = self.trans_matrix_set(matrix)

        if not flag:
            QtWidgets.QMessageBox.critical(None,
                                           self.tr("Error"),
                                           self.tr("{} does not appear to contain a valid matrix definition.".format(f)))
            return None
        else:
            return True

    def trans_matrix_savefile(self):
        f, _ = QtWidgets.QFileDialog.getSaveFileName(self,
                                                     self.tr('Choose where to save this transition matrix definition'),
                                                     QSettings().value("LDMP/lc_def_dir", None),
                                                     self.tr('Transition matrix definition (*.json)'))
        if f:
            if os.access(os.path.dirname(f), os.W_OK):
                QSettings().setValue("LDMP/lc_def_dir", os.path.dirname(f))
            else:
                QtWidgets.QMessageBox.critical(None,
                                               self.tr("Error"),
                                               self.tr(u"Cannot write to {}. Choose a different file.".format(f)))
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

    def trans_matrix_get(self):
        legend = self.get_legend()
        m = self.trans_matrix_get()
        #
        # for row in range(0, self.deg_def_matrix.rowCount()):
        #     for col in range(0, self.deg_def_matrix.columnCount()):
        #         initial = LCClass(self.classes[row]
        #
        # transitions = []
        # initial = LCClass(code_initial, name_short_initial, name_long_initial, description_initial)
        # final = LCClass(code_initial, name_short_initial, name_long_initial, description_initial)
        # LCTransMeaning(initial, final, meaning)

        return LCTransMatrix(legend, transitions)


class LCSetupWidget(QtWidgets.QWidget, Ui_WidgetLCSetup):
    def __init__(self, parent=None):
        super(LCSetupWidget, self).__init__(parent)

        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                               'data', 'gee_datasets.json')) as datasets_file:
            self.datasets = json.load(datasets_file)

        self.setupUi(self)

        nesting = get_lc_nesting()
        self.dlg_esa_agg = DlgCalculateLCSetAggregation(nesting, parent=self)

        lc_start_year = QDate(self.datasets['Land cover']['ESA CCI']['Start year'], 1, 1)
        lc_end_year = QDate(self.datasets['Land cover']['ESA CCI']['End year'], 12, 31)
        self.use_esa_bl_year.setMinimumDate(lc_start_year)
        self.use_esa_bl_year.setMaximumDate(lc_end_year)
        self.use_esa_tg_year.setMinimumDate(lc_start_year)
        self.use_esa_tg_year.setMaximumDate(lc_end_year)

        self.use_esa.toggled.connect(self.lc_source_changed)
        self.use_custom.toggled.connect(self.lc_source_changed)

        # Below is a bugfix for checkable group boxes created in QtDesigner - 
        # if they aren't checked by default in Qt Designer then checking them 
        # in the final gui doesn't enable their children. 
        self.groupBox_esa_agg.setChecked(False)

        self.use_esa_agg_edit.clicked.connect(self.esa_agg_custom_edit)

        # Make sure the custom data boxes are turned off by default
        self.lc_source_changed()

        # Ensure that if a LC layer is loaded in one box it shows up also in 
        # the other
        #self.use_custom_initial.layers_added.connect(self.use_custom_final.populate)
        #self.use_custom_final.layers_added.connect(self.use_custom_initial.populate)

    def lc_source_changed(self):
        if self.use_esa.isChecked():
            self.groupBox_esa_period.setEnabled(True)
            self.groupBox_esa_agg.setEnabled(True)
            self.groupBox_custom_bl.setEnabled(False)
            self.groupBox_custom_tg.setEnabled(False)
        elif self.use_custom.isChecked():
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
