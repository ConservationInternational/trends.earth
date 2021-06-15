import os
import functools
import typing
import json
from pathlib import Path
from zipfile import ZipFile

import qgis.core
import qgis.gui

from PyQt5 import (
    QtCore,
    QtGui,
    QtWidgets,
    uic,
)

from .. import (
    layers,
    log,
    openFolder,
    tr,
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

WidgetDatasetItemDetailsUi, _ = uic.loadUiType(
    str(Path(__file__).parents[1] / "gui/WidgetDatasetItemDetails.ui"))


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
    current_index: typing.Optional[QtCore.QModelIndex]

    def __init__(self, parent: QtCore.QObject = None):
        super().__init__(parent)
        self.parent = parent
        self.current_index = None

    def paint(
            self,
            painter: QtGui.QPainter,
            option: QtWidgets.QStyleOptionViewItem,
            index: QtCore.QModelIndex
    ):
        # get item and manipulate painter basing on idetm data
        proxy_model: QtCore.QSortFilterProxyModel = index.model()
        source_index = proxy_model.mapToSource(index)
        source_model = source_index.model()
        item = source_model.data(source_index, QtCore.Qt.DisplayRole)

        # if a Dataset => show custom widget
        if isinstance(item, models.Job):
            # get default widget used to edit data
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
        proxy_model: QtCore.QSortFilterProxyModel = index.model()
        source_index = proxy_model.mapToSource(index)
        source_model = source_index.model()
        item = source_model.data(source_index, QtCore.Qt.DisplayRole)

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
        proxy_model: QtCore.QSortFilterProxyModel = index.model()
        source_index = proxy_model.mapToSource(index)
        source_model = source_index.model()
        item = source_model.data(source_index, QtCore.Qt.DisplayRole)

        # item = model.data(index, QtCore.Qt.DisplayRole)
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


class DatasetActions:
    job: models.Job

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


class DatasetEditorWidget(QtWidgets.QWidget, DatasetActions,  WidgetDatasetItemUi):
    job: models.Job

    add_to_canvas_tb: QtWidgets.QToolButton
    creation_date_la: QtWidgets.QLabel
    delete_tb: QtWidgets.QToolButton
    download_tb: QtWidgets.QToolButton
    name_la: QtWidgets.QLabel
    open_details_tb: QtWidgets.QToolButton
    open_directory_tb: QtWidgets.QToolButton
    progressBar: QtWidgets.QProgressBar

    def __init__(self, job: models.Job, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.job = job
        self.setAutoFillBackground(True)  # allows hiding background prerendered pixmap
        self.add_to_canvas_tb.clicked.connect(self.load_dataset)
        self.open_details_tb.clicked.connect(self.show_details)
        self.open_directory_tb.clicked.connect(self.open_job_directory)
        self.delete_tb.clicked.connect(self.delete_dataset)

        self.delete_tb.setIcon(
            QtGui.QIcon(':/images/themes/default/mActionDeleteSelected.svg'))
        self.open_details_tb.setIcon(
            QtGui.QIcon(':/images/themes/default/mActionPropertiesWidget.svg'))
        self.open_directory_tb.setIcon(
            QtGui.QIcon(':/images/themes/default/mActionFileOpen.svg'))
        self.add_to_canvas_tb.setIcon(
            QtGui.QIcon(':/images/themes/default/mActionAddRasterLayer.svg'))
        self.download_tb.setIcon(
            QtGui.QIcon(':/plugins/LDMP/icons/cloud-download.svg'))

        task_name = self.job.params.task_name
        if task_name != "":
            name = f"{task_name}({self.job.script.name})"
        else:
            name = self.job.script.name
        self.name_la.setText(name)
        self.creation_date_la.setText(self.job.start_date.strftime("%Y-%m-%d %H:%M"))

        self.download_tb.setEnabled(False)

        self.delete_tb.setEnabled(True)

        # set visibility of progress bar and download button
        if self.job.status in (models.JobStatus.RUNNING, models.JobStatus.PENDING):
            self.progressBar.setMinimum(0)
            self.progressBar.setMaximum(0)
            self.progressBar.setFormat('Processing...')
            self.progressBar.show()
            self.download_tb.hide()
            self.add_to_canvas_tb.setEnabled(False)
        elif self.job.status == models.JobStatus.FINISHED:
            self.progressBar.hide()
            result_auto_download = settings_manager.get_value(Setting.DOWNLOAD_RESULTS)
            if result_auto_download:
                self.download_tb.hide()
            else:
                self.download_tb.show()
                self.download_tb.setEnabled(True)
                self.download_tb.clicked.connect(
                    functools.partial(manager.job_manager.download_job_results, job)
                )
            self.add_to_canvas_tb.setEnabled(False)
        elif self.job.status in (
                models.JobStatus.DOWNLOADED, models.JobStatus.GENERATED_LOCALLY):
            self.progressBar.hide()
            self.download_tb.hide()
            self.add_to_canvas_tb.setEnabled(True)

    def show_details(self):
        log(f"Details button clicked for job {self.job.params.task_name!r}")
        result = DatasetDetailsWidget(self.job).exec_()

    def open_job_directory(self):
        log(f"Open directory button clicked for job {self.job.params.task_name!r}")
        job_directory = manager.job_manager.get_job_file_path(self.job).parent
        # NOTE: not using QDesktopServices.openUrl here, since it seems to not be
        # working correctly (as of Jun 2021 on Ubuntu)
        openFolder(str(job_directory))

class DatasetDetailsWidget(QtWidgets.QDialog, DatasetActions, WidgetDatasetItemDetailsUi):

    def __init__(self, job: models.Job, parent=None):
        super(DatasetDetailsWidget, self).__init__(parent)
        self.setupUi(self)

        self.job = job

        self.name_le.setText(self.job.params.task_name)
        self.state_le.setText(self.job.status.value)
        self.created_at_le.setText(str(self.job.start_date))

        self.alg_le.setText(self.job.script.name)
        self.path = None

        for path in self.job.results.local_paths:
            if 'tif' in str(path):
                self.path = str(path)
        self.path_le.setText(self.path)

        self.load_btn.setIcon(
            QtGui.QIcon(':/plugins/LDMP/icons/mActionAddRasterLayer.svg'))
        self.export_btn.setIcon(
            QtGui.QIcon(':/plugins/LDMP/icons/export_zip.svg'))
        self.delete_btn.setIcon(
            QtGui.QIcon(':/plugins/LDMP/icons/mActionDeleteSelected.svg'))
        self.export_btn.clicked.connect(self.export_dataset)
        self.delete_btn.setEnabled(
            self.job.status == models.JobStatus.DOWNLOADED
        )
        self.delete_btn.clicked.connect(self.__delete_dataset)
        self.load_btn.clicked.connect(self.load_dataset)

        self.load_job_details()

        self.bar = qgis.gui.QgsMessageBar()
        self.bar.setSizePolicy(
            QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed
        )
        self.layout().addWidget(self.bar, 0, 0, alignment=QtCore.Qt.AlignTop)

    def __delete_dataset(self):
        self.delete_dataset()
        self.close()

    def export_dataset(self):
        log(f"Exporting dataset {self.job.params.task_name!r}")
        self.export_btn.setEnabled(False)

        # collect all files related to the dataset and compress them
        # into one zip file.
        dataset_base_dir = Path(os.path.dirname(self.path))
        file_name = os.path.splitext(os.path.basename(self.path))[0]
        folder_contents = dataset_base_dir.glob(f"{file_name}.*")
        files = [f for f in folder_contents if f.is_file()]

        manager.job_manager.exports_dir.mkdir(exist_ok=True)

        try:
            zipped_file = f"{str(manager.job_manager.exports_dir)}/" \
                          f"{self.job.params.task_name}.zip"
            with ZipFile(zipped_file, 'w') as zip:
                for file in files:
                    zip.write(file, os.path.basename(file))
        except Exception:
            self.bar.clearWidgets()
            message_bar_item = self.bar.createMessage(
                tr(f"Error exporting dataset {zipped_file}"))
            self.bar.pushWidget(message_bar_item, level=qgis.core.Qgis.Critical)

        self.bar.clearWidgets()
        message_bar_item = self.bar.createMessage(
            tr(f"Dataset exported to {zipped_file}"))
        self.bar.pushWidget(message_bar_item, level=qgis.core.Qgis.Info)

        self.export_btn.setEnabled(True)

    def load_job_details(self):
        self.comments.setText(self.job.params.task_notes.user_notes)
        self.input.setText(json.dumps(self.job.params.params, indent=4, sort_keys=True))
        self.output.setText(json.dumps(self.job.results.serialize(), indent=4, sort_keys=True))
