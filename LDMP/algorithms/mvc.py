import functools
import typing
from pathlib import Path

from PyQt5 import (
    QtCore,
    QtGui,
    QtWidgets,
    uic,
)

from .. import tr
from . import models

WidgetAlgorithmLeafUi, _ = uic.loadUiType(
    str(Path(__file__).parents[1] / "gui/WidgetAlgorithmLeaf.ui"))


class AlgorithmTreeModel(QtCore.QAbstractItemModel):
    root_item: models.AlgorithmGroup

    def __init__(self, tree: models.AlgorithmGroup, parent=None):
        super().__init__(parent)
        self.root_item = tree

    def index(
            self,
            row: int,
            column: int,
            parent: QtCore.QModelIndex
    ) -> QtCore.QModelIndex:
        invalid_index = QtCore.QModelIndex()
        if self.hasIndex(row, column, parent):
            if parent.isValid():
                # regardless of the current item, its parent is always a group
                parent_group: models.AlgorithmGroup = parent.internalPointer()
            else:  # we are on the root node
                parent_group = self.root_item
            all_items = parent_group.groups + parent_group.algorithms
            current_item = all_items[row]
            result = self.createIndex(row, column, current_item)
        else:
            result = invalid_index
        return result

    def _find_current_row(
            self,
            current_item: typing.Union[
                models.AlgorithmGroup, models.Algorithm],
            parent_group: models.AlgorithmGroup
    ) -> typing.Optional[int]:
        relevant_items = parent_group.groups + parent_group.algorithms
        for index, item in enumerate(relevant_items):
            if item.name == current_item.name:
                row = index
                break
        else:
            row = None
        return row

    def parent(self, index: QtCore.QModelIndex) -> QtCore.QModelIndex:
        invalid_index = QtCore.QModelIndex()
        if index.isValid():
            current_item = index.internalPointer()
            current_item: typing.Optional[
                models.AlgorithmGroup, models.Algorithm]
            parent_item = current_item.parent
            if parent_item is None:
                row = 0
            else:
                grand_parent_item = parent_item.parent
                if grand_parent_item is None:
                    row = self._find_current_row(parent_item, self.root_item)
                else:
                    row = self._find_current_row(parent_item, grand_parent_item)
            if row is None:
                result = invalid_index
            else:
                result = self.createIndex(row, 0, parent_item)
        else:
            result = invalid_index
        return result

    def rowCount(self, index: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        if index.column() > 0:
            result = 0
        elif index.isValid():
            current_item = index.internalPointer()
            current_item: typing.Optional[
                models.AlgorithmGroup, models.Algorithm]
            if current_item is not None:
                if current_item.item_type == models.AlgorithmNodeType.Group:
                    result = len(current_item.groups) + len(current_item.algorithms)
                else:
                    result = 0
            else:
                result = 0
        else:
            result = len(self.root_item.groups) + len(self.root_item.algorithms)
        return result

    def columnCount(self, index: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        return 1

    def data(
            self,
            index: QtCore.QModelIndex = QtCore.QModelIndex(),
            role: QtCore.Qt.ItemDataRole = QtCore.Qt.DisplayRole
    ) -> typing.Optional[
        typing.Union[models.AlgorithmGroup, models.Algorithm]
    ]:
        if index.isValid():
            current_item = index.internalPointer()
            if role == QtCore.Qt.DisplayRole:
                if index.column() == 0:
                    try:
                        result = f"{current_item.name} - {current_item.name_details}"
                    except AttributeError:
                        result = f"{current_item.name}"
                else:
                    result = f"row: {index.row()} column: 2"
            elif role == QtCore.Qt.ItemDataRole:
                result = current_item
            else:
                result = None
        else:
            result = None
        return result

    def flags(
            self,
            index: QtCore.QModelIndex = QtCore.QModelIndex()
    ) -> QtCore.Qt.ItemFlags:
        if index.isValid():
            default_flags = super().flags(index)
            current_item = index.internalPointer()
            result = default_flags
            if current_item.item_type == models.AlgorithmNodeType.Algorithm:
                result = default_flags | QtCore.Qt.ItemIsEditable
        else:
            result = QtCore.Qt.NoItemFlags
        return result


class AlgorithmItemDelegate(QtWidgets.QStyledItemDelegate):
    current_index: typing.Optional[QtCore.QModelIndex]
    algorithm_execution_handler: typing.Callable

    def __init__(
            self,
            algorithm_execution_handler: typing.Callable,
            parent: QtCore.QObject = None
    ):
        super().__init__(parent)
        self.parent = parent
        self.current_index = None
        self.algorithm_execution_handler = algorithm_execution_handler

    def paint(
            self,
            painter: QtGui.QPainter,
            option: QtWidgets.QStyleOptionViewItem,
            index: QtCore.QModelIndex
    ):
        item = index.internalPointer()
        if item.item_type == models.AlgorithmNodeType.Algorithm:
            editor_widget = self.createEditor(self.parent, option, index)
            editor_widget.setGeometry(option.rect)
            pixmap = editor_widget.grab()
            del editor_widget
            painter.drawPixmap(option.rect.x(), option.rect.y(), pixmap)
        else:
            super().paint(painter, option, index)

    def sizeHint(
            self,
            option: QtWidgets.QStyleOptionViewItem,
            index: QtCore.QModelIndex
    ):
        item = index.internalPointer()
        if item.item_type == models.AlgorithmNodeType.Algorithm:
            widget = self.createEditor(None, option, index)  # parent set to none otherwise remain painted in the widget
            size = widget.size()
            del widget
            result = size
        else:
            result = super().sizeHint(option, index)
        return result

    def createEditor(
            self,
            parent: QtWidgets.QWidget,
            option: QtWidgets.QStyleOptionViewItem,
            index: QtCore.QModelIndex
    ):
        item = index.internalPointer()
        if item.item_type == models.AlgorithmNodeType.Algorithm:
            result = AlgorithmEditorWidget(
                item, execution_handler=self.algorithm_execution_handler, parent=parent)
        else:
            result = super().createEditor(parent, option, index)
        return result

    def updateEditorGeometry(
            self,
            editor: QtWidgets.QWidget,
            option: QtWidgets.QStyleOptionViewItem,
            index: QtCore.QModelIndex
    ):
        editor.setGeometry(option.rect)


class AlgorithmEditorWidget(QtWidgets.QWidget, WidgetAlgorithmLeafUi):
    name_la: QtWidgets.QLabel
    description_la: QtWidgets.QLabel
    single_execution_mode_pb: QtWidgets.QPushButton
    multiple_execution_modes_tb: QtWidgets.QToolButton

    def __init__(
            self,
            algorithm: models.Algorithm,
            execution_handler: typing.Callable,
            parent=None
    ):
        super().__init__(parent)
        self.setupUi(self)
        self.setAutoFillBackground(True)  # this allow to hide background prerendered pixmap
        self.name_la.setText(algorithm.name)
        self.description_la.setText(algorithm.description)
        action_labels = {
            models.AlgorithmRunMode.LOCAL: "Run",
            models.AlgorithmRunMode.REMOTE: "Run with default data",
        }
        if len(algorithm.scripts) >= 2:
            self.multiple_execution_modes_tb.setPopupMode(
                QtWidgets.QToolButton.MenuButtonPopup)
            self.multiple_execution_modes_tb.setMenu(QtWidgets.QMenu())
            self.single_execution_mode_pb.hide()
            for action_type, action_label in action_labels.items():
                action = QtWidgets.QAction(tr(action_label), self)
                action.triggered.connect(
                    functools.partial(execution_handler, algorithm, action_type))
                self.multiple_execution_modes_tb.menu().addAction(action)
        elif len(algorithm.scripts) == 1:
            self.multiple_execution_modes_tb.hide()
            run_mode = algorithm.scripts[0].script.run_mode
            label = action_labels[run_mode]
            self.single_execution_mode_pb.setText(tr(label))
            self.single_execution_mode_pb.clicked.connect(
                functools.partial(execution_handler, algorithm, run_mode))
        else:
            self.single_execution_mode_pb.hide()
            self.multiple_execution_modes_tb.hide()
