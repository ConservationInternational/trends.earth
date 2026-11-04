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

import csv
from pathlib import Path

import qgis.gui
from qgis.core import Qgis, QgsMapLayerProxyModel, QgsVectorLayer
from qgis.PyQt import QtCore, QtWidgets, uic
from te_schemas.algorithms import ExecutionScript

from . import calculate
from .jobs.manager import job_manager
from .reports.ecosystem_restoration.report import (
    CSV_DELIMITER,
    GEF_CP_ID,
    REQUIRED_DATA_COLUMNS,
)
from .reports.ecosystem_restoration.spatial import REQUIRED_SPATIAL_FIELDS

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
        # Only polygon layers, Qgis.LayerFilter since QGIS 3.34
        polygon_filter = (
            getattr(getattr(Qgis, "LayerFilter", None), "PolygonLayer", None)
            or QgsMapLayerProxyModel.PolygonLayer
        )
        self.spatial_layer_cb.setFilters(polygon_filter)

        # Reporting period, by default from the start of last year to today
        today = QtCore.QDate.currentDate()
        self.baseline_date_de.setDate(QtCore.QDate(today.year() - 1, 1, 1))
        self.latest_monitoring_date_de.setDate(today)

        # Child projects of the CSV, searched by any part of their GEF_CP_ID
        completer = self.child_project_cb.completer()
        completer.setFilterMode(QtCore.Qt.MatchContains)
        completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.child_project_rb.toggled.connect(self.child_project_cb.setEnabled)
        self.data_csv_fw.fileChanged.connect(self._load_child_projects)
        self._finish_initialization()

    def _load_child_projects(self, path: str):
        """List the GEF_CP_ID of the CSV in the child project input."""
        child_projects = set()
        if path and Path(path).is_file():
            try:
                with open(path, newline="", encoding="utf-8") as csv_file:
                    for row in csv.DictReader(csv_file, delimiter=CSV_DELIMITER):
                        child_projects.add((row.get(GEF_CP_ID) or "").strip())
            except (OSError, UnicodeDecodeError, csv.Error):
                pass
        child_projects.discard("")
        self.child_project_cb.clear()
        self.child_project_cb.addItems(sorted(child_projects))

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
                "<h4>Report data (CSV)</h4>"
                "<p>The CSV file has one row per sub-indicator, columns "
                "separated by semicolons (;), and a header row with these "
                "columns:</p>"
                "<ul>"
                "<li><b>indicator</b>: full name of the indicator, e.g. "
                "<i>1. Under improved management</i>.</li>"
                "<li><b>sub_indicator</b>: full name of the sub-indicator, "
                "e.g. <i>1.1 Protected areas newly created</i>.</li>"
                "<li><b>target</b>: reporting target, in hectares.</li>"
                "<li><b>reported_progress</b>: reported progress, in "
                "hectares.</li>"
                "</ul>"
                "<p>The indicator totals are the sums of their "
                "sub-indicators. Example:</p>"
                "<pre>"
                "indicator;sub_indicator;target;reported_progress\n"
                "1. Under improved management;"
                "1.1 Protected areas newly created;500;450\n"
                "1. Under improved management;"
                "1.2 Improved management effectiveness;2000;1750"
                "</pre>"
            )
        )

    def _check_data_csv(self, path: str) -> bool:
        """Shows an error and returns False when the CSV cannot be used."""
        if not path:
            message = self.tr("Choose the CSV file with the report data.")
        elif not Path(path).is_file():
            message = self.tr("The report data file does not exist.")
        else:
            try:
                with open(path, newline="", encoding="utf-8") as csv_file:
                    columns = next(csv.reader(csv_file, delimiter=CSV_DELIMITER), [])
            except (OSError, UnicodeDecodeError):
                columns = None
            if columns is None:
                message = self.tr("Cannot read the report data file.")
            else:
                missing = [c for c in REQUIRED_DATA_COLUMNS if c not in columns]
                if not missing:
                    return True
                message = self.tr("The report data file has no column: {}").format(
                    ", ".join(missing)
                )

        QtWidgets.QMessageBox.critical(None, self.tr("Error"), message)
        return False

    def _check_spatial_layer(self, layer) -> bool:
        """Shows an error and returns False when the layer cannot be used."""
        if not isinstance(layer, QgsVectorLayer):
            message = self.tr("Choose the polygon layer of the restoration sites.")
        elif layer.providerType() == "memory":
            message = self.tr(
                "Save the restoration sites layer to a file, e.g. a GeoPackage."
            )
        else:
            missing = [
                f for f in REQUIRED_SPATIAL_FIELDS if layer.fields().indexOf(f) < 0
            ]
            if not missing:
                return True
            message = self.tr("The restoration sites layer has no field: {}").format(
                ", ".join(missing)
            )

        QtWidgets.QMessageBox.critical(None, self.tr("Error"), message)
        return False

    def btn_calculate(self):
        ret = super().btn_calculate()
        if not ret:
            return

        project_name = self.project_name_le.text().strip()
        if not project_name:
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"), self.tr("Enter the project name.")
            )
            return

        data_csv = self.data_csv_fw.filePath()
        if not self._check_data_csv(data_csv):
            return

        # GEF_CP_ID of the child project, None for all the child projects
        gef_cp_id = None
        if self.child_project_rb.isChecked():
            gef_cp_id = self.child_project_cb.currentText().strip()
            if self.child_project_cb.findText(gef_cp_id) < 0:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr("Choose a child project of the report data file."),
                )
                return

        spatial_layer = self.spatial_layer_cb.currentLayer()
        if not self._check_spatial_layer(spatial_layer):
            return
        if gef_cp_id and spatial_layer.fields().indexOf(GEF_CP_ID) < 0:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "The restoration sites layer has no field {}, to select "
                    "the sites of the child project."
                ).format(GEF_CP_ID),
            )
            return

        baseline_date = self.baseline_date_de.date()
        latest_monitoring_date = self.latest_monitoring_date_de.date()
        if baseline_date > latest_monitoring_date:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("The baseline date is after the latest monitoring date."),
            )
            return

        self.close()

        job_params = {
            "task_name": self.execution_name_le.text(),
            "task_notes": self.task_notes.toPlainText(),
            "project_name": project_name,
            "data_csv": data_csv,
            "gef_cp_id": gef_cp_id,
            # The source, as the job opens the layer again outside of the
            # main thread
            "spatial_layer": spatial_layer.source(),
            "spatial_layer_provider": spatial_layer.providerType(),
            # Name of the layer, the spatial data version of the report
            "spatial_layer_name": spatial_layer.name(),
            # Reporting period, as YYYY-MM-DD
            "baseline_date": baseline_date.toString("yyyy-MM-dd"),
            "latest_monitoring_date": latest_monitoring_date.toString("yyyy-MM-dd"),
        }
        job_manager.submit_local_job_as_qgstask(
            job_params, self.LOCAL_SCRIPT_NAME, self.aoi
        )
