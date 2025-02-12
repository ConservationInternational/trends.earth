import datetime as dt
import functools
import os
import typing
from pathlib import Path

import qgis.core
import qgis.gui
from qgis.PyQt import QtCore, QtGui, QtWidgets, uic
from te_schemas.algorithms import AlgorithmRunMode
from te_schemas.jobs import JobStatus

from .algorithms import models as algorithm_models
from .algorithms import mvc as algorithms_mvc
from .conf import (
    ALGORITHM_TREE,
    DOCK_TITLE,
    DOCK_TITLE_OFFLINE,
    KNOWN_SCRIPTS,
    Setting,
    settings_manager,
)
from .data_io import DlgDataIOImportProd, DlgDataIOImportSOC, DlgDataIOLoadTE
from .download_data import DlgDownload
from .jobs import mvc as jobs_mvc
from .jobs.manager import job_manager
from .jobs.models import Job, SortField, TypeFilter
from .landpks import DlgLandPKSDownload
from .lc_setup import DlgDataIOImportLC
from .logger import log
from .select_dataset import DlgSelectDataset
from .utils import load_object
from .visualization import DlgVisualizationBasemap

DockWidgetTrendsEarthUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/WidgetMain.ui")
)


ICON_PATH = os.path.join(os.path.dirname(__file__), "icons")


class UpdateWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal()

    def run(self):
        self.work()
        self.finished.emit()

    def work(self):
        raise NotImplementedError


class LocalPeriodicUpdateWorker(UpdateWorker):
    def work(self):
        job_manager.refresh_local_state()


class RemoteStateRefreshWorker(UpdateWorker):
    def work(self):
        job_manager.refresh_from_remote_state()


class MainWidget(QtWidgets.QDockWidget, DockWidgetTrendsEarthUi):
    _SUB_INDICATORS_TAB_PAGE: int = 0
    _DATASETS_TAB_PAGE: int = 1

    iface: qgis.gui.QgisInterface
    refreshing_filesystem_cache: bool
    scheduler_paused: bool
    last_refreshed_local_state: typing.Optional[dt.datetime]
    last_refreshed_remote_state: typing.Optional[dt.datetime]

    algorithms_tv: QtWidgets.QTreeView
    algorithms_tv_delegate: algorithms_mvc.AlgorithmItemDelegate
    datasets_tv: QtWidgets.QTreeView
    lineEdit_search: QtWidgets.QLineEdit
    import_dataset_pb: QtWidgets.QPushButton
    create_layer_pb: QtWidgets.QPushButton
    pushButton_load: QtWidgets.QPushButton
    pushButton_download: QtWidgets.QPushButton
    pushButton_refresh: QtWidgets.QPushButton
    pushButton_filter: QtWidgets.QPushButton
    tabWidget: QtWidgets.QTabWidget

    cache_refresh_about_to_begin = QtCore.pyqtSignal()
    cache_refresh_finished = QtCore.pyqtSignal()

    remote_refresh_running: bool = False

    _cache_refresh_togglable_widgets: typing.List[QtWidgets.QWidget]

    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        parent: typing.Optional[QtWidgets.QWidget] = None,
    ):
        super().__init__(parent)
        self.iface = iface
        self.refreshing_filesystem_cache = False
        self.scheduler_paused = False
        self.setupUi(self)
        self._cache_refresh_togglable_widgets = [
            self.pushButton_refresh,
        ]
        self.last_refreshed_remote_state = None
        self.last_refreshed_local_state = None
        self.refreshing_local_state = False

        self.pu_thread = None
        self.pu_worker = None

        self.rs_thread = None
        self.rs_worker = None

        # remove space before dataset item
        self.datasets_tv.setIndentation(0)
        self.datasets_tv.verticalScrollBar().setSingleStep(10)

        self.message_bar_sort_filter = None

        self.proxy_model = None

        job_manager.refreshed_local_state.connect(self.refresh_after_cache_update)
        job_manager.refreshed_from_remote.connect(self.refresh_after_cache_update)
        job_manager.downloaded_job_results.connect(self.refresh_after_cache_update)
        job_manager.deleted_job.connect(self.refresh_after_cache_update)
        job_manager.submitted_remote_job.connect(self.refresh_after_job_modified)
        job_manager.processed_local_job.connect(self.refresh_after_job_modified)
        job_manager.imported_job.connect(self.refresh_after_job_modified)

        self.cache_refresh_about_to_begin.connect(
            functools.partial(self.toggle_ui_for_cache_refresh, True)
        )
        self.cache_refresh_finished.connect(
            functools.partial(self.toggle_ui_for_cache_refresh, False)
        )
        self.cache_refresh_about_to_begin.connect(
            functools.partial(self.toggle_refreshing_state, True)
        )
        self.cache_refresh_finished.connect(
            functools.partial(self.toggle_refreshing_state, False)
        )
        qgis.core.QgsProject.instance().layersRemoved.connect(
            self.refresh_after_cache_update
        )

        self.clean_empty_directories()
        self.setup_algorithms_tree()
        self.setup_datasets_page_gui()
        self._run_local_update_worker()  # perform an initial update, before the scheduler kicks in
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.perform_periodic_tasks)
        self.timer.start(
            settings_manager.get_value(Setting.UPDATE_FREQUENCY_MILLISECONDS)
        )

        offline_mode = settings_manager.get_value(Setting.OFFLINE_MODE)
        if offline_mode:
            self.pushButton_download.setEnabled(False)
            self.setWindowTitle(DOCK_TITLE_OFFLINE)
        else:
            self.pushButton_download.setEnabled(True)
            self.setWindowTitle(DOCK_TITLE)

        date_filter_enabled = settings_manager.get_value(Setting.DATE_FILTER_ENABLED)

        if not date_filter_enabled:
            date_filter_enabled = False

        self.date_filter_group.setChecked(date_filter_enabled)

        settings_start_date = settings_manager.get_value(Setting.FILTER_START_DATE)
        settings_end_date = settings_manager.get_value(Setting.FILTER_END_DATE)
        if settings_start_date != "" and settings_end_date != "":
            start_date = QtCore.QDateTime.fromString(
                settings_start_date, "yyyy-MM-dd HH:mm:ss"
            )
            end_date = QtCore.QDateTime.fromString(
                settings_end_date, "yyyy-MM-dd HH:mm:ss"
            )

            self.start_dte.setDateTime(start_date)
            self.end_dte.setDateTime(end_date)

        self.date_filter_group.toggled.connect(self.date_filter_group_toggled)
        date_filter_enabled = functools.partial(self.date_filter_changed, False)

        self.start_dte.dateChanged.connect(date_filter_enabled)
        self.end_dte.dateChanged.connect(date_filter_enabled)

    def date_filter_group_toggled(self, value):
        settings_manager.write_value(Setting.DATE_FILTER_ENABLED, value)
        self.date_filter_changed(disabled=not value)

    def date_filter_changed(self, disabled=False):
        settings_manager.write_value(
            Setting.FILTER_START_DATE,
            self.start_dte.dateTime().toString("yyyy-MM-dd HH:mm:ss"),
        )

        settings_manager.write_value(
            Setting.FILTER_END_DATE,
            self.end_dte.dateTime().toString("yyyy-MM-dd HH:mm:ss"),
        )

        start_date = self.start_dte.dateTime() if not disabled else None
        end_date = self.end_dte.dateTime() if not disabled else None

        if self.proxy_model:
            self.proxy_model.set_date_filter(start_date, end_date)

    def setup_datasets_page_gui(self):
        self.pushButton_refresh.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, "mActionRefresh.svg"))
        )
        self.pushButton_filter.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, "mActionFilter2.svg"))
        )
        self.filter_menu = QtWidgets.QMenu()
        action_show_all = self.filter_menu.addAction(self.tr("All"))
        action_show_all.setCheckable(True)
        action_show_all.triggered.connect(
            lambda: self.type_filter_changed(TypeFilter.ALL)
        )
        action_show_raster = self.filter_menu.addAction(self.tr("Raster"))
        action_show_raster.setCheckable(True)
        action_show_raster.triggered.connect(
            lambda: self.type_filter_changed(TypeFilter.RASTER)
        )
        action_show_vector = self.filter_menu.addAction(self.tr("Vector"))
        action_show_vector.setCheckable(True)
        action_show_vector.triggered.connect(
            lambda: self.type_filter_changed(TypeFilter.VECTOR)
        )
        filter_action_group = QtWidgets.QActionGroup(self)
        filter_action_group.addAction(action_show_all)
        filter_action_group.addAction(action_show_raster)
        filter_action_group.addAction(action_show_vector)
        action_show_all.setChecked(True)
        self.pushButton_filter.setMenu(self.filter_menu)

        self.import_menu = QtWidgets.QMenu()
        action_import_known_dataset = self.import_menu.addAction(
            self.tr("Load existing Trends.Earth output file...")
        )
        action_import_known_dataset.triggered.connect(self.import_known_dataset)
        action_import_productivity_dataset = self.import_menu.addAction(
            self.tr("Import custom Productivity dataset...")
        )
        action_import_productivity_dataset.triggered.connect(
            self.import_productivity_dataset
        )
        action_import_land_cover_dataset = self.import_menu.addAction(
            self.tr("Import custom Land Cover dataset...")
        )
        action_import_land_cover_dataset.triggered.connect(
            self.import_land_cover_dataset
        )
        action_import_soil_organic_carbon_dataset = self.import_menu.addAction(
            self.tr("Import custom Soil Organic Carbon dataset...")
        )
        action_import_soil_organic_carbon_dataset.triggered.connect(
            self.import_soil_organic_carbon_dataset
        )
        self.import_dataset_pb.setMenu(self.import_menu)
        self.import_dataset_pb.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, "mActionSharingImport.svg"))
        )

        self.download_menu = QtWidgets.QMenu()
        action_download_raw = self.download_menu.addAction(
            self.tr("Download raw dataset used in Trends.Earth...")
        )
        action_download_raw.triggered.connect(self.download_data)

        # TODO: re-enable this one LandPKS login is working
        # action_download_landpks = self.download_menu.addAction(
        #     self.tr("Download Land Potential Knowledge System (LandPKS) data...")
        # )
        # action_download_landpks.triggered.connect(self.download_landpks)
        # self.pushButton_download.setMenu(self.download_menu)
        # self.pushButton_download.setIcon(
        #     QtGui.QIcon(os.path.join(ICON_PATH, "cloud-download.svg"))
        # )

        self.pushButton_download.clicked.connect(self.download_data)

        self.pushButton_load.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, "document.svg"))
        )
        self.pushButton_load.clicked.connect(self.load_base_map)
        self.pushButton_refresh.clicked.connect(self.perform_single_update)

        self.error_recode_menu = QtWidgets.QMenu()
        action_create_error_recode = self.error_recode_menu.addAction(
            self.tr("Create false positive/negative layer")
        )
        action_create_error_recode.triggered.connect(self.create_error_recode)
        self.create_layer_pb.setMenu(self.error_recode_menu)
        # self.create_layer_pb.setIcon(
        #    QtGui.QIcon(os.path.join(ICON_PATH, "cloud-download.svg")))

        # to allow emit entered events and manage editing over mouse
        self.datasets_tv.setMouseTracking(True)
        # add ... to wrap DisplayRole text... to have a real wrap need a custom widget
        self.datasets_tv.setWordWrap(True)
        self.datasets_tv_delegate = jobs_mvc.JobItemDelegate(
            self, parent=self.datasets_tv
        )
        self.datasets_tv.setItemDelegate(self.datasets_tv_delegate)
        self.datasets_tv.setEditTriggers(QtWidgets.QAbstractItemView.AllEditTriggers)
        # self.datasets_tv.clicked.connect(self._manage_datasets_tree_view)
        self.datasets_tv.entered.connect(self._manage_datasets_tree_view)

        offline_mode = settings_manager.get_value(Setting.OFFLINE_MODE)
        if offline_mode:
            self.pushButton_download.setEnabled(False)
            self.setWindowTitle(DOCK_TITLE)
        else:
            self.pushButton_download.setEnabled(True)
            self.setWindowTitle(DOCK_TITLE_OFFLINE)

    def refresh_after_cache_update(self):
        current_dataset_index = self.datasets_tv_delegate.current_index

        if current_dataset_index is not None:
            has_open_editor = self.datasets_tv.isPersistentEditorOpen(
                current_dataset_index
            )

            if has_open_editor:
                self.datasets_tv.closePersistentEditor(current_dataset_index)
            self.datasets_tv_delegate.current_index = None

        maybe_download_finished_results()
        model = jobs_mvc.JobsModel(job_manager)
        # self.datasets_tv.setModel(model)
        self.proxy_model = jobs_mvc.JobsSortFilterProxyModel(SortField.DATE)
        self.type_filter_changed(TypeFilter.ALL)
        self.date_filter_changed(disabled=not self.date_filter_group.isChecked())

        self.filter_changed("")
        action = self.filter_menu.actions()[0]
        action.setChecked(True)
        self.proxy_model.setSourceModel(model)
        self.lineEdit_search.valueChanged.connect(self.filter_changed)
        self.datasets_tv.setModel(self.proxy_model)
        self.resume_scheduler()
        self.cache_refresh_finished.emit()

    def perform_periodic_tasks(self):
        """Handle periodic execution of plugin related tasks

        This slot is connected to a QTimer and is called periodically by Qt every
        `Setting.UPDATE_FREQUENCY_MILLISECONDS` - check this class's `__init__` method
        for details.

        This slot takes care of refreshing the local state and, if configured as such,
        it also contacts the remote server in order to get an updated state. These two
        tasks are controlled by different settings:

        - local state, which consists in scanning the Trends.Earth base directory for
          new datasets and updated job descriptions uses a frequency of
          `Setting.LOCAL_POLLING_FREQUENCY`

        - remote state, which consists in retrieving running job information from the
          remote server uses a frequency of `Setting.REMOTE_POLLING_FREQUENCY`.

        """
        if self.refreshing_filesystem_cache:
            # log("Filesystem cache is already being refreshed, skipping...")
            pass
        elif self.scheduler_paused:
            # log("Scheduling is paused, skipping...")
            pass
        else:
            run_local_worker = False
            run_remote_worker = False

            local_frequency = settings_manager.get_value(
                Setting.LOCAL_POLLING_FREQUENCY
            )

            if _should_run(local_frequency, self.last_refreshed_local_state):
                # lets check if we also need to update from remote, as that takes
                # precedence
                if not settings_manager.get_value(
                    Setting.OFFLINE_MODE
                ) and settings_manager.get_value(Setting.POLL_REMOTE):
                    remote_frequency = settings_manager.get_value(
                        Setting.REMOTE_POLLING_FREQUENCY
                    )
                    if (
                        _should_run(remote_frequency, self.last_refreshed_remote_state)
                        and not self.remote_refresh_running
                    ):
                        run_remote_worker = True
                    else:
                        run_local_worker = True
                else:
                    run_local_worker = True

            if run_local_worker:
                self._run_local_update_worker()
            else:
                if run_remote_worker:
                    self._run_remote_update_worker()

    def _run_local_update_worker(self):
        # Create thread worker for refreshing local state via the job_manager.
        if self.refreshing_local_state:
            return

        def _update_local_refreshing_state():
            self.refreshing_local_state = True

        self.pu_thread = QtCore.QThread()
        self.pu_worker = LocalPeriodicUpdateWorker()
        self.pu_worker.moveToThread(self.pu_thread)
        self.pu_thread.started.connect(self.pu_worker.run)
        self.pu_thread.started.connect(_update_local_refreshing_state)
        self.pu_worker.finished.connect(self.pu_thread.quit)
        self.pu_thread.finished.connect(self._on_finish_updating_local_state)
        self.pu_worker.finished.connect(self.pu_worker.deleteLater)
        self.pu_thread.finished.connect(self.pu_thread.deleteLater)

        if settings_manager.get_value(Setting.DEBUG):
            log("updating local state...")

        self.cache_refresh_about_to_begin.emit()
        self.refreshing_local_state = True
        self.pu_thread.start()

    def _on_finish_updating_local_state(self):
        # Slot raised when job_manager has finished refreshing the local state.
        self.last_refreshed_local_state = dt.datetime.now(tz=dt.timezone.utc)
        self.refreshing_local_state = False

    def _run_remote_update_worker(self):
        # Create thread worker for refreshing remote state.
        self.rs_thread = QtCore.QThread()
        self.rs_worker = RemoteStateRefreshWorker()
        self.rs_worker.moveToThread(self.rs_thread)
        self.rs_thread.started.connect(self.rs_worker.run)
        self.rs_worker.finished.connect(self.rs_thread.quit)
        self.rs_thread.finished.connect(self._on_finish_updating_remote_state)
        self.rs_worker.finished.connect(self.rs_worker.deleteLater)
        self.rs_thread.finished.connect(self.rs_thread.deleteLater)

        if settings_manager.get_value(Setting.DEBUG):
            log("updating remote state...")

        self.set_remote_refresh_running(True)
        self.update_refresh_button_status()
        self.cache_refresh_about_to_begin.emit()
        self.rs_thread.start()

    def _on_finish_updating_remote_state(self):
        # Slot raised when job_manager has finished refreshing the remote state.
        self.last_refreshed_remote_state = dt.datetime.now(tz=dt.timezone.utc)
        self.set_remote_refresh_running(False)
        self.update_refresh_button_status()

    def clean_empty_directories(self):
        """Remove any Job or Dataset empty folder. Job or Dataset folder can be empty
        due to delete action by the user.
        """
        base_data_directory = settings_manager.get_value(Setting.BASE_DIR)

        if not base_data_directory:
            return

        def clean(folders):
            for folder in folders:
                # floder leaf is empty if ('folder', [], [])

                if not folder[1] and not folder[2]:
                    os.rmdir(folder[0])

        # remove empty Jobs folders
        jobs_path = os.path.join(base_data_directory, "Jobs")
        folders = list(os.walk(jobs_path))[1:]
        clean(folders)

        # remove empty Datasets folders
        datasets_path = os.path.join(base_data_directory, "outputs")
        folders = list(os.walk(datasets_path))[1:]
        clean(folders)

    def perform_single_update(self):
        # self.update_from_remote_state()
        self._run_remote_update_worker()

    def set_remote_refresh_running(self, val: bool = True):
        self.remote_refresh_running = val

    def update_from_remote_state(self):
        if settings_manager.get_value(Setting.DEBUG):
            log("updating remote state...")
        # self.set_remote_refresh_running()
        # self.su_thread = QtCore.QThread(self.iface.mainWindow())
        # self.update_worker = RemoteStateRefreshWorker(self)
        # self.update_worker.moveToThread(self.su_thread)
        # self.su_thread.started.connect(self.update_worker.run)
        # self.su_thread.started.connect(self.update_refresh_button_status)
        # self.update_worker.finished.connect(
        #     functools.partial(self.set_remote_refresh_running, False))
        # self.update_worker.finished.connect(self.update_refresh_button_status)
        # self.update_worker.finished.connect(self.su_thread.quit)
        # self.update_worker.finished.connect(self.update_worker.deleteLater)
        # self.su_thread.finished.connect(self.su_thread.deleteLater)
        # self.su_thread.start()

        self.set_remote_refresh_running(True)
        self.update_refresh_button_status()
        self.cache_refresh_about_to_begin.emit()
        job_manager.refresh_from_remote_state()
        self.last_refreshed_remote_state = dt.datetime.now(tz=dt.timezone.utc)
        self.set_remote_refresh_running(False)
        self.update_refresh_button_status()

    def update_local_state(self):
        """Update the state of local datasets"""

        if settings_manager.get_value(Setting.DEBUG):
            log("updating local state...")
        self.cache_refresh_about_to_begin.emit()
        job_manager.refresh_local_state()
        self.last_refreshed_local_state = dt.datetime.now(tz=dt.timezone.utc)

    def toggle_ui_for_cache_refresh(self, refresh_started: bool):
        if settings_manager.get_value(Setting.DEBUG):
            log(
                f"toggle_ui_for_cache_refresh called. refresh_started: {refresh_started}"
            )

        for widget in self._cache_refresh_togglable_widgets:
            widget.setEnabled(not refresh_started)

    def toggle_refreshing_state(self, refresh_started: bool):
        if settings_manager.get_value(Setting.DEBUG):
            log(f"toggle_refreshing_state called. refresh_started: {refresh_started}")
        self.refreshing_filesystem_cache = refresh_started

    def refresh_after_job_modified(self, job: Job):
        self.refresh_after_cache_update()

    def filter_changed(self, filter_string: str):
        special_chars = [
            "*",
            ".",
            "[",
            "]",
        ]
        has_special_char = False

        for char in filter_string:
            if char in special_chars:
                has_special_char = True

                break
        filter_ = filter_string if has_special_char else f"{filter_string}*"
        self.proxy_model.setFilterRegExp(
            QtCore.QRegExp(filter_, QtCore.Qt.CaseInsensitive, QtCore.QRegExp.Wildcard)
        )

    def type_filter_changed(self, type_filter: TypeFilter):
        self.proxy_model.set_type_filter(type_filter)
        self.lineEdit_search.setText("")
        self.filter_changed("")

    def setup_algorithms_tree(self):
        self.algorithms_tv.setStyleSheet(
            "QTreeView { selection-background-color: white; selection-color: black }"
        )
        # NOTE: mouse tracking is needed in order to use the `entered` signal, which
        # we need (check below)
        self.algorithms_tv.setMouseTracking(True)
        # add ... to wrap DisplayRole text... to have a real wrap need a custom widget
        self.algorithms_tv.setWordWrap(True)
        model = algorithms_mvc.AlgorithmTreeModel(ALGORITHM_TREE)
        self.algorithms_tv.setModel(model)
        self.algorithms_tv_delegate = algorithms_mvc.AlgorithmItemDelegate(
            self.launch_algorithm_execution_dialogue, self, self.algorithms_tv
        )
        self.algorithms_tv.setItemDelegate(self.algorithms_tv_delegate)
        self.algorithms_tv.setEditTriggers(QtWidgets.QAbstractItemView.AllEditTriggers)
        self.algorithms_tv.entered.connect(self._manage_algorithm_tree_view)
        self.tabWidget.setCurrentIndex(self._SUB_INDICATORS_TAB_PAGE)

    def create_error_recode(self):
        dlg = DlgSelectDataset(self, validate_all=True)
        win_title = f"{dlg.windowTitle()} - {self.tr('False positive/negative')}"
        dlg.setWindowTitle(win_title)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self.pause_scheduler()

            prod = dlg.prod_band()
            lc = dlg.lc_band()
            soil = dlg.soil_band()
            sdg = dlg.sdg_band()
            task_name = dlg.task_name
            job_manager.create_error_recode(task_name, lc, soil, prod, sdg)

            self.resume_scheduler()

    def update_refresh_button_status(self):
        if self.remote_refresh_running:
            self.pushButton_refresh.setEnabled(False)
        else:
            self.pushButton_refresh.setEnabled(True)

    def pause_scheduler(self):
        self.scheduler_paused = True

    def resume_scheduler(self):
        self.scheduler_paused = False

    def launch_algorithm_execution_dialogue(
        self, algorithm: algorithm_models.Algorithm, run_mode: AlgorithmRunMode
    ):
        algorithm_script = _get_script(algorithm, run_mode)
        dialog_class_path = algorithm_script.parametrization_dialogue
        dialog_class = load_object(dialog_class_path)
        dialog = dialog_class(self.iface, algorithm_script.script, parent=self)
        self.pause_scheduler()
        result = dialog.exec_()

        if result == QtWidgets.QDialog.Rejected:
            self.resume_scheduler()
        else:
            # if the dialog has been accepted we will resume the scheduler only after
            # the datasets treeview has been refreshed
            pass

    def _manage_datasets_tree_view(self, index: QtCore.QModelIndex):
        """Manage dataset treeview's editing

        Since we are using a custom delegate for providing editing functionalities to
        the datasets treeview, we need to manage when the delegate should have an
        open editor widget. In this case we are not doing any real editing, but since we
        do show some buttons on the custom widget, we need the delegate to be in
        editing mode so that we can interact with the buttons

        """

        if index.isValid():
            # current_item = index.internalPointer()
            source_index = self.proxy_model.mapToSource(index)
            current_item = source_index.internalPointer()
            current_item: Job

            if current_item is not None:
                previous_index = self.datasets_tv_delegate.current_index
                index_changed = index != previous_index

                if previous_index is not None:
                    previously_open = self.datasets_tv.isPersistentEditorOpen(
                        previous_index
                    )
                else:
                    previously_open = False

                if index_changed and previously_open:
                    self.datasets_tv.closePersistentEditor(previous_index)
                    self.datasets_tv.openPersistentEditor(index)
                elif index_changed and not previously_open:
                    self.datasets_tv.openPersistentEditor(index)
                elif not index_changed and previously_open:
                    pass
                elif not index_changed and not previously_open:
                    self.datasets_tv.openPersistentEditor(index)

            self.datasets_tv_delegate.current_index = index

    def _manage_algorithm_tree_view(self, index: QtCore.QModelIndex):
        """Manage algorithm treeview's editing

        Since we are using a custom delegate for providing editing functionalities to
        the algorithms treeview, we need to manage when the delegate should have an
        open editor widget. In this case we are not doing any real editing, but since we
        do show some buttons on the custom widget, we need the delegate to be in
        editing mode so that we can interact with the buttons

        """

        if index.isValid():
            current_item = index.internalPointer()
            current_item: typing.Union[
                algorithm_models.AlgorithmGroup, algorithm_models.Algorithm
            ]
            is_algorithm = (
                current_item.item_type == algorithm_models.AlgorithmNodeType.Algorithm
            )

            if current_item is not None and is_algorithm:
                previous_index = self.algorithms_tv_delegate.current_index
                index_changed = index != previous_index

                if previous_index is not None:
                    previously_open = self.algorithms_tv.isPersistentEditorOpen(
                        previous_index
                    )
                else:
                    previously_open = False

                if index_changed and previously_open:
                    self.algorithms_tv.closePersistentEditor(previous_index)
                    self.algorithms_tv.openPersistentEditor(index)
                elif index_changed and not previously_open:
                    self.algorithms_tv.openPersistentEditor(index)
                elif not index_changed and previously_open:
                    pass
                elif not index_changed and not previously_open:
                    self.algorithms_tv.openPersistentEditor(index)
            self.algorithms_tv_delegate.current_index = index

    def load_base_map(self):
        dialogue = DlgVisualizationBasemap(self)
        dialogue.exec_()

    def download_data(self):
        dialogue = DlgDownload(self.iface, KNOWN_SCRIPTS["download-data"], self)
        dialogue.exec_()

    def download_landpks(self):
        dialogue = DlgLandPKSDownload(
            self.iface, KNOWN_SCRIPTS["download-landpks"], self
        )
        dialogue.exec_()

    def import_known_dataset(self, action: QtWidgets.QAction):
        dialogue = DlgDataIOLoadTE(self)
        dialogue.exec_()

    def import_productivity_dataset(self, action: QtWidgets.QAction):
        log("import_productivity_dataset called")
        dialogue = DlgDataIOImportProd(self)
        dialogue.exec_()

    def import_land_cover_dataset(self, action: QtWidgets.QAction):
        log("import_land_cover_dataset called")
        dialogue = DlgDataIOImportLC(self)
        dialogue.exec_()

    def import_soil_organic_carbon_dataset(self, action: QtWidgets.QAction):
        log("import_soil_organic_carbon_dataset called")
        dialogue = DlgDataIOImportSOC(self)
        dialogue.exec_()


def maybe_download_finished_results():
    offline_mode = settings_manager.get_value(Setting.OFFLINE_MODE)
    dataset_auto_download = settings_manager.get_value(Setting.DOWNLOAD_RESULTS)

    if not offline_mode and dataset_auto_download:
        if len(job_manager.known_jobs[JobStatus.FINISHED]) > 0:
            log("downloading results...")
            job_manager.download_available_results()


def _should_run(periodic_frequency_seconds: int, last_run: dt.datetime):
    """Check whether some periodic task should be run"""
    now = dt.datetime.now(tz=dt.timezone.utc)
    try:
        delta = now - last_run
    except TypeError:
        delta = dt.timedelta(seconds=periodic_frequency_seconds)

    return True if delta.seconds >= periodic_frequency_seconds else False


def _get_script(
    algorithm: algorithm_models.Algorithm, run_mode: AlgorithmRunMode
) -> algorithm_models.AlgorithmScript:
    for algorithm_script in algorithm.scripts:
        if algorithm_script.script.run_mode == run_mode:
            result = algorithm_script

            break
    else:
        raise RuntimeError(
            f"invalid algorithm configuration for {algorithm.name!r} - Could not "
            f"find a script for run mode: {run_mode}"
        )

    return result
