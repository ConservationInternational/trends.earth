"""Docked LDN planning projects and explicit result handoffs."""

import json
import uuid

from qgis.PyQt import QtCore, QtWidgets
from te_schemas.jobs import JobStatus
from te_algorithms.gdal.land_deg.ldn_planning_inputs import area_checksum

from .jobs.manager import job_manager
from .ldn_planning_actions import (
    arr_factory,
    land_types_factory,
    launch_calculate_dialog,
    priority_factory,
    projection_factory,
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
_panel = None


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
    return _get_usable_bands(band_name=ld_config.SDG_BAND_NAME, aoi=aoi)


def load_projects(settings):
    raw = settings.value(SETTINGS_KEY, "")
    if not raw:
        return {"version": 1, "projects": [], "current": None}
    try:
        data = json.loads(raw)
        if (
            not isinstance(data, dict)
            or data.get("version") != 1
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
        return data
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Cannot load planning projects: {exc}") from exc


def save_projects(settings, data):
    settings.setValue(SETTINGS_KEY, json.dumps(data, allow_nan=False))
    settings.sync()
    if settings.status() != QtCore.QSettings.Status.NoError:
        raise OSError("Could not save planning projects in QGIS settings.")


class PlanningPanel(QtWidgets.QDockWidget):
    def __init__(self, main_dock, parent=None, settings=None):
        super().__init__(parent)
        self._main_dock = main_dock
        self._settings = settings if settings is not None else QtCore.QSettings()
        self._jobs = {}
        self._baseline_bands = {}
        self._changing = False
        self._disposed = False
        self.setObjectName("trends_earth_ldn_planning_panel")
        self.setWindowTitle(self.tr("LDN Planning"))
        self.setAllowedAreas(
            QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
            | QtCore.Qt.DockWidgetArea.RightDockWidgetArea
        )

        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
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
        self.region_selector.region_changed.connect(self.refresh)
        layout.addWidget(self.region_selector)
        self.area_label = QtWidgets.QLabel()
        self.area_label.setWordWrap(True)
        layout.addWidget(self.area_label)
        self.adopt_area_button = QtWidgets.QPushButton(
            self.tr("Use current region for this project...")
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
                "changing a selection does not update or rerun other results."
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
        self.combos = {}
        self.status_labels = {}
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
            inner.addWidget(status)
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
            body_layout.addWidget(group)
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
            ("Build scenario...", self._scenario),
            ("Compare with selected scenario...", self._compare),
        ):
            actions.addAction(self.tr(label), callback)
        self.actions_button = QtWidgets.QPushButton(self.tr("Planning actions"))
        self.actions_button.setMenu(actions)
        layout.addWidget(self.actions_button)
        self.setWidget(container)
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
        try:
            self.data = load_projects(self._settings)
        except ValueError as exc:
            self.data = None
            QtWidgets.QMessageBox.critical(self, self.tr("Planning projects"), str(exc))
        self.refresh()

    def dispose(self):
        self._disposed = True
        for signal in self._signals:
            signal.disconnect(self.refresh)

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
        job_id = self.combos[key].currentData()
        if job_id is None:
            project["selections"].pop(key, None)
        else:
            project["selections"][key] = {
                "job_id": job_id,
                "area_sha256": project["area"].get("sha256"),
            }
        self._save()
        self._update_status()

    def _baseline_changed(self, _index):
        if self._changing:
            return
        project = self._project()
        if project is None:
            return
        band = self._baseline_bands.get(self.baseline_combo.currentData())
        if band is None:
            project["selections"].pop("baseline", None)
        else:
            project["selections"]["baseline"] = {
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
            self._jobs = {}
            self._baseline_bands = {}
            self.baseline_combo.clear()
            self.baseline_combo.addItem(self.tr("Not selected"), None)
            for band in baseline_bands() if project is not None else []:
                band_id = f"{band.job.id}:{band.band_index}"
                self._baseline_bands[band_id] = band
                self.baseline_combo.addItem(band.get_name_info(), band_id)
            selected_baseline = (
                (project or {}).get("selections", {}).get("baseline", {})
            )
            if selected_baseline:
                band_id = (
                    f"{selected_baseline.get('job_id')}:"
                    f"{selected_baseline.get('band_index')}"
                )
                index = self.baseline_combo.findData(band_id)
                if index < 0:
                    self.baseline_combo.addItem(
                        self.tr("Unavailable: %s") % band_id, band_id
                    )
                    index = self.baseline_combo.count() - 1
                self.baseline_combo.setCurrentIndex(index)
            self.baseline_combo.setEnabled(project is not None)
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
        finally:
            self._changing = False
        self._update_status()

    def _update_status(self):
        project = self._project()
        self.adopt_area_button.setEnabled(project is not None)
        if project is None:
            self.area_label.setText(self.tr("Create or select a planning project."))
            self.baseline_status.setText("")
            for label in self.status_labels.values():
                label.setText("")
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
                self.tr("Selected before the project area changed; review or replace.")
            )
        else:
            self.baseline_status.setText(
                self.tr(
                    "Confirm the baseline encoding and years in the scenario dialog."
                )
            )
        for key, _label, _result, _bands in RESULTS:
            selection = project["selections"].get(key)
            job = self._selected(key)
            if not selection:
                text = self.tr("No result selected.")
            elif job is None:
                text = self.tr("Dataset unavailable; restore it or choose another.")
            elif selection.get("area_sha256") != project["area"].get("sha256"):
                text = self.tr(
                    "Selected before the project area changed; review or rerun."
                )
            else:
                text = self._lineage_status(key, job)
            self.status_labels[key].setText(text)

    def _lineage_status(self, key, job):
        if key in ("arr", "land_types"):
            return self.tr(
                "Selected; verify that this dataset covers the project area."
            )
        if not job_manager.ensure_params_loaded(job):
            return self.tr("Input lineage unavailable; inspect the dataset before use.")
        params = job.params or {}
        if key == "priority":
            arr = self._selected("arr")
            if arr is None:
                return self.tr("Select an ARR classification to check its input.")
            from .calculate_ldn_priority import job_raster_path

            try:
                path, _result = job_raster_path(arr)
            except ValueError as exc:
                return self.tr("Cannot check ARR input: %s") % str(exc)
            recorded = params.get("arr_layer_path")
            if not recorded:
                return self.tr("ARR input not recorded; inspect this result.")
            if recorded != path:
                return self.tr("Different ARR input from the selected classification.")
            return self.tr(
                "Uses the selected ARR path; input changes are not verified."
            )
        if key == "candidate":
            priority = self._selected("priority")
            recorded = params.get("priority_job_id")
            if not recorded:
                return self.tr("Priority lineage not recorded; inspect this result.")
            if priority is None:
                return self.tr("Source priority: %s") % recorded
            if recorded != str(priority.id):
                return self.tr("Uses a different priority preview.")
            return self.tr(
                "Uses the selected priority preview; review before approval."
            )
        arr = self._selected("arr")
        if arr is not None:
            from .calculate_ldn_priority import job_raster_path

            try:
                arr_path, _result = job_raster_path(arr)
            except ValueError as exc:
                return self.tr("Cannot check ARR input: %s") % str(exc)
            if params.get("arr_layer_path") != arr_path:
                return self.tr("Scenario uses a different or unrecorded ARR input.")
        baseline = self._selected_baseline()
        if baseline is not None and (
            params.get("status_baseline_path") != str(baseline.path)
            or params.get("status_baseline_band_index", 1) != baseline.band_index
        ):
            return self.tr(
                "Scenario uses a different or unrecorded baseline indicator."
            )
        targets = params.get("targets") or []
        source_ids = {target.get("source_job_id") for target in targets}
        candidate = self._selected("candidate")
        if candidate is not None and str(candidate.id) not in source_ids:
            return self.tr(
                "Does not reference the selected candidate dataset; "
                "it may use other or polygon targets."
            )
        return self.tr(
            "Scenario is a saved snapshot. Check its inputs and assumptions in the summary."
        )

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
            launch_calculate_dialog(self._main_dock, factory, **kwargs)
            self.refresh()

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
        if land_types is not None:
            kwargs["preselect_land_type_job_id"] = str(land_types.id)
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
        self._launch(selection_factory, preselect_priority_job_id=str(priority.id))

    def _scenario(self, comparison=None):
        project = self._project()
        if project is None:
            return
        arr = self._selected("arr")
        candidate = self._selected("candidate")
        land_types = self._selected("land_types")
        baseline = self._selected_baseline()
        for key, selected in (
            ("arr", arr),
            ("baseline", baseline),
            ("land_types", land_types),
            ("candidate", candidate),
        ):
            if project["selections"].get(key) and selected is None:
                QtWidgets.QMessageBox.warning(
                    self,
                    self.tr("Dataset unavailable"),
                    self.tr(
                        "A selected scenario input is unavailable. Restore it or "
                        "explicitly clear or replace the selection before continuing."
                    ),
                )
                return
        kwargs = {}
        if arr is not None:
            kwargs["preselect_arr_job_id"] = str(arr.id)
        if candidate is not None:
            kwargs["preselect_candidate_job_id"] = str(candidate.id)
        if land_types is not None:
            kwargs["preselect_land_type_job_id"] = str(land_types.id)
        if baseline is not None:
            kwargs["preselect_baseline_job_id"] = str(baseline.job.id)
            kwargs["preselect_baseline_band_index"] = baseline.band_index
        if comparison is not None:
            kwargs["preselect_comparison_job_id"] = str(comparison.id)
        self._launch(projection_factory, **kwargs)

    def _compare(self):
        scenario = self._selected("scenario")
        if scenario is None:
            QtWidgets.QMessageBox.information(
                self, self.tr("Select scenario"), self.tr("Choose a scenario first.")
            )
            return
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
    global _panel
    if _panel is None:
        iface = main_dock.iface
        _panel = PlanningPanel(main_dock, iface.mainWindow())
        iface.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, _panel)
    _panel.refresh()
    _panel.show()
    _panel.raise_()
    return _panel


def close_panel():
    global _panel
    if _panel is not None:
        _panel.dispose()
        _panel.close()
        _panel._main_dock.iface.removeDockWidget(_panel)
        _panel.deleteLater()
        _panel = None
