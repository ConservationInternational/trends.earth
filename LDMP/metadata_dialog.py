"""Metadata editing dialog for Trends.Earth QGIS plugin."""

import os
from pathlib import Path

import qgis.core
from qgis.PyQt import QtCore
from qgis.PyQt import QtGui
from qgis.PyQt import QtWidgets
from qgis.PyQt import uic

Ui_DlgDatasetMetadata, _ = uic.loadUiType(
    str(Path(__file__).parents[0] / "gui/DlgDatasetMetadata.ui")
)

ICON_PATH = os.path.join(os.path.dirname(__file__), "icons")


class DlgDatasetMetadata(QtWidgets.QDialog, Ui_DlgDatasetMetadata):
    layer: qgis.core.QgsMapLayer
    metadata: qgis.core.QgsLayerMetadata

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.btn_add_address.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, "symbologyAdd.svg"))
        )
        self.btn_remove_address.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, "symbologyRemove.svg"))
        )
        self.btn_new_category.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, "symbologyAdd.svg"))
        )
        self.btn_add_default_category.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, "mActionArrowRight.svg"))
        )
        self.btn_remove_category.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, "symbologyRemove.svg"))
        )

        self.layer = None
        self.metadata = None
        self.default_categories = [
            self.tr("Farming"),
            self.tr("Biota"),
            self.tr("Boundaries"),
            self.tr("Climatology Meteorology Atmosphere"),
            self.tr("Economy"),
            self.tr("Elevation"),
            self.tr("Environment"),
            self.tr("Geoscientific Information"),
            self.tr("Health"),
            self.tr("Imagery Base Maps Earth Cover"),
            self.tr("Intelligence Military"),
            self.tr("Inland Waters"),
            self.tr("Location"),
            self.tr("Oceans"),
            self.tr("Planning Cadastre"),
            self.tr("Society"),
            self.tr("Structure"),
            self.tr("Transportation"),
            self.tr("Utilities Communication"),
        ]
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
        row = self.tbl_addresses.rowCount()
        self.tbl_addresses.setRowCount(row + 1)

        cell = QtWidgets.QTableWidgetItem(self.tr("postal"))
        self.tbl_addresses.setItem(row, 0, cell)
        self.tbl_addresses.setItem(row, 1, QtWidgets.QTableWidgetItem())
        self.tbl_addresses.setItem(row, 2, QtWidgets.QTableWidgetItem())
        self.tbl_addresses.setItem(row, 3, QtWidgets.QTableWidgetItem())
        self.tbl_addresses.setItem(row, 4, QtWidgets.QTableWidgetItem())
        self.tbl_addresses.setItem(row, 5, QtWidgets.QTableWidgetItem())

    def remove_address(self):
        selection_model = self.tbl_addresses.selectionModel()
        selected_rows = selection_model.selectedRows()
        for i in selected_rows:
            self.tbl_addresses.model().removeRow(i.row())

    def add_new_category(self):
        text, ok = QtWidgets.QInputDialog.getText(
            self,
            self.tr("New Category"),
            self.tr("New Category"),
            QtWidgets.QLineEdit.Normal,
            "",
        )
        if ok and text:
            categories_list = self.categories_model.stringList()
            if text not in categories_list:
                categories_list.append(text)
                self.categories_model.setStringList(categories_list)
                self.categories_model.sort(0)

    def add_default_categories(self):
        selected_indexes = (
            self.lst_default_categories.selectionModel().selectedIndexes()
        )
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

    def set_metadata(self, metadata):
        self.metadata = metadata
        self.update_ui()

    def set_layer(self, layer):
        self.layer = layer

    def update_ui(self):
        if self.metadata is None:
            return

        if self.metadata.title():
            self.le_title.setText(self.metadata.title())

        self.te_abstract.setPlainText(self.metadata.abstract())

        self.categories_model.setStringList(self.metadata.categories())

        contacts = self.metadata.contacts()
        if len(contacts) > 0:
            contact = contacts[0]
            self.le_contact_name.setText(contact.name)
            self.le_contact_email.setText(contact.email)
            self.le_contact_organisation.setText(contact.organization)
            self.le_contact_phone.setText(contact.voice)

            if self.cmb_contact_role.findText(contact.role) == -1:
                self.cmb_contact_role.addItem(contact.role)
            self.cmb_contact_role.setCurrentIndex(
                self.cmb_contact_role.findText(contact.role)
            )

            self.tbl_addresses.setRowCount(0)
            addresses = contact.addresses
            for address in addresses:
                row = self.tbl_addresses.rowCount()
                self.tbl_addresses.setRowCount(row + 1)
                self.tbl_addresses.setItem(
                    row, 0, QtWidgets.QTableWidgetItem(address.type)
                )
                self.tbl_addresses.setItem(
                    row, 1, QtWidgets.QTableWidgetItem(address.address)
                )
                self.tbl_addresses.setItem(
                    row, 2, QtWidgets.QTableWidgetItem(address.postalCode)
                )
                self.tbl_addresses.setItem(
                    row, 3, QtWidgets.QTableWidgetItem(address.city)
                )
                self.tbl_addresses.setItem(
                    row, 4, QtWidgets.QTableWidgetItem(address.administrativeArea)
                )
                self.tbl_addresses.setItem(
                    row, 5, QtWidgets.QTableWidgetItem(address.country)
                )

    def save_metadata(self):
        if self.metadata is None:
            self.metadata = qgis.core.QgsLayerMetadata()

        self.metadata.setTitle(self.le_title.text())
        self.metadata.setAbstract(self.te_abstract.toPlainText())
        self.metadata.setEncoding("UTF-8")

        if self.categories_model.rowCount() > 0:
            self.metadata.setKeywords(
                {"gmd:topicCategory": self.categories_model.stringList()}
            )

        contacts = self.metadata.contacts()
        if len(contacts) > 0:
            del contacts[0]

        contact = qgis.core.QgsAbstractMetadataBase.Contact()
        contact.email = self.le_contact_email.text()
        contact.voice = self.le_contact_phone.text()
        contact.name = self.le_contact_name.text()
        contact.organization = self.le_contact_organisation.text()
        contact.role = self.cmb_contact_role.currentText()
        addresses = list()
        for i in range(self.tbl_addresses.rowCount()):
            address = qgis.core.QgsAbstractMetadataBase.Address()
            address.type = self.tbl_addresses.item(i, 0).text()
            address.address = self.tbl_addresses.item(i, 1).text()
            address.postalCode = self.tbl_addresses.item(i, 2).text()
            address.city = self.tbl_addresses.item(i, 3).text()
            address.administrativeArea = self.tbl_addresses.item(i, 4).text()
            address.country = self.tbl_addresses.item(i, 5).text()
            addresses.append(address)
        contact.addresses = addresses
        contacts.insert(0, contact)
        self.metadata.setContacts(contacts)

        if self.layer is not None:
            self.metadata.setCrs(self.layer.dataProvider().crs())

            spatialExtent = qgis.core.QgsLayerMetadata.SpatialExtent()
            spatialExtent.geom = qgis.core.QgsBox3d(self.layer.extent())
            spatialExtent.extentCrs = self.layer.dataProvider().crs()
            spatialExtents = [spatialExtent]
            extent = qgis.core.QgsLayerMetadata.Extent()
            extent.setSpatialExtents(spatialExtents)
            self.metadata.setExtent(extent)

    def get_metadata(self):
        return self.metadata

    def accept(self):
        self.save_metadata()
        QtWidgets.QDialog.accept(self)
