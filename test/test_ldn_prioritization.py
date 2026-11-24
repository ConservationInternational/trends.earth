import copy
import datetime as dt
import functools
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from osgeo import gdal, ogr, osr
from qgis.core import (
    QgsFeature,
    QgsGeometry,
    QgsRasterLayer,
    QgsVectorLayer,
)
from qgis.PyQt import QtCore, QtWidgets
from qgis.PyQt.QtGui import QColor
from te_algorithms.common.checksum import file_checksum
from te_algorithms.gdal.land_deg import config as ld_config

from LDMP import layers
from LDMP.calculate_counterbalancing import DlgCalculateCounterbalancing
from LDMP.calculate_ldn_planning import (
    DlgCalculateLDNPlanningARR,
    DlgCalculateLDNPlanningHotspots,
    DlgCalculateLDNPlanningLandTypes,
    ScenarioTargetsWidget,
)
from LDMP.calculate_ldn_priority import (
    DlgCalculateLDNPlanningPriority,
    DlgCalculateLDNPlanningSelection,
    DlgPriorityCriterion,
)
from LDMP.conf import KNOWN_SCRIPTS
from LDMP.jobs.manager import JobManager, job_manager
from LDMP.localexecution.ldn_planning import (
    compute_arr_local,
    compute_planning_local,
    compute_priority_local,
    compute_selection_local,
)


def make_raster(path, values):
    driver = gdal.GetDriverByName("GTiff")
    values = np.array(values, dtype=np.float32)
    dataset = driver.Create(
        str(path), values.shape[1], values.shape[0], 1, gdal.GDT_Float32
    )
    dataset.SetGeoTransform((0, 0.01, 0, 1, 0, -0.01))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    dataset.SetProjection(srs.ExportToWkt())
    dataset.GetRasterBand(1).SetNoDataValue(-32768)
    dataset.GetRasterBand(1).WriteArray(values)
    dataset = None


class PriorityInputTests(unittest.TestCase):
    def test_planning_dialogs_record_encoding_from_selected_band(self):
        parent = QtWidgets.QWidget()
        parent.cache_refresh_about_to_begin = Mock()
        parent.cache_refresh_finished = Mock()
        parent.refreshing_filesystem_cache = False

        def band(name, index):
            return SimpleNamespace(
                path=Path("/input.tif"),
                band_index=index,
                band_info=SimpleNamespace(name=name, metadata={}),
                job=SimpleNamespace(id=f"source-{index}"),
            )

        indicator = band(ld_config.SDG_BAND_NAME, 2)
        status = band(ld_config.SDG_STATUS_BAND_NAME, 3)
        with (
            patch(
                "LDMP.calculate.download.get_admin_bounds", return_value={"country": {}}
            ),
            patch("LDMP.calculate.download.get_cities", return_value={"city": {}}),
            patch("LDMP.calculate.DlgCalculateBase.btn_calculate", return_value=True),
            patch.object(job_manager, "submit_local_job_as_qgstask") as submit,
            patch.object(
                QtWidgets.QMessageBox,
                "question",
                return_value=QtWidgets.QMessageBox.Yes,
            ),
            patch.object(QtWidgets.QMessageBox, "critical") as critical,
        ):
            for dialog_type in (
                DlgCalculateLDNPlanningARR,
                DlgCalculateLDNPlanningHotspots,
            ):
                for selected, expected in ((indicator, "3class"), (status, "7class")):
                    dialog = dialog_type(
                        Mock(), KNOWN_SCRIPTS[dialog_type.LOCAL_SCRIPT_NAME], parent
                    )
                    dialog.aoi = None
                    dialog.combo_status.get_current_band = Mock(return_value=selected)
                    if dialog_type is DlgCalculateLDNPlanningHotspots:
                        dialog.rb_zones_grid.setChecked(True)
                    submit.reset_mock()
                    dialog.btn_calculate()
                    params = submit.call_args.args[0]
                    self.assertEqual(params["status_type"], expected)
                    self.assertEqual(params["status_band_index"], selected.band_index)
                    if dialog_type is DlgCalculateLDNPlanningARR:
                        self.assertEqual(params["status_job_id"], str(selected.job.id))
                    dialog.close()

            dialog = DlgCalculateLDNPlanningARR(
                Mock(),
                KNOWN_SCRIPTS[DlgCalculateLDNPlanningARR.LOCAL_SCRIPT_NAME],
                parent,
            )
            dialog.aoi = None
            dialog.combo_status.get_current_band = Mock(return_value=band("Unknown", 1))
            submit.reset_mock()
            dialog.btn_calculate()
            submit.assert_not_called()
            critical.assert_called_once()
            dialog.close()
        parent.close()

    def test_lazy_loaded_planning_results_appear_in_dropdown_lookups(self):
        from te_schemas.jobs import JobStatus
        from te_schemas.results import (
            URI,
            DataType,
            Raster,
            RasterFileType,
            RasterResults,
        )
        from te_schemas.results import Band as JobBand

        from LDMP.calculate_ldn_priority import planning_raster_jobs
        from LDMP.data_io import _get_usable_bands

        band = JobBand(name="LDN Planning - Avoid/Reduce/Reverse", metadata={})
        uri = URI(uri=Path("/arr.tif"))
        result = RasterResults(
            name="ldn-planning-arr",
            uri=uri,
            rasters={
                DataType.INT16.value: Raster(
                    uri=uri,
                    bands=[band],
                    datatype=DataType.INT16,
                    filetype=RasterFileType.GEOTIFF,
                )
            },
        )
        job = SimpleNamespace(
            id="arr",
            status=JobStatus.GENERATED_LOCALLY,
            results=None,
            params={},
            start_date=dt.datetime.now(),
            _cached_band_names=(band.name,),
        )
        job.is_raster = lambda: job.results is not None
        job.get_first_result_by_type = lambda _type: job.results

        def load_results(item):
            item.results = result
            return True

        manager = SimpleNamespace(
            relevant_jobs=[job],
            ensure_results_loaded=load_results,
            ensure_params_loaded=lambda _job: True,
        )
        _get_usable_bands.cache_clear()
        try:
            with (
                patch("LDMP.calculate_ldn_priority.job_manager", manager),
                patch("LDMP.data_io.job_manager", manager),
            ):
                self.assertEqual(planning_raster_jobs("ldn-planning-arr"), [job])
                job.results = None
                bands = _get_usable_bands(band_name=band.name)
                self.assertEqual(len(bands), 1)
                self.assertEqual(bands[0].job.id, "arr")
        finally:
            _get_usable_bands.cache_clear()

    def test_local_task_preserves_parameters_recorded_during_execution(self):
        from te_schemas.jobs import JobStatus

        from LDMP.jobs.manager import LocalJobTask
        from LDMP.jobs.models import Job

        job = Job(
            id=uuid.uuid4(),
            params={"input": "original"},
            progress=0,
            start_date=dt.datetime.now(dt.timezone.utc),
            status=JobStatus.RUNNING,
        )
        task = LocalJobTask("planning", job, None)
        task.job_copy.params["aoi_checksum"] = "recorded-area"
        task.results = None
        emitted = []
        task.processed_job.connect(emitted.append)
        task.finished(True)
        self.assertEqual(emitted[0].params["aoi_checksum"], "recorded-area")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "job.json"
            manager = Mock()
            manager.get_job_file_path.return_value = path
            manager._encoding = "utf-8"
            JobManager.write_job_metadata_file(manager, emitted[0])
            with path.open(encoding="utf-8") as source:
                self.assertEqual(
                    json.load(source)["params"]["aoi_checksum"], "recorded-area"
                )

    def test_completed_lazy_jobs_refresh_panel_and_restore_selection(self):
        from te_schemas.jobs import JobStatus
        from te_schemas.results import RasterResults

        from LDMP.ldn_planning_panel import PlanningPanel

        class JobSignals(QtCore.QObject):
            imported_job = QtCore.pyqtSignal(object)
            downloaded_job_results = QtCore.pyqtSignal(object)
            submitted_local_job = QtCore.pyqtSignal(object)
            processed_local_job = QtCore.pyqtSignal(object)
            failed_local_job = QtCore.pyqtSignal(object)
            deleted_job = QtCore.pyqtSignal(object)

            def __init__(self):
                super().__init__()
                self.relevant_jobs = []

            def ensure_results_loaded(self, job):
                job.results = job.saved_result
                return True

            def ensure_params_loaded(self, job):
                return True

        def make_job(identifier, result_name):
            job = SimpleNamespace(
                id=identifier,
                task_name=identifier,
                status=JobStatus.GENERATED_LOCALLY,
                results=None,
                params={"aoi_checksum": "area-a"},
                saved_result=RasterResults(name=result_name, rasters={}, uri=None),
            )
            job.get_first_result_by_type = lambda _type: job.results
            return job

        manager = JobSignals()
        area = {"name": "Region A", "sha256": "area-a"}
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("LDMP.region_selector.download.get_admin_bounds", return_value={}),
            patch("LDMP.region_selector.get_admin_bbox", return_value=None),
            patch("LDMP.ldn_planning_panel.job_manager", manager),
            patch("LDMP.calculate_ldn_priority.job_manager", manager),
            patch("LDMP.ldn_planning_panel.current_area", return_value=area),
            patch("LDMP.ldn_planning_panel.baseline_bands", return_value=[]),
        ):
            settings = QtCore.QSettings(
                str(Path(directory) / "settings.ini"), QtCore.QSettings.Format.IniFormat
            )
            panel = PlanningPanel(Mock(), settings=settings)
            panel.data = {
                "version": 1,
                "current": "project",
                "projects": [
                    {
                        "id": "project",
                        "name": "Plan",
                        "area": area,
                        "selections": {
                            "land_types": {"job_id": "land", "area_sha256": "area-a"}
                        },
                    }
                ],
            }
            panel.refresh()
            self.assertIn("Unavailable", panel.combos["land_types"].currentText())
            land = make_job("land", "ldn-planning-land-types")
            arr = make_job("arr", "ldn-planning-arr")
            for job in (land, arr):
                manager.relevant_jobs.append(job)
                manager.processed_local_job.emit(job)
                QtWidgets.QApplication.processEvents()
            self.assertEqual(panel.combos["land_types"].currentText(), "land")
            self.assertEqual(
                panel.status_icons["land_types"].property("lineage_state"), "match"
            )
            self.assertGreater(panel.combos["arr"].findData("arr"), 0)
            panel.dispose()
            panel.close()

    def test_priority_workflow_dialogs_initialize_with_registered_scripts(self):
        parent = QtWidgets.QWidget()
        parent.cache_refresh_about_to_begin = Mock()
        parent.cache_refresh_finished = Mock()
        parent.refreshing_filesystem_cache = False
        with (
            patch(
                "LDMP.calculate.download.get_admin_bounds", return_value={"country": {}}
            ),
            patch("LDMP.calculate.download.get_cities", return_value={"city": {}}),
        ):
            for dialog_type in (
                DlgCalculateLDNPlanningARR,
                DlgCalculateLDNPlanningHotspots,
                DlgCalculateLDNPlanningLandTypes,
                DlgCalculateLDNPlanningPriority,
                DlgCalculateLDNPlanningSelection,
                DlgCalculateCounterbalancing,
            ):
                dialog = dialog_type(
                    Mock(), KNOWN_SCRIPTS[dialog_type.LOCAL_SCRIPT_NAME], parent
                )
                self.assertTrue(
                    dialog.button_box.button(QtWidgets.QDialogButtonBox.Ok).isEnabled()
                )
                help_browser = dialog.splitter.widget(1)
                self.assertIsInstance(help_browser, QtWidgets.QTextBrowser)
                self.assertTrue(help_browser.toPlainText().strip())
                self.assertIn("ldnplanning.html", help_browser.toHtml())
                self.assertTrue(help_browser.openExternalLinks())
                if dialog_type is DlgCalculateLDNPlanningPriority:
                    # Jurisdictions offer built-in admin units or uploaded files.
                    self.assertEqual(dialog._zones_source(), "none")
                    dialog._apply_zones_source("admin_level_1")
                    self.assertTrue(dialog.rb_zones_admin.isChecked())
                    settings = dialog._settings()
                    self.assertEqual(settings["zones_source"], "admin_level_1")
                    # Land types come from saved Define Land Types datasets.
                    self.assertIsNone(settings["land_type_job_id"])
                    self.assertFalse(dialog.btn_zones_browse.isEnabled())
                    dialog._apply_zones_source("file")
                    self.assertTrue(dialog.btn_zones_browse.isEnabled())
                dialog.close()
        parent.close()

    def test_priority_update_respects_cleared_or_missing_land_types(self):
        parent = QtWidgets.QWidget()
        parent.cache_refresh_about_to_begin = Mock()
        parent.cache_refresh_finished = Mock()
        parent.refreshing_filesystem_cache = False
        land = SimpleNamespace(id="land-1", task_name="Land types")
        with (
            patch(
                "LDMP.calculate.download.get_admin_bounds", return_value={"country": {}}
            ),
            patch("LDMP.calculate.download.get_cities", return_value={"city": {}}),
            patch.object(DlgCalculateLDNPlanningPriority, "_restore_draft"),
            patch.object(DlgCalculateLDNPlanningPriority, "_store_draft"),
            patch.object(job_manager, "get_ldn_land_types_jobs", return_value=[land]),
            patch.object(QtWidgets.QMessageBox, "warning") as warning,
        ):
            for project_selection in (None, "missing"):
                dialog = DlgCalculateLDNPlanningPriority(
                    Mock(),
                    KNOWN_SCRIPTS[DlgCalculateLDNPlanningPriority.LOCAL_SCRIPT_NAME],
                    parent,
                )
                dialog._firstShowEvent = False
                dialog.combo_arr.populate = Mock()
                dialog.preselect_priority_settings = {
                    "entries": [],
                    "land_type_job_id": "land-1",
                }
                dialog.preselect_land_type_job_id = project_selection
                dialog.show()
                QtWidgets.QApplication.processEvents()
                self.assertEqual(
                    dialog.combo_land_types.currentIndex(),
                    0 if project_selection is None else -1,
                )
                dialog.close()
            self.assertEqual(warning.call_count, 1)
        parent.close()

    def test_candidate_update_restores_selection_settings(self):
        parent = QtWidgets.QWidget()
        parent.cache_refresh_about_to_begin = Mock()
        parent.cache_refresh_finished = Mock()
        parent.refreshing_filesystem_cache = False
        job = SimpleNamespace(id="new-priority", task_name="New priority")
        with (
            patch(
                "LDMP.calculate.download.get_admin_bounds", return_value={"country": {}}
            ),
            patch("LDMP.calculate.download.get_cities", return_value={"city": {}}),
            patch(
                "LDMP.calculate_ldn_priority.planning_raster_jobs", return_value=[job]
            ),
        ):
            dialog = DlgCalculateLDNPlanningSelection(
                Mock(),
                KNOWN_SCRIPTS[DlgCalculateLDNPlanningSelection.LOCAL_SCRIPT_NAME],
                parent,
            )
            dialog._firstShowEvent = False
            dialog.preselect_priority_job_id = "new-priority"
            dialog.preselect_selections = {
                "reverse": {"mode": "area", "threshold": 0.6, "area_km2": 25}
            }
            dialog.show()
            QtWidgets.QApplication.processEvents()
            enabled, mode, threshold, area = dialog.rows["reverse"]
            self.assertTrue(enabled.isChecked())
            self.assertEqual(mode.currentData(), "area")
            self.assertAlmostEqual(threshold.value(), 0.6)
            self.assertAlmostEqual(area.value(), 25)
            self.assertFalse(dialog.rows["avoid"][0].isChecked())
            self.assertEqual(dialog.combo_priority.currentData(), "new-priority")
            dialog.close()
        parent.close()

    def test_import_preserves_zero_default_and_transforms_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "source.gpkg"
            reference = osr.SpatialReference()
            reference.ImportFromEPSG(3857)
            datasource = ogr.GetDriverByName("GPKG").CreateDataSource(str(source))
            layer = datasource.CreateLayer("targets", reference, ogr.wkbPolygon)
            feature = ogr.Feature(layer.GetLayerDefn())
            feature.SetGeometry(
                ogr.CreateGeometryFromWkt("POLYGON ((0 0, 1000 0, 1000 1000, 0 0))")
            )
            layer.CreateFeature(feature)
            datasource = None
            manager = Mock()
            output = directory / "output.gpkg"
            manager.get_job_file_path.return_value = output.with_suffix(".json")
            manager._init_ldn_targets_layer.side_effect = lambda job: (
                JobManager._init_ldn_targets_layer(manager, job)
            )
            JobManager.create_ldn_targets_layer_from_file(
                manager,
                str(source),
                {
                    "default_intervention": "reverse",
                    "default_effectiveness": 0,
                },
                "Imported",
            )
            datasource = ogr.Open(str(output))
            feature = datasource.GetLayer().GetNextFeature()
            self.assertEqual(feature.GetField("effectiveness"), 0)
            self.assertLess(feature.GetGeometryRef().GetEnvelope()[1], 0.01)
            datasource = None

    def test_criterion_dialog_categorical_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "criterion.tif"
            make_raster(path, [[1, 2]])
            dialog = DlgPriorityCriterion()
            for key, value in {
                "name": "Habitat",
                "path": str(path),
                "source": "Local inventory",
                "date": "2025",
                "units": "class",
                "license": "CC BY",
            }.items():
                dialog.fields[key].setText(value)
            dialog.categories.setText('{"1": 0.1, "2": 0.9}')
            dialog._accept()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)
            self.assertEqual(dialog.criterion["resampling"], "nearest")
            self.assertEqual(dialog.criterion["source"], "Local inventory")
            dialog.close()

    def test_live_targets_snapshot_does_not_commit_and_replaces_previous_load(self):
        layer = QgsVectorLayer(
            "Polygon?crs=EPSG:4326&field=intervention:string&field=effectiveness:double",
            "targets",
            "memory",
        )
        layer.startEditing()
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt("POLYGON ((0 0, 1 0, 1 1, 0 0))"))
        feature.setAttributes(["reverse", 0.0])
        layer.addFeature(feature)
        layer.setCustomProperty("job_id", "test-job")
        job = Mock()
        job.id = "test-job"
        job.task_name = "targets"
        job.get_first_result_by_type.return_value = None
        dialog = Mock()
        dialog.tr.side_effect = lambda text: text
        dialog.combo_targets_layer.currentIndex.return_value = 0
        dialog._targets_jobs = [job]
        dialog._targets = []
        with patch("qgis.core.QgsProject.instance") as project:
            project.return_value.mapLayers.return_value = {"layer": layer}
            with patch("LDMP.calculate_ldn_planning.job_manager") as manager:
                manager.get_job_file_path.return_value = Path("/missing")
                with patch.object(
                    QtWidgets.QMessageBox,
                    "question",
                    return_value=QtWidgets.QMessageBox.StandardButton.Yes,
                ):
                    ScenarioTargetsWidget._load_targets_from_job(dialog)
                    ScenarioTargetsWidget._load_targets_from_job(dialog)
        self.assertTrue(layer.isEditable())
        self.assertTrue(layer.isModified())
        self.assertEqual(len(dialog._targets), 1)
        self.assertEqual(dialog._targets[0]["effectiveness"], 0)
        self.assertIn("WGS 84", dialog._targets[0]["geometry_crs"])
        layer.rollBack()


class PlanningInputTests(unittest.TestCase):
    """Managed prioritization inputs and reusable scoring profiles."""

    def _patched_settings(self, directory):
        from LDMP import conf

        def get_value(setting, *args, **kwargs):
            if setting == conf.Setting.BASE_DIR:
                return str(directory)
            return "test"

        return patch.object(conf.settings_manager, "get_value", side_effect=get_value)

    def test_scoring_profile_loads_cached_band_metadata_and_existing_profiles(self):
        from LDMP import ldn_planning_assets
        from LDMP.jobs.cache import JobCache

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "capital.tif"
            dataset = gdal.GetDriverByName("GTiff").Create(
                str(source), 2, 1, 2, gdal.GDT_Float32
            )
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(4326)
            dataset.SetProjection(srs.ExportToWkt())
            dataset.SetGeoTransform((0, 0.01, 0, 1, 0, -0.01))
            for index in (1, 2):
                dataset.GetRasterBand(index).SetDescription(f"Input {index}")
                dataset.GetRasterBand(index).WriteArray(np.array([[index, index + 1]]))
            dataset = None
            with self._patched_settings(directory / "base"):
                job = job_manager.register_planning_input_job(
                    source_path=str(source),
                    task_name="Capital",
                    task_notes="",
                    input_kind="raster",
                )
                existing = {"name": "Existing", "revision": 1, "band_index": 1}
                job.params["scoring_profiles"] = [existing]
                path = job_manager.get_job_file_path(job)
                cache = JobCache(directory / "base")
                self.assertTrue(cache.cache_job(path, 123, job))
                with patch.object(job_manager, "_job_cache", cache):
                    job = cache.get_cached_job(path, 123, load_params=False)
                    self.assertEqual(job.params, {})
                    host = QtWidgets.QWidget()
                    host.entries = []
                    host._refresh = Mock()
                    with patch.object(
                        QtWidgets.QInputDialog,
                        "getItem",
                        return_value=("Existing (rev 1)", True),
                    ):
                        DlgCalculateLDNPlanningPriority._configure_entry_for_job(
                            host, job
                        )
                    self.assertEqual(host.entries[0]["profile"], existing)

                    job = cache.get_cached_job(path, 123, load_params=False)
                    dialog = ldn_planning_assets.DlgScoringProfile(job)
                    self.assertEqual(dialog.band_combo.count(), 2)
                    self.assertEqual(dialog.band_combo.itemData(1), 2)
                    self.assertIn("Input 2", dialog.band_combo.itemText(1))
                    dialog.name_edit.setText("Second band")
                    dialog.band_combo.setCurrentIndex(1)
                    dialog._accept()
                    self.assertEqual(dialog.profile["band_index"], 2)
                    self.assertEqual(len(job.params["scoring_profiles"]), 2)
                    self.assertEqual(len(job.params["band_info"]), 2)
                    with path.open(encoding="utf-8") as saved:
                        persisted = json.load(saved)["params"]
                    self.assertEqual(len(persisted["scoring_profiles"]), 2)
                    self.assertEqual(len(persisted["band_info"]), 2)
                    host.close()
                cache.close()

    def test_missing_profile_metadata_fails_without_defaulting_to_band_one(self):
        from LDMP import ldn_planning_assets

        job = SimpleNamespace(id="missing", task_name="Missing", params={})
        with (
            patch.object(job_manager, "ensure_params_loaded", return_value=False),
            patch.object(QtWidgets.QMessageBox, "critical") as critical,
        ):
            host = QtWidgets.QWidget()
            host.entries = []
            host._refresh = Mock()
            DlgCalculateLDNPlanningPriority._configure_entry_for_job(host, job)
            self.assertEqual(host.entries, [])
            critical.assert_called_once()
            with self.assertRaisesRegex(ValueError, "metadata is unavailable"):
                ldn_planning_assets.save_scoring_profile(job, {"name": "Unsafe"})
            host.close()

    def test_scoring_profile_recovers_missing_band_info_and_rejects_missing_band(self):
        from LDMP import ldn_planning_assets

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.tif"
            make_raster(source, [[0, 1]])
            job = SimpleNamespace(
                id="old",
                task_name="Old",
                params={"input_kind": "raster"},
                results=SimpleNamespace(uri=SimpleNamespace(uri=source)),
            )
            with (
                patch.object(job_manager, "ensure_params_loaded", return_value=True),
                patch.object(job_manager, "ensure_results_loaded", return_value=True),
                patch.object(QtWidgets.QMessageBox, "critical") as critical,
                patch.object(job_manager, "save_planning_input_profiles") as save,
            ):
                dialog = ldn_planning_assets.DlgScoringProfile(
                    job, profile={"name": "Old profile", "band_index": 9}
                )
                self.assertEqual(dialog.band_combo.count(), 1)
                self.assertEqual(dialog.band_combo.currentIndex(), -1)
                dialog._accept()
                critical.assert_called_once()
                save.assert_not_called()
                dialog.close()

    def test_raster_input_preserves_values_and_builds_reusable_criterion(self):
        from LDMP import ldn_planning_assets

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "capital.tif"
            make_raster(source, [[0.25, 0.75, -32768]])
            with self._patched_settings(directory / "base"):
                job = job_manager.register_planning_input_job(
                    source_path=str(source),
                    task_name="Soil capital",
                    task_notes="",
                    provenance={
                        "source": "Inventory",
                        "date": "2025",
                        "units": "index",
                        "license": "CC BY",
                    },
                    input_kind="raster",
                )
                managed = ldn_planning_assets.input_path(job)
                dataset = gdal.Open(managed)
                band = dataset.GetRasterBand(1)
                self.assertEqual(gdal.GetDataTypeName(band.DataType), "Float32")
                self.assertEqual(band.GetNoDataValue(), -32768)
                self.assertEqual(band.ReadAsArray().tolist(), [[0.25, 0.75, -32768.0]])
                del dataset
                self.assertEqual(job.params["provenance"]["units"], "index")
                self.assertTrue(job.params["checksums"])

                stats = ldn_planning_assets.observed_band_stats(managed, 1)
                self.assertAlmostEqual(stats["minimum"], 0.25)
                self.assertAlmostEqual(stats["maximum"], 0.75)

                profile = ldn_planning_assets.save_scoring_profile(
                    job,
                    {
                        "name": "Higher capital first",
                        "band_index": 1,
                        "field": "",
                        "direction": "higher",
                        "minimum": 0,
                        "maximum": 1,
                        "categories": None,
                        "resampling": "bilinear",
                    },
                )
                self.assertEqual(profile["revision"], 1)
                self.assertEqual(
                    job.params["scoring_profiles"][0]["name"], "Higher capital first"
                )

                criterion = ldn_planning_assets.build_criterion(
                    job, profile, "avoid", 2.0
                )
            from te_algorithms.gdal.land_deg.ldn_priority import validate_criteria

            validated = validate_criteria([criterion])
            self.assertEqual(validated[0]["path"], managed)
            self.assertEqual(validated[0]["source"], "Inventory")
            self.assertEqual(validated[0]["input_job_id"], str(job.id))
            self.assertEqual(validated[0]["weight"], 1.0)

            # The managed criterion scores identically to a direct file criterion.
            arr_path = directory / "arr.tif"
            make_raster(arr_path, [[1, 1, 1]])
            priority_job = SimpleNamespace(
                params=dict(arr_layer_path=str(arr_path), criteria=[criterion])
            )
            result = compute_priority_local(
                priority_job, None, directory / "priority.json", directory / "x.tif"
            )
            scored = gdal.Open(str(result.uri.uri))
            values = scored.GetRasterBand(1).ReadAsArray()
            self.assertAlmostEqual(float(values[0, 0]), 0.25, places=5)
            self.assertAlmostEqual(float(values[0, 1]), 0.75, places=5)
            del scored

    def test_vector_input_materializes_selected_sublayer(self):
        from LDMP import ldn_planning_assets

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "inputs.gpkg"
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(4326)
            datasource = ogr.GetDriverByName("GPKG").CreateDataSource(str(source))
            for name, value in (("first", 1.0), ("habitat", 0.9)):
                layer = datasource.CreateLayer(name, srs=srs, geom_type=ogr.wkbPolygon)
                layer.CreateField(ogr.FieldDefn("value", ogr.OFTReal))
                feature = ogr.Feature(layer.GetLayerDefn())
                feature.SetGeometry(
                    ogr.CreateGeometryFromWkt("POLYGON((0 0,0 1,1 1,1 0,0 0))")
                )
                feature.SetField("value", value)
                layer.CreateFeature(feature)
            datasource.FlushCache()
            del datasource

            with self._patched_settings(directory / "base"):
                with self.assertRaisesRegex(ValueError, "Select which layer"):
                    job_manager.register_planning_input_job(
                        source_path=str(source),
                        task_name="Habitat",
                        task_notes="",
                        provenance={
                            "source": "Survey",
                            "date": "2024",
                            "units": "fraction",
                            "license": "CC BY",
                        },
                        input_kind="vector",
                    )
                job = job_manager.register_planning_input_job(
                    source_path=str(source),
                    task_name="Habitat",
                    task_notes="",
                    provenance={
                        "source": "Survey",
                        "date": "2024",
                        "units": "fraction",
                        "license": "CC BY",
                    },
                    input_kind="vector",
                    vector_layer_name="habitat",
                )
                managed = ldn_planning_assets.input_path(job)
                materialized = ogr.Open(managed, 0)
                self.assertEqual(materialized.GetLayerCount(), 1)
                self.assertEqual(materialized.GetLayer(0).GetName(), "habitat")
                value = materialized.GetLayer(0).GetNextFeature().GetField("value")
                self.assertEqual(value, 0.9)
                del materialized
                self.assertEqual(
                    [f["name"] for f in job.params["numeric_fields"]], ["value"]
                )
                stats = ldn_planning_assets.observed_field_stats(managed, "value")
                self.assertEqual(stats["minimum"], 0.9)
                discovered = ldn_planning_assets.discover_categories(
                    managed, "vector", field="value"
                )
                self.assertEqual(discovered["counts"], {0.9: 1})
                cached_params = copy.deepcopy(job.params)
                job.params = {}

                def load_params(item):
                    if not item.params:
                        item.params = copy.deepcopy(cached_params)
                    return True

                with patch.object(
                    job_manager, "ensure_params_loaded", side_effect=load_params
                ):
                    dialog = ldn_planning_assets.DlgScoringProfile(job)
                    self.assertEqual(dialog.kind, "vector")
                    self.assertEqual(dialog.field_combo.currentData(), "value")
                    dialog._discover_categories()
                    self.assertEqual(dialog.category_table.rowCount(), 1)
                    dialog.close()

    def test_registration_metadata_is_optional_with_explicit_defaults(self):
        from LDMP import ldn_planning_assets

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "capital.tif"
            make_raster(source, [[1.0, 2.0]])
            with self._patched_settings(directory / "base"):
                job = job_manager.register_planning_input_job(
                    source_path=str(source),
                    task_name="No metadata",
                    task_notes="",
                    input_kind="raster",
                )
                # Metadata is stored like the other import tools (.qmd sidecar).
                qmd = job_manager.get_job_file_path(job).with_suffix(".qmd")
                self.assertTrue(qmd.is_file())
                self.assertEqual(job.params["provenance"]["license"], "")
                profile = ldn_planning_assets.save_scoring_profile(
                    job,
                    {
                        "name": "Default",
                        "band_index": 1,
                        "field": "",
                        "direction": "higher",
                        "minimum": 0,
                        "maximum": 2,
                        "categories": None,
                        "resampling": "nearest",
                    },
                )
                criterion = ldn_planning_assets.build_criterion(
                    job, profile, "avoid", 1.0
                )
            from te_algorithms.gdal.land_deg.ldn_priority import validate_criteria

            validated = validate_criteria([criterion])
            # Missing entries are reported explicitly, not invented.
            self.assertEqual(validated[0]["source"], "Not specified")
            self.assertEqual(validated[0]["license"], "Not specified")


class PlanningPanelTests(unittest.TestCase):
    """Workspace panel, dataset actions, previews and multi-raster loading."""

    @staticmethod
    def _make_multiband(path, bands, gdal_type=gdal.GDT_Float32):
        driver = gdal.GetDriverByName("GTiff")
        rows, cols = np.array(bands[0]).shape
        dataset = driver.Create(str(path), cols, rows, len(bands), gdal_type)
        dataset.SetGeoTransform((0, 0.01, 0, 1, 0, -0.01))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        dataset.SetProjection(srs.ExportToWkt())
        for index, values in enumerate(bands, start=1):
            band = dataset.GetRasterBand(index)
            band.SetNoDataValue(-32768)
            band.WriteArray(np.array(values, dtype=np.float32))
        del dataset

    def test_display_selected_job_results_loads_band_from_owning_raster(self):
        from te_schemas.results import (
            URI,
            DataType,
            Raster,
            RasterFileType,
            RasterResults,
        )
        from te_schemas.results import Band as JobBand

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            score_path = directory / "score.tif"
            coverage_path = directory / "coverage.tif"
            self._make_multiband(score_path, [[[0.5]], [[0.6]], [[0.7]]])
            self._make_multiband(coverage_path, [[[1]], [[1]], [[1]]], gdal.GDT_Byte)
            result = RasterResults(
                name="ldn-planning-priority",
                uri=URI(uri=score_path),
                rasters={
                    "Float32": Raster(
                        uri=URI(uri=score_path),
                        bands=[
                            JobBand(name=f"score {key}", metadata={})
                            for key in ("avoid", "reduce", "reverse")
                        ],
                        datatype=DataType.FLOAT32,
                        filetype=RasterFileType.GEOTIFF,
                    ),
                    "Byte": Raster(
                        uri=URI(uri=coverage_path),
                        bands=[
                            JobBand(name=f"coverage {key}", metadata={})
                            for key in ("avoid", "reduce", "reverse")
                        ],
                        datatype=DataType.BYTE,
                        filetype=RasterFileType.GEOTIFF,
                    ),
                },
            )
            job = SimpleNamespace(
                id="job", get_first_result_by_type=lambda _type: result
            )
            with patch("LDMP.jobs.manager.layers.add_layer") as add_layer:
                job_manager.display_selected_job_results(job, [2, 4])
            calls = [(call.args[0], call.args[1]) for call in add_layer.call_args_list]
            # Global band 2 -> score raster band 2; global band 4 -> coverage band 1.
            self.assertEqual(calls, [(str(score_path), 2), (str(coverage_path), 1)])

    def test_priority_map_renders_each_score_band_and_transparent_nodata(self):
        from te_schemas.results import (
            URI,
            DataType,
            Raster,
            RasterFileType,
            RasterResults,
        )
        from te_schemas.results import Band as JobBand

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "priority.tif"
            self._make_multiband(
                path,
                [
                    [[0, 0.333333, 0.333334, 0.666667, 0.666668, 1, -32768]],
                    [[1, 0.666668, 0.666667, 0.333334, 0.333333, 0, -32768]],
                    [[-32768] * 7],
                ],
            )
            bands = [
                JobBand(
                    name=f"LDN Planning - Priority ({key})",
                    no_data_value=-32768,
                    metadata={"priority_class": key},
                )
                for key in ("avoid", "reduce", "reverse")
            ]
            result = RasterResults(
                name="ldn-planning-priority",
                uri=URI(uri=path),
                rasters={
                    "Float32": Raster(
                        uri=URI(uri=path),
                        bands=bands,
                        datatype=DataType.FLOAT32,
                        filetype=RasterFileType.GEOTIFF,
                    )
                },
            )
            job = SimpleNamespace(
                id="job", get_first_result_by_type=lambda _type: result
            )
            added = []

            def add_raster(layer_path, title):
                layer = QgsRasterLayer(layer_path, title)
                added.append(layer)
                return layer

            iface = Mock()
            iface.addRasterLayer.side_effect = add_raster
            with patch.object(layers, "iface", iface):
                job_manager.display_selected_job_results(job, [1, 2, 3])

            self.assertEqual(
                [layer.name() for layer in added],
                [
                    "LDN Planning - Avoid relative priority",
                    "LDN Planning - Reduce relative priority",
                    "LDN Planning - Reverse relative priority",
                ],
            )
            expected = [
                [
                    "#edf8e9",
                    "#edf8e9",
                    "#74c476",
                    "#74c476",
                    "#006d2c",
                    "#006d2c",
                    None,
                ],
                [
                    "#006d2c",
                    "#006d2c",
                    "#74c476",
                    "#74c476",
                    "#edf8e9",
                    "#edf8e9",
                    None,
                ],
                [None] * 7,
            ]
            for index, (layer, colors) in enumerate(zip(added, expected), start=1):
                self.assertEqual(layer.renderer().type(), "singlebandpseudocolor")
                self.assertEqual(layer.renderer().inputBand(), index)
                shader = layer.renderer().shader().rasterShaderFunction()
                self.assertEqual(
                    [item.label for item in shader.colorRampItemList()],
                    [
                        "Low relative priority (0-0.333333)",
                        "Medium relative priority (>0.333333-0.666667)",
                        "High relative priority (>0.666667-1)",
                    ],
                )
                block = layer.renderer().block(1, layer.extent(), 7, 1)
                for column, expected_color in enumerate(colors):
                    color = QColor.fromRgba(block.color(0, column))
                    if expected_color is None:
                        self.assertEqual(color.alpha(), 0)
                    else:
                        self.assertEqual(color.alpha(), 255)
                        self.assertEqual(color.name(), expected_color)

    def test_other_discrete_style_retains_configured_nodata_color(self):
        from te_schemas.results import Band as JobBand

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.tif"
            self._make_multiband(path, [[[20, -32768]]])
            band = JobBand(
                name="LDN Planning - Scenario P(restoration)",
                no_data_value=-32768,
                metadata={},
            )
            layer = QgsRasterLayer(str(path), "scenario")
            self.assertTrue(
                layers.style_layer(
                    str(path),
                    layer,
                    1,
                    layers.styles[band.name],
                    JobBand.Schema().dump(band),
                    in_process_alg=True,
                )
            )
            block = layer.renderer().block(1, layer.extent(), 2, 1)
            self.assertEqual(QColor.fromRgba(block.color(0, 0)).name(), "#c7e9c0")
            nodata = QColor.fromRgba(block.color(0, 1))
            self.assertEqual((nodata.name(), nodata.alpha()), ("#000000", 255))

    def test_planning_actions_hide_panel_reports_but_keep_independent_reports(self):
        from te_schemas.jobs import JobStatus

        from LDMP.ldn_planning_actions import (
            DlgPlanningSummary,
            attach_planning_actions,
        )

        report = {
            "summary": {
                "classes": {"avoid": {"scored_area_km2": 10.0}},
                "scoring_policy": "complete_case_weighted_mean",
            },
            "parameters": {"task_name": "Priority"},
        }
        job = SimpleNamespace(
            id="priority-job",
            task_name="Priority",
            status=JobStatus.GENERATED_LOCALLY,
            script=SimpleNamespace(name="ldn-planning-priority", id="x"),
            results=SimpleNamespace(data={"report": report}),
        )
        button = QtWidgets.QPushButton()
        self.assertTrue(attach_planning_actions(button, job, Mock()))
        titles = [action.text() for action in button.menu().actions()]
        self.assertNotIn("View planning summary...", titles)
        self.assertNotIn("Open Excel report", titles)
        self.assertIn("Open report folder", titles)
        self.assertIn("Select candidate areas...", titles)
        self.assertTrue(button.isEnabled())

        unrelated = SimpleNamespace(script=SimpleNamespace(name="productivity", id="y"))
        other_button = QtWidgets.QPushButton()
        self.assertFalse(attach_planning_actions(other_button, unrelated, Mock()))
        self.assertIsNone(other_button.menu())

        with patch(
            "LDMP.ldn_planning_actions.job_manager.ensure_results_loaded",
            return_value=True,
        ):
            independent_job = SimpleNamespace(
                id="hotspot-job",
                task_name="Hotspots",
                status=JobStatus.GENERATED_LOCALLY,
                script=SimpleNamespace(name="ldn-planning-hotspots", id="x"),
                results=SimpleNamespace(data={"report": report}),
            )
            hotspot_button = QtWidgets.QPushButton()
            self.assertTrue(
                attach_planning_actions(hotspot_button, independent_job, Mock())
            )
            hotspot_titles = [
                action.text() for action in hotspot_button.menu().actions()
            ]
            self.assertIn("View planning summary...", hotspot_titles)
            self.assertIn("Open Excel report", hotspot_titles)
            dialog = DlgPlanningSummary(independent_job)
        texts = [
            dialog.tree.topLevelItem(i).text(0)
            for i in range(dialog.tree.topLevelItemCount())
        ]
        self.assertIn("summary", texts)
        dialog.close()

    def test_projects_preserve_selection_and_explain_lineage(self):
        from te_schemas.jobs import JobStatus

        from LDMP.ldn_planning_panel import PlanningPanel

        jobs = {
            "ldn-planning-arr": [
                SimpleNamespace(
                    id="arr-1",
                    task_name="ARR",
                    status=JobStatus.GENERATED_LOCALLY,
                    params={"aoi_checksum": "area-a"},
                )
            ],
            "ldn-planning-priority": [
                SimpleNamespace(
                    id="priority-1",
                    task_name="Priority",
                    status=JobStatus.GENERATED_LOCALLY,
                    params={"arr_layer_path": "/arr.tif", "aoi_checksum": "area-a"},
                )
            ],
            "ldn-planning-selection": [
                SimpleNamespace(
                    id="candidate-1",
                    task_name="Candidate",
                    status=JobStatus.GENERATED_LOCALLY,
                    params={
                        "aoi_checksum": "area-a",
                        "priority_job_id": "priority-1",
                        "selections": {
                            "avoid": {
                                "mode": "threshold",
                                "threshold": 0.8,
                                "area_km2": 100,
                            }
                        },
                    },
                )
            ],
        }
        area = {"name": "Region A", "sha256": "area-a"}
        baseline = SimpleNamespace(
            job=SimpleNamespace(id="baseline-1"),
            band_index=2,
            path=Path("/baseline.tif"),
            get_name_info=lambda: "Baseline band 2",
            band_info=SimpleNamespace(name=ld_config.SDG_BAND_NAME),
        )
        dock = Mock()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("LDMP.region_selector.download.get_admin_bounds", return_value={}),
            patch("LDMP.region_selector.get_admin_bbox", return_value=None),
            patch("LDMP.ldn_planning_panel.current_area", return_value=area),
            patch("LDMP.ldn_planning_panel.baseline_bands", return_value=[baseline]),
            patch(
                "LDMP.calculate_ldn_priority.planning_raster_jobs",
                side_effect=lambda name: jobs.get(name, []),
            ),
            patch(
                "LDMP.ldn_planning_panel.job_manager.ensure_params_loaded",
                return_value=True,
            ),
            patch(
                "LDMP.calculate_ldn_priority.job_raster_path",
                return_value=("/arr.tif", None),
            ),
            patch.object(
                QtWidgets.QInputDialog, "getText", return_value=("Plan A", True)
            ),
        ):
            settings = QtCore.QSettings(
                str(Path(directory) / "settings.ini"), QtCore.QSettings.Format.IniFormat
            )
            panel = PlanningPanel(dock, settings=settings)
            panel._new_project()
            panel.baseline_combo.setCurrentIndex(
                panel.baseline_combo.findData("baseline-1:2")
            )
            for key, job_id in (
                ("arr", "arr-1"),
                ("priority", "priority-1"),
                ("candidate", "candidate-1"),
            ):
                panel.combos[key].setCurrentIndex(panel.combos[key].findData(job_id))
            self.assertEqual(
                panel.status_icons["candidate"].property("lineage_state"),
                "match",
                (
                    panel.combos["candidate"].currentData(),
                    panel._project()["selections"],
                ),
            )
            with patch("LDMP.ldn_planning_panel.launch_calculate_dialog") as launch:
                panel._select_candidates()
            self.assertEqual(
                launch.call_args.kwargs["preselect_priority_job_id"], "priority-1"
            )
            panel.scenario_editor.execution_name_le.setText("Draft A")
            panel.years["year_initial"].setValue(2000)
            panel.years["year_final"].setValue(2019)
            panel.years["target_year"].setValue(2030)
            first_project = panel._project()["id"]
            with patch.object(
                QtWidgets.QInputDialog, "getText", return_value=("Plan B", True)
            ):
                panel._new_project()
            self.assertIsNone(panel.combos["candidate"].currentData())
            panel.project_combo.setCurrentIndex(
                panel.project_combo.findData(first_project)
            )
            self.assertEqual(panel.combos["candidate"].currentData(), "candidate-1")
            panel.dispose()
            panel.close()

            reopened = PlanningPanel(dock, settings=settings)
            self.assertEqual(reopened.combos["candidate"].currentData(), "candidate-1")
            self.assertEqual(reopened.baseline_combo.currentData(), "baseline-1:2")
            self.assertEqual(
                reopened.scenario_editor.execution_name_le.text(), "Draft A"
            )
            self.assertEqual(reopened.years["year_final"].value(), 2019)
            jobs["ldn-planning-priority"] = []
            reopened.refresh()
            self.assertEqual(reopened.combos["priority"].currentData(), "priority-1")
            self.assertIn(
                "unavailable", reopened.status_labels["priority"].text().lower()
            )
            self.assertIn("Source priority", reopened.status_labels["candidate"].text())
            saved_candidates = jobs["ldn-planning-selection"]
            jobs["ldn-planning-selection"] = []
            reopened.refresh()
            with (
                patch.object(QtWidgets.QMessageBox, "warning"),
                patch.object(QtWidgets.QMessageBox, "critical"),
                patch("LDMP.ldn_planning_panel.launch_calculate_dialog") as launch,
            ):
                reopened._scenario()
                launch.assert_not_called()
            jobs["ldn-planning-selection"] = saved_candidates
            reopened.refresh()
            with patch(
                "LDMP.ldn_planning_panel.current_area",
                return_value={"name": "Region B", "sha256": "area-b"},
            ):
                reopened.refresh()
                self.assertIn("differs", reopened.area_label.text())
                with patch.object(QtWidgets.QMessageBox, "warning"):
                    self.assertFalse(reopened._require_area())
                with patch.object(
                    QtWidgets.QMessageBox,
                    "question",
                    return_value=QtWidgets.QMessageBox.StandardButton.Yes,
                ):
                    reopened._adopt_area()
                self.assertIn(
                    "area changed", reopened.status_labels["candidate"].text()
                )
            reopened.dispose()
            reopened.close()

    def test_planning_panel_refreshes_after_import_and_download(self):
        from te_schemas.jobs import JobStatus

        from LDMP.ldn_planning_panel import PlanningPanel

        class JobSignals(QtCore.QObject):
            imported_job = QtCore.pyqtSignal(object)
            downloaded_job_results = QtCore.pyqtSignal(object)
            submitted_local_job = QtCore.pyqtSignal(object)
            processed_local_job = QtCore.pyqtSignal(object)
            failed_local_job = QtCore.pyqtSignal(object)
            deleted_job = QtCore.pyqtSignal(object)

            def ensure_params_loaded(self, _job):
                return True

        signals = JobSignals()
        area = {"name": "Region A", "sha256": "area-a"}
        baselines = [
            SimpleNamespace(
                job=SimpleNamespace(id="baseline-1"),
                band_index=1,
                get_name_info=lambda: "Original baseline",
            )
        ]
        jobs = [
            SimpleNamespace(
                id="arr-1",
                task_name="Original ARR",
                status=JobStatus.GENERATED_LOCALLY,
                params={"aoi_checksum": "area-a"},
            )
        ]

        @functools.lru_cache(maxsize=1)
        def cached_baselines():
            return list(baselines)

        with (
            tempfile.TemporaryDirectory() as directory,
            patch("LDMP.region_selector.download.get_admin_bounds", return_value={}),
            patch("LDMP.region_selector.get_admin_bbox", return_value=None),
            patch("LDMP.ldn_planning_panel.job_manager", signals),
            patch("LDMP.ldn_planning_panel.current_area", return_value=area),
            patch("LDMP.ldn_planning_panel.baseline_bands", cached_baselines),
            patch(
                "LDMP.calculate_ldn_priority.planning_raster_jobs",
                side_effect=lambda name: jobs if name == "ldn-planning-arr" else [],
            ),
        ):
            settings = QtCore.QSettings(
                str(Path(directory) / "settings.ini"), QtCore.QSettings.Format.IniFormat
            )
            panel = PlanningPanel(Mock(), settings=settings)
            panel.data = {
                "version": 1,
                "current": "project",
                "projects": [
                    {"id": "project", "name": "Plan", "area": area, "selections": {}}
                ],
            }
            panel.refresh()
            panel.baseline_combo.setCurrentIndex(
                panel.baseline_combo.findData("baseline-1:1")
            )
            panel.combos["arr"].setCurrentIndex(panel.combos["arr"].findData("arr-1"))
            # Cache invalidation can be connected after the panel.
            for signal in (signals.imported_job, signals.downloaded_job_results):
                signal.connect(lambda _job: cached_baselines.cache_clear())

            for suffix, signal in (
                ("imported", signals.imported_job),
                ("downloaded", signals.downloaded_job_results),
            ):
                baseline = SimpleNamespace(
                    job=SimpleNamespace(id=f"baseline-{suffix}"),
                    band_index=1,
                    get_name_info=lambda: "New baseline",
                )
                baselines.append(baseline)
                job = SimpleNamespace(
                    id=f"arr-{suffix}",
                    task_name="New ARR",
                    status=JobStatus.DOWNLOADED,
                    params={"aoi_checksum": "area-a"},
                )
                jobs.append(job)
                signal.emit(job)
                QtWidgets.QApplication.processEvents()
                self.assertGreaterEqual(
                    panel.baseline_combo.findData(f"baseline-{suffix}:1"), 0
                )
                self.assertGreaterEqual(panel.combos["arr"].findData(job.id), 0)
                self.assertEqual(panel.baseline_combo.currentData(), "baseline-1:1")
                self.assertEqual(panel.combos["arr"].currentData(), "arr-1")

            jobs.append(
                SimpleNamespace(
                    id="pending", task_name="Pending", status=JobStatus.DOWNLOADED
                )
            )
            signals.downloaded_job_results.emit(jobs[-1])
            panel.dispose()
            QtWidgets.QApplication.processEvents()
            self.assertEqual(panel.combos["arr"].findData("pending"), -1)
            jobs.append(
                SimpleNamespace(
                    id="after-dispose", task_name="Later", status=JobStatus.DOWNLOADED
                )
            )
            signals.downloaded_job_results.emit(jobs[-1])
            QtWidgets.QApplication.processEvents()
            self.assertEqual(panel.combos["arr"].findData("after-dispose"), -1)
            panel.close()

    def test_section_actions_and_transitive_lineage_status(self):
        from te_schemas.jobs import JobStatus

        from LDMP.ldn_planning_panel import PlanningPanel

        def job(job_id, params=None):
            return SimpleNamespace(
                id=job_id,
                task_name=job_id,
                status=JobStatus.GENERATED_LOCALLY,
                params={"aoi_checksum": "area-a", **(params or {})},
            )

        arr1, arr2 = job("arr-1"), job("arr-2")
        land1, land2 = job("land-1"), job("land-2")
        priority = job(
            "priority-1",
            {"arr_layer_path": "/arr-1.tif", "land_type_path": "/land-1.tif"},
        )
        candidate = job(
            "candidate-1",
            {
                "priority_job_id": "priority-1",
                "selections": {
                    "avoid": {"mode": "threshold", "threshold": 0.7, "area_km2": 100}
                },
            },
        )
        candidate2 = job(
            "candidate-2",
            {
                "priority_job_id": "priority-1",
                "selections": {
                    "reverse": {"mode": "area", "threshold": 0.8, "area_km2": 25}
                },
            },
        )
        scenario = job(
            "scenario-1",
            {
                "arr_layer_path": "/arr-1.tif",
                "status_baseline_path": "/baseline.tif",
                "status_baseline_band_index": 2,
                "land_type_path": "/land-1.tif",
                "targets": [{"source_job_id": "candidate-1"}],
                "aoi_checksum": "area-a",
            },
        )
        jobs = {
            "ldn-planning-arr": [arr1, arr2],
            "ldn-planning-land-types": [land1, land2],
            "ldn-planning-priority": [priority],
            "ldn-planning-selection": [candidate, candidate2],
            "ldn-planning-projection": [scenario],
        }
        baseline = SimpleNamespace(
            job=SimpleNamespace(id="baseline-1"),
            band_index=2,
            path=Path("/baseline.tif"),
            get_name_info=lambda: "Baseline",
        )
        baseline2 = SimpleNamespace(
            job=SimpleNamespace(id="baseline-2"),
            band_index=1,
            path=Path("/baseline-2.tif"),
            get_name_info=lambda: "Other baseline",
        )
        area = {"name": "Region A", "sha256": "area-a"}
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("LDMP.region_selector.download.get_admin_bounds", return_value={}),
            patch("LDMP.region_selector.get_admin_bbox", return_value=None),
            patch("LDMP.ldn_planning_panel.current_area", return_value=area),
            patch(
                "LDMP.ldn_planning_panel.baseline_bands",
                return_value=[baseline, baseline2],
            ),
            patch(
                "LDMP.calculate_ldn_priority.planning_raster_jobs",
                side_effect=lambda name: jobs.get(name, []),
            ),
            patch(
                "LDMP.ldn_planning_panel.job_manager.ensure_params_loaded",
                return_value=True,
            ),
            patch(
                "LDMP.calculate_ldn_priority.job_raster_path",
                side_effect=lambda selected: (f"/{selected.id}.tif", None),
            ),
        ):
            settings = QtCore.QSettings(
                str(Path(directory) / "settings.ini"), QtCore.QSettings.Format.IniFormat
            )
            panel = PlanningPanel(Mock(), settings=settings)
            panel.data = {
                "version": 1,
                "current": "project",
                "projects": [
                    {"id": "project", "name": "Plan", "area": area, "selections": {}}
                ],
            }
            panel.refresh()
            panel.baseline_combo.setCurrentIndex(
                panel.baseline_combo.findData("baseline-1:2")
            )
            for key, selected in (
                ("arr", arr1),
                ("land_types", land1),
                ("priority", priority),
                ("candidate", candidate),
                ("scenario", scenario),
            ):
                panel.combos[key].setCurrentIndex(
                    panel.combos[key].findData(selected.id)
                )
            for key in ("priority", "candidate", "scenario"):
                self.assertEqual(
                    panel.status_icons[key].property("lineage_state"),
                    "match",
                    (
                        key,
                        panel.combos[key].currentData(),
                        panel._project()["selections"],
                    ),
                )
            self.assertIn("not verified", panel.status_labels["scenario"].text())

            arr1.params["aoi_checksum"] = "another-area"
            panel._update_status()
            for key in ("arr", "priority", "candidate", "scenario"):
                self.assertEqual(
                    panel.status_icons[key].property("lineage_state"), "stale"
                )
            arr1.params.pop("aoi_checksum")
            panel._update_status()
            for key in ("arr", "priority", "candidate", "scenario"):
                self.assertEqual(
                    panel.status_icons[key].property("lineage_state"), "unknown"
                )
            arr1.params["aoi_checksum"] = "area-a"
            priority.params["arr_job_id"] = "arr-1"
            priority.params["arr_layer_path"] = "/previous-location.tif"
            panel._update_status()
            self.assertEqual(
                panel.status_icons["priority"].property("lineage_state"), "match"
            )
            panel.section_groups["ranking"].setChecked(True)
            panel.section_groups["candidates"].setChecked(True)
            del priority.params["arr_job_id"]
            priority.params["arr_layer_path"] = "/arr-1.tif"
            panel._update_status()

            panel.combos["arr"].setCurrentIndex(panel.combos["arr"].findData("arr-2"))
            for key in ("priority", "candidate", "scenario"):
                self.assertEqual(
                    panel.status_icons[key].property("lineage_state"), "stale"
                )
            with patch("LDMP.ldn_planning_panel.launch_calculate_dialog") as launch:
                panel.step_buttons["priority"].click()
            self.assertEqual(launch.call_args.kwargs["preselect_arr_job_id"], "arr-2")
            self.assertEqual(
                launch.call_args.kwargs["preselect_land_type_job_id"], "land-1"
            )
            with patch("LDMP.ldn_planning_panel.launch_calculate_dialog") as launch:
                panel.step_buttons["candidate"].click()
            self.assertEqual(
                launch.call_args.kwargs["preselect_priority_job_id"], "priority-1"
            )
            self.assertEqual(
                launch.call_args.kwargs["preselect_selections"]["avoid"]["threshold"],
                0.7,
            )
            with patch.object(QtWidgets.QMessageBox, "critical") as error:
                panel.step_buttons["scenario"].click()
            self.assertTrue(error.called)
            with patch("LDMP.ldn_planning_panel.launch_calculate_dialog") as launch:
                panel.step_buttons["arr"].click()
            self.assertTrue(launch.called)
            with patch("LDMP.ldn_planning_panel.launch_calculate_dialog") as launch:
                panel.step_buttons["land_types"].click()
            self.assertTrue(launch.called)

            panel.combos["arr"].setCurrentIndex(panel.combos["arr"].findData("arr-1"))
            panel.baseline_combo.setCurrentIndex(
                panel.baseline_combo.findData("baseline-2:1")
            )
            self.assertEqual(
                panel.status_icons["scenario"].property("lineage_state"), "stale"
            )
            panel.baseline_combo.setCurrentIndex(
                panel.baseline_combo.findData("baseline-1:2")
            )
            panel.combos["candidate"].setCurrentIndex(
                panel.combos["candidate"].findData("candidate-2")
            )
            self.assertEqual(
                panel.status_icons["scenario"].property("lineage_state"), "stale"
            )
            panel.combos["candidate"].setCurrentIndex(
                panel.combos["candidate"].findData("candidate-1")
            )
            panel.combos["land_types"].setCurrentIndex(
                panel.combos["land_types"].findData("land-2")
            )
            self.assertEqual(
                panel.status_icons["priority"].property("lineage_state"), "stale"
            )
            self.assertEqual(
                panel.status_icons["scenario"].property("lineage_state"), "stale"
            )
            panel.combos["land_types"].setCurrentIndex(
                panel.combos["land_types"].findData("land-1")
            )
            panel.combos["land_types"].setCurrentIndex(0)
            self.assertEqual(
                panel.status_icons["priority"].property("lineage_state"), "unknown"
            )
            self.assertEqual(
                panel.status_icons["scenario"].property("lineage_state"), "unknown"
            )
            with patch("LDMP.ldn_planning_panel.launch_calculate_dialog") as launch:
                panel.step_buttons["priority"].click()
            self.assertIsNone(launch.call_args.kwargs["preselect_land_type_job_id"])
            panel.combos["land_types"].setCurrentIndex(
                panel.combos["land_types"].findData("land-1")
            )
            panel.combos["candidate"].setCurrentIndex(0)
            self.assertEqual(
                panel.status_icons["scenario"].property("lineage_state"), "unknown"
            )
            panel.combos["candidate"].setCurrentIndex(
                panel.combos["candidate"].findData("candidate-1")
            )
            priority.params.pop("arr_layer_path")
            panel._update_status()
            self.assertEqual(
                panel.status_icons["priority"].property("lineage_state"), "unknown"
            )
            self.assertEqual(
                panel.status_icons["candidate"].property("lineage_state"), "unknown"
            )
            self.assertEqual(
                panel.status_icons["scenario"].property("lineage_state"), "unknown"
            )
            panel.dispose()
            panel.close()

    def test_unavailable_preselected_band_does_not_select_another(self):
        from LDMP.data_io import WidgetDataIOSelectTELayerExisting
        from LDMP.ldn_planning_actions import select_job_band

        widget = WidgetDataIOSelectTELayerExisting()
        widget.layer_list = [SimpleNamespace(job=SimpleNamespace(id="other"))]
        widget.comboBox_layers.addItem("other")
        with patch.object(QtWidgets.QMessageBox, "warning"):
            select_job_band(widget, "missing", widget, "ARR")
        self.assertEqual(widget.comboBox_layers.currentIndex(), -1)
        self.assertIsNone(widget.get_current_band())

    def test_invalid_project_storage_is_not_replaced(self):
        from LDMP.ldn_planning_panel import SETTINGS_KEY, load_projects

        with tempfile.TemporaryDirectory() as directory:
            settings = QtCore.QSettings(
                str(Path(directory) / "settings.ini"), QtCore.QSettings.Format.IniFormat
            )
            settings.setValue(SETTINGS_KEY, "{broken")
            with self.assertRaises(ValueError):
                load_projects(settings)
            self.assertEqual(settings.value(SETTINGS_KEY), "{broken")

    def test_project_migration_preserves_selections_without_inventing_settings_or_targets(
        self,
    ):
        from LDMP.ldn_planning_panel import SETTINGS_KEY, load_projects, save_projects

        with tempfile.TemporaryDirectory() as directory:
            settings = QtCore.QSettings(
                str(Path(directory) / "settings.ini"), QtCore.QSettings.Format.IniFormat
            )
            selections = {
                "baseline": {
                    "job_id": "baseline",
                    "band_index": 3,
                    "area_sha256": "area",
                },
                "candidate": {"job_id": "candidate", "area_sha256": "area"},
            }
            settings.setValue(
                SETTINGS_KEY,
                json.dumps(
                    {
                        "version": 1,
                        "current": "project",
                        "projects": [
                            {
                                "id": "project",
                                "name": "Plan",
                                "area": {"name": "Area", "sha256": "area"},
                                "selections": selections,
                            }
                        ],
                    }
                ),
            )
            migrated = load_projects(settings)
            project = migrated["projects"][0]
            self.assertEqual(migrated["version"], 2)
            self.assertEqual(project["selections"], selections)
            self.assertIsNone(project["context"]["year_initial"])
            self.assertEqual(project["context"]["breakdown"], "none")
            self.assertEqual(project["drafts"][0]["targets"], [])
            self.assertFalse(project["drafts"][0]["use_candidates"])
            save_projects(settings, migrated)
            self.assertEqual(load_projects(settings), migrated)
            for invalid in (None, {"breakdown": "unknown"}):
                corrupted = copy.deepcopy(migrated)
                corrupted["projects"][0]["context"] = invalid
                settings.setValue(SETTINGS_KEY, json.dumps(corrupted))
                raw = settings.value(SETTINGS_KEY)
                with self.assertRaises(ValueError):
                    load_projects(settings)
                self.assertEqual(settings.value(SETTINGS_KEY), raw)

    def test_planning_tab_order_navigation_and_disposal(self):
        from LDMP import ldn_planning_panel
        from LDMP.main_widget import MainWidget

        with (
            tempfile.TemporaryDirectory() as directory,
            patch("LDMP.region_selector.download.get_admin_bounds", return_value={}),
            patch("LDMP.region_selector.get_admin_bbox", return_value=None),
            patch("LDMP.ldn_planning_panel.baseline_bands", return_value=[]),
            patch("LDMP.calculate_ldn_priority.planning_raster_jobs", return_value=[]),
        ):
            settings = QtCore.QSettings(
                str(Path(directory) / "settings.ini"), QtCore.QSettings.Format.IniFormat
            )
            dock = MainWidget.__new__(MainWidget)
            QtWidgets.QDockWidget.__init__(dock)
            dock.setupUi(dock)
            dock.iface = Mock()
            panel_type = ldn_planning_panel.PlanningPanel
            with patch.object(
                ldn_planning_panel,
                "PlanningPanel",
                side_effect=lambda main, parent: panel_type(main, parent, settings),
            ):
                dock.setup_planning_tab()
                panel = ldn_planning_panel.open_panel(dock)
                self.assertNotIsInstance(panel, QtWidgets.QDockWidget)
                self.assertEqual(
                    [dock.tabWidget.tabText(i) for i in range(dock.tabWidget.count())],
                    ["Algorithms", "Datasets", "LDN Planning", "News"],
                )
                self.assertIs(dock.tabWidget.currentWidget(), panel)
                dock.tabWidget.setCurrentIndex(1)
                self.assertIs(ldn_planning_panel.open_panel(dock), panel)
                dock._update_news_tab_style(True)
                self.assertIn("News", dock.tabWidget.tabText(3))
                self.assertEqual(dock.tabWidget.tabText(2), "LDN Planning")
                panel.dispose()
                panel.dispose()
                self.assertTrue(panel._disposed)
                dock.deleteLater()

    def test_scenario_editor_has_only_target_and_draft_controls(self):
        parent = QtWidgets.QWidget()
        parent._main_dock = Mock()
        editor = ScenarioTargetsWidget(parent)
        for name in (
            "combo_arr",
            "combo_baseline",
            "combo_reporting",
            "combo_candidates",
            "combo_land_type",
        ):
            self.assertFalse(hasattr(editor, name))
        self.assertEqual(editor.findChildren(QtWidgets.QTabWidget), [])
        editor.close()
        parent.close()

    def test_histogram_text(self):
        from LDMP.ldn_planning_assets import histogram_text

        bars = histogram_text(np.array([0.1, 0.2, 1.0]))
        self.assertTrue(bars.startswith("0.1 |"))
        self.assertTrue(bars.endswith("| 1"))


class PrioritizationJobTests(unittest.TestCase):
    def test_weight_ratios_and_maximum_area_caps(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            arr = directory / "arr.tif"
            capital = directory / "capital.tif"
            cost = directory / "cost.tif"
            make_raster(arr, [[1, 1]])
            make_raster(capital, [[0.2, 0.9]])
            make_raster(cost, [[0, 1]])
            criteria = [
                dict(
                    name=name,
                    path=str(path),
                    arr_class="avoid",
                    minimum=0,
                    maximum=1,
                    weight=weight,
                    direction=direction,
                    source="Inventory",
                    date="2025",
                    units="index",
                    license="CC BY",
                    resampling="nearest",
                )
                for name, path, weight, direction in (
                    ("Capital", capital, 2, "higher"),
                    ("Cost", cost, 1, "lower"),
                )
            ]
            priority = compute_priority_local(
                SimpleNamespace(
                    params=dict(arr_layer_path=str(arr), criteria=criteria)
                ),
                None,
                directory / "priority.json",
                directory / "unused.tif",
            )
            dataset = gdal.Open(str(priority.uri.uri))
            values = dataset.GetRasterBand(1).ReadAsArray()
            self.assertAlmostEqual(float(values[0, 0]), 0.2 * 2 / 3 + 1 / 3)
            self.assertAlmostEqual(float(values[0, 1]), 0.9 * 2 / 3)
            for budget, expected in ((0.5, [[0, 0]]), (1.3, [[0, 1]])):
                selection_job = SimpleNamespace(
                    params=dict(
                        score_path=str(priority.uri.uri),
                        priority_job_id="priority",
                        priority_params={"aoi_checksum": "source-area"},
                        selections={"avoid": {"mode": "area", "area_km2": budget}},
                    )
                )
                selection = compute_selection_local(
                    selection_job,
                    None,
                    directory / f"area_{budget}.json",
                    directory / "unused.tif",
                )
                dataset = gdal.Open(str(selection.uri.uri))
                self.assertEqual(dataset.ReadAsArray().tolist(), expected)
                self.assertEqual(selection_job.params["aoi_checksum"], "source-area")

    def test_arr_handler_preserves_fractional_risk_and_unknown_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            status = directory / "status.tif"
            risk = directory / "risk.tif"
            make_raster(status, [[1, 0, -1, 0, 0]])
            make_raster(risk, [[0.25, 0.75, 0, -32768, 0.25]])
            job = SimpleNamespace(
                params=dict(
                    status_layer_path=str(status),
                    status_type="3class",
                    risk_layer_path=str(risk),
                    risk_threshold=0.5,
                )
            )
            result = compute_arr_local(
                job, None, directory / "arr.json", directory / "unused.tif"
            )
            dataset = gdal.Open(str(result.uri.uri))
            self.assertEqual(
                dataset.GetRasterBand(1).ReadAsArray().tolist(),
                [[1, 2, 3, -32768, 1]],
            )
            reason_band = result.rasters["Int16"].bands[1]
            with open(Path(layers.__file__).parent / "data" / "styles.json") as source:
                styles = json.load(source)
            layer = QgsRasterLayer(str(result.uri.uri), "ARR reasons")
            self.assertTrue(
                layers.style_layer(
                    str(result.uri.uri),
                    layer,
                    2,
                    styles[reason_band.name],
                    reason_band.Schema().dump(reason_band),
                    in_process_alg=True,
                )
            )
            del layer

    def test_candidate_target_snapshots_preserve_fractional_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            arr, baseline, reporting, mask = [
                directory / name
                for name in ("arr.tif", "baseline.tif", "reporting.tif", "mask.tif")
            ]
            make_raster(arr, [[3, 3, 1]])
            make_raster(baseline, [[-1, 0, 0]])
            make_raster(reporting, [[-1, -1, 0]])
            make_raster(mask, [[3, 0, 0]])
            target = dict(
                selected_mask_path=str(mask),
                intervention="reverse",
                effectiveness=0.5,
                configured_effectiveness=0.5,
                mask_sha256=file_checksum(mask),
                source_job_id="candidate",
            )
            job = SimpleNamespace(
                params=dict(
                    arr_layer_path=str(arr),
                    status_baseline_path=str(baseline),
                    status_reporting_path=str(reporting),
                    status_baseline_type="3class",
                    status_reporting_type="3class",
                    year_initial=2000,
                    year_final=2020,
                    target_year=2030,
                    targets=[target],
                )
            )
            result = compute_planning_local(
                job, None, directory / "scenario.json", directory / "unused.tif"
            )
            dataset = gdal.Open(str(result.uri.uri))
            values = dataset.GetRasterBand(1).ReadAsArray()
            self.assertEqual(float(values[0, 0]), 50)
            self.assertEqual(float(values[0, 1]), 0)
            self.assertIn("Int16", result.rasters)
            snapshot = Path(
                result.data["report"]["target_provenance"][0]["selected_mask_path"]
            )
            self.assertNotEqual(snapshot, mask)
            self.assertEqual(file_checksum(snapshot), file_checksum(mask))
            make_raster(snapshot, [[3, 3, 3]])
            with self.assertRaisesRegex(ValueError, "Candidate raster changed"):
                compute_planning_local(
                    job, None, directory / "changed.json", directory / "unused.tif"
                )

    def test_scoring_and_selection_publish_real_bands_and_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            arr_path = directory / "arr.tif"
            criterion_path = directory / "criterion.tif"
            make_raster(arr_path, [[1, 1, 2, 3]])
            make_raster(criterion_path, [[0.2, 0.9, 0.5, 0.8]])
            criterion = dict(
                name="Capital",
                path=str(criterion_path),
                band_index=1,
                arr_class="avoid",
                minimum=0,
                maximum=1,
                direction="higher",
                weight=1,
                source="Inventory",
                date="2025",
                units="index",
                license="CC BY",
                resampling="nearest",
            )
            job = SimpleNamespace(
                params=dict(
                    arr_layer_path=str(arr_path),
                    criteria=[criterion],
                    task_name="Priority",
                )
            )
            result = compute_priority_local(
                job, None, directory / "priority.json", directory / "dataset.tif"
            )
            self.assertEqual(result.name, "ldn-planning-priority")
            dataset = gdal.Open(str(result.uri.uri))
            self.assertEqual(dataset.RasterCount, 3)
            values = dataset.GetRasterBand(1).ReadAsArray()
            self.assertAlmostEqual(float(values[0, 1]), 0.9, places=5)
            self.assertEqual(float(values[0, 2]), -32768)
            coverage = result.rasters["Byte"]
            coverage_dataset = gdal.Open(str(coverage.uri.uri))
            self.assertEqual(
                coverage_dataset.GetRasterBand(1).ReadAsArray().tolist(),
                [[1, 1, 255, 255]],
            )
            selected_job = SimpleNamespace(
                params=dict(
                    score_path=str(result.uri.uri),
                    priority_job_id="priority",
                    priority_params=job.params,
                    selections={"avoid": {"mode": "threshold", "threshold": 0.8}},
                )
            )
            selected = compute_selection_local(
                selected_job,
                None,
                directory / "selection.json",
                directory / "unused.tif",
            )
            mask = gdal.Open(str(selected.uri.uri)).ReadAsArray()
            self.assertEqual(int(mask[0, 1]), 1)
            self.assertNotEqual(int(mask[0, 0]), 1)
            self.assertNotIn("approved", selected.rasters["Int16"].bands[0].metadata)
            # Reports must not share the job metadata file name.
            for name in ("selection_candidates", "priority_priority"):
                self.assertTrue((directory / f"{name}.xlsx").is_file())
                self.assertTrue((directory / f"{name}.json").is_file())
            configuration = SimpleNamespace(
                panel=Mock(),
                _targets=[],
                targets_list=Mock(),
                tr=lambda text: text,
                _configure_candidate_targets=Mock(return_value={"avoid": 0.5}),
                use_candidates=Mock(),
                changed=Mock(),
            )
            configuration.panel._selected.return_value = SimpleNamespace(
                id="selection", task_name="Candidates", params=selected_job.params
            )
            configuration.panel.candidate_target_context.return_value = {
                "area_sha256": "area",
                "arr_job_id": "arr",
            }
            with (
                patch(
                    "LDMP.calculate_ldn_priority.job_raster_path",
                    return_value=(str(selected.uri.uri), selected),
                ),
                patch(
                    "LDMP.calculate_ldn_planning.job_manager.ensure_params_loaded",
                    return_value=True,
                ),
                patch.object(QtWidgets.QMessageBox, "critical") as error,
            ):
                ScenarioTargetsWidget._configure_candidates(configuration)
                self.assertEqual(len(configuration._targets), 1)
                self.assertEqual(
                    configuration._targets[0]["configured_effectiveness"], 0.5
                )
                self.assertEqual(configuration._targets[0]["effectiveness"], 0.5)
                self.assertEqual(configuration._targets[0]["intervention"], "avoid")
                make_raster(selected.uri.uri, [[1, 1, 0, 0]])
                ScenarioTargetsWidget._configure_candidates(configuration)
                error.assert_called_once()
                self.assertIn("no longer matches its report", error.call_args.args[2])
