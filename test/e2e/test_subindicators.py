"""Offline regression tests for the dialog-driven separate sub-indicators."""

import contextlib
import types
import unittest
from pathlib import Path
from unittest import mock

from qgis.gui import QgsMapCanvas, QgsMessageBar
from qgis.PyQt import QtCore, QtWidgets
from qgis.testing import start_app
from te_algorithms.gdal.land_deg import config as ld_config

from LDMP import calculate, conf, lc_setup
from LDMP.calculate_lc import DlgCalculateLC
from LDMP.calculate_prod import DlgCalculateProd
from LDMP.calculate_soc import DlgCalculateSOC

from . import harness, subindicators, test_remote_pipelines
from .harness import DialogDriver, job_manager
from .test_remote_pipelines import TASK_NOTES


class SubindicatorDialogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = start_app()

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(
            mock.patch("LDMP.download.get_admin_bounds", return_value={"test": {}})
        )
        self.stack.enter_context(
            mock.patch("LDMP.download.get_cities", return_value={"test": {}})
        )
        for name, value in (
            ("ipcc_lc_nesting_from_settings", lc_setup.get_default_ipcc_nesting()),
            ("esa_lc_nesting_from_settings", lc_setup.get_default_esa_nesting()),
            ("trans_matrix_from_settings", None),
        ):
            self.stack.enter_context(
                mock.patch.object(lc_setup, name, return_value=value)
            )
        for name in (
            "ipcc_lc_nesting_to_settings",
            "esa_lc_nesting_to_settings",
            "trans_matrix_to_settings",
        ):
            self.stack.enter_context(mock.patch.object(lc_setup, name))
        self.stack.enter_context(
            mock.patch.object(calculate.DlgCalculateBase, "update_current_region")
        )
        self.stack.enter_context(
            mock.patch.object(
                calculate.DlgCalculateBase, "btn_calculate", return_value=True
            )
        )
        iface = mock.Mock()
        self.canvas = QgsMapCanvas()
        self.message_bar = QgsMessageBar()
        iface.mapCanvas.return_value = self.canvas
        iface.messageBar.return_value = self.message_bar
        self.driver = DialogDriver(iface)
        self.addCleanup(self.driver.main_dock.deleteLater)
        self.submit = self.stack.enter_context(
            mock.patch.object(
                job_manager, "submit_remote_job", return_value=mock.Mock(id="accepted")
            )
        )

    def run_dialog(self, dlg_cls, script_name, configure):
        def setup(dlg):
            dlg.aoi = mock.Mock()
            dlg.aoi.get_crs_dst_wkt.return_value = "EPSG:4326"
            dlg.gee_bounding_box = (False, [{"type": "Polygon", "coordinates": []}])
            configure(dlg)
            dlg.execution_name_le.setText("e2e-offline")
            dlg.task_notes.setPlainText(TASK_NOTES)
            dlg.options_tab.task_notes.setPlainText(TASK_NOTES)

        run = self.driver.run(dlg_cls, script_name, setup)
        self.assertEqual(run.errors, [])
        self.assertEqual(len(run.remote), 1)
        self.assertIsNotNone(run.remote[0].job)
        self.submit.assert_called_once()
        payload, script_id = self.submit.call_args.args
        self.assertEqual(script_id, conf.KNOWN_SCRIPTS[script_name].id)
        self.assertEqual(payload["task_name"], "e2e-offline")
        self.assertEqual(payload["task_notes"], TASK_NOTES)
        self.assertIn("geojsons", payload)
        return payload

    def test_productivity_dialog_submits_all_three_components(self):
        payload = self.run_dialog(
            DlgCalculateProd, "productivity", subindicators.configure_productivity
        )
        prod = payload["productivity"]
        for key in ("calc_traj", "calc_perf", "calc_state"):
            self.assertIs(prod[key], True)
        self.assertEqual(prod["trajectory_method"], "ndvi_trend")
        self.assertEqual(prod["traj_year_initial"], 2001)
        self.assertEqual(prod["traj_year_final"], 2015)
        self.assertEqual(prod["perf_year_initial"], 2001)
        self.assertEqual(prod["perf_year_final"], 2015)
        self.assertEqual(prod["state_year_bl_start"], 2001)
        self.assertEqual(prod["state_year_bl_end"], 2012)
        self.assertEqual(prod["state_year_tg_start"], 2013)
        self.assertEqual(prod["state_year_tg_end"], 2015)

    def test_land_cover_dialog_submits_baseline(self):
        payload = self.run_dialog(
            DlgCalculateLC, "land-cover", subindicators.configure_land_cover
        )
        self.assertEqual(payload["year_initial"], 2000)
        self.assertEqual(payload["year_final"], 2015)
        self.assertTrue(payload["trans_matrix"])
        self.assertTrue(payload["legend_nesting_custom_to_ipcc"])

    def test_soc_dialog_submits_baseline_with_annual_stocks(self):
        payload = self.run_dialog(
            DlgCalculateSOC, "soil-organic-carbon", subindicators.configure_soc
        )
        self.assertEqual(payload["year_initial"], 2000)
        self.assertEqual(payload["year_final"], 2015)
        self.assertEqual(payload["fl"], "per pixel")
        self.assertIs(payload["download_annual_lc"], True)

    def test_unavailable_year_is_an_error_not_silently_clamped(self):
        widget = QtWidgets.QDateEdit()
        self.addCleanup(widget.deleteLater)
        widget.setMaximumDate(QtCore.QDate(2005, 1, 1))
        with self.assertRaisesRegex(ValueError, "does not support year 2015"):
            subindicators.set_year(widget, 2015)


class SeparateInputTest(unittest.TestCase):
    def setUp(self):
        self.jobs = [
            types.SimpleNamespace(id=name) for name in ("prod", "lc", "soc", "pop")
        ]
        self.dlg = mock.Mock()
        self.widgets = mock.Mock()
        self.dlg.combo_boxes = {"baseline": self.widgets}

    def test_layers_are_selected_from_the_separate_jobs(self):
        with (
            mock.patch.object(subindicators, "select_dataset_by_job_id") as select,
            mock.patch.object(subindicators, "layer_matches_job", return_value=True),
        ):
            subindicators.select_separate_inputs(self.dlg, *self.jobs)
        select.assert_called_once_with(self.widgets.combo_datasets, "pop")
        for combo in (
            self.widgets.combo_layer_traj,
            self.widgets.combo_layer_perf,
            self.widgets.combo_layer_state,
        ):
            combo.set_index_from_job_id.assert_called_once_with("prod")
        self.widgets.combo_layer_lc.set_index_from_job_id.assert_called_once_with("lc")
        self.widgets.combo_layer_soc.set_index_from_job_id.assert_called_once_with(
            "soc"
        )
        self.dlg.checkBox_progress_period.setChecked.assert_called_once_with(False)
        self.dlg.radio_population_baseline_bysex.setChecked.assert_called_once_with(
            True
        )

    def test_missing_component_is_not_replaced_by_one_step_output(self):
        self.widgets.combo_layer_soc.set_index_from_job_id.return_value = False
        with (
            mock.patch.object(subindicators, "select_dataset_by_job_id"),
            mock.patch.object(subindicators, "layer_matches_job", return_value=True),
            self.assertRaisesRegex(LookupError, "No soil organic carbon layer"),
        ):
            subindicators.select_separate_inputs(self.dlg, *self.jobs)

    def test_total_population_fallback(self):
        def matches(combo, job_id):
            return combo not in (
                self.widgets.combo_layer_pop_male,
                self.widgets.combo_layer_pop_female,
            )

        with (
            mock.patch.object(subindicators, "select_dataset_by_job_id"),
            mock.patch.object(subindicators, "layer_matches_job", side_effect=matches),
        ):
            subindicators.select_separate_inputs(self.dlg, *self.jobs)
        self.dlg.radio_population_baseline_total.setChecked.assert_called_once_with(
            True
        )

    def test_no_population_is_an_error(self):
        def matches(combo, job_id):
            return combo not in (
                self.widgets.combo_layer_pop_male,
                self.widgets.combo_layer_pop_female,
                self.widgets.combo_layer_pop_total,
            )

        with (
            mock.patch.object(subindicators, "select_dataset_by_job_id"),
            mock.patch.object(subindicators, "layer_matches_job", side_effect=matches),
            self.assertRaisesRegex(LookupError, "No population layer"),
        ):
            subindicators.select_separate_inputs(self.dlg, *self.jobs)

    def test_local_job_paths_must_match_separate_sources(self):
        paths = {
            "layer_traj_path": "/prod.vrt",
            "layer_perf_path": "/prod.vrt",
            "layer_state_path": "/prod.vrt",
            "layer_lc_path": "/lc.vrt",
            "layer_soc_path": "/soc.vrt",
        }
        summary = types.SimpleNamespace(
            params={"periods": [{"name": "baseline", "params": paths}]}
        )
        with mock.patch.object(
            harness,
            "job_output_path",
            side_effect=lambda job: Path(f"/{job.id}.vrt"),
        ):
            subindicators.verify_separate_input_paths(summary, *self.jobs[:3])
            paths["layer_lc_path"] = "/one-step.vrt"
            with self.assertRaisesRegex(
                AssertionError, "layer_lc_path did not use job"
            ):
                subindicators.verify_separate_input_paths(summary, *self.jobs[:3])

    def test_separate_summary_uses_existing_json_checker(self):
        runner = mock.Mock()
        test_remote_pipelines.RemotePipelinesE2ETest._sdg_separate_checks(runner, "STP")
        from .summary_checks import check_sdg_summary

        runner._check_summary.assert_called_once_with(
            "STP", "sdg_separate", check_sdg_summary
        )

    def test_required_output_bands(self):
        for chain, bands in (
            (
                "productivity",
                [
                    ld_config.TRAJ_BAND_NAME,
                    ld_config.PERF_BAND_NAME,
                    ld_config.STATE_BAND_NAME,
                ],
            ),
            (
                "land_cover",
                [
                    ld_config.LC_DEG_BAND_NAME,
                    ld_config.LC_BAND_NAME[0],
                    ld_config.LC_TRANS_BAND_NAME,
                ],
            ),
            ("soc", [ld_config.SOC_DEG_BAND_NAME, ld_config.SOC_BAND_NAME]),
        ):
            with self.subTest(chain=chain):
                subindicators.check_subindicator_bands(chain, bands)
                with self.assertRaisesRegex(AssertionError, "missing required bands"):
                    subindicators.check_subindicator_bands(chain, bands[:-1])

    def test_land_cover_band_alias(self):
        subindicators.check_subindicator_bands(
            "land_cover",
            [
                ld_config.LC_DEG_BAND_NAME,
                "Land cover (7 class)",
                ld_config.LC_TRANS_BAND_NAME,
            ],
        )

    def test_failed_subindicator_blocks_calculation_and_checks(self):
        runner = test_remote_pipelines.RemotePipelinesE2ETest(
            "test_8_sdg_from_separate_subindicators"
        )
        runner.status = {
            ("STP", "productivity_outputs"): "ok",
            ("STP", "land_cover_outputs"): "failed: missing bands",
            ("STP", "soc_outputs"): "ok",
            ("STP", "sdg_remote"): "ok",
        }
        self.assertEqual(
            runner._blocker("STP", "sdg_separate_summary"), "land_cover_outputs"
        )
        runner.status[("STP", "sdg_separate_summary")] = "skipped: land_cover_outputs"
        self.assertEqual(
            runner._blocker("STP", "sdg_separate_checks"), "sdg_separate_summary"
        )
