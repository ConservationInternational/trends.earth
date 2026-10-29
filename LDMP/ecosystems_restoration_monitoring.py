"""
/***************************************************************************
 LDMP - A QGIS plugin
 This plugin supports monitoring and reporting of land degradation to the UNCCD
 and in support of the SDG Land Degradation Neutrality (LDN) target.
                              -------------------
        begin                : 2017-05-23
        git sha              : $Format:%H$
        copyright            : (C) 2017 by Conservation International
        email                : trends.earth@conservation.org
 ***************************************************************************/
"""

from pathlib import Path

import qgis.gui
from qgis.PyQt import QtWidgets, uic
from te_schemas.algorithms import ExecutionScript

from . import calculate
from .jobs.manager import job_manager

DlgEcosystemReportingRestorationProgressUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgEcosystemReportingRestorationProgress.ui")
)


class DlgEcosystemReportingRestorationProgress(
    calculate.DlgCalculateBase, DlgEcosystemReportingRestorationProgressUi
):
    LOCAL_SCRIPT_NAME = "ecosystem-restoration-progress-local"

    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        script: ExecutionScript,
        parent: QtWidgets.QWidget = None,
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)
        self._finish_initialization()

    def _setup_alg_help(self):
        self.alg_help.setHtml(
            self.tr(
                "<h3>Reporting Restoration Progress</h3>"
                "<p>Generates a restoration progress report for the selected "
                "project, country, or custom area of interest. The report "
                "compares the reporting target, the reported progress, and the "
                "spatially supported area for the GEF-8 Ecosystem Restoration "
                "Integrated Program (ERIP) core spatial indicators:</p>"
                "<ul>"
                "<li><b>Indicator 1.</b> Terrestrial protected areas under "
                "improved management.</li>"
                "<li><b>Indicator 3.</b> Land and ecosystems under restoration "
                "(degraded agricultural lands, forest and forest land, natural "
                "grasslands and woodlands, wetlands).</li>"
                "<li><b>Indicator 4.</b> Landscapes under improved "
                "practices.</li>"
                "</ul>"
                "<p>Each indicator is summarized with its sub-indicator "
                "breakdown, satellite monitoring evidence, and the remaining "
                "gap to target.</p>"
            )
        )

    def btn_calculate(self):
        ret = super().btn_calculate()
        if not ret:
            return

        self.close()

        job_params = {
            "task_name": self.execution_name_le.text(),
            "task_notes": self.task_notes.toPlainText(),
        }
        job_manager.submit_local_job_as_qgstask(
            job_params, self.LOCAL_SCRIPT_NAME, self.aoi
        )
