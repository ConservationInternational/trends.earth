"""Criteria configuration and candidate-area selection for LDN Planning."""

import copy
import json
import math
import typing
from pathlib import Path

from qgis.PyQt import QtCore, QtWidgets
from te_schemas.jobs import JobStatus
from te_schemas.results import RasterResults

from . import data_io
from .calculate import DlgCalculateBase
from .calculate_ldn_planning import (
    _add_region_buttons,
    _add_task_name_notes,
    _build_splitter_with_ok_cancel,
    _make_group,
)
from .jobs.manager import job_manager

CLASSES = ("avoid", "reduce", "reverse")


def planning_raster_jobs(result_name):
    jobs = []
    for job in job_manager.relevant_jobs:
        if job.status not in (JobStatus.DOWNLOADED, JobStatus.GENERATED_LOCALLY):
            continue
        if not job_manager.ensure_results_loaded(job):
            continue
        result = job.get_first_result_by_type(RasterResults)
        if result is not None and result.name == result_name:
            jobs.append(job)
    return jobs


def job_raster_path(job):
    job_manager.ensure_results_loaded(job)
    result = job.get_first_result_by_type(RasterResults)
    if result is None or result.uri is None or result.uri.uri is None:
        raise ValueError("The selected job has no readable raster result.")
    path = Path(result.uri.uri)
    if not path.is_file():
        raise ValueError(f"Raster file is missing: {path}")
    return str(path), result


class DlgPriorityCriterion(QtWidgets.QDialog):
    def __init__(self, parent=None, criterion=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Priority criterion"))
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.fields = {}
        for key, label in (
            ("name", self.tr("Name")),
            ("path", self.tr("Raster or polygon file")),
            ("field", self.tr("Polygon numeric field (leave empty for raster)")),
            ("source", self.tr("Source / attribution (optional)")),
            ("date", self.tr("Dataset date (optional)")),
            ("units", self.tr("Units (optional)")),
            ("license", self.tr("License / usage rights (optional)")),
        ):
            widget = QtWidgets.QLineEdit()
            self.fields[key] = widget
            form.addRow(label, widget)
        browse = QtWidgets.QPushButton(self.tr("Browse..."))
        browse.clicked.connect(self._browse)
        form.addRow("", browse)
        self.band = QtWidgets.QSpinBox()
        self.band.setRange(1, 10000)
        form.addRow(self.tr("Raster band"), self.band)
        self.arr_class = QtWidgets.QComboBox()
        for key, label in (
            ("avoid", self.tr("Avoid")),
            ("reduce", self.tr("Reduce")),
            ("reverse", self.tr("Reverse")),
        ):
            self.arr_class.addItem(label, key)
        form.addRow(self.tr("Eligible ARR class"), self.arr_class)
        self.weight = QtWidgets.QDoubleSpinBox()
        self.weight.setRange(0, 1e6)
        self.weight.setDecimals(6)
        self.weight.setValue(1)
        form.addRow(
            self.tr("Relative weight (normalized within each class)"), self.weight
        )
        self.direction = QtWidgets.QComboBox()
        self.direction.addItem(self.tr("Higher preferred"), "higher")
        self.direction.addItem(self.tr("Lower preferred"), "lower")
        form.addRow(self.tr("Direction"), self.direction)
        self.minimum = QtWidgets.QDoubleSpinBox()
        self.maximum = QtWidgets.QDoubleSpinBox()
        for widget in (self.minimum, self.maximum):
            widget.setRange(-1e12, 1e12)
            widget.setDecimals(6)
        self.maximum.setValue(1)
        form.addRow(self.tr("Normalization minimum"), self.minimum)
        form.addRow(self.tr("Normalization maximum"), self.maximum)
        self.categories = QtWidgets.QLineEdit()
        self.categories.setPlaceholderText('{"1": 0.2, "2": 0.8}')
        form.addRow(
            self.tr("Category scores (JSON; empty for continuous)"), self.categories
        )
        self.resampling = QtWidgets.QComboBox()
        self.resampling.addItems(["bilinear", "nearest", "average"])
        form.addRow(self.tr("Continuous resampling"), self.resampling)
        layout.addLayout(form)
        note = QtWidgets.QLabel(
            self.tr(
                "Scores are relative preferences, not success probabilities. Values outside "
                "the normalization range are clamped. Category scores must be in [0,1]; "
                "unmapped categories are unscored. Missing required data are unscored, "
                "never assigned zero. No datasets or value judgments are supplied by default."
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if criterion:
            for key, widget in self.fields.items():
                widget.setText(str(criterion.get(key, "")))
            self.band.setValue(criterion.get("band_index", 1))
            self.arr_class.setCurrentIndex(CLASSES.index(criterion["arr_class"]))
            self.weight.setValue(criterion["weight"])
            self.direction.setCurrentIndex(
                self.direction.findData(criterion.get("direction", "higher"))
            )
            self.minimum.setValue(criterion.get("minimum", 0))
            self.maximum.setValue(criterion.get("maximum", 1))
            if criterion.get("categories"):
                self.categories.setText(json.dumps(criterion["categories"]))
            self.resampling.setCurrentText(criterion.get("resampling", "bilinear"))
        self.criterion = None

    def _browse(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr("Criterion dataset"),
            "",
            self.tr("Spatial files (*.tif *.tiff *.vrt *.gpkg *.geojson *.shp)"),
        )
        if path:
            self.fields["path"].setText(path)

    def _accept(self):
        try:
            criterion = {
                key: widget.text().strip() for key, widget in self.fields.items()
            }
            for key in ("name", "path"):
                if not criterion[key]:
                    raise ValueError(self.tr("Name and file are required."))
            # Metadata is optional; record missing entries explicitly.
            for key in ("source", "date", "units", "license"):
                criterion[key] = criterion[key] or "Not specified"
            if not Path(criterion["path"]).is_file():
                raise ValueError(self.tr("The criterion file does not exist."))
            criterion.update(
                arr_class=self.arr_class.currentData(),
                band_index=self.band.value(),
                weight=self.weight.value(),
                direction=self.direction.currentData(),
                resampling=self.resampling.currentText(),
                minimum=self.minimum.value(),
                maximum=self.maximum.value(),
            )
            if self.categories.text().strip():
                categories = json.loads(self.categories.text())
                if not isinstance(categories, dict) or not categories:
                    raise ValueError(
                        self.tr("Category scores must be a non-empty JSON object.")
                    )
                for key, value in categories.items():
                    if not math.isfinite(float(key)) or not math.isfinite(float(value)):
                        raise ValueError(
                            self.tr("Category values and scores must be finite.")
                        )
                    if not 0 <= float(value) <= 1:
                        raise ValueError(
                            self.tr("Category scores must be between 0 and 1.")
                        )
                criterion["categories"] = categories
                criterion["resampling"] = "nearest"
            elif criterion["minimum"] >= criterion["maximum"]:
                raise ValueError(self.tr("Normalization maximum must exceed minimum."))
        except (ValueError, TypeError) as exc:
            QtWidgets.QMessageBox.critical(self, self.tr("Invalid criterion"), str(exc))
            return
        self.criterion = criterion
        self.accept()


class DlgCalculateLDNPlanningPriority(DlgCalculateBase):
    LOCAL_SCRIPT_NAME = "ldn-planning-priority"
    DRAFT_NAME = "priority"
    TABLE_HEADERS = ("", "Input", "Profile", "Class", "Weight", "Influence")

    def __init__(self, iface, script, parent=None, draft_name=None):
        super().__init__(iface, script, parent)
        if draft_name is not None:
            self.DRAFT_NAME = draft_name
        # Each entry is either
        #   {"kind": "managed", "job_id": ..., "profile": {...}, "arr_class": ...,
        #    "weight": ..., "enabled": ...}
        # or the advanced escape hatch
        #   {"kind": "file", "criterion": {...}, "enabled": ...}
        self.entries: typing.List[dict] = []
        layout = QtWidgets.QVBoxLayout()
        inner = _make_group(self.tr("ARR classification"), layout)
        self.combo_arr = data_io.WidgetDataIOSelectTELayerExisting()
        self.combo_arr.setProperty("layer_type", "LDN Planning - Avoid/Reduce/Reverse")
        inner.addWidget(self.combo_arr)
        inner = _make_group(self.tr("Class-specific priority criteria"), layout)
        self.criteria_table = QtWidgets.QTableWidget(0, len(self.TABLE_HEADERS))
        self.criteria_table.setHorizontalHeaderLabels(
            [self.tr(header) for header in self.TABLE_HEADERS]
        )
        self.criteria_table.horizontalHeader().setStretchLastSection(True)
        self.criteria_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        inner.addWidget(self.criteria_table)
        row = QtWidgets.QHBoxLayout()
        for label, callback in (
            (self.tr("Add imported input..."), self._add_managed),
            (self.tr("Import new input..."), self._import_input),
            (self.tr("Remove selected"), self._remove),
        ):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        inner.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        for label, callback in (
            (self.tr("Advanced: add from file..."), self._add),
            (self.tr("Load settings..."), self._load_settings),
            (self.tr("Save settings..."), self._save_settings),
        ):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        inner.addLayout(row)
        self.paths = {}
        key, label = (
            "exclusion_path",
            self.tr("Exclusion raster (>0 excluded; missing values unscored)"),
        )
        row = QtWidgets.QHBoxLayout()
        path = QtWidgets.QLineEdit()
        self.paths[key] = path
        row.addWidget(path)
        button = QtWidgets.QPushButton(self.tr("Browse..."))
        button.clicked.connect(lambda checked=False, w=path: self._browse(w))
        row.addWidget(button)
        inner.addWidget(QtWidgets.QLabel(label))
        inner.addLayout(row)
        self.land_types_label = QtWidgets.QLabel(
            self.tr("Land-type summaries (optional)")
        )
        inner.addWidget(self.land_types_label)
        self.combo_land_types = QtWidgets.QComboBox()
        inner.addWidget(self.combo_land_types)
        self._land_types_jobs: typing.List = []
        self._pending_land_type_job_id = None
        self.jurisdictions_label = QtWidgets.QLabel(
            self.tr("Jurisdiction summaries (optional)")
        )
        inner.addWidget(self.jurisdictions_label)
        self.rb_zones_none = QtWidgets.QRadioButton(
            self.tr("No jurisdiction breakdown")
        )
        self.rb_zones_none.setChecked(True)
        self.rb_zones_admin = QtWidgets.QRadioButton(
            self.tr("Administrative units (level 1) of the selected country")
        )
        self.rb_zones_file = QtWidgets.QRadioButton(self.tr("Upload a polygon layer"))
        for radio in (self.rb_zones_none, self.rb_zones_admin, self.rb_zones_file):
            inner.addWidget(radio)
        row = QtWidgets.QHBoxLayout()
        zones_edit = QtWidgets.QLineEdit()
        zones_edit.setPlaceholderText(self.tr("No file selected"))
        self.paths["zones_path"] = zones_edit
        row.addWidget(zones_edit)
        self.btn_zones_browse = QtWidgets.QPushButton(self.tr("Browse..."))
        self.btn_zones_browse.clicked.connect(
            lambda checked=False, w=zones_edit: self._browse(w)
        )
        row.addWidget(self.btn_zones_browse)
        inner.addLayout(row)
        zones_edit.setEnabled(False)
        self.btn_zones_browse.setEnabled(False)
        self.rb_zones_file.toggled.connect(zones_edit.setEnabled)
        self.rb_zones_file.toggled.connect(self.btn_zones_browse.setEnabled)
        note = QtWidgets.QLabel(
            self.tr(
                "Complete-case scoring: pixels missing any required criterion remain "
                "unscored. Scores are comparable only within an ARR class. "
                "This creates preview maps and reports, not scenario targets. "
                "Add candidate areas to a scenario draft to compare outcomes. "
                "Repeat with different weights to examine sensitivity. "
                "Your configuration is kept as a draft between sessions."
            )
        )
        note.setWordWrap(True)
        inner.addWidget(note)
        self.execution_name_le, self.task_notes = _add_task_name_notes(
            layout, "LDN Planning - Priority"
        )
        self.region_la, self.region_button = _add_region_buttons(layout)
        left = QtWidgets.QWidget()
        left.setLayout(layout)
        self.splitter, self.button_box = _build_splitter_with_ok_cancel(
            self,
            left,
            self.tr(
                "<h3>Prioritize interventions</h3>"
                "<p>Select an ARR layer, then add imported prioritization inputs "
                "and their scoring profiles to each response class. Dataset "
                "provenance and scoring settings are stored with the input, so "
                "they are configured once and reused across plans.</p>"
                "<p>Scores are comparable within a class. Missing criterion data "
                "remain unscored. Inspect coverage and compare alternative weights.</p>"
                "<p><a href='https://docs.trends.earth/en/latest/for_users/training/ldnplanning.html'>"
                "LDN planning tutorial</a></p>"
            ),
        )
        self._finish_initialization()
        self.setWindowTitle(self.tr("LDN Planning - Prioritize interventions"))
        self.resize(950, 700)
        self.changed_region.connect(self.combo_arr.populate)
        self._restore_draft()

    def showEvent(self, event):
        super().showEvent(event)
        self.combo_arr.populate()
        settings = getattr(self, "preselect_priority_settings", None)
        if settings is not None:
            self.preselect_priority_settings = None
            if "entries" not in settings:
                QtWidgets.QMessageBox.warning(
                    self,
                    self.tr("Settings unavailable"),
                    self.tr(
                        "The saved priority has no editable criteria settings. "
                        "Inspect the current draft before running."
                    ),
                )
            else:
                self.entries = copy.deepcopy(settings["entries"])
                for key, widget in self.paths.items():
                    widget.setText(settings.get(key) or "")
                self._apply_zones_source(settings.get("zones_source"))
                self._pending_land_type_job_id = settings.get("land_type_job_id")
                self._refresh()
        preselect_arr = getattr(self, "preselect_arr_job_id", None)
        if preselect_arr:
            from .ldn_planning_actions import select_job_band

            select_job_band(
                self.combo_arr, preselect_arr, self, self.tr("ARR classification")
            )
            self.preselect_arr_job_id = None
        previous = self._pending_land_type_job_id or self.combo_land_types.currentData()
        self._pending_land_type_job_id = None
        self._land_types_jobs = job_manager.get_ldn_land_types_jobs()
        self.combo_land_types.clear()
        self.combo_land_types.addItem(self.tr("No land-type summaries"), None)
        for job in self._land_types_jobs:
            self.combo_land_types.addItem(job.task_name or str(job.id), str(job.id))
        if hasattr(self, "preselect_land_type_job_id"):
            previous = self.preselect_land_type_job_id
            del self.preselect_land_type_job_id
        if previous is not None:
            index = self.combo_land_types.findData(previous)
            if index >= 0:
                self.combo_land_types.setCurrentIndex(index)
            else:
                self.combo_land_types.setCurrentIndex(-1)
                QtWidgets.QMessageBox.warning(
                    self,
                    self.tr("Dataset unavailable"),
                    self.tr("The selected land types are unavailable. Choose another."),
                )
        if getattr(self, "project_inputs", None):
            self.combo_arr.parentWidget().hide()
            self.combo_land_types.hide()
            self.land_types_label.hide()
            self.region_button.hide()
            self.region_la.hide()
            context = self.project_inputs["state"]["context"]
            self._apply_zones_source(
                {"none": "none", "file": "file", "admin": "admin_level_1"}[
                    context["jurisdictions"]
                ]
            )
            self.paths["zones_path"].setText(context["jurisdictions_path"] or "")
            for widget in (
                self.jurisdictions_label,
                self.rb_zones_none,
                self.rb_zones_admin,
                self.rb_zones_file,
                self.paths["zones_path"],
                self.btn_zones_browse,
            ):
                widget.hide()

    def closeEvent(self, event):
        self._store_draft()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Draft persistence
    # ------------------------------------------------------------------

    def _store_draft(self):
        from . import ldn_planning_assets

        try:
            ldn_planning_assets.save_draft(self.DRAFT_NAME, self._settings())
        except (OSError, ValueError, TypeError):
            pass

    def _restore_draft(self):
        from . import ldn_planning_assets

        try:
            draft = ldn_planning_assets.load_draft(self.DRAFT_NAME)
        except (OSError, ValueError, TypeError):
            draft = None
        if not draft:
            return
        self.entries = draft.get("entries", [])
        for key, widget in self.paths.items():
            widget.setText(draft.get(key) or "")
        self._apply_zones_source(draft.get("zones_source"))
        self._pending_land_type_job_id = draft.get("land_type_job_id")
        self._refresh()

    # ------------------------------------------------------------------
    # Jurisdiction source
    # ------------------------------------------------------------------

    def _zones_source(self) -> str:
        if self.rb_zones_admin.isChecked():
            return "admin_level_1"
        if self.rb_zones_file.isChecked():
            return "file"
        return "none"

    def _apply_zones_source(self, source):
        if source is None:
            source = "file" if self.paths["zones_path"].text().strip() else "none"
        radios = {
            "admin_level_1": self.rb_zones_admin,
            "file": self.rb_zones_file,
        }
        radios.get(source, self.rb_zones_none).setChecked(True)

    # ------------------------------------------------------------------
    # Criteria table
    # ------------------------------------------------------------------

    def _entry_labels(self, entry) -> typing.Tuple[str, str]:
        from . import ldn_planning_assets

        if entry["kind"] == "managed":
            job = self._find_input_job(entry["job_id"])
            input_label = (
                ldn_planning_assets.input_display_name(job)
                if job is not None
                else self.tr("Missing input %s — relink or re-import") % entry["job_id"]
            )
            profile = entry["profile"]
            profile_label = "%s (rev %s)" % (
                profile.get("name", "?"),
                profile.get("revision", "?"),
            )
            return input_label, profile_label
        criterion = entry["criterion"]
        return (
            self.tr("File: %s") % criterion.get("path", "?"),
            criterion.get("name", "?"),
        )

    def _find_input_job(self, job_id: str):
        for job in job_manager.get_planning_input_jobs():
            if str(job.id) == str(job_id):
                return job
        return None

    def _refresh(self):
        self.criteria_table.setRowCount(0)
        for index, entry in enumerate(self.entries):
            row = self.criteria_table.rowCount()
            self.criteria_table.insertRow(row)
            enabled = QtWidgets.QCheckBox()
            enabled.setChecked(entry.get("enabled", True))
            enabled.toggled.connect(
                lambda checked, i=index: self._entry_changed(i, enabled=checked)
            )
            self.criteria_table.setCellWidget(row, 0, enabled)
            input_label, profile_label = self._entry_labels(entry)
            for column, text in ((1, input_label), (2, profile_label)):
                item = QtWidgets.QTableWidgetItem(text)
                item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
                self.criteria_table.setItem(row, column, item)
            class_combo = QtWidgets.QComboBox()
            for key, label in (
                ("avoid", self.tr("Avoid")),
                ("reduce", self.tr("Reduce")),
                ("reverse", self.tr("Reverse")),
            ):
                class_combo.addItem(label, key)
            class_combo.setCurrentIndex(CLASSES.index(self._entry_class(entry)))
            class_combo.currentIndexChanged.connect(
                lambda _, i=index, combo=class_combo: self._entry_changed(
                    i, arr_class=combo.currentData()
                )
            )
            self.criteria_table.setCellWidget(row, 3, class_combo)
            weight = QtWidgets.QDoubleSpinBox()
            weight.setRange(0, 1e6)
            weight.setDecimals(3)
            weight.setValue(self._entry_weight(entry))
            weight.valueChanged.connect(
                lambda value, i=index: self._entry_changed(i, weight=value)
            )
            self.criteria_table.setCellWidget(row, 4, weight)
            influence = QtWidgets.QTableWidgetItem("")
            influence.setFlags(QtCore.Qt.ItemIsEnabled)
            self.criteria_table.setItem(row, 5, influence)
        self._update_influence()

    def _entry_class(self, entry) -> str:
        if entry["kind"] == "managed":
            return entry.get("arr_class", "avoid")
        return entry["criterion"].get("arr_class", "avoid")

    def _entry_weight(self, entry) -> float:
        if entry["kind"] == "managed":
            return float(entry.get("weight", 1))
        return float(entry["criterion"].get("weight", 1))

    def _entry_changed(self, index, enabled=None, arr_class=None, weight=None):
        entry = self.entries[index]
        if enabled is not None:
            entry["enabled"] = enabled
        if arr_class is not None:
            if entry["kind"] == "managed":
                entry["arr_class"] = arr_class
            else:
                entry["criterion"]["arr_class"] = arr_class
        if weight is not None:
            if entry["kind"] == "managed":
                entry["weight"] = weight
            else:
                entry["criterion"]["weight"] = weight
        self._update_influence()

    def _update_influence(self):
        totals: typing.Dict[str, float] = {}
        for entry in self.entries:
            if entry.get("enabled", True):
                totals[self._entry_class(entry)] = totals.get(
                    self._entry_class(entry), 0.0
                ) + self._entry_weight(entry)
        for row, entry in enumerate(self.entries):
            if row >= self.criteria_table.rowCount():
                break
            total = totals.get(self._entry_class(entry), 0.0)
            if not entry.get("enabled", True):
                text = self.tr("excluded")
            elif total <= 0:
                text = self.tr("no positive weights")
            else:
                text = f"{100 * self._entry_weight(entry) / total:.0f}%"
            self.criteria_table.item(row, 5).setText(text)

    # ------------------------------------------------------------------
    # Adding and removing criteria
    # ------------------------------------------------------------------

    def _import_input(self):
        from .ldn_planning_assets import DlgImportPlanningInput

        dialog = DlgImportPlanningInput(self)
        if dialog.exec() == QtWidgets.QDialog.Accepted and dialog.job is not None:
            self._configure_entry_for_job(dialog.job)

    def _add_managed(self):
        inputs = job_manager.get_planning_input_jobs()
        if not inputs:
            QtWidgets.QMessageBox.information(
                self,
                self.tr("No imported inputs"),
                self.tr(
                    "Import a prioritization input first (Import new input..., "
                    "or the Datasets panel import menu)."
                ),
            )
            return
        from .ldn_planning_assets import input_display_name

        labels = [input_display_name(job) for job in inputs]
        label, ok = QtWidgets.QInputDialog.getItem(
            self, self.tr("Choose input"), self.tr("Imported input"), labels, 0, False
        )
        if not ok:
            return
        self._configure_entry_for_job(inputs[labels.index(label)])

    def _configure_entry_for_job(self, job):
        from .ldn_planning_assets import DlgScoringProfile, input_params

        try:
            profiles = list(input_params(job).get("scoring_profiles", []))
        except ValueError as exc:
            QtWidgets.QMessageBox.critical(self, self.tr("Cannot use input"), str(exc))
            return
        profile = None
        if profiles:
            labels = [
                "%s (rev %s)" % (p.get("name", "?"), p.get("revision", "?"))
                for p in profiles
            ] + [self.tr("New profile...")]
            label, ok = QtWidgets.QInputDialog.getItem(
                self,
                self.tr("Scoring profile"),
                self.tr("Use profile"),
                labels,
                0,
                False,
            )
            if not ok:
                return
            if label != self.tr("New profile..."):
                profile = profiles[labels.index(label)]
        if profile is None:
            try:
                dialog = DlgScoringProfile(job, self)
            except (OSError, ValueError) as exc:
                QtWidgets.QMessageBox.critical(
                    self, self.tr("Cannot use input"), str(exc)
                )
                return
            if dialog.exec() != QtWidgets.QDialog.Accepted or dialog.profile is None:
                return
            profile = dialog.profile
        self.entries.append(
            {
                "kind": "managed",
                "job_id": str(job.id),
                "profile": profile,
                "arr_class": "avoid",
                "weight": 1.0,
                "enabled": True,
            }
        )
        self._refresh()

    def _add(self):
        dialog = DlgPriorityCriterion(self)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self.entries.append(
                {"kind": "file", "criterion": dialog.criterion, "enabled": True}
            )
            self._refresh()

    def _remove(self):
        index = self.criteria_table.currentRow()
        if index >= 0:
            del self.entries[index]
            self._refresh()

    def _browse(self, widget):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr("Optional spatial input"),
            "",
            self.tr("Spatial files (*.tif *.tiff *.vrt *.gpkg *.shp *.geojson)"),
        )
        if path:
            widget.setText(path)

    def _load_settings(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, self.tr("Load priority settings"), "", self.tr("JSON (*.json)")
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as source:
                settings = json.load(source)
            if "entries" in settings:
                entries = settings["entries"]
            else:
                # Legacy settings carried bare criterion dicts: convert them to
                # advanced file entries without changing weights or classes.
                from te_algorithms.gdal.land_deg.ldn_priority import validate_criteria

                entries = [
                    {"kind": "file", "criterion": criterion, "enabled": True}
                    for criterion in validate_criteria(settings["criteria"])
                ]
            self.entries = entries
            for key, widget in self.paths.items():
                widget.setText(settings.get(key) or "")
            self._apply_zones_source(settings.get("zones_source"))
            self._pending_land_type_job_id = settings.get("land_type_job_id")
            index = self.combo_land_types.findData(self._pending_land_type_job_id)
            if index >= 0:
                self.combo_land_types.setCurrentIndex(index)
                self._pending_land_type_job_id = None
            self._refresh()
        except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
            QtWidgets.QMessageBox.critical(
                self, self.tr("Cannot load settings"), str(exc)
            )

    def _save_settings(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, self.tr("Save priority settings"), "", self.tr("JSON (*.json)")
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as target:
                json.dump(self._settings(), target, indent=2, allow_nan=False)
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.critical(
                self, self.tr("Cannot save settings"), str(exc)
            )

    def _settings(self):
        settings = {
            "entries": self.entries,
            "zones_source": self._zones_source(),
            "land_type_job_id": self.combo_land_types.currentData(),
            **{
                key: widget.text().strip() or None for key, widget in self.paths.items()
            },
        }
        if getattr(self, "project_inputs", None):
            state = self.project_inputs["state"]
            context = state["context"]
            settings["land_type_job_id"] = (
                (state["selections"].get("land_types") or {}).get("job_id")
                if context["breakdown"] == "saved"
                else None
            )
            settings["zones_source"] = {
                "none": "none",
                "file": "file",
                "admin": "admin_level_1",
            }[context["jurisdictions"]]
            settings["zones_path"] = context["jurisdictions_path"]
        return settings

    def _build_criteria(self) -> typing.List[dict]:
        from .ldn_planning_assets import build_criterion

        criteria = []
        for entry in self.entries:
            if not entry.get("enabled", True):
                continue
            if entry["kind"] == "managed":
                job = self._find_input_job(entry["job_id"])
                if job is None:
                    raise ValueError(
                        self.tr(
                            "Input %s is no longer available. Re-import it or "
                            "remove the criterion."
                        )
                        % entry["job_id"]
                    )
                criteria.append(
                    build_criterion(
                        job,
                        entry["profile"],
                        entry.get("arr_class", "avoid"),
                        float(entry.get("weight", 1)),
                    )
                )
            else:
                criteria.append(dict(entry["criterion"]))
        return criteria

    def btn_calculate(self):
        if not super().btn_calculate():
            return
        info = self.combo_arr.get_current_band()
        try:
            from .ldn_planning_actions import validate_project_dialog

            validate_project_dialog(self)
            if getattr(self, "project_inputs", None):
                selected_id = self.project_inputs["state"]["selections"]["arr"][
                    "job_id"
                ]
                info = next(
                    (
                        band
                        for band in self.combo_arr.layer_list
                        if str(band.job.id) == selected_id
                    ),
                    None,
                )
            if info is None:
                raise ValueError(self.tr("Select an ARR classification layer."))
            if self.combo_land_types.currentIndex() < 0:
                raise ValueError(
                    self.tr("Choose land types or select no land-type summaries.")
                )
            from te_algorithms.gdal.land_deg.ldn_priority import validate_criteria

            settings = self._settings()
            criteria = validate_criteria(self._build_criteria())
            exclusion = settings["exclusion_path"]
            if exclusion and not Path(exclusion).is_file():
                raise ValueError(self.tr("The exclusion raster does not exist."))
            zones_path = None
            if settings["zones_source"] == "file":
                zones_path = settings["zones_path"]
                if not zones_path or not Path(zones_path).is_file():
                    raise ValueError(
                        self.tr("Choose an existing polygon layer for jurisdictions.")
                    )
            land_type_path = None
            land_type_labels = None
            land_type_job_id = settings["land_type_job_id"]
            if land_type_job_id is not None:
                land_type_job = next(
                    (
                        job
                        for job in self._land_types_jobs
                        if str(job.id) == land_type_job_id
                    ),
                    None,
                )
                if land_type_job is None:
                    raise ValueError(
                        self.tr("The selected land-types dataset is unavailable.")
                    )
                land_type_path, land_type_result = job_raster_path(land_type_job)
                units = (
                    (getattr(land_type_result, "data", None) or {}).get(
                        "land_types_key"
                    )
                    or {}
                ).get("units", {})
                land_type_labels = {
                    str(key): unit.get("label", str(key))
                    for key, unit in units.items()
                    if isinstance(unit, dict)
                }
        except (ValueError, ImportError) as exc:
            QtWidgets.QMessageBox.critical(self, self.tr("Cannot prioritize"), str(exc))
            return
        if settings["zones_source"] == "admin_level_1":
            # Shows its own error dialogs and returns None on failure.
            from .calculate_ldn_planning import _resolve_admin_zones

            zones_path = _resolve_admin_zones(self)
            if zones_path is None:
                return
        params = dict(
            settings,
            criteria=criteria,
            zones_path=zones_path,
            land_type_path=land_type_path,
            land_type_labels=land_type_labels,
            task_name=self.execution_name_le.text(),
            task_notes=self.task_notes.toPlainText(),
            arr_layer_path=str(info.path),
            arr_band_index=info.band_index,
            arr_job_id=str(info.job.id),
        )
        self._store_draft()
        self.close()
        job_manager.submit_local_job_as_qgstask(
            params, script_name=self.LOCAL_SCRIPT_NAME, area_of_interest=self.aoi
        )


class DlgCalculateLDNPlanningSelection(DlgCalculateBase):
    LOCAL_SCRIPT_NAME = "ldn-planning-selection"

    def __init__(self, iface, script, parent=None):
        super().__init__(iface, script, parent)
        layout = QtWidgets.QVBoxLayout()
        self.combo_priority = QtWidgets.QComboBox()
        layout.addWidget(QtWidgets.QLabel(self.tr("Priority preview dataset")))
        layout.addWidget(self.combo_priority)
        self.rows = {}
        self.preview_labels = {}
        for key, label in (
            ("avoid", self.tr("Avoid")),
            ("reduce", self.tr("Reduce")),
            ("reverse", self.tr("Reverse")),
        ):
            inner = _make_group(label, layout)
            enabled = QtWidgets.QCheckBox(self.tr("Select candidate areas"))
            mode = QtWidgets.QComboBox()
            mode.addItem(
                self.tr("Keep every pixel at or above a minimum score"), "threshold"
            )
            mode.addItem(self.tr("Keep the best pixels up to a maximum area"), "area")
            threshold_label = QtWidgets.QLabel(self.tr("Minimum priority score (0-1)"))
            threshold = QtWidgets.QDoubleSpinBox()
            threshold.setRange(0, 1)
            threshold.setDecimals(6)
            threshold.setValue(0.8)
            area_label = QtWidgets.QLabel(self.tr("Maximum physical area (km²)"))
            area = QtWidgets.QDoubleSpinBox()
            area.setRange(0, 1e9)
            area.setDecimals(6)
            area.setValue(100)
            for widget in (enabled, mode, threshold_label, threshold, area_label, area):
                inner.addWidget(widget)

            def _mode_changed(
                index=None,
                mode=mode,
                threshold_label=threshold_label,
                threshold=threshold,
                area_label=area_label,
                area=area,
            ):
                by_area = mode.currentData() == "area"
                threshold_label.setVisible(not by_area)
                threshold.setVisible(not by_area)
                area_label.setVisible(by_area)
                area.setVisible(by_area)

            mode.currentIndexChanged.connect(_mode_changed)
            _mode_changed()
            self.rows[key] = (enabled, mode, threshold, area)
            preview = QtWidgets.QLabel("")
            preview.setWordWrap(True)
            inner.addWidget(preview)
            self.preview_labels[key] = preview
        preview_button = QtWidgets.QPushButton(
            self.tr("Preview estimated selection sizes")
        )
        preview_button.clicked.connect(self._preview_selection)
        layout.addWidget(preview_button)
        note = QtWidgets.QLabel(
            self.tr(
                "Threshold selection includes all scored pixels at or above the threshold. "
                "Area selection ranks by score with deterministic ties and does not exceed "
                "the physical-area limit. Inspect the output map and selected-area "
                "report, then configure desired areas as scenario targets in the "
                "LDN Planning tab. This step does not modify existing scenario drafts."
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.execution_name_le, self.task_notes = _add_task_name_notes(
            layout, "LDN Planning - Candidate areas"
        )
        self.region_la, self.region_button = _add_region_buttons(layout)
        left = QtWidgets.QWidget()
        left.setLayout(layout)
        self.splitter, self.button_box = _build_splitter_with_ok_cancel(
            self,
            left,
            self.tr(
                "<h3>Select candidate areas</h3>"
                "<p>Choose a priority preview and enable the response classes "
                "to select. Set a minimum score or a maximum area for each class.</p>"
                "<p>Inspect the resulting map and selected-area report. Add "
                "desired areas as scenario targets in the LDN Planning tab.</p>"
                "<p><a href='https://docs.trends.earth/en/latest/for_users/training/ldnplanning.html'>"
                "LDN planning tutorial</a></p>"
            ),
        )
        self._finish_initialization()
        self.setWindowTitle(self.tr("LDN Planning - Select candidate areas"))
        self.resize(650, 750)

    def showEvent(self, event):
        super().showEvent(event)
        selections = getattr(self, "preselect_selections", None)
        if selections is not None:
            self.preselect_selections = None
            try:
                for key, (enabled, mode, threshold, area) in self.rows.items():
                    selected = selections.get(key)
                    enabled.setChecked(selected is not None)
                    if selected is not None:
                        index = mode.findData(selected["mode"])
                        if index < 0:
                            raise ValueError(
                                self.tr("Unknown candidate selection mode.")
                            )
                        mode.setCurrentIndex(index)
                        threshold.setValue(selected["threshold"])
                        area.setValue(selected["area_km2"])
            except (KeyError, TypeError, ValueError) as exc:
                for enabled, _mode, _threshold, _area in self.rows.values():
                    enabled.setChecked(False)
                QtWidgets.QMessageBox.warning(
                    self,
                    self.tr("Settings unavailable"),
                    self.tr("Cannot restore candidate settings: %s") % str(exc),
                )
        preselect = getattr(self, "preselect_priority_job_id", None)
        previous = preselect or self.combo_priority.currentData()
        self.preselect_priority_job_id = None
        self.jobs = planning_raster_jobs("ldn-planning-priority")
        self.combo_priority.clear()
        for job in self.jobs:
            self.combo_priority.addItem(job.task_name or str(job.id), str(job.id))
        if previous is not None:
            index = self.combo_priority.findData(previous)
            if index >= 0:
                self.combo_priority.setCurrentIndex(index)
            elif preselect:
                self.combo_priority.setCurrentIndex(-1)
                QtWidgets.QMessageBox.warning(
                    self,
                    self.tr("Dataset unavailable"),
                    self.tr(
                        "The selected priority preview is unavailable. Choose another."
                    ),
                )
        if getattr(self, "project_inputs", None):
            self.combo_priority.hide()
            self.region_button.hide()
            self.region_la.hide()

    def _preview_selection(self):
        """Sampled per-class estimate of selection size; the run stays exact."""
        from te_algorithms.gdal.land_deg.ldn_priority_inputs import estimate_selection

        index = self.combo_priority.currentIndex()
        if index < 0 or not self.jobs:
            QtWidgets.QMessageBox.information(
                self,
                self.tr("No priority preview"),
                self.tr("First create and choose a priority preview dataset."),
            )
            return
        job = self.jobs[index]
        try:
            path, result = job_raster_path(job)
        except ValueError as exc:
            QtWidgets.QMessageBox.critical(self, self.tr("Cannot preview"), str(exc))
            return
        class_stats = (
            (result.data or {}).get("report", {}).get("summary", {}).get("classes", {})
        )
        for band_index, key in enumerate(CLASSES, start=1):
            enabled, mode, threshold, area = self.rows[key]
            label = self.preview_labels[key]
            if not enabled.isChecked():
                label.setText("")
                continue
            scored = class_stats.get(key, {}).get("scored_area_km2")
            try:
                estimate = estimate_selection(
                    path,
                    band_index,
                    mode.currentData(),
                    threshold.value(),
                    area.value(),
                    scored,
                )
            except (ValueError, OSError) as exc:
                label.setText(self.tr("Preview failed: %s") % exc)
                continue
            if not estimate["has_scores"]:
                label.setText(
                    self.tr("No scored pixels found for this class in the sample.")
                )
                continue
            parts = []
            if estimate.get("selected_area_km2") is not None:
                parts.append(
                    self.tr("≈ %.1f of %.1f scored km² selected")
                    % (estimate["selected_area_km2"], scored)
                )
            elif estimate.get("selected_fraction") is not None:
                parts.append(
                    self.tr("≈ %.0f%% of scored pixels selected")
                    % (100 * estimate["selected_fraction"])
                )
            else:
                parts.append(
                    self.tr(
                        "Scored area unknown for this dataset; rerun the "
                        "priority preview to enable area estimates."
                    )
                )
            if estimate.get("binding_score") is not None:
                parts.append(
                    self.tr("area cap binds near score %.3f")
                    % estimate["binding_score"]
                )
            label.setText(
                self.tr("Sampled estimate: %s. The final run is exact.")
                % "; ".join(parts)
            )

    def btn_calculate(self):
        if not super().btn_calculate():
            return
        try:
            from .ldn_planning_actions import validate_project_dialog

            validate_project_dialog(self)
            index = self.combo_priority.currentIndex()
            if index < 0:
                raise ValueError(self.tr("First create a priority preview dataset."))
            if getattr(self, "project_inputs", None):
                selected_id = self.project_inputs["state"]["selections"]["priority"][
                    "job_id"
                ]
                job = next(
                    (job for job in self.jobs if str(job.id) == selected_id), None
                )
                if job is None:
                    raise ValueError(
                        self.tr("The project's priority preview is unavailable.")
                    )
            else:
                job = self.jobs[index]
            path, _ = job_raster_path(job)
            if not job_manager.ensure_params_loaded(job):
                raise ValueError(
                    self.tr("Priority settings are missing from this dataset.")
                )
            selections = {}
            for key, (enabled, mode, threshold, area) in self.rows.items():
                if enabled.isChecked():
                    selections[key] = {
                        "mode": mode.currentData(),
                        "threshold": threshold.value(),
                        "area_km2": area.value(),
                    }
            if not selections:
                raise ValueError(self.tr("Select at least one ARR class."))
        except ValueError as exc:
            QtWidgets.QMessageBox.critical(
                self, self.tr("Cannot select areas"), str(exc)
            )
            return
        params = dict(
            task_name=self.execution_name_le.text(),
            task_notes=self.task_notes.toPlainText(),
            score_path=path,
            selections=selections,
            priority_job_id=str(job.id),
            priority_params=job.params,
        )
        self.close()
        job_manager.submit_local_job_as_qgstask(
            params, script_name=self.LOCAL_SCRIPT_NAME, area_of_interest=self.aoi
        )
