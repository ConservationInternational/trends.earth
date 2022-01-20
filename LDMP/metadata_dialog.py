"""Metadata editing dialog for Trends.Earth QGIS plugin."""

import os
from pathlib import Path

import qgis.core
import qgis.gui
from qgis.PyQt import QtCore
from qgis.PyQt import QtGui
from qgis.PyQt import QtWidgets
from qgis.PyQt import uic

from . import tr

Ui_DlgDatasetMetadata, _ = uic.loadUiType(
    str(Path(__file__).parents[0] / "gui/DlgDatasetMetadata.ui")
)

ICON_PATH = os.path.join(os.path.dirname(__file__), 'icons')


class DlgDatasetMetadata(QtWidgets.QDialog, Ui_DlgDatasetMetadata):

    def __init__(self, parent=None):
        super(DlgDatasetMetadata, self).__init__(parent)
        self.setupUi(self)

        self.btn_add_address.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, 'symbologyAdd.svg'))
        )
        self.btn_remove_address.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, 'symbologyRemove.svg'))
        )
        self.btn_new_category.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, 'symbologyAdd.svg'))
        )
        self.btn_add_default_category.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, 'mActionArrowRight.svg'))
        )
        self.btn_remove_category.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, 'symbologyRemove.svg'))
        )


        self.default_categories = [tr("Farming"), tr("Biota"),
                               tr("Boundaries"), tr("Climatology Meteorology Atmosphere" ),
                               tr("Economy"), tr("Elevation"), tr("Environment"),
                               tr("Geoscientific Information"), tr("Health"),
                               tr("Imagery Base Maps Earth Cover"), tr("Intelligence Military"),
                               tr("Inland Waters"), tr("Location"),tr("Oceans"),
                               tr("Planning Cadastre"), tr("Society"), tr("Structure"),
                               tr("Transportation"),tr("Utilities Communication")]
        self.default_categories_model = QtCore.QStringListModel(self.default_categories)
        self.default_categories_model.sort(0)
        self.lst_default_categories.setModel(self.default_categories_model)

        self.categories_model = QtCore.QStringListModel(self.lst_categories)
        self.lst_categories.setModel(self.categories_model)

        self.btn_add_address.clicked.connect(self.add_address)
        self.btn_remove_address.clicked.connect(self.remove_address)
        self.btn_new_category.clicked.connect(self.add_new_category)
        self.btn_add_default_category.clicked.connect(self.add_default_categories)
        self.btn_remove_category.clicked.connect(self.remove_categories)

    def add_address(self):
        pass

    def remove_address(self):
        pass

    def add_new_category(self):
        text, ok = QtWidgets.QInputDialog.getText(self, tr("New Category"), tr("New Category"), QtWidgets.QLineEdit.Normal, "")
        if ok and text != "":
            categories_list = self.categories_model.stringList()
            if text not in categories_list:
                categories_list.append(text)
                self.categories_model.setStringList(categories_list)
                self.categories_model.sort(0)

    def add_default_categories(self):
        selected_indexes = self.lst_default_categories.selectionModel().selectedIndexes()
        default_categories_list = self.default_categories_model.stringList()
        selected_categories = self.categories_model.stringList()

        for i in selected_indexes:
            item = self.default_categories_model.data(i, QtCore.Qt.DisplayRole)
            default_categories_list.remove(item)
            selected_categories.append(item)

        self.default_categories_model.setStringList(default_categories_list)
        self.categories_model.setStringList(selected_categories)
        self.categories_model.sort(0)

    def remove_categories(self):
        selected_indexes = self.lst_categories.selectionModel().selectedIndexes()
        categories = self.categories_model.stringList()
        default_list = self.default_categories_model.stringList()

        for i in selected_indexes:
            item = self.categories_model.data(i, QtCore.Qt.DisplayRole)
            categories.remove(item)
            if item in self.default_categories:
                 default_list.append(item)

        self.categories_model.setStringList(categories)
        self.default_categories_model.setStringList(default_list)
        self.default_categories_model.sort(0)
