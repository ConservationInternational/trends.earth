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

from functools import partial
from typing import Optional, Union
from qgis.PyQt.QtCore import (
    QModelIndex,
    Qt,
    QCoreApplication,
    QObject,
    pyqtSignal,
    QRectF,
    QAbstractItemModel
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
    QPainter
)
from LDMP.models.algorithms import (
    AlgorithmGroup,
    AlgorithmDescriptor,
    AlgorithmNodeType,
    AlgorithmRunMode
)
from LDMP import __version__, log, tr
from LDMP.gui.WidgetAlgorithmLeaf import Ui_WidgetAlgorithmLeafItem


class AlgorithmItemDelegate(QStyledItemDelegate):

    def __init__(self, parent: QObject = None):
        super().__init__(parent)

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
        self.parent.openPersistentEditor(self.enteredCell)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        # get item and manipulate painter basing on idetm data
        model = index.model()
        item = model.data(index, Qt.ItemDataRole)

        # text column
        if item.algorithm_type == AlgorithmNodeType.Group:
            text = model.data(index, Qt.DisplayRole)
            painter.drawText( option.rect, int(option.displayAlignment), text )

        # if a Algorithm => show custom widget
        if item.algorithm_type == AlgorithmNodeType.Algorithm:
            # get default widget used to edit data
            editorWidget = self.createEditor(self.parent, option, index)
            editorWidget.setGeometry(option.rect)
            pixmap = editorWidget.grab()

            painter.drawPixmap(option.rect.x(), option.rect.y(), pixmap)

        # if a Algorithm details => show description
        if item.algorithm_type == AlgorithmNodeType.Details:
            super().paint(painter, option, index)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex):
        model = index.model()
        item = model.data(index, Qt.ItemDataRole)

        if item.algorithm_type == AlgorithmNodeType.Algorithm:
            widget = self.createEditor(None, option, index)
            return widget.size()
        return super().sizeHint(option, index)

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex):
        # get item and manipulate painter basing on item data
        model = index.model()
        item = model.data(index, Qt.ItemDataRole)

        if item.algorithm_type == AlgorithmNodeType.Algorithm:
            editorWidget = AlgorithmEditorWidget(parent)

            editorWidget.labelAlgorithmName.setText(item.name)
            if item.name_details:
                editorWidget.lableAalgorithmNameDetail.setText('[{}]'.format(item.name_details))
            else:
                editorWidget.lableAalgorithmNameDetail.hide()
            
            # add run button to the toolButton menu
            editorWidget.toolButtonAlgorithmRun.setPopupMode(QToolButton.MenuButtonPopup)
            editorWidget.toolButtonAlgorithmRun.setMenu(QMenu())

            # add action entries of the pull down menu
            runAction = QAction(tr('Run'), editorWidget)
            editorWidget.toolButtonAlgorithmRun.menu().addAction(runAction)
            editorWidget.toolButtonAlgorithmRun.setDefaultAction(runAction)

            if item.run_mode == AlgorithmRunMode.Both:
                runWithDefaultAction = QAction(tr('Run with default data'), editorWidget)
                editorWidget.toolButtonAlgorithmRun.menu().addAction(runWithDefaultAction)

            return editorWidget
        else:
            return super().createEditor(parent, option, index)

class AlgorithmEditorWidget(QWidget, Ui_WidgetAlgorithmLeafItem):
    def __init__(self, parent=None):
        super(AlgorithmEditorWidget, self).__init__(parent)
        self.setupUi(self)
        self.setAutoFillBackground(True) # this allow to hide background prerendered pixmap
