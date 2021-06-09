# """
# /***************************************************************************
#  LDMP - A QGIS plugin
#  This plugin supports monitoring and reporting of land degradation to the UNCCD
#  and in support of the SDG Land Degradation Neutrality (LDN) target.
#                               -------------------
#         begin                : 2021-02-25
#         git sha              : $Format:%H$
#         copyright            : (C) 2017 by Conservation International
#         email                : trends.earth@conservation.org
#  ***************************************************************************/
# """
#
# __author__ = 'Luigi Pirelli / Kartoza'
# __date__ = '2021-03-03'
#
# import enum
#
# from datetime import datetime
#
# from typing import Optional
# from qgis.PyQt.QtCore import (
#     QAbstractItemModel,
#     QModelIndex,
#     QSortFilterProxyModel,
#     Qt
# )
# from LDMP.models.datasets import (
#     Dataset,
#     Datasets,
#     SortField
# )
#
#
# class DatasetsModel(QAbstractItemModel):
#
#     def __init__(self, tree: Datasets, parent=None):
#         super().__init__(parent)
#
#         self.rootItem = tree
#
#     def rowCount(self, index: QModelIndex = QModelIndex()) -> int:
#         if index.column() > 0:
#             return 0
#
#         if index.isValid():
#             internalPointer = index.internalPointer()
#             return internalPointer.rowCount()
#
#         return self.rootItem.rowCount()
#
#     def columnCount(self, index: QModelIndex = QModelIndex()) -> int:
#         if index.isValid():
#             internalPointer = index.internalPointer()
#             return internalPointer.columnCount()
#
#         return self.rootItem.columnCount()
#
#     def data(self, index: QModelIndex = QModelIndex(), role: Qt.ItemDataRole = Qt.DisplayRole ) -> Optional[Dataset]:
#         if not index.isValid():
#             return None
#
#         item = index.internalPointer()
#         if role == Qt.DisplayRole or role == Qt.ItemDataRole:
#             return item
#
#     def flags(self, index: QModelIndex = QModelIndex()) -> Qt.ItemFlags:
#         if not index.isValid():
#             return Qt.NoItemFlags
#         return Qt.ItemIsEditable | super().flags(index)
#
#     def headerData(self, section: int, orientation: Qt.Orientation, role: Qt.ItemDataRole):
#         if (orientation == Qt.Horizontal and role == Qt.DisplayRole):
#             return self.rootItem.columnName(section)
#         return None
#
#     def index(self, row: int, column: int, parent: QModelIndex) -> QModelIndex:
#         if not self.hasIndex(row, column, parent):
#             return QModelIndex()
#
#         parentItem = self.rootItem
#         childItem = parentItem.child(row)
#         if childItem:
#             return self.createIndex(row, column, childItem)
#
#         return QModelIndex()
#
#     def parent(self, index: QModelIndex) -> QModelIndex:
#         return QModelIndex()
#
#     def setData(self, index: QModelIndex, value, role: Qt.ItemDataRole) -> bool:
#         if role != Qt.EditRole:
#             return False
#
#         return True
#
#     def rootModel(self):
#         return self.rootItem
#
#
# class DatasetsSortFilterProxyModel(QSortFilterProxyModel):
#     def __init__(self, parent=None):
#         super().__init__(parent)
#
#     def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex):
#         index = self.sourceModel().index(source_row, 0, source_parent)
#
#         match = self.filterRegularExpression().match(self.sourceModel().data(index).name)
#         return match.hasMatch()
#
#     def sort(self, column: int, order, field: SortField = None):
#         if field is not None:
#             self.sourceModel().rootModel().sort(order, field)
#             self.layoutChanged.emit()
