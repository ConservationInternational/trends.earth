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
        form.addRow(self.tr("Relative importance within this class"), self.weight)
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
    TABLE_HEADERS = (
        "Use",
        "Criterion and scoring rule",
        "Relative importance",
        "Actions",
    )

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
        self.project_context_label = QtWidgets.QLabel()
        self.project_context_label.setWordWrap(True)
        self.project_context_label.hide()
        inner.addWidget(self.project_context_label)
        self.change_project_button = QtWidgets.QPushButton(self.tr("Change in project"))
        self.change_project_button.clicked.connect(self._change_project_inputs)
        self.change_project_button.hide()
        inner.addWidget(self.change_project_button)
        self.combo_arr = data_io.WidgetDataIOSelectTELayerExisting()
        self.combo_arr.setProperty("layer_type", "LDN Planning - Avoid/Reduce/Reverse")
        inner.addWidget(self.combo_arr)
        criteria_group = _make_group(self.tr("Rank within each ARR class"), layout)
        explanation = QtWidgets.QLabel(
            self.tr(
                "ARR determines which locations are eligible for Avoid, Reduce, "
                "or Reverse. Criteria rank locations within a class; they do not "
                "change ARR classes. Each class gets its own priority score."
            )
        )
        explanation.setWordWrap(True)
        criteria_group.addWidget(explanation)
        self.criteria_tables = {}
        self.class_status_labels = {}
        class_labels = {
            "avoid": self.tr("Avoid - protect non-degraded land"),
            "reduce": self.tr("Reduce - manage at-risk non-degraded land"),
            "reverse": self.tr("Reverse - restore degraded land"),
        }
        for arr_class in CLASSES:
            class_box = QtWidgets.QGroupBox(class_labels[arr_class])
            class_layout = QtWidgets.QVBoxLayout(class_box)
            status = QtWidgets.QLabel()
            status.setWordWrap(True)
            self.class_status_labels[arr_class] = status
            class_layout.addWidget(status)
            table = QtWidgets.QTableWidget(0, len(self.TABLE_HEADERS))
            table.setHorizontalHeaderLabels(
                [self.tr(header) for header in self.TABLE_HEADERS]
            )
            table.horizontalHeader().setStretchLastSection(True)
            table.horizontalHeader().setSectionResizeMode(
                1, QtWidgets.QHeaderView.Stretch
            )
            table.horizontalHeader().setSectionResizeMode(
                3, QtWidgets.QHeaderView.ResizeToContents
            )
            table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            table.setMinimumHeight(72)
            self.criteria_tables[arr_class] = table
            class_layout.addWidget(table)
            row = QtWidgets.QHBoxLayout()
            add_menu = QtWidgets.QMenu(self)
            add_menu.addAction(
                self.tr("Add imported input..."),
                lambda checked=False, key=arr_class: self._add_managed(key),
            )
            add_menu.addAction(
                self.tr("Import dataset..."),
                lambda checked=False, key=arr_class: self._import_input(key),
            )
            add_button = QtWidgets.QPushButton(
                self.tr("Add criterion to %s...") % arr_class.title()
            )
            add_button.setMenu(add_menu)
            row.addWidget(add_button)
            equal_button = QtWidgets.QPushButton(self.tr("Set equal importance"))
            equal_button.clicked.connect(
                lambda checked=False, key=arr_class: self._set_equal_importance(key)
            )
            row.addWidget(equal_button)
            class_layout.addLayout(row)
            criteria_group.addWidget(class_box)
        more_menu = QtWidgets.QMenu(self)
        more_menu.addAction(self.tr("Advanced: add from file..."), self._add)
        more_menu.addAction(self.tr("Import settings..."), self._load_settings)
        more_menu.addAction(self.tr("Export settings..."), self._save_settings)
        more_button = QtWidgets.QPushButton(self.tr("More"))
        more_button.setMenu(more_menu)
        criteria_group.addWidget(more_button)
        weight_note = QtWidgets.QLabel(
            self.tr(
                "Relative importance is normalized within each class. Only "
                "the ratios matter: weights 2 and 1 contribute about 67% and "
                "33%. A single active criterion contributes 100%, whatever "
                "its positive weight. Priority is not intervention effectiveness."
            )
        )
        weight_note.setWordWrap(True)
        criteria_group.addWidget(weight_note)
        optional = _make_group(self.tr("Optional exclusions and breakdowns"), layout)
        optional_box = layout.itemAt(layout.count() - 1).widget()
        optional_box.setCheckable(True)
        optional_box.setChecked(False)
        optional_box.toggled.connect(
            lambda checked: [
                widget.setVisible(checked)
                for widget in optional_box.findChildren(
                    QtWidgets.QWidget,
                    options=QtCore.Qt.FindChildOption.FindDirectChildrenOnly,
                )
            ]
        )
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
        optional.addWidget(QtWidgets.QLabel(label))
        optional.addLayout(row)
        self.land_types_label = QtWidgets.QLabel(
            self.tr("Land-type summaries (optional)")
        )
        optional.addWidget(self.land_types_label)
        self.combo_land_types = QtWidgets.QComboBox()
        optional.addWidget(self.combo_land_types)
        self._land_types_jobs: typing.List = []
        self._pending_land_type_job_id = None
        self.jurisdictions_label = QtWidgets.QLabel(
            self.tr("Jurisdiction summaries (optional)")
        )
        optional.addWidget(self.jurisdictions_label)
        self.rb_zones_none = QtWidgets.QRadioButton(
            self.tr("No jurisdiction breakdown")
        )
        self.rb_zones_none.setChecked(True)
        self.rb_zones_admin = QtWidgets.QRadioButton(
            self.tr("Administrative units (level 1) of the selected country")
        )
        self.rb_zones_file = QtWidgets.QRadioButton(self.tr("Upload a polygon layer"))
        for radio in (self.rb_zones_none, self.rb_zones_admin, self.rb_zones_file):
            optional.addWidget(radio)
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
        optional.addLayout(row)
        zones_edit.setEnabled(False)
        self.btn_zones_browse.setEnabled(False)
        self.rb_zones_file.toggled.connect(zones_edit.setEnabled)
        self.rb_zones_file.toggled.connect(self.btn_zones_browse.setEnabled)
        if not optional_box.isChecked():
            for widget in optional_box.findChildren(
                QtWidgets.QWidget,
                options=QtCore.Qt.FindChildOption.FindDirectChildrenOnly,
            ):
                widget.hide()
        note = QtWidgets.QLabel(
            self.tr(
                "ARR determines eligibility. Criteria combine into a relative "
                "priority score separately within Avoid, Reduce, and Reverse; "
                "scores are not comparable across classes or probabilities of "
                "success. Missing data for any positive-importance criterion "
                "remain unscored. Ranking creates a priority map, not candidate "
                "areas or scenario targets. Candidate selection and expected "
                "effectiveness are separate steps. Your configuration is kept "
                "as a draft between sessions."
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.execution_name_le, self.task_notes = _add_task_name_notes(
            layout, "LDN Planning - Intervention priorities"
        )
        self.region_la, self.region_button = _add_region_buttons(layout)
        left = QtWidgets.QWidget()
        left.setLayout(layout)
        self.splitter, self.button_box = _build_splitter_with_ok_cancel(
            self,
            left,
            self.tr(
                "<h3>Rank intervention areas</h3>"
                "<p>ARR determines where each response applies. Criteria rank "
                "locations within Avoid, Reduce, or Reverse; they do not change "
                "the ARR class. Each class receives a separate 0-1 relative "
                "priority score.</p>"
                "<p>Relative importance is normalized within its class. Only "
                "the ratios matter; a single active criterion is 100% of that "
                "class regardless of its positive weight. Missing required "
                "criterion data remain unscored.</p>"
                "<p>Candidate selection chooses locations from a ranking. A "
                "scenario then uses selected targets and your expected "
                "effectiveness assumptions.</p>"
                "<p><a href='https://docs.trends.earth/en/latest/for_users/training/ldnplanning.html'>"
                "LDN planning tutorial</a></p>"
            ),
        )
        self._finish_initialization()
        self.button_box.button(QtWidgets.QDialogButtonBox.Ok).setText(
            self.tr("Create ranking")
        )
        self.setWindowTitle(self.tr("Rank intervention areas"))
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
            self.combo_arr.hide()
            self.combo_land_types.hide()
            self.land_types_label.hide()
            self.region_button.hide()
            self.region_la.hide()
            state = self.project_inputs["state"]
            context = state["context"]
            panel = self.project_inputs["panel"]
            arr = panel._selected("arr")
            land_types = panel._selected("land_types")
            self.project_context_label.setText(
                self.tr("Using project inputs — ARR: %s; land types: %s")
                % (
                    arr.task_name if arr is not None else self.tr("Not selected"),
                    land_types.task_name if land_types is not None else self.tr("None"),
                )
            )
            self.project_context_label.show()
            self.change_project_button.show()
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

    def _change_project_inputs(self):
        project_inputs = getattr(self, "project_inputs", None)
        if project_inputs is None:
            return
        project_inputs["panel"]._focus_section("prepare")
        self.reject()

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

    def _entry_details(self, entry) -> tuple[str, str, str, str]:
        from . import ldn_planning_assets

        if entry["kind"] == "managed":
            job = self._find_input_job(entry["job_id"])
            input_name = (
                ldn_planning_assets.input_display_name(job)
                if job is not None
                else self.tr("Missing input %s — relink or re-import") % entry["job_id"]
            )
            profile = entry["profile"]
            profile_name = (
                f"{profile.get('name', '?')} (rev {profile.get('revision', '?')})"
            )
            if job is not None:
                try:
                    path = ldn_planning_assets.input_path(job)
                except (OSError, ValueError) as exc:
                    path = self.tr("Unavailable: %s") % exc
            else:
                path = ""
            settings = profile
            provenance = job.params.get("provenance") or {} if job is not None else {}
            if not isinstance(provenance, dict):
                provenance = {}
        else:
            criterion = entry["criterion"]
            input_name = self.tr("Direct file")
            profile_name = criterion.get("name", "?")
            path = criterion.get("path", "")
            settings = criterion
            provenance = criterion

        if settings.get("field"):
            band_or_field = self.tr("Field: %s") % settings["field"]
        else:
            band_or_field = self.tr("Band %s") % settings.get("band_index", 1)
        if settings.get("categories"):
            category_count = len(settings["categories"])
            scoring = self.tr("%d categories scored; others remain unscored") % (
                category_count
            )
        else:
            direction = settings.get("direction", "higher")
            if direction == "lower":
                preference = self.tr("lower values preferred")
            else:
                preference = self.tr("higher values preferred")
            minimum = settings.get("minimum", 0)
            maximum = settings.get("maximum", 1)
            scoring = self.tr("%s; range %s to %s, values outside are clamped") % (
                preference,
                minimum,
                maximum,
            )
        summary = f"{band_or_field}; {scoring}"
        details = "\n".join(
            (
                self.tr("Input: %s") % input_name,
                self.tr("Scoring rule: %s") % profile_name,
                self.tr("Source: %s") % (path or self.tr("Unavailable")),
                self.tr("ARR class: %s") % self._entry_class(entry).title(),
                self.tr("Relative importance: %s") % self._entry_weight(entry),
                self.tr("Scoring: %s") % summary,
                self.tr("Source / attribution: %s")
                % provenance.get("source", self.tr("Not specified")),
                self.tr("Dataset date: %s")
                % provenance.get("date", self.tr("Not specified")),
                self.tr("Units: %s")
                % provenance.get("units", self.tr("Not specified")),
                self.tr("License / usage rights: %s")
                % provenance.get("license", self.tr("Not specified")),
            )
        )
        return input_name, profile_name, summary, details

    def _find_input_job(self, job_id: str):
        for job in job_manager.get_planning_input_jobs():
            if str(job.id) == str(job_id):
                return job
        return None

    def _refresh(self):
        for table in self.criteria_tables.values():
            table.setRowCount(0)
        for index, entry in enumerate(self.entries):
            arr_class = self._entry_class(entry)
            table = self.criteria_tables[arr_class]
            row = table.rowCount()
            table.insertRow(row)
            enabled = QtWidgets.QCheckBox()
            enabled.setAccessibleName(self.tr("Use criterion in ranking"))
            enabled.setChecked(entry.get("enabled", True))
            enabled.toggled.connect(
                lambda checked, i=index: self._entry_changed(i, enabled=checked)
            )
            table.setCellWidget(row, 0, enabled)
            _input_name, profile_name, summary, details = self._entry_details(entry)
            criterion_label = QtWidgets.QLabel(
                f"{_input_name}\n{summary}; {profile_name}"
            )
            criterion_label.setWordWrap(True)
            criterion_label.setToolTip(details)
            table.setCellWidget(row, 1, criterion_label)
            weight = QtWidgets.QDoubleSpinBox()
            weight.setRange(0, 1e6)
            weight.setDecimals(3)
            weight.setValue(self._entry_weight(entry))
            weight.setEnabled(entry.get("enabled", True))
            weight.setToolTip(
                self.tr(
                    "Relative importance within this ARR class; only weight "
                    "ratios within the class affect its score."
                )
            )
            weight.valueChanged.connect(
                lambda value, i=index: self._entry_changed(i, weight=value)
            )
            share = QtWidgets.QLabel()
            share.setWordWrap(True)
            share_layout = QtWidgets.QVBoxLayout()
            share_layout.setContentsMargins(2, 0, 2, 0)
            share_layout.addWidget(weight)
            share_layout.addWidget(share)
            share_widget = QtWidgets.QWidget()
            share_widget.setLayout(share_layout)
            table.setCellWidget(row, 2, share_widget)
            table.setItem(row, 0, QtWidgets.QTableWidgetItem())
            table.item(row, 0).setData(QtCore.Qt.UserRole, index)
            actions = QtWidgets.QToolButton()
            actions.setText(self.tr("Actions"))
            actions.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            menu = QtWidgets.QMenu(actions)
            menu.addAction(
                self.tr("Details..."),
                lambda checked=False, text=details: QtWidgets.QMessageBox.information(
                    self, self.tr("Criterion details"), text
                ),
            )
            menu.addAction(
                self.tr("Create new scoring-rule revision...")
                if entry["kind"] == "managed"
                else self.tr("Edit scoring..."),
                lambda checked=False, i=index: self._edit_entry(i),
            )
            move_menu = menu.addMenu(self.tr("Move to..."))
            for other_class in CLASSES:
                if other_class == arr_class:
                    continue
                move_menu.addAction(
                    self.tr(other_class.title()),
                    lambda checked=False, i=index, key=other_class: self._move_entry(
                        i, key
                    ),
                )
            menu.addAction(
                self.tr("Remove"),
                lambda checked=False, i=index: self._remove_entry(i),
            )
            actions.setMenu(menu)
            table.setCellWidget(row, 3, actions)
            table.setRowHeight(row, 68)

        for arr_class, table in self.criteria_tables.items():
            class_entries = [
                entry for entry in self.entries if self._entry_class(entry) == arr_class
            ]
            active = [entry for entry in class_entries if entry.get("enabled", True)]
            positive = [entry for entry in active if self._entry_weight(entry) > 0]
            if not active:
                text = self.tr(
                    "No ranking for this class. Add a criterion to score and select "
                    "locations for this response."
                )
            elif not positive:
                text = self.tr(
                    "No positive relative importance. Increase at least one active "
                    "criterion above zero to create a ranking."
                )
            else:
                text = self.tr(
                    "%d active criteria. Their preferences are combined only within "
                    "this class. Locations missing any positive-weight criterion "
                    "remain unscored."
                ) % len(active)
            self.class_status_labels[arr_class].setText(text)
        self._update_weight_shares()

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
        if enabled is not None:
            self._refresh()
        else:
            self._update_weight_shares()

    def _update_weight_shares(self):
        totals: dict[str, float] = {}
        positive_counts: dict[str, int] = {}
        for entry in self.entries:
            if entry.get("enabled", True) and self._entry_weight(entry) > 0:
                arr_class = self._entry_class(entry)
                totals[arr_class] = totals.get(arr_class, 0.0) + self._entry_weight(
                    entry
                )
                positive_counts[arr_class] = positive_counts.get(arr_class, 0) + 1
        for arr_class, table in self.criteria_tables.items():
            for row in range(table.rowCount()):
                index = table.item(row, 0).data(QtCore.Qt.UserRole)
                entry = self.entries[index]
                enabled = entry.get("enabled", True)
                weight = self._entry_weight(entry)
                if not enabled:
                    text = self.tr("Not used")
                elif weight <= 0:
                    text = self.tr("No score contribution")
                elif positive_counts.get(arr_class) == 1:
                    text = self.tr("Only active criterion: 100% of this class score")
                else:
                    total = totals.get(arr_class, 0.0)
                    text = self.tr("%d%% of this class score") % round(
                        100 * weight / total
                    )
                table.cellWidget(row, 2).findChildren(QtWidgets.QLabel)[0].setText(text)
                table.cellWidget(row, 2).findChild(QtWidgets.QDoubleSpinBox).setEnabled(
                    enabled
                )

    def _set_equal_importance(self, arr_class):
        for entry in self.entries:
            if self._entry_class(entry) == arr_class and entry.get("enabled", True):
                if entry["kind"] == "managed":
                    entry["weight"] = 1.0
                else:
                    entry["criterion"]["weight"] = 1.0
        self._refresh()

    # ------------------------------------------------------------------
    # Adding and removing criteria
    # ------------------------------------------------------------------

    def _import_input(self, arr_class="avoid"):
        from .ldn_planning_assets import DlgImportPlanningInput

        dialog = DlgImportPlanningInput(self)
        if dialog.exec() == QtWidgets.QDialog.Accepted and dialog.job is not None:
            self._configure_entry_for_job(dialog.job, arr_class)

    def _add_managed(self, arr_class="avoid"):
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
        self._configure_entry_for_job(inputs[labels.index(label)], arr_class)

    def _configure_entry_for_job(self, job, arr_class="avoid"):
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
        duplicate = any(
            entry["kind"] == "managed"
            and entry.get("enabled", True)
            and str(entry.get("job_id")) == str(job.id)
            and entry.get("arr_class", "avoid") == arr_class
            and entry.get("profile") == profile
            for entry in self.entries
        )
        if duplicate and (
            QtWidgets.QMessageBox.question(
                self,
                self.tr("Criterion already used"),
                self.tr(
                    "This input and scoring rule are already active in %s. "
                    "Adding it again gives that preference extra importance. "
                    "Add another copy anyway?"
                )
                % arr_class.title(),
            )
            != QtWidgets.QMessageBox.StandardButton.Yes
        ):
            return
        self.entries.append(
            {
                "kind": "managed",
                "job_id": str(job.id),
                "profile": profile,
                "arr_class": arr_class,
                "weight": 1.0,
                "enabled": True,
            }
        )
        self._refresh()

    def _add(self, arr_class=None):
        dialog = DlgPriorityCriterion(self)
        if arr_class is not None:
            dialog.arr_class.setCurrentIndex(CLASSES.index(arr_class))
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self.entries.append(
                {"kind": "file", "criterion": dialog.criterion, "enabled": True}
            )
            self._refresh()

    def _remove(self):
        for table in self.criteria_tables.values():
            row = table.currentRow()
            if row >= 0 and table.item(row, 0) is not None:
                index = table.item(row, 0).data(QtCore.Qt.UserRole)
                self._remove_entry(index)
                return

    def _remove_entry(self, index):
        del self.entries[index]
        self._refresh()

    def _move_entry(self, index, arr_class):
        entry = self.entries[index]
        if entry["kind"] == "managed":
            entry["arr_class"] = arr_class
        else:
            entry["criterion"]["arr_class"] = arr_class
        self._refresh()

    def _edit_entry(self, index):
        entry = self.entries[index]
        if entry["kind"] == "managed":
            from .ldn_planning_assets import DlgScoringProfile

            job = self._find_input_job(entry["job_id"])
            if job is None:
                QtWidgets.QMessageBox.critical(
                    self,
                    self.tr("Cannot edit criterion"),
                    self.tr("The source input is unavailable. Re-import it first."),
                )
                return
            try:
                dialog = DlgScoringProfile(job, self, profile=entry["profile"])
            except (OSError, ValueError) as exc:
                QtWidgets.QMessageBox.critical(
                    self, self.tr("Cannot edit criterion"), str(exc)
                )
                return
            if (
                dialog.exec() == QtWidgets.QDialog.Accepted
                and dialog.profile is not None
            ):
                entry["profile"] = dialog.profile
        else:
            dialog = DlgPriorityCriterion(self, criterion=entry["criterion"])
            if dialog.exec() == QtWidgets.QDialog.Accepted:
                entry["criterion"] = dialog.criterion
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
        source = _make_group(self.tr("Intervention priorities"), layout)
        self.project_context_label = QtWidgets.QLabel()
        self.project_context_label.setWordWrap(True)
        self.project_context_label.hide()
        source.addWidget(self.project_context_label)
        self.change_project_button = QtWidgets.QPushButton(self.tr("Change in project"))
        self.change_project_button.clicked.connect(self._change_project_inputs)
        self.change_project_button.hide()
        source.addWidget(self.change_project_button)
        self.combo_priority = QtWidgets.QComboBox()
        source.addWidget(self.combo_priority)
        self.source_note = QtWidgets.QLabel()
        self.source_note.setText(
            self.tr(
                "Scores are relative only within an ARR class. Candidate selection "
                "chooses locations from this ranking; expected effectiveness is "
                "configured separately in a scenario."
            )
        )
        self.source_note.setWordWrap(True)
        source.addWidget(self.source_note)
        self.rows = {}
        self.estimate_labels = {}
        for key, label in (
            ("avoid", self.tr("Avoid")),
            ("reduce", self.tr("Reduce")),
            ("reverse", self.tr("Reverse")),
        ):
            inner = _make_group(label, layout)
            enabled = QtWidgets.QCheckBox(
                self.tr("Include %s candidate areas") % key.title()
            )
            mode = QtWidgets.QComboBox()
            mode.addItem(
                self.tr("Choose all scored locations meeting a minimum priority score"),
                "threshold",
            )
            mode.addItem(
                self.tr("Choose highest-priority locations up to an area limit"),
                "area",
            )
            threshold_label = QtWidgets.QLabel(
                self.tr("Minimum priority score (0-1; not a percentile)")
            )
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
                enabled=enabled,
                mode=mode,
                threshold_label=threshold_label,
                threshold=threshold,
                area_label=area_label,
                area=area,
            ):
                active = enabled.isChecked()
                by_area = mode.currentData() == "area"
                mode.setVisible(active)
                threshold_label.setVisible(active and not by_area)
                threshold.setVisible(active and not by_area)
                area_label.setVisible(active and by_area)
                area.setVisible(active and by_area)

            mode.currentIndexChanged.connect(_mode_changed)
            enabled.toggled.connect(_mode_changed)
            _mode_changed()
            self.rows[key] = (enabled, mode, threshold, area)
            estimate = QtWidgets.QLabel("")
            estimate.setWordWrap(True)
            inner.addWidget(estimate)
            self.estimate_labels[key] = estimate
        estimate_button = QtWidgets.QPushButton(self.tr("Estimate selected area"))
        estimate_button.clicked.connect(self._estimate_selection)
        layout.addWidget(estimate_button)
        self.estimate_status = QtWidgets.QLabel()
        self.estimate_status.setWordWrap(True)
        layout.addWidget(self.estimate_status)
        self._estimate_signature = None
        self.combo_priority.currentIndexChanged.connect(self._invalidate_estimates)
        for enabled, mode, threshold, area in self.rows.values():
            enabled.toggled.connect(self._invalidate_estimates)
            mode.currentIndexChanged.connect(self._invalidate_estimates)
            threshold.valueChanged.connect(self._invalidate_estimates)
            area.valueChanged.connect(self._invalidate_estimates)
        note = QtWidgets.QLabel(
            self.tr(
                "Scores are relative preferences within each ARR class, not "
                "percentiles or success probabilities. A threshold keeps every "
                "scored pixel at or above the score; an area limit selects the "
                "highest-scoring whole pixels up to that per-class limit. Ties "
                "are deterministic and the actual area can be smaller. Review "
                "the output map and selected area, then explicitly configure "
                "candidate areas as scenario targets and set expected "
                "effectiveness. This step never changes existing scenario drafts."
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
                "<p>ARR determines the eligible response class. The selected "
                "priority map ranks locations only within that class; choose "
                "a minimum priority score or an area limit for each class.</p>"
                "<p>Candidate areas are proposed locations, not scenario targets "
                "or predicted successful area. Review the map, then configure "
                "targets and expected effectiveness in a scenario.</p>"
                "<p><a href='https://docs.trends.earth/en/latest/for_users/training/ldnplanning.html'>"
                "LDN planning tutorial</a></p>"
            ),
        )
        self._finish_initialization()
        self.button_box.button(QtWidgets.QDialogButtonBox.Ok).setText(
            self.tr("Create candidate areas")
        )
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
                    self.tr("The selected intervention priorities are unavailable."),
                )
        if getattr(self, "project_inputs", None):
            selection = self.project_inputs["state"]["selections"].get("priority", {})
            source_job = next(
                (job for job in self.jobs if str(job.id) == selection.get("job_id")),
                None,
            )
            self.project_context_label.setText(
                self.tr("Using project ranking: %s")
                % (
                    source_job.task_name
                    if source_job is not None
                    else self.tr("Unavailable")
                )
            )
            self.project_context_label.show()
            self.change_project_button.show()
            self.combo_priority.hide()
            self.region_button.hide()
            self.region_la.hide()
            self.source_note.setText(
                self.tr(
                    "This source is inherited from the project. Change it in the "
                    "Rank intervention areas section. Scores are relative within "
                    "each ARR class; expected effectiveness is set separately in "
                    "a scenario."
                )
            )

    def _change_project_inputs(self):
        project_inputs = getattr(self, "project_inputs", None)
        if project_inputs is None:
            return
        project_inputs["panel"]._focus_section("ranking")
        self.reject()

    def _invalidate_estimates(self, *_args):
        had_estimate = bool(
            self._estimate_signature is not None
            or any(label.text() for label in self.estimate_labels.values())
        )
        self._estimate_signature = None
        for label in self.estimate_labels.values():
            label.clear()
        self.estimate_status.setText(
            self.tr("Settings changed; estimate again.") if had_estimate else ""
        )

    def _estimate_selection(self):
        """Sampled per-class estimate of selection size; the run stays exact."""
        from te_algorithms.gdal.land_deg.ldn_priority_inputs import estimate_selection

        index = self.combo_priority.currentIndex()
        if index < 0 or not self.jobs:
            QtWidgets.QMessageBox.information(
                self,
                self.tr("No intervention priorities"),
                self.tr("First create and choose intervention priorities."),
            )
            return
        if not any(row[0].isChecked() for row in self.rows.values()):
            QtWidgets.QMessageBox.information(
                self,
                self.tr("No response classes"),
                self.tr("Include at least one response class to estimate its area."),
            )
            return
        job = self.jobs[index]
        try:
            path, result = job_raster_path(job)
        except ValueError as exc:
            QtWidgets.QMessageBox.critical(self, self.tr("Cannot estimate"), str(exc))
            return
        class_stats = (
            (result.data or {}).get("report", {}).get("summary", {}).get("classes", {})
        )
        for band_index, key in enumerate(CLASSES, start=1):
            enabled, mode, threshold, area = self.rows[key]
            label = self.estimate_labels[key]
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
                        "ranking to enable area estimates."
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
        self._estimate_signature = self._current_selection_signature()
        self.estimate_status.setText(
            self.tr("Sampled estimate. The final selection uses the exact algorithm.")
        )

    def _current_selection_signature(self):
        return (
            self.combo_priority.currentData(),
            tuple(
                (
                    key,
                    enabled.isChecked(),
                    mode.currentData(),
                    threshold.value(),
                    area.value(),
                )
                for key, (enabled, mode, threshold, area) in self.rows.items()
            ),
        )

    def btn_calculate(self):
        if not super().btn_calculate():
            return
        try:
            from .ldn_planning_actions import validate_project_dialog

            validate_project_dialog(self)
            index = self.combo_priority.currentIndex()
            if index < 0:
                raise ValueError(self.tr("First create intervention priorities."))
            if getattr(self, "project_inputs", None):
                selected_id = self.project_inputs["state"]["selections"]["priority"][
                    "job_id"
                ]
                job = next(
                    (job for job in self.jobs if str(job.id) == selected_id), None
                )
                if job is None:
                    raise ValueError(
                        self.tr(
                            "The project's intervention priorities are unavailable."
                        )
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
