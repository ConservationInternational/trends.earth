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
    QAction,
    QStyle
)
from qgis.PyQt.QtGui import (
    QPainter,
    QBrush,
    QColor
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

        # if a Algorithm => show custom widget
        if item.item_type == AlgorithmNodeType.Algorithm:
            # get default widget used to edit data
            editorWidget = self.createEditor(self.parent, option, index)
            editorWidget.setGeometry(option.rect)
            pixmap = editorWidget.grab()

            painter.drawPixmap(option.rect.x(), option.rect.y(), pixmap)
        else:
            super().paint(painter, option, index)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex):
        model = index.model()
        item = model.data(index, Qt.ItemDataRole)

        if item.item_type == AlgorithmNodeType.Algorithm:
            widget = self.createEditor(None, option, index)
            return widget.size()
        return super().sizeHint(option, index)

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex):
        # get item and manipulate painter basing on item data
        model = index.model()
        item = model.data(index, Qt.ItemDataRole)

        if item.item_type == AlgorithmNodeType.Algorithm:
            editorWidget = AlgorithmEditorWidget(parent)

            text = index.data(Qt.DisplayRole)
            editorWidget.labelAlgorithmName.setText(text)
            
            # add run button to the toolButton menu
            editorWidget.toolButtonAlgorithmRun.setPopupMode(QToolButton.MenuButtonPopup)
            editorWidget.toolButtonAlgorithmRun.setMenu(QMenu())

            # add action entries of the pull down menu
            runAction = None
            if item.run_mode in [AlgorithmRunMode.Locally, AlgorithmRunMode.Both]:
                runAction = QAction(tr('Run'), editorWidget)
                editorWidget.toolButtonAlgorithmRun.menu().addAction(runAction)
                editorWidget.toolButtonAlgorithmRun.setDefaultAction(runAction)

                # link callback to local processing
                if( item.run_callbacks and
                    (AlgorithmRunMode.Locally in item.run_callbacks) and
                    (item.run_callbacks[AlgorithmRunMode.Locally] is not None) ):
                    runAction.triggered.connect( item.run_callbacks[AlgorithmRunMode.Locally] )
                else:
                    runAction.setDisabled(True)

            if item.run_mode in [AlgorithmRunMode.Remotely, AlgorithmRunMode.Both]:
                runWithDefaultAction = QAction(tr('Run with default data'), editorWidget)
                editorWidget.toolButtonAlgorithmRun.menu().addAction(runWithDefaultAction)
                if not runAction:
                    editorWidget.toolButtonAlgorithmRun.setDefaultAction(runWithDefaultAction)

                # link callback to remote processing
                if( item.run_callbacks and
                    (AlgorithmRunMode.Remotely in item.run_callbacks) and
                    (item.run_callbacks[AlgorithmRunMode.Remotely] is not None) ):
                    runWithDefaultAction.triggered.connect( item.run_callbacks[AlgorithmRunMode.Remotely] )
                else:
                    runWithDefaultAction.setDisabled(True)

            return editorWidget
        else:
            return super().createEditor(parent, option, index)

class AlgorithmEditorWidget(QWidget, Ui_WidgetAlgorithmLeafItem):
    def __init__(self, parent=None):
        super(AlgorithmEditorWidget, self).__init__(parent)
        self.setupUi(self)
        self.setAutoFillBackground(True) # this allow to hide background prerendered pixmap
