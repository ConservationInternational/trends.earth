"""
/***************************************************************************
 LDMP - A QGIS plugin
 This plugin supports monitoring and reporting of land degradation to the UNCCD 
 and in support of the SDG Land Degradation Neutrality (LDN) target.
                              -------------------
        begin                : 2021-02-25
        git sha              : $Format:%H$
        copyright            : (C) 2017 by Conservation International
        email                : trends.earth@conservation.org
 ***************************************************************************/
"""

__author__ = 'Luigi Pirelli / Kartoza'
__date__ = '2021-03-03'

from datetime import datetime

import qgis.core
from functools import partial
from qgis.PyQt.QtCore import (
    QModelIndex,
    Qt,
    QCoreApplication,
    QObject,
    pyqtSignal,
    QRectF,
    QRect,
    QAbstractItemModel,
    QSize
)
from qgis.PyQt.QtWidgets import (
    QStyleOptionViewItem,
    QToolButton,
    QMenu,
    QStyledItemDelegate,
    QItemDelegate,
    QWidget,
    QAction
)
from qgis.PyQt.QtGui import (
    QPainter,
    QIcon
)
from LDMP.models.datasets import (
    Dataset,
    Datasets
)
from LDMP.models.algorithms import AlgorithmDescriptor
from LDMP import __version__, log, tr
from LDMP.gui.WidgetDatasetItem import Ui_WidgetDatasetItem


class DatasetItemDelegate(QStyledItemDelegate):

    def __init__(self, plugin, parent: QObject = None):
        super().__init__(parent)

        self.plugin = plugin
        self.parent = parent

        # manage activate editing when entering the cell (if editable)
        self.enteredCell = None
        self.parent.entered.connect(self.manageEditing)

    def manageEditing(self, index: QModelIndex):
        # close previous editor
        if index == self.enteredCell:
            return
        else:
            if self.enteredCell:
                self.parent.closePersistentEditor(self.enteredCell)
        self.enteredCell = index

        # do nothing if cell is not editable
        model = index.model()
        flags = model.flags(index)
        if not (flags & Qt.ItemIsEditable):
            return

        # activate editor
        item = model.data(index, Qt.ItemDataRole)
        self.parent.openPersistentEditor(self.enteredCell)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        # get item and manipulate painter basing on idetm data
        model = index.model()
        item = model.data(index, Qt.ItemDataRole)

        # if a Dataset => show custom widget
        if isinstance(item, Dataset):
            # get default widget used to edit data
            editorWidget = self.createEditor(self.parent, option, index)
            editorWidget.setGeometry(option.rect)

            # then grab and paint it
            pixmap = editorWidget.grab()
            del editorWidget
            painter.drawPixmap(option.rect.x(), option.rect.y(), pixmap)
        else:
            super().paint(painter, option, index)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex):
        model = index.model()
        item = model.data(index, Qt.ItemDataRole)

        if isinstance(item, Dataset):
            widget = self.createEditor(None, option, index) # parent swet to none otherwise remain painted in the widget
            size = widget.size()
            del widget
            return size

        return super().sizeHint(option, index)

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex):
        # get item and manipulate painter basing on item data
        model = index.model()
        item = model.data(index, Qt.ItemDataRole)
        if isinstance(item, Dataset):
            return DatasetEditorWidget(item, plugin=self.plugin, parent=parent)
        else:
            return super().createEditor(parent, option, index)

    def updateEditorGeometry(self, editor: QWidget, option: QStyleOptionViewItem, index: QModelIndex):
        editor.setGeometry(option.rect)

class DatasetEditorWidget(QWidget, Ui_WidgetDatasetItem):

    def __init__(self, dataset: Dataset, plugin=None, parent=None):
        super(DatasetEditorWidget, self).__init__(parent)
        self.plugin = plugin
        self.setupUi(self)
        self.setAutoFillBackground(True)  # allows hiding background prerendered pixmap
        self.dataset = dataset
        self.pushButtonLoad.clicked.connect(self.load_dataset)
        self.pushButtonDetails.clicked.connect(self.show_details)
        self.pushButtonDelete.clicked.connect(self.delete_dataset)

        self.pushButtonDelete.setIcon(
            QIcon(':/plugins/LDMP/icons/mActionDeleteSelected.svg'))
        self.pushButtonDetails.setIcon(
            QIcon(':/plugins/LDMP/icons/mActionPropertiesWidget.svg'))
        self.pushButtonLoad.setIcon(
            QIcon(':/plugins/LDMP/icons/mActionAddRasterLayer.svg'))

        # allow having string or datetime for start_date
        start_date_txt = self.dataset.creation_date
        if isinstance(self.dataset.creation_date, datetime):
            start_date_txt = self.dataset.creation_date.strftime('%Y-%m-%d (%H:%M)')
        self.labelCreationDate.setText(start_date_txt)

        self.labelRunId.setText(str(self.dataset.run_id)) # it is UUID

        # show progress bar or download button depending on status
        if self.dataset.progress is not None:
            self.progressBar.setValue( self.dataset.progress )
        self.pushButtonStatus.hide()
        self.progressBar.show()
        if self.dataset.status == 'PENDING':
            self.progressBar.setFormat(self.dataset.status)

        if self.dataset.progress is not None:
            if (self.dataset.progress > 0 and
                self.dataset.progress < 100):
               self.progressBar.setFormat(self.dataset.progress)
            # change GUI if finished
            if (self.dataset.status in ['FINISHED', 'SUCCESS'] and
                self.dataset.progress == 100):
                self.progressBar.hide()
                self.pushButtonStatus.show()
                self.pushButtonStatus.setIcon(QIcon(':/plugins/LDMP/icons/cloud-download.svg'))

        dataset_name = self.dataset.name if self.dataset.name else '<no name set>'
        self.labelDatasetName.setText(dataset_name)

        data_source = self.dataset.source if self.dataset.source else 'Unknown'
        self.labelSourceName.setText(self.dataset.source)

    def show_details(self):
        log(f"Details button clicked for dataset {self.dataset.name!r}")

    def load_dataset(self):
        log(f"Load button clicked for dataset {self.dataset.name!r}")

    def delete_dataset(self):
        log(f"Delete button clicked for dataset {self.dataset.name!r}")
