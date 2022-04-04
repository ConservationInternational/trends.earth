"""Classes for interfacing UI with report models."""
import os
import typing

from qgis.gui import QgisInterface
from qgis.core import Qgis
from qgis.PyQt.QtCore import (
    QAbstractItemModel,
    QCoreApplication,
    QFileInfo,
    QModelIndex,
    Qt,
    QUrl
)
from qgis.PyQt.QtGui import (
    QDesktopServices,
    QStandardItem,
    QStandardItemModel
)
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QMenu,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget
)

from te_schemas.jobs import JobStatus

from ..jobs.manager import job_manager
from ..jobs.models import Job
from ..logger import log
from .models import (
    ReportConfiguration,
    ItemScopeMapping,
    ReportTaskContext
)

from .generator import report_generator_manager
from .template_manager import template_manager
from .utils import (
    job_has_report,
    job_has_results,
    job_report_directory
)
from ..utils import (
    FileUtils,
    open_qgis_project
)


class DatasetReportHandler:
    """
    Interface for functionality related to report generation and viewing
    as well as template editing for each dataset generated by the
    algorithms.
    """
    def __init__(
            self,
            rpt_btn: QPushButton,
            job: Job,
            iface: QgisInterface=None
    ) -> None:
        self._rpt_btn = rpt_btn
        self._job = job
        self._iface = iface
        self._rpt_menu = QMenu()
        self._view_rpt_action = None
        self._open_layouts_action = None
        self._rpt_config = None
        self._rpt_task_ctx = None
        self._regenerate_report = False

        # Connect signal for report task completion
        report_generator_manager.task_completed.connect(
            self.on_task_completed
        )

    @property
    def report_button(self) -> QPushButton:
        return self._rpt_btn

    @property
    def job(self) -> Job:
        return self._job

    @property
    def report_menu(self) -> QMenu:
        return self._rpt_menu

    def init(self) -> None:
        """Creates sub-menus and set state based on job status."""
        self._view_rpt_action = self._rpt_menu.addAction(
            FileUtils.get_icon('mActionFileOpen.svg'),
            self.tr('Open report directory')
        )
        self._view_rpt_action.setToolTip(
            self.tr('Open directory containing reports')
        )
        self._view_rpt_action.triggered.connect(self.open_report_directory)

        self._open_layouts_action = self._rpt_menu.addAction(
            FileUtils.get_icon('layout.svg'),
            self.tr('Open layouts...')
        )
        self._open_layouts_action.setToolTip(
            self.tr('Open report layouts in QGIS')
        )
        self._open_layouts_action.triggered.connect(self.open_designer)

        self._rpt_btn.setMenu(self._rpt_menu)

        # Check report configuration
        if hasattr(self._job.script, 'name'):
            scope = self._job.script.name
        else:
            # Vector layers won't have a script type
            # 
            # TODO: Need to add an alternate field to determine scope so reports
            # can be processed on vector layers
            return
        single_scope_configs = template_manager.single_scope_configs()
        configs = template_manager.configs_by_scope_name(
            scope,
            single_scope_configs
        )

        if len(configs) == 0:
            self._rpt_btn.setVisible(False)
            return
        else:
            self._rpt_config = configs[0]
            self._rpt_task_ctx = ReportTaskContext(
                self._rpt_config,
                [self._job]
            )

        self.update_report_status()

        # For previously finished jobs but there is no report, submit the
        # job for report generation.
        self.generate_report()

    def update_report_status(self) -> bool:
        # Enable/disable report button based on job and results status.
        rpt_status = self.check_job_report_status()
        self._rpt_btn.setEnabled(rpt_status)

        return rpt_status

    def check_job_report_status(self) -> bool:
        # Check job status, assert datasets are available and no report has
        # been generated yet.
        if not self._job.status in (
                JobStatus.DOWNLOADED,
                JobStatus.GENERATED_LOCALLY
        ):
            return False

        if not job_has_results(self._job):
            return False

        else:
            if not job_has_report(
                    self._job,
                    self._rpt_config.output_options
            ):
                self._regenerate_report = True
                return False

        return True

    @property
    def report_config(self) -> ReportConfiguration:
        """
        Returns the active report configuration based on the scope
        defined, if any, in the templates file.
        """
        return self._rpt_config

    @property
    def report_task_context(self) -> ReportTaskContext:
        """
        Contains context information required for producing a job's report.
        """
        return self._rpt_task_ctx

    def _push_refactor_message(self, title, msg):
        if self._iface is None:
            return

        msg_bar = self._iface.messageBar()
        msg_bar.pushWarning(title, msg)

    def open_report_directory(self):
        # Open directory containing the job reports.
        rpt_dir = job_report_directory(self._job)

        if not os.path.exists(rpt_dir):
            self._push_refactor_message(
                self.tr('Invalid File'),
                self.tr('Report output directory does not exist.')
            )
            log(f'Report file \'{rpt_dir}\' not found.', Qgis.Warning)
            return

        rpt_path_url = QUrl(QUrl.fromLocalFile(rpt_dir))
        QDesktopServices.openUrl(rpt_path_url)

    def open_designer(self):
        # Open project which contains a macro to show layout manager window.
        rpt_dir = job_report_directory(self._job)

        if not os.path.exists(rpt_dir):
            self._push_refactor_message(
                self.tr('Invalid File'),
                self.tr('Report output directory does not exist.')
            )
            log(f'Report file \'{rpt_dir}\' not found.', Qgis.Warning)
            return

        proj_path = FileUtils.project_path_from_report_task(
            self._rpt_task_ctx,
            rpt_dir,
        )

        # Check if the QGIS project file exists
        if not os.path.exists(proj_path):
            self._push_refactor_message(
                self.tr('Invalid File'),
                self.tr('Project file does not exist.')
            )
            log(f'Project file \'{proj_path}\' not found.', Qgis.Warning)
            return

        if not os.access(proj_path, os.R_OK):
            self._push_refactor_message(
                self.tr('File Read Permission'),
                self.tr('Unable to open report file.')
            )
            log(
                f'Project file \'{proj_path}\' cannot be opened.',
                Qgis.Warning
            )
            return

        status = open_qgis_project(proj_path)
        if not status:
            self._push_refactor_message(
                self.tr('Open Layouts'),
                self.tr('Unable to open the QGIS project file.')
            )

    @classmethod
    def tr(cls, source):
        return QCoreApplication.translate(
            'DatasetReportHandler',
            source
        )

    def generate_report(self) -> bool:
        """
        Generates output reports and corresponding QGIS project. Checks
        prerequisites (job finished, no prior reports and no previous
        submission still running).
        Returns True if a report task is submitted, else False if at least
        one of the prerequisites has not been met.
        """
        self.check_job_report_status()
        rpt_task_running = report_generator_manager.is_task_running(
            self._rpt_task_ctx
        )
        if self._regenerate_report and not rpt_task_running:
            report_generator_manager.process_report_task(
                self._rpt_task_ctx
            )
            return True

        return False

    def on_task_completed(self, context_id: str):
        """
        Slot raised when a report task has been completed. This is used to
        enable the status button if the task was successful.
        """
        if self._rpt_task_ctx is None:
            return

        if self._rpt_task_ctx.id() == context_id:
            self.update_report_status()


class MultiscopeJobReportModel(QStandardItemModel):
    """
    For displaying item scope - job pairing in the dialog for
    generating multiscope reports.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setColumnCount(2)
        self.setHorizontalHeaderLabels([
            self.tr('Scope Name'),
            self.tr('Source Dataset')
        ])

    def load_scopes(self, scopes: typing.List[ItemScopeMapping]):
        # Load scope definitions to the collection
        self.clear_data()
        for sc in scopes:
            scope_item = QStandardItem(sc.name)
            scope_item.setToolTip(sc.name)
            self.appendRow([scope_item, QStandardItem()])

        # Sort by scope name
        self.sort(0)

    def clear_data(self):
        # Removes rows and resets scope collection
        self.removeRows(0, self.rowCount())

    @property
    def scope_job_mapping(self) -> typing.Dict[str, Job]:
        """
        Returns a mapping of scope name and corresponding job as paired
        by the user.
        """
        sj_mapping = dict()

        for r in range(self.rowCount()):
            scope_name = self.item(r, 0).text()
            idx = self.index(r, 1)
            job = self.data(idx, Qt.EditRole)
            if job is not None:
                sj_mapping[scope_name] = job

        return sj_mapping

    def flags(self, index: QModelIndex):
        col = index.column()
        if col == 1:
            return Qt.ItemIsEnabled | Qt.ItemIsEditable | Qt.ItemIsSelectable

        return Qt.ItemIsEnabled | Qt.ItemIsSelectable


class JobSelectionItemDelegate(QStyledItemDelegate):
    """
    Delegate for selecting finished jobs matching a specific algorithm.
    """
    def __init__(self, scope_column_index: int, **kwargs):
        super().__init__(**kwargs)
        # Model index to fetch algorithm/scope name
        self._scope_col_idx = scope_column_index

    @property
    def scope_column_index(self) -> int:
        return self._scope_col_idx

    @classmethod
    def jobs_by_scope_name(cls, name: str) -> typing.List[Job]:
        # Returns a list of downloaded jobs matching the given scope name.
        jobs = job_manager.relevant_jobs
        return [j for j in jobs if j.status in
                (JobStatus.DOWNLOADED, JobStatus.GENERATED_LOCALLY)
                and j.script.name ==name
                ]

    def createEditor(
            self,
            parent: QWidget,
            option: QStyleOptionViewItem,
            idx: QModelIndex
    ) -> QComboBox:
        job_combo = QComboBox(parent)

        # Add a list of completed jobs
        if idx.isValid():
            model = idx.model()
            scope_item = model.item(idx.row(), self._scope_col_idx)
            if scope_item is not None:
                scope_name = scope_item.text()
                jobs = self.jobs_by_scope_name(scope_name)
                job_combo.addItem('')
                for j in jobs:
                    job_combo.addItem(j.visible_name, j)

                job_combo.currentIndexChanged.connect(self._on_job_changed)
                self._on_combo_updated(job_combo)

        return job_combo

    def setEditorData(self, combo: QComboBox, idx: QModelIndex):
        job = idx.model().data(idx, Qt.EditRole)
        if job is None:
            return

        job_idx = combo.findText(job.visible_name)
        if job_idx != -1:
            combo.setCurrentIndex(job_idx)

    def setModelData(
            self,
            combo: QComboBox,
            model: QAbstractItemModel,
            idx: QModelIndex
    ):
        job = combo.itemData(combo.currentIndex())
        if job is not None:
            model.setData(idx, job, Qt.EditRole)

    def _on_job_changed(self, idx: int):
        # Commit job to the model
        job_combo = self.sender()
        if job_combo is not None:
            self._on_combo_updated(job_combo)

    def _on_combo_updated(self, cbo: QComboBox):
        # Update cell tooltip and commit data
        cbo.setToolTip(cbo.currentText())
        self.commitData.emit(cbo)

    def updateEditorGeometry(
            self,
            combo: QComboBox,
            option: QStyleOptionViewItem,
            idx: QModelIndex
    ):
        combo.setGeometry(option.rect)

