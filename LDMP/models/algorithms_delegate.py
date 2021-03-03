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
    QPainter,
    QPixmap
)
from qgis.PyQt.QtSvg import (
    QSvgRenderer
)

from LDMP.models.algorithms import (
    AlgorithmGroup,
    AlgorithmDescriptor,
    AlgorithmNodeType,
    AlgorithmRunMode
)
from LDMP import __version__, log, tr


# Icons used for animation:
# inspired by https://wiki.python.org/moin/PyQt/Animated%20items%20using%20delegates
_icon0_xpm = [
    "16 16 4 1",
    ".  c None",
    "s  c #cccc00",
    "x  c #ffffff",
    "   c #000000",
    "................",
    ".              .",
    ". xxxxxxxxxxxx .",
    ". x          x .",
    ".. x ssssss x ..",
    "... x ssss x ...",
    ".... x ss x ....",
    "..... x  x .....",
    "..... x  x .....",
    ".... x    x ....",
    "... x      x ...",
    ".. x        x ..",
    ". x          x .",
    ". xxxxxxxxxxxx .",
    ".              .",
    "................"]

_icon1_xpm = [
    "16 16 4 1",
    ".  c None",
    "s  c #cccc00",
    "x  c #ffffff",
    "   c #000000",
    "................",
    ".              .",
    ". xxxxxxxxxxxx .",
    ". x          x .",
    ".. x s    s x ..",
    "... x ssss x ...",
    ".... x ss x ....",
    "..... x  x .....",
    "..... x  x .....",
    ".... x ss x ....",
    "... x  ss  x ...",
    ".. x        x ..",
    ". x          x .",
    ". xxxxxxxxxxxx .",
    ".              .",
    "................"]

_icon2_xpm = [
    "16 16 4 1",
    ".  c None",
    "s  c #cccc00",
    "x  c #ffffff",
    "   c #000000",
    "................",
    ".              .",
    ". xxxxxxxxxxxx .",
    ". x          x .",
    ".. x        x ..",
    "... x ssss x ...",
    ".... x ss x ....",
    "..... x  x .....",
    "..... x  x .....",
    ".... x ss x ....",
    "... x  ss  x ...",
    ".. x   ss   x ..",
    ". x          x .",
    ". xxxxxxxxxxxx .",
    ".              .",
    "................"]

_icon3_xpm = [
    "16 16 4 1",
    ".  c None",
    "s  c #cccc00",
    "x  c #ffffff",
    "   c #000000",
    "................",
    ".              .",
    ". xxxxxxxxxxxx .",
    ". x          x .",
    ".. x        x ..",
    "... x      x ...",
    ".... x    x ....",
    "..... x  x .....",
    "..... x  x .....",
    ".... x ss x ....",
    "... x ssss x ...",
    ".. x ssssss x ..",
    ". x          x .",
    ". xxxxxxxxxxxx .",
    ".              .",
    "................"]

class AlgorithmItemDelegate(QStyledItemDelegate):

    needsRedraw = pyqtSignal()

    def __init__(self, parent: QObject = None):
        super().__init__(parent)

        # create widget but do not display it. It will be used to grab it during paint
        # In this way is efficient and not rendered the widget every paint envet.
        # Working widget is rendered and displayed only during createEditor of the cell
        # in this way the widget is represented, but active only during editing role.
        # This speedup View rendering.
        # observe that I just create the top level ToolButton because is that 
        # statically rendered
        # self.runAction = QAction(tr('Run'))
        # self.editorWidget = QToolButton()
        # self.editorWidget.setPopupMode(QToolButton.MenuButtonPopup)
        # self.editorWidget.setMenu(QMenu())
        # self.editorWidget.menu().addAction(self.runAction)
        # self.editorWidget.setDefaultAction(self.runAction)

        # pixmap animation control
        self.current = 0
        self.timerId = self.startTimer(250)
        self.pixmaps = (QPixmap(_icon0_xpm),
                        QPixmap(_icon1_xpm),
                        QPixmap(_icon2_xpm),
                        QPixmap(_icon3_xpm))
        self.needsRedraw.connect(parent.viewport().update)

        # create svg renderer
        # self.svg_renderer = QSvgRenderer('/home/ginetto/Downloads/tcjp3h.svg', parent)
        # self.svg_renderer = QSvgRenderer('/home/ginetto/Downloads/spinner-of-dots-svgrepo-com.svg', parent)
        # self.svg_renderer.repaintNeeded.connect(parent.viewport().update) 

    def timerEvent(self, event):
        if event.timerId() == self.timerId:
            self.current = (self.current + 1) % 4
            self.needsRedraw.emit()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        column = index.column()

        # get item and manipulate painter basing on idetm data
        model = index.model()
        item = model.data(index, Qt.ItemDataRole)

        # text column
        if column == 0:
            text = model.data(index, Qt.DisplayRole)
            painter.drawText( option.rect, int(option.displayAlignment), text )

        # widget column
        elif column == 1:
            # if a Leaf => show actions menu
            if item.type == AlgorithmNodeType.Leaf:
                # get default widget used to edit data
                editorWidget = self.createEditor(None, option, index)
                editorWidget.setGeometry(option.rect)
                pixmap = editorWidget.grab()
                painter.drawPixmap(option.rect.x(), option.rect.y(), pixmap)

            # if a Group then show Status icon
            elif item.type == AlgorithmNodeType.Group:
                # draw timeglass to the right border minus width of the pixmap
                # otherwise rendered outside the cell.
                currentPixmap = self.pixmaps[self.current]
                painter.drawPixmap(
                    option.rect.topRight().x() - currentPixmap.width(),
                    option.rect.topRight().y(),
                    currentPixmap
                )
                # option.rect = option.rect.translated(20, 0)
                # super().paint(painter, option, index)
                # bounds = option.rect
                # bounds.setWidth(28)
                # bounds.moveTo(option.rect.center().x() - bounds.width() / 2,
                # option.rect.center().y() - bounds.height() / 2);
                # self.svg_renderer.render(painter, QRectF(bounds))
            else:
                super().paint(painter, option, index)
        else:
            super().paint(painter, option, index)

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex):
        # get item and manipulate painter basing on idetm data
        model = index.model()
        item = model.data(index, Qt.ItemDataRole)

        column = index.column()
        if column == 1 and item.type == AlgorithmNodeType.Leaf:

            editorWidget = QToolButton(parent)
            editorWidget.setPopupMode(QToolButton.MenuButtonPopup)
            editorWidget.setMenu(QMenu())

            # add action entries of the pull down menu
            runAction = QAction(tr('Run'), editorWidget)
            editorWidget.menu().addAction(runAction)
            editorWidget.setDefaultAction(runAction)

            if item.run_mode == AlgorithmRunMode.Both:
                runWithDefaultAction = QAction(tr('Run with default data'), editorWidget)
                editorWidget.menu().addAction(runWithDefaultAction)

            return editorWidget
        else:
            return super().createEditor(parent, option, index)

    # def setEditorData(self, editor: QWidget, index: QModelIndex):
    #     # no need to edit due the fact that values are actions
    #     pass

    # def setModelData(self, editor: QWidget, model: QAbstractItemModel, index: QModelIndex):
    #     # no need to set model due the fact that values are actions
    #     pass
