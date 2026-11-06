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

import shutil
from pathlib import Path

import qgis.gui
from qgis.core import QgsProject, QgsVectorLayer, QgsWkbTypes
from qgis.PyQt import QtCore, QtGui, QtWidgets, uic
from te_schemas.algorithms import ExecutionScript

from . import calculate
from .jobs.manager import job_manager
from .reports.ecosystem_restoration.report import (
    DATA_TEMPLATE_PATH,
    DATA_XLSX_NAME,
    GEF_CP_ID,
    REQUIRED_DATA_COLUMNS,
    read_data,
)
from .reports.ecosystem_restoration.spatial import (
    LAYER_NAME_REGEX,
    check_layer_file,
    layer_dates,
    layer_name,
    missing_fields,
    validate_sites,
    write_spatial_template,
)

DlgEcosystemReportingRestorationProgressUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgEcosystemReportingRestorationProgress.ui")
)
DlgSpatialTemplateUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgSpatialTemplate.ui")
)


class DlgSpatialTemplate(QtWidgets.QDialog, DlgSpatialTemplateUi):
    """ISO3 of the country and date of the restoration sites template."""

    def __init__(self, parent: QtWidgets.QWidget = None):
        super().__init__(parent)
        self.setupUi(self)
        # Only letters, upper case when accepted
        self.country.setValidator(
            QtGui.QRegularExpressionValidator(
                QtCore.QRegularExpression("[A-Za-z]{0,3}"), self.country
            )
        )
        self.date.setDate(QtCore.QDate.currentDate())
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

    def accept(self):
        self.country.setText(self.country.text().strip().upper())
        if not LAYER_NAME_REGEX.match(self.layer_name()):
            QtWidgets.QMessageBox.critical(
                self,
                self.tr("Error"),
                self.tr(
                    "Enter the three-letter ISO 3166-1 alpha-3 code of the "
                    "country, e.g. IND."
                ),
            )
            return
        super().accept()

    def layer_name(self) -> str:
        """Name of the files of the template, e.g. IND_V20261231."""
        return layer_name(self.country.text(), self.date.date().toPyDate())


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

        # Child projects of the report data, searched by any part of their GEF_CP_ID
        completer = self.child_project.completer()
        completer.setFilterMode(QtCore.Qt.MatchContains)
        completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.child_project_radio_button.toggled.connect(self.child_project.setEnabled)
        self.data_xlsx.fileChanged.connect(self._load_child_projects)
        self.data_xlsx_template_label.linkActivated.connect(
            self._download_data_template
        )

        # Spatial input layers, and the reporting period from their names
        self.spatial_layers.checkedItemsChanged.connect(self._update_reporting_period)
        self.spatial_layers_import_button.clicked.connect(self._import_spatial_layer)
        self.spatial_layers_template_label.linkActivated.connect(
            self._download_spatial_template
        )
        self._load_spatial_layers()
        self._finish_initialization()

    def showEvent(self, event):
        super().showEvent(event)
        self._load_spatial_layers()

    def _load_spatial_layers(self, checked_ids: list[str] | None = None):
        """List the polygon layers of the project in the spatial input."""
        checked_ids = set(checked_ids or []) | set(
            self.spatial_layers.checkedItemsData()
        )
        self.spatial_layers.blockSignals(True)
        self.spatial_layers.clear()
        layers = sorted(
            (
                layer
                for layer in QgsProject.instance().mapLayers().values()
                if isinstance(layer, QgsVectorLayer)
                and layer.geometryType() == QgsWkbTypes.PolygonGeometry
            ),
            key=lambda layer: layer.name(),
        )
        for layer in layers:
            self.spatial_layers.addItemWithCheckState(
                layer.name(),
                QtCore.Qt.Checked if layer.id() in checked_ids else QtCore.Qt.Unchecked,
                layer.id(),
            )
        self.spatial_layers.blockSignals(False)
        self._update_reporting_period()

    def _checked_spatial_layers(self) -> list[QgsVectorLayer]:
        """Checked layers of the spatial input, still in the project."""
        project = QgsProject.instance()
        layers = [
            project.mapLayer(layer_id)
            for layer_id in self.spatial_layers.checkedItemsData()
        ]
        return [layer for layer in layers if layer]

    def _update_reporting_period(self):
        """Show the reporting period, from the names of the checked layers."""
        names = [layer.name() for layer in self._checked_spatial_layers()]
        dates, errors = layer_dates(names)
        if errors:
            text = "<br>".join(errors)
            self.reporting_period_label.setText(
                f"<span style='color:red'>{text}</span>"
            )
        elif dates:
            self.reporting_period_label.setText(
                self.tr("Baseline date: {} • Latest monitoring date: {}").format(
                    min(dates.values()), max(dates.values())
                )
            )
        else:
            self.reporting_period_label.setText(
                self.tr("Choose the layers, one per year for a country.")
            )

    def _import_spatial_layer(self):
        """Add vector layers to the project and select them in the spatial input."""
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            self.tr("Import restoration sites"),
            "",
            self.tr(
                "Vector files (*.geojson *.kml *.shp);;"
                "GeoJSON (*.geojson);;"
                "KML (*.kml);;"
                "Shapefile (*.shp)"
            ),
        )
        if not paths:
            return

        layer_ids = []
        failed_paths = []
        for path in paths:
            layer = self.iface.addVectorLayer(path, Path(path).stem, "ogr")
            if layer and layer.isValid():
                layer_ids.append(layer.id())
            else:
                failed_paths.append(path)

        # List the layers of the project, now with the loaded layers checked
        self._load_spatial_layers(layer_ids)
        if failed_paths:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Cannot load the layers:\n{}").format("\n".join(failed_paths)),
            )

    def _download_data_template(self):
        """Save the report data XLSX template."""
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            self.tr("Save report data template"),
            DATA_XLSX_NAME,
            self.tr("Excel files (*.xlsx)"),
        )
        if not path:
            return
        if Path(path).suffix.lower() != ".xlsx":
            path = f"{path}.xlsx"
        try:
            shutil.copyfile(DATA_TEMPLATE_PATH, path)
        except OSError as error:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Cannot save the template: {}").format(error),
            )
            return

    def _download_spatial_template(self):
        """Save the ZIP of the Shapefile template of the restoration sites.

        The files are named after the ISO3 and the date entered in
        DlgSpatialTemplate, e.g. IND_V20261231.
        """
        dialog = DlgSpatialTemplate(self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            self.tr("Save restoration sites template"),
            f"{dialog.layer_name()}.zip",
            self.tr("ZIP files (*.zip)"),
        )
        if not path:
            return
        if Path(path).suffix.lower() != ".zip":
            path = f"{path}.zip"
        try:
            write_spatial_template(
                Path(path), dialog.country.text(), dialog.date.date().toPyDate()
            )
        except OSError as error:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Cannot save the template: {}").format(error),
            )

    def _load_child_projects(self, path: str):
        """List the GEF_CP_ID of the report data in the child project input."""
        child_projects = set()
        if path and Path(path).is_file():
            try:
                _, data = read_data(path)
            except Exception as error:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr("Cannot read the report data file: {}").format(error),
                )
                data = []
            child_projects.update(row.get(GEF_CP_ID, "") for row in data)
        child_projects.discard("")
        self.child_project.clear()
        self.child_project.addItems(sorted(child_projects))

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
                "<h4>Report data (XLSX)</h4>"
                "<p>The first sheet of the XLSX file has a header row with "
                "these columns, and one row per sub-indicator of a child "
                "project:</p>"
                "<ul>"
                "<li><b>GEF_CP_ID</b>: GEF identification of the child "
                "project.</li>"
                "<li><b>indicator</b>: full name of the indicator, e.g. "
                "<i>1. Under improved management</i>.</li>"
                "<li><b>sub_indicator</b>: full name of the sub-indicator, "
                "e.g. <i>1.1 Protected areas newly created</i>.</li>"
                "<li><b>target</b>: reporting target, in hectares.</li>"
                "<li><b>reported_progress</b>: reported progress, in "
                "hectares.</li>"
                "</ul>"
                "<p>The indicator totals are the sums of their "
                "sub-indicators. Download the template for an example.</p>"
            )
        )

    def _check_data_xlsx(self, path: str) -> bool:
        """Shows an error and returns False when the XLSX cannot be used."""
        if not path:
            message = self.tr("Choose the XLSX file with the report data.")
        elif not Path(path).is_file():
            message = self.tr("The report data file does not exist.")
        else:
            try:
                columns, _ = read_data(path)
                error = None
            except Exception as read_error:
                error = read_error
            if error is not None:
                message = self.tr("Cannot read the report data file: {}").format(error)
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
            message = self.tr("The restoration sites layer is not a vector layer.")
        elif check_layer_file(layer):
            message = "\n".join(check_layer_file(layer))
        else:
            missing = missing_fields(layer)
            errors = [] if missing else validate_sites(layer)
            if missing:
                message = self.tr("The layer {} has no field: {}").format(
                    layer.name(), ", ".join(missing)
                )
            elif errors:
                message = self.tr("The layer {} has invalid sites:\n{}").format(
                    layer.name(), "\n".join(errors)
                )
            else:
                return True

        QtWidgets.QMessageBox.critical(None, self.tr("Error"), message)
        return False

    def btn_calculate(self):
        ret = super().btn_calculate()
        if not ret:
            return

        project_name = self.project_name.text().strip()
        if not project_name:
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"), self.tr("Enter the project name.")
            )
            return

        data_xlsx = self.data_xlsx.filePath()
        if not self._check_data_xlsx(data_xlsx):
            return

        # GEF_CP_ID of the child project, None for all the child projects
        gef_cp_id = None
        if self.child_project_radio_button.isChecked():
            gef_cp_id = self.child_project.currentText().strip()
            if self.child_project.findText(gef_cp_id) < 0:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr("Choose a child project of the report data file."),
                )
                return

        # Spatial input layers, named [ISO COUNTRY]_V[YYYYMMDD], one per year
        # for a country
        spatial_layers = self._checked_spatial_layers()
        if not spatial_layers:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Choose the polygon layers of the restoration sites."),
            )
            return
        _, errors = layer_dates([layer.name() for layer in spatial_layers])
        if errors:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"), "\n".join(errors))
            return
        for spatial_layer in spatial_layers:
            if not self._check_spatial_layer(spatial_layer):
                return

        self.close()

        job_params = {
            "task_name": self.execution_name.text(),
            "task_notes": self.task_notes.toPlainText(),
            "project_name": project_name,
            "data_xlsx": data_xlsx,
            "gef_cp_id": gef_cp_id,
            "spatial_layers": [
                {
                    "name": spatial_layer.name(),
                    "source": spatial_layer.source(),
                    "provider": spatial_layer.providerType(),
                }
                for spatial_layer in spatial_layers
            ],
        }
        job_manager.submit_local_job_as_qgstask(
            job_params, self.LOCAL_SCRIPT_NAME, self.aoi
        )
