import datetime as dt
import functools
import os
import typing
from pathlib import Path

import qgis.gui
from PyQt5 import (
    QtWidgets,
    QtGui,
    QtCore,
    uic,
)

from . import (
    log,
    tr,
)
from .algorithms import (
    models as algorithm_models,
    mvc as algorithms_mvc,
)
from .conf import (
    ALGORITHM_TREE,
    KNOWN_SCRIPTS,
    Setting,
    settings_manager,
)
from .data_io import (
    DlgDataIO,
    DlgDataIOLoadTE,
    DlgDataIOImportLC,
    DlgDataIOImportSOC,
    DlgDataIOImportProd,
)
from .download_data import DlgDownload
from .jobs.manager import job_manager
from .jobs import mvc as jobs_mvc
from .jobs.models import (
    Job,
    JobStatus,
    SortField,
)
from .utils import load_object
from .visualization import DlgVisualizationBasemap

DockWidgetTrendsEarthUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/WidgetMain.ui"))


class MainWidget(QtWidgets.QDockWidget, DockWidgetTrendsEarthUi):
    _SUB_INDICATORS_TAB_PAGE: int = 0
    _DATASETS_TAB_PAGE: int = 1

    iface: qgis.gui.QgisInterface
    busy: bool
    last_refreshed_local_state: typing.Optional[dt.datetime]
    last_refreshed_remote_state: typing.Optional[dt.datetime]

    algorithms_tv: QtWidgets.QTreeView
    algorithms_tv_delegate: algorithms_mvc.AlgorithmItemDelegate
    datasets_tv: QtWidgets.QTreeView
    lineEdit_search: QtWidgets.QLineEdit
    import_dataset_pb: QtWidgets.QPushButton
    pushButton_load: QtWidgets.QPushButton
    pushButton_download: QtWidgets.QPushButton
    pushButton_refresh: QtWidgets.QPushButton
    reverse_box: QtWidgets.QCheckBox
    tab_widget: QtWidgets.QTabWidget
    toolButton_sort: QtWidgets.QToolButton

    cache_synchronization_began = QtCore.pyqtSignal()
    cache_synchronization_ended = QtCore.pyqtSignal()

    _editing_widgets: typing.List[QtWidgets.QWidget]

    def __init__(
            self,
            iface: qgis.gui.QgisInterface,
            parent: typing.Optional[QtWidgets.QWidget] = None
    ):
        super().__init__(parent)
        self.iface = iface
        self.busy = False
        self.setupUi(self)
        self._editing_widgets = [
            self.pushButton_refresh,
            self.toolButton_sort,
        ]
        self.last_refreshed_remote_state = None
        self.last_refreshed_local_state = None

        # remove space before dataset item
        self.datasets_tv.setIndentation(0)
        self.datasets_tv.verticalScrollBar().setSingleStep(10)

        self.message_bar_sort_filter = None

        job_manager.refreshed_local_state.connect(self.refresh_after_cache_update)
        job_manager.refreshed_from_remote.connect(self.refresh_after_cache_update)
        job_manager.downloaded_job_results.connect(self.refresh_after_cache_update)
        job_manager.downloaded_available_jobs_results.connect(
            self.refresh_after_cache_update)
        job_manager.deleted_job.connect(self.refresh_after_cache_update)
        job_manager.submitted_job.connect(self.refresh_after_job_modified)
        job_manager.imported_job.connect(self.refresh_after_job_modified)
        self.clean_empty_directories()
        self.setup_algorithms_tree()
        self.setup_datasets_page_gui()
        self.update_local_state()  # perform an initial update, before the scheduler kicks in
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.perform_periodic_tasks)
        self.timer.start(
            settings_manager.get_value(Setting.UPDATE_FREQUENCY_MILLISECONDS))

    def setup_datasets_page_gui(self):
        # add sort actions
        self.toolButton_sort.setMenu(QtWidgets.QMenu())
        self.toolButton_sort.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
        for member in SortField:
            sort_action = QtWidgets.QAction(tr(member.value), self)
            sort_action.setData(member)
            sort_action.triggered.connect(
                functools.partial(self.sort_jobs, sort_action))
            self.toolButton_sort.menu().addAction(sort_action)
            if member == SortField.DATE:
                self.toolButton_sort.setDefaultAction(sort_action)
        self.toolButton_sort.defaultAction().setToolTip(
            tr('Sort the datasets using the selected property.')
        )
        self.pushButton_refresh.setIcon(
            QtGui.QIcon(':/plugins/LDMP/icons/mActionRefresh.svg'))
        self.import_menu = QtWidgets.QMenu()
        action_import_known_dataset = self.import_menu.addAction(
            tr("Load existing Trends.Earth output file...")
        )
        action_import_known_dataset.triggered.connect(self.import_known_dataset)
        action_import_productivity_dataset = self.import_menu.addAction(
            tr("Import custom Productivity dataset...")
        )
        action_import_productivity_dataset.triggered.connect(
            self.import_productivity_dataset)
        action_import_land_cover_dataset = self.import_menu.addAction(
            tr("Import custom Land Cover dataset...")
        )
        action_import_land_cover_dataset.triggered.connect(
            self.import_land_cover_dataset)
        action_import_soil_organic_carbon_dataset = self.import_menu.addAction(
            tr("Import custom Soil Organic Carbon dataset...")
        )
        action_import_soil_organic_carbon_dataset.triggered.connect(
            self.import_soil_organic_carbon_dataset)
        self.import_dataset_pb.setMenu(self.import_menu)
        self.import_dataset_pb.setIcon(
            QtGui.QIcon(":/plugins/LDMP/icons/mActionSharingImport.svg"))


        self.pushButton_download.setIcon(
            QtGui.QIcon(":/plugins/LDMP/icons/cloud-download.svg"))
        self.pushButton_load.setIcon(QtGui.QIcon(':/plugins/LDMP/icons/document.svg'))
        self.pushButton_download.clicked.connect(self.download_data)
        self.pushButton_load.clicked.connect(self.load_base_map)
        self.pushButton_refresh.clicked.connect(self.perform_single_update)

        self.datasets_tv.setMouseTracking(True)  # to allow emit entered events and manage editing over mouse
        self.datasets_tv.setWordWrap(True)  # add ... to wrap DisplayRole text... to have a real wrap need a custom widget
        self.datasets_tv_delegate = jobs_mvc.JobItemDelegate(self.datasets_tv)
        self.datasets_tv.setItemDelegate(self.datasets_tv_delegate)
        self.datasets_tv.setEditTriggers(
            QtWidgets.QAbstractItemView.AllEditTriggers)
        # self.datasets_tv.clicked.connect(self._manage_datasets_tree_view)
        self.datasets_tv.entered.connect(self._manage_datasets_tree_view)

    def refresh_after_cache_update(self):
        current_dataset_index = self.datasets_tv_delegate.current_index
        if current_dataset_index is not None:
            has_open_editor = self.datasets_tv.isPersistentEditorOpen(
                current_dataset_index)
            if has_open_editor:
                self.datasets_tv.closePersistentEditor(current_dataset_index)
            self.datasets_tv_delegate.current_index = None

        maybe_download_finished_results()
        model = jobs_mvc.JobsModel(job_manager)
        # self.datasets_tv.setModel(model)

        self.proxy_model = jobs_mvc.JobsSortFilterProxyModel(SortField.DATE)
        self.proxy_model.setSourceModel(model)
        self.lineEdit_search.valueChanged.connect(self.filter_changed)
        self.datasets_tv.setModel(self.proxy_model)
        self.toggle_editing_widgets(True)

    def perform_periodic_tasks(self):
        """Handle periodic execution of plugin related tasks

        This slot is connected to a QTimer and is called periodically by Qt every
        `Setting.UPDATE_FREQUENCY_MILLISECONDS` - check this class's `__init__` method
        for details.

        This slot takes care of refreshing the local state and, if configured as such,
        it also contacte the remote server in order to get an updated state. These two
        tasks are controlled by different settings:

        - local state, which consists in scanning the Trends.Earth base directory for
          new datasets and updated job descriptions uses a frequency of
          `Setting.LOCAL_POLLING_FREQUENCY`

        - remote state, which consists in retrieving running job information from the
          remote server uses a frequency of `Setting.REMOTE_POLLING_FREQUENCY`.

        """

        local_frequency = settings_manager.get_value(Setting.LOCAL_POLLING_FREQUENCY)
        if _should_run(local_frequency, self.last_refreshed_local_state):
            # TODO: disable editing widgets while the refresh is working in order to avoid
            # potential mess up of the file system cache caused by the user mashing
            # the refresh button too quickly.
            self.toggle_editing_widgets(False)
            # lets check if we also need to update from remote, as that takes precedence
            if settings_manager.get_value(Setting.POLL_REMOTE):
                remote_frequency = settings_manager.get_value(
                    Setting.REMOTE_POLLING_FREQUENCY)
                if _should_run(remote_frequency, self.last_refreshed_remote_state):
                    self.update_remote_state()
                else:
                    self.update_local_state()
            else:
                self.update_local_state()
        else:
            pass  # nothing to do, move along

    def toggle_editing_widgets(self, enable: bool):
        for widget in self._editing_widgets:
            widget.setEnabled(enable)

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
                if ( not folder[1] and
                     not folder[2] ):
                    os.rmdir(folder[0])


        # remove empty Jobs folders
        jobs_path = os.path.join(base_data_directory, 'Jobs')
        folders = list(os.walk(jobs_path))[1:]
        clean(folders)

        # remove empty Datasets folders
        datasets_path = os.path.join(base_data_directory, 'outputs')
        folders = list(os.walk(datasets_path))[1:]
        clean(folders)

    def perform_single_update(self):
        self.update_remote_state()

    def update_remote_state(self):
        log("updating remote state...")
        job_manager.refresh_from_remote_state()
        self.last_refreshed_remote_state = dt.datetime.now(tz=dt.timezone.utc)

    def update_local_state(self):
        """Update the state of local datasets"""
        log("updating local state...")
        job_manager.refresh_local_state()
        self.last_refreshed_local_state = dt.datetime.now(tz=dt.timezone.utc)

    def refresh_after_job_modified(self, job: Job):
        self.refresh_after_cache_update()

    def filter_changed(self, filter_string: str):
        options = QtCore.QRegularExpression.NoPatternOption
        options |= QtCore.QRegularExpression.CaseInsensitiveOption
        regular_expression = QtCore.QRegularExpression(filter_string, options)
        self.proxy_model.setFilterRegularExpression(regular_expression)

    def sort_jobs(self, action: QtWidgets.QAction):
        sort_field: SortField = action.data()
        self.toolButton_sort.setDefaultAction(action)
        order = (
            QtCore.Qt.AscendingOrder if self.reverse_box.isChecked() else
            QtCore.Qt.DescendingOrder
        )

        self.proxy_model.current_sort_field = sort_field
        sort_field_index = list(SortField).index(sort_field)
        self.proxy_model.sort(sort_field_index, order)

    def setup_algorithms_tree(self):
        self.algorithms_tv.setStyleSheet(
            'QTreeView { selection-background-color: white; selection-color: black }'
        )
        # NOTE: mouse tracking is needed in order to use the `entered` signal, which
        # we need (check below)
        self.algorithms_tv.setMouseTracking(True)
        self.algorithms_tv.setWordWrap(True)  # add ... to wrap DisplayRole text... to have a real wrap need a custom widget
        model = algorithms_mvc.AlgorithmTreeModel(ALGORITHM_TREE)
        self.algorithms_tv.setModel(model)
        self.algorithms_tv_delegate = algorithms_mvc.AlgorithmItemDelegate(
            self.launch_algorithm_execution_dialogue,
            self.algorithms_tv
        )
        self.algorithms_tv.setItemDelegate(self.algorithms_tv_delegate)
        self.algorithms_tv.setEditTriggers(
            QtWidgets.QAbstractItemView.AllEditTriggers)
        self.algorithms_tv.entered.connect(self._manage_algorithm_tree_view)

    def launch_algorithm_execution_dialogue(
            self,
            algorithm: algorithm_models.Algorithm,
            run_mode: algorithm_models.AlgorithmRunMode
    ):
        algorithm_script = _get_script(algorithm, run_mode)
        dialog_class_path = algorithm_script.parametrization_dialogue
        dialog_class = load_object(dialog_class_path)
        dialog = dialog_class(self.iface, algorithm_script.script, parent=self)
        dialog.exec_()

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
                        previous_index)
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
                algorithm_models.AlgorithmGroup, algorithm_models.Algorithm]
            is_algorithm = (
                    current_item.item_type ==
                    algorithm_models.AlgorithmNodeType.Algorithm
            )

            if current_item is not None and is_algorithm:
                previous_index = self.algorithms_tv_delegate.current_index
                index_changed = index != previous_index
                if previous_index is not None:
                    previously_open = self.algorithms_tv.isPersistentEditorOpen(
                        previous_index)
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
        dialogue = DlgDownload(
            self.iface,
            KNOWN_SCRIPTS["download-data"],
            self
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
    dataset_auto_download = settings_manager.get_value(Setting.DOWNLOAD_RESULTS)
    if dataset_auto_download:
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
        algorithm: algorithm_models.Algorithm,
        run_mode: algorithm_models.AlgorithmRunMode
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
