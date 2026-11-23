"""Integrated LDN planning projects, scenario drafts and immutable results."""

import copy
import json
import math
import uuid
from pathlib import Path

from qgis.PyQt import QtCore, QtWidgets
from te_algorithms.gdal.land_deg.ldn_planning_inputs import area_checksum
from te_schemas.jobs import JobStatus

from .jobs.manager import job_manager
from .ldn_planning_actions import (
    arr_factory,
    land_types_factory,
    launch_calculate_dialog,
    priority_factory,
    selection_factory,
    show_planning_summary,
)

SETTINGS_KEY = "trends_earth/ldn_planning_projects"
RESULTS = (
    ("arr", "ARR classification", "ldn-planning-arr", (1,)),
    ("land_types", "Land types", "ldn-planning-land-types", (1,)),
    ("priority", "Priority preview", "ldn-planning-priority", (1, 2, 3)),
    ("candidate", "Candidate areas", "ldn-planning-selection", (1,)),
    ("scenario", "Scenario", "ldn-planning-projection", (1, 2, 3)),
)
AVAILABLE = (JobStatus.DOWNLOADED, JobStatus.GENERATED_LOCALLY)
AUTO_SELECT_RESULT_KEYS = {
    "ldn-planning-arr": "arr",
    "ldn-planning-land-types": "land_types",
    "ldn-planning-selection": "candidate",
}


def new_draft():
    return {
        "id": str(uuid.uuid4()),
        "targets": [],
        "use_candidates": False,
        "use_polygons": False,
        "task_name": "LDN scenario",
        "task_notes": "",
        "default_effectiveness": 0.8,
        "comparison_job_id": None,
    }


def initialize_project(project):
    project.setdefault(
        "context",
        {
            "breakdown": "saved" if project["selections"].get("land_types") else "none",
            "year_initial": None,
            "year_final": None,
            "target_year": None,
            "jurisdictions": "none",
            "jurisdictions_path": None,
        },
    )
    if "drafts" not in project:
        draft = new_draft()
        project["drafts"] = [draft]
        project["active_draft"] = draft["id"]


def validate_project_state(project):
    context = project.get("context")
    if (
        not isinstance(context, dict)
        or context.get("breakdown") not in ("none", "saved", "land_cover")
        or context.get("jurisdictions") not in ("none", "admin", "file")
        or not isinstance(context.get("jurisdictions_path"), (str, type(None)))
        or any(
            key not in context
            for key in (
                "year_initial",
                "year_final",
                "target_year",
                "jurisdictions_path",
            )
        )
        or any(
            value is not None and (type(value) is not int or not 1980 <= value <= 2100)
            for value in (
                context.get(k) for k in ("year_initial", "year_final", "target_year")
            )
        )
        or not isinstance(project.get("drafts"), list)
        or not project["drafts"]
    ):
        raise ValueError("Invalid project context or scenario drafts.")
    ids = []
    for draft in project["drafts"]:
        if (
            not isinstance(draft, dict)
            or not isinstance(draft.get("id"), str)
            or not isinstance(draft.get("task_name"), str)
            or not isinstance(draft.get("task_notes"), str)
            or type(draft.get("use_candidates")) is not bool
            or type(draft.get("use_polygons")) is not bool
            or not isinstance(draft.get("targets"), list)
            or not isinstance(draft.get("comparison_job_id"), (str, type(None)))
            or not isinstance(draft.get("default_effectiveness"), (int, float))
            or not math.isfinite(draft["default_effectiveness"])
            or not 0 <= draft["default_effectiveness"] <= 1
        ):
            raise ValueError("Invalid scenario draft.")
        for target in draft["targets"]:
            if (
                not isinstance(target, dict)
                or target.get("intervention") not in ("avoid", "reduce", "reverse")
                or not isinstance(target.get("effectiveness"), (int, float))
                or not math.isfinite(target["effectiveness"])
                or not 0 <= target["effectiveness"] <= 1
                or not (target.get("selected_mask_path") or target.get("wkt_geometry"))
                or (
                    target.get("selected_mask_path") is not None
                    and not isinstance(target["selected_mask_path"], str)
                )
                or (
                    target.get("wkt_geometry") is not None
                    and not isinstance(target["wkt_geometry"], str)
                )
                or ("approved" in target and type(target["approved"]) is not bool)
                or (
                    "approval_context" in target
                    and not isinstance(target["approval_context"], dict)
                )
                or (
                    "configuration_context" in target
                    and not isinstance(target["configuration_context"], dict)
                )
                or (
                    "configured_effectiveness" in target
                    and (
                        not isinstance(target["configured_effectiveness"], (int, float))
                        or not math.isfinite(target["configured_effectiveness"])
                        or not 0 <= target["configured_effectiveness"] <= 1
                    )
                )
            ):
                raise ValueError("Invalid draft target.")
        ids.append(draft["id"])
    if len(ids) != len(set(ids)) or project.get("active_draft") not in ids:
        raise ValueError("Invalid active scenario draft.")


def current_area():
    """Fingerprint the actual analysis geometry, not just its display name."""
    from .areaofinterest import prepare_area_of_interest
    from .conf import Setting, settings_manager

    aoi = prepare_area_of_interest(show_errors=False)
    if aoi is None:
        raise ValueError("Select a valid area of interest in Trends.Earth settings.")
    return {
        "name": settings_manager.get_value(Setting.AREA_NAME) or "",
        "sha256": area_checksum(aoi.get_geojson()),
    }


def baseline_bands():
    from te_algorithms.gdal.land_deg import config as ld_config

    from .areaofinterest import try_prepare_area_of_interest
    from .data_io import _get_usable_bands

    aoi = try_prepare_area_of_interest(use_cache=False)
    if aoi is None:
        return []
    return _get_usable_bands(
        band_name=(ld_config.SDG_BAND_NAME, ld_config.SDG_STATUS_BAND_NAME), aoi=aoi
    )


def band_period(band, reporting=False):
    """Return the (start, end) years recorded in an SDG band's metadata.

    Indicator bands record ``year_initial``/``year_final``. Status bands
    compare a reporting period against the baseline, so they span the
    baseline start to the baseline end (or the reporting end for reporting).
    Degraded classes in either band are cumulative over this period.
    """
    if band is None:
        return None
    metadata = getattr(getattr(band, "band_info", band), "metadata", None)
    if not isinstance(metadata, dict):
        return None
    end_key = "reporting_year_final" if reporting else "baseline_year_final"
    years = []
    for keys in (
        ("year_initial", "baseline_year_initial"),
        ("year_final", end_key),
    ):
        value = next((metadata[k] for k in keys if metadata.get(k) is not None), None)
        if isinstance(value, bool):
            return None
        try:
            year = int(value)
            if year != float(value):
                return None
        except (TypeError, ValueError):
            return None
        years.append(year)
    start, end = years
    if not 1980 <= start < end < 2100:
        return None
    return start, end


def load_projects(settings):
    raw = settings.value(SETTINGS_KEY, "")
    if not raw:
        return {"version": 2, "projects": [], "current": None}
    try:
        data = json.loads(raw)
        if (
            not isinstance(data, dict)
            or data.get("version") not in (1, 2)
            or "current" not in data
            or not isinstance(data["current"], (str, type(None)))
            or not isinstance(data.get("projects"), list)
            or any(
                not isinstance(project, dict)
                or not isinstance(project.get("id"), str)
                or not isinstance(project.get("name"), str)
                or not isinstance(project.get("area"), dict)
                or not isinstance(project["area"].get("sha256"), str)
                or not isinstance(project.get("selections"), dict)
                or any(
                    not isinstance(selection, dict)
                    or not isinstance(selection.get("job_id"), str)
                    or not isinstance(selection.get("area_sha256"), str)
                    for selection in project["selections"].values()
                )
                for project in data["projects"]
            )
        ):
            raise ValueError("Unsupported or invalid planning project data.")
        for project in data["projects"]:
            if data["version"] == 1:
                initialize_project(project)
            validate_project_state(project)
        ids = [project["id"] for project in data["projects"]]
        if len(ids) != len(set(ids)) or (
            data["current"] is not None and data["current"] not in ids
        ):
            raise ValueError("Invalid current planning project.")
        data["version"] = 2
        return data
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Cannot load planning projects: {exc}") from exc


def save_projects(settings, data):
    settings.setValue(SETTINGS_KEY, json.dumps(data, allow_nan=False))
    settings.sync()
    if settings.status() != QtCore.QSettings.Status.NoError:
        raise OSError("Could not save planning projects in QGIS settings.")


class PlanningPanel(QtWidgets.QWidget):
    def __init__(self, main_dock, parent=None, settings=None):
        super().__init__(parent)
        self._main_dock = main_dock
        self._settings = settings if settings is not None else QtCore.QSettings()
        self._jobs = {}
        self._baseline_bands = {}
        self._launching_result_key = None
        self._pending_results = {}
        self._failed_results = {}
        self._changing = False
        self._disposed = False
        self.setObjectName("trends_earth_ldn_planning_panel")
        layout = QtWidgets.QVBoxLayout(self)
        project_row = QtWidgets.QHBoxLayout()
        self.project_combo = QtWidgets.QComboBox()
        self.project_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        project_row.addWidget(self.project_combo)
        new_project = QtWidgets.QPushButton(self.tr("New project..."))
        new_project.clicked.connect(self._new_project)
        project_row.addWidget(new_project)
        layout.addLayout(project_row)

        from .region_selector import RegionSelector

        self.region_selector = RegionSelector()
        self.region_selector.lbl_region.setWordWrap(True)
        self.region_selector.region_changed.connect(self.refresh)
        layout.addWidget(self.region_selector)
        self.area_label = QtWidgets.QLabel()
        self.area_label.setWordWrap(True)
        layout.addWidget(self.area_label)
        self.adopt_area_button = QtWidgets.QPushButton(
            self.tr("Change project area to current region...")
        )
        self.adopt_area_button.clicked.connect(self._adopt_area)
        layout.addWidget(self.adopt_area_button)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        body = QtWidgets.QWidget()
        body_layout = QtWidgets.QVBoxLayout(body)
        note = QtWidgets.QLabel(
            self.tr(
                "Choose saved results for this project. Results are snapshots: "
                "changing a selection does not update or rerun other results. "
                "Configure shared inputs here, then design and run a scenario below. "
                "Configure candidate targets in the scenario draft before running it."
            )
        )
        note.setWordWrap(True)
        body_layout.addWidget(note)
        baseline_group = QtWidgets.QGroupBox(self.tr("Baseline indicator"))
        baseline_layout = QtWidgets.QVBoxLayout(baseline_group)
        self.baseline_combo = QtWidgets.QComboBox()
        self.baseline_combo.currentIndexChanged.connect(self._baseline_changed)
        baseline_layout.addWidget(self.baseline_combo)
        self.baseline_status = QtWidgets.QLabel()
        self.baseline_status.setWordWrap(True)
        baseline_layout.addWidget(self.baseline_status)
        body_layout.addWidget(baseline_group)
        self.reporting_combo = QtWidgets.QComboBox()
        body_layout.addWidget(
            QtWidgets.QLabel(self.tr("Reporting period (optional, sets BAU rate)"))
        )
        body_layout.addWidget(self.reporting_combo)
        self.reporting_combo.currentIndexChanged.connect(self._reporting_changed)
        self.context_group = QtWidgets.QGroupBox(
            self.tr("Period and reporting breakdown")
        )
        context_layout = QtWidgets.QFormLayout(self.context_group)
        context_layout.setRowWrapPolicy(
            QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows
        )
        self.years = {}
        for key, label in (
            ("year_initial", self.tr("Baseline start year")),
            ("year_final", self.tr("Baseline / reporting end year")),
            ("target_year", self.tr("Projection target year")),
        ):
            spin = QtWidgets.QSpinBox()
            spin.setRange(1979, 2100)
            spin.setSpecialValueText(self.tr("Not configured"))
            context_layout.addRow(label, spin)
            self.years[key] = spin
            spin.valueChanged.connect(
                lambda _value, year_key=key: self._context_changed(year_key)
            )
        self.breakdown_combo = QtWidgets.QComboBox()
        for label, value in (
            (self.tr("No land-type breakdown"), "none"),
            (self.tr("Saved land types"), "saved"),
            (self.tr("Land cover"), "land_cover"),
        ):
            self.breakdown_combo.addItem(label, value)
        context_layout.addRow(self.tr("Land-type breakdown"), self.breakdown_combo)
        self.breakdown_combo.currentIndexChanged.connect(self._context_changed)
        self.land_cover_combo = QtWidgets.QComboBox()
        self._land_cover_bands = {}
        context_layout.addRow(self.tr("Land cover dataset"), self.land_cover_combo)
        self.land_cover_combo.currentIndexChanged.connect(
            lambda: self._band_changed(
                "land_cover", self.land_cover_combo, self._land_cover_bands
            )
        )
        self.jurisdictions_combo = QtWidgets.QComboBox()
        for label, value in (
            (self.tr("No jurisdictions"), "none"),
            (self.tr("Administrative units (level 1)"), "admin"),
            (self.tr("Polygon file"), "file"),
        ):
            self.jurisdictions_combo.addItem(label, value)
        context_layout.addRow(self.tr("Jurisdictions"), self.jurisdictions_combo)
        self.jurisdictions_combo.currentIndexChanged.connect(self._context_changed)
        self.jurisdictions_path = QtWidgets.QLineEdit()
        self.jurisdictions_path.setReadOnly(True)
        browse = QtWidgets.QPushButton(self.tr("Choose jurisdiction boundaries..."))
        browse.clicked.connect(self._choose_jurisdictions)
        context_layout.addRow(self.jurisdictions_path)
        context_layout.addRow(browse)
        self._make_collapsible(self.context_group)
        body_layout.addWidget(self.context_group)
        self.combos = {}
        self.status_labels = {}
        self.status_icons = {}
        self.step_buttons = {}
        self._lineage_states = {}
        for key, label, _result, bands in RESULTS:
            group = QtWidgets.QGroupBox(self.tr(label))
            inner = QtWidgets.QVBoxLayout(group)
            combo = QtWidgets.QComboBox()
            combo.currentIndexChanged.connect(
                lambda _index, k=key: self._selection_changed(k)
            )
            inner.addWidget(combo)
            status = QtWidgets.QLabel()
            status.setWordWrap(True)
            status_row = QtWidgets.QHBoxLayout()
            status_icon = QtWidgets.QLabel()
            status_icon.setFixedSize(18, 18)
            status_row.addWidget(status_icon)
            status_row.addWidget(status, 1)
            inner.addLayout(status_row)
            step_button = QtWidgets.QPushButton()
            step_button.clicked.connect(lambda _checked=False, k=key: self._run_step(k))
            step_button.setToolTip(
                self.tr(
                    "Open the tool with the current project selections. "
                    "Inspect its settings before creating a new result."
                )
            )
            inner.addWidget(step_button)
            row = QtWidgets.QHBoxLayout()
            map_button = QtWidgets.QPushButton(self.tr("Show on map"))
            map_button.clicked.connect(
                lambda _checked=False, k=key, b=bands: self._show_map(k, b)
            )
            row.addWidget(map_button)
            summary_button = QtWidgets.QPushButton(self.tr("Summary..."))
            summary_button.clicked.connect(
                lambda _checked=False, k=key: self._summary(k)
            )
            row.addWidget(summary_button)
            inner.addLayout(row)
            self.combos[key] = combo
            self.status_labels[key] = status
            self.status_icons[key] = status_icon
            self.step_buttons[key] = step_button
            if key == "scenario":
                self._build_scenario_editor(body_layout)
            self._make_collapsible(group)
            body_layout.addWidget(group)
        self.scroll = scroll
        body_layout.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        actions = QtWidgets.QMenu(self)
        for label, callback in (
            ("Import prioritization input...", self._import_input),
            ("Create ARR classification...", lambda: self._launch(arr_factory)),
            ("Define land types...", lambda: self._launch(land_types_factory)),
            ("Prioritize interventions...", self._prioritize),
            ("Select candidate areas...", self._select_candidates),
            ("Run current scenario draft", self._scenario),
            ("Create alternative from selected scenario...", self._alternative),
            ("Compare with selected scenario...", self._compare),
        ):
            actions.addAction(self.tr(label), callback)
        self.actions_button = QtWidgets.QPushButton(self.tr("Planning actions"))
        self.actions_button.setMenu(actions)
        layout.addWidget(self.actions_button)
        for combo in self.findChildren(QtWidgets.QComboBox):
            combo.setMinimumContentsLength(15)
            combo.setSizeAdjustPolicy(
                QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
        self.project_combo.currentIndexChanged.connect(self._project_changed)
        self._signals = (
            job_manager.imported_job,
            job_manager.downloaded_job_results,
            job_manager.processed_local_job,
            job_manager.deleted_job,
            main_dock.cache_refresh_finished,
        )
        for signal in self._signals:
            signal.connect(self.refresh, QtCore.Qt.ConnectionType.QueuedConnection)
        job_manager.submitted_local_job.connect(self._submitted_result)
        job_manager.processed_local_job.connect(
            self._completed, QtCore.Qt.ConnectionType.QueuedConnection
        )
        job_manager.failed_local_job.connect(
            self._failed_result, QtCore.Qt.ConnectionType.QueuedConnection
        )
        try:
            self.data = load_projects(self._settings)
        except ValueError as exc:
            self.data = None
            QtWidgets.QMessageBox.critical(self, self.tr("Planning projects"), str(exc))
        if self.data is not None and self._settings.value(SETTINGS_KEY, ""):
            self._save()
        self.refresh()

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        for signal in self._signals:
            signal.disconnect(self.refresh)
        job_manager.submitted_local_job.disconnect(self._submitted_result)
        job_manager.processed_local_job.disconnect(self._completed)
        job_manager.failed_local_job.disconnect(self._failed_result)

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, "data") and not self._disposed:
            self.refresh()

    def _project(self):
        if self.data is None:
            return None
        return next(
            (p for p in self.data["projects"] if p["id"] == self.data["current"]),
            None,
        )

    def _save(self):
        try:
            save_projects(self._settings, self.data)
            return True
        except (OSError, TypeError, ValueError) as exc:
            QtWidgets.QMessageBox.critical(
                self, self.tr("Cannot save planning project"), str(exc)
            )
            return False

    def _current_area(self):
        try:
            return current_area()
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self.area_label.setText(self.tr("Area unavailable: %s") % str(exc))
            return None

    def _new_project(self):
        if self.data is None:
            return
        area = self._current_area()
        if area is None:
            return
        name, accepted = QtWidgets.QInputDialog.getText(
            self, self.tr("New planning project"), self.tr("Project name")
        )
        if not accepted:
            return
        name = name.strip()
        if not name:
            QtWidgets.QMessageBox.warning(
                self, self.tr("Project name"), self.tr("Enter a project name.")
            )
            return
        if any(p["name"].casefold() == name.casefold() for p in self.data["projects"]):
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("Project name"),
                self.tr("That project name already exists."),
            )
            return
        project = {
            "id": str(uuid.uuid4()),
            "name": name,
            "area": area,
            "selections": {},
        }
        initialize_project(project)
        self.data["projects"].append(project)
        self.data["current"] = project["id"]
        self._save()
        self.refresh()

    def _adopt_area(self):
        project = self._project()
        area = self._current_area()
        if project is None or area is None:
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            self.tr("Change project area"),
            self.tr(
                "Use the current area for this project? Existing results will "
                "not be changed and should be checked or rerun for the new area."
            ),
        )
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            project["area"] = area
            self._save()
            self.refresh()

    def _project_changed(self, _index):
        if self._changing or self.data is None:
            return
        self.data["current"] = self.project_combo.currentData()
        self._save()
        self.refresh()

    def _selection_changed(self, key):
        if self._changing:
            return
        project = self._project()
        if project is None:
            return
        self._failed_results.pop((project["id"], key), None)
        job_id = self.combos[key].currentData()
        if job_id is None:
            project["selections"].pop(key, None)
        else:
            project["selections"][key] = {
                "job_id": job_id,
                "area_sha256": project["area"].get("sha256"),
            }
        if key == "land_types":
            if job_id:
                project["context"]["breakdown"] = "saved"
            elif project["context"]["breakdown"] == "saved":
                project["context"]["breakdown"] = "none"
            blocked = self.breakdown_combo.blockSignals(True)
            self.breakdown_combo.setCurrentIndex(
                self.breakdown_combo.findData(project["context"]["breakdown"])
            )
            self.breakdown_combo.blockSignals(blocked)
        self._save()
        self._update_status()

    def _baseline_changed(self, _index):
        if self._changing:
            return
        self._band_changed("baseline", self.baseline_combo, self._baseline_bands)
        project = self._project()
        if project is not None:
            self._sync_baseline_years(project, reset=True)
            self._save()
            self._update_status()

    def _baseline_year_range(self):
        baseline = band_period(self._selected_baseline())
        if baseline is None:
            return None
        reporting_band = self._baseline_bands.get(self.reporting_combo.currentData())
        if reporting_band is None:
            return baseline
        # Indicator bands measure their own period; status bands measure from
        # the baseline start to the reporting end.
        return band_period(reporting_band, reporting=True)

    def _reporting_changed(self, _index):
        if self._changing:
            return
        self._band_changed("reporting", self.reporting_combo, self._baseline_bands)
        project = self._project()
        if project is not None:
            self._sync_baseline_years(project, reset=True)
            self._save()
            self._update_status()

    def _sync_baseline_years(self, project, reset=False):
        context = project["context"]
        supported_years = self._baseline_year_range()
        changed = False
        if supported_years is not None:
            initial, final = supported_years
            target = context["target_year"]
            if reset or type(target) is not int or target <= final:
                target = max(2030, final + 1)
            defaults = {
                "year_initial": initial,
                "year_final": final,
                "target_year": target,
            }
            for key, value in defaults.items():
                if context[key] != value:
                    context[key] = value
                    changed = True
        else:
            initial = context["year_initial"]
            final = context["year_final"]
            if type(final) is int and final > 2099:
                context["year_final"] = final = 2099
                changed = True
            if type(initial) is int and type(final) is int and initial >= final:
                context["year_initial"] = initial = final - 1
                changed = True
            target = context["target_year"]
            if self._selected_baseline() is not None and (
                reset
                or target is None
                or type(target) is not int
                or (type(final) is int and target <= final)
            ):
                target = max(2030, final + 1) if type(final) is int else 2030
                if context["target_year"] != target:
                    context["target_year"] = target
                    changed = True
        self._set_year_controls(supported_years, context)
        return changed

    def _set_year_controls(self, supported_years, context):
        if supported_years is None:
            limits = {
                "year_initial": (1979, 2098),
                "year_final": (1979, 2099),
            }
        else:
            # Degraded classes are cumulative over the band's period, so the
            # BAU rate is only valid for the exact period in its metadata.
            first_year, last_year = supported_years
            limits = {
                "year_initial": (first_year, first_year),
                "year_final": (last_year, last_year),
            }
        end_year = context["year_final"]
        target_minimum = max(1980, end_year + 1) if type(end_year) is int else 1979
        limits["target_year"] = (target_minimum, 2100)
        for key, spin in self.years.items():
            blocked = spin.blockSignals(True)
            spin.setRange(*limits[key])
            spin.setValue(context[key] or 1979)
            if key != "target_year":
                spin.setEnabled(supported_years is None)
            spin.blockSignals(blocked)

    def _band_changed(self, key, combo, bands):
        if self._changing:
            return
        project = self._project()
        if project is None:
            return
        band = bands.get(combo.currentData())
        if band is None:
            project["selections"].pop(key, None)
        else:
            project["selections"][key] = {
                "job_id": str(band.job.id),
                "band_index": band.band_index,
                "area_sha256": project["area"].get("sha256"),
            }
        self._save()
        self._update_status()

    def _selected_baseline(self):
        return self._baseline_bands.get(self.baseline_combo.currentData())

    def _selected(self, key):
        project = self._project()
        if project is None:
            return None
        selection = project["selections"].get(key) or {}
        return self._jobs.get(selection.get("job_id"))

    def _populate_band_combo(self, combo, bands, key, project):
        combo.clear()
        combo.addItem(self.tr("Not selected"), None)
        for band_id, band in bands.items():
            combo.addItem(band.get_name_info(), band_id)
        selected = (project or {}).get("selections", {}).get(key)
        if selected:
            band_id = f"{selected['job_id']}:{selected.get('band_index', 1)}"
            index = combo.findData(band_id)
            if index < 0:
                combo.addItem(self.tr("Unavailable: %s") % band_id, band_id)
                index = combo.count() - 1
            combo.setCurrentIndex(index)
        combo.setEnabled(project is not None)

    def _make_collapsible(self, group):
        group.setCheckable(True)
        group.setChecked(True)
        widgets = group.findChildren(
            QtWidgets.QWidget, options=QtCore.Qt.FindChildOption.FindDirectChildrenOnly
        )
        group.toggled.connect(
            lambda checked: [widget.setVisible(checked) for widget in widgets]
        )

    def _build_scenario_editor(self, layout):
        from .calculate_ldn_planning import ScenarioTargetsWidget

        self.scenario_group = QtWidgets.QGroupBox(self.tr("Scenario design"))
        inner = QtWidgets.QVBoxLayout(self.scenario_group)
        self.draft_combo = QtWidgets.QComboBox()
        self.draft_combo.currentIndexChanged.connect(self._draft_changed)
        inner.addWidget(self.draft_combo)
        new_button = QtWidgets.QPushButton(self.tr("New scenario draft"))
        new_button.clicked.connect(self._new_draft)
        inner.addWidget(new_button)
        self.scenario_editor = ScenarioTargetsWidget(self)
        self.scenario_editor.changed.connect(self._store_editor)
        self.scenario_editor.spin_candidate_eff.valueChanged.connect(self._store_editor)
        inner.addWidget(self.scenario_editor)
        self.readiness_label = QtWidgets.QLabel()
        self.readiness_label.setWordWrap(True)
        self.readiness_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self.readiness_label.linkActivated.connect(self._focus_section)
        inner.addWidget(self.readiness_label)
        self.completion_label = QtWidgets.QLabel()
        self.completion_label.setWordWrap(True)
        inner.addWidget(self.completion_label)
        self.use_result_button = QtWidgets.QPushButton(
            self.tr("Use latest result from this draft")
        )
        self.use_result_button.clicked.connect(self._use_result)
        inner.addWidget(self.use_result_button)
        alternative = QtWidgets.QPushButton(
            self.tr("Create alternative from selected result...")
        )
        alternative.clicked.connect(self._alternative)
        inner.addWidget(alternative)
        save_button = QtWidgets.QPushButton(self.tr("Save draft"))
        save_button.clicked.connect(self._store_editor)
        inner.addWidget(save_button)
        self.step_buttons["scenario"].setToolTip(
            self.tr("Run this draft as a new immutable scenario result.")
        )
        inner.addWidget(self.step_buttons["scenario"])
        clear_comparison = QtWidgets.QPushButton(self.tr("Clear scenario comparison"))
        clear_comparison.clicked.connect(self._clear_comparison)
        inner.addWidget(clear_comparison)
        self._make_collapsible(self.scenario_group)
        layout.addWidget(self.scenario_group)

    def _draft(self):
        project = self._project()
        if project is None:
            return None
        return next(d for d in project["drafts"] if d["id"] == project["active_draft"])

    def _restore_editor(self, project):
        self.context_group.setEnabled(project is not None)
        self.scenario_group.setEnabled(project is not None)
        self.draft_combo.clear()
        if project is None:
            self.scenario_editor.restore(new_draft())
            return
        context = project["context"]
        self._set_year_controls(self._baseline_year_range(), context)
        self.breakdown_combo.setCurrentIndex(
            self.breakdown_combo.findData(context["breakdown"])
        )
        self.land_cover_combo.setEnabled(context["breakdown"] == "land_cover")
        self.jurisdictions_combo.setCurrentIndex(
            self.jurisdictions_combo.findData(context["jurisdictions"])
        )
        self.jurisdictions_path.setText(context["jurisdictions_path"] or "")
        for draft in project["drafts"]:
            self.draft_combo.addItem(
                draft["task_name"] or self.tr("Unnamed scenario"), draft["id"]
            )
        self.draft_combo.setCurrentIndex(
            self.draft_combo.findData(project["active_draft"])
        )
        self.scenario_editor.restore(self._draft())
        self.scenario_editor._refresh_targets_combo()

    def _draft_changed(self, _index):
        if self._changing or self._project() is None:
            return
        self._project()["active_draft"] = self.draft_combo.currentData()
        self._save()
        self.refresh()

    def _new_draft(self):
        project = self._project()
        if project is None:
            return
        draft = new_draft()
        project["drafts"].append(draft)
        project["active_draft"] = draft["id"]
        self._save()
        self.refresh()

    def _store_editor(self, *_args):
        if self._changing or self._project() is None:
            return
        self.scenario_editor._refresh_target_list()
        self._draft().update(self.scenario_editor.draft_values())
        self.draft_combo.setItemText(
            self.draft_combo.currentIndex(),
            self._draft()["task_name"] or self.tr("Unnamed scenario"),
        )
        self._save()
        self._update_status()

    def _context_changed(self, changed_year=None, *_args):
        if self._changing or self._project() is None:
            return
        project = self._project()
        context = project["context"]
        context.update(
            {
                **{
                    key: spin.value() if spin.value() != 1979 else None
                    for key, spin in self.years.items()
                },
                "breakdown": self.breakdown_combo.currentData(),
                "jurisdictions": self.jurisdictions_combo.currentData(),
                "jurisdictions_path": self.jurisdictions_path.text() or None,
            }
        )
        supported_years = self._baseline_year_range()
        if supported_years is not None:
            context["year_initial"], context["year_final"] = supported_years
        else:
            initial = context["year_initial"]
            final = context["year_final"]
            if (
                changed_year == "year_initial"
                and type(initial) is int
                and type(final) is int
                and initial >= final
            ):
                context["year_final"] = initial + 1
            elif (
                changed_year == "year_final"
                and type(initial) is int
                and type(final) is int
                and final <= initial
            ):
                context["year_initial"] = final - 1
        end_year = context["year_final"]
        target = context["target_year"]
        if type(end_year) is int and (target is None or target <= end_year):
            context["target_year"] = max(2030, end_year + 1)
        elif self._selected_baseline() is not None and target is None:
            context["target_year"] = 2030
        self._set_year_controls(supported_years, context)
        self.land_cover_combo.setEnabled(
            self.breakdown_combo.currentData() == "land_cover"
        )
        self._save()
        self._update_status()

    def _choose_jurisdictions(self):
        admin_source = self.tr(
            "Trends.Earth administrative boundaries for the selected country"
        )
        source, accepted = QtWidgets.QInputDialog.getItem(
            self,
            self.tr("Choose jurisdiction boundaries"),
            self.tr("Boundary source"),
            [
                admin_source,
                self.tr("Custom polygon file"),
            ],
            0,
            False,
        )
        if not accepted:
            return
        if source == admin_source:
            self.jurisdictions_path.clear()
            self.jurisdictions_combo.setCurrentIndex(
                self.jurisdictions_combo.findData("admin")
            )
            self._context_changed()
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr("Choose custom jurisdiction polygons"),
            "",
            self.tr("Vector files (*.gpkg *.shp *.geojson);;All files (*)"),
        )
        if path:
            self.jurisdictions_path.setText(path)
            self.jurisdictions_combo.setCurrentIndex(
                self.jurisdictions_combo.findData("file")
            )
            self._context_changed()

    def _focus_section(self, section):
        widget = {
            "baseline": self.baseline_combo,
            "reporting": self.reporting_combo,
            "arr": self.combos["arr"],
            "candidate": self.combos["candidate"],
            "context": self.context_group,
            "targets": self.scenario_editor,
        }.get(section, self.region_selector)
        ancestor = widget.parentWidget()
        while ancestor is not None and ancestor is not self:
            if isinstance(ancestor, QtWidgets.QGroupBox) and ancestor.isCheckable():
                ancestor.setChecked(True)
            ancestor = ancestor.parentWidget()
        if isinstance(widget, QtWidgets.QGroupBox) and widget.isCheckable():
            widget.setChecked(True)
        self.scroll.ensureWidgetVisible(widget)
        widget.setFocus()

    def candidate_target_context(self, check_files=True):
        from te_algorithms.common.checksum import file_checksum

        from .calculate_ldn_priority import job_raster_path

        project = self._project()
        if project is None or self._selected("arr") is None:
            raise ValueError(
                self.tr(
                    "Select an ARR classification before configuring candidate targets."
                )
            )
        if current_area()["sha256"] != project["area"]["sha256"]:
            raise ValueError(
                self.tr("Switch to the project region before using candidate targets.")
            )
        if self._lineage_states.get("candidate") == "stale":
            raise ValueError(
                self.tr(
                    "Candidate inputs differ. Update the selection before "
                    "configuring targets."
                )
            )
        arr_path, _ = job_raster_path(self._selected("arr"))
        candidate = self._selected("candidate")
        candidate_path = (
            job_raster_path(candidate)[0] if candidate and check_files else None
        )
        return {
            "area_sha256": project["area"]["sha256"],
            "arr_job_id": str(self._selected("arr").id),
            "candidate_job_id": str(self._selected("candidate").id)
            if self._selected("candidate")
            else None,
            **(
                {
                    "arr_sha256": file_checksum(arr_path),
                    "mask_sha256": file_checksum(candidate_path)
                    if candidate_path
                    else None,
                }
                if check_files
                else {}
            ),
        }

    def _scenario_params(self, check_files=False):
        from te_algorithms.common.checksum import file_checksum
        from te_algorithms.gdal.util import dataset_checksums

        from .calculate_ldn_planning import ScenarioTargetsWidget, _status_type
        from .calculate_ldn_priority import job_raster_path

        project = self._project()
        if project is None:
            raise ValueError(self.tr("Create or select a project."))
        if current_area()["sha256"] != project["area"]["sha256"]:
            raise ValueError(self.tr("Current region differs from the project region."))
        arr = self._selected("arr")
        baseline = self._selected_baseline()
        if arr is None:
            raise ValueError(self.tr("Select an available ARR classification."))
        if baseline is None:
            raise ValueError(self.tr("Select an available baseline indicator."))
        for key in ("arr", "baseline"):
            if project["selections"][key]["area_sha256"] != project["area"]["sha256"]:
                raise ValueError(
                    self.tr("Select %s again for the changed project area.") % key
                )
        if self._lineage_states.get("arr") == "stale":
            raise ValueError(self.tr("ARR was created for a different region."))
        context = project["context"]
        years = [context[key] for key in ("year_initial", "year_final", "target_year")]
        if any(type(year) is not int or not 1980 <= year <= 2100 for year in years):
            raise ValueError(self.tr("Configure all three planning years."))
        if years[0] >= years[1] or years[2] <= years[1]:
            raise ValueError(
                self.tr(
                    "Initial year must precede reporting end; target year "
                    "must follow it."
                )
            )
        reporting = self._baseline_bands.get(self.reporting_combo.currentData())
        if project["selections"].get("reporting") and reporting is None:
            raise ValueError(
                self.tr(
                    "Reporting status is unavailable; restore or explicitly clear it."
                )
            )
        if (
            reporting
            and project["selections"]["reporting"]["area_sha256"]
            != project["area"]["sha256"]
        ):
            raise ValueError(
                self.tr("Select reporting status again for the changed project area.")
            )
        arr_path, _ = job_raster_path(arr)
        params = {
            "arr_layer_path": arr_path,
            "arr_band_index": 1,
            "arr_job_id": str(arr.id),
            "status_baseline_path": str(baseline.path),
            "status_baseline_band_index": baseline.band_index,
            "status_baseline_job_id": str(baseline.job.id),
            "status_baseline_type": _status_type(baseline),
            "status_reporting_path": str(reporting.path) if reporting else None,
            "status_reporting_band_index": reporting.band_index if reporting else 1,
            "status_reporting_job_id": str(reporting.job.id) if reporting else None,
            "status_reporting_type": _status_type(reporting) if reporting else "3class",
            **{key: context[key] for key in self.years},
            "land_type_path": None,
            "land_type_band_index": 1,
            "land_type_job_id": None,
            "land_type_labels": None,
            "jurisdictions_path": None,
            "aoi_checksum": project["area"]["sha256"],
        }
        if context["breakdown"] == "saved":
            land = self._selected("land_types")
            if land is None or self._lineage_states.get("land_types") == "stale":
                raise ValueError(
                    self.tr(
                        "Choose matching saved land types or explicitly choose no breakdown."
                    )
                )
            path, result = job_raster_path(land)
            units = (result.data or {}).get("land_types_key", {}).get("units", {})
            params.update(
                {
                    "land_type_path": path,
                    "land_type_job_id": str(land.id),
                    "land_type_labels": {
                        str(k): v.get("label", str(k))
                        if isinstance(v, dict)
                        else str(v)
                        for k, v in units.items()
                    },
                }
            )
        elif context["breakdown"] == "land_cover":
            land = self._land_cover_bands.get(self.land_cover_combo.currentData())
            if land is None:
                raise ValueError(self.tr("Select an available land cover dataset."))
            params.update(
                {
                    "land_type_path": str(land.path),
                    "land_type_band_index": land.band_index,
                    "land_type_job_id": str(land.job.id),
                    "land_type_labels": {
                        str(k): v for k, v in ScenarioTargetsWidget._LC_LABELS.items()
                    },
                }
            )
        if context["jurisdictions"] == "file":
            params["jurisdictions_path"] = context["jurisdictions_path"]
            if (
                not params["jurisdictions_path"]
                or not Path(params["jurisdictions_path"]).is_file()
            ):
                raise ValueError(
                    self.tr("Select an available jurisdiction polygon file.")
                )
        elif context["jurisdictions"] == "admin":
            from .conf import Setting, settings_manager

            if not settings_manager.get_value(Setting.COUNTRY_ID):
                raise ValueError(
                    self.tr("Select a country to use administrative jurisdictions.")
                )
            if check_files:
                from .calculate_ldn_planning import _resolve_admin_zones

                params["jurisdictions_path"] = _resolve_admin_zones(self)
                if params["jurisdictions_path"] is None:
                    raise ValueError(
                        self.tr("Could not prepare administrative jurisdictions.")
                    )
        draft = self._draft()
        targets = []
        if draft["use_candidates"]:
            candidate = self._selected("candidate")
            if candidate is None:
                raise ValueError(
                    self.tr(
                        "Select available candidate areas or uncheck Include candidate areas."
                    )
                )
            if self._lineage_states.get("candidate") == "stale":
                raise ValueError(
                    self.tr(
                        "Candidate inputs differ; update candidates before running."
                    )
                )
            candidate_targets = [
                target
                for target in draft["targets"]
                if target.get("selected_mask_path")
            ]
            if not candidate_targets:
                raise ValueError(
                    self.tr("Configure candidate targets in the scenario draft.")
                )
            actual_context = self.candidate_target_context(check_files)
            path, result = job_raster_path(candidate)
            for target in candidate_targets:
                recorded = (
                    target.get("configuration_context")
                    or target.get("approval_context")
                    or {}
                )
                configured_effectiveness = target.get(
                    "configured_effectiveness", target.get("approved_effectiveness")
                )
                if check_files and actual_context["mask_sha256"] != target.get(
                    "mask_sha256"
                ):
                    raise ValueError(
                        self.tr(
                            "Candidate raster changed. Generate new candidate "
                            "areas and update the scenario targets."
                        )
                    )
                if configured_effectiveness != target["effectiveness"] or any(
                    recorded.get(k) != v for k, v in actual_context.items()
                ):
                    raise ValueError(
                        self.tr(
                            "Candidate target settings no longer match the "
                            "current inputs. Configure them again."
                        )
                    )
                if check_files and (
                    file_checksum(path) != target.get("mask_sha256")
                    or file_checksum(path)
                    != (result.data or {})
                    .get("report", {})
                    .get("summary", {})
                    .get("mask_sha256")
                ):
                    raise ValueError(
                        self.tr(
                            "Candidate raster changed. Generate new candidate "
                            "areas and update the scenario targets."
                        )
                    )
                target = copy.deepcopy(target)
                target["selected_mask_path"] = path
                targets.append(target)
        if draft["use_polygons"]:
            polygons = [t for t in draft["targets"] if not t.get("selected_mask_path")]
            if not polygons:
                raise ValueError(
                    self.tr("Load polygon targets or uncheck Include polygon targets.")
                )
            targets.extend(copy.deepcopy(polygons))
        params.update(
            {
                "targets": targets,
                "task_name": draft["task_name"],
                "task_notes": draft["task_notes"],
                "planning_project_id": project["id"],
                "planning_draft_id": draft["id"],
                "planning_context": copy.deepcopy(
                    {
                        "area": project["area"],
                        "selections": {
                            k: v
                            for k, v in project["selections"].items()
                            if k != "scenario"
                        },
                        "context": context,
                    }
                ),
                "scenario_draft": copy.deepcopy(draft),
            }
        )
        if check_files:
            params["input_checksums"] = {
                key: dataset_checksums(params[key])
                for key in (
                    "arr_layer_path",
                    "status_baseline_path",
                    "status_reporting_path",
                    "land_type_path",
                    "jurisdictions_path",
                )
                if params.get(key)
            }
        return params

    def _update_readiness(self):
        if not hasattr(self, "scenario_editor"):
            return
        try:
            self._scenario_params()
        except (ValueError, OSError, RuntimeError) as exc:
            import html

            self.readiness_label.setText(
                self.tr("Needs attention: %s") % html.escape(str(exc))
                + ' <a href="context">'
                + self.tr("Project settings")
                + "</a>"
                + ' | <a href="targets">'
                + self.tr("Configure targets")
                + "</a>"
            )
        else:
            required = ["arr"]
            if self._project()["context"]["breakdown"] == "saved":
                required.append("land_types")
            if self._draft()["use_candidates"]:
                required.append("candidate")
            unverified = any(
                self._lineage_states.get(key) in ("unknown", "processing")
                for key in required
            )
            self.readiness_label.setText(
                self.tr(
                    "Draft configured; some source links are unverified. Inspect their reports before running."
                )
                if unverified
                else self.tr(
                    "Draft ready. Inputs and candidate checksums will be checked before execution."
                )
            )
        draft = self._draft() if self._project() else None
        result_id = draft.get("latest_result_id") if draft else None
        self.use_result_button.setEnabled(result_id in self._jobs)
        self.completion_label.setText(
            self.tr("Latest completed result: %s") % result_id if result_id else ""
        )

    def _use_result(self):
        result_id = self._draft().get("latest_result_id")
        index = self.combos["scenario"].findData(result_id)
        if index >= 0:
            self.combos["scenario"].setCurrentIndex(index)

    def _clear_comparison(self):
        if self._project() is None:
            return
        self._draft()["comparison_job_id"] = None
        self._save()
        self._update_status()

    def refresh(self, *_args):
        if self._disposed:
            return
        from .calculate_ldn_priority import planning_raster_jobs

        blocked = self.region_selector.blockSignals(True)
        try:
            self.region_selector._update_current_region()
        finally:
            self.region_selector.blockSignals(blocked)
        self._changing = True
        try:
            self.project_combo.clear()
            self.project_combo.addItem(self.tr("Select a planning project"), None)
            if self.data is not None:
                for project in self.data["projects"]:
                    self.project_combo.addItem(project["name"], project["id"])
                index = self.project_combo.findData(self.data["current"])
                self.project_combo.setCurrentIndex(max(index, 0))
            project = self._project()
            if project is not None:
                initialize_project(project)
            self._jobs = {}
            self._baseline_bands = {}
            for band in baseline_bands() if project is not None else []:
                band_id = f"{band.job.id}:{band.band_index}"
                self._baseline_bands[band_id] = band
            for key, combo in (
                ("baseline", self.baseline_combo),
                ("reporting", self.reporting_combo),
            ):
                self._populate_band_combo(combo, self._baseline_bands, key, project)
            from te_algorithms.gdal.land_deg import config as ld_config

            from .areaofinterest import try_prepare_area_of_interest
            from .data_io import _get_usable_bands

            aoi = try_prepare_area_of_interest(use_cache=False) if project else None
            self._land_cover_bands = {
                f"{band.job.id}:{band.band_index}": band
                for band in (
                    _get_usable_bands(
                        band_name=tuple(ld_config.LC_BAND_NAME)
                        if isinstance(ld_config.LC_BAND_NAME, list)
                        else ld_config.LC_BAND_NAME,
                        aoi=aoi,
                    )
                    if aoi
                    else []
                )
            }
            self._populate_band_combo(
                self.land_cover_combo, self._land_cover_bands, "land_cover", project
            )
            if project is not None and self._sync_baseline_years(project):
                self._save()
            for key, _label, result_name, _bands in RESULTS:
                combo = self.combos[key]
                combo.clear()
                combo.addItem(self.tr("Not selected"), None)
                for job in planning_raster_jobs(result_name):
                    if job.status not in AVAILABLE:
                        continue
                    job_id = str(job.id)
                    self._jobs[job_id] = job
                    combo.addItem(job.task_name or job_id, job_id)
                selected = (project or {}).get("selections", {}).get(key, {})
                job_id = selected.get("job_id")
                if job_id:
                    index = combo.findData(job_id)
                    if index < 0:
                        combo.addItem(self.tr("Unavailable: %s") % job_id, job_id)
                        index = combo.count() - 1
                    combo.setCurrentIndex(index)
                combo.setEnabled(project is not None)
            self.actions_button.setEnabled(project is not None)
            self._restore_editor(project)
        finally:
            self._changing = False
        self._update_status()

    def _update_status(self):
        project = self._project()
        self.adopt_area_button.setEnabled(project is not None)
        self._lineage_states = {}
        if project is None:
            self.area_label.setText(self.tr("Create or select a planning project."))
            self.baseline_status.setText("")
            for key, _label, _result, _bands in RESULTS:
                self._set_lineage_status(key, "empty", "")
                self.step_buttons[key].setEnabled(False)
            self._update_readiness()
            return
        area = self._current_area()
        if area is not None:
            if area["sha256"] == project["area"].get("sha256"):
                self.area_label.setText(
                    self.tr(
                        "Project area: %s. Dataset area compatibility is not verified."
                    )
                    % project["area"].get("name", "")
                )
            else:
                self.area_label.setText(
                    self.tr(
                        "Current area differs from project area (%s). "
                        "Switch back or explicitly change the project area before running."
                    )
                    % project["area"].get("name", "")
                )
        baseline_selection = project["selections"].get("baseline")
        if not baseline_selection:
            self.baseline_status.setText(self.tr("No baseline indicator selected."))
        elif self._selected_baseline() is None:
            self.baseline_status.setText(
                self.tr(
                    "Baseline unavailable for the current area; restore or replace it."
                )
            )
        elif baseline_selection.get("area_sha256") != project["area"].get("sha256"):
            self.baseline_status.setText(
                self.tr("Selected before the project area changed; update or replace.")
            )
        else:
            self.baseline_status.setText(
                self.tr("The baseline is selected. Configure its years above.")
            )
        for key, _label, _result, _bands in RESULTS:
            if pending := self._pending_result(project["id"], key):
                self._set_lineage_status(
                    key, "processing", pending.get("task_name", "")
                )
                continue
            if failure := self._failed_results.get((project["id"], key)):
                self._set_lineage_status(key, "unknown", failure)
                continue
            selection = project["selections"].get(key)
            job = self._selected(key)
            button = self.step_buttons[key]
            button.setEnabled(True)
            button_labels = {
                "arr": (self.tr("Create ARR..."), self.tr("Update ARR...")),
                "land_types": (
                    self.tr("Define land types..."),
                    self.tr("Update land types..."),
                ),
                "priority": (
                    self.tr("Create priority preview..."),
                    self.tr("Update priority preview..."),
                ),
                "candidate": (
                    self.tr("Select candidate areas..."),
                    self.tr("Update candidate areas..."),
                ),
                "scenario": (
                    self.tr("Run current draft"),
                    self.tr("Run current draft"),
                ),
            }
            button.setText(button_labels[key][bool(selection)])
            if not selection:
                state, text = "empty", self.tr("No result selected.")
            elif job is None:
                state, text = (
                    "unknown",
                    self.tr("Dataset unavailable; restore it or choose another."),
                )
            elif selection.get("area_sha256") != project["area"].get("sha256"):
                state, text = (
                    "stale",
                    self.tr(
                        "Selected before the project area changed; update or rerun."
                    ),
                )
            else:
                state, text = self._lineage_status(key, job)
            self._set_lineage_status(key, state, text)
        self._update_readiness()

    def _set_lineage_status(self, key, state, text):
        self._lineage_states[key] = state
        labels = {
            "match": (
                self.tr("Analysis area matches")
                if key in ("arr", "land_types")
                else self.tr("Selected inputs match")
            ),
            "stale": self.tr("Needs update"),
            "unknown": self.tr("Not verified"),
            "processing": self.tr("Result processing"),
        }
        if state in labels:
            label = labels[state]
            self.status_labels[key].setText("%s: %s" % (label, text) if text else label)
        else:
            self.status_labels[key].setText(text)
        icon = self.status_icons[key]
        icon.setProperty("lineage_state", state)
        icon.setToolTip(self.status_labels[key].text())
        icon.setAccessibleName(labels.get(state, self.tr("No result selected")))
        icons = {
            "match": QtWidgets.QStyle.StandardPixmap.SP_DialogApplyButton,
            "stale": QtWidgets.QStyle.StandardPixmap.SP_DialogCancelButton,
            "unknown": QtWidgets.QStyle.StandardPixmap.SP_MessageBoxWarning,
            "processing": QtWidgets.QStyle.StandardPixmap.SP_BrowserReload,
        }
        if state in icons:
            icon.setPixmap(self.style().standardIcon(icons[state]).pixmap(16, 16))
        else:
            icon.clear()

    def _lineage_status(self, key, job):
        if not job_manager.ensure_params_loaded(job):
            return (
                "unknown",
                self.tr(
                    "Recorded inputs are unavailable; inspect the dataset before use."
                ),
            )
        params = job.params or {}
        project = self._project()
        selections = project["selections"]
        missing = []
        recorded_area = params.get("aoi_checksum")
        if recorded_area and recorded_area != project["area"].get("sha256"):
            return "stale", self.tr("Created for a different project area.")
        if not recorded_area:
            missing.append(self.tr("The dataset's analysis area was not recorded."))

        if key in ("arr", "land_types"):
            if missing:
                return "unknown", " ".join(missing)
            return "match", ""

        def check_raster(selection_key, path_key, band_key=None, job_key=None):
            selected = self._selected(selection_key)
            if selected is None:
                if selections.get(selection_key):
                    missing.append(
                        self.tr("Selected %s is unavailable.") % selection_key
                    )
                elif params.get(path_key):
                    missing.append(
                        self.tr("Select %s to check the recorded input.")
                        % selection_key
                    )
                return None
            if self._lineage_states.get(selection_key) == "stale":
                return self.tr("Selected %s needs updating.") % selection_key
            if self._lineage_states.get(selection_key) != "match":
                missing.append(self.tr("Selected %s is not verified.") % selection_key)
            recorded_id = params.get(job_key) if job_key else None
            if recorded_id:
                if str(recorded_id) != str(selected.id) or (
                    band_key is not None and params.get(band_key, 1) != 1
                ):
                    return (
                        self.tr("Uses a different %s dataset or band.") % selection_key
                    )
                return None
            from .calculate_ldn_priority import job_raster_path

            try:
                path, _result = job_raster_path(selected)
            except ValueError as exc:
                missing.append(
                    self.tr("Cannot check %s: %s") % (selection_key, str(exc))
                )
                return None
            if path_key not in params:
                missing.append(self.tr("%s input was not recorded.") % selection_key)
            elif params[path_key] != path or (
                band_key is not None and params.get(band_key, 1) != 1
            ):
                return self.tr("Uses a different %s dataset or band.") % selection_key
            return None

        if key == "priority":
            if not selections.get("arr"):
                missing.append(
                    self.tr("Select an ARR classification to check its input.")
                )
            for selection_key, path_key, band_key, job_key in (
                ("arr", "arr_layer_path", "arr_band_index", "arr_job_id"),
                ("land_types", "land_type_path", None, "land_type_job_id"),
            ):
                mismatch = check_raster(selection_key, path_key, band_key, job_key)
                if mismatch:
                    return "stale", mismatch
        elif key == "candidate":
            priority = self._selected("priority")
            recorded = params.get("priority_job_id")
            if not recorded:
                missing.append(
                    self.tr("Priority lineage not recorded; inspect this result.")
                )
            if priority is None:
                missing.append(self.tr("Source priority: %s") % (recorded or "unknown"))
            elif recorded and recorded != str(priority.id):
                return "stale", self.tr("Uses a different priority preview.")
            elif self._lineage_states.get("priority") == "stale":
                return "stale", self.tr("The selected priority preview needs updating.")
            elif self._lineage_states.get("priority") != "match":
                missing.append(self.tr("The selected priority input is not verified."))
        else:
            if not selections.get("arr"):
                missing.append(
                    self.tr("Select an ARR classification to check its input.")
                )
            for selection_key, path_key, band_key, job_key in (
                ("arr", "arr_layer_path", "arr_band_index", "arr_job_id"),
                (
                    "land_types",
                    "land_type_path",
                    "land_type_band_index",
                    "land_type_job_id",
                ),
            ):
                mismatch = check_raster(selection_key, path_key, band_key, job_key)
                if mismatch:
                    return "stale", mismatch
            baseline = self._selected_baseline()
            if baseline is None:
                missing.append(
                    self.tr("Select an available baseline to check its input.")
                )
            elif selections["baseline"].get("area_sha256") != project["area"].get(
                "sha256"
            ):
                return "stale", self.tr("Select the baseline again for this area.")
            elif params.get("status_baseline_job_id"):
                if (
                    str(params["status_baseline_job_id"]) != str(baseline.job.id)
                    or params.get("status_baseline_band_index", 1)
                    != baseline.band_index
                ):
                    return "stale", self.tr(
                        "Uses a different baseline indicator or band."
                    )
            elif "status_baseline_path" not in params:
                missing.append(self.tr("Baseline input was not recorded."))
            elif (
                params["status_baseline_path"] != str(baseline.path)
                or params.get("status_baseline_band_index", 1) != baseline.band_index
            ):
                return "stale", self.tr("Uses a different baseline indicator or band.")
            candidate = self._selected("candidate")
            if candidate is None and selections.get("candidate"):
                missing.append(self.tr("Selected candidate dataset is unavailable."))
            elif candidate is None and any(
                target.get("source_job_id") for target in (params.get("targets") or [])
            ):
                missing.append(
                    self.tr("Select a candidate dataset to check its input.")
                )
            elif candidate is not None and (
                "scenario_draft" not in params
                or params["scenario_draft"].get("use_candidates")
            ):
                if "targets" not in params:
                    missing.append(self.tr("Scenario targets were not recorded."))
                elif str(candidate.id) not in {
                    target.get("source_job_id") for target in (params["targets"] or [])
                }:
                    return "stale", self.tr(
                        "Does not reference the selected candidate dataset."
                    )
                elif self._lineage_states.get("candidate") == "stale":
                    return "stale", self.tr(
                        "The selected candidate dataset needs updating."
                    )
                elif self._lineage_states.get("candidate") != "match":
                    missing.append(
                        self.tr("The selected candidate input is not verified.")
                    )
        if key == "scenario" and params.get("planning_context"):
            recorded = params["planning_context"]
            if recorded.get("context") != project["context"]:
                return "stale", self.tr(
                    "Uses different planning years or reporting breakdown settings."
                )
            for selection_key in ("reporting", "land_cover"):
                if recorded.get("selections", {}).get(selection_key) != selections.get(
                    selection_key
                ):
                    return "stale", self.tr(
                        "Uses a different %s dataset or band."
                    ) % selection_key
            if params.get("scenario_draft", {}).get("targets") != self._draft()[
                "targets"
            ] or any(
                params.get("scenario_draft", {}).get(k) != self._draft().get(k)
                for k in ("use_candidates", "use_polygons")
            ):
                return "stale", self.tr(
                    "Saved targets or effectiveness differ from the current draft."
                )
        if missing:
            return "unknown", " ".join(missing)
        return "match", self.tr(
            "Selected links match; file contents and dataset coverage are not verified."
        )

    def _run_step(self, key):
        if key == "arr":
            self._launch(arr_factory)
        elif key == "land_types":
            self._launch(land_types_factory)
        elif key == "priority":
            self._prioritize()
        elif key == "candidate":
            self._select_candidates()
        elif key == "scenario":
            self._scenario()

    def _require_area(self):
        project = self._project()
        area = self._current_area()
        if project is None or area is None:
            return False
        if area["sha256"] != project["area"].get("sha256"):
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("Different project area"),
                self.tr(
                    "Switch to the project area or explicitly change the project area."
                ),
            )
            return False
        return True

    def _launch(self, factory, **kwargs):
        if self._require_area():
            previous_result_key = self._launching_result_key
            self._launching_result_key = {
                arr_factory: "arr",
                land_types_factory: "land_types",
                selection_factory: "candidate",
            }.get(factory)
            try:
                launch_calculate_dialog(
                    self._main_dock,
                    factory,
                    project_inputs={"panel": self, "state": self.operation_context()},
                    **kwargs,
                )
            finally:
                self._launching_result_key = previous_result_key
            self.refresh()

    def _pending_result(self, project_id, key):
        pending = None
        for result in self._pending_results.values():
            if result["project_id"] == project_id and result["key"] == key:
                pending = result
        return pending

    def _submitted_result(self, job):
        if self._disposed or self._launching_result_key is None:
            return
        script_name = getattr(getattr(job, "script", None), "name", None)
        if AUTO_SELECT_RESULT_KEYS.get(script_name) != self._launching_result_key:
            return
        project = self._project()
        if project is None:
            return
        key = self._launching_result_key
        self._failed_results.pop((project["id"], key), None)
        self._pending_results[str(job.id)] = {
            "key": key,
            "project_id": project["id"],
            "area_sha256": project["area"].get("sha256"),
            "task_name": job.task_name or str(job.id),
        }
        self._update_status()

    def _failed_result(self, job):
        pending = self._pending_results.pop(str(job.id), None)
        if pending is None:
            return
        self._failed_results[(pending["project_id"], pending["key"])] = self.tr(
            "Result processing failed; the current selection was not changed."
        )
        if (
            self._project() is not None
            and self._project()["id"] == pending["project_id"]
        ):
            self._update_status()

    def operation_context(self):
        project = self._project()
        return copy.deepcopy(
            {
                "project_id": project["id"],
                "area": project["area"],
                "selections": {
                    k: v for k, v in project["selections"].items() if k != "scenario"
                },
                "context": project["context"],
            }
        )

    def _prioritize(self):
        arr = self._selected("arr")
        if arr is None:
            QtWidgets.QMessageBox.information(
                self,
                self.tr("Select ARR"),
                self.tr("Choose an ARR classification first."),
            )
            return
        kwargs = {
            "draft_name": "priority-" + self._project()["id"],
            "preselect_arr_job_id": str(arr.id),
        }
        land_types = self._selected("land_types")
        if self._project()["selections"].get("land_types") and land_types is None:
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("Dataset unavailable"),
                self.tr(
                    "The selected land types are unavailable. Restore or replace them."
                ),
            )
            return
        kwargs["preselect_land_type_job_id"] = (
            str(land_types.id) if land_types is not None else None
        )
        previous = self._selected("priority")
        if previous is not None:
            if not job_manager.ensure_params_loaded(previous):
                QtWidgets.QMessageBox.warning(
                    self,
                    self.tr("Settings unavailable"),
                    self.tr("The selected priority settings cannot be loaded."),
                )
                return
            kwargs["preselect_priority_settings"] = copy.deepcopy(previous.params or {})
        self._launch(priority_factory, **kwargs)

    def _select_candidates(self):
        priority = self._selected("priority")
        if priority is None:
            QtWidgets.QMessageBox.information(
                self,
                self.tr("Select priority"),
                self.tr("Choose a priority preview first."),
            )
            return
        kwargs = {"preselect_priority_job_id": str(priority.id)}
        previous = self._selected("candidate")
        if previous is not None:
            if not job_manager.ensure_params_loaded(previous):
                QtWidgets.QMessageBox.warning(
                    self,
                    self.tr("Settings unavailable"),
                    self.tr("The selected candidate settings cannot be loaded."),
                )
                return
            selections = (previous.params or {}).get("selections")
            if not isinstance(selections, dict) or not selections:
                QtWidgets.QMessageBox.warning(
                    self,
                    self.tr("Settings unavailable"),
                    self.tr(
                        "The selected candidate settings are missing. Clear the "
                        "selection to create new candidate areas."
                    ),
                )
                return
            kwargs["preselect_selections"] = copy.deepcopy(selections)
        self._launch(selection_factory, **kwargs)

    def _scenario(self, comparison=None):
        self._update_status()
        if not self._require_area() or not self._save():
            return
        from te_algorithms.gdal.land_deg.ldn_planning import compare_scenarios
        from te_schemas.results import RasterResults

        from .areaofinterest import prepare_area_of_interest

        snapshot = copy.deepcopy((self._project(), self._draft()))
        try:
            params = self._scenario_params(check_files=True)
            comparison_id = self._draft().get("comparison_job_id")
            if comparison is None and comparison_id:
                comparison = self._jobs.get(comparison_id)
                if comparison is None:
                    raise ValueError(
                        self.tr(
                            "Comparison result is unavailable. Clear or replace it."
                        )
                    )
            if comparison is not None:
                job_manager.ensure_results_loaded(comparison)
                if not job_manager.ensure_params_loaded(comparison):
                    raise ValueError(self.tr("Comparison parameters are unavailable."))
                result = comparison.get_first_result_by_type(RasterResults)
                if result is None:
                    raise ValueError(self.tr("Comparison result has no raster data."))
                params["comparison"] = {
                    "job_id": str(comparison.id),
                    "task_name": comparison.task_name,
                    "projection": (result.data or {}).get("projection"),
                    "parameters": comparison.params,
                }
                # The helper checks reference inputs before calculating differences.
                compare_scenarios(params, params["comparison"]["projection"])
            if not params["targets"]:
                if (
                    QtWidgets.QMessageBox.question(
                        self,
                        self.tr("No targets"),
                        self.tr(
                            "This scenario has no interventions and will produce no changes. Run it anyway?"
                        ),
                        QtWidgets.QMessageBox.StandardButton.Yes
                        | QtWidgets.QMessageBox.StandardButton.No,
                    )
                    != QtWidgets.QMessageBox.StandardButton.Yes
                ):
                    return
            aoi = prepare_area_of_interest()
            if aoi is None:
                raise ValueError(self.tr("Select a valid region before running."))
            if (
                snapshot != (self._project(), self._draft())
                or area_checksum(aoi.get_geojson()) != params["aoi_checksum"]
            ):
                raise ValueError(
                    self.tr(
                        "Project inputs changed while preparing the run. "
                        "Update the inputs and try again."
                    )
                )
            job_manager.submit_local_job_as_qgstask(
                copy.deepcopy(params),
                script_name="ldn-planning-projection",
                area_of_interest=aoi,
            )
        except (ValueError, OSError, RuntimeError) as exc:
            QtWidgets.QMessageBox.critical(
                self, self.tr("Cannot run scenario"), str(exc)
            )
        self._update_status()

    def _completed(self, job):
        if self._disposed or self.data is None:
            return
        pending = self._pending_results.pop(str(job.id), None)
        if pending is not None:
            for project in self.data["projects"]:
                if project["id"] != pending["project_id"]:
                    continue
                key = pending["key"]
                project["selections"][key] = {
                    "job_id": str(job.id),
                    "area_sha256": pending["area_sha256"],
                }
                if key == "land_types":
                    project["context"]["breakdown"] = "saved"
                self._failed_results.pop((project["id"], key), None)
                self._save()
                if self._project() is project:
                    self.refresh()
                break
        if not job_manager.ensure_params_loaded(job):
            return
        params = job.params or {}
        project_id, draft_id = (
            params.get("planning_project_id"),
            params.get("planning_draft_id"),
        )
        if not project_id or not draft_id:
            return
        for project in self.data["projects"]:
            if project["id"] == project_id:
                for draft in project["drafts"]:
                    if draft["id"] == draft_id:
                        previous_id = draft.get("latest_result_id")
                        previous = self._jobs.get(previous_id)
                        if (
                            previous is not None
                            and previous.start_date > job.start_date
                        ):
                            return
                        draft["latest_result_id"] = str(job.id)
                        self._save()
                        self.refresh()
                        return

    def _alternative(self):
        job = self._selected("scenario")
        project = self._project()
        if job is None or project is None:
            QtWidgets.QMessageBox.information(
                self,
                self.tr("Select scenario"),
                self.tr("Choose a saved scenario first."),
            )
            return
        if not job_manager.ensure_params_loaded(job):
            QtWidgets.QMessageBox.critical(
                self,
                self.tr("Cannot create alternative"),
                self.tr("Saved parameters are unavailable."),
            )
            return
        params = job.params or {}
        recorded = params.get("planning_context")
        if recorded is None:
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("Unverified reference inputs"),
                self.tr(
                    "This older result has no project context. Its targets "
                    "can be rebased to current inputs, but should be checked "
                    "against them."
                ),
            )
            rebase = True
        else:
            current = {
                "area": project["area"],
                "selections": {
                    k: v for k, v in project["selections"].items() if k != "scenario"
                },
                "context": project["context"],
            }
            rebase = recorded != current
        if rebase:
            choice, accepted = QtWidgets.QInputDialog.getItem(
                self,
                self.tr("Different reference inputs"),
                self.tr("Create alternative using"),
                [
                    self.tr("Current project inputs (reconfigure targets)"),
                    self.tr("New project with saved inputs"),
                ],
                0,
                False,
            )
            if not accepted:
                return
            if choice == self.tr("New project with saved inputs"):
                if recorded is None:
                    QtWidgets.QMessageBox.critical(
                        self,
                        self.tr("Missing context"),
                        self.tr(
                            "This result cannot restore its original project inputs."
                        ),
                    )
                    return
                project = {
                    "id": str(uuid.uuid4()),
                    "name": (job.task_name or self.tr("Scenario"))
                    + " - "
                    + str(uuid.uuid4())[:8],
                    **copy.deepcopy(recorded),
                }
                initialize_project(project)
                self.data["projects"].append(project)
                self.data["current"] = project["id"]
                rebase = False
        draft = new_draft()
        if params.get("scenario_draft"):
            draft.update(copy.deepcopy(params["scenario_draft"]))
        else:
            draft.update(
                {
                    "targets": copy.deepcopy(params.get("targets") or []),
                    "use_candidates": any(
                        t.get("selected_mask_path") for t in params.get("targets", [])
                    ),
                    "use_polygons": any(
                        not t.get("selected_mask_path")
                        for t in params.get("targets", [])
                    ),
                    "task_notes": params.get("task_notes") or "",
                }
            )
        draft["id"] = str(uuid.uuid4())
        draft["task_name"] = (job.task_name or self.tr("Scenario")) + self.tr(
            " - alternative"
        )
        draft.pop("latest_result_id", None)
        if rebase:
            for target in draft["targets"]:
                if target.get("selected_mask_path"):
                    for key in (
                        "approval_context",
                        "approved_effectiveness",
                        "approved",
                        "configuration_context",
                        "configured_effectiveness",
                    ):
                        target.pop(key, None)
        project["drafts"].append(draft)
        project["active_draft"] = draft["id"]
        self._save()
        self.refresh()
        self._focus_section("targets")

    def _compare(self):
        scenario = self._selected("scenario")
        if scenario is None:
            QtWidgets.QMessageBox.information(
                self, self.tr("Select scenario"), self.tr("Choose a scenario first.")
            )
            return
        self._draft()["comparison_job_id"] = str(scenario.id)
        self._save()
        self._scenario(comparison=scenario)

    def _import_input(self):
        if not self._require_area():
            return
        from .ldn_planning_assets import DlgImportPlanningInput

        DlgImportPlanningInput(self).exec()
        self.refresh()

    def _show_map(self, key, bands):
        job = self._selected(key)
        if job is None:
            QtWidgets.QMessageBox.information(
                self,
                self.tr("No dataset"),
                self.tr("Choose an available dataset first."),
            )
            return
        job_manager.ensure_results_loaded(job)
        job_manager.display_selected_job_results(job, list(bands))

    def _summary(self, key):
        job = self._selected(key)
        if job is None:
            QtWidgets.QMessageBox.information(
                self,
                self.tr("No dataset"),
                self.tr("Choose an available dataset first."),
            )
            return
        show_planning_summary(job, self)


def open_panel(main_dock):
    main_dock.show()
    main_dock.raise_()
    main_dock.tabWidget.setCurrentWidget(main_dock.planning_panel)
    main_dock.planning_panel.refresh()
    return main_dock.planning_panel
