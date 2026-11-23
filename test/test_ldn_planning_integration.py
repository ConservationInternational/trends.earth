"""Integration tests for the embedded LDN Planning tab.

Every planning step is run from the panel through the real calculation dialogs,
the job manager's local task path, the on-disk job store and the panel's signal
handlers. Only network lookups and modal ``exec()`` loops are replaced: dialogs
are shown and submitted with their OK button; scenarios run from the tab.
"""

import contextlib
import json
import sys
import unittest
import uuid
from pathlib import Path
from traceback import format_exception
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from e2e.harness import MainDockStub, isolated_plugin_state
from osgeo import gdal, osr
from qgis.PyQt import QtCore, QtWidgets
from te_algorithms.common.checksum import file_checksum
from te_algorithms.gdal.land_deg import config as ld_config
from te_algorithms.gdal.land_deg.ldn_planning_inputs import area_checksum
from te_schemas import jobs as te_jobs
from te_schemas.results import (
    URI,
    DataType,
    Raster,
    RasterFileType,
    RasterResults,
)
from te_schemas.results import Band as JobBand

from LDMP import conf, data_io
from LDMP.calculate import DlgCalculateBase
from LDMP.calculate_ldn_planning import (
    DlgCalculateLDNPlanningHotspots,
    DlgConfigureCandidateTargets,
)
from LDMP.calculate_ldn_priority import job_raster_path
from LDMP.jobs.manager import job_manager
from LDMP.jobs.models import Job
from LDMP.ldn_planning_actions import (
    report_files,
    select_job_band,
)
from LDMP.ldn_planning_panel import PlanningPanel

SIZE = 10
PIXEL = 0.01
ORIGIN = (0.0, 1.0)
CLASSES = ("avoid", "reduce", "reverse")
PANEL_KEYS = ("arr", "land_types", "priority", "candidate", "scenario")
ALL_MATCH = dict.fromkeys(PANEL_KEYS, "match")
AOI_SETTINGS = (
    conf.Setting.AREA_FROM_OPTION,
    conf.Setting.AREA_NAME,
    conf.Setting.BUFFER_CHECKED,
    conf.Setting.BUFFER_SIZE,
    conf.Setting.COUNTRY_ID,
    conf.Setting.VECTOR_FILE_PATH,
)


def write_raster(path, bands, gdal_type=gdal.GDT_Float32, nodata=-32768):
    bands = [np.asarray(values) for values in bands]
    rows, cols = bands[0].shape
    dataset = gdal.GetDriverByName("GTiff").Create(
        str(path), cols, rows, len(bands), gdal_type
    )
    dataset.SetGeoTransform((ORIGIN[0], PIXEL, 0, ORIGIN[1], 0, -PIXEL))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    dataset.SetProjection(srs.ExportToWkt())
    for index, values in enumerate(bands, start=1):
        band = dataset.GetRasterBand(index)
        band.SetNoDataValue(nodata)
        band.WriteArray(values)
    dataset = None
    return Path(path)


def write_aoi(path, west, south, east, north):
    geometry = {
        "type": "Polygon",
        "coordinates": [
            [[west, south], [east, south], [east, north], [west, north], [west, south]]
        ],
    }
    Path(path).write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "properties": {}, "geometry": geometry}
                ],
            }
        )
    )
    return Path(path)


def sdg_job(path, task_name, year_initial, year_final):
    """A downloaded SDG 15.3.1 indicator dataset as the panel would discover it."""
    band = JobBand(
        name=ld_config.SDG_BAND_NAME,
        no_data_value=-32768.0,
        metadata={"year_initial": year_initial, "year_final": year_final},
    )
    uri = URI(uri=path)
    extent = (
        ORIGIN[0],
        ORIGIN[1] - SIZE * PIXEL,
        ORIGIN[0] + SIZE * PIXEL,
        ORIGIN[1],
    )
    return Job(
        id=uuid.uuid4(),
        params={},
        progress=100,
        start_date=job_manager_now(),
        end_date=job_manager_now(),
        status=te_jobs.JobStatus.GENERATED_LOCALLY,
        local_context=te_jobs.JobLocalContext(
            base_dir=conf.settings_manager.get_value(conf.Setting.BASE_DIR),
            area_of_interest_name="Planning test area",
        ),
        results=RasterResults(
            name="sdg-15-3-1-summary",
            uri=uri,
            rasters={
                DataType.INT16.value: Raster(
                    uri=uri,
                    bands=[band],
                    datatype=DataType.INT16,
                    filetype=RasterFileType.GEOTIFF,
                    extent=extent,
                )
            },
        ),
        task_name=task_name,
        task_notes="",
        script=conf.KNOWN_SCRIPTS["sdg-15-3-1-summary"],
    )


def job_manager_now():
    import datetime as dt

    return dt.datetime.now(dt.timezone.utc)


def run_task_synchronously(task):
    """Run a submitted QgsTask on the calling thread, like the task manager."""
    task.finished(task.run())
    return True


class PlanningWorkflow(contextlib.ExitStack):
    """Isolated plugin state, inputs, an open panel and dialog automation."""

    def __enter__(self):
        super().__enter__()
        self.base_dir = self.enter_context(isolated_plugin_state())
        saved = {s: conf.settings_manager.get_value(s) for s in AOI_SETTINGS}
        self.callback(
            lambda: [conf.settings_manager.write_value(s, v) for s, v in saved.items()]
        )
        self.inputs = self.base_dir / "inputs"
        self.inputs.mkdir()
        self.aoi_path = write_aoi(self.inputs / "aoi.geojson", 0, 0.9, 0.1, 1.0)
        self.other_aoi_path = write_aoi(
            self.inputs / "other.geojson", 0.02, 0.92, 0.08, 0.98
        )
        self.set_area(self.aoi_path)
        conf.settings_manager.write_value(
            conf.Setting.AREA_FROM_OPTION, conf.AreaSetting.VECTOR_LAYER.value
        )
        conf.settings_manager.write_value(conf.Setting.BUFFER_CHECKED, False)
        conf.settings_manager.write_value(conf.Setting.COUNTRY_ID, "")
        conf.settings_manager.write_value(conf.Setting.AREA_NAME, "Planning area")

        self.errors = []
        self.exceptions = []
        # PyQt reports slot exceptions through a custom excepthook instead of
        # aborting the interpreter.
        self.enter_context(
            patch.object(
                sys,
                "excepthook",
                lambda *exc: self.exceptions.append("".join(format_exception(*exc))),
            )
        )
        self.warnings = []
        self.dialog_actions = []
        self.submitted = []
        for target, value in (
            # calculate and region_selector share LDMP.download.
            ("LDMP.download.get_admin_bounds", {"country": {}}),
            ("LDMP.download.get_cities", {"city": {}}),
            ("LDMP.region_selector.get_admin_bbox", None),
        ):
            self.enter_context(patch(target, return_value=value))
        self.enter_context(patch("LDMP.jobs.manager.iface", Mock()))
        self.enter_context(
            patch.object(job_manager.tm, "addTask", side_effect=run_task_synchronously)
        )
        self.enter_context(
            patch.object(QtWidgets.QMessageBox, "critical", side_effect=self._error)
        )
        self.enter_context(
            patch.object(QtWidgets.QMessageBox, "warning", side_effect=self._warning)
        )
        self.enter_context(
            patch.object(
                QtWidgets.QMessageBox, "information", side_effect=self._warning
            )
        )
        self.enter_context(
            patch.object(
                QtWidgets.QMessageBox,
                "question",
                return_value=QtWidgets.QMessageBox.StandardButton.Yes,
            )
        )
        self.enter_context(
            patch.object(DlgCalculateBase, "exec", new=lambda dialog: self._run(dialog))
        )
        job_manager.submitted_local_job.connect(self.submitted.append)
        self.callback(job_manager.submitted_local_job.disconnect, self.submitted.append)

        self.main_dock = MainDockStub()
        self.main_dock.iface = Mock()
        self.main_dock.pause_scheduler = Mock()
        self.main_dock.resume_scheduler = Mock()
        self.main_dock.tabWidget = QtWidgets.QTabWidget(self.main_dock)
        for name in ("Algorithms", "Datasets", "News"):
            self.main_dock.tabWidget.addTab(QtWidgets.QWidget(), name)
        self.main_dock._PLANNING_TAB_PAGE = 2
        self.main_dock._NEWS_TAB_PAGE = 3
        self.callback(self._delete_widgets)
        self.settings = QtCore.QSettings(
            str(self.base_dir / "panel.ini"), QtCore.QSettings.Format.IniFormat
        )
        self._create_inputs()
        self.panel = self.open_panel()
        with patch.object(
            QtWidgets.QInputDialog, "getText", return_value=("Plan", True)
        ):
            self.panel._new_project()
        return self

    def open_panel(self):
        from LDMP.main_widget import MainWidget

        existing = getattr(self.main_dock, "planning_panel", None)
        if existing is not None:
            existing.dispose()
            index = self.main_dock.tabWidget.indexOf(existing)
            self.main_dock.tabWidget.removeTab(index)
        with patch(
            "LDMP.ldn_planning_panel.PlanningPanel",
            side_effect=lambda main, parent: PlanningPanel(main, parent, self.settings),
        ):
            MainWidget.setup_planning_tab(self.main_dock)
        panel = self.main_dock.planning_panel
        self.panel = panel
        self.callback(panel.deleteLater)
        self.callback(panel.dispose)
        return panel

    def _delete_widgets(self):
        # Delete Qt objects before interpreter shutdown; QGIS 4 can crash if
        # they are left for Python's finalizer.
        self.main_dock.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(
            None, QtCore.QEvent.Type.DeferredDelete
        )

    def set_area(self, path):
        from LDMP.areaofinterest import invalidate_aoi_cache

        conf.settings_manager.write_value(conf.Setting.VECTOR_FILE_PATH, str(path))
        invalidate_aoi_cache()
        data_io.invalidate_usable_data_caches()

    def area_checksum(self):
        from LDMP.areaofinterest import prepare_area_of_interest

        return area_checksum(prepare_area_of_interest().get_geojson())

    def _error(self, _parent, title, text, *args, **kwargs):
        self.errors.append(f"{title}: {text}")
        return QtWidgets.QMessageBox.StandardButton.Ok

    def _warning(self, _parent, title, text, *args, **kwargs):
        self.warnings.append(f"{title}: {text}")
        return QtWidgets.QMessageBox.StandardButton.Ok

    def _run(self, dialog):
        """Replacement for ``exec()``: show, configure, then press OK."""
        dialog.show()
        QtWidgets.QApplication.processEvents()
        action = self.dialog_actions.pop(0)
        if action(dialog) is False:
            dialog.reject()
            return QtWidgets.QDialog.DialogCode.Rejected
        dialog.button_box.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).click()
        QtWidgets.QApplication.processEvents()
        return QtWidgets.QDialog.DialogCode.Accepted

    def _create_inputs(self):
        rows = np.arange(SIZE)[:, None] * np.ones((1, SIZE))
        cols = np.ones((SIZE, 1)) * np.arange(SIZE)[None, :]
        # Degraded west, stable centre and improving east.
        baseline = np.where(cols < 3, -1, np.where(cols < 7, 0, 1))
        reporting = np.where(cols < 4, -1, np.where(cols < 7, 0, 1))
        later = np.where(cols < 2, -1, np.where(cols < 6, 0, 1))
        risk = np.where(rows < 5, 0.9, 0.1)
        self.land_cover = write_raster(
            self.inputs / "land_cover.tif",
            [np.where(rows < 5, 1, 2)],
            gdal.GDT_Int16,
            nodata=0,
        )
        self.soil = write_raster(
            self.inputs / "soil.tif", [np.where(cols < 5, 1, 2)], gdal.GDT_Int16, 0
        )
        self.risk = write_raster(self.inputs / "risk.tif", [risk])
        self.capital = write_raster(
            self.inputs / "capital.tif", [(rows * SIZE + cols) / (SIZE * SIZE - 1)]
        )
        self.baselines = {}
        for name, values, years in (
            ("baseline", baseline, (2000, 2015)),
            ("reporting", reporting, (2004, 2019)),
            ("alternate", later, (2000, 2015)),
        ):
            path = write_raster(self.inputs / f"{name}.tif", [values], gdal.GDT_Int16)
            job = sdg_job(path, f"SDG {name}", *years)
            job_manager.write_job_metadata_file(job)
            job_manager.import_job(job, job_manager.get_job_file_path(job))
            self.baselines[name] = job
        self.capital_input = job_manager.register_planning_input_job(
            str(self.capital), "Natural capital", "", {"source": "Test inventory"}
        )
        from LDMP.ldn_planning_assets import save_scoring_profile

        self.profile = save_scoring_profile(
            self.capital_input,
            {
                "name": "Higher capital",
                "band_index": 1,
                "minimum": 0,
                "maximum": 1,
                "direction": "higher",
                "resampling": "nearest",
            },
        )
        QtWidgets.QApplication.processEvents()

    # ------------------------------------------------------------------
    # Running steps
    # ------------------------------------------------------------------

    def run_step(self, key, action):
        """Click a panel section button and return the job it created."""
        before = len(self.submitted)
        section = {
            "arr": "prepare",
            "land_types": "prepare",
            "priority": "ranking",
            "candidate": "candidates",
            "scenario": "scenario",
        }[key]
        self.panel.section_groups[section].setChecked(True)
        if key == "scenario":
            action(self.panel.scenario_editor)
        else:
            self.dialog_actions.append(action)
        self.panel.step_buttons[key].click()
        QtWidgets.QApplication.processEvents()
        self.assertion.assertEqual(self.exceptions, [])
        self.assertion.assertEqual(self.dialog_actions, [])
        self.assertion.assertEqual(self.errors, [])
        created = self.submitted[before:]
        self.assertion.assertEqual(len(created), 1, f"{key} did not submit one job")
        job = created[0]
        self.assertion.assertEqual(
            job.status,
            te_jobs.JobStatus.GENERATED_LOCALLY,
            f"{key} failed: {job.status}",
        )
        if key in ("arr", "land_types", "candidate"):
            self.assertion.assertEqual(
                self.panel.combos[key].currentData(), str(job.id)
            )
        return job

    def select(self, key, job):
        combo = self.panel.combos[key]
        index = combo.findData(str(job.id))
        self.assertion.assertGreater(index, 0, f"{key} result missing from dropdown")
        combo.setCurrentIndex(index)

    def select_baseline(self, name, band_index=1):
        index = self.panel.baseline_combo.findData(
            f"{self.baselines[name].id}:{band_index}"
        )
        self.assertion.assertGreater(index, 0, f"{name} missing from baseline list")
        self.panel.baseline_combo.setCurrentIndex(index)

    def states(self):
        return {
            key: self.panel.status_icons[key].property("lineage_state")
            for key in PANEL_KEYS
        }

    def summary(self, key):
        """Return the compact inline details for a selected result."""
        return self.panel.result_summary_labels[key].text()


def report(job):
    job_manager.ensure_results_loaded(job)
    return job.results.data["report"]


def class_areas(arr_report):
    return arr_report["arr_summary"]["class_areas_km2"]


class LDNPlanningIntegrationTests(unittest.TestCase):
    """End-to-end planning chain through the panel, dialogs and job store."""

    maxDiff = None

    def workflow(self):
        workflow = PlanningWorkflow()
        workflow.assertion = self
        return workflow

    # Dialog actions ----------------------------------------------------

    def define_land_types(self, workflow, *paths):
        def action(dialog):
            for path in paths:
                dialog.raster_list.addItem(str(path))
            dialog._update_info()

        return workflow.run_step("land_types", action)

    def create_arr(self, workflow, baseline="baseline", threshold=0.5):
        def action(dialog):
            band_jobs = {str(band.job.id) for band in dialog.combo_status.layer_list}
            self.assertEqual(
                band_jobs, {str(job.id) for job in workflow.baselines.values()}
            )
            select_job_band(
                dialog.combo_status, workflow.baselines[baseline].id, dialog, "status"
            )
            dialog.chk_use_risk.setChecked(True)
            dialog._risk_path = str(workflow.risk)
            dialog.spin_risk_threshold.setValue(threshold)

        return workflow.run_step("arr", action)

    def prioritize(self, workflow, arr, land_types, add_criteria=True):
        def action(dialog):
            self.assertEqual(
                str(dialog.combo_arr.get_current_band().job.id), str(arr.id)
            )
            self.assertFalse(dialog.combo_arr.isVisible())
            self.assertIn("Using project inputs", dialog.project_context_label.text())
            self.assertTrue(dialog.change_project_button.isVisible())
            self.assertEqual(
                dialog.combo_land_types.currentData(),
                str(land_types.id) if land_types else None,
            )
            if not add_criteria:
                self.assertEqual(len(dialog.entries), 3)
                return
            label = "%s (rev %s)" % (self.profile_name, 1)
            for arr_class in CLASSES:
                with patch.object(
                    QtWidgets.QInputDialog, "getItem", return_value=(label, True)
                ):
                    dialog._configure_entry_for_job(workflow.capital_input)
                dialog._entry_changed(len(dialog.entries) - 1, arr_class=arr_class)
            self.assertEqual(
                [dialog.criteria_table.item(row, 5).text() for row in range(3)],
                ["100%"] * 3,
            )

        return workflow.run_step("priority", action)

    profile_name = "Higher capital"

    def select_candidates(self, workflow, priority, selections=None):
        def action(dialog):
            self.assertEqual(dialog.combo_priority.currentData(), str(priority.id))
            self.assertFalse(dialog.combo_priority.isVisible())
            self.assertIn("Using project ranking", dialog.project_context_label.text())
            self.assertTrue(dialog.change_project_button.isVisible())
            if selections is None:
                return
            for key, (enabled, mode, threshold, area) in dialog.rows.items():
                selected = selections.get(key)
                enabled.setChecked(selected is not None)
                if selected:
                    mode.setCurrentIndex(mode.findData(selected["mode"]))
                    threshold.setValue(selected.get("threshold", 0.8))
                    area.setValue(selected.get("area_km2", 100))

        return workflow.run_step("candidate", action)

    def build_scenario(self, workflow, arr, land_types, candidate, baseline):
        panel = workflow.panel
        workflow.select_baseline(baseline)
        panel.reporting_combo.setCurrentIndex(
            panel.reporting_combo.findData(f"{workflow.baselines['reporting'].id}:1")
        )
        self.assertEqual(
            (panel.years["year_initial"].value(), panel.years["year_final"].value()),
            (2004, 2019),
        )
        panel.years["target_year"].setValue(2030)
        panel.breakdown_combo.setCurrentIndex(panel.breakdown_combo.findData("saved"))

        def action(dialog):
            self.assertEqual(panel.combos["arr"].currentData(), str(arr.id))
            self.assertEqual(
                panel.combos["land_types"].currentData(), str(land_types.id)
            )
            self.assertEqual(panel.combos["candidate"].currentData(), str(candidate.id))
            self.assertFalse(hasattr(dialog, "combo_arr"))
            self.assertFalse(hasattr(dialog, "combo_baseline"))
            self.assertFalse(hasattr(dialog, "combo_candidates"))
            dialog.default_effectiveness = 0.5

            def configure(target_dialog):
                target_dialog.default_effectiveness.setValue(0.5)
                target_dialog._accept()
                return QtWidgets.QDialog.DialogCode.Accepted

            with patch.object(DlgConfigureCandidateTargets, "exec", new=configure):
                dialog.btn_configure_candidates.click()
            self.assertEqual(dialog.targets_list.count(), 0, workflow.errors)
            self.assertIn(
                "Configured effectiveness", dialog.candidate_summary.text()
            )

        return workflow.run_step("scenario", action)

    def expect_states(self, workflow, **expected):
        states = workflow.states()
        texts = {key: workflow.panel.status_labels[key].text() for key in PANEL_KEYS}
        for key in PANEL_KEYS:
            self.assertEqual(
                states[key], expected.get(key, "empty"), f"{key}: {texts[key]}"
            )
        return texts

    def build_chain(self, workflow):
        self.expect_states(workflow)
        land_types = self.define_land_types(
            workflow, workflow.land_cover, workflow.soil
        )
        workflow.select("land_types", land_types)
        self.expect_states(workflow, land_types="match")
        arr = self.create_arr(workflow)
        workflow.select("arr", arr)
        self.expect_states(workflow, land_types="match", arr="match")
        workflow.select_baseline("baseline")
        priority = self.prioritize(workflow, arr, land_types)
        workflow.select("priority", priority)
        self.expect_states(workflow, **dict.fromkeys(PANEL_KEYS[:3], "match"))
        candidate = self.select_candidates(
            workflow,
            priority,
            {
                "avoid": {"mode": "threshold", "threshold": 0.5},
                "reverse": {"mode": "area", "area_km2": 5},
            },
        )
        workflow.select("candidate", candidate)
        self.expect_states(workflow, **dict.fromkeys(PANEL_KEYS[:4], "match"))
        scenario = self.build_scenario(workflow, arr, land_types, candidate, "baseline")
        workflow.select("scenario", scenario)
        self.expect_states(workflow, **ALL_MATCH)
        return dict(
            land_types=land_types,
            arr=arr,
            priority=priority,
            candidate=candidate,
            scenario=scenario,
        )

    def combo_jobs(self, workflow, key):
        combo = workflow.panel.combos[key]
        return [combo.itemData(index) for index in range(1, combo.count())]

    # Tests ---------------------------------------------------------------

    def test_small_tab_can_reach_scenario_and_restore_collapsed_controls(self):
        from LDMP.ldn_planning_panel import open_panel

        with self.workflow() as workflow:
            self.build_chain(workflow)
            panel = open_panel(workflow.main_dock)
            panel.combos["arr"].setItemText(
                panel.combos["arr"].currentIndex(),
                "ARR classification for a planning area with a very long descriptive name",
            )
            for width in (480, 360):
                workflow.main_dock.resize(width, 720)
                workflow.main_dock.tabWidget.setGeometry(0, 0, width, 720)
                QtWidgets.QApplication.processEvents()
                viewport_width = panel.scroll.viewport().width()
                self.assertLessEqual(panel.width(), width)
                self.assertLessEqual(panel.scroll.widget().width(), viewport_width)
                self.assertEqual(panel.scroll.horizontalScrollBar().maximum(), 0)
                controls = panel.scroll.widget().findChildren(
                    QtWidgets.QPushButton
                ) + panel.scroll.widget().findChildren(QtWidgets.QComboBox)
                for control in controls:
                    if control.isVisible():
                        right_edge = control.mapTo(
                            panel.scroll.widget(), QtCore.QPoint(0, 0)
                        ).x() + control.width()
                        self.assertLessEqual(
                            control.width(),
                            viewport_width,
                            f"{type(control).__name__} exceeds {width}px panel",
                        )
                        self.assertLessEqual(right_edge, panel.scroll.widget().width())
            panel.scroll.ensureWidgetVisible(panel.scenario_editor)
            panel.scenario_group.setChecked(False)
            QtWidgets.QApplication.processEvents()
            self.assertFalse(panel.scenario_editor.isVisible())
            panel.scenario_group.setChecked(True)
            QtWidgets.QApplication.processEvents()
            self.assertTrue(panel.scenario_editor.isVisible())
            panel.scroll.ensureWidgetVisible(
                panel.map_buttons["candidate"]
            )
            panel.section_groups["candidates"].setChecked(True)
            panel.map_buttons["candidate"].setFocus()
            self.assertTrue(panel.map_buttons["candidate"].hasFocus())
            self.assertNotIn(
                "Summary...",
                [button.text() for button in panel.findChildren(QtWidgets.QPushButton)],
            )
            project_id = panel._project()["id"]
            panel.section_groups["ranking"].setChecked(True)
            panel.section_groups["candidates"].setChecked(False)
            panel.section_groups["prepare"].setChecked(False)
            panel.refresh()
            self.assertTrue(panel.section_groups["ranking"].isChecked())
            self.assertFalse(panel.section_groups["candidates"].isChecked())
            self.assertFalse(panel.section_groups["prepare"].isChecked())
            self.assertTrue(
                panel._settings.value(
                    f"trends_earth/ldn_planning_view/{project_id}"
                )
            )
            self.assertEqual(workflow.exceptions + workflow.errors, [])

    def test_embedded_navigation_preserves_draft_and_candidate_targets_for_alternatives(
        self,
    ):
        from LDMP.ldn_planning_panel import open_panel

        with self.workflow() as workflow:
            chain = self.build_chain(workflow)
            panel = workflow.panel
            original_params = json.dumps(chain["scenario"].params, sort_keys=True)
            self.assertEqual(
                [workflow.main_dock.tabWidget.tabText(i) for i in range(4)],
                ["Algorithms", "Datasets", "LDN Planning", "News"],
            )
            panel.scenario_editor.task_notes.setPlainText("Alternative assumptions")
            targets = panel._draft()["targets"]
            for index in (1, 3, 0, 2):
                workflow.main_dock.tabWidget.setCurrentIndex(index)
            self.assertIs(open_panel(workflow.main_dock), panel)
            self.assertEqual(panel._draft()["targets"], targets)
            with patch.object(DlgConfigureCandidateTargets, "exec") as target_dialog:
                scenario = workflow.run_step("scenario", lambda editor: None)
            target_dialog.assert_not_called()
            self.assertEqual(
                scenario.params["planning_project_id"], panel._project()["id"]
            )
            self.assertEqual(scenario.params["planning_draft_id"], panel._draft()["id"])
            self.assertEqual(
                json.dumps(chain["scenario"].params, sort_keys=True), original_params
            )
            self.assertEqual(
                panel.combos["scenario"].currentData(), str(chain["scenario"].id)
            )
            panel.use_result_button.click()
            self.assertEqual(panel.combos["scenario"].currentData(), str(scenario.id))
            panel._alternative()
            self.assertEqual(panel._draft()["targets"], targets)
            self.assertNotEqual(
                panel._draft()["id"], scenario.params["planning_draft_id"]
            )
            reopened = workflow.open_panel()
            self.assertEqual(reopened._draft()["targets"], targets)
            self.assertEqual(
                reopened.scenario_editor.task_notes.toPlainText(),
                "Alternative assumptions",
            )
            self.assertEqual(workflow.exceptions + workflow.errors, [])

    def test_changed_effectiveness_and_mask_require_target_reconfiguration(self):
        import copy

        with self.workflow() as workflow:
            chain = self.build_chain(workflow)
            panel = workflow.panel
            editor = panel.scenario_editor
            before = copy.deepcopy(panel._draft()["targets"])
            with patch.object(
                editor, "_configure_candidate_targets", return_value=None
            ):
                editor._configure_candidates()
            self.assertEqual(panel._draft()["targets"], before)
            editor._targets[0]["effectiveness"] = 0.9
            editor.changed.emit()
            submitted = len(workflow.submitted)
            panel.step_buttons["scenario"].click()
            self.assertEqual(len(workflow.submitted), submitted)
            self.assertIn(
                "candidate target settings no longer match",
                workflow.errors.pop().lower(),
            )
            editor._targets = copy.deepcopy(before)
            editor.changed.emit()
            mask_path, _ = job_raster_path(chain["candidate"])
            dataset = gdal.Open(mask_path, gdal.GA_Update)
            dataset.GetRasterBand(1).Fill(0)
            dataset = None
            panel.step_buttons["scenario"].click()
            self.assertEqual(len(workflow.submitted), submitted)
            self.assertIn("Candidate raster changed.", workflow.errors.pop())

    def test_optional_inputs_are_explicit_and_zero_target_run_never_picks_defaults(
        self,
    ):
        with self.workflow() as workflow:
            chain = self.build_chain(workflow)
            panel = workflow.panel
            panel._new_draft()
            panel.reporting_combo.setCurrentIndex(0)
            panel.breakdown_combo.setCurrentIndex(
                panel.breakdown_combo.findData("none")
            )
            submitted = len(workflow.submitted)
            with patch.object(
                QtWidgets.QMessageBox,
                "question",
                return_value=QtWidgets.QMessageBox.StandardButton.No,
            ):
                panel.step_buttons["scenario"].click()
            self.assertEqual(len(workflow.submitted), submitted)

            def change_region(*_args, **_kwargs):
                workflow.set_area(workflow.other_aoi_path)
                return QtWidgets.QMessageBox.StandardButton.Yes

            with patch.object(
                QtWidgets.QMessageBox, "question", side_effect=change_region
            ):
                panel.step_buttons["scenario"].click()
            self.assertEqual(len(workflow.submitted), submitted)
            self.assertIn("changed while preparing", workflow.errors.pop())
            workflow.set_area(workflow.aoi_path)
            panel.refresh()
            scenario = workflow.run_step("scenario", lambda editor: None)
            self.assertIsNone(scenario.params["status_reporting_path"])
            self.assertIsNone(scenario.params["land_type_path"])
            self.assertIsNone(scenario.params["jurisdictions_path"])
            self.assertEqual(scenario.params["targets"], [])
            projection = scenario.results.data["projection"]
            self.assertEqual(
                (projection["year_initial"], projection["year_final"]), (2000, 2015)
            )
            self.assertIsNone(projection["degraded_area_reporting_km2"])
            self.assertIsNotNone(projection["bau_projection_km2"])
            self.assertEqual(
                panel.combos["scenario"].currentData(), str(chain["scenario"].id)
            )
            self.assertEqual(workflow.exceptions + workflow.errors, [])

    def test_completion_updates_originating_draft_not_visible_project(self):
        with self.workflow() as workflow:
            chain = self.build_chain(workflow)
            panel = workflow.panel
            origin = panel._project()
            draft = panel._draft()
            draft.pop("latest_result_id", None)
            with patch.object(
                QtWidgets.QInputDialog, "getText", return_value=("Other project", True)
            ):
                panel._new_project()
            self.assertNotEqual(panel._project()["id"], origin["id"])
            job_manager.processed_local_job.emit(chain["scenario"])
            QtWidgets.QApplication.processEvents()
            self.assertEqual(draft["latest_result_id"], str(chain["scenario"].id))
            self.assertNotIn("latest_result_id", panel._draft())
            self.assertIsNone(panel.combos["scenario"].currentData())
            self.assertEqual(panel.completion_label.text(), "")

    def test_comparison_preflight_rejects_changed_reference_period(self):
        with self.workflow() as workflow:
            chain = self.build_chain(workflow)
            panel = workflow.panel
            before = len(workflow.submitted)
            panel._compare()
            QtWidgets.QApplication.processEvents()
            self.assertEqual(len(workflow.submitted), before + 1, workflow.errors)
            comparison = workflow.submitted[-1]
            self.assertEqual(
                comparison.params["comparison"]["job_id"], str(chain["scenario"].id)
            )
            self.assertIn("scenario_comparison", comparison.results.data["report"])
            before = len(workflow.submitted)
            panel.years["target_year"].setValue(2040)
            self.assertEqual(workflow.states()["scenario"], "stale")
            panel._compare()
            self.assertEqual(len(workflow.submitted), before)
            self.assertIn("target_year", workflow.errors.pop())
            panel._clear_comparison()
            self.assertIsNone(panel._draft()["comparison_job_id"])

    def test_comparison_uses_downloaded_boundary_checksums(self):
        from LDMP import calculate_ldn_planning

        with self.workflow() as workflow:
            arr = self.create_arr(workflow)
            workflow.select("arr", arr)
            workflow.select_baseline("baseline")
            panel = workflow.panel
            conf.settings_manager.write_value(conf.Setting.COUNTRY_ID, "TST")
            index = panel.jurisdictions_combo.findData("admin")
            panel.jurisdictions_combo.setCurrentIndex(index)
            panel.jurisdictions_combo.activated.emit(index)
            boundary = json.loads(workflow.aoi_path.read_text())
            boundary["features"][0]["properties"]["shapeName"] = "District"
            resolve_admin = calculate_ldn_planning._resolve_admin_zones

            def tracked_admin(parent):
                path = resolve_admin(parent)
                self.assertIsNotNone(path)
                workflow.callback(Path(path).unlink, missing_ok=True)
                return path

            with (
                patch.object(
                    calculate_ldn_planning, "_resolve_admin_zones", tracked_admin
                ),
                patch("LDMP.download.download_boundary_geojson", return_value=boundary),
                patch(
                    "LDMP.download.get_admin_bounds",
                    return_value={
                        "Test country": SimpleNamespace(code="TST", level1_regions={})
                    },
                ),
            ):
                first = workflow.run_step("scenario", lambda editor: None)
                first_path = Path(first.params["jurisdictions_path"])
                first_path.unlink()
                workflow.select("scenario", first)
                before = len(workflow.submitted)
                panel._compare()
                QtWidgets.QApplication.processEvents()
                self.assertEqual(len(workflow.submitted), before + 1, workflow.errors)
                comparison = workflow.submitted[-1]
                self.assertEqual(comparison.status, te_jobs.JobStatus.GENERATED_LOCALLY)
                second_path = comparison.params["jurisdictions_path"]
                self.assertNotEqual(second_path, str(first_path))
                self.assertEqual(
                    first.params["input_checksums"]["jurisdictions_path"][
                        str(first_path)
                    ],
                    comparison.params["input_checksums"]["jurisdictions_path"][
                        second_path
                    ],
                )
                self.assertEqual(
                    comparison.params["comparison"]["parameters"]["jurisdictions_path"],
                    str(first_path),
                )
                self.assertEqual(
                    comparison.results.data["report"]["scenario_comparison"][
                        "previous_job_id"
                    ],
                    str(first.id),
                )

                boundary["features"][0]["properties"]["shapeName"] = "Changed"
                before = len(workflow.submitted)
                panel._compare()
                self.assertEqual(len(workflow.submitted), before)
                self.assertIn("jurisdiction boundary checksums", workflow.errors.pop())
                self.assertEqual(workflow.exceptions + workflow.errors, [])

    def test_polygon_snapshots_work_alone_and_with_candidates(self):
        with self.workflow() as workflow:
            self.build_chain(workflow)
            panel = workflow.panel
            path = write_aoi(workflow.inputs / "targets.geojson", 0, 0.9, 0.03, 1)
            data = json.loads(path.read_text())
            data["features"][0]["properties"] = {
                "intervention": "reverse",
                "effectiveness": 0.25,
            }
            path.write_text(json.dumps(data))
            target_job = job_manager.create_ldn_targets_layer_from_file(
                str(path),
                {
                    "intervention_field": "intervention",
                    "effectiveness_field": "effectiveness",
                    "effectiveness_units": "fraction",
                },
                "Drawn restoration",
            )
            QtWidgets.QApplication.processEvents()
            editor = panel.scenario_editor
            editor._refresh_targets_combo()
            editor.combo_targets_layer.setCurrentIndex(
                editor.combo_targets_layer.findData(str(target_job.id))
            )
            editor._load_targets_from_job()
            self.assertTrue(editor.use_polygons.isChecked())
            combined = workflow.run_step("scenario", lambda widget: None)
            self.assertEqual(len(combined.params["targets"]), 3)
            editor.use_candidates.setChecked(False)
            polygon_only = workflow.run_step("scenario", lambda widget: None)
            self.assertEqual(len(polygon_only.params["targets"]), 1)
            snapshot = polygon_only.params["targets"][0]
            self.assertEqual(snapshot["effectiveness"], 0.25)
            self.assertIn("geometry_crs", snapshot)
            self.assertIn("wkt_geometry", snapshot)
            self.assertEqual(workflow.exceptions + workflow.errors, [])

    def test_dataset_shortcut_requires_project_choice_and_uses_embedded_tab(self):
        from LDMP.ldn_planning_actions import attach_planning_actions

        with self.workflow() as workflow:
            chain = self.build_chain(workflow)
            panel = workflow.panel
            origin_name = panel._project()["name"]
            with patch.object(
                QtWidgets.QInputDialog, "getText", return_value=("Other project", True)
            ):
                panel._new_project()
            other_id = panel._project()["id"]
            button = QtWidgets.QPushButton(workflow.main_dock)
            self.assertTrue(
                attach_planning_actions(button, chain["candidate"], workflow.main_dock)
            )
            action = next(
                a for a in button.menu().actions() if a.text() == "Use in scenario..."
            )
            with patch.object(
                QtWidgets.QInputDialog, "getItem", return_value=("", False)
            ):
                action.trigger()
            self.assertEqual(panel._project()["id"], other_id)
            self.assertIsNone(panel.combos["candidate"].currentData())
            with patch.object(
                QtWidgets.QInputDialog, "getItem", return_value=(origin_name, True)
            ):
                action.trigger()
            self.assertEqual(panel._project()["name"], origin_name)
            self.assertEqual(
                panel.combos["candidate"].currentData(), str(chain["candidate"].id)
            )
            self.assertIs(workflow.main_dock.tabWidget.currentWidget(), panel)
            self.assertEqual(workflow.exceptions + workflow.errors, [])
            scripts = set()
            groups = [conf.ALGORITHM_TREE]
            while groups:
                group = groups.pop()
                groups.extend(group.groups)
                scripts.update(
                    entry.script.name
                    for algorithm in group.algorithms
                    for entry in algorithm.scripts
                )
            self.assertTrue(
                {"ldn-planning-hotspots", "ldn-counterbalancing"} <= scripts
            )
            self.assertFalse(
                {
                    "ldn-planning-arr",
                    "ldn-planning-land-types",
                    "ldn-planning-priority",
                    "ldn-planning-selection",
                    "ldn-planning-projection",
                }
                & scripts
            )

    def test_period_is_locked_to_band_metadata(self):
        with self.workflow() as workflow:
            panel = workflow.panel
            workflow.select_baseline("baseline")

            self.assertEqual(panel.years["year_initial"].value(), 2000)
            self.assertEqual(panel.years["year_final"].value(), 2015)
            self.assertEqual(panel.years["year_initial"].text(), "2000")
            self.assertEqual(panel.years["year_final"].text(), "2015")
            self.assertEqual(panel.years["target_year"].text(), "2030")
            self.assertEqual(panel.years["target_year"].value(), 2030)
            panel.input_context_group.setChecked(True)
            self.assertFalse(panel.years["year_initial"].isEnabled())
            self.assertFalse(panel.years["year_final"].isEnabled())
            self.assertTrue(
                panel.years["target_year"].isEnabled(),
                (
                    panel.scenario_group.isEnabled(),
                    panel.input_context_group.isEnabled(),
                    panel.context_group.isEnabled(),
                ),
            )
            self.assertEqual(panel.years["target_year"].minimum(), 2016)

            panel._project()["context"].update(year_initial=2005, year_final=2010)
            panel.refresh()
            context = panel._project()["context"]
            self.assertEqual(
                (context["year_initial"], context["year_final"]), (2000, 2015)
            )
            self.assertEqual(panel.years["target_year"].value(), 2030)

            # An indicator reporting band uses its own period.
            panel.reporting_combo.setCurrentIndex(
                panel.reporting_combo.findData(
                    f"{workflow.baselines['reporting'].id}:1"
                )
            )
            self.assertEqual(
                (
                    panel.years["year_initial"].value(),
                    panel.years["year_final"].value(),
                ),
                (2004, 2019),
            )
            panel.reporting_combo.setCurrentIndex(0)

            reporting_id = str(workflow.baselines["reporting"].id)
            reporting_band = panel._baseline_bands[f"{reporting_id}:1"]
            reporting_band.band_info.metadata["year_final"] = 2035
            workflow.select_baseline("reporting")
            self.assertEqual(panel.years["year_final"].value(), 2035)
            self.assertEqual(panel.years["target_year"].value(), 2036)
            self.assertEqual(panel.years["target_year"].minimum(), 2036)
            self.assertEqual(panel.years["target_year"].text(), "2036")
            panel.years["target_year"].setValue(2040)
            self.assertEqual(panel._project()["context"]["target_year"], 2040)

    def test_period_reads_status_metadata_and_spans_baseline_to_reporting(self):
        with self.workflow() as workflow:
            panel = workflow.panel
            bands = {
                name: panel._baseline_bands[f"{workflow.baselines[name].id}:1"]
                for name in ("baseline", "reporting")
            }
            bands["baseline"].band_info.metadata = {
                "baseline_year_initial": 2001,
                "baseline_year_final": 2015,
                "reporting_year_initial": 2004,
                "reporting_year_final": 2019,
            }
            bands["reporting"].band_info.metadata = {
                "baseline_year_initial": 2001,
                "baseline_year_final": 2015,
                "reporting_year_initial": 2008,
                "reporting_year_final": 2023,
            }
            workflow.select_baseline("baseline")
            self.assertEqual(panel.years["year_initial"].value(), 2001)
            self.assertEqual(panel.years["year_final"].value(), 2015)
            self.assertEqual(panel.years["year_initial"].text(), "2001")
            self.assertEqual(panel.years["year_final"].text(), "2015")

            panel.reporting_combo.setCurrentIndex(
                panel.reporting_combo.findData(
                    f"{workflow.baselines['reporting'].id}:1"
                )
            )
            context = panel._project()["context"]
            self.assertEqual(
                (context["year_initial"], context["year_final"]), (2001, 2023)
            )
            self.assertEqual(panel.years["year_final"].maximum(), 2023)
            self.assertEqual(panel.years["year_final"].text(), "2023")
            self.assertEqual(panel.years["target_year"].value(), 2030)

            panel.reporting_combo.setCurrentIndex(0)
            self.assertEqual(panel.years["year_final"].value(), 2015)

    def test_jurisdiction_picker_supports_builtin_and_custom_boundaries(self):
        with self.workflow() as workflow:
            panel = workflow.panel
            combo = panel.jurisdictions_combo

            def choose(source):
                index = combo.findData(source)
                combo.setCurrentIndex(index)
                combo.activated.emit(index)

            with patch.object(QtWidgets.QFileDialog, "getOpenFileName") as browse:
                choose("admin")
                browse.assert_not_called()
            self.assertEqual(panel._project()["context"]["jurisdictions"], "admin")

            with patch.object(
                QtWidgets.QFileDialog, "getOpenFileName", return_value=("", "")
            ):
                choose("file")
            self.assertEqual(combo.currentData(), "admin")
            self.assertEqual(panel._project()["context"]["jurisdictions"], "admin")

            custom_path = workflow.inputs / "jurisdictions.geojson"
            with patch.object(
                QtWidgets.QFileDialog,
                "getOpenFileName",
                return_value=(str(custom_path), ""),
            ) as browse:
                choose("file")
                browse.assert_called_once()
            context = panel._project()["context"]
            self.assertEqual(context["jurisdictions"], "file")
            self.assertEqual(context["jurisdictions_path"], str(custom_path))
            self.assertIn(custom_path.name, combo.currentText())
            self.assertEqual(combo.toolTip(), str(custom_path))

            with patch.object(
                QtWidgets.QFileDialog, "getOpenFileName", return_value=("", "")
            ):
                choose("file")
            self.assertEqual(context["jurisdictions_path"], str(custom_path))
            self.assertEqual(combo.currentData(), "file")

            replacement = workflow.inputs / "replacement.geojson"
            with patch.object(
                QtWidgets.QFileDialog,
                "getOpenFileName",
                return_value=(str(replacement), ""),
            ):
                choose("file")
            self.assertEqual(context["jurisdictions_path"], str(replacement))
            self.assertIn(replacement.name, combo.currentText())

            with patch.object(QtWidgets.QFileDialog, "getOpenFileName") as browse:
                panel = workflow.open_panel()
                browse.assert_not_called()
            combo = panel.jurisdictions_combo
            self.assertEqual(combo.currentData(), "file")
            self.assertIn(replacement.name, combo.currentText())
            self.assertEqual(combo.toolTip(), str(replacement))
            choose("none")
            self.assertEqual(panel._project()["context"]["jurisdictions"], "none")

    def test_full_chain_populates_dropdowns_and_consistent_reports(self):
        with self.workflow() as workflow:
            panel = workflow.panel
            for key in PANEL_KEYS:
                self.assertEqual(self.combo_jobs(workflow, key), [])
                self.assertEqual(panel.status_labels[key].text(), "No result selected.")
            self.assertEqual(
                {
                    panel.baseline_combo.itemData(index)
                    for index in range(1, panel.baseline_combo.count())
                },
                {f"{job.id}:1" for job in workflow.baselines.values()},
            )

            chain = self.build_chain(workflow)
            for key, job in chain.items():
                self.assertEqual(self.combo_jobs(workflow, key), [str(job.id)])
                self.assertTrue(
                    panel.step_buttons[key]
                    .text()
                    .startswith("Run" if key == "scenario" else "Revise"),
                    key,
                )
                for suffix in (".xlsx", ".json"):
                    self.assertTrue(report_files(job, suffix), f"{key}{suffix}")
                details = workflow.summary(key)
                self.assertTrue(details, key)
                self.assertNotIn("details are not available", details, key)
            legacy = SimpleNamespace(
                results=SimpleNamespace(
                    data={
                        "report": {
                            "arr": {},
                            "land_types": {},
                            "projection": {"year_final": 2015},
                        }
                    }
                )
            )
            with patch(
                "LDMP.ldn_planning_panel.job_manager.ensure_results_loaded",
                return_value=True,
            ):
                arr_details = panel._result_metrics("arr", legacy)
                land_type_details = panel._result_metrics("land_types", legacy)
                scenario_details = panel._result_metrics("scenario", legacy)
            self.assertIn("Avoid: Not available", arr_details)
            self.assertIn("Land types: Not available", land_type_details)
            self.assertIn("Projection year: Not available", scenario_details)
            self.assertNotIn("Avoid: 0.00", arr_details)
            self.assertNotIn(
                "Summary...",
                [button.text() for button in panel.findChildren(QtWidgets.QPushButton)],
            )

            arr = report(chain["arr"])["arr"]
            land_types = report(chain["land_types"])["land_types"]
            priority = report(chain["priority"])
            candidate = report(chain["candidate"])
            scenario = report(chain["scenario"])
            total = arr["total_km2"]
            self.assertAlmostEqual(
                arr["avoid_km2"] + arr["reduce_km2"] + arr["reverse_km2"], total
            )
            self.assertEqual(
                {int(code): count for code, count in arr["reason_counts"].items()},
                {1: 30, 4: 35, 32: 35},
            )
            self.assertEqual(
                [row["label"] for row in land_types["land_types"]],
                ["1_1", "1_2", "2_1", "2_2"],
            )
            self.assertEqual(
                [row["pixels"] for row in land_types["land_types"]], [25] * 4
            )
            self.assertAlmostEqual(land_types["total_area_km2"], total)

            classes = priority["summary"]["classes"]
            for name in CLASSES:
                self.assertAlmostEqual(
                    classes[name]["scored_area_km2"], arr[f"{name}_km2"]
                )
                self.assertEqual(classes[name]["coverage_fraction"], 1.0)
            self.assertEqual(
                {row["name"] for row in priority["summary"]["by_land_type"]},
                {"1_1", "1_2", "2_1", "2_2"},
            )
            self.assertEqual(
                priority["parameters"]["land_type_job_id"], str(chain["land_types"].id)
            )
            self.assertEqual(
                priority["summary"]["provenance"]["arr_sha256"],
                file_checksum(job_raster_path(chain["arr"])[0]),
            )

            selections = candidate["summary"]["selections"]
            self.assertAlmostEqual(
                selections["avoid"]["selected_area_km2"], arr["avoid_km2"]
            )
            self.assertLessEqual(selections["reverse"]["selected_area_km2"], 5)
            self.assertAlmostEqual(
                selections["reverse"]["selected_area_km2"]
                + selections["reverse"]["unspent_area_km2"],
                5,
            )
            self.assertEqual(
                candidate["summary"]["mask_sha256"],
                file_checksum(job_raster_path(chain["candidate"])[0]),
            )
            self.assertEqual(
                candidate["summary"]["score_sha256"],
                file_checksum(job_raster_path(chain["priority"])[0]),
            )

            bau = scenario["bau"]
            self.assertAlmostEqual(bau["total_area_km2"], total)
            self.assertAlmostEqual(
                bau["degraded_area_baseline_km2"], arr["reverse_km2"]
            )
            self.assertAlmostEqual(
                sum(row["total_area_km2"] for row in bau["land_types_bau"]), total
            )
            targets = chain["scenario"].params["targets"]
            self.assertEqual(
                {target["source_job_id"] for target in targets},
                {str(chain["candidate"].id)},
            )
            per_target = {
                row["intervention"]: row for row in scenario["scenario"]["per_target"]
            }
            self.assertEqual(set(per_target), {"avoid", "reverse"})
            self.assertAlmostEqual(
                per_target["avoid"]["area_treated_km2"],
                selections["avoid"]["selected_area_km2"],
            )
            self.assertAlmostEqual(
                per_target["reverse"]["area_treated_km2"],
                selections["reverse"]["selected_area_km2"],
            )
            self.assertAlmostEqual(
                per_target["reverse"]["gains_km2"],
                0.5 * selections["reverse"]["selected_area_km2"],
            )
            self.assertAlmostEqual(
                scenario["scenario"]["total_avoided_losses_km2"],
                0.5 * selections["avoid"]["selected_area_km2"],
            )
            projection = scenario["projection"]
            self.assertIn("Projection year: 2030", workflow.summary("scenario"))
            self.assertAlmostEqual(
                projection["scenario_contribution_km2"],
                projection["scenario_gains_km2"]
                + projection["scenario_avoided_losses_km2"],
            )
            self.assertEqual(workflow.warnings, [])

    def test_rerunning_an_input_flags_and_clears_downstream_results(self):
        with self.workflow() as workflow:
            chain = self.build_chain(workflow)
            arr = self.create_arr(workflow, threshold=0.3)
            self.assertEqual(
                self.combo_jobs(workflow, "arr"), [str(chain["arr"].id), str(arr.id)]
            )
            self.assertEqual(workflow.panel.combos["arr"].currentData(), str(arr.id))
            self.expect_states(
                workflow,
                arr="match",
                land_types="match",
                priority="stale",
                candidate="stale",
                scenario="stale",
            )

            workflow.select("arr", arr)
            texts = self.expect_states(
                workflow,
                arr="match",
                land_types="match",
                priority="stale",
                candidate="stale",
                scenario="stale",
            )
            self.assertIn("different arr dataset", texts["priority"])
            self.assertIn("intervention ranking needs updating", texts["candidate"])
            self.assertIn("different arr dataset", texts["scenario"])

            priority = self.prioritize(workflow, arr, chain["land_types"], False)
            self.assertEqual(priority.params["arr_job_id"], str(arr.id))
            workflow.select("priority", priority)
            texts = self.expect_states(
                workflow,
                **dict.fromkeys(PANEL_KEYS[:3], "match"),
                candidate="stale",
                scenario="stale",
            )
            self.assertIn("different intervention ranking", texts["candidate"])

            candidate = self.select_candidates(workflow, priority)
            self.assertEqual(
                candidate.params["selections"], chain["candidate"].params["selections"]
            )
            self.assertEqual(candidate.params["priority_job_id"], str(priority.id))
            workflow.select("candidate", candidate)
            self.expect_states(
                workflow, **dict.fromkeys(PANEL_KEYS[:4], "match"), scenario="stale"
            )

            scenario = self.build_scenario(
                workflow, arr, chain["land_types"], candidate, "baseline"
            )
            workflow.select("scenario", scenario)
            self.expect_states(workflow, **ALL_MATCH)
            self.assertEqual(
                report(scenario)["scenario"]["per_target"][0]["area_treated_km2"],
                report(chain["scenario"])["scenario"]["per_target"][0][
                    "area_treated_km2"
                ],
            )

            # Updating land types affects every result that recorded them.
            land_types = self.define_land_types(workflow, workflow.land_cover)
            workflow.select("land_types", land_types)
            self.expect_states(
                workflow,
                arr="match",
                land_types="match",
                priority="stale",
                candidate="stale",
                scenario="stale",
            )

    def test_selection_changes_are_verified_dynamically(self):
        with self.workflow() as workflow:
            chain = self.build_chain(workflow)
            panel = workflow.panel

            workflow.select_baseline("alternate")
            texts = self.expect_states(
                workflow, **dict.fromkeys(PANEL_KEYS[:4], "match"), scenario="stale"
            )
            self.assertIn("different baseline", texts["scenario"])
            workflow.select_baseline("baseline")
            self.expect_states(workflow, **ALL_MATCH)

            panel.combos["land_types"].setCurrentIndex(0)
            texts = self.expect_states(
                workflow,
                arr="match",
                priority="unknown",
                candidate="unknown",
                scenario="stale",
            )
            self.assertIn("Select land_types", texts["priority"])
            self.assertIn("not verified", texts["candidate"])
            workflow.select("land_types", chain["land_types"])
            self.expect_states(workflow, **ALL_MATCH)

            # Selecting an older result upstream marks the later ones as stale.
            other = self.create_arr(workflow, baseline="alternate")
            workflow.select("arr", other)
            self.assertEqual(workflow.states()["priority"], "stale")
            workflow.select("arr", chain["arr"])
            self.expect_states(workflow, **ALL_MATCH)

            # The selections persist with the project when the panel is reopened.
            reopened = workflow.open_panel()
            self.assertEqual(
                {
                    key: reopened.status_icons[key].property("lineage_state")
                    for key in PANEL_KEYS
                },
                ALL_MATCH,
            )
            panel = reopened

            job_manager.delete_job(chain["candidate"])
            QtWidgets.QApplication.processEvents()
            combo = panel.combos["candidate"]
            self.assertTrue(combo.currentText().startswith("Unavailable"))
            texts = self.expect_states(
                workflow,
                **dict.fromkeys(PANEL_KEYS[:3], "match"),
                candidate="unknown",
                scenario="unknown",
            )
            self.assertIn("restore it or choose another", texts["candidate"])
            self.assertIn("candidate dataset is unavailable", texts["scenario"])
            panel.step_buttons["scenario"].click()
            QtWidgets.QApplication.processEvents()
            self.assertEqual(workflow.exceptions, [])
            self.assertIn("candidate areas", workflow.errors[-1])

    def test_area_change_blocks_runs_until_adopted_then_flags_results(self):
        with self.workflow() as workflow:
            chain = self.build_chain(workflow)
            panel = workflow.panel
            self.assertEqual(panel.status_labels["arr"].text(), "Analysis area matches")
            submitted = len(workflow.submitted)

            workflow.set_area(workflow.other_aoi_path)
            panel.refresh()
            self.assertIn("differs from project area", panel.area_label.text())
            for key in PANEL_KEYS:
                panel.step_buttons[key].click()
                QtWidgets.QApplication.processEvents()
                self.assertIn("Different project area", workflow.warnings.pop())
            self.assertEqual(workflow.exceptions, [])
            self.assertEqual(len(workflow.submitted), submitted)

            panel._adopt_area()
            texts = self.expect_states(workflow, **dict.fromkeys(PANEL_KEYS, "stale"))
            self.assertIn("project area changed", texts["arr"])
            self.assertIn("project area changed", panel.baseline_status.text())

            # Reselecting a result made for the old area keeps it flagged.
            panel.combos["arr"].setCurrentIndex(0)
            workflow.select("arr", chain["arr"])
            self.assertIn("different project area", panel.status_labels["arr"].text())
            self.assertEqual(workflow.states()["arr"], "stale")

            arr = self.create_arr(workflow)
            workflow.select("arr", arr)
            self.assertEqual(workflow.states()["arr"], "match")
            self.assertLess(
                report(arr)["arr"]["total_km2"],
                report(chain["arr"])["arr"]["total_km2"],
            )

    def test_dropdowns_reload_for_datasets_created_elsewhere(self):
        with self.workflow() as workflow:
            panel = workflow.panel
            path = write_raster(
                workflow.inputs / "imported.tif",
                [np.full((SIZE, SIZE), -1)],
                gdal.GDT_Int16,
            )
            job = sdg_job(path, "SDG imported", 2001, 2016)
            job_manager.write_job_metadata_file(job)
            job_manager.import_job(job, job_manager.get_job_file_path(job))
            QtWidgets.QApplication.processEvents()
            self.assertGreaterEqual(panel.baseline_combo.findData(f"{job.id}:1"), 0)
            workflow.baselines["imported"] = job

            # An external import/run still refreshes the embedded tab.
            from LDMP.ldn_planning_actions import arr_factory, launch_calculate_dialog

            def action(dialog):
                select_job_band(dialog.combo_status, job.id, dialog, "status")

            workflow.dialog_actions.append(action)
            launch_calculate_dialog(workflow.main_dock, arr_factory)
            QtWidgets.QApplication.processEvents()
            self.assertEqual(workflow.exceptions, [])
            arr = workflow.submitted[-1]
            self.assertEqual(self.combo_jobs(workflow, "arr"), [str(arr.id)])
            workflow.select("arr", arr)
            self.assertEqual(workflow.states()["arr"], "match")
            self.assertAlmostEqual(
                report(arr)["arr"]["reverse_km2"], report(arr)["arr"]["total_km2"]
            )

    def test_hotspots_report_matches_baseline(self):
        with self.workflow() as workflow:
            from LDMP.ldn_planning_actions import launch_calculate_dialog

            def action(dialog):
                select_job_band(
                    dialog.combo_status,
                    workflow.baselines["baseline"].id,
                    dialog,
                    "status",
                )
                dialog.rb_zones_grid.setChecked(True)
                dialog.spin_grid_km.setValue(5)

            workflow.dialog_actions.append(action)
            launch_calculate_dialog(
                workflow.main_dock,
                lambda: (DlgCalculateLDNPlanningHotspots, "ldn-planning-hotspots"),
            )
            QtWidgets.QApplication.processEvents()
            self.assertEqual(workflow.exceptions + workflow.errors, [])
            job = workflow.submitted[-1]
            self.assertEqual(job.status, te_jobs.JobStatus.GENERATED_LOCALLY)
            hotspots = report(job)["hotspots"]
            self.assertEqual(hotspots["n_zones"], 9)
            self.assertEqual(hotspots["status_type"], "3class")
            # Only the western column of the 3 x 3 grid contains degraded land.
            self.assertEqual(set(hotspots["top10_zone_fids"][:3]), {1, 4, 7})
            self.assertGreater(hotspots["mean_degraded_fraction"], 0)
            self.assertLess(hotspots["mean_degraded_fraction"], 0.3)
            for suffix in (".xlsx", ".json", ".gpkg"):
                self.assertTrue(report_files(job, suffix), suffix)

    def test_arr_result_shows_processing_then_selects_completed_dataset(self):
        with self.workflow() as workflow:
            tasks = []

            def configure_arr(dialog):
                select_job_band(
                    dialog.combo_status,
                    workflow.baselines["baseline"].id,
                    dialog,
                    "status",
                )
                dialog.chk_use_risk.setChecked(True)
                dialog._risk_path = str(workflow.risk)
                dialog.spin_risk_threshold.setValue(0.5)

            with patch.object(job_manager.tm, "addTask", side_effect=tasks.append):
                workflow.dialog_actions.append(configure_arr)
                workflow.panel.step_buttons["arr"].click()
                QtWidgets.QApplication.processEvents()
                job = workflow.submitted[-1]
                self.assertEqual(
                    workflow.panel.status_labels["arr"].text(),
                    "Result processing: %s" % job.task_name,
                )
                self.assertEqual(len(tasks), 1)

                tasks[0].finished(tasks[0].run())
                QtWidgets.QApplication.processEvents()

            self.assertEqual(workflow.panel.combos["arr"].currentData(), str(job.id))
            self.assertEqual(
                workflow.panel.status_labels["arr"].text(), "Analysis area matches"
            )
