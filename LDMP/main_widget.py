import datetime as dt
import functools
import os
import re
import typing
from pathlib import Path

import qgis.core
import qgis.gui
from qgis.PyQt import QtCore, QtGui, QtWidgets, uic
from qgis.PyQt.QtNetwork import QNetworkAccessManager, QNetworkRequest
from te_schemas.algorithms import AlgorithmRunMode
from te_schemas.jobs import JobStatus

from .algorithms import models as algorithm_models
from .algorithms import mvc as algorithms_mvc
from .conf import (
    ALGORITHM_TREE,
    KNOWN_SCRIPTS,
    Setting,
    get_dock_title,
    settings_manager,
)
from .data_io import (
    DlgDataIOImportPopulation,
    DlgDataIOImportProd,
    DlgDataIOImportSOC,
    DlgDataIOLoadTE,
)
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

if typing.TYPE_CHECKING:
    from .news import NewsItem

DockWidgetTrendsEarthUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/WidgetMain.ui")
)


ICON_PATH = os.path.join(os.path.dirname(__file__), "icons")


class NetworkImageTextBrowser(QtWidgets.QTextBrowser):
    """QTextBrowser that can load images from remote URLs and auto-sizes to content."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._network_manager = QNetworkAccessManager(self)
        self._pending_images = {}
        self._loaded_images = {}  # Cache of loaded images
        self._original_html = ""
        # Remove scroll bars and make it act like a label
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum
        )

    def setHtml(self, html: str) -> None:
        """Set HTML and start loading any remote images."""
        self._original_html = html
        super().setHtml(html)
        self._load_remote_images(html)
        self._adjust_height()

    def _adjust_height(self) -> None:
        """Adjust widget height to fit document content."""
        doc = self.document()
        doc.setTextWidth(self.viewport().width())
        height = int(doc.size().height()) + 4  # Small padding
        self.setMinimumHeight(height)
        self.setMaximumHeight(height)

    def resizeEvent(self, event) -> None:
        """Re-adjust height when width changes."""
        super().resizeEvent(event)
        self._adjust_height()

    def loadResource(self, type: int, url: QtCore.QUrl) -> typing.Any:
        """Override to return cached images for remote URLs."""
        url_string = url.toString()
        if (
            type == QtGui.QTextDocument.ImageResource
            and url_string in self._loaded_images
        ):
            return QtGui.QPixmap.fromImage(self._loaded_images[url_string])
        return super().loadResource(type, url)

    def _load_remote_images(self, html: str) -> None:
        """Find and load remote images in the HTML."""
        img_pattern = r'<img[^>]+src=["\']([^"\']+)["\']'
        for match in re.finditer(img_pattern, html, re.IGNORECASE):
            url = match.group(1)
            if (
                url.startswith(("http://", "https://"))
                and url not in self._loaded_images
            ):
                self._fetch_image(url)

    def _fetch_image(self, url: str) -> None:
        """Fetch an image from a URL."""
        if url in self._pending_images:
            return

        request = QNetworkRequest(QtCore.QUrl(url))
        reply = self._network_manager.get(request)
        self._pending_images[url] = reply
        reply.finished.connect(lambda: self._on_image_loaded(url, reply))

    def _on_image_loaded(self, url: str, reply) -> None:
        """Handle completed image download."""
        if reply.error():
            log(f"Failed to load image {url}: {reply.errorString()}")
            self._pending_images.pop(url, None)
            reply.deleteLater()
            return

        data = reply.readAll()
        image = QtGui.QImage()
        if image.loadFromData(data):
            self._loaded_images[url] = image
            # Re-render HTML to show the image
            super(NetworkImageTextBrowser, self).setHtml(self._original_html)
            self._adjust_height()

        self._pending_images.pop(url, None)
        reply.deleteLater()


class UpdateWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self._killed = False

    def run(self):
        if not self._killed:
            self.work()
        self.finished.emit()

    def work(self):
        raise NotImplementedError

    def kill(self):
        """Signal the worker to stop at the next opportunity."""
        self._killed = True


class LocalPeriodicUpdateWorker(UpdateWorker):
    def __init__(self):
        super().__init__()

    def work(self):
        if not self._killed:
            job_manager.refresh_local_state()


class RemoteStateRefreshWorker(UpdateWorker):
    def __init__(self):
        super().__init__()

    def work(self):
        if not self._killed:
            job_manager.refresh_from_remote_state()


class MainWidget(QtWidgets.QDockWidget, DockWidgetTrendsEarthUi):
    _SUB_INDICATORS_TAB_PAGE: int = 0
    _DATASETS_TAB_PAGE: int = 1
    _NEWS_TAB_PAGE: int = 2

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
    # News tab widgets
    news_container_layout: QtWidgets.QVBoxLayout
    news_refresh_btn: QtWidgets.QPushButton

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
        self._pending_cache_refresh = False
        self.setupUi(self)

        # Initialize the news tab
        self._setup_news_tab()

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
        self._pending_remote_refresh = False  # queued refresh from button click

        # remove space before dataset item
        self.datasets_tv.setIndentation(0)
        self.datasets_tv.verticalScrollBar().setSingleStep(10)
        self.datasets_tv.setUniformRowHeights(True)
        # When setSortingEnabled(True) is set (from the UI file), Qt internally calls
        #  sort() repeatedly when. We'll sort programmatically via proxy_model.sort()
        # after setting the model.
        self.datasets_tv.setSortingEnabled(False)

        self.message_bar_sort_filter = None

        self.proxy_model = jobs_mvc.JobsSortFilterProxyModel(SortField.DATE)

        self.source_model = jobs_mvc.JobsModel(job_manager, jobs_list=[])

        # Use QueuedConnection for all job_manager signals that may be emitted
        # from background threads (LocalPeriodicUpdateWorker, RemoteStateRefreshWorker)
        # to ensure GUI updates always run on the main thread.
        job_manager.refreshed_local_state.connect(
            self.refresh_after_cache_update, QtCore.Qt.QueuedConnection
        )
        job_manager.refreshed_from_remote.connect(
            self.refresh_after_cache_update, QtCore.Qt.QueuedConnection
        )
        job_manager.downloaded_job_results.connect(
            self.refresh_after_cache_update, QtCore.Qt.QueuedConnection
        )
        job_manager.deleted_job.connect(
            self.refresh_after_cache_update, QtCore.Qt.QueuedConnection
        )
        job_manager.submitted_remote_job.connect(
            self.refresh_after_job_modified, QtCore.Qt.QueuedConnection
        )
        job_manager.processed_local_job.connect(
            self.refresh_after_job_modified, QtCore.Qt.QueuedConnection
        )
        job_manager.failed_local_job.connect(
            self.refresh_after_job_modified, QtCore.Qt.QueuedConnection
        )
        job_manager.imported_job.connect(
            self.refresh_after_job_modified, QtCore.Qt.QueuedConnection
        )
        job_manager.authentication_failed.connect(
            self._show_authentication_error, QtCore.Qt.QueuedConnection
        )

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
            self.setWindowTitle(get_dock_title(offline_mode=True))
        else:
            self.pushButton_download.setEnabled(True)
            self.setWindowTitle(get_dock_title(offline_mode=False))

        # --- Master filter group setup ---
        filters_enabled = settings_manager.get_value(Setting.FILTERS_ENABLED)
        if not filters_enabled:
            filters_enabled = False
        self.filter_group.setChecked(filters_enabled)
        self.filter_group.toggled.connect(self._filter_group_toggled)

        # --- Date filter setup ---
        date_filter_enabled = settings_manager.get_value(Setting.DATE_FILTER_ENABLED)
        if not date_filter_enabled:
            date_filter_enabled = False
        self.date_filter_chk.setChecked(date_filter_enabled)
        self._set_date_widgets_enabled(date_filter_enabled)

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
        else:
            # Default to current month range on first load
            today = QtCore.QDate.currentDate()
            start_of_month = QtCore.QDateTime(
                QtCore.QDate(today.year(), today.month(), 1), QtCore.QTime(0, 0, 0)
            )
            end_of_month = QtCore.QDateTime(
                QtCore.QDate(today.year(), today.month(), today.daysInMonth()),
                QtCore.QTime(23, 59, 59),
            )
            self.start_dte.setDateTime(start_of_month)
            self.end_dte.setDateTime(end_of_month)

        self.date_filter_chk.toggled.connect(self._date_filter_chk_toggled)
        self.start_dte.dateChanged.connect(lambda: self.date_filter_changed(False))
        self.end_dte.dateChanged.connect(lambda: self.date_filter_changed(False))

        # --- Status filter setup ---
        status_filter_enabled = settings_manager.get_value(
            Setting.STATUS_FILTER_ENABLED
        )
        if not status_filter_enabled:
            status_filter_enabled = False
        self.status_filter_chk.setChecked(status_filter_enabled)
        self.status_filter_cb.setEnabled(status_filter_enabled)
        self.status_filter_chk.toggled.connect(self._status_filter_chk_toggled)
        self.status_filter_cb.currentIndexChanged.connect(self.status_filter_changed)

        # --- Task type filter setup ---
        task_type_filter_enabled = settings_manager.get_value(
            Setting.TASK_TYPE_FILTER_ENABLED
        )
        if not task_type_filter_enabled:
            task_type_filter_enabled = False
        self.task_type_filter_chk.setChecked(task_type_filter_enabled)
        self.task_type_filter_cb.setEnabled(task_type_filter_enabled)
        self.task_type_filter_chk.toggled.connect(self._task_type_filter_chk_toggled)
        self.task_type_filter_cb.currentIndexChanged.connect(
            self.task_type_filter_changed
        )

    def _filter_group_toggled(self, value):
        """Master filter group checkbox toggled."""
        settings_manager.write_value(Setting.FILTERS_ENABLED, value)
        self._apply_all_filters()

    def _date_filter_chk_toggled(self, value):
        settings_manager.write_value(Setting.DATE_FILTER_ENABLED, value)
        self._set_date_widgets_enabled(value)
        self._apply_all_filters()

    def _set_date_widgets_enabled(self, enabled):
        self.start_dte.setEnabled(enabled)
        self.end_dte.setEnabled(enabled)
        self.label_13.setEnabled(enabled)
        self.label_14.setEnabled(enabled)

    def _status_filter_chk_toggled(self, value):
        settings_manager.write_value(Setting.STATUS_FILTER_ENABLED, value)
        self.status_filter_cb.setEnabled(value)
        self._apply_all_filters()

    def _task_type_filter_chk_toggled(self, value):
        settings_manager.write_value(Setting.TASK_TYPE_FILTER_ENABLED, value)
        self.task_type_filter_cb.setEnabled(value)
        self._apply_all_filters()

    def status_filter_changed(self, index):
        settings_manager.write_value(
            Setting.STATUS_FILTER_VALUE,
            self.status_filter_cb.currentData(),
        )
        self._apply_all_filters()

    def task_type_filter_changed(self, index):
        settings_manager.write_value(
            Setting.TASK_TYPE_FILTER_VALUE,
            self.task_type_filter_cb.currentData(),
        )
        self._apply_all_filters()

    def _apply_all_filters(self):
        """Apply or clear all three filters based on the master group and
        individual checkbox states."""
        if not self.proxy_model:
            return

        master_on = self.filter_group.isChecked()

        # Date filter - don't invalidate yet
        if master_on and self.date_filter_chk.isChecked():
            start_date = self.start_dte.dateTime()
            end_date = self.end_dte.dateTime()
        else:
            start_date = None
            end_date = None
        self.proxy_model.set_date_filter(start_date, end_date, invalidate=False)

        # Status filter - don't invalidate yet
        if master_on and self.status_filter_chk.isChecked():
            status_value = self.status_filter_cb.currentData()
            if status_value is not None:
                self.proxy_model.set_status_filter(
                    JobStatus(status_value), invalidate=False
                )
            else:
                self.proxy_model.set_status_filter(None, invalidate=False)
        else:
            self.proxy_model.set_status_filter(None, invalidate=False)

        # Task type filter - don't invalidate yet
        if master_on and self.task_type_filter_chk.isChecked():
            self.proxy_model.set_task_type_filter(
                self.task_type_filter_cb.currentData(), invalidate=False
            )
        else:
            self.proxy_model.set_task_type_filter(None, invalidate=False)

        # Invalidate ONCE after all filters are set
        self.proxy_model.invalidateFilter()

    def _apply_all_filters_no_invalidate(self):
        """Apply or clear all three filters WITHOUT triggering invalidation.

        Use this when you will set the source model afterward, which already
        triggers a filter pass. Avoids redundant filter operations.
        """
        if not self.proxy_model:
            return

        master_on = self.filter_group.isChecked()

        # Date filter - don't invalidate
        if master_on and self.date_filter_chk.isChecked():
            start_date = self.start_dte.dateTime()
            end_date = self.end_dte.dateTime()
        else:
            start_date = None
            end_date = None
        self.proxy_model.set_date_filter(start_date, end_date, invalidate=False)

        # Status filter - don't invalidate
        if master_on and self.status_filter_chk.isChecked():
            status_value = self.status_filter_cb.currentData()
            if status_value is not None:
                self.proxy_model.set_status_filter(
                    JobStatus(status_value), invalidate=False
                )
            else:
                self.proxy_model.set_status_filter(None, invalidate=False)
        else:
            self.proxy_model.set_status_filter(None, invalidate=False)

        # Task type filter - don't invalidate
        if master_on and self.task_type_filter_chk.isChecked():
            self.proxy_model.set_task_type_filter(
                self.task_type_filter_cb.currentData(), invalidate=False
            )
        else:
            self.proxy_model.set_task_type_filter(None, invalidate=False)

        # NOTE: No invalidateFilter() call - caller is responsible for triggering
        # the filter pass (e.g., by calling setSourceModel which does it automatically)

    def _populate_filter_dropdowns(self, jobs=None):
        """Populate the status and task type filter dropdowns from job data.

        This method has two modes:
        1. If `jobs` is provided: Extract data from the loaded Job objects
        2. If `jobs` is None/empty: Use SQLite cache queries (no unpickling)

        Preserves the previously selected value if it still exists in the
        updated list, to avoid resetting the user's filter on every refresh.
        """
        if jobs:
            # Mode 1: Extract from loaded jobs (existing behavior)
            statuses = sorted(
                {job.status for job in jobs},
                key=lambda s: s.value,
            )
            script_names = set()
            for job in jobs:
                if job.script is not None and job.script.name:
                    script_names.add(job.script.name)
            script_names = sorted(script_names)
        else:
            # Mode 2: Fast cache query - no Job unpickling needed
            # This is much faster for initial UI population
            try:
                metadata = job_manager.get_job_dropdown_metadata()
                statuses = sorted(
                    {JobStatus(m["job_status"]) for m in metadata if m["job_status"]},
                    key=lambda s: s.value,
                )
                script_names = sorted(
                    {m["script_name"] for m in metadata if m["script_name"]}
                )
            except Exception:
                # Fall back to empty if cache unavailable
                statuses = []
                script_names = []

        # --- Status dropdown ---
        prev_status = self.status_filter_cb.currentData()
        if prev_status is None:
            prev_status = settings_manager.get_value(Setting.STATUS_FILTER_VALUE)

        self.status_filter_cb.blockSignals(True)
        self.status_filter_cb.clear()
        restore_idx = 0
        for idx, status in enumerate(statuses):
            display = status.value
            if status == JobStatus.GENERATED_LOCALLY:
                display = "LOCAL"
            self.status_filter_cb.addItem(display, userData=status.value)
            if status.value == prev_status:
                restore_idx = idx
        self.status_filter_cb.setCurrentIndex(restore_idx)
        self.status_filter_cb.blockSignals(False)

        # --- Task type dropdown ---
        prev_task_type = self.task_type_filter_cb.currentData()
        if prev_task_type is None:
            prev_task_type = settings_manager.get_value(Setting.TASK_TYPE_FILTER_VALUE)

        self.task_type_filter_cb.blockSignals(True)
        self.task_type_filter_cb.clear()
        restore_idx = 0
        for idx, name in enumerate(script_names):
            self.task_type_filter_cb.addItem(name, userData=name)
            if name == prev_task_type:
                restore_idx = idx
        self.task_type_filter_cb.setCurrentIndex(restore_idx)
        self.task_type_filter_cb.blockSignals(False)

    def closeEvent(self, event):
        """Handle widget close event to properly cleanup background threads.

        This prevents access violations when QGIS closes while marshmallow
        schema operations are running in background threads.
        """
        # Stop the timer first to prevent new threads from starting
        if hasattr(self, "timer") and self.timer is not None:
            self.timer.stop()

        # Kill workers first to signal them to stop processing
        if self.pu_worker is not None:
            try:
                self.pu_worker.kill()
            except RuntimeError:
                pass

        if self.rs_worker is not None:
            try:
                self.rs_worker.kill()
            except RuntimeError:
                pass

        # Wait for local update thread to finish
        if self.pu_thread is not None:
            try:
                if self.pu_thread.isRunning():
                    self.pu_thread.quit()
                    # Wait with timeout to avoid hanging on close
                    if not self.pu_thread.wait(5000):  # 5 second timeout
                        log("Warning: Local update thread did not stop cleanly")
            except RuntimeError:
                # C++ object already deleted
                pass
            self.pu_thread = None
            self.pu_worker = None

        # Wait for remote update thread to finish
        if self.rs_thread is not None:
            try:
                if self.rs_thread.isRunning():
                    self.rs_thread.quit()
                    # Wait with timeout to avoid hanging on close
                    if not self.rs_thread.wait(5000):  # 5 second timeout
                        log("Warning: Remote update thread did not stop cleanly")
            except RuntimeError:
                # C++ object already deleted
                pass
            self.rs_thread = None
            self.rs_worker = None

        super().closeEvent(event)

    def _setup_news_tab(self) -> None:
        """Initialize the news tab with news widgets."""
        from .news import NewsClient

        # Create news widgets container (stores the QFrame widgets for each news item)
        self._news_widgets: typing.List[QtWidgets.QWidget] = []
        self._news_client = NewsClient(self)
        self._news_client.news_fetched.connect(self._display_news_items)
        self._news_fetch_in_progress = False

        # Connect refresh button
        self.news_refresh_btn.clicked.connect(lambda: self._refresh_news(force=True))

        # Schedule initial news fetch after startup (non-blocking)
        QtCore.QTimer.singleShot(2000, self._refresh_news)

    def _refresh_news(self, force: bool = False) -> None:
        """Refresh news items from the API and display in the news tab."""
        offline_mode = settings_manager.get_value(Setting.OFFLINE_MODE)
        if offline_mode:
            log("Skipping news fetch - offline mode enabled")
            return

        if self._news_fetch_in_progress:
            log("News fetch already in progress, skipping")
            return

        self._news_fetch_in_progress = True
        self._news_client.fetch_news(platform="qgis_plugin", force=force)

    def _display_news_items(self, news_items: typing.List["NewsItem"]) -> None:
        """Display news items in the news tab."""
        from .news import _is_news_dismissed

        self._news_fetch_in_progress = False

        # Clear existing news widgets
        while self.news_container_layout.count():
            item = self.news_container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._news_widgets.clear()

        # Filter out dismissed items
        active_items = [item for item in news_items if not _is_news_dismissed(item.id)]

        # Update tab title style based on whether there are news items
        self._update_news_tab_style(has_news=len(active_items) > 0)

        if not active_items:
            # Show "no news" message
            no_news_label = QtWidgets.QLabel(self.tr("No news items at this time."))
            no_news_label.setStyleSheet("color: gray; padding: 20px;")
            no_news_label.setAlignment(QtCore.Qt.AlignCenter)
            self.news_container_layout.addWidget(no_news_label)
            return

        # Create a widget for each news item
        for item in active_items:
            news_widget = self._create_news_item_widget(item)
            self.news_container_layout.addWidget(news_widget)
            self._news_widgets.append(news_widget)

    def _update_news_tab_style(self, has_news: bool) -> None:
        """Update the News tab title style to indicate unread news."""
        tab_bar = self.tabWidget.tabBar()
        news_tab_index = self._NEWS_TAB_PAGE

        # Get the current font and modify it
        font = tab_bar.font()
        font.setBold(has_news)
        tab_bar.setTabTextColor(
            news_tab_index, QtGui.QColor("#000000") if has_news else QtGui.QColor()
        )

        # Update tab text with indicator if there are news items
        base_text = "News"
        if has_news:
            self.tabWidget.setTabText(news_tab_index, f"● {base_text}")
        else:
            self.tabWidget.setTabText(news_tab_index, base_text)

    def _create_news_item_widget(self, item: "NewsItem") -> QtWidgets.QFrame:
        """Create a widget for displaying a single news item."""
        from .news import open_news_link

        # Style colors based on news type (bg_color, border_color, text_color)
        style_colors = {
            "announcement": ("#e3f2fd", "#2196f3", "#1565c0"),
            "warning": ("#fff3e0", "#ff9800", "#e65100"),
            "release": ("#e8f5e9", "#4caf50", "#2e7d32"),
            "tip": ("#f3e5f5", "#9c27b0", "#7b1fa2"),
            "maintenance": ("#eceff1", "#607d8b", "#455a64"),
        }
        bg_color, border_color, text_color = style_colors.get(
            item.news_type, style_colors["announcement"]
        )

        # Create frame
        frame = QtWidgets.QFrame()
        frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        frame.setStyleSheet(
            f"QFrame {{ background-color: {bg_color}; "
            f"border: 1px solid {border_color}; border-radius: 4px; }} "
            f"QFrame QLabel {{ border: none; background: transparent; }}"
        )

        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Type label row (small caps style)
        type_row = QtWidgets.QHBoxLayout()
        type_label = QtWidgets.QLabel(item.news_type.upper())
        type_label.setStyleSheet(
            f"color: {text_color}; font-size: 9px; font-weight: 600; "
            f"letter-spacing: 1px;"
        )
        type_row.addWidget(type_label)
        type_row.addStretch()

        # Dismiss button
        dismiss_btn = QtWidgets.QToolButton()
        dismiss_btn.setText("×")
        dismiss_btn.setToolTip("Dismiss this news item")
        dismiss_btn.setAutoRaise(True)
        dismiss_btn.setStyleSheet("font-size: 14px; color: #666;")
        dismiss_btn.clicked.connect(
            lambda checked, news_id=item.id, widget=frame: self._dismiss_news(
                news_id, widget
            )
        )
        type_row.addWidget(dismiss_btn)
        layout.addLayout(type_row)

        # Title
        title_label = QtWidgets.QLabel(f"<b>{item.title}</b>")
        title_label.setWordWrap(True)
        title_label.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse | QtCore.Qt.LinksAccessibleByMouse
        )
        layout.addWidget(title_label)

        # Message - use NetworkImageTextBrowser to support remote images in HTML
        html_content = item.message_html if item.message_html else item.message
        message_browser = NetworkImageTextBrowser()
        message_browser.setOpenExternalLinks(False)
        message_browser.setOpenLinks(False)
        message_browser.anchorClicked.connect(
            lambda url: open_news_link(url.toString())
        )
        message_browser.setFrameShape(QtWidgets.QFrame.NoFrame)
        message_browser.setStyleSheet("background: transparent; border: none;")
        message_browser.setHtml(html_content)
        layout.addWidget(message_browser)

        # Link if present
        if item.link_url:
            link_text = item.link_text or "Learn more"
            link_label = QtWidgets.QLabel(f'<a href="{item.link_url}">{link_text}</a>')
            link_label.setOpenExternalLinks(False)
            link_label.setTextInteractionFlags(
                QtCore.Qt.TextSelectableByMouse | QtCore.Qt.LinksAccessibleByMouse
            )
            link_label.linkActivated.connect(open_news_link)
            layout.addWidget(link_label)

        return frame

    def _dismiss_news(self, news_id: str, widget: QtWidgets.QWidget) -> None:
        """Dismiss a news item and remove its widget."""
        from .news import _add_dismissed_news_id

        _add_dismissed_news_id(news_id)
        widget.deleteLater()
        if widget in self._news_widgets:
            self._news_widgets.remove(widget)
        log(f"Dismissed news item {news_id}")

        # Show "no news" message if all items dismissed
        if not self._news_widgets:
            no_news_label = QtWidgets.QLabel(self.tr("No news items at this time."))
            no_news_label.setStyleSheet("color: gray; padding: 20px;")
            no_news_label.setAlignment(QtCore.Qt.AlignCenter)
            self.news_container_layout.addWidget(no_news_label)

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
        action_import_population_dataset = self.import_menu.addAction(
            self.tr("Import custom Population dataset...")
        )
        action_import_population_dataset.triggered.connect(
            self.import_population_dataset
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

        self.pushButton_load.setIcon(QtGui.QIcon(os.path.join(ICON_PATH, "globe.svg")))
        self.pushButton_load.clicked.connect(self.load_base_map)
        self.pushButton_refresh.clicked.connect(self.perform_single_update)

        # Connect search box filter once here (not in refresh_after_cache_update)
        # to avoid accumulating duplicate signal connections.
        self.lineEdit_search.valueChanged.connect(self.filter_changed)

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
            self.setWindowTitle(get_dock_title(offline_mode=True))
        else:
            self.pushButton_download.setEnabled(True)
            self.setWindowTitle(get_dock_title(offline_mode=False))

    def _show_authentication_error(self, error_message: str):
        """Display authentication error message to the user via the message bar.

        This slot is connected with Qt.QueuedConnection to ensure thread-safe
        GUI updates when signals are emitted from background worker threads.
        """
        self.iface.messageBar().pushCritical("Trends.Earth", error_message)

    def refresh_after_cache_update(self, *args):
        # Accept *args to handle signals with varying signatures:
        # - QgsProject.layersRemoved emits layer_ids (list of str)
        # - job_manager.downloaded_job_results emits Job
        # - job_manager.deleted_job emits Job
        # - job_manager.refreshed_local_state emits nothing
        # - job_manager.refreshed_from_remote emits nothing
        # Using *args avoids access violation crashes on Windows caused by
        # signal/slot signature mismatches

        # If the scheduler is paused (e.g. a modal dialog is open), defer
        # the refresh until resume_scheduler() is called.  This prevents
        # the model reset from destroying editor widgets that are parents
        # of open dialogs.
        if self.scheduler_paused:
            self._pending_cache_refresh = True
            return

        # Close any open persistent editor BEFORE changing the model
        # to avoid access violations with dangling QModelIndex pointers
        current_dataset_index = self.datasets_tv_delegate.current_index

        if current_dataset_index is not None and current_dataset_index.isValid():
            try:
                has_open_editor = self.datasets_tv.isPersistentEditorOpen(
                    current_dataset_index
                )

                if has_open_editor:
                    self.datasets_tv.closePersistentEditor(current_dataset_index)
            except (RuntimeError, AttributeError):
                # Handle cases where the index or editor is no longer valid
                pass
            finally:
                # Always reset the current index
                self.datasets_tv_delegate.current_index = None

        # Defer downloads to after model rebuild is complete, to avoid
        # mutating job states while the model is being constructed
        QtCore.QTimer.singleShot(0, maybe_download_finished_results)
        # Note: We intentionally do NOT invalidate the delegate's pixmap/size caches
        # here. The cache key includes (job.id, job.status, job.progress) so unchanged
        # jobs will naturally hit cache, while changed jobs get new entries. This
        # dramatically improves refresh performance by avoiding expensive widget
        # recreation for unchanged jobs.
        #
        # Get relevant_jobs once and reuse for both model and filter dropdowns
        # to avoid locking the mutex twice.
        relevant_jobs = job_manager.relevant_jobs

        # Pre-sort in Python (fast) so we can disable Qt sorting entirely
        relevant_jobs = sorted(
            relevant_jobs,
            key=lambda j: j.start_date if j.start_date else dt.datetime.min,
            reverse=True,  # Descending (newest first)
        )

        # Set ALL filter properties BEFORE updating the model data.
        # This ensures there's only ONE filter pass when set_jobs() triggers
        # beginResetModel/endResetModel.

        # Only set source model on first load
        is_first_load = self.proxy_model.sourceModel() is None

        # Only reset type filter and search text on first load - preserve user's
        # filter choices during periodic refreshes
        if is_first_load:
            self.proxy_model.set_type_filter(TypeFilter.ALL)
            self.lineEdit_search.setText("")
            # Set the "All" menu action as checked initially
            action = self.filter_menu.actions()[0]
            action.setChecked(True)

        # Populate status and task type dropdowns from actual job data
        self._populate_filter_dropdowns(relevant_jobs)

        # Set all filter properties WITHOUT triggering invalidation
        self._apply_all_filters_no_invalidate()

        if is_first_load:
            # Set filter regexp only on first load - it persists and doesn't need resetting
            # Note: setFilterRegExp calls invalidateFilter internally, which is harmless
            # when there's no data yet (source model is empty).
            self.proxy_model.setFilterRegExp(
                QtCore.QRegExp("*", QtCore.Qt.CaseInsensitive, QtCore.QRegExp.Wildcard)
            )
            self.proxy_model.setSourceModel(self.source_model)

        # Data is pre-sorted in Python. Use sort(-1) to DISABLE Qt sorting.
        self.proxy_model.sort(-1)

        # NOW update the model data - this triggers ONE filter pass with all
        # filter properties already set correctly
        self.source_model.set_jobs(relevant_jobs)

        # Only call setModel once (on first load). Subsequent refreshes just
        # update the source model above, and Qt automatically updates the view.
        if self.datasets_tv.model() is None:
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

        # Ensure any previous thread is properly cleaned up before creating a new one
        # This prevents access violations when marshmallow schema operations are
        # interrupted by premature thread destruction
        if self.pu_thread is not None:
            try:
                if self.pu_thread.isRunning():
                    # Thread is still running, skip this update cycle
                    return
                # Wait for thread to fully finish cleanup
                self.pu_thread.wait()
            except RuntimeError:
                # C++ object already deleted, safe to proceed
                pass
            self.pu_thread = None
            self.pu_worker = None

        def _update_local_refreshing_state():
            self.refreshing_local_state = True

        self.pu_thread = QtCore.QThread()
        self.pu_worker = LocalPeriodicUpdateWorker()
        self.pu_worker.moveToThread(self.pu_thread)
        self.pu_thread.started.connect(self.pu_worker.run)
        self.pu_thread.started.connect(_update_local_refreshing_state)
        self.pu_worker.finished.connect(self.pu_thread.quit)
        self.pu_thread.finished.connect(self._on_finish_updating_local_state)

        if settings_manager.get_value(Setting.DEBUG):
            log("updating local state...")

        self.cache_refresh_about_to_begin.emit()
        self.refreshing_local_state = True
        self.pu_thread.start()

    def _on_finish_updating_local_state(self):
        # Slot raised when job_manager has finished refreshing the local state.
        self.last_refreshed_local_state = dt.datetime.now(tz=dt.timezone.utc)
        self.refreshing_local_state = False
        # Clear references to allow garbage collection - must be done here
        # before any deleteLater would execute to avoid accessing deleted objects
        self.pu_thread = None
        self.pu_worker = None

    def _run_remote_update_worker(self):
        # Create thread worker for refreshing remote state.

        # Ensure any previous thread is properly cleaned up before creating a new one
        # This prevents access violations when marshmallow schema operations are
        # interrupted by premature thread destruction
        if self.rs_thread is not None:
            try:
                if self.rs_thread.isRunning():
                    # Thread is still running — queue a follow-up refresh so the
                    # request (e.g. from the Refresh button) is not silently lost.
                    self._pending_remote_refresh = True
                    log(
                        "Remote refresh already in progress — "
                        "queuing a follow-up refresh"
                    )
                    return
                # Wait for thread to fully finish cleanup
                self.rs_thread.wait()
            except RuntimeError:
                # C++ object already deleted, safe to proceed
                pass
            self.rs_thread = None
            self.rs_worker = None

        self._pending_remote_refresh = False
        self.rs_thread = QtCore.QThread()
        self.rs_worker = RemoteStateRefreshWorker()
        self.rs_worker.moveToThread(self.rs_thread)
        self.rs_thread.started.connect(self.rs_worker.run)
        self.rs_worker.finished.connect(self.rs_thread.quit)
        self.rs_thread.finished.connect(self._on_finish_updating_remote_state)

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
        # Clear references to allow garbage collection - must be done here
        # before any deleteLater would execute to avoid accessing deleted objects
        self.rs_thread = None
        self.rs_worker = None

        # If a refresh was requested while the previous one was still running
        # (e.g. user clicked the Refresh button), kick off a new cycle now.
        if self._pending_remote_refresh:
            self._pending_remote_refresh = False
            log("Executing queued remote refresh")
            # Use a short delay so the current finished-signal chain can
            # complete before re-entering _run_remote_update_worker.
            QtCore.QTimer.singleShot(0, self._run_remote_update_worker)

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
        self._run_remote_update_worker()

    def set_remote_refresh_running(self, val: bool = True):
        self.remote_refresh_running = val

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
        if self._pending_cache_refresh:
            self._pending_cache_refresh = False
            self.refresh_after_cache_update()

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

                if previous_index is not None and previous_index.isValid():
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

                if previous_index is not None and previous_index.isValid():
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

    def import_population_dataset(self, action: QtWidgets.QAction):
        log("import_population_dataset called")
        dialogue = DlgDataIOImportPopulation(self)
        dialogue.exec_()


# Module-level guard to prevent reentrant calls to maybe_download_finished_results.
# This can happen because download_available_results() spins a nested QEventLoop
# on the main thread (for each file download), and during that nested loop Qt
# delivers queued signals — including another refresh_after_cache_update which
# dispatches a new QTimer.singleShot(0, maybe_download_finished_results).
# A QMutex with tryLock() is used instead of a plain bool so that reentrant
# calls from nested event loops are correctly rejected.
_downloading_finished_results_mutex = QtCore.QMutex()


def maybe_download_finished_results():
    if not _downloading_finished_results_mutex.tryLock():
        return

    try:
        offline_mode = settings_manager.get_value(Setting.OFFLINE_MODE)
        dataset_auto_download = settings_manager.get_value(Setting.DOWNLOAD_RESULTS)

        if not offline_mode and dataset_auto_download:
            if len(job_manager.known_jobs[JobStatus.FINISHED]) > 0:
                log("downloading results...")
                # Download one job at a time to avoid blocking the UI
                has_more = job_manager.download_one_available_result()
                if has_more:
                    # Schedule next download after a short delay to allow UI updates
                    QtCore.QTimer.singleShot(100, maybe_download_finished_results)
    finally:
        _downloading_finished_results_mutex.unlock()


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
