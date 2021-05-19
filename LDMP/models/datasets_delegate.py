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
    QSize,
    QSettings
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
from LDMP.calculate import local_scripts

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
        item = model.data(index, Qt.DisplayRole)
        self.parent.openPersistentEditor(self.enteredCell)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        # get item and manipulate painter basing on idetm data
        model = index.model()
        item = model.data(index, Qt.DisplayRole)

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
        item = model.data(index, Qt.DisplayRole)

        if isinstance(item, Dataset):
            widget = self.createEditor(None, option, index) # parent swet to none otherwise remain painted in the widget
            size = widget.size()
            del widget
            return size

        return super().sizeHint(option, index)

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex):
        # get item and manipulate painter basing on item data
        model = index.model()
        item = model.data(index, Qt.DisplayRole)
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
        self.pushButtonStatus.setIcon(
            QIcon(':/plugins/LDMP/icons/cloud-download.svg'))

        # allow having string or datetime for start_date
        # setting string in a uniform format
        start_date_txt = self.dataset.creation_date
        if isinstance(self.dataset.creation_date, datetime):
            start_date_txt = self.dataset.datetimeRepr(self.dataset.creation_date)
        else:
            # manage in case no start_date is available
            if start_date_txt:
                dt = self.dataset.toDatetime(start_date_txt)
                start_date_txt = self.dataset.datetimeRepr(dt)
            else:
                start_date_txt = '<No start date set>'
        self.labelCreationDate.setText(start_date_txt)

        self.labelRunId.setText(str(self.dataset.run_id)) # it is UUID

        # disable delete button by default
        self.pushButtonDelete.setEnabled(False)

        # disable download button by default
        self.pushButtonStatus.setEnabled(False)
        dataset_auto_download = QSettings().value("trends_earth/advanced/dataset_auto_download", True, type=bool)
        self.pushButtonStatus.setHidden(dataset_auto_download)

        # show progress bar or download button depending on status
        if hasattr(self.dataset, 'progress'):
            self.progressBar.setValue(self.dataset.progress)
        else:
            self.progressBar.hide()

        if self.dataset.status == 'PENDING':
            self.progressBar.setRange(0,100)
            self.progressBar.setFormat(self.dataset.status)
            self.progressBar.show()
        if ( self.dataset.progress > 0 and
             self.dataset.progress < 100
            ):
            # no % come from server => set progress as continue update
            self.progressBar.show()
            self.progressBar.setMinimum(0)
            self.progressBar.setMaximum(0)
            self.progressBar.setFormat('Processing...')
        # change GUI if finished
        if ( self.dataset.status in ['FINISHED', 'SUCCESS'] and
             self.dataset.progress == 100 and
             self.dataset.origin() != Dataset.Origin.downloaded_dataset
            ):
            self.progressBar.reset()
            self.progressBar.hide()
            # disable download button if auto download is set
            self.pushButtonStatus.setEnabled(True)
            # add event to download dataset
            self.pushButtonStatus.clicked.connect(self.dataset.download)

        dataset_name = self.dataset.name if self.dataset.name else '<no name set>'
        self.labelDatasetName.setText(dataset_name)

        # set data source string
        data_source = self.dataset.source if self.dataset.source else 'Unknown'
        metadata = local_scripts.get(data_source, None)
        if metadata:
            data_source = metadata['display_name']
        self.labelSourceName.setText(data_source)

        # get data differently if come from Dataset or Downloaded dataset
        if self.dataset.origin() in [Dataset.Origin.downloaded_dataset, Dataset.Origin.local_raster]:
            self.progressBar.hide()
            self.pushButtonStatus.hide()
            # allow delete if downloaded
            self.pushButtonDelete.setEnabled(True)
        
            

    def show_details(self):
        log(f"Details button clicked for dataset {self.dataset.name!r}")

    def load_dataset(self):
        log(f"Load button clicked for dataset {self.dataset.name!r}")
        self.dataset.add()

    def delete_dataset(self):
        log(f"Delete button clicked for dataset {self.dataset.name!r}")
        self.dataset.delete()

