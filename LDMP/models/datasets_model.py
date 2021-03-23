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

from typing import Optional, Union
from qgis.PyQt.QtCore import (
    QAbstractItemModel,
    QModelIndex,
    Qt
)
from LDMP.models.datasets import (
    Dataset,
    Datasets
)

class DatasetsModel(QAbstractItemModel):

    def __init__(self, tree: Datasets, parent=None):
        super().__init__(parent)

        self.rootItem = tree

    def rowCount(self, index: QModelIndex = QModelIndex()) -> int:
        if index.column() > 0:
            return 0

        if index.isValid():
            internalPointer = index.internalPointer()
            return internalPointer.rowCount()

        return self.rootItem.rowCount()

    def columnCount(self, index: QModelIndex = QModelIndex()) -> int:
        if index.isValid():
            internalPointer = index.internalPointer()
            return internalPointer.columnCount()

        return self.rootItem.columnCount()

    def data(self, index: QModelIndex = QModelIndex(), role: Qt.ItemDataRole = Qt.DisplayRole ) -> Union[Dataset, None]:
        if not index.isValid():
            return None

        item = index.internalPointer()
        if role == Qt.DisplayRole:
            if index.column() == 0:
                return item.name
            
        if role == Qt.ItemDataRole:
            return item

    def flags(self, index: QModelIndex = QModelIndex()) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags

        # is editable only second column with popup menu
        model = index.model()
        item = model.data(index, Qt.ItemDataRole)

        # if index.column() == 0:
        #     return Qt.ItemIsEditable | super().flags(index)

        return super().flags(index)

    def headerData(self, section: int, orientation: Qt.Orientation, role: Qt.ItemDataRole):
        if (orientation == Qt.Horizontal and role == Qt.DisplayRole):
            return self.rootItem.columnName(section)
        return None
    
    def index(self, row: int, column: int, parent: QModelIndex) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        parentItem = self.rootItem
        childItem = parentItem.child(row)
        if childItem:
            return self.createIndex(row, column, childItem)
        
        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
        return QModelIndex()

    def setData(self, index: QModelIndex, value, role: Qt.ItemDataRole) -> bool:
        if role != Qt.EditRole:
            return False

        return True
