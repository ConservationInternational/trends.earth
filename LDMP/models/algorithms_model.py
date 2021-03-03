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
from LDMP.models.algorithms import AlgorithmGroup, AlgorithmDescriptor


class AlgorithmTreeModel(QAbstractItemModel):

    def __init__(self, tree: AlgorithmGroup, parent=None):
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

    def data(self, index: QModelIndex = QModelIndex(), role: Qt.ItemDataRole = Qt.DisplayRole ) -> Union[AlgorithmGroup, AlgorithmDescriptor, None]:
        if not index.isValid():
            return None

        item = index.internalPointer()
        if role == Qt.DisplayRole:
            if index.column() == 0:
                entry_string = '{}'.format(item.name)
                if item.name_details:
                    entry_string += '[{}]'.format(item.name_details)

                return entry_string
            
            if index.column() == 1:
                # return a widget depending of kind of node
                return "row: {} column: 2".format(index.row())

        if role == Qt.ItemDataRole:
            return item

    def flags(self, index: QModelIndex = QModelIndex()) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags

        # is editable only second column with popup menu
        if index.column() == 1:
            return Qt.ItemIsEditable | super().flags(index)
        
        return super().flags(index)

    def headerData(self, section: int, orientation: Qt.Orientation, role: Qt.ItemDataRole):
        if (orientation == Qt.Horizontal and role == Qt.DisplayRole):
            return self.rootItem.columnName(section)
        return None
    
    def index(self, row: int, column: int, parent: QModelIndex) -> QModelIndex:
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        if not parent.isValid():
            parentItem = self.rootItem
        else:
            parentItem = parent.internalPointer()

        childItem = parentItem.child(row)
        if childItem:
            return self.createIndex(row, column, childItem)
        
        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()

        childItem = index.internalPointer()
        if childItem is self.rootItem:
            return QModelIndex()
        if childItem.getGroup() is None:
            return QModelIndex()

        group = childItem.getGroup()
        return self.createIndex(group.row(), 0, group)

    def setData(self, index: QModelIndex, value, role: Qt.ItemDataRole) -> bool:
        if role != Qt.EditRole:
            return False

        # item = self.data(index, Qt.ItemDataRole)
        
        # result = item.setData(index.column(), value)
        # if (result):
        #     emit dataChanged(index, index, [Qt.DisplayRole, Qt.EditRole])

        # return result;
        return True
