import functools
import os
import typing
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from qgis.core import QgsProject
from qgis.PyQt import QtCore, QtGui, QtWidgets, uic
from qgis.utils import iface
from te_schemas.jobs import JobStatus
from te_schemas.results import Band as JobBand
from te_schemas.results import RasterResults, TimeSeriesTableResult

from .. import layers, metadata, metadata_dialog, utils
from ..conf import Setting, settings_manager
from ..data_io import DlgDataIOAddLayersToMap
from ..datasets_dialog import DatasetDetailsDialogue
from ..plot import DlgPlotTimeries
from ..reports.mvc import DatasetReportHandler
from ..select_dataset import DlgSelectDataset
from ..utils import FileUtils
from . import manager
from .models import Job, SortField, TypeFilter

if TYPE_CHECKING:
    from ..main_widget import MainWidget

WidgetDatasetItemUi, _ = uic.loadUiType(
    str(Path(__file__).parents[1] / "gui/WidgetDatasetItem.ui")
)

ICON_PATH = os.path.join(os.path.dirname(__file__), os.path.pardir, "icons")


class JobsModel(QtCore.QAbstractItemModel):
    _relevant_jobs: typing.List[Job]

    def __init__(self, job_manager: manager.JobManager, parent=None):
        super().__init__(parent)
        self._relevant_jobs = job_manager.relevant_jobs

    def index(
        self, row: int, column: int, parent: QtCore.QModelIndex
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
        role: QtCore.Qt.ItemDataRole = QtCore.Qt.DisplayRole,
    ) -> typing.Optional[Job]:
        result = None

        if index.isValid():
            job = index.internalPointer()

            if role == QtCore.Qt.DisplayRole or role == QtCore.Qt.ItemDataRole:
                result = job

        return result

    def flags(
        self, index: QtCore.QModelIndex = QtCore.QModelIndex()
    ) -> QtCore.Qt.ItemFlags:
        if index.isValid():
            flags = super().flags(index)
            result = QtCore.Qt.ItemIsEditable | flags
        else:
            result = QtCore.Qt.NoItemFlags

        return result


class JobsSortFilterProxyModel(QtCore.QSortFilterProxyModel):
    current_sort_field: typing.Optional[SortField]
    type_filter: TypeFilter

    def __init__(self, current_sort_field: SortField, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_sort_field = current_sort_field
        self.start_date = None
        self.end_date = None
        self.type_filter = TypeFilter.ALL  # Initialize with default value

    def set_date_filter(self, start_date, end_date):
        self.start_date = start_date
        self.end_date = end_date
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QtCore.QModelIndex):
        jobs_model = self.sourceModel()
        index = jobs_model.index(source_row, 0, source_parent)
        job: Job = jobs_model.data(index)
        reg_exp = self.filterRegExp()

        matches_filter = (
            reg_exp.exactMatch(job.visible_name)
            or reg_exp.exactMatch(job.local_context.area_of_interest_name)
            or reg_exp.exactMatch(str(job.id))
        )

        matches_type = True
        if self.type_filter == TypeFilter.RASTER:
            matches_type = not job.is_vector()
        elif self.type_filter == TypeFilter.VECTOR:
            matches_type = job.is_vector()

        # Date filtering logic
        matches_date = True
        # Only apply date filtering if we have all required dates
        # Use try-except to handle any unexpected None values or type issues defensively
        if self.start_date and self.end_date:
            try:
                if (
                    job.start_date is not None
                    and job.end_date is not None
                    and hasattr(job.start_date, "strftime")
                    and hasattr(job.end_date, "strftime")
                ):
                    job_start_date = QtCore.QDateTime.fromString(
                        job.start_date.strftime("%Y-%m-%d %H:%M:%S"),
                        "yyyy-MM-dd HH:mm:ss",
                    )
                    job_end_date = QtCore.QDateTime.fromString(
                        job.end_date.strftime("%Y-%m-%d %H:%M:%S"),
                        "yyyy-MM-dd HH:mm:ss",
                    )
                    matches_date = (
                        job_start_date >= self.start_date
                        and job_end_date <= self.end_date
                    )
            except (AttributeError, ValueError, TypeError):
                # If any error occurs during date conversion, don't filter by date
                # This handles cases where job dates might be None or invalid
                pass

        return matches_filter and matches_type and matches_date

    def lessThan(self, left: QtCore.QModelIndex, right: QtCore.QModelIndex) -> bool:
        model = self.sourceModel()
        left_job: Job = model.data(left)
        right_job: Job = model.data(right)
        to_sort = (left_job, right_job)

        if self.current_sort_field == SortField.DATE:
            result = sorted(to_sort, key=lambda j: j.start_date)[0] == left_job
        else:
            raise NotImplementedError

        return result

    def set_type_filter(self, filter_type):
        self.type_filter = filter_type


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
        index: QtCore.QModelIndex,
    ):
        # get item and manipulate painter basing on idetm data
        proxy_model: QtCore.QSortFilterProxyModel = index.model()
        source_index = proxy_model.mapToSource(index)
        source_model = source_index.model()
        item = source_model.data(source_index, QtCore.Qt.DisplayRole)

        # if a Dataset => show custom widget

        if isinstance(item, Job):
            # get default widget used to edit data
            editor_widget = self.createEditor(self.parent, option, index)
            editor_widget.setGeometry(option.rect)
            pixmap = editor_widget.grab()
            del editor_widget
            painter.drawPixmap(option.rect.x(), option.rect.y(), pixmap)
        else:
            super().paint(painter, option, index)

    def sizeHint(
        self, option: QtWidgets.QStyleOptionViewItem, index: QtCore.QModelIndex
    ):
        proxy_model: QtCore.QSortFilterProxyModel = index.model()
        source_index = proxy_model.mapToSource(index)
        source_model = source_index.model()
        item = source_model.data(source_index, QtCore.Qt.DisplayRole)

        if isinstance(item, Job):
            # parent set to none otherwise remain painted in the widget
            widget = self.createEditor(None, option, index)
            size = widget.size()
            del widget

            return size

        return super().sizeHint(option, index)

    def createEditor(
        self,
        parent: QtWidgets.QWidget,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ):
        # get item and manipulate painter basing on item data
        proxy_model: QtCore.QSortFilterProxyModel = index.model()
        source_index = proxy_model.mapToSource(index)
        source_model = source_index.model()
        item = source_model.data(source_index, QtCore.Qt.DisplayRole)

        # item = model.data(index, QtCore.Qt.DisplayRole)

        if isinstance(item, Job):
            return DatasetEditorWidget(item, self.main_dock, parent=parent)
        else:
            return super().createEditor(parent, option, index)

    def updateEditorGeometry(
        self,
        editor: QtWidgets.QWidget,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ):
        editor.setGeometry(option.rect)


class DatasetEditorWidget(QtWidgets.QWidget, WidgetDatasetItemUi):
    job: Job
    main_dock: "MainWidget"

    add_to_canvas_pb: QtWidgets.QToolButton
    notes_la: QtWidgets.QLabel
    delete_tb: QtWidgets.QToolButton
    download_tb: QtWidgets.QToolButton
    name_la: QtWidgets.QLabel
    open_details_tb: QtWidgets.QToolButton
    metadata_pb: QtWidgets.QPushButton
    view_logs_tb: QtWidgets.QToolButton
    plot_tb: QtWidgets.QToolButton
    load_tb: QtWidgets.QToolButton
    edit_tb: QtWidgets.QToolButton
    report_pb: QtWidgets.QPushButton
    status_frame: QtWidgets.QFrame
    status_label: QtWidgets.QLabel

    def __init__(self, job: Job, main_dock: "MainWidget", parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.job = job
        self.main_dock = main_dock
        # allows hiding background prerendered pixmap
        self.setAutoFillBackground(True)

        # Flag to track if widget is being destroyed
        self._is_being_destroyed = False

        self.load_data_menu_setup()
        self.add_to_canvas_pb.setMenu(self.load_data_menu)

        self.metadata_menu = QtWidgets.QMenu()
        self.metadata_menu.aboutToShow.connect(self.prepare_metadata_menu)
        self.metadata_pb.setMenu(self.metadata_menu)

        self.open_details_tb.clicked.connect(self.show_details)
        self.view_logs_tb.clicked.connect(self.view_execution_logs)
        self.delete_tb.clicked.connect(self.delete_dataset)
        self.load_tb.clicked.connect(self.load_layer)

        self.edit_tb.clicked.connect(self.edit_layer)

        self.delete_tb.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, "mActionDeleteSelected.svg"))
        )
        self.open_details_tb.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, "mActionPropertiesWidget.svg"))
        )
        self.view_logs_tb.setIcon(QtGui.QIcon(os.path.join(ICON_PATH, "document.svg")))
        self.metadata_pb.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, "editmetadata.svg"))
        )
        self.add_to_canvas_pb.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, "mActionAddRasterLayer.svg"))
        )
        self.download_tb.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, "cloud-download.svg"))
        )
        self.edit_tb.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, "mActionToggleEditing.svg"))
        )
        self.load_tb.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, "mActionAddOgrLayer.svg"))
        )

        self.plot_tb.setIcon(FileUtils.get_icon("chart.svg"))
        self.plot_tb.clicked.connect(self.show_time_series_plot)
        self.plot_tb.setEnabled(False)
        self.plot_tb.hide()

        self.report_pb.setIcon(FileUtils.get_icon("report.svg"))

        # Initialize report handler with error handling
        try:
            self._report_handler = DatasetReportHandler(
                self.report_pb, self.job, self.main_dock.iface
            )
        except Exception as e:
            # If report handler fails to initialize, create a dummy one to prevent crashes
            print(f"Warning: Failed to initialize report handler: {e}")
            self._report_handler = None
        # self.add_to_canvas_pb.setFixedSize(self.view_logs_tb.size())
        # self.add_to_canvas_pb.setMinimumSize(self.view_logs_tb.size())

        if self.job.is_vector():
            self.edit_tb.setEnabled(False)
            layers = QgsProject.instance().mapLayers()
            for lyr in layers.values():
                # Ensure this vector layer is added to the map
                if lyr.source().split("|")[0] == str(job.results.vector.uri.uri):
                    self.edit_tb.setEnabled(True)
                    break

        self.name_la.setText(self.job.visible_name)

        area_name = self.job.local_context.area_of_interest_name

        # Handle missing start_date gracefully with defensive checks
        if self.job.start_date is not None:
            try:
                if hasattr(self.job.start_date, "strftime"):
                    job_start_date = utils.utc_to_local(self.job.start_date).strftime(
                        "%Y-%m-%d %H:%M"
                    )
                else:
                    job_start_date = "Date unknown"
            except (AttributeError, ValueError, TypeError):
                job_start_date = "Date unknown"
        else:
            job_start_date = "Date unknown"

        if area_name:
            notes_text = f"{area_name} ({job_start_date})"
        else:
            notes_text = f"{job_start_date}"
        self.notes_la.setText(notes_text)

        # Setup status bar
        status_text, status_color = self._get_status_display_info(self.job.status)
        self._setup_status_bar(status_text, status_color)

        self.download_tb.setEnabled(False)

        self.delete_tb.setEnabled(True)

        offline_mode = settings_manager.get_value(Setting.OFFLINE_MODE)

        # Reset download button to default state before status handling
        self.download_tb.setStyleSheet("")  # Clear any previous styling
        self.download_tb.setText("")  # Clear any previous text

        # Set up the status bar display
        status_text, status_color = self._get_status_display_info(self.job.status)
        self._setup_status_bar(status_text, status_color)

        # Handle specific status behavior
        if self.job.status in [JobStatus.RUNNING, JobStatus.PENDING, JobStatus.READY]:
            # Jobs that aren't completed yet - disable main actions
            self._disable_main_action_buttons()
            if self.job.status in [JobStatus.RUNNING, JobStatus.PENDING]:
                self._handle_time_series_result()
        elif self.job.status == JobStatus.FINISHED:
            result_auto_download = settings_manager.get_value(Setting.DOWNLOAD_RESULTS)

            if result_auto_download:
                self.download_tb.hide()
            else:
                self.download_tb.show()

                if offline_mode:
                    # Disable the download button so that the user cannot download
                    self.download_tb.setEnabled(False)
                else:
                    self.download_tb.setEnabled(True)

                self.download_tb.clicked.connect(
                    functools.partial(manager.job_manager.download_job_results, job)
                )

            # Hide buttons that don't make sense for finished but not downloaded jobs
            self.add_to_canvas_pb.setEnabled(False)
            self.metadata_pb.setEnabled(
                False
            )  # Disable metadata for finished jobs (remote URLs cause errors)
            self.load_tb.hide()  # Hide the load vector button
            self.edit_tb.hide()  # Hide the edit button

            if isinstance(self.job.results, TimeSeriesTableResult):
                self.plot_tb.setEnabled(True)
                self.plot_tb.show()
                self.download_tb.hide()
                self.add_to_canvas_pb.hide()
                self.metadata_pb.hide()
                # Show logs button for remote jobs (finished jobs that aren't local)
                if self.job.status != JobStatus.GENERATED_LOCALLY:
                    self.view_logs_tb.show()
                else:
                    self.view_logs_tb.hide()
        elif self.job.status in (JobStatus.DOWNLOADED, JobStatus.GENERATED_LOCALLY):
            self.download_tb.hide()
            self.add_to_canvas_pb.setEnabled(self.has_loadable_result())
            self.metadata_pb.setEnabled(self.has_loadable_result())
        elif self.job.status in [
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.EXPIRED,
        ]:
            self._hide_buttons_failed_cancelled()
        else:
            # For unknown statuses, disable main actions
            self.download_tb.hide()
            self._disable_main_action_buttons()

        # Apply job type specific visibility for completed jobs only
        if self.job.status in (JobStatus.DOWNLOADED, JobStatus.GENERATED_LOCALLY):
            if self.job.is_vector():
                self.download_tb.hide()
                self.add_to_canvas_pb.hide()
                self.open_details_tb.hide()
            elif self.job.is_file():
                # File jobs need most buttons hidden
                self.download_tb.hide()
                self.add_to_canvas_pb.hide()
                self.metadata_pb.hide()
                self.load_tb.hide()
                self.edit_tb.hide()
            else:
                # Raster jobs - hide vector-specific buttons
                self.load_tb.hide()
                self.edit_tb.hide()

        # Control logs button visibility - only show for non-locally generated jobs
        if self.job.status == JobStatus.GENERATED_LOCALLY:
            self.view_logs_tb.hide()
        else:
            self.view_logs_tb.show()

        # Set up dual loading menu for appropriate jobs
        # Only show dual menu for downloaded/local jobs that have both vector and raster results
        if (
            self.job.status in (JobStatus.DOWNLOADED, JobStatus.GENERATED_LOCALLY)
            and self._has_both_vector_and_raster_results()
        ):
            self.load_vector_menu_setup()
            self.load_tb.setMenu(self.load_vector_menu)

        # Initialize dataset report handler
        if self._report_handler:
            try:
                self._report_handler.init()
            except Exception as e:
                print(f"Warning: Failed to initialize report handler: {e}")
                self._report_handler = None

    def _has_both_vector_and_raster_results(self):
        """Check if this job has both vector and raster results available."""
        # Only show dual menu for jobs that are actually downloaded/available locally
        if self.job.status not in (JobStatus.DOWNLOADED, JobStatus.GENERATED_LOCALLY):
            return False

        if not (hasattr(self.job, "results") and self.job.results):
            return False

        # Check for vector results with actual accessible URI
        has_vector = (
            hasattr(self.job.results, "vector")
            and self.job.results.vector
            and hasattr(self.job.results.vector, "uri")
            and self.job.results.vector.uri
        )

        # Check for raster results (can be in urls or rasters)
        has_raster = (hasattr(self.job.results, "urls") and self.job.results.urls) or (
            hasattr(self.job.results, "rasters") and self.job.results.rasters
        )

        # Only return true if we have both types AND they're actually accessible
        if has_vector and has_raster:
            # Additional check: make sure the vector URI actually points to a file
            # (not just a placeholder or remote URL)
            try:
                vector_uri = str(self.job.results.vector.uri.uri)
                # If it's a local file path or accessible resource, show dual menu
                if vector_uri and not vector_uri.startswith("http"):
                    return True
            except (AttributeError, TypeError):
                pass

        return False

    def _disable_main_action_buttons(self):
        """Helper method to disable main action buttons for jobs that can't be used."""
        self.add_to_canvas_pb.setEnabled(False)
        self.metadata_pb.setEnabled(False)
        self.load_tb.hide()
        self.edit_tb.hide()

    def _hide_all_action_buttons(self):
        """Helper method to hide all action buttons for failed/cancelled jobs."""
        self.add_to_canvas_pb.setEnabled(False)
        self.add_to_canvas_pb.hide()
        self.metadata_pb.setEnabled(False)
        self.metadata_pb.hide()
        self.load_tb.hide()
        self.edit_tb.hide()
        self.report_pb.hide()
        self.download_tb.hide()

    def has_loadable_result(self):
        result = False

        if self.job.results is not None:
            if self.job.results.uri and (
                manager.is_gdal_vsi_path(self.job.results.uri.uri)
                or (
                    self.job.results.uri.uri.suffix in [".vrt", ".tif"]
                    and self.job.results.uri.uri.exists()
                )
            ):
                result = True

        return result

    def show_details(self):
        self.main_dock.pause_scheduler()
        DatasetDetailsDialogue(self.job, parent=iface.mainWindow()).exec_()
        self.main_dock.resume_scheduler()

    def show_metadata(self, file_path):
        self.main_dock.pause_scheduler()
        ds_metadata = metadata.read_qmd(file_path)
        dlg = metadata_dialog.DlgDatasetMetadata(self)
        dlg.set_metadata(ds_metadata)
        dlg.exec_()
        ds_metadata = dlg.get_metadata()
        metadata.save_qmd(file_path, ds_metadata)
        self.main_dock.resume_scheduler()

    def view_execution_logs(self):
        """Open the execution logs dialog as a non-blocking dialog."""
        from ..dialog_manager import dialog_manager
        from ..execution_logs_dialog import DlgExecutionLogs

        # Create unique dialog ID for this job
        dialog_id = f"logs_{str(self.job.id)}"

        # Check if dialog already exists and is visible
        existing_dialog = dialog_manager.get_dialog(dialog_id)
        if existing_dialog and not existing_dialog.isHidden():
            # Bring existing dialog to front
            existing_dialog.raise_()
            existing_dialog.activateWindow()
            return

        # Create and show the dialog as non-blocking
        # Use None as parent to make it a top-level window
        self.logs_dialog = DlgExecutionLogs(self.job, parent=None)
        self.logs_dialog.show()
        self.logs_dialog.raise_()
        self.logs_dialog.activateWindow()

    def load_data_menu_setup(self):
        self.load_data_menu = QtWidgets.QMenu()
        action_add_default_data_to_map = self.load_data_menu.addAction(
            self.tr("Add default layers from this dataset to map")
        )
        action_add_default_data_to_map.triggered.connect(self.load_dataset)
        action_choose_layers_to_add_to_map = self.load_data_menu.addAction(
            self.tr("Select specific layers from this dataset to add to map...")
        )
        action_choose_layers_to_add_to_map.triggered.connect(
            self.load_dataset_choose_layers
        )

    def load_dataset(self):
        manager.job_manager.display_default_job_results(self.job)

    def delete_dataset(self):
        self.main_dock.pause_scheduler()
        utils.delete_dataset(self.job)
        self.main_dock.resume_scheduler()

    def load_dataset_choose_layers(self):
        self.main_dock.pause_scheduler()
        dialogue = DlgDataIOAddLayersToMap(self, self.job)
        dialogue.exec_()
        self.main_dock.resume_scheduler()

    def load_layer(self):
        manager.job_manager.display_error_recode_layer(self.job)
        self.edit_tb.setEnabled(True)

    def show_time_series_plot(self):
        """Show the time series plot dialog as a non-blocking, persistent dialog."""
        from ..dialog_manager import dialog_manager

        table = self.job.results.table
        if len(table) == 0:
            self.main_dock.iface.messageBar().pushMessage(
                self.tr("Time series table is empty"), level=1, duration=5
            )
            return

        # Create unique dialog ID for this job's timeseries
        dialog_id = f"timeseries_{str(self.job.id)}"

        # Check if dialog already exists and is visible
        existing_dialog = dialog_manager.get_dialog(dialog_id)
        if existing_dialog and not existing_dialog.isHidden():
            # Bring existing dialog to front
            existing_dialog.raise_()
            existing_dialog.activateWindow()
            return

        data = [x for x in table if x["name"] == "mean"][0]
        base_title = self.tr("Time Series")
        if self.job.task_name:
            task_name = self.job.task_name
        else:
            task_name = ""

        # Create dialog as top-level window with job_id for dialog manager
        dlg_plot = DlgPlotTimeries(parent=None, job_id=self.job.id)
        self.set_widget_title(dlg_plot, base_title)
        labels = {
            "title": task_name,
            "bottom": self.tr("Time"),
            "left": [self.tr("Integrated NDVI"), self.tr("NDVI x 10000")],
        }
        dlg_plot.plot_data(data["time"], data["y"], labels)

        # Show as non-blocking dialog
        dlg_plot.show()
        dlg_plot.raise_()
        dlg_plot.activateWindow()

        # Store reference to prevent garbage collection
        self.timeseries_dialog = dlg_plot

    def _setup_status_bar(self, status_text: str, color: str):
        """Set up the colored status bar with status text."""
        # Set the status frame background color
        self.status_frame.setStyleSheet(f"""
            QFrame#status_frame {{
                background-color: {color};
                border: none;
            }}
        """)

        # Set the status label text and styling
        self.status_label.setText(status_text)
        self.status_label.setStyleSheet("""
            QLabel#status_label {
                color: white;
                border: none;
                border-radius: 0px;
                font-weight: bold;
                font-size: 12pt;
                padding: 1px;
                background-color: transparent;
            }
        """)

        # Create a custom rotated text approach
        # We'll override the paintEvent to draw rotated text
        self._setup_rotated_label(status_text)

    def _setup_rotated_label(self, status_text: str):
        """Set up the status label with rotated text."""

        # Create a custom paint event for the status label
        def paintEvent(event):
            painter = QtGui.QPainter(self.status_label)

            # Enable high-quality text rendering
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            painter.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
            painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
            painter.setRenderHint(QtGui.QPainter.HighQualityAntialiasing, True)

            # Get the label's rectangle
            rect = self.status_label.rect()

            # Set up the font and color with better settings
            font = QtGui.QFont("Arial", 8)  # Use specific font and size
            font.setBold(True)
            font.setHintingPreference(QtGui.QFont.PreferFullHinting)
            painter.setFont(font)

            # Use a proper QPen for better text rendering
            pen = QtGui.QPen(QtGui.QColor("white"))
            pen.setWidth(1)
            painter.setPen(pen)

            # Save the current transformation
            painter.save()

            # Get text metrics for proper positioning
            font_metrics = painter.fontMetrics()
            text_width = font_metrics.horizontalAdvance(status_text)
            text_height = font_metrics.height()

            # Move to center and rotate
            center = rect.center()
            painter.translate(center.x(), center.y())
            painter.rotate(-90)  # 90 degrees counterclockwise

            # Draw text centered at origin
            text_x = -text_width // 2
            text_y = text_height // 4  # Adjust for baseline

            painter.drawText(text_x, text_y, status_text)

            # Restore transformation
            painter.restore()
            painter.end()

        # Override the paintEvent of the status_label
        self.status_label.paintEvent = paintEvent

        # Clear the label text since we're drawing it manually
        self.status_label.setText("")

    def _get_status_display_info(self, job_status: JobStatus):
        """Get the display text and color for a job status."""
        status_mapping = {
            JobStatus.RUNNING: ("RUNNING", "#2196F3"),
            JobStatus.PENDING: ("PENDING", "#9C27B0"),
            JobStatus.READY: ("READY", "#9C27B0"),
            JobStatus.FINISHED: ("FINISHED", "#4CAF50"),
            JobStatus.DOWNLOADED: ("DOWNLOADED", "#8F5D00"),
            JobStatus.GENERATED_LOCALLY: ("LOCAL", "#CC942C"),
            JobStatus.FAILED: ("FAILED", "#EC2121"),
            JobStatus.CANCELLED: ("CANCELLED", "#E2810A"),
            JobStatus.EXPIRED: ("EXPIRED", "#727272"),
        }

        return status_mapping.get(job_status, ("UNKNOWN", "#4E4E4E"))

    def _handle_time_series_result(self):
        """Helper method to handle TimeSeriesTableResult specific UI changes."""
        if isinstance(self.job.results, TimeSeriesTableResult):
            self.plot_tb.show()
            self.add_to_canvas_pb.hide()
            self.metadata_pb.hide()
            # Show logs button for remote jobs only
            if self.job.status != JobStatus.GENERATED_LOCALLY:
                self.view_logs_tb.show()
            else:
                self.view_logs_tb.hide()

    def _hide_buttons_failed_cancelled(self):
        """Helper method to hide buttons on FAILED/CANCELLED jobs."""
        self._hide_all_action_buttons()

    def set_widget_title(
        self, widget: QtWidgets.QWidget, base_title: typing.Optional[str] = None
    ):
        # Convenient function for setting the title of a widget.
        if base_title is None:
            base_title = widget.windowTitle()

        if self.job.task_name:
            task_name = self.job.task_name
        else:
            task_name = ""

        if not task_name:
            win_title = base_title
        else:
            win_title = f"{base_title} - {task_name}"

        widget.setWindowTitle(win_title)

    def edit_layer(self):
        if not self.has_connected_data():
            self.main_dock.pause_scheduler()
            dlg = DlgSelectDataset(self, validate_all=True)
            self.set_widget_title(dlg)
            if dlg.exec_() == QtWidgets.QDialog.Accepted:
                prod = dlg.prod_band()
                lc = dlg.lc_band()
                soil = dlg.soil_band()
                sdg = dlg.sdg_band()

                if prod:
                    self.job.params["prod"] = {
                        "path": str(prod.path),
                        "band": prod.band_index,
                        "band_name": prod.band_info.name,
                        "uuid": str(prod.job.id),
                    }

                if lc:
                    self.job.params["lc"] = {
                        "path": str(lc.path),
                        "band": lc.band_index,
                        "band_name": lc.band_info.name,
                        "uuid": str(lc.job.id),
                    }

                if soil:
                    self.job.params["soil"] = {
                        "path": str(soil.path),
                        "band": soil.band_index,
                        "band_name": soil.band_info.name,
                        "uuid": str(soil.job.id),
                    }
                if sdg:
                    self.job.params["sdg"] = {
                        "path": str(sdg.path),
                        "band": sdg.band_index,
                        "band_name": sdg.band_info.name,
                        "uuid": str(sdg.job.id),
                    }

                manager.job_manager.write_job_metadata_file(self.job)
                manager.job_manager.display_error_recode_layer(self.job)

                band_datas = [
                    {
                        "path": str(prod.path.as_posix()),
                        "name": prod.band_info.name,
                        "out_name": "land_productivity",
                        "index": prod.band_index,
                    },
                    {
                        "path": str(lc.path.as_posix()),
                        "name": lc.band_info.name,
                        "out_name": "land_cover",
                        "index": lc.band_index,
                    },
                    {
                        "path": str(soil.path.as_posix()),
                        "name": soil.band_info.name,
                        "out_name": "soil_organic_carbon",
                        "index": soil.band_index,
                    },
                    {
                        "path": str(sdg.path.as_posix()),
                        "name": sdg.band_info.name,
                        "out_name": "sdg",
                        "index": sdg.band_index,
                    },
                ]
                layers.set_default_stats_value(
                    str(self.job.results.vector.uri.uri), band_datas
                )

                manager.job_manager.edit_error_recode_layer(self.job)
                self.main_dock.resume_scheduler()
        else:
            manager.job_manager.display_error_recode_layer(self.job)
            manager.job_manager.edit_error_recode_layer(self.job)

    def has_connected_data(self):
        has_prod = True if "prod" in self.job.params else False
        has_lc = True if "lc" in self.job.params else False
        has_soil = True if "soil" in self.job.params else False
        has_sdg = True if "sdg" in self.job.params else False

        return has_prod and has_lc and has_soil and has_sdg

    def prepare_metadata_menu(self):
        self.metadata_menu.clear()

        file_path = (
            os.path.splitext(manager.job_manager.get_job_file_path(self.job))[0]
            + ".qmd"
        )
        action = self.metadata_menu.addAction(self.tr("Dataset metadata"))
        action.triggered.connect(lambda _, x=file_path: self.show_metadata(x))
        self.metadata_menu.addSeparator()

        if self.job.results is not None and isinstance(self.job.results, RasterResults):
            for raster in self.job.results.rasters.values():
                file_path = os.path.splitext(raster.uri.uri)[0] + ".qmd"
                action = self.metadata_menu.addAction(
                    self.tr("{} metadata").format(os.path.split(raster.uri.uri)[1])
                )
                action.triggered.connect(lambda _, x=file_path: self.show_metadata(x))

    @property
    def report_handler(self):
        """
        Returns handler with helper methods for generating and viewing
        reports. Returns None if widget is being destroyed.
        """
        if not self.is_widget_valid():
            return None

        try:
            return self._report_handler
        except RuntimeError:
            # Widget or report handler has been deleted
            return None

    def load_vector_menu_setup(self):
        self.load_vector_menu = QtWidgets.QMenu()
        action_add_vector_to_map = self.load_vector_menu.addAction(
            self.tr("Add vector layer to map")
        )
        action_add_vector_to_map.triggered.connect(self.load_layer)
        action_add_rasters_to_map = self.load_vector_menu.addAction(
            self.tr("Add raster layers to map")
        )
        action_add_rasters_to_map.triggered.connect(self.load_rasters_layers)

    def load_rasters_layers(self):
        jobs = manager.job_manager._known_downloaded_jobs.copy()
        self._load_raster(jobs, "soil")
        self._load_raster(jobs, "lc")
        self._load_raster(jobs, "prod")
        self._load_raster(jobs, "sdg")

    def _load_raster(self, jobs, name):
        if name in self.job.params:
            data = self.job.params[name]
            job = (
                jobs[uuid.UUID(data["uuid"])]
                if uuid.UUID(data["uuid"]) in jobs
                else None
            )
            if job:
                band = job.results.get_bands()[data["band"] - 1]
                layers.add_layer(
                    str(data["path"]), int(data["band"]), JobBand.Schema().dump(band)
                )

    def closeEvent(self, event):
        """Handle widget cleanup when being closed/destroyed."""
        self._is_being_destroyed = True

        # Clean up report handler to prevent accessing deleted widgets
        if hasattr(self, "_report_handler") and self._report_handler:
            try:
                # Clear the button reference in the report handler to prevent access to deleted widget
                self._report_handler._rpt_btn = None
            except (RuntimeError, AttributeError):
                # Widget may already be deleted, that's ok
                pass

        super().closeEvent(event)

    def is_widget_valid(self):
        """Check if this widget and its UI elements are still valid."""
        if self._is_being_destroyed:
            return False

        try:
            # Try to access a basic property to see if widget is still valid
            _ = self.isVisible()
            return True
        except RuntimeError:
            # Widget has been deleted
            return False
