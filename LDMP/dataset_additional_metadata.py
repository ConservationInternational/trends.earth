import os

from pathlib import Path

from qgis.PyQt import QtCore, QtGui, QtWidgets, uic

from LDMP.utils import log

DatasetAdditionalMetadataUi, _ = uic.loadUiType(
    str(Path(__file__).parents[0] / "gui/DlgDatasetAdditionalMetadata.ui")
)

ICON_PATH = os.path.join(os.path.dirname(__file__), "icons")


class DataSetAdditionalMetadataDialog(QtWidgets.QDialog, DatasetAdditionalMetadataUi):
    dataset: dict

    le_title: QtWidgets.QLineEdit
    te_author: QtWidgets.QTextEdit
    le_source: QtWidgets.QLineEdit
    te_citation: QtWidgets.QTextEdit

    def __init__(self, dataset: dict, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.le_title.setText(dataset.get('title', ''))
        self.te_author.setPlainText(dataset.get('Data source', ''))
        self.le_source.setText(dataset.get('Source', ''))
        self.te_citation.setPlainText(dataset.get('Citation', ''))
