"""Classes for interfacing UI with report models."""
import os
import typing

from qgis.gui import QgisInterface
from qgis.core import Qgis
from qgis.PyQt.QtCore import (
    QAbstractItemModel,
    QCoreApplication,
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

from .generator import report_generator
from .template_manager import template_manager
from .utils import (
    job_has_report,
    job_has_results,
    build_report_name,
    build_template_name
)
from ..utils import FileUtils


class DatasetReportHandler:
    """
    Interface for functionality related to report generation and viewing
    as well as template editing for each dataset generated by the
    algorithms.
    """
    def __init__(self, rpt_btn: QPushButton, job: Job, iface: QgisInterface=None) -> None:
        self._rpt_btn = rpt_btn
        self._job = job
        self._iface = iface
        self._rpt_menu = QMenu()
        self._view_rpt_action = None
        self._open_template_action = None
        self._rpt_config = None
        self._rpt_task_ctx = None
        self._regenerate_report = False

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
            FileUtils.get_icon('view.svg'),
            self.tr('View report')
        )
        self._view_rpt_action.triggered.connect(self.view_report)

        self._open_template_action = self._rpt_menu.addAction(
            FileUtils.get_icon('layout.svg'),
            self.tr('Open template')
        )
        self._open_template_action.triggered.connect(self.open_designer)

        self._rpt_btn.setMenu(self._rpt_menu)

        # Check report configuration
        scope = self._job.script.name
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

        # Check if qpt should be included in the output
        if self._rpt_config.output_options.include_qpt:
            self._open_template_action.setEnabled(True)
        else:
            self._open_template_action.setEnabled(False)

        # Enable/disable report button based on job and results status
        rpt_status = self._check_job_report_status()
        self._rpt_btn.setEnabled(rpt_status)

        # For previously finished jobs but there is no report, submit the
        # job for report generation.
        if self._regenerate_report and \
                not report_generator.is_task_running(self.report_task_id):
            self.generate_report()

    def _check_job_report_status(self) -> bool:
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
    def task_context(self) -> ReportTaskContext:
        """
        Returns an instance of the report task context that has been used
        to generate the corresponding report. This is for jobs that have
        successfully finished with the results in the datasets folder,
        otherwise it will return None.
        """
        return self._rpt_task_ctx

    @property
    def report_task_id(self) -> str:
        """
        Returns the task_id for generating the report which, in this case,
        corresponds to the job id..
        """
        return str(self._job.id)

    def _push_refactor_message(self, title, msg):
        if self._iface is None:
            return

        msg_bar = self._iface.messageBar()
        msg_bar.pushWarning(title, msg)

    def view_report(self):
        # View report in the default pdf or image viewer.
        _, rpt_path = self._report_name_path()

        if not os.path.exists(rpt_path):
            self._push_refactor_message(
                self.tr('Invalid File'),
                self.tr('Report file does not exist.')
            )
            log(f'Report file \'{rpt_path}\' not found.', Qgis.Warning)
            return

        if not os.access(rpt_path, os.R_OK):
            self._push_refactor_message(
                self.tr('File Permission'),
                self.tr('Unable to open report file.')
            )
            log(
                f'Report file \'{rpt_path}\' cannot be opened.', Qgis.Warning
            )
            return

        rpt_path_url = QUrl(QUrl.fromLocalFile(rpt_path))
        QDesktopServices.openUrl(rpt_path_url)

    def _report_name_path(self) -> typing.Tuple[str, str]:
        rpt_name, rpt_path = build_report_name(
            self._job,
            self._rpt_config.output_options
        )

        return rpt_name, rpt_path

    def open_designer(self):
        # Open template in the QGIS layout designer.
        pass

    @classmethod
    def tr(cls, source):
        return QCoreApplication.translate(
            'DatasetReportHandler',
            source
        )

    def generate_report(self):
        # Generate output report and source template
        _, temp_path = build_template_name(self._job)
        _, rpt_path = self._report_name_path()

        # Create report task context for report generation.
        self._rpt_task_ctx = ReportTaskContext(
            self._rpt_config,
            (rpt_path, temp_path),
            [self._job]
        )
        report_generator.process_report_task(
            self._rpt_task_ctx
        )


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

