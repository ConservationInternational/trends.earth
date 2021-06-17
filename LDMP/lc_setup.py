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

import json
import os
from pathlib import Path

from PyQt5 import (
    QtCore,
    QtGui,
    QtWidgets,
    uic
)

from qgis.utils import iface

from . import (
    conf,
    data_io,
    log,
)
from .layers import tr_style_text

DlgCalculateLcSetAggregationUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateLCSetAggregation.ui"))
WidgetLcDefineDegradationUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/WidgetLCDefineDegradation.ui"))
WidgetLcSetupUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/WidgetLCSetup.ui"))

mb = iface.messageBar()


class tr_lc_setup(object):
    def tr(message):
        return QtCore.QCoreApplication.translate("tr_lc_setup", message)


# Load the default classes and their assigned color codes
with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                       'data', 'land_cover_classes_IPCC.json')) as class_file:
    classes = json.load(class_file)
final_classes = {}
for key in classes.keys():
    classes[key]['label'] = key
    final_classes[tr_style_text(key)] = classes[key]


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    #TODO: This was QPyNullVariant under pyqt4 - check the below works on pyqt5
    if isinstance(obj, QtCore.QJsonValue.Null):
        return None
    raise TypeError("Type {} not serializable".format(type(obj)))


class VerticalLabel(QtWidgets.QLabel):
    def __init__(self, parent=None):
        super(VerticalLabel, self).__init__(parent)

    def paintEvent(self, paint_event):
        painter = QtGui.QPainter(self)
        painter.translate(self.sizeHint().width(), self.sizeHint().height())
        painter.rotate(270)
        painter.drawText(0, 0, self.text())

    def minimumSizeHint(self):
        s = QtWidgets.QLabel.minimumSizeHint(self)
        return QtCore.QSize(s.height(), s.width())

    def sizeHint(self):
        s = QtWidgets.QLabel.sizeHint(self)
        return QtCore.QSize(s.height(), s.width())


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
    def __init__(self, parent=None, *args):
        super(LCClassComboBox, self).__init__(parent)

        # Add the translations of the item labels in order of their codes
        self.addItems(sorted(list(final_classes), key = lambda k: final_classes[k]['value']))

        for n in range(0, len(final_classes.keys())):
            color = final_classes[self.itemData(n, QtCore.Qt.DisplayRole)]['color']
            self.setItemData(n, QtGui.QColor(color), QtCore.Qt.BackgroundRole)
            if color == '#000000':
                self.setItemData(n, QtGui.QColor('#FFFFFF'), QtCore.Qt.ForegroundRole)
            else:
                self.setItemData(n, QtGui.QColor('#000000'), QtCore.Qt.ForegroundRole)

        self.index_changed()
        self.currentIndexChanged.connect(self.index_changed)

    def index_changed(self):
        color = final_classes[self.currentText()]['color']
        if color == '#000000':
            self.setStyleSheet('QComboBox:editable {{background-color: {}; color: #FFFFFF;}}'.format(color))
        else:
            self.setStyleSheet('QComboBox:editable {{background-color: {};}}'.format(color))

class LCAggTableModel(QtCore.QAbstractTableModel):
    def __init__(self, datain, parent=None, *args):
        QtCore.QAbstractTableModel.__init__(self, parent, *args)
        self.classes = datain
        
        # Column names as tuples with json name in [0], pretty name in [1]
        # Note that the columns with json names set to to INVALID aren't loaded
        # into the shell, but shown from a widget.
        colname_tuples = [('Initial_Code', tr_lc_setup.tr('Input code')),
                          ('Initial_Label', tr_lc_setup.tr('Input class')),
                          ('Final_Label', tr_lc_setup.tr('Output class'))]
        self.colnames_json = [x[0] for x in colname_tuples]
        self.colnames_pretty = [x[1] for x in colname_tuples]

    def rowCount(self, parent):
        return len(self.classes)

    def columnCount(self, parent):
        return len(self.colnames_json)

    def data(self, index, role):
        if not index.isValid():
            return None
        elif role == QtCore.Qt.TextAlignmentRole and index.column() in [0, 2, 3]:
            return QtCore.Qt.AlignCenter
        elif role != QtCore.Qt.DisplayRole:
            return None
        return self.classes[index.row()].get(self.colnames_json[index.column()], '')

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if role == QtCore.Qt.DisplayRole and orientation == QtCore.Qt.Horizontal:
            return self.colnames_pretty[section]
        return QtCore.QAbstractTableModel.headerData(self, section, orientation, role)


# Function to read a file defining land cover aggegation
def read_class_file(f):
    if not os.access(f, os.R_OK):
        QtWidgets.QMessageBox.critical(None,
                tr_lc_setup.tr("Error"),
                tr_lc_setup.tr(u"Cannot read {}.".format(f)))
        return None

    with open(f) as class_file:
        classes = json.load(class_file)
    if (not isinstance(classes, list)
            or not len(classes) > 0
            or not isinstance(classes[0], dict)
            or 'Initial_Code' not in classes[0]
            or 'Final_Code' not in classes[0]
            or 'Final_Label' not in classes[0]):

        QtWidgets.QMessageBox.critical(None,
                                       tr_lc_setup.tr("Error"),
                                       tr_lc_setup.tr("{} does not appear to contain a valid class definition.".format(f)))
        return None
    else:
        log(u'Loaded class definition from {}'.format(f))
        return classes


class DlgCalculateLCSetAggregation(QtWidgets.QDialog, DlgCalculateLcSetAggregationUi):
    def __init__(self, default_classes, parent=None):
        super().__init__(parent)

        self.default_classes = default_classes

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
        f, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr('Select a land cover definition file'),
            conf.settings_manager.get_value(conf.Setting.DEFINITIONS_DIRECTORY),
            self.tr('Land cover definition (*.json)')
        )
        if f:
            if os.access(f, os.R_OK):
                conf.settings_manager.write_value(
                    conf.Setting.DEFINITIONS_DIRECTORY, os.path.dirname(f))
            else:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(u"Cannot read {}. Choose a different file.".format(f))
                )
        else:
            return
        classes = read_class_file(f)

        if classes:
            self.setup_class_table(classes)

    def btn_save_pressed(self):
        f, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            self.tr('Choose where to save this land cover definition'),
            conf.settings_manager.get_value(conf.Setting.DEFINITIONS_DIRECTORY),
            self.tr('Land cover definition (*.json)')
        )
        if f:
            if os.access(os.path.dirname(f), os.W_OK):
                conf.settings_manager.write_value(
                    conf.Setting.DEFINITIONS_DIRECTORY, os.path.dirname(f))
            else:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(u"Cannot write to {}. Choose a different file.".format(f)))
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
            out[initial_code] = final_classes[label_widget.currentText()]['value']
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
            this_out['Final_Label'] = final_classes[label_widget.currentText()]['label']
            this_out['Final_Code'] = final_classes[label_widget.currentText()]['value']

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
            final_code = final_classes[label_widget.currentText()]['value']
            out[0].append(initial_code)
            out[1].append(final_code)
        return out

    def setup_class_table(self, classes=[]):
        # Load the codes each class will be recoded to.
        # 
        # The "classes" parameter will include any mappings derived from a 
        # class definition file, or, in the case or reading in user land cover 
        # files, classes from the file itself.
        # 
        # The default codes stored in self.default_classes are derived either 
        # from the data/land_cover_classes_ESA_to_IPCC.json file when this class is 
        # instantiated from the LCSetupWidget, or from the values within a 
        # custom user data file when this class is instantiated from the 
        # DlgDataIOImportLC class.
        if len(classes) > 0:
            input_codes = sorted([c['Initial_Code'] for c in classes])
            default_codes = sorted([c['Initial_Code'] for c in self.default_classes])
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

            # Setup a new classes list with the new class codes for all classes 
            # included in default classes, and any other class codes that are 
            # missing added from the default class list
            classes = [c for c in classes if c['Initial_Code'] in default_codes]
            classes.extend([c for c in self.default_classes if c['Initial_Code'] not in input_codes])
        else:
            classes = self.default_classes

        table_model = LCAggTableModel(classes, parent=self)
        proxy_model = QtCore.QSortFilterProxyModel()
        proxy_model.setSourceModel(table_model)
        self.remap_view.setModel(proxy_model)

        # Add selector in cell
        for row in range(0, len(classes)):
            lc_class_combo = LCClassComboBox()


            # Now Set the default final codes for each row. Note that the 
            # QComboBox entries are potentially translated, so need to link the 
            # translated names back to a particular code.
            
            # Get the input code for this row and the final label it should map 
            # to by default
            input_code = table_model.index(row, 0).data()
            final_label = [c['Final_Label'] for c in classes if c['Initial_Code'] == input_code][0]

            # Figure out which label translation this Final_Label (in English) 
            # is equivalent to
            label_to_label_tr = {final_classes[key]['label']: key for key in final_classes.keys()}
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


class LCDefineDegradationWidget(QtWidgets.QWidget, WidgetLcDefineDegradationUi):
    def __init__(self, parent=None):
        super().__init__(parent)

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
                line_edit.setValidator(QtGui.QRegExpValidator(QtCore.QRegExp("[-0+]")))
                line_edit.setAlignment(QtCore.Qt.AlignHCenter)
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
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        label_lc_baseline_year.setFont(font)
        self.lc_trans_table_layout.addWidget(label_lc_baseline_year, 1, 0, 1, 1, QtCore.Qt.AlignCenter)

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
        f, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr('Select a transition matrix definition file'),
            conf.settings_manager.get_value(conf.Setting.DEFINITIONS_DIRECTORY),
            self.tr('Transition matrix definition (*.json)')
        )
        if f:
            if os.access(f, os.R_OK):
                conf.settings_manager.write_value(
                    conf.Setting.DEFINITIONS_DIRECTORY, os.path.dirname(f))
            else:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(u"Cannot read {}. Choose a different file.".format(f))
                )
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
        f, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            self.tr('Choose where to save this transition matrix definition'),
            conf.settings_manager.get_value(conf.Setting.DEFINITIONS_DIRECTORY),
            self.tr('Transition matrix definition (*.json)')
        )
        if f:
            if os.access(os.path.dirname(f), os.W_OK):
                conf.settings_manager.write_value(
                    conf.Setting.DEFINITIONS_DIRECTORY, os.path.dirname(f))
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


class LCSetupWidget(QtWidgets.QWidget, WidgetLcSetupUi):
    use_custom_initial: data_io.WidgetDataIOSelectTELayerImport
    use_custom_final: data_io.WidgetDataIOSelectTELayerImport

    def __init__(self, parent=None):
        super().__init__(parent)

        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                               'data', 'gee_datasets.json')) as datasets_file:
            self.datasets = json.load(datasets_file)

        self.setupUi(self)

        default_class_file = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                         'data', 'land_cover_classes_ESA_to_IPCC.json')
        self.dlg_esa_agg = DlgCalculateLCSetAggregation(read_class_file(default_class_file), parent=self)

        lc_start_year = QtCore.QDate(self.datasets['Land cover']['ESA CCI']['Start year'], 1, 1)
        lc_end_year = QtCore.QDate(self.datasets['Land cover']['ESA CCI']['End year'], 12, 31)
        self.use_esa_bl_year.setMinimumDate(lc_start_year)
        self.use_esa_bl_year.setMaximumDate(lc_end_year)
        self.use_esa_tg_year.setMinimumDate(lc_start_year)
        self.use_esa_tg_year.setMaximumDate(lc_end_year)

        # Below is a bugfix for checkable group boxes created in QtDesigner - 
        # if they aren't checked by default in Qt Designer then checking them 
        # in the final gui doesn't enable their children. 
        self.groupBox_esa_agg.setChecked(False)

        self.use_esa_agg_edit.clicked.connect(self.esa_agg_custom_edit)

        # Ensure that if a LC layer is loaded in one box it shows up also in 
        # the other
        #self.use_custom_initial.layers_added.connect(self.use_custom_final.populate)
        #self.use_custom_final.layers_added.connect(self.use_custom_initial.populate)

    def get_initial_year(self):
        usable_band_info = self.use_custom_initial.get_usable_band_info()
        return usable_band_info.band_info.metadata["year"]

    def get_final_year(self):
        usable_band_info = self.use_custom_final.get_usable_band_info()
        return usable_band_info.band_info.metadata["year"]

    def esa_agg_custom_edit(self):
        self.dlg_esa_agg.exec_()

# LC widgets shared across dialogs
lc_define_deg_widget = LCDefineDegradationWidget()
lc_setup_widget = LCSetupWidget()
