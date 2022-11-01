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
import re
import typing
from copy import deepcopy
from enum import Enum
from pathlib import Path

from marshmallow.exceptions import ValidationError
from marshmallow_dataclass import dataclass
from qgis.core import QgsApplication
from qgis.PyQt import QtCore
from qgis.PyQt import QtGui
from qgis.PyQt import QtWidgets
from qgis.PyQt import uic
from qgis.utils import iface
from te_schemas.land_cover import LCClass
from te_schemas.land_cover import LCLegend
from te_schemas.land_cover import LCLegendNesting
from te_schemas.land_cover import LCTransitionDefinitionDeg
from te_schemas.land_cover import LCTransitionMatrixDeg
from te_schemas.land_cover import LCTransitionMeaningDeg

from . import conf
from . import data_io
from .jobs.manager import job_manager
from .logger import log


DlgCalculateLCSetAggregationUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateLCSetAggregation.ui")
)
DlgDataIOImportLCUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgDataIOImportLC.ui")
)
WidgetLcDefineDegradationUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/WidgetLCDefineDegradation.ui")
)

WidgetLandCoverSetupLocalExecutionUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/land_cover_setup_widget_local.ui")
)
WidgetLandCoverSetupRemoteExecutionUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/land_cover_setup_widget.ui")
)


class tr_lc_setup(object):
    def tr(message):
        return QtCore.QCoreApplication.translate("tr_lc_setup", message)


tr_dict = {
    "No data": tr_lc_setup.tr("No data"),
    "Tree-covered": tr_lc_setup.tr("Tree-covered"),
    "Grassland": tr_lc_setup.tr("Grassland"),
    "Cropland": tr_lc_setup.tr("Cropland"),
    "Wetland": tr_lc_setup.tr("Wetland"),
    "Artificial": tr_lc_setup.tr("Artificial"),
    "Other land": tr_lc_setup.tr("Other land"),
    "Water body": tr_lc_setup.tr("Water body"),
    "Cropland, rainfed": tr_lc_setup.tr("Cropland, rainfed"),
    "Herbaceous cover": tr_lc_setup.tr("Herbaceous cover"),
    "Tree or shrub cover": tr_lc_setup.tr("Tree or shrub cover"),
    "Cropland, irrigated or post‐flooding": tr_lc_setup.tr(
        "Cropland, irrigated or post‐flooding"
    ),
    "Mosaic cropland (>50%) / natural vegetation (tree, shrub, herbaceous cover) (<50%)": tr_lc_setup.tr(
        "Mosaic cropland (>50%) / natural vegetation (tree, shrub, herbaceous cover) (<50%)"
    ),
    "Mosaic natural vegetation (tree, shrub, herbaceous cover) (>50%) / cropland (<50%)": tr_lc_setup.tr(
        "Mosaic natural vegetation (tree, shrub, herbaceous cover) (>50%) / cropland (<50%)"
    ),
    "Tree cover, broadleaved, evergreen, closed to open (>15%)": tr_lc_setup.tr(
        "Tree cover, broadleaved, evergreen, closed to open (>15%)"
    ),
    "Tree cover, broadleaved, deciduous, closed to open (>15%)": tr_lc_setup.tr(
        "Tree cover, broadleaved, deciduous, closed to open (>15%)"
    ),
    "Tree cover, broadleaved, deciduous, closed (>40%)": tr_lc_setup.tr(
        "Tree cover, broadleaved, deciduous, closed (>40%)"
    ),
    "Tree cover, broadleaved, deciduous, open (15‐40%)": tr_lc_setup.tr(
        "Tree cover, broadleaved, deciduous, open (15‐40%)"
    ),
    "Tree cover, needleleaved, evergreen, closed to open (>15%)": tr_lc_setup.tr(
        "Tree cover, needleleaved, evergreen, closed to open (>15%)"
    ),
    "Tree cover, needleleaved, evergreen, closed (>40%)": tr_lc_setup.tr(
        "Tree cover, needleleaved, evergreen, closed (>40%)"
    ),
    "Tree cover, needleleaved, evergreen, open (15‐40%)": tr_lc_setup.tr(
        "Tree cover, needleleaved, evergreen, open (15‐40%)"
    ),
    "Tree cover, needleleaved, deciduous, closed to open (>15%)": tr_lc_setup.tr(
        "Tree cover, needleleaved, deciduous, closed to open (>15%)"
    ),
    "Tree cover, needleleaved, deciduous, closed (>40%)": tr_lc_setup.tr(
        "Tree cover, needleleaved, deciduous, closed (>40%)"
    ),
    "Tree cover, needleleaved, deciduous, open (15‐40%)": tr_lc_setup.tr(
        "Tree cover, needleleaved, deciduous, open (15‐40%)"
    ),
    "Tree cover, mixed leaf type (broadleaved and needleleaved)": tr_lc_setup.tr(
        "Tree cover, mixed leaf type (broadleaved and needleleaved)"
    ),
    "Mosaic tree and shrub (>50%) / herbaceous cover (<50%)": tr_lc_setup.tr(
        "Mosaic tree and shrub (>50%) / herbaceous cover (<50%)"
    ),
    "Mosaic herbaceous cover (>50%) / tree and shrub (<50%)": tr_lc_setup.tr(
        "Mosaic herbaceous cover (>50%) / tree and shrub (<50%)"
    ),
    "Shrubland": tr_lc_setup.tr("Shrubland"),
    "Evergreen shrubland": tr_lc_setup.tr("Evergreen shrubland"),
    "Deciduous shrubland": tr_lc_setup.tr("Deciduous shrubland"),
    "Grassland": tr_lc_setup.tr("Grassland"),
    "Lichens and mosses": tr_lc_setup.tr("Lichens and mosses"),
    "Sparse vegetation (tree, shrub, herbaceous cover) (<15%)": tr_lc_setup.tr(
        "Sparse vegetation (tree, shrub, herbaceous cover) (<15%)"
    ),
    "Sparse tree (<15%)": tr_lc_setup.tr("Sparse tree (<15%)"),
    "Sparse shrub (<15%)": tr_lc_setup.tr("Sparse shrub (<15%)"),
    "Sparse herbaceous cover (<15%)": tr_lc_setup.tr("Sparse herbaceous cover (<15%)"),
    "Tree cover, flooded, fresh or brakish water": tr_lc_setup.tr(
        "Tree cover, flooded, fresh or brakish water"
    ),
    "Tree cover, flooded, saline water": tr_lc_setup.tr(
        "Tree cover, flooded, saline water"
    ),
    "Shrub or herbaceous cover, flooded, fresh/saline/brakish water": tr_lc_setup.tr(
        "Shrub or herbaceous cover, flooded, fresh/saline/brakish water"
    ),
    "Urban areas": tr_lc_setup.tr("Urban areas"),
    "Bare areas": tr_lc_setup.tr("Bare areas"),
    "Consolidated bare areas": tr_lc_setup.tr("Consolidated bare areas"),
    "Unconsolidated bare areas": tr_lc_setup.tr("Unconsolidated bare areas"),
    "Water bodies": tr_lc_setup.tr("Water bodies"),
    "Permanent snow and ice": tr_lc_setup.tr("Permanent snow and ice"),
}

# TODO: Finish this - probably makes more sense to do it by subclassing dict, or see
# here: https://stackoverflow.com/questions/3387691/how-to-perfectly-override-a-dict
def _tr_cover_class(translations):
    """
    Handle translation of cover class names preceded by numeric codes

    Some cover class names are preceded by numeric codes. Translate these by stripping
    the code, finding the translation, and then re-adding the code.
    """
    label = re.sub("^-?[0-9]* - ", "", item["label"])
    code = re.sub(" - .*$", "", item["label"])

    translations.get()
    nesting.translate(tr_dict)


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    # TODO: This was QPyNullVariant under pyqt4 - check the below works on pyqt5

    if isinstance(obj, QtCore.QJsonValue.Null):
        return None
    raise TypeError("Type {} not serializable".format(type(obj)))


class RotatedHeaderView(QtWidgets.QHeaderView):
    def __init__(self, orientation, parent=None):
        super(RotatedHeaderView, self).__init__(orientation, parent)
        self.setMinimumSectionSize(20)

    def paintSection(self, painter, rect, logicalIndex):
        painter.save()
        # translate the painter such that rotate will rotate around the correct point
        painter.translate(rect.x() + rect.width(), rect.y())
        painter.rotate(90)
        # and have parent code paint at this location
        newrect = QtCore.QRect(0, 0, rect.height(), rect.width())
        super(RotatedHeaderView, self).paintSection(painter, newrect, logicalIndex)
        painter.restore()

    def minimumSizeHint(self):
        size = super(RotatedHeaderView, self).minimumSizeHint()
        size.transpose()
        return size

    def sectionSizeFromContents(self, logicalIndex):
        size = super(RotatedHeaderView, self).sectionSizeFromContents(logicalIndex)
        size.transpose()
        return size


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
        if self.text() == "-":
            self.setStyleSheet(
                "QLineEdit {background: #9B2779;} QLineEdit:hover {border: 1px solid gray; background: #9B2779;}"
            )
        elif self.text() == "+":
            self.setStyleSheet(
                "QLineEdit {background: #006500;} QLineEdit:hover {border: 1px solid gray; background: #006500;}"
            )
        else:
            self.setStyleSheet(
                "QLineEdit {background: #FFFFE0;} QLineEdit:hover {border: 1px solid gray; background: #FFFFE0;}"
            )

    def focusInEvent(self, e):
        super(TransMatrixEdit, self).focusInEvent(e)
        self.selectAll()


class LCClassComboBox(QtWidgets.QComboBox):
    def __init__(self, nesting=None, parent=None):
        super(LCClassComboBox, self).__init__(parent)
        self._nesting = nesting

        self.currentIndexChanged.connect(self.index_changed)

        # Add the translations of the item labels in order of their codes
        if self._nesting is not None:
            self.update_nesting()

    @property
    def nesting(self):
        return self._nesting

    @nesting.setter
    def nesting(self, lc_nesting):
        self._nesting = lc_nesting
        self.update_nesting()

    def update_nesting(self):
        # Adds LC cover classes defined in nesting.
        if self._nesting is None:
            return

        self.blockSignals(True)
        self.addItems(
            [c.name_long for c in self._nesting.parent.orderByCode().key_with_nodata()]
        )
        self.blockSignals(False)

        for n in range(0, len(self._nesting.parent.key_with_nodata())):
            lcc = self._nesting.parent.class_by_name_long(
                self.itemData(n, QtCore.Qt.DisplayRole)
            )
            if lcc is None:
                continue

            color = lcc.color
            self.setItemData(n, QtGui.QColor(color), QtCore.Qt.BackgroundRole)

            if color == "#000000":
                self.setItemData(n, QtGui.QColor("#FFFFFF"), QtCore.Qt.ForegroundRole)
            else:
                self.setItemData(n, QtGui.QColor("#000000"), QtCore.Qt.ForegroundRole)

        self.index_changed()

    def index_changed(self, value=-1):
        lcc = self._nesting.parent.class_by_name_long(self.currentText())
        if lcc is None:
            # Clear stylesheet
            self.setStyleSheet("")
            return

        color = lcc.color
        if color == "#000000":
            self.setStyleSheet(
                "QComboBox:editable {{background-color: {}; color: #FFFFFF;}}".format(
                    color
                )
            )
        else:
            self.setStyleSheet(
                "QComboBox:editable {{background-color: {};}}".format(color)
            )

    def get_current_class(self):
        return self._nesting.parent.classByNameLong(self.currentText())


class LCAggTableModel(QtCore.QAbstractTableModel):
    def __init__(self, nesting, parent=None, child_label_col=True, *args):
        QtCore.QAbstractTableModel.__init__(self, parent, *args)
        self.nesting = nesting

        # Column names as tuples with json name in [0], pretty name in [1]
        # Note that the columns with json names set to to INVALID aren't loaded
        # into the shell, but shown from a widget.
        colname_tuples = [
            ("Child_Code", tr_lc_setup.tr("Input code")),
            ("Child_Label", tr_lc_setup.tr("Input class")),
            ("Parent_Label", tr_lc_setup.tr("Output class")),
        ]
        if not child_label_col:
            colname_tuples.pop(1)
        self.colnames_json = [x[0] for x in colname_tuples]
        self.colnames_pretty = [x[1] for x in colname_tuples]

    def rowCount(self, parent=None):
        return len(self.nesting.child.key_with_nodata())

    def columnCount(self, parent=None):
        return len(self.colnames_json)

    def child_code_col(self):
        return self.colnames_json.index("Child_Code")

    def child_label_col(self):
        try:
            return self.colnames_json.index("Child_Label")
        except ValueError:
            return None

    def parent_label_col(self):
        return self.colnames_json.index("Parent_Label")

    def data(self, index, role):
        if not index.isValid():
            return None
        elif (
            role == QtCore.Qt.TextAlignmentRole
            and index.column() != self.child_label_col()
        ):
            return QtCore.Qt.AlignCenter
        elif role != QtCore.Qt.DisplayRole:
            return None
        col_name = self.colnames_json[index.column()]
        initial_class = self.nesting.child.key_with_nodata()[index.row()]

        if col_name == "Child_Code":
            return initial_class.code
        elif col_name == "Child_Label":
            return initial_class.name_long
        elif col_name == "Parent_Label":
            return self.nesting.parentClassForChild(initial_class).name_long

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if role == QtCore.Qt.DisplayRole and orientation == QtCore.Qt.Horizontal:
            return self.colnames_pretty[section]

        return QtCore.QAbstractTableModel.headerData(self, section, orientation, role)


def read_lc_nesting_file(f):
    if not os.access(f, os.R_OK):
        QtWidgets.QMessageBox.critical(
            None, tr_lc_setup.tr("Error"), tr_lc_setup.tr("Cannot read {}.".format(f))
        )

        return None

    try:
        with open(f) as nesting_file:
            nesting = LCLegendNesting.Schema().loads(nesting_file.read())
    except ValidationError as e:
        log("Error loading land cover legend " f"nesting definition from {f}: {e}")
        QtWidgets.QMessageBox.critical(
            None,
            tr_lc_setup.tr("Error"),
            tr_lc_setup.tr(
                f"{f} does not appear to contain a valid land cover legend "
                f"nesting definition: {e}"
            ),
        )

        return None
    else:
        log("Loaded land cover legend nesting definition from {}".format(f))
        nesting.translate(tr_dict)
        return nesting


def read_lc_matrix_file(f):
    if not os.access(f, os.R_OK):
        QtWidgets.QMessageBox.critical(
            None, tr_lc_setup.tr("Error"), tr_lc_setup.tr("Cannot read {}.".format(f))
        )

        return None

    try:
        with open(f) as matrix_file:
            matrix = LCTransitionDefinitionDeg.Schema().loads(matrix_file.read())
    except ValidationError as e:
        log(f"Error loading land cover transition matrix from {f}: {e}")
        QtWidgets.QMessageBox.critical(
            None,
            tr_lc_setup.tr("Error"),
            tr_lc_setup.tr(
                f"{f} does not appear to contain a valid land cover "
                f"transition matrix definition: {e}"
            ),
        )

        return None
    else:
        log(f"Loaded land cover transition matrix definition from {f}")
        matrix.translate(tr_dict)
        return matrix


def get_default_ipcc_nesting():
    nesting = read_lc_nesting_file(
        os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            "data",
            "land_cover_nesting_unccd_esa.json",
        )
    )
    nesting.child = deepcopy(nesting.parent)
    nesting.nesting = {c.code: c.code for c in nesting.parent.key}
    return nesting


def get_default_esa_nesting():
    return read_lc_nesting_file(
        os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            "data",
            "land_cover_nesting_unccd_esa.json",
        )
    )


def ipcc_lc_nesting_to_settings(nesting: LCLegendNesting):
    conf.settings_manager.write_value(
        conf.Setting.LC_IPCC_NESTING, LCLegendNesting.Schema().dumps(nesting)
    )


def ipcc_lc_nesting_from_settings() -> LCLegendNesting:
    nesting_str = conf.settings_manager.get_value(conf.Setting.LC_IPCC_NESTING)
    if nesting_str == "":
        return None

    return LCLegendNesting.Schema().loads(nesting_str)


def esa_lc_nesting_to_settings(nesting: LCLegendNesting):
    conf.settings_manager.write_value(
        conf.Setting.LC_ESA_NESTING, LCLegendNesting.Schema().dumps(nesting)
    )


def esa_lc_nesting_from_settings() -> LCLegendNesting:
    nesting_str = conf.settings_manager.get_value(conf.Setting.LC_ESA_NESTING)
    if nesting_str == "":
        return None

    return LCLegendNesting.Schema().loads(nesting_str)


def _get_default_matrix():
    return read_lc_matrix_file(
        os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            "data",
            f"land_cover_transition_matrix_UNCCD.json",
        )
    )


def get_trans_matrix(get_default=False, save_settings=True):

    if not get_default:
        log("Loading land cover degradation matrix from settings")
        matrix = trans_matrix_from_settings()
    else:
        matrix = None

    if matrix is None:
        log("Land cover degradation matrix is None")
        matrix = _get_default_matrix()
        nesting = ipcc_lc_nesting_from_settings()
        definitions = []
        for c_initial in nesting.child.key:
            for c_final in nesting.child.key:
                definition = deepcopy(
                    matrix.get_definition(
                        nesting.parent_for_child(c_initial),
                        nesting.parent_for_child(c_final),
                    )
                )
                definition.initial = c_initial
                definition.final = c_final
                definitions.append(definition)
        matrix.definitions = LCTransitionMatrixDeg(
            name="Degradation matrix", transitions=definitions
        )
        matrix.legend = nesting.child
        matrix.name = "Custom transition matrix"

        if matrix and save_settings:
            trans_matrix_to_settings(matrix)
    else:
        matrix = LCTransitionDefinitionDeg.Schema().loads(matrix)

    return matrix


def trans_matrix_from_settings() -> str:
    matrix = QtCore.QSettings().value("LDMP/land_cover_deg_trans_matrix", None)
    return matrix


def trans_matrix_to_settings(matrix: LCTransitionDefinitionDeg):
    QtCore.QSettings().setValue(
        "LDMP/land_cover_deg_trans_matrix",
        LCTransitionDefinitionDeg.Schema().dumps(matrix),
    )


class DlgCalculateLCSetAggregationBase(
    QtWidgets.QDialog, DlgCalculateLCSetAggregationUi
):
    def __init__(self, parent=None, nesting=None):
        super().__init__(parent)

        self.setupUi(self)

        self.btn_save.clicked.connect(self.btn_save_pressed)
        self.btn_load.clicked.connect(self.btn_load_pressed)
        self.btn_reset.clicked.connect(self.reset_nesting_table)
        self.btn_close.clicked.connect(self.btn_close_pressed)

        # Setup the class table so that the table is defined when a user first
        # loads the dialog
        if nesting:
            self.nesting = nesting
        else:
            self.nesting = self.get_nesting()
        self.setup_nesting(self.nesting)

    def btn_close_pressed(self):
        self.update_nesting_from_widget()
        self.close()

    def btn_load_pressed(self):
        f, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr("Select a land cover definition file"),
            conf.settings_manager.get_value(conf.Setting.DEFINITIONS_DIRECTORY),
            self.tr("Land cover definition (*.json)"),
        )

        if f:
            if os.access(f, os.R_OK):
                conf.settings_manager.write_value(
                    conf.Setting.DEFINITIONS_DIRECTORY, os.path.dirname(f)
                )
            else:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr("Cannot read {}. Choose a different file.".format(f)),
                )
        else:
            return
        nesting = read_lc_nesting_file(f)

        if nesting:
            log(f"Loaded nesting from {f}")
            self.setup_nesting(nesting)

    def btn_save_pressed(self):
        self.update_nesting_from_widget()

        f, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            self.tr("Choose where to save this land cover definition"),
            conf.settings_manager.get_value(conf.Setting.DEFINITIONS_DIRECTORY),
            self.tr("Land cover definition (*.json)"),
        )

        if f:
            if os.access(os.path.dirname(f), os.W_OK):
                conf.settings_manager.write_value(
                    conf.Setting.DEFINITIONS_DIRECTORY, os.path.dirname(f)
                )
            else:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr("Cannot write to {}. Choose a different file.".format(f)),
                )

                return

            nesting = self.get_nesting()
            with open(f, "w") as outfile:
                json.dump(
                    LCLegendNesting.Schema().dump(nesting),
                    outfile,
                    sort_keys=True,
                    indent=4,
                    separators=(",", ":"),
                    default=json_serial,
                )

    def update_nesting_from_widget(self):
        nesting = self.get_nesting()
        for row in range(0, self.table_model.rowCount()):
            child_code = self.table_model.index(
                row, self.table_model.child_code_col()
            ).data()
            child_class = nesting.child.classByCode(child_code)
            new_parent_class = self.remap_view.indexWidget(
                self.proxy_model.index(row, self.table_model.parent_label_col())
            ).get_current_class()

            nesting.update_parent(child_class, new_parent_class)
        self.set_nesting(nesting)
        self.nesting = deepcopy(nesting)

    def reset_nesting_table(self, get_default=False):
        if get_default:
            self.nesting = self.get_nesting()
        self.setup_nesting(nesting_input=self.nesting)


class DlgCalculateLCSetAggregationESA(DlgCalculateLCSetAggregationBase):
    def __init__(self, parent=None):
        super().__init__(parent)

    def set_nesting(self, nesting):
        self.nesting = nesting
        esa_lc_nesting_to_settings(nesting)

    def get_nesting(self):
        self.nesting = esa_lc_nesting_from_settings()
        return self.nesting

    def setup_nesting(self, nesting_input=None):
        # Load the codes each class will be recoded to.
        #
        # The "nesting_input" parameter will include any mappings derived from a
        # class definition file, or, in the case or reading in user land cover
        # files, nesting from the file itself.
        #
        # The default codes stored in self.nesting are derived either
        # from the data/land_cover_nesting_unccd_esa.json file when this class
        # is instantiated from the LCSetupWidget, or from the values within a
        # custom user data file when this class is instantiated from the
        # DlgDataIOImportLC class.

        if nesting_input:
            # All ESA codes need to be represented, and any non-ESA codes should be excluded
            child_legend = self.get_nesting().child
            valid_child_codes = sorted([c.code for c in child_legend.key])
            child_code_input = sorted([c.code for c in nesting_input.child.key])
            unnecessary_child_codes = sorted(
                [c for c in child_code_input if c not in valid_child_codes]
            )
            child_codes_missing_from_input = sorted(
                [c for c in valid_child_codes if c not in child_code_input]
            )

            if len(unnecessary_child_codes) > 0:
                QtWidgets.QMessageBox.warning(
                    None,
                    self.tr("Warning"),
                    self.tr(
                        f"Some of the class codes ({unnecessary_child_codes!r}) "
                        "in the definition file do not appear in the chosen data "
                        "file."
                    ),
                )
                return

            if len(child_codes_missing_from_input) > 0:
                QtWidgets.QMessageBox.warning(
                    None,
                    self.tr("Warning"),
                    self.tr(
                        f"Some of the class codes ({child_codes_missing_from_input!r}) "
                        "in the data file do not appear in the chosen definition "
                        "file."
                    ),
                )
                return

            # Remove unnecessary classes from the input child legend
            nesting_input.child.key = [
                c for c in nesting_input.child.key if c.code in valid_child_codes
            ]

            # Supplement input child legend with missing classes
            nesting_input.child.key.extend(
                [
                    c
                    for c in child_legend.key
                    if c.code in child_codes_missing_from_input
                ]
            )

            # Remove dropped classes from the nesting dict
            new_child_codes = [c.code for c in nesting_input.child.key]
            new_nesting_dict = {}

            for key, values in nesting_input.nesting.items():
                new_nesting_dict.update(
                    {key: [v for v in values if v in new_child_codes]}
                )

            # And add into the nesting dict any classes that are in the data
            # but were missing from the input, including the child legend no
            # data code (it should be nested under parent nodata as well)
            if (
                nesting_input.child.nodata
                and nesting_input.child.nodata.code
                not in child_codes_missing_from_input
            ):
                child_codes_missing_from_input.append(nesting_input.child.nodata.code)
            new_nesting_dict.update(
                {
                    nesting_input.parent.nodata.code: new_nesting_dict.get(
                        nesting_input.parent.nodata.code, []
                    )
                    + child_codes_missing_from_input
                }
            )

            nesting_input.nesting = new_nesting_dict

        self.set_nesting(nesting_input)
        self.setup_nesting_table()

    def setup_nesting_table(self):
        self.table_model = LCAggTableModel(
            self.nesting,
            parent=self,
            child_label_col=True,
        )
        self.proxy_model = QtCore.QSortFilterProxyModel()
        self.proxy_model.setSourceModel(self.table_model)
        self.remap_view.setModel(self.proxy_model)

        # Add selector in cell

        for row in range(0, len(self.nesting.child.key_with_nodata())):
            # Get the input code for this row and the final label it should map
            # to by default
            child_code = self.table_model.index(
                row, self.table_model.child_code_col()
            ).data()
            parent_class = [
                self.nesting.parentClassForChild(c)
                for c in self.nesting.child.key_with_nodata()
                if c.code == child_code
            ][0]

            lc_class_combo = LCClassComboBox(self.nesting)

            # Find the index in the combo box of this translated final label
            ind = lc_class_combo.findText(parent_class.name_long)

            if ind != -1:
                lc_class_combo.setCurrentIndex(ind)
            self.remap_view.setIndexWidget(
                self.proxy_model.index(row, self.table_model.parent_label_col()),
                lc_class_combo,
            )

        self.remap_view.horizontalHeader().setSectionResizeMode(
            self.table_model.child_code_col(), QtWidgets.QHeaderView.ResizeToContents
        )
        # This column is hidden for CUSTOM_TO_CUSTOM transitions
        self.remap_view.horizontalHeader().setSectionResizeMode(
            self.table_model.child_label_col(), QtWidgets.QHeaderView.Stretch
        )
        self.remap_view.horizontalHeader().setSectionResizeMode(
            self.table_model.parent_label_col(),
            QtWidgets.QHeaderView.ResizeToContents,
        )

        self.remap_view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)

        return True


class DlgCalculateLCSetAggregationCustom(DlgCalculateLCSetAggregationBase):
    def __init__(self, parent=None, nesting=None):
        super().__init__(parent, nesting)

    def set_nesting(self, nesting):
        self.nesting = nesting

    def get_nesting(self):
        return self.nesting

    def setup_nesting(self, nesting_input=None):
        if nesting_input:
            # Get the parent custom legend from the IPCC nesting (the custom legend
            # is a child of the IPCC legend)
            default_parent_legend = ipcc_lc_nesting_from_settings().child
            valid_parent_codes = sorted([c.code for c in default_parent_legend.key])
            parent_code_input = sorted([c.code for c in nesting_input.parent.key])
            unnecessary_parent_codes = sorted(
                [c for c in parent_code_input if c not in valid_parent_codes]
            )
            parent_codes_missing_from_input = sorted(
                [c for c in valid_parent_codes if c not in parent_code_input]
            )

            if len(unnecessary_parent_codes) > 0:
                QtWidgets.QMessageBox.warning(
                    None,
                    self.tr("Warning"),
                    self.tr(
                        f"Some of the parent classes ({unnecessary_parent_codes!r}) "
                        "in the definition file are not listed in the current class "
                        "legend. These classes will be ignored."
                    ),
                )

            # Remove any classes from the input parent legend that aren't in the current
            # custom legend
            nesting_input.parent.key = [
                c for c in nesting_input.parent.key if c.code in valid_parent_codes
            ]
            # Remove invalid parent classes from the nesting dict
            nesting_input.nesting = {
                key: values
                for key, values in nesting_input.nesting.items()
                if key in valid_parent_codes + [nesting_input.parent.nodata.code]
            }
            # Nest under nodata any child classes that were nested under invalid
            # parent classes
            child_codes_in_nesting_dict = [
                value for values in nesting_input.nesting.values() for value in values
            ]

        if conf.settings_manager.get_value(conf.Setting.DEBUG):
            log(f"nesting is {nesting_input.nesting}")
            log(f"parent codes are {nesting_input.parent.codes()}")
            log(f"child codes are {nesting_input.child.codes()}")
        self.set_nesting(nesting_input)
        self.setup_nesting_table()

    def setup_nesting_table(self):
        self.table_model = LCAggTableModel(
            self.nesting,
            parent=self,
            child_label_col=False,
        )
        self.proxy_model = QtCore.QSortFilterProxyModel()
        self.proxy_model.setSourceModel(self.table_model)
        self.remap_view.setModel(self.proxy_model)

        # Add selector in cell

        for row in range(0, len(self.nesting.child.key_with_nodata())):
            # Get the input code for this row and the final label it should map
            # to by default
            child_code = self.table_model.index(
                row, self.table_model.child_code_col()
            ).data()
            parent_class = [
                self.nesting.parentClassForChild(c)
                for c in self.nesting.child.key_with_nodata()
                if c.code == child_code
            ][0]

            lc_class_combo = LCClassComboBox(self.nesting)

            # Find the index in the combo box of this translated final label
            ind = lc_class_combo.findText(parent_class.name_long)

            if ind != -1:
                lc_class_combo.setCurrentIndex(ind)
            self.remap_view.setIndexWidget(
                self.proxy_model.index(row, self.table_model.parent_label_col()),
                lc_class_combo,
            )

        self.remap_view.horizontalHeader().setSectionResizeMode(
            self.table_model.child_code_col(), QtWidgets.QHeaderView.ResizeToContents
        )
        self.remap_view.horizontalHeader().setSectionResizeMode(
            self.table_model.parent_label_col(), QtWidgets.QHeaderView.Stretch
        )

        self.remap_view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)

        return True


class DlgDataIOImportLC(data_io.DlgDataIOImportBase, DlgDataIOImportLCUi):
    def __init__(self, parent=None):
        super().__init__(parent)

        # This needs to be inserted after the lc definition widget but before
        # the button box with ok/cancel
        self.output_widget = data_io.ImportSelectRasterOutput()
        self.verticalLayout.insertWidget(2, self.output_widget)

        self.input_widget.inputFileChanged.connect(self.input_changed)
        self.input_widget.inputTypeChanged.connect(self.input_changed)

        self.checkBox_use_sample.stateChanged.connect(self.clear_dlg_agg)

        self.input_widget.lineEdit_nodata.setValidator(QtGui.QIntValidator())

        self.btn_agg_edit_def.clicked.connect(self.agg_edit)
        self.btn_agg_edit_def.setEnabled(False)

        self.dlg_agg = None

    def showEvent(self, event):
        super(DlgDataIOImportLC, self).showEvent(event)

        # Reset flags to avoid reloading of unique values when files haven't
        # changed:
        self.last_raster = None
        self.last_band_number = None
        self.last_vector = None
        self.idx = None

    def done(self, value):
        if value == QtWidgets.QDialog.Accepted:
            self.validate_input(value)
        else:
            super().done(value)

    def validate_input(self, value):
        if self.output_widget.lineEdit_output_file.text() == "":
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"), self.tr("Choose an output file.")
            )

            return

        if not self.dlg_agg:
            QtWidgets.QMessageBox.information(
                None,
                self.tr("No definition set"),
                self.tr(
                    'Click "Edit Definition" to define the land cover definition before exporting.'
                ),
            )

            return

        if (
            self.input_widget.spinBox_data_year.text()
            == self.input_widget.spinBox_data_year.specialValueText()
        ):
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"), self.tr("Enter the year of the input data.")
            )

            return

        ret = super(DlgDataIOImportLC, self).validate_input(value)

        if not ret:
            return

        super(DlgDataIOImportLC, self).done(value)

        self.ok_clicked()

    def clear_dlg_agg(self):
        self.dlg_agg = None

    def input_changed(self, valid):
        if valid:
            self.btn_agg_edit_def.setEnabled(True)
        else:
            self.btn_agg_edit_def.setEnabled(False)
        self.clear_dlg_agg()

        if self.input_widget.radio_raster_input.isChecked():
            self.checkBox_use_sample.setEnabled(True)
            self.checkBox_use_sample_description.setEnabled(True)
        else:
            self.checkBox_use_sample.setEnabled(False)
            self.checkBox_use_sample_description.setEnabled(False)

    def load_agg(self, values, child_nodata_code=-32768):
        # Set all of the classes to no data by default, and default to nesting
        # under the current custom legend (which may be the default IPCC legend
        # in any case)
        default_nesting = ipcc_lc_nesting_from_settings()

        # From the default nesting class instance, setup the actual nesting
        # dictionary so that all the default classes have no values nested
        # under them, except for no data - nest all of the values in this
        # dataset under nodata (-32768 for the default data) until the user
        # determines otherwise. Note we use the "child" legend in case the
        # user has defined a custom legend (which would be stored there).
        nest = {c: [] for c in default_nesting.child.codes()}
        # The nodata code in the data being imported needs to be handled.
        # Nest this under the parent nodata code as well.

        if child_nodata_code not in values:
            values = values + [child_nodata_code]
        nest.update({default_nesting.child.nodata.code: values})

        nesting = LCLegendNesting(
            parent=default_nesting.child,
            child=LCLegend(
                name="Default remap",
                key=[
                    LCClass(value, str(value))
                    for value in sorted(values)
                    if value != child_nodata_code
                ],
                nodata=LCClass(child_nodata_code, "No data"),
            ),
            nesting=nest,
        )
        self.dlg_agg = DlgCalculateLCSetAggregationCustom(parent=self, nesting=nesting)

    def agg_edit(self):
        if self.input_widget.radio_raster_input.isChecked():
            f = self.input_widget.lineEdit_raster_file.text()
            band_number = int(self.input_widget.comboBox_bandnumber.currentText())

            if not self.dlg_agg or (
                self.last_raster != f or self.last_band_number != band_number
            ):
                values = data_io.get_unique_values_raster(
                    f,
                    int(self.input_widget.comboBox_bandnumber.currentText()),
                    self.checkBox_use_sample.isChecked(),
                )

                if not values:
                    QtWidgets.QMessageBox.critical(
                        None,
                        self.tr("Error"),
                        self.tr(
                            "Error reading data. Trends.Earth supports a maximum "
                            "of 38 different land cover classes"
                        ),
                    )

                    return
                self.last_raster = f
                self.last_band_number = band_number
                self.load_agg(values, child_nodata_code=self.get_nodata_value())
        else:
            f = self.input_widget.lineEdit_vector_file.text()
            l = self.input_widget.get_vector_layer()
            idx = l.fields().lookupField(
                self.input_widget.comboBox_fieldname.currentText()
            )

            if not self.dlg_agg or (self.last_vector != f or self.last_idx != idx):
                values = data_io.get_unique_values_vector(
                    l, self.input_widget.comboBox_fieldname.currentText()
                )

                if not values:
                    QtWidgets.QMessageBox.critical(
                        None,
                        self.tr("Error"),
                        self.tr(
                            "Error reading data. Trends.Earth supports a maximum "
                            "of 38 different land cover classes"
                        ),
                    )

                    return
                self.last_vector = f
                self.last_idx = idx
                self.load_agg(values, child_nodata_code=self.get_nodata_value())
        self.dlg_agg.exec_()

    def get_nodata_value(self):
        return int(self.input_widget.lineEdit_nodata.text())

    def ok_clicked(self):
        out_file = self.output_widget.lineEdit_output_file.text()

        if self.input_widget.radio_raster_input.isChecked():
            in_file = self.input_widget.lineEdit_raster_file.text()
            remap_ret = self.remap_raster(
                in_file, out_file, self.dlg_agg.nesting.get_list()
            )
        else:
            attribute = self.input_widget.comboBox_fieldname.currentText()
            l = self.input_widget.get_vector_layer()
            remap_ret = self.remap_vector(
                l, out_file, self.dlg_agg.nesting.nesting, attribute
            )

        if not remap_ret:
            return False

        job = job_manager.create_job_from_dataset(
            Path(out_file),
            "Land cover",
            {
                "year": int(self.input_widget.spinBox_data_year.text()),
                "nesting": LCLegendNesting.Schema().dumps(
                    ipcc_lc_nesting_from_settings()
                ),
                "source": "custom data",
            },
        )
        job_manager.import_job(job, Path(out_file))


class LCDefineDegradationWidget(QtWidgets.QWidget, WidgetLcDefineDegradationUi):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setupUi(self)

        # UI initialization
        reload_icon = QgsApplication.instance().getThemeIcon("mActionReload.svg")
        self.btn_transmatrix_reset.setIcon(reload_icon)

        load_table_icon = QgsApplication.instance().getThemeIcon("mActionFileOpen.svg")
        self.btn_transmatrix_loadfile.setIcon(load_table_icon)

        save_table_icon = QgsApplication.instance().getThemeIcon("mActionFileSave.svg")
        self.btn_transmatrix_savefile.setIcon(save_table_icon)

        trans_matrix = get_trans_matrix()

        self.setup_deg_def_matrix(trans_matrix.legend)

        self.set_trans_matrix()

        # Setup the vertical label for the rows of the table
        label_lc_baseline_year = VerticalLabel(self)
        label_lc_baseline_year.setText(self.tr("Land cover in initial year "))
        sizePolicy = QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Minimum
        )
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(
            self.label_lc_target_year.sizePolicy().hasHeightForWidth()
        )
        label_lc_baseline_year.setSizePolicy(sizePolicy)
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        label_lc_baseline_year.setFont(font)
        self.lc_trans_table_layout.addWidget(
            label_lc_baseline_year, 1, 0, 1, 1, QtCore.Qt.AlignCenter
        )

        self.btn_transmatrix_reset.clicked.connect(
            lambda: self.set_trans_matrix(get_default=False)
        )
        self.btn_transmatrix_loadfile.clicked.connect(self.trans_matrix_loadfile)
        self.btn_transmatrix_savefile.clicked.connect(self.trans_matrix_savefile)

        self.legend_deg.setStyleSheet(
            "QLineEdit {background: #9B2779;} QLineEdit:hover {border: 1px solid gray; background: #9B2779;}"
        )
        self.legend_imp.setStyleSheet(
            "QLineEdit {background: #006500;} QLineEdit:hover {border: 1px solid gray; background: #006500;}"
        )
        self.legend_stable.setStyleSheet(
            "QLineEdit {background: #FFFFE0;} QLineEdit:hover {border: 1px solid gray; background: #FFFFE0;}"
        )

    def setup_deg_def_matrix(self, legend):
        self.deg_def_matrix.setRowCount(len(legend.key))
        self.deg_def_matrix.setColumnCount(len(legend.key))
        self.deg_def_matrix.setHorizontalHeaderLabels(
            [c.get_name_short() for c in legend.key]
        )
        self.deg_def_matrix.setVerticalHeaderLabels(
            [c.get_name_short() for c in legend.key]
        )
        if len(legend.key) > 9:
            self.deg_def_matrix.setHorizontalHeader(
                RotatedHeaderView(QtCore.Qt.Horizontal, self.deg_def_matrix)
            )
        # else:
        #     self.deg_def_matrix.setHorizontalHeader(
        #         QtWidgets.QHeaderView(QtCore.Qt.Horizontal, self.deg_def_matrix)
        #     )

        for row in range(0, self.deg_def_matrix.rowCount()):
            for col in range(0, self.deg_def_matrix.columnCount()):
                line_edit = TransMatrixEdit()
                line_edit.setValidator(QtGui.QRegExpValidator(QtCore.QRegExp("[-0+]")))
                line_edit.setAlignment(QtCore.Qt.AlignHCenter)
                self.deg_def_matrix.setCellWidget(row, col, line_edit)

        self.deg_def_matrix.setStyleSheet("QTableWidget {border: 0px;}")
        self.deg_def_matrix.horizontalHeader().setStyleSheet(
            "QHeaderView::section {background-color: white;border: 0px;}"
        )
        self.deg_def_matrix.verticalHeader().setStyleSheet(
            "QHeaderView::section {background-color: white;border: 0px;}"
        )

        for row in range(0, self.deg_def_matrix.rowCount()):
            self.deg_def_matrix.horizontalHeader().setSectionResizeMode(
                row, QtWidgets.QHeaderView.Stretch
            )

        for col in range(0, self.deg_def_matrix.columnCount()):
            self.deg_def_matrix.verticalHeader().setSectionResizeMode(
                col, QtWidgets.QHeaderView.Stretch
            )

    def trans_matrix_loadfile(self):
        f, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr("Select a transition matrix definition file"),
            conf.settings_manager.get_value(conf.Setting.DEFINITIONS_DIRECTORY),
            self.tr("Transition matrix definition (*.json)"),
        )

        if f:
            if os.access(f, os.R_OK):
                conf.settings_manager.write_value(
                    conf.Setting.DEFINITIONS_DIRECTORY, os.path.dirname(f)
                )
            else:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr("Cannot read {}. Choose a different file.".format(f)),
                )
        else:
            return None

        matrix = read_lc_matrix_file(f)

        if not matrix:
            return None
        else:
            self.set_trans_matrix(matrix)

            return True

    def trans_matrix_savefile(self):
        f, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            self.tr("Choose where to save this transition matrix definition"),
            conf.settings_manager.get_value(conf.Setting.DEFINITIONS_DIRECTORY),
            self.tr("Transition matrix definition (*.json)"),
        )

        if f:
            if os.access(os.path.dirname(f), os.W_OK):
                conf.settings_manager.write_value(
                    conf.Setting.DEFINITIONS_DIRECTORY, os.path.dirname(f)
                )
            else:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr("Cannot write to {}. Choose a different file.".format(f)),
                )

                return

            with open(f, "w") as outfile:
                json.dump(
                    LCTransitionDefinitionDeg.Schema().dump(
                        self.get_trans_matrix_from_widget()
                    ),
                    outfile,
                    sort_keys=True,
                    indent=4,
                    separators=(",", ":"),
                    default=json_serial,
                )

    def set_trans_matrix(self, matrix=None, get_default=False):
        if not matrix:
            matrix = get_trans_matrix(get_default)
        QtCore.QSettings().setValue(
            "LDMP/land_cover_deg_trans_matrix",
            LCTransitionDefinitionDeg.Schema().dumps(matrix),
        )

        self.setup_deg_def_matrix(matrix.legend)

        for row in range(0, self.deg_def_matrix.rowCount()):
            initial_class = matrix.legend.key[row]

            for col in range(0, self.deg_def_matrix.columnCount()):
                final_class = matrix.legend.key[col]
                meaning = matrix.definitions.meaningByTransition(
                    initial_class, final_class
                )

                if meaning == "stable":
                    code = "0"
                elif meaning == "degradation":
                    code = "-"
                elif meaning == "improvement":
                    code = "+"
                else:
                    log(
                        'unrecognized transition meaning "{}" when setting transition matrix'.format(
                            meaning
                        )
                    )

                    return False
                self.deg_def_matrix.cellWidget(row, col).setText(code)

        return True

    def get_trans_matrix_from_widget(self):
        # Extract trans_matrix from the QTableWidget
        transitions = []
        trans_matrix = get_trans_matrix()

        for row in range(0, self.deg_def_matrix.rowCount()):
            for col in range(0, self.deg_def_matrix.columnCount()):
                val = self.deg_def_matrix.cellWidget(row, col).text()

                if val == "" or val == "0":
                    meaning = "stable"
                elif val == "-":
                    meaning = "degradation"
                elif val == "+":
                    meaning = "improvement"
                else:
                    log(
                        'unrecognized value "{}" when reading transition meaning from cellWidget'.format(
                            val
                        )
                    )
                    raise ValueError(
                        'unrecognized value "{}" when reading transition meaning from cellWidget'.format(
                            val
                        )
                    )
                transitions.append(
                    LCTransitionMeaningDeg(
                        trans_matrix.legend.key[row],
                        trans_matrix.legend.key[col],
                        meaning,
                    )
                )

        return LCTransitionDefinitionDeg(
            legend=trans_matrix.legend,
            name="Land cover transition definition matrix",
            definitions=LCTransitionMatrixDeg(
                name="Degradation matrix", transitions=transitions
            ),
        )


class LandCoverSetupLocalExecutionWidget(
    QtWidgets.QWidget, WidgetLandCoverSetupLocalExecutionUi
):
    initial_year_layer_cb: data_io.WidgetDataIOSelectTELayerImport
    target_year_layer_cb: data_io.WidgetDataIOSelectTELayerImport

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.initial_year_layer_cb.populate()
        self.target_year_layer_cb.populate()

    def get_initial_year(self):
        usable_band_info = self.initial_year_layer_cb.get_current_band()

        return usable_band_info.band_info.metadata["year"]

    def get_final_year(self):
        usable_band_info = self.target_year_layer_cb.get_current_band()

        return usable_band_info.band_info.metadata["year"]


class LandCoverSetupRemoteExecutionWidget(
    QtWidgets.QWidget, WidgetLandCoverSetupRemoteExecutionUi
):
    initial_year_la: QtWidgets.QLabel
    initial_year_de: QtWidgets.QDateEdit
    target_year_de: QtWidgets.QDateEdit
    target_year_la: QtWidgets.QLabel
    aggregation_method_pb: QtWidgets.QPushButton
    aggregation_dialog: QtWidgets.QDialog

    def __init__(
        self,
        parent=None,
        hide_min_year: typing.Optional[bool] = False,
        hide_max_year: typing.Optional[bool] = False,
        selected_min_year: typing.Optional[int] = 2001,
        selected_max_year: typing.Optional[int] = 2015,
    ):
        super().__init__(parent)
        self.setupUi(self)
        esa_cci_lc_conf = conf.REMOTE_DATASETS["Land cover"]["ESA CCI"]
        min_year = QtCore.QDate(esa_cci_lc_conf["Start year"], 1, 1)
        max_year = QtCore.QDate(esa_cci_lc_conf["End year"], 12, 31)
        self.initial_year_de.setMinimumDate(min_year)
        self.initial_year_de.setMaximumDate(max_year)
        self.target_year_de.setMinimumDate(min_year)
        self.target_year_de.setMaximumDate(max_year)
        self.initial_year_de.setDate(QtCore.QDate(selected_min_year, 1, 1))
        self.target_year_de.setDate(QtCore.QDate(selected_max_year, 12, 31))

        if hide_min_year:
            self.initial_year_la.hide()
            self.initial_year_de.hide()

        if hide_max_year:
            self.target_year_la.hide()
            self.target_year_de.hide()
        self.aggregation_method_pb.clicked.connect(self.open_aggregation_method_dialog)

        self.aggregation_dialog = DlgCalculateLCSetAggregationESA(parent=self)

    def open_aggregation_method_dialog(self):
        self.aggregation_dialog.exec_()


@dataclass
class LCClassInfo:
    """
    Land cover class information from editor
    """

    idx: int = -1
    lcc: LCClass = None
    parent: LCClass = None

    class Meta:
        ordered = True
        load_only = ["idx"]


class LccInfoUtils:
    """
    Helper for LCCInfo management operations.
    """

    CUSTOM_LEGEND_NAME = "Custom Land Cover"

    @staticmethod
    def save_settings(
        lcc_infos: typing.List["LCClassInfo"] = [], restore_default=True
    ) -> bool:
        """
        Saves list of LCClassInfo objects to settings but if settings is
        empty and 'restore_default' is True then it will restore the default
        UNCCD land cover classes.
        """
        if len(lcc_infos) == 0:
            conf.settings_manager.write_value(conf.Setting.LC_CLASSES, [])
            if restore_default:
                _ = get_trans_matrix(True)
                esa_lc_nesting_to_settings(get_default_esa_nesting())
                ipcc_lc_nesting_to_settings(get_default_ipcc_nesting())

            return True

        status = True
        try:
            infos = []
            for lcc in lcc_infos:
                lcc_str = LCClassInfo.Schema().dumps(lcc)
                infos.append(lcc_str)
            conf.settings_manager.write_value(conf.Setting.LC_CLASSES, infos)
        except ValidationError as ve:
            status = False
        except Exception as exc:
            status = False

        # Update transition matrix and land cover nesting with our new custom
        # classes.
        log(
            f"{LccInfoUtils.CUSTOM_LEGEND_NAME} - Saving LCCInfo to settings: "
            f"{status!s}"
        )
        if status:
            LccInfoUtils.sync_lc_nesting(lcc_infos)
            LccInfoUtils.sync_trans_matrix(lcc_infos)

        return status

    @staticmethod
    def load_settings() -> typing.Tuple[bool, typing.List["LCClassInfo"]]:
        """
        Loads LCCInfo objects from the settings.
        """
        lcc_infos_str = conf.settings_manager.get_value(conf.Setting.LC_CLASSES)
        lcc_infos = []
        status = True

        try:
            for lcc_info_str in lcc_infos_str:
                lcc_info = LCClassInfo.Schema().loads(lcc_info_str)
                lcc_infos.append(lcc_info)

        except ValidationError as ve:
            status = False

        except Exception as exc:
            status = False

        return status, lcc_infos

    @staticmethod
    def save_file(file_path: str, lcc_infos: typing.List["LCClassInfo"]) -> bool:
        # Saves the LC classes to JSON file.
        lc_cls_infos = []
        status = True
        try:
            for lcc in lcc_infos:
                lcc_dict = LCClassInfo.Schema().dump(lcc)
                lc_cls_infos.append(lcc_dict)
        except ValidationError as ve:
            status = False
        except Exception as exc:
            status = False

        if not status:
            return False

        fi = QtCore.QFileInfo(file_path)
        cls_dir = fi.dir().path()

        # Check write permissions
        if not os.access(cls_dir, os.W_OK):
            return False

        suffix = fi.suffix()
        if "json" not in suffix:
            file_path = f"{file_path}.json"

        with open(file_path, "w") as f:
            json.dump(lc_cls_infos, f, sort_keys=True, indent=4)

        return True

    @staticmethod
    def load_file(file_path: str) -> typing.Tuple[bool, typing.List["LCClassInfo"]]:
        # Load classes from file.
        fi = QtCore.QFileInfo(file_path)
        cls_dir = fi.dir().path()

        # Check read permissions
        if not os.access(cls_dir, os.R_OK):
            return False, []

        lc_classes = []
        status = True
        with open(file_path) as f:
            try:
                classes = json.load(f)
                for lcc in classes:
                    lcc_info = LCClassInfo.Schema().load(lcc)
                    lc_classes.append(lcc_info)
            except ValidationError as ve:
                log(f"ValidationError while loading {file_path}: {ve}")
                status = False
            except Exception as exc:
                log(f"Exception while loading {file_path}: {exc}")
                status = False

        if not status:
            return False, []

        return True, lc_classes

    @staticmethod
    def lcc_in_infos(
        lcc: LCClass, lcc_infos: typing.List["LCClassInfo"]
    ) -> typing.Tuple[bool, "LCClassInfo"]:
        """
        Checks if the given lc class is in the collection using
        code to compare.
        """
        match = [lcc_info for lcc_info in lcc_infos if lcc_info.lcc.code == lcc.code]

        return (True, match[0]) if len(match) > 0 else (False, None)

    @staticmethod
    def lc_nesting() -> LCLegendNesting:
        """
        Returns the land cover nesting in settings and if this fails
        (due to validation errors) then uses the default one.
        """
        try:
            nesting = esa_lc_nesting_from_settings()
        except ValidationError:
            nesting = get_default_esa_nesting()

        return nesting

    @staticmethod
    def sync_trans_matrix(ref_lcc_infos: typing.List["LCClassInfo"]):
        """
        Update transition matrix in settings with custom classes in the
        reference list.
        """
        if len(ref_lcc_infos) == 0:
            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                log(
                    f"{LccInfoUtils.CUSTOM_LEGEND_NAME} - No land cover "
                    f"classes to update transition matrix."
                )
            return

        try:
            matrix = get_trans_matrix(save_settings=False)
        except ValidationError:
            matrix = get_trans_matrix(True, False)

        if matrix is None:
            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                log(
                    f"{LccInfoUtils.CUSTOM_LEGEND_NAME} - No transition "
                    f"matrix in settings"
                )
            return

        # Check if there are custom classes to be removed.
        i = 0
        while i < len(matrix.legend.key):
            lcc = matrix.legend.key[i]
            lcc_in_ref, lcc_info = LccInfoUtils.lcc_in_infos(lcc, ref_lcc_infos)

            if not lcc_in_ref:
                if conf.settings_manager.get_value(conf.Setting.DEBUG):
                    log(
                        f"{LccInfoUtils.CUSTOM_LEGEND_NAME} - {lcc.name_long} "
                        f"class not in matrix settings, attempting to remove..."
                    )
                matrix.remove_class(lcc)
                if conf.settings_manager.get_value(conf.Setting.DEBUG):
                    log(
                        f"{LccInfoUtils.CUSTOM_LEGEND_NAME} - "
                        f"{lcc.name_long} class successfully removed in matrix."
                    )
            else:
                i += 1

        # Check if we need to add or update
        for lcc_info in ref_lcc_infos:
            ref_lcc = lcc_info.lcc
            matrix.add_update_class(ref_lcc)
            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                log(
                    f"{LccInfoUtils.CUSTOM_LEGEND_NAME} - Adding "
                    f"{ref_lcc.name_long} class to matrix."
                )

        # Use meanings for default classes if names match.
        ref_matrix = get_trans_matrix(True, False)
        for m in matrix.definitions.transitions:
            try:
                ref_meaning = ref_matrix.definitions.meaningByTransition(
                    m.initial, m.final
                )
                if ref_meaning:
                    m.meaning = ref_meaning
            except (IndexError, KeyError):
                continue

        matrix.legend.name = LccInfoUtils.CUSTOM_LEGEND_NAME
        matrix.name = "Custom land cover degradation transition matrix"

        # Update matrix in settings
        trans_matrix_to_settings(matrix)
        if conf.settings_manager.get_value(conf.Setting.DEBUG):
            log(
                f"{LccInfoUtils.CUSTOM_LEGEND_NAME} - Saved updated matrix to "
                f"settings."
            )

    @staticmethod
    def save_lc_nesting_ipcc(ref_lcc_infos: typing.List["LCClassInfo"]):
        """
        Save IPCC land cover nesting to settings.

        This shows how (possibly custom) classes nest under the IPCC classes.
        """
        if len(ref_lcc_infos) == 0:
            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                log(
                    f"{LccInfoUtils.CUSTOM_LEGEND_NAME} - No land cover "
                    f"classes to update IPCC land cover nesting."
                )

            return

        reference_nesting = get_default_esa_nesting()

        parents = []
        children = []
        nesting_map = dict()
        nodata = reference_nesting.parent.nodata
        no_data_children = []
        for lcci in ref_lcc_infos:
            parent = lcci.parent
            child = lcci.lcc
            children.append(child)
            if parent.code == nodata.code:
                no_data_children.append(child.code)
                continue

            if parent not in parents:
                parents.append(parent)
            if parent.code not in nesting_map:
                nesting_map[parent.code] = []
            nesting_map.get(parent.code).append(child.code)

        child_nodata = None
        if len(no_data_children) == 0:
            child_nodata = deepcopy(nodata)
            nesting_map[nodata.code] = [child_nodata.code]
        else:
            nesting_map[nodata.code] = no_data_children

        reference_nesting.parent.key = parents
        reference_nesting.child.key = children
        reference_nesting.child.name = LccInfoUtils.CUSTOM_LEGEND_NAME
        reference_nesting.child.nodata = child_nodata
        reference_nesting.nesting = nesting_map

        ipcc_lc_nesting_to_settings(reference_nesting)

        if conf.settings_manager.get_value(conf.Setting.DEBUG):
            log(f"nesting is {reference_nesting.nesting}")
            log(f"parent codes are {reference_nesting.parent.codes()}")
            log(f"child codes are {reference_nesting.child.codes()}")

            log(
                f"{LccInfoUtils.CUSTOM_LEGEND_NAME} - Saved IPCC lc "
                f"nesting to settings."
            )

    @staticmethod
    def save_lc_nesting_esa(ref_lcc_infos: typing.List["LCClassInfo"]):
        """
        Save ESA land cover nesting to settings.

        This shows how (possibly custom) classes nest under the ESA classes.
        The ESA classes are in turn nested under the IPCC.
        """
        if len(ref_lcc_infos) == 0:
            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                log(
                    f"{LccInfoUtils.CUSTOM_LEGEND_NAME} - No land cover "
                    f"classes to update ESA land cover nesting."
                )
            return

        reference_esa_nesting = get_default_esa_nesting()
        try:
            current_nesting = esa_lc_nesting_from_settings()
        except ValidationError:
            current_nesting = None
        if current_nesting is None:
            current_nesting = get_default_esa_nesting()
        new_nesting = deepcopy(current_nesting)

        current_child_codes = [c.code for c in current_nesting.child.key]
        new_child_codes = [lcc.lcc.code for lcc in ref_lcc_infos]
        ipcc_codes = [c.code for c in reference_esa_nesting.parent.key]

        new_esa_parent_key = []
        new_nesting_map = {
            current_nesting.parent.nodata.code: [current_nesting.child.nodata.code]
        }
        for lcc in ref_lcc_infos:
            custom_class = lcc.lcc  # this is a custom class ESA needs to nest under
            custom_class_parent = lcc.parent  # this is an IPCC class
            if custom_class_parent.code == current_nesting.parent.nodata.code:
                new_nesting_map[current_nesting.parent.nodata.code].append(
                    custom_class.code
                )
            elif custom_class.code in ipcc_codes:
                # This code is in the IPCC key, so assume this custom class
                # is an IPCC class, so nest the same ESA classes under it as
                # are nested in the default UNCCD key
                custom_class_ref = reference_esa_nesting.parent.classByCode(
                    custom_class.code
                )
                new_esa_parent_key.append(custom_class_ref)
                # It is possible that the custom legend may have class codes that match
                # those in the ESA legend. If that is the case, make sure these codes
                # aren't included in the children that are nested under this class (as
                # then they would be added to the legend twice - as both a parent, and
                # as a child)
                new_nesting_map[custom_class_ref.code] = [
                    c.code
                    for c in reference_esa_nesting.children_for_parent(custom_class_ref)
                    if c.code not in new_child_codes
                ]

            elif custom_class.code in current_child_codes:
                # This code is in the ESA key, so assume this custom class
                # IS an ESA class, and nest the same ESA classes under it
                custom_class_ref = reference_esa_nesting.child.classByCode(
                    custom_class.code
                )
                new_esa_parent_key.append(custom_class_ref)
                new_nesting_map[custom_class_ref.code] = [custom_class_ref.code]
            else:
                # This code is a new custom class that isn't in the ESA or IPCC keys,
                # so add it to the parent key with nothing nested under it
                new_esa_parent_key.append(custom_class)
                new_nesting_map[custom_class.code] = []

        # Nest any ESA classes that aren't already neded under nodata
        child_codes_in_nesting = [
            value for key, values in new_nesting_map.items() for value in values
        ]
        for esa_class in reference_esa_nesting.child.key:
            if esa_class.code not in child_codes_in_nesting:
                new_nesting_map[current_nesting.parent.nodata.code].append(
                    esa_class.code
                )

        current_nesting.parent.key = new_esa_parent_key
        current_nesting.parent.name = LccInfoUtils.CUSTOM_LEGEND_NAME
        current_nesting.nesting = new_nesting_map
        esa_lc_nesting_to_settings(current_nesting)

        if conf.settings_manager.get_value(conf.Setting.DEBUG):
            log(f"nesting is {current_nesting.nesting}")
            log(f"parent codes are {current_nesting.parent.codes()}")
            log(f"child codes are {current_nesting.child.codes()}")

            log(
                f"{LccInfoUtils.CUSTOM_LEGEND_NAME} - Saved ESA lc "
                f"nesting to settings."
            )

    @staticmethod
    def sync_lc_nesting(ref_lcc_infos: typing.List["LCClassInfo"]):
        """
        Updates both IPCC and ESA land cover nestings in settings.
        """
        if len(ref_lcc_infos) == 0:
            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                log(
                    f"{LccInfoUtils.CUSTOM_LEGEND_NAME} - No land cover "
                    f"classes to update land cover nesting."
                )
            return

        LccInfoUtils.save_lc_nesting_ipcc(ref_lcc_infos)
        LccInfoUtils.save_lc_nesting_esa(ref_lcc_infos)

    @staticmethod
    def set_default_unccd_classes(force_update=False):
        """
        Overrides the custom land cover classes in the setting and replaces
        with the UNCCD classes. If 'force_update' is False then it will
        only replace if the corresponding setting is empty otherwise it will
        always update the land cover classes.
        """
        status, lcc_infos = LccInfoUtils.load_settings()
        if len(lcc_infos) > 0 and not force_update:
            return

        ref_nesting = get_default_esa_nesting()

        def_lcc_infos = []
        for lcc in ref_nesting.parent.key:
            lcc_info = LCClassInfo()
            lcc_info.lcc = lcc
            lcc_info.parent = lcc
            def_lcc_infos.append(lcc_info)

        # Save to settings
        if len(def_lcc_infos) > 0:
            LccInfoUtils.save_settings(def_lcc_infos)

        # Re-write the matrix but with the original meanings restored
        _ = get_trans_matrix(True, True)

    @staticmethod
    def set_default_esa_classes(force_update=False):
        """
        Overrides the custom land cover classes in the setting and replaces
        with the ESA classes, nested under UNCCD. If 'force_update' is False then it will
        only replace if the corresponding setting is empty otherwise it will
        always update the land cover classes.
        """
        status, lcc_infos = LccInfoUtils.load_settings()
        if len(lcc_infos) > 0 and not force_update:
            return

        ref_nesting = get_default_esa_nesting()

        esa_nesting = {}
        def_lcc_infos = []
        for lcc in ref_nesting.child.key:
            lcc_info = LCClassInfo()
            lcc_info.lcc = lcc
            lcc_info.parent = ref_nesting.parent_for_child(lcc)
            def_lcc_infos.append(lcc_info)
            esa_nesting[lcc.code] = [lcc.code]

        # Nodata code shouldn't be listed in nesting dict
        esa_nesting[ref_nesting.child.nodata.code] = [ref_nesting.child.nodata.code]

        # Save custom to ipcc nesting to settings
        if len(def_lcc_infos) > 0:
            LccInfoUtils.save_settings(def_lcc_infos)

        # Re-write the esa nesting matrix
        esa_lc_nesting_to_settings(
            LCLegendNesting(
                parent=ref_nesting.child, child=ref_nesting.child, nesting=esa_nesting
            )
        )

        # Re-write the matrix but with the original meanings restored
        _ = get_trans_matrix(True, True)
