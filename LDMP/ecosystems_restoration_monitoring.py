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
from qgis.core import QgsProject, QgsVectorLayer
from qgis.gui import QgsFileWidget
from qgis.PyQt import QtCore, QtGui, QtWidgets, uic
from te_schemas.algorithms import ExecutionScript

from . import calculate
from .jobs.manager import job_manager
from .reports.ecosystem_restoration.report import (
    DATA_TEMPLATE_PATH,
    DATA_XLSX_NAME,
    GEF_CP_ID,
    DEFAULT_BASELINE_YEARS_BEFORE,
    MIN_REPORTING_YEAR,
    REQUIRED_DATA_COLUMNS,
    read_data,
    validate_reporting_period,
)
from .reports.ecosystem_restoration.spatial import (
    LAYER_NAME_REGEX,
    SPATIAL_FILE_FILTER,
    TEMPLATE_FORMATS,
    layer_name,
    open_spatial_file,
    read_sites_yearly,
    validate_spatial_layer_name,
    write_spatial_template,
)
from .reports.ecosystem_restoration.spatial_validation import (
    LayerValidation,
    validate_spatial_data,
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
        self.template_format.addItems(list(TEMPLATE_FORMATS))
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

        # Spatial input files
        self.spatial_layers.setFilter(self.tr(SPATIAL_FILE_FILTER))
        self.spatial_layers_load_button.clicked.connect(self._load_spatial_files)
        self.spatial_layers_template_label.linkActivated.connect(
            self._download_spatial_template
        )

        # Reporting period, from the baseline year to the reporting year, the
        # baseline year is not after the reporting year
        this_year = QtCore.QDate.currentDate().year()
        for spin_box in (self.baseline_year, self.reporting_year):
            spin_box.setRange(MIN_REPORTING_YEAR, this_year)
        self.reporting_year.setValue(this_year)
        # Year inputs twice as wide as their default width
        for spin_box in (self.baseline_year, self.reporting_year):
            spin_box.setMinimumWidth(2 * spin_box.sizeHint().width())
        self.baseline_year.setValue(this_year - DEFAULT_BASELINE_YEARS_BEFORE)
        self.baseline_year.setMaximum(self.reporting_year.value())
        self.reporting_year.valueChanged.connect(self._reporting_year_changed)
        self.baseline_year.valueChanged.connect(self._baseline_year_changed)
        self._finish_initialization()

    def _load_spatial_files(self):
        """Add the selected spatial input files to the QGIS project."""
        paths = QgsFileWidget.splitFilePaths(self.spatial_layers.filePath())
        if not paths:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Choose the files of the restoration sites."),
            )
            return

        errors = []
        for path in paths:
            try:
                layer = open_spatial_file(path)
            except ValueError as error:
                errors.append(str(error))
                continue
            QgsProject.instance().addMapLayer(layer)
        if errors:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Cannot load the files:\n{}").format("\n".join(errors)),
            )

    def _reporting_year_changed(self, year: int):
        """The baseline year is not after the reporting year, it is changed to
        the reporting year when it is."""
        if self.baseline_year.value() > year:
            self.baseline_year.setValue(year)
        self.baseline_year.setMaximum(year)

    def _baseline_year_changed(self, year: int):
        """The reporting year is not before the baseline year, it is changed
        to the baseline year when it is."""
        if self.reporting_year.value() < year:
            self.reporting_year.setValue(year)

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
        """Save the template of the restoration sites, in the format chosen in
        DlgSpatialTemplate."""
        dialog = DlgSpatialTemplate(self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return

        template_format = dialog.template_format.currentText()
        extension = TEMPLATE_FORMATS[template_format]
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            self.tr("Save restoration sites template"),
            f"{dialog.layer_name()}{extension}",
            self.tr("{} files (*{})").format(
                "ZIP" if template_format == "Shapefile" else template_format,
                extension,
            ),
        )
        if not path:
            return
        if Path(path).suffix.lower() != extension:
            path = f"{path}{extension}"
        try:
            write_spatial_template(
                Path(path),
                dialog.country.text(),
                dialog.date.date().toPyDate(),
                template_format,
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
        else:
            errors = LayerValidation(layer).run()
            if not errors:
                return True
            message = self.tr("The layer {} is not valid:\n{}").format(
                layer.name(), "\n".join(errors)
            )

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

        # Reporting period, the baseline year is not after the reporting year
        baseline_year = self.baseline_year.value()
        reporting_year = self.reporting_year.value()
        errors = validate_reporting_period(baseline_year, reporting_year)
        if errors:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"), "\n".join(errors))
            return

        # Spatial input files of one country
        paths = QgsFileWidget.splitFilePaths(self.spatial_layers.filePath())
        if not paths:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Choose the files of the restoration sites."),
            )
            return
        spatial_layers = []
        for path in paths:
            try:
                spatial_layers.append(open_spatial_file(path))
            except ValueError as error:
                QtWidgets.QMessageBox.critical(None, self.tr("Error"), str(error))
                return
        errors = validate_spatial_layer_name([layer.name() for layer in spatial_layers])
        if errors:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"), "\n".join(errors))
            return
        for spatial_layer in spatial_layers:
            if not self._check_spatial_layer(spatial_layer):
                return
        # Sites of the layers, one record of a site in a year, the sites of an
        # indicator in a year do not overlap
        errors = validate_spatial_data(read_sites_yearly(spatial_layers))
        if errors:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("The spatial input layers are not valid:\n{}").format(
                    "\n".join(errors)
                ),
            )
            return

        self.close()

        job_params = {
            "task_name": self.execution_name.text(),
            "task_notes": self.task_notes.toPlainText(),
            "project_name": project_name,
            "data_xlsx": data_xlsx,
            "gef_cp_id": gef_cp_id,
            "baseline_year": baseline_year,
            "reporting_year": reporting_year,
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
