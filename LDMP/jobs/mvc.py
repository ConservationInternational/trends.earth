import functools
import typing
from pathlib import Path

from qgis.utils import iface

from PyQt5 import (
    QtCore,
    QtGui,
    QtWidgets,
    uic,
)
from .. import (
    layers,
    openFolder,
    utils,
)
from ..conf import (
    Setting,
    settings_manager,
)
from . import (
    manager,
    models,
)

from ..data_io import DlgDataIOAddLayersToMap
from ..datasets_dialog import DatasetDetailsDialogue

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
        reg_exp = self.filterRegExp()
        return reg_exp.exactMatch(job.visible_name)

    def lessThan(self, left: QtCore.QModelIndex, right: QtCore.QModelIndex) -> bool:
        model = self.sourceModel()
        left_job: models.Job = model.data(left)
        right_job: models.Job = model.data(right)
        to_sort = (left_job, right_job)

        if self.current_sort_field == models.SortField.DATE:
            result = sorted(to_sort, key=lambda j: j.start_date)[0] == left_job
        else:
            raise NotImplementedError

        return result


class JobItemDelegate(QtWidgets.QStyledItemDelegate):
    current_index: typing.Optional[QtCore.QModelIndex]
    main_dock: "MainWidget"

    def __init__(
            self,
            main_dock: "MainWidget",
            parent: QtCore.QObject = None,
    ):
        super().__init__(parent)
        self.parent = parent
        self.main_dock = main_dock
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
            return DatasetEditorWidget(item, self.main_dock, parent=parent)
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
    main_dock: "MainWidget"

    add_to_canvas_pb: QtWidgets.QPushButton
    creation_date_la: QtWidgets.QLabel
    delete_tb: QtWidgets.QToolButton
    download_tb: QtWidgets.QToolButton
    name_la: QtWidgets.QLabel
    open_details_tb: QtWidgets.QToolButton
    open_directory_tb: QtWidgets.QToolButton
    progressBar: QtWidgets.QProgressBar

    def __init__(self, job: models.Job, main_dock: "MainWidget", parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.job = job
        self.main_dock = main_dock
        self.setAutoFillBackground(True)  # allows hiding background prerendered pixmap

        self.load_data_menu_setup()
        self.add_to_canvas_pb.setMenu(self.load_data_menu)

        self.open_details_tb.clicked.connect(self.show_details)
        self.open_directory_tb.clicked.connect(self.open_job_directory)
        self.delete_tb.clicked.connect(
            functools.partial(utils.delete_dataset, self.job))

        self.delete_tb.setIcon(
            QtGui.QIcon(':/images/themes/default/mActionDeleteSelected.svg'))
        self.open_details_tb.setIcon(
            QtGui.QIcon(':/images/themes/default/mActionPropertiesWidget.svg'))
        self.open_directory_tb.setIcon(
            QtGui.QIcon(':/images/themes/default/mActionFileOpen.svg'))
        self.add_to_canvas_pb.setIcon(
            QtGui.QIcon(':/images/themes/default/mActionAddRasterLayer.svg'))
        self.download_tb.setIcon(
            QtGui.QIcon(':/plugins/LDMP/icons/cloud-download.svg'))

        self.name_la.setText(self.job.visible_name)
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
            self.add_to_canvas_pb.setEnabled(False)
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
            self.add_to_canvas_pb.setEnabled(False)
        elif self.job.status in (
                models.JobStatus.DOWNLOADED, models.JobStatus.GENERATED_LOCALLY):
            self.progressBar.hide()
            self.download_tb.hide()
            self.add_to_canvas_pb.setEnabled(self.has_loadable_result())

    def has_loadable_result(self):
        result = False
        if self.job.results is not None:
            if (self.job.results.data_path and
                    self.job.results.data_path.suffix in [".vrt", ".tif"] and
                    self.job.results.data_path.exists()):
                result = True
        return result

    def show_details(self):
        self.main_dock.pause_scheduler()
        DatasetDetailsDialogue(
            self.job,
            parent=iface.mainWindow()
        ).exec_()
        self.main_dock.resume_scheduler()

    def open_job_directory(self):
        job_directory = manager.job_manager.get_job_file_path(self.job).parent
        # NOTE: not using QDesktopServices.openUrl here, since it seems to not be
        # working correctly (as of Jun 2021 on Ubuntu)
        openFolder(str(job_directory))

    def load_data_menu_setup(self):
        self.load_data_menu = QtWidgets.QMenu()
        action_add_default_data_to_map = self.load_data_menu.addAction(
            self.tr("Add default layers from this dataset to map")
        )
        action_add_default_data_to_map.triggered.connect(
            self.load_dataset)
        action_choose_layers_to_add_to_map = self.load_data_menu.addAction(
            self.tr("Select specific layers from this dataset to add to map...")
        )
        action_choose_layers_to_add_to_map.triggered.connect(
            self.load_dataset_choose_layers)

    def load_dataset(self):
        manager.job_manager.display_default_job_results(self.job)

    def load_dataset_choose_layers(self):
        dialogue = DlgDataIOAddLayersToMap(
            self,
            self.job
        )
        dialogue.exec_()
