import functools
import typing
from pathlib import Path

from PyQt5 import (
    QtCore,
    QtGui,
    QtWidgets,
    uic,
)

from .. import (
    layers,
    log,
)
from ..conf import (
    Setting,
    settings_manager,
)
from . import (
    manager,
    models,
)

WidgetDatasetItemUi, _ = uic.loadUiType(
    str(Path(__file__).parents[1] / "gui/WidgetDatasetItem.ui"))


class JobsModel(QtCore.QAbstractItemModel):
    _relevant_jobs: typing.List[models.Job]

    def __init__(self, job_manager: manager.JobManager, parent=None):
        super().__init__(parent)
        self._relevant_jobs = job_manager.relevant_jobs

    def index(
            self,
            row: int,
            column: int,
            parent: QtCore.QModelIndex
    ) -> QtCore.QModelIndex:
        invalid_index = QtCore.QModelIndex()
        if self.hasIndex(row, column, parent):
            try:
                job = self._relevant_jobs[row]
                result = self.createIndex(row, column, job)
            except IndexError:
                result = invalid_index
        else:
            result = invalid_index
        return result

    def parent(self, index: QtCore.QModelIndex) -> QtCore.QModelIndex:
        return QtCore.QModelIndex()

    def rowCount(self, index: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        return len(self._relevant_jobs)

    def columnCount(self, index: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        return 1

    def data(
            self,
            index: QtCore.QModelIndex = QtCore.QModelIndex(),
            role: QtCore.Qt.ItemDataRole = QtCore.Qt.DisplayRole
    ) -> typing.Optional[models.Job]:
        result = None
        if index.isValid():
            job = index.internalPointer()
            if role == QtCore.Qt.DisplayRole or role == QtCore.Qt.ItemDataRole:
                result = job
        return result

    def flags(
            self,
            index: QtCore.QModelIndex = QtCore.QModelIndex()
    ) -> QtCore.Qt.ItemFlags:
        if index.isValid():
            flags = super().flags(index)
            result = QtCore.Qt.ItemIsEditable | flags
        else:
            result = QtCore.Qt.NoItemFlags
        return result


class JobsSortFilterProxyModel(QtCore.QSortFilterProxyModel):
    current_sort_field: typing.Optional[models.SortField]

    def __init__(self, current_sort_field: models.SortField, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_sort_field = current_sort_field

    def filterAcceptsRow(self, source_row: int, source_parent: QtCore.QModelIndex):
        jobs_model = self.sourceModel()
        index = jobs_model.index(source_row, 0, source_parent)
        job: models.Job = jobs_model.data(index)
        match = self.filterRegularExpression().match(job.params.task_name)
        return match.hasMatch()

    def lessThan(self, left: QtCore.QModelIndex, right: QtCore.QModelIndex) -> bool:
        model = self.sourceModel()
        left_job: models.Job = model.data(left)
        right_job: models.Job = model.data(right)
        to_sort = (left_job, right_job)
        if self.current_sort_field == models.SortField.NAME:
            result = sorted(to_sort, key=lambda j: j.params.task_name)[0] == left_job
        elif self.current_sort_field == models.SortField.DATE:
            result = sorted(to_sort, key=lambda j: j.start_date)[0] == left_job
        elif self.current_sort_field == models.SortField.STATUS:
            result = sorted(to_sort, key=lambda j: j.status)[0] == left_job
        elif self.current_sort_field == models.SortField.ALGORITHM:
            result = sorted(to_sort, key=lambda j: j.script.name)[0] == left_job
        else:
            raise NotImplementedError
        return result


class JobItemDelegate(QtWidgets.QStyledItemDelegate):

    def __init__(self, parent: QtCore.QObject = None):
        super().__init__(parent)
        self.parent = parent
        # manage activate editing when entering the cell (if editable)
        self.enteredCell = None
        self.parent.entered.connect(self.manage_editing)

    def manage_editing(self, index: QtCore.QModelIndex):
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
        if not (flags & QtCore.Qt.ItemIsEditable):
            return

        # activate editor
        item = model.data(index, QtCore.Qt.DisplayRole)
        self.parent.openPersistentEditor(self.enteredCell)

    def paint(
            self,
            painter: QtGui.QPainter,
            option: QtWidgets.QStyleOptionViewItem,
            index: QtCore.QModelIndex
    ):
        # get item and manipulate painter basing on idetm data
        model = index.model()
        item = model.data(index, QtCore.Qt.DisplayRole)

        # if a Dataset => show custom widget
        if isinstance(item, models.Job):
            # get default widget used to edit data
            editorWidget = self.createEditor(self.parent, option, index)
            editorWidget.setGeometry(option.rect)

            # then grab and paint it
            pixmap = editorWidget.grab()
            del editorWidget
            painter.drawPixmap(option.rect.x(), option.rect.y(), pixmap)
        else:
            super().paint(painter, option, index)

    def sizeHint(
            self,
            option: QtWidgets.QStyleOptionViewItem,
            index: QtCore.QModelIndex
    ):
        model = index.model()
        item = model.data(index, QtCore.Qt.DisplayRole)

        if isinstance(item, models.Job):
            widget = self.createEditor(None, option, index)  # parent set to none otherwise remain painted in the widget
            size = widget.size()
            del widget
            return size

        return super().sizeHint(option, index)

    def createEditor(
            self,
            parent: QtWidgets.QWidget,
            option: QtWidgets.QStyleOptionViewItem,
            index: QtCore.QModelIndex
    ):
        # get item and manipulate painter basing on item data
        model = index.model()
        item = model.data(index, QtCore.Qt.DisplayRole)
        if isinstance(item, models.Job):
            return DatasetEditorWidget(item, parent=parent)
        else:
            return super().createEditor(parent, option, index)

    def updateEditorGeometry(
            self,
            editor: QtWidgets.QWidget,
            option: QtWidgets.QStyleOptionViewItem,
            index: QtCore.QModelIndex
    ):
        editor.setGeometry(option.rect)


class DatasetEditorWidget(QtWidgets.QWidget, WidgetDatasetItemUi):
    job: models.Job

    add_to_canvas_pb: QtWidgets.QPushButton
    creation_date_la: QtWidgets.QLabel
    delete_pb: QtWidgets.QPushButton
    download_pb: QtWidgets.QPushButton
    generated_by_la: QtWidgets.QLabel
    name_la: QtWidgets.QLabel
    open_details_pb: QtWidgets.QPushButton
    progressBar: QtWidgets.QProgressBar
    run_id_la: QtWidgets.QLabel

    def __init__(self, job: models.Job, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.job = job
        self.setAutoFillBackground(True)  # allows hiding background prerendered pixmap
        self.add_to_canvas_pb.clicked.connect(self.load_dataset)
        self.open_details_pb.clicked.connect(self.show_details)
        self.delete_pb.clicked.connect(self.delete_dataset)

        self.delete_pb.setIcon(
            QtGui.QIcon(':/plugins/LDMP/icons/mActionDeleteSelected.svg'))
        self.open_details_pb.setIcon(
            QtGui.QIcon(':/plugins/LDMP/icons/mActionPropertiesWidget.svg'))
        self.add_to_canvas_pb.setIcon(
            QtGui.QIcon(':/plugins/LDMP/icons/mActionAddRasterLayer.svg'))
        self.download_pb.setIcon(
            QtGui.QIcon(':/plugins/LDMP/icons/cloud-download.svg'))

        self.name_la.setText(str(self.job.params.task_name))
        self.generated_by_la.setText(str(self.job.script.name))
        self.creation_date_la.setText(
            self.job.start_date.strftime("%Y-%m-%dT%H:%M:%S.%f"))
        self.run_id_la.setText(str(self.job.id))

        self.download_pb.setEnabled(False)

        self.delete_pb.setEnabled(True)

        # set visibility of progress bar and download button
        if self.job.status in (models.JobStatus.RUNNING, models.JobStatus.PENDING):
            self.progressBar.setMinimum(0)
            self.progressBar.setMaximum(0)
            self.progressBar.setFormat('Processing...')
            self.progressBar.show()
            self.download_pb.hide()
            self.add_to_canvas_pb.setEnabled(False)
        elif self.job.status == models.JobStatus.FINISHED:
            self.progressBar.hide()
            result_auto_download = settings_manager.get_value(Setting.DOWNLOAD_RESULTS)
            if result_auto_download:
                self.download_pb.hide()
            else:
                self.download_pb.show()
                self.download_pb.setEnabled(True)
                self.download_pb.clicked.connect(
                    functools.partial(manager.job_manager.download_job_results, job)
                )
            self.add_to_canvas_pb.setEnabled(False)
        elif self.job.status == models.JobStatus.DOWNLOADED:
            self.progressBar.hide()
            self.download_pb.hide()
            self.add_to_canvas_pb.setEnabled(True)

    def show_details(self):
        log(f"Details button clicked for job {self.job.params.task_name!r}")

    def load_dataset(self):
        manager.job_manager.display_job_results(self.job)

    def delete_dataset(self):
        message_box = QtWidgets.QMessageBox()
        message_box.setText(
            f"You are about to delete job {self.job.params.task_name!r}")
        message_box.setInformativeText("Confirm?")
        message_box.setStandardButtons(
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel)
        message_box.setDefaultButton(QtWidgets.QMessageBox.Cancel)
        message_box.setIcon(QtWidgets.QMessageBox.Information)
        result = QtWidgets.QMessageBox.Res = message_box.exec_()
        if result == QtWidgets.QMessageBox.Yes:
            log("About to delete the dataset")
            for path in self.job.results.local_paths:
                layers.delete_layer_by_filename(str(path))
            manager.job_manager.delete_job(self.job)