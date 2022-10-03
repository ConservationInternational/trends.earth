"""Dialog for generating compound/multiscope reports."""

import typing
from pathlib import Path

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QFileInfo
from qgis.PyQt.QtGui import QResizeEvent
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QTableView,
    QToolButton,
    QWidget,
)

from qgis.core import Qgis
from qgis.gui import QgsMessageBar

from .conf import Setting, settings_manager
from .jobs.models import Job
from .reports.generator import report_generator_manager
from .reports.models import ReportTaskContext
from .reports.template_manager import template_manager
from .reports.mvc import JobSelectionItemDelegate, MultiscopeJobReportModel

from .utils import FileUtils


DlgGenerateReportUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgGenerateReport.ui")
)


class DlgGenerateReport(QDialog, DlgGenerateReportUi):
    base_filename_le: QLineEdit
    browse_dir_tb: QToolButton
    buttonBox: QDialogButtonBox
    dataset_scope_tv: QTableView
    description_lbl: QLabel
    msg_bar: QgsMessageBar
    output_dir_le: QLineEdit
    template_cbo: QComboBox

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setupUi(self)

        # Placeholder text
        self.output_dir_le.setPlaceholderText(
            self.tr("Base file name for report output files")
        )

        self.browse_dir_tb.setIcon(FileUtils.get_icon("mActionFileOpen.svg"))
        self.browse_dir_tb.clicked.connect(self.on_select_output_dir)
        self.template_cbo.currentIndexChanged.connect(self._on_template_changed)
        self._scope_job_model = MultiscopeJobReportModel()
        self.dataset_scope_tv.setModel(self._scope_job_model)
        self.dataset_scope_tv.setItemDelegateForColumn(1, JobSelectionItemDelegate(0))

        self.load_templates()

        ok_btn = self.buttonBox.button(QDialogButtonBox.Ok)
        if ok_btn is not None:
            ok_btn.setText(self.tr("Generate"))
        self.buttonBox.accepted.connect(self.generate)

        self._rpt_tasK_ctx = None

    def load_templates(self):
        # Load multi-scope templates to the combobox
        self.template_cbo.clear()

        configs = template_manager.multi_scope_configs()
        for c in configs:
            temp_name = c.template_info.name
            self.template_cbo.addItem(temp_name, c)

    def _on_template_changed(self, idx):
        # Update template description and scopes in the table view
        self.description_lbl.clear()

        if idx == -1:
            return

        self._scope_job_model.clear_data()

        config = self.template_cbo.itemData(idx)
        if config is not None:
            self.description_lbl.setText(config.template_info.description)
            self._scope_job_model.load_scopes(config.template_info.item_scopes)

        self._persist_editor()

    def _persist_editor(self):
        # Always show the combobox for selecting the datasets
        for r in range(self._scope_job_model.rowCount()):
            idx = self._scope_job_model.index(r, 1)
            if idx.isValid():
                self.dataset_scope_tv.openPersistentEditor(idx)

    def scope_job_mapping(self) -> typing.Dict[str, Job]:
        """
        Returns a mapping of scope name and corresponding job as specified
        by the user.
        """
        return self._scope_job_model.scope_job_mapping

    def resizeEvent(self, event: QResizeEvent):
        # Adjust column width
        width = event.size().width()
        self.dataset_scope_tv.setColumnWidth(0, int(width * 0.35))

    def on_select_output_dir(self):
        """
        Slot raised to select output directory.
        """
        # Point to an initially selected directory if specified
        init_dir = self.output_dir_le.text()
        if not init_dir:
            init_dir = template_manager.default_output_path

        output_dir = QFileDialog.getExistingDirectory(
            self,
            self.tr("Select Report Output Directory"),
            init_dir,
            options=QFileDialog.DontResolveSymlinks | QFileDialog.ShowDirsOnly,
        )

        if output_dir:
            self.output_dir_le.setText(output_dir)
            self.output_dir_le.setToolTip(output_dir)

    def validate(self) -> bool:
        # Validate user options.
        status = True
        title = self.tr("Validation")
        level = Qgis.Warning
        duration = 5

        # Check template
        if not self.template_cbo.currentText():
            msg = self.tr("No template selected.")
            self.msg_bar.pushMessage(title, msg, level, duration)
            status = False

        # Check model
        model_status, msgs = self._validate_model()
        if not model_status:
            for msg in msgs:
                self.msg_bar.pushMessage(title, msg, level, duration)
            status = False

        # Check output directory
        if not self.output_dir_le.text():
            msg = self.tr("No output directory specified.")
            self.msg_bar.pushMessage(title, msg, level, duration)
            status = False

        return status

    def _validate_model(self) -> typing.Tuple[bool, list]:
        # Check if user has specified datasets for all scopes
        status = True
        msgs = []
        for r in range(self._scope_job_model.rowCount()):
            scope_name = self._scope_job_model.item(r, 0).text()
            idx = self._scope_job_model.index(r, 1)
            job = self._scope_job_model.data(idx, Qt.EditRole)
            if job is None:
                if status:
                    status = False
                tr_msg = self.tr("dataset not specified.")
                msgs.append(f"{scope_name} {tr_msg}")

        return status, msgs

    def generate(self):
        """
        Create a report task context object for submission to the report
        generator.
        """
        if not self.validate():
            return

        sel_config = self.template_cbo.itemData(self.template_cbo.currentIndex())
        jobs = self._scope_job_model.scope_job_mapping.values()
        report_output_dir = self.output_dir_le.text()

        rpt_task_ctx = ReportTaskContext(sel_config, jobs, report_output_dir)

        report_generator_manager.process_report_task(rpt_task_ctx)

        self.accept()
