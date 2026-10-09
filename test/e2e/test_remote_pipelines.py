"""Opt-in end-to-end test of the SDG 15.3.1 and drought pipelines.

For each country this submits remote jobs to the real Trends.Earth API through
the plugin's own dialogs, waits for them, downloads the results, runs the
summary tools, and builds UNCCD/PRAIS packages (SDG only, drought only, and
combined).

The test authenticates as a dedicated test user with an OAuth2 service
credential and only runs via ``test_suite.test_e2e`` with
``TE_E2E_CLIENT_ID`` and ``TE_E2E_CLIENT_SECRET`` set.
See ``test/README.md`` for details.
"""

import json
import unittest

from .harness import (
    E2E_SKIP_REASON,
    REMOTE_SUCCESS_STATUSES,
    DialogDriver,
    E2EConfig,
    LocalJobTracker,
    copy_job_artifacts,
    country_aoi_area_km2,
    download_jobs,
    e2e_enabled,
    find_job,
    find_summary_json,
    get_iface,
    job_band_names,
    job_output_path,
    layer_matches_job,
    process_events_for,
    say,
    select_dataset_by_job_id,
    set_country_aoi,
    utc_stamp,
    validate_package,
    wait_for_remote,
)
from .summary_checks import Thresholds, check_drought_summary, check_sdg_summary

SDG_PRESET = "UNCCD Reporting (2026 reporting cycle - Default Data, Trends.Earth)"
TASK_NOTES = "Automated e2e test"
MIN_DROUGHT_YEARS = 5

STAGES = (
    "sdg_remote",
    "sdg_summary",
    "sdg_checks",
    "sdg_package",
    "drought_remote",
    "drought_summary",
    "drought_checks",
    "drought_package",
    "combined_package",
)
DEPENDS_ON = {
    "sdg_summary": ("sdg_remote",),
    "sdg_checks": ("sdg_summary",),
    "sdg_package": ("sdg_checks",),
    "drought_summary": ("drought_remote",),
    "drought_checks": ("drought_summary",),
    "drought_package": ("drought_checks",),
    "combined_package": ("sdg_checks", "drought_checks"),
}


@unittest.skipUnless(e2e_enabled(), E2E_SKIP_REASON)
class RemotePipelinesE2ETest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import contextlib

        from .harness import (
            auth_placeholder,
            installed_api_client,
            isolated_plugin_state,
        )
        from .service_auth import ServiceCredentialAPIClient

        cls.config = E2EConfig.from_env()
        cls.stamp = utc_stamp()
        cls.status = {}
        cls.remote_jobs = {}
        cls.summary_jobs = {}
        cls.packages = {}
        cls.checks = {}
        cls._stack = contextlib.ExitStack()
        cls.tracker = None
        try:
            from LDMP.constants import get_api_url

            api_url = cls.config.api_url or get_api_url()
            cls.client = ServiceCredentialAPIClient(
                api_url, cls.config.client_id, cls.config.client_secret
            )
            say(f"api: {api_url}; countries: {','.join(cls.config.countries)}")
            cls.config.output_dir.mkdir(parents=True, exist_ok=True)

            cls._stack.enter_context(isolated_plugin_state())
            cls._stack.enter_context(installed_api_client(cls.client))
            cls._stack.enter_context(auth_placeholder(cls.config.client_id))
            cls.tracker = LocalJobTracker()
            cls.driver = DialogDriver(get_iface())

            cls._check_service_credential()
            cls._submit_remote_jobs()
            cls._wait_and_download()
        except Exception:
            try:
                cls._write_summary()
            finally:
                cls._cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        try:
            cls._write_summary()
        finally:
            cls._cleanup()

    @classmethod
    def _cleanup(cls):
        if cls.tracker is not None:
            cls.tracker.disconnect_all()
            cls.tracker = None
        cls._stack.close()

    # ------------------------------------------------------------------
    # Remote stages (run once for all countries so GEE jobs overlap)
    # ------------------------------------------------------------------

    @classmethod
    def _check_service_credential(cls):
        from LDMP import conf

        if not cls.client.login():
            raise RuntimeError(
                "Could not obtain an access token with the e2e service credential. "
                "Check that it is valid and has the scopes execution:read "
                "execution:write script:read user:read boundary:read."
            )
        user = cls.client.get_user("me")
        if not user or not user.get("id"):
            raise RuntimeError(
                "The service credential could not read its user (needs user:read)."
            )
        conf.settings_manager.write_value(conf.Setting.USER_ID, str(user["id"]))
        say(f"authenticated as service user {user['id']}")

    @classmethod
    def _task_name(cls, iso3, chain):
        return f"e2e-{iso3}-{chain}-{cls.stamp}"

    @classmethod
    def _submit_remote_jobs(cls):
        for iso3 in cls.config.countries:
            try:
                set_country_aoi(iso3)
            except Exception as exc:  # noqa: BLE001
                reason = cls.client.redact(f"failed: {exc}")
                cls.status[(iso3, "sdg_remote")] = reason
                cls.status[(iso3, "drought_remote")] = reason
                continue
            for chain, submit in (
                ("sdg", cls._submit_sdg),
                ("drought", cls._submit_drought),
            ):
                try:
                    cls.remote_jobs[(iso3, chain)] = submit(iso3)
                    say(f"{iso3} {chain}: submitted")
                except Exception as exc:  # noqa: BLE001
                    message = cls.client.redact(f"failed: submission: {exc}")
                    say(f"{iso3} {chain}: {message}")
                    cls.status[(iso3, f"{chain}_remote")] = message

    @classmethod
    def _submit_sdg(cls, iso3):
        from LDMP.calculate_ldn import DlgCalculateOneStep

        task_name = cls._task_name(iso3, "sdg")

        def configure(dlg):
            dlg._select_preset_by_name(SDG_PRESET)
            if dlg.comboBox_presets.currentData() != SDG_PRESET:
                raise LookupError(f"Preset {SDG_PRESET!r} is not available")
            dlg.on_apply_preset()
            process_events_for(0.5)
            dlg.execution_name_le.setText(task_name)
            dlg.task_notes.setPlainText(TASK_NOTES)

        run = cls.driver.run(
            DlgCalculateOneStep, "sdg-15-3-1-sub-indicators", configure
        )
        if run.errors:
            raise RuntimeError("; ".join(run.errors))
        if not run.remote:
            raise RuntimeError("the dialog did not submit any job")
        periods = {}
        for params, job in run.remote:
            period = (params.get("period") or {}).get("name", "baseline")
            if job is None:
                raise RuntimeError(f"the API rejected the {period} job")
            periods[period] = job
        if "baseline" not in periods:
            raise RuntimeError(f"no baseline period submitted: {sorted(periods)}")
        # Summary dialog keys: baseline, report_1, report_2, ...
        jobs = {"baseline": periods.pop("baseline")}
        for name in sorted(periods, key=lambda n: int(n.rsplit("_", 1)[-1])):
            jobs[f"report_{name.rsplit('_', 1)[-1]}"] = periods[name]
        return jobs

    @classmethod
    def _submit_drought(cls, iso3):
        from LDMP.calculate_drought_vulnerability import DlgCalculateDrought

        task_name = cls._task_name(iso3, "drought")

        def configure(dlg):
            initial = dlg.year_initial_de.date().year()
            final = dlg.year_final_de.date().year()
            if final - initial < MIN_DROUGHT_YEARS:
                dlg.year_initial_de.setDate(dlg.year_initial_de.minimumDate())
                dlg.year_final_de.setDate(dlg.year_final_de.maximumDate())
            dlg.execution_name_le.setText(task_name)
            dlg.task_notes.setPlainText(TASK_NOTES)

        run = cls.driver.run(DlgCalculateDrought, "drought-vulnerability", configure)
        if run.errors:
            raise RuntimeError("; ".join(run.errors))
        if len(run.remote) != 1:
            raise RuntimeError(f"expected 1 submission, got {len(run.remote)}")
        job = run.remote[0][1]
        if job is None:
            raise RuntimeError("the API rejected the drought job")
        return {"drought": job}

    @classmethod
    def _wait_and_download(cls):
        all_ids = [job.id for jobs in cls.remote_jobs.values() for job in jobs.values()]
        if not all_ids:
            return
        say(f"waiting for {len(all_ids)} remote job(s)")
        final = wait_for_remote(all_ids, cls.config.timeout_min, cls.config.poll_sec)
        finished = [
            job_id for job_id, st in final.items() if st in REMOTE_SUCCESS_STATUSES
        ]
        say(f"downloading {len(finished)} finished job(s)")
        download_errors = download_jobs(finished, cls.config.timeout_min)

        for (iso3, chain), jobs in cls.remote_jobs.items():
            problems = []
            for key, job in jobs.items():
                st = final.get(job.id)
                if st not in REMOTE_SUCCESS_STATUSES:
                    label = st.value.lower() if st else "not finished before timeout"
                    problems.append(f"{key} job {job.id} ended as {label}")
                elif download_errors.get(job.id):
                    problems.append(f"{key} job {job.id}: {download_errors[job.id]}")
                else:
                    _, refreshed = find_job(job.id)
                    jobs[key] = refreshed or job
                    copy_job_artifacts(
                        jobs[key],
                        cls._artifact_dir(iso3, chain, f"remote_{key}"),
                        include_outputs=False,
                    )
            cls.status[(iso3, f"{chain}_remote")] = (
                "failed: " + "; ".join(problems) if problems else "ok"
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def _artifact_dir(cls, iso3, chain, stage):
        return cls.config.output_dir / iso3 / chain / stage

    def _blocker(self, iso3, stage):
        for dependency in DEPENDS_ON.get(stage, ()):
            if self.status.get((iso3, dependency)) != "ok":
                return dependency
        return None

    def _run_chain(self, iso3, stages):
        """Run dependent stages for one country and report the root failure."""
        with self.subTest(country=iso3):
            failures = []
            skipped = []
            for stage, func in stages:
                if stage.endswith("_remote"):
                    result = self.status.get((iso3, stage), "failed: not submitted")
                    if result != "ok":
                        failures.append(f"{stage}: {result}")
                    continue
                blocker = self._blocker(iso3, stage)
                if blocker:
                    self.status[(iso3, stage)] = f"skipped: {blocker}"
                    skipped.append(stage)
                    continue
                say(f"{iso3} {stage}: starting")
                try:
                    func(iso3)
                except Exception as exc:  # noqa: BLE001
                    message = self.client.redact(f"{type(exc).__name__}: {exc}")
                    self.status[(iso3, stage)] = f"failed: {message}"
                    failures.append(f"{stage}: {message}")
                else:
                    self.status[(iso3, stage)] = "ok"
                say(f"{iso3} {stage}: {self.status[(iso3, stage)]}")
            if failures:
                self.fail(f"{iso3}: " + " | ".join(failures))
            if skipped and len(skipped) == len(stages):
                self.skipTest(f"{iso3}: prerequisites not met")

    def _run_local(self, dlg_cls, script_name, configure):
        run = self.driver.run(dlg_cls, script_name, configure)
        if run.errors:
            raise RuntimeError("; ".join(run.errors))
        if len(run.local) != 1:
            raise RuntimeError(
                f"expected 1 local job, got {len(run.local)}"
                + (f" (warnings: {run.warnings})" if run.warnings else "")
            )
        return self.tracker.wait(run.local[0].id, self.config.local_timeout_min)

    def _check_remote_outputs(self, iso3, chain):
        for key, job in self.remote_jobs[(iso3, chain)].items():
            path = job_output_path(job)
            if path is None or not path.exists():
                raise AssertionError(f"{key} results file missing: {path}")
            bands = job_band_names(job)
            if not bands:
                raise AssertionError(f"{key} results have no bands")
            say(f"{iso3} {chain} {key} bands: {bands}")

    def _make_package(self, iso3, name, sdg_summary=None, drought_summary=None):
        from LDMP.calculate_unccd import DlgCalculateUNCCDReport

        set_country_aoi(iso3)

        def configure(dlg):
            dlg.combo_boxes.populate()
            dlg.groupbox_so1_so2.setChecked(sdg_summary is not None)
            dlg.groupbox_so3.setChecked(drought_summary is not None)
            dlg.error_recode_gb.setChecked(False)
            dlg.checkBox_affected_areas_only.setChecked(False)
            if sdg_summary is not None:
                select_dataset_by_job_id(dlg.combo_dataset_so1_so2, sdg_summary.id)
            if drought_summary is not None:
                select_dataset_by_job_id(dlg.combo_dataset_so3, drought_summary.id)
            dlg.execution_name_le.setText(self._task_name(iso3, f"{name}-package"))
            dlg.task_notes.setPlainText(TASK_NOTES)

        job = self._run_local(DlgCalculateUNCCDReport, "unccd-report", configure)
        package = job_output_path(job)
        found = validate_package(
            package,
            expect_so1_so2=sdg_summary is not None,
            expect_so3=drought_summary is not None,
        )
        dest = self._artifact_dir(iso3, name, "package")
        copy_job_artifacts(job, dest, include_outputs=False)
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / f"{iso3}_{name}_unccd_package.tar.gz"
        target.write_bytes(package.read_bytes())
        self.packages[(iso3, name)] = str(target)
        say(f"{iso3} {name} package: {target.name} {json.dumps(found)}")

    def _check_summary(self, iso3, chain, check):
        """Sanity check a summary JSON before it is packaged."""
        path = find_summary_json(self.summary_jobs[(iso3, chain)])
        data = json.loads(path.read_text())
        report = check(
            data,
            aoi_area_km2=country_aoi_area_km2(iso3),
            thresholds=Thresholds.from_env(),
        )
        self.checks[(iso3, chain)] = report.as_dict()
        dest = self._artifact_dir(iso3, chain, "checks")
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "checks.json").write_text(json.dumps(report.as_dict(), indent=2))
        for warning in report.warnings:
            say(f"{iso3} {chain} check warning: {warning}")
        say(
            f"{iso3} {chain} checks: {len(report.errors)} error(s), "
            f"{len(report.warnings)} warning(s); "
            f"area {report.metrics.get('total_area_km2') or 0:,.0f} sq km "
            f"(AOI {report.metrics.get('aoi_area_km2') or 0:,.0f} sq km)"
        )
        if report.errors:
            raise AssertionError(
                f"{len(report.errors)} summary check(s) failed: "
                + "; ".join(report.errors)
            )

    # ------------------------------------------------------------------
    # SDG 15.3.1 chain
    # ------------------------------------------------------------------

    def _sdg_summary(self, iso3):
        from LDMP.calculate_ldn import DlgCalculateLDNSummaryTableAdmin
        from LDMP.data_io import invalidate_usable_data_caches

        self._check_remote_outputs(iso3, "sdg")
        jobs = self.remote_jobs[(iso3, "sdg")]
        report_keys = [k for k in jobs if k != "baseline"]
        set_country_aoi(iso3)

        def configure(dlg):
            invalidate_usable_data_caches()
            dlg.checkBox_progress_period.setChecked(bool(report_keys))
            process_events_for(0.2)
            dlg.populate_combos()
            while len([k for k in dlg.combo_boxes if k != "baseline"]) < len(
                report_keys
            ):
                dlg.pushButton_progress_period.click()
                process_events_for(0.2)
            by_sex = {"baseline": True, "progress": True}
            for key, job in jobs.items():
                widgets = dlg.combo_boxes[key]
                widgets.radio_lpd_te.setChecked(True)
                select_dataset_by_job_id(widgets.combo_datasets, job.id)
                widgets.set_combo_selections_from_job_id(job.id)
                required = [
                    ("trajectory", widgets.combo_layer_traj),
                    ("performance", widgets.combo_layer_perf),
                    ("state", widgets.combo_layer_state),
                    ("land cover", widgets.combo_layer_lc),
                    ("soil organic carbon", widgets.combo_layer_soc),
                ]
                for label, combo in required:
                    if not layer_matches_job(combo, job.id):
                        raise LookupError(f"{key}: no {label} layer from job {job.id}")
                group = "baseline" if key == "baseline" else "progress"
                if not (
                    layer_matches_job(widgets.combo_layer_pop_male, job.id)
                    and layer_matches_job(widgets.combo_layer_pop_female, job.id)
                ):
                    by_sex[group] = False
                    if not layer_matches_job(widgets.combo_layer_pop_total, job.id):
                        raise LookupError(
                            f"{key}: no population layer from job {job.id}"
                        )
            dlg.radio_population_baseline_bysex.setChecked(by_sex["baseline"])
            dlg.radio_population_baseline_total.setChecked(not by_sex["baseline"])
            dlg.radio_population_progress_bysex.setChecked(by_sex["progress"])
            dlg.radio_population_progress_total.setChecked(not by_sex["progress"])
            dlg.execution_name_le.setText(self._task_name(iso3, "sdg-summary"))
            dlg.task_notes.setPlainText(TASK_NOTES)

        job = self._run_local(
            DlgCalculateLDNSummaryTableAdmin, "sdg-15-3-1-summary", configure
        )
        find_summary_json(job)
        self.summary_jobs[(iso3, "sdg")] = job
        copy_job_artifacts(job, self._artifact_dir(iso3, "sdg", "summary"))

    def _sdg_checks(self, iso3):
        self._check_summary(iso3, "sdg", check_sdg_summary)

    def _sdg_package(self, iso3):
        self._make_package(iso3, "sdg", sdg_summary=self.summary_jobs[(iso3, "sdg")])

    def test_1_sdg_15_3_1_pipeline(self):
        for iso3 in self.config.countries:
            self._run_chain(
                iso3,
                (
                    ("sdg_remote", None),
                    ("sdg_summary", self._sdg_summary),
                    ("sdg_checks", self._sdg_checks),
                    ("sdg_package", self._sdg_package),
                ),
            )

    # ------------------------------------------------------------------
    # Drought chain
    # ------------------------------------------------------------------

    def _drought_summary(self, iso3):
        from LDMP.calculate_drought_vulnerability import DlgCalculateDroughtSummary

        self._check_remote_outputs(iso3, "drought")
        drought_job = self.remote_jobs[(iso3, "drought")]["drought"]
        set_country_aoi(iso3)

        def configure(dlg):
            dlg.combo_boxes.populate()
            select_dataset_by_job_id(dlg.combo_dataset_drought, drought_job.id)
            if not dlg.combo_layer_so3_vulnerability.set_index_from_job_id(
                drought_job.id
            ):
                raise LookupError(f"no vulnerability layer from job {drought_job.id}")
            dlg.execution_name_le.setText(self._task_name(iso3, "drought-summary"))
            dlg.task_notes.setPlainText(TASK_NOTES)

        job = self._run_local(
            DlgCalculateDroughtSummary, "drought-vulnerability-summary", configure
        )
        find_summary_json(job)
        self.summary_jobs[(iso3, "drought")] = job
        copy_job_artifacts(job, self._artifact_dir(iso3, "drought", "summary"))

    def _drought_checks(self, iso3):
        self._check_summary(iso3, "drought", check_drought_summary)

    def _drought_package(self, iso3):
        self._make_package(
            iso3, "drought", drought_summary=self.summary_jobs[(iso3, "drought")]
        )

    def test_2_drought_pipeline(self):
        for iso3 in self.config.countries:
            self._run_chain(
                iso3,
                (
                    ("drought_remote", None),
                    ("drought_summary", self._drought_summary),
                    ("drought_checks", self._drought_checks),
                    ("drought_package", self._drought_package),
                ),
            )

    # ------------------------------------------------------------------
    # Combined package
    # ------------------------------------------------------------------

    def _combined_package(self, iso3):
        self._make_package(
            iso3,
            "combined",
            sdg_summary=self.summary_jobs[(iso3, "sdg")],
            drought_summary=self.summary_jobs[(iso3, "drought")],
        )

    def test_3_combined_unccd_package(self):
        for iso3 in self.config.countries:
            self._run_chain(iso3, (("combined_package", self._combined_package),))

    def test_4_no_password_login(self):
        self.assertEqual(
            self.client.password_login_calls,
            0,
            "The e2e run must authenticate only with the service credential",
        )
        self.assertGreaterEqual(self.client.token_mints, 1)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    @classmethod
    def _write_summary(cls):
        rows = []
        for iso3 in cls.config.countries:
            row = {"country": iso3}
            for stage in STAGES:
                row[stage] = cls.status.get((iso3, stage), "not run")
            rows.append(row)

        def short(value):
            return value if len(value) <= 60 else value[:57] + "..."

        header = "| country | " + " | ".join(STAGES) + " |"
        divider = "|" + "---|" * (len(STAGES) + 1)
        lines = [header, divider]
        for row in rows:
            cells = [short(row[s]).replace("|", "/") for s in STAGES]
            lines.append(f"| {row['country']} | " + " | ".join(cells) + " |")
        table = "\n".join(lines)
        print("\nE2E remote pipeline summary\n" + table, flush=True)
        try:
            out = cls.config.output_dir
            out.mkdir(parents=True, exist_ok=True)
            (out / "summary.json").write_text(
                json.dumps(
                    {
                        "run": cls.stamp,
                        "results": rows,
                        "packages": {
                            f"{k[0]}/{k[1]}": v for k, v in cls.packages.items()
                        },
                        "checks": {f"{k[0]}/{k[1]}": v for k, v in cls.checks.items()},
                    },
                    indent=2,
                )
            )
            notes = [
                f"- {key[0]} {key[1]}: {warning}"
                for key, report in cls.checks.items()
                for warning in report["warnings"]
            ]
            warnings_md = (
                "\n### Summary check warnings\n\n" + "\n".join(notes) + "\n"
                if notes
                else ""
            )
            (out / "summary.md").write_text(
                f"## E2E remote pipelines ({cls.stamp})\n\n{table}\n{warnings_md}"
            )
        except OSError as exc:
            say(f"could not write summary: {exc}")
