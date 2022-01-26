"""Dialog for generating compound/multiscope reports."""
import typing
from pathlib import Path

from qgis.PyQt import uic
from qgis.PyQt.QtGui import QResizeEvent
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QTableView,
    QToolButton,
    QWidget,
)

from .jobs.models import Job
from .reports.template_manager import template_manager
from .reports.mvc import (
    JobSelectionItemDelegate,
    MultiscopeJobReportModel
)

from .utils import FileUtils


DlgGenerateReportUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgGenerateReport.ui")
)


class DlgGenerateReport(QDialog, DlgGenerateReportUi):
    browse_dir_tb: QToolButton
    buttonBox: QDialogButtonBox
    dataset_scope_tv: QTableView
    description_lbl: QLabel
    output_dir_le: QLineEdit
    template_cbo: QComboBox

    def __init__(self, parent: QWidget=None):
        super().__init__(parent)
        self.setupUi(self)

        self.browse_dir_tb.setIcon(FileUtils.get_icon('mActionFileOpen.svg'))
        self.template_cbo.currentIndexChanged.connect(
            self._on_template_changed
        )
        self._scope_job_model = MultiscopeJobReportModel()
        self.dataset_scope_tv.setModel(self._scope_job_model)
        self.dataset_scope_tv.setItemDelegateForColumn(
            1,
            JobSelectionItemDelegate(0)
        )

        self.load_templates()

        ok_btn = self.buttonBox.button(QDialogButtonBox.Ok)
        if ok_btn is not None:
            ok_btn.setText(self.tr('Generate'))

    def load_templates(self):
        # Load multi-scope templates to the combobox
        self.template_cbo.clear()
        self.template_cbo.addItem('')

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
            self._scope_job_model.load_scopes(
                config.template_info.item_scopes
            )

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