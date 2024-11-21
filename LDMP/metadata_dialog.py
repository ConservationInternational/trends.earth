"""Metadata editing dialog for Trends.Earth QGIS plugin."""

import os
from pathlib import Path

import qgis.core
from qgis.PyQt import QtCore, QtGui, QtWidgets, uic

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

    def save_metadata(self):
        if self.metadata is None:
            self.metadata = qgis.core.QgsLayerMetadata()

        self.metadata.setTitle(self.le_title.text())

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
