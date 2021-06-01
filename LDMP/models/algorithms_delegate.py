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

            # then grab and paint it
            pixmap = editorWidget.grab()
            del editorWidget
            painter.drawPixmap(option.rect.x(), option.rect.y(), pixmap)
        else:
            super().paint(painter, option, index)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex):
        model = index.model()
        item = model.data(index, Qt.ItemDataRole)

        if item.item_type == AlgorithmNodeType.Algorithm:
            widget = self.createEditor(None, option, index) # parent set to none otherwise remain painted in the widget
            size = widget.size()
            del widget
            return size
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

            # add action entries to be used on the pull down menu and the push button
            action_modes = {
                AlgorithmRunMode.Locally: 'Run',
                AlgorithmRunMode.Remotely: 'Run with default data',
            }

            if item.run_mode is AlgorithmRunMode.Both:
                editorWidget.pushButton.hide()
                for action_mode, action_text in action_modes.items():
                    runAction = QAction(tr(action_text), editorWidget)
                    editorWidget.toolButtonAlgorithmRun.menu().addAction(runAction)
                    editorWidget.toolButtonAlgorithmRun.setDefaultAction(runAction)

                    # link callback to local processing
                    if(item.run_callbacks and
                        (action_mode in item.run_callbacks) and
                        (item.run_callbacks[action_mode] is not None)):
                        runAction.triggered.connect(item.run_callbacks[action_mode])
                    else:
                        runAction.setDisabled(True)
            elif item.run_mode in action_modes.keys():
                editorWidget.toolButtonAlgorithmRun.hide()

                editorWidget.pushButton.setText(tr(action_modes[item.run_mode]))

                # link callback to algorithm processing
                if (item.run_callbacks and
                        (item.run_mode in item.run_callbacks) and
                        (item.run_callbacks[item.run_mode] is not None)):
                    editorWidget.pushButton.clicked.connect(item.run_callbacks[item.run_mode])
                else:
                    editorWidget.pushButton.setDisabled(True)
            else:
                editorWidget.pushButton.hide()
                editorWidget.toolButtonAlgorithmRun.hide()

            # set the value of Alg description if a leaf is available
            if item.details:
                editorWidget.labelDescription.setText( f'  > {item.details.description}' )
            else:
                editorWidget.labelDescription.hide()

            return editorWidget
        else:
            return super().createEditor(parent, option, index)

    def updateEditorGeometry(self, editor: QWidget, option: QStyleOptionViewItem, index: QModelIndex):
        editor.setGeometry(option.rect)


class AlgorithmEditorWidget(QWidget, Ui_WidgetAlgorithmLeafItem):
    def __init__(self, parent=None):
        super(AlgorithmEditorWidget, self).__init__(parent)
        self.setupUi(self)
        self.setAutoFillBackground(True) # this allow to hide background prerendered pixmap
