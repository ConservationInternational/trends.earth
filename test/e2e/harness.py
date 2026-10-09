"""Helpers for the opt-in end-to-end tests that drive the real plugin dialogs
against the live Trends.Earth API.

Nothing in this module talks to the network at import time, so it is safe for
the regular test discovery to import it when the e2e tests are skipped.
"""

import contextlib
import dataclasses
import datetime as dt
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
import traceback
import uuid
from pathlib import Path
from unittest import mock

from qgis.core import (
    QgsApplication,
    QgsAuthMethodConfig,
    QgsCoordinateReferenceSystem,
    QgsDistanceArea,
    QgsGeometry,
    QgsProject,
)
from qgis.PyQt import QtCore, QtWidgets
from te_schemas.jobs import JobStatus

from LDMP import api, auth, conf, data_io, download
from LDMP.jobs.cache import JobCache
from LDMP.jobs.manager import job_manager

DEFAULT_COUNTRIES = "FJI,STP,GUY"
AUTH_PLACEHOLDER_PASSWORD_BYTES = 32
QGIS_AUTH_MASTER_PASSWORD = "password"

# Remote job states after which polling stops.
REMOTE_TERMINAL_STATUSES = {
    JobStatus.FINISHED,
    JobStatus.DOWNLOADED,
    JobStatus.GENERATED_LOCALLY,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
    JobStatus.EXPIRED,
    JobStatus.DELETED,
}
REMOTE_SUCCESS_STATUSES = {
    JobStatus.FINISHED,
    JobStatus.DOWNLOADED,
    JobStatus.GENERATED_LOCALLY,
}

# Settings touched by the e2e tests; saved before and restored afterwards.
TOUCHED_SETTINGS = (
    conf.Setting.BASE_DIR,
    conf.Setting.AREA_FROM_OPTION,
    conf.Setting.COUNTRY_ID,
    conf.Setting.COUNTRY_NAME,
    conf.Setting.REGION_ID,
    conf.Setting.REGION_NAME,
    conf.Setting.AREA_NAME,
    conf.Setting.BUFFER_CHECKED,
    conf.Setting.CUSTOM_CRS_ENABLED,
    conf.Setting.OFFLINE_MODE,
    conf.Setting.CUSTOM_API_URL,
    conf.Setting.DOWNLOAD_RESULTS,
    conf.Setting.POLL_REMOTE,
    conf.Setting.FILTER_JOBS_BY_BASE_DIR,
    conf.Setting.USER_ID,
)

# Large intermediate files are not copied to the artifacts directory.
ARTIFACT_SKIP_SUFFIXES = {".tif", ".tiff", ".vrt"}
ARTIFACT_MAX_BYTES = 50 * 1024 * 1024


def _env_int(name, default):
    value = os.environ.get(name, "").strip()
    try:
        return int(value) if value else default
    except ValueError:
        return default


@dataclasses.dataclass
class E2EConfig:
    client_id: str
    client_secret: str
    api_url: str
    countries: list
    timeout_min: int
    poll_sec: int
    local_timeout_min: int
    output_dir: Path

    @classmethod
    def from_env(cls):
        countries_raw = os.environ.get("TE_E2E_COUNTRIES", "") or DEFAULT_COUNTRIES
        countries = []
        for code in countries_raw.split(","):
            code = code.strip().upper()
            if code and code not in countries:
                countries.append(code)
        output_dir = os.environ.get("TE_E2E_OUTPUT_DIR", "").strip() or str(
            Path(tempfile.gettempdir()) / "te_e2e_artifacts"
        )
        return cls(
            client_id=os.environ.get("TE_E2E_CLIENT_ID", "").strip(),
            client_secret=os.environ.get("TE_E2E_CLIENT_SECRET", "").strip(),
            api_url=(os.environ.get("TE_E2E_API_URL", "").strip().rstrip("/")),
            countries=countries,
            timeout_min=_env_int("TE_E2E_TIMEOUT_MIN", 240),
            poll_sec=max(_env_int("TE_E2E_POLL_SEC", 60), 5),
            local_timeout_min=_env_int("TE_E2E_LOCAL_TIMEOUT_MIN", 60),
            output_dir=Path(output_dir),
        )


def e2e_enabled():
    return bool(
        os.environ.get("TE_E2E_ENABLE", "") == "1"
        and os.environ.get("TE_E2E_CLIENT_ID", "").strip()
        and os.environ.get("TE_E2E_CLIENT_SECRET", "").strip()
    )


E2E_SKIP_REASON = (
    "End-to-end tests run only via test_suite.test_e2e with TE_E2E_CLIENT_ID "
    "and TE_E2E_CLIENT_SECRET set"
)


def say(message):
    """Print a progress line to the test output (never include secrets)."""
    stamp = dt.datetime.now(dt.UTC).strftime("%H:%M:%S")
    print(f"[e2e {stamp}] {message}", flush=True)


def utc_stamp():
    return dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M")


def process_events_for(seconds=0.0):
    deadline = time.monotonic() + seconds
    while True:
        QgsApplication.processEvents()
        if time.monotonic() >= deadline:
            break
        time.sleep(0.05)


def get_iface():
    import qgis.utils

    if qgis.utils.iface is not None:
        return qgis.utils.iface
    from test.utilities_for_testing import get_qgis_app

    return get_qgis_app()[2]


class MainDockStub(QtWidgets.QWidget):
    """Minimal stand-in for the plugin dock that dialogs expect as parent."""

    cache_refresh_about_to_begin = QtCore.pyqtSignal()
    cache_refresh_finished = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.refreshing_filesystem_cache = False


# ---------------------------------------------------------------------------
# Plugin state isolation
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def isolated_plugin_state():
    """Point the plugin at a fresh base directory and restore settings after."""
    saved = {}
    for setting in TOUCHED_SETTINGS:
        try:
            saved[setting] = conf.settings_manager.get_value(setting)
        except Exception:  # noqa: BLE001 - unset settings are restored as-is
            saved[setting] = None
    old_cache = job_manager._job_cache
    base_dir = Path(tempfile.mkdtemp(prefix="te_e2e_base_"))
    try:
        conf.settings_manager.write_value(conf.Setting.BASE_DIR, str(base_dir))
        conf.settings_manager.write_value(conf.Setting.OFFLINE_MODE, False)
        conf.settings_manager.write_value(conf.Setting.DOWNLOAD_RESULTS, False)
        conf.settings_manager.write_value(conf.Setting.POLL_REMOTE, False)
        conf.settings_manager.write_value(conf.Setting.FILTER_JOBS_BY_BASE_DIR, True)
        conf.settings_manager.write_value(conf.Setting.CUSTOM_CRS_ENABLED, False)
        conf.settings_manager.write_value(conf.Setting.USER_ID, "")
        job_manager._job_cache = JobCache(base_dir=base_dir)
        job_manager.clear_known_jobs()
        data_io.invalidate_usable_data_caches()
        yield base_dir
    finally:
        job_manager.clear_known_jobs()
        job_manager._job_cache = old_cache
        for setting, value in saved.items():
            try:
                conf.settings_manager.write_value(setting, value)
            except Exception as exc:  # noqa: BLE001
                say(f"could not restore setting {setting.name}: {exc}")
        data_io.invalidate_usable_data_caches()
        if os.environ.get("TE_E2E_KEEP_BASE_DIR", "") != "1":
            shutil.rmtree(base_dir, ignore_errors=True)


@contextlib.contextmanager
def auth_placeholder(client_id):
    """Create a throwaway QGIS auth config so the dialogs' login check passes.

    The dialogs refuse to submit remote jobs unless a "Basic" auth config is
    registered for Trends.Earth. The config created here holds a random
    password that is never sent anywhere: the service-credential client mints
    its own tokens and the test asserts that no password login happens.
    """
    import secrets

    auth_manager = QgsApplication.authManager()
    if (
        not auth_manager.masterPasswordHashInDatabase()
        or not auth_manager.masterPasswordIsSet()
    ):
        auth_manager.setMasterPassword(QGIS_AUTH_MASTER_PASSWORD, True)

    settings = QtCore.QSettings()
    settings_key = f"trends_earth/{auth.TE_API_AUTH_SETUP.key}"
    previous_auth_id = settings.value(settings_key, None)

    cfg = QgsAuthMethodConfig()
    cfg.setName(auth.TE_API_AUTH_SETUP.name)
    cfg.setMethod("Basic")
    cfg.setConfig("username", f"service-client:{client_id}")
    cfg.setConfig("password", secrets.token_hex(AUTH_PLACEHOLDER_PASSWORD_BYTES))
    result = auth_manager.storeAuthenticationConfig(cfg)
    if isinstance(result, tuple):
        ok, cfg = result[0], result[-1]
    else:
        ok = result
    if not ok or not cfg.id():
        raise RuntimeError("Unable to store placeholder QGIS auth config")
    settings.setValue(settings_key, cfg.id())
    try:
        if not auth.get_auth_config(auth.TE_API_AUTH_SETUP, warn=False):
            raise RuntimeError("Placeholder auth config was not accepted by the plugin")
        yield cfg.id()
    finally:
        auth_manager.removeAuthenticationConfig(cfg.id())
        if previous_auth_id is None:
            settings.remove(settings_key)
        else:
            settings.setValue(settings_key, previous_auth_id)


@contextlib.contextmanager
def installed_api_client(client):
    """Route every plugin API call through ``client``."""
    old_client = job_manager._api_client
    old_testing = job_manager._api_client_testing
    old_url = job_manager._current_api_url
    job_manager.api_client = client
    try:
        with mock.patch.object(api, "get_default_api_client", return_value=client):
            yield client
    finally:
        job_manager._api_client = old_client
        job_manager._api_client_testing = old_testing
        job_manager._current_api_url = old_url


def set_country_aoi(iso3):
    """Select a whole country (ADM0) as the area of interest."""
    bounds = download.get_admin_bounds()
    if not bounds:
        raise RuntimeError("Admin boundary list is unavailable")
    country_name = next(
        (name for name, country in bounds.items() if country.code == iso3), None
    )
    if country_name is None:
        raise ValueError(f"Country {iso3!r} not found in the admin boundary list")
    sm = conf.settings_manager
    sm.write_value(conf.Setting.AREA_FROM_OPTION, conf.AreaSetting.COUNTRY_REGION.value)
    sm.write_value(conf.Setting.COUNTRY_ID, iso3)
    sm.write_value(conf.Setting.COUNTRY_NAME, country_name)
    sm.write_value(conf.Setting.REGION_ID, "")
    sm.write_value(conf.Setting.REGION_NAME, "")
    sm.write_value(conf.Setting.AREA_NAME, country_name)
    sm.write_value(conf.Setting.BUFFER_CHECKED, False)
    data_io.invalidate_usable_data_caches()
    return country_name


def country_aoi_area_km2(iso3):
    """Return the ellipsoidal polygon area (sq km) of the country AOI.

    ``AOI.get_area`` measures bounding boxes (it is used for size limits), so
    it overstates the area of sparse or antimeridian-crossing AOIs such as
    Fiji. Measure the polygons themselves instead, split at the antimeridian
    into east and west pieces so no piece wraps around the globe.
    """
    from LDMP.areaofinterest import prepare_area_of_interest

    set_country_aoi(iso3)
    aoi = prepare_area_of_interest(show_errors=False)
    if aoi is None:
        raise RuntimeError(f"Could not prepare the area of interest for {iso3}")
    pieces = aoi.meridian_split(out_type="layer", out_format="wkt", warn=False)[1]
    calc = QgsDistanceArea()
    calc.setSourceCrs(
        QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsProject.instance().transformContext(),
    )
    calc.setEllipsoid("WGS84")
    area = sum(calc.measureArea(QgsGeometry.fromWkt(wkt)) for wkt in pieces or [])
    if not area:
        raise RuntimeError(f"Could not compute the area of interest for {iso3}")
    return area / 1e6


# ---------------------------------------------------------------------------
# Dialog driving
# ---------------------------------------------------------------------------


class ModalGuard:
    """Replace blocking Qt modals with recorders for unattended runs."""

    def __init__(self):
        self.messages = []
        self.exceptions = []
        self._stack = None

    def _recorder(self, kind, answer):
        def record(*args, **kwargs):
            title = args[1] if len(args) > 1 else kwargs.get("title", "")
            text = args[2] if len(args) > 2 else kwargs.get("text", "")
            self.messages.append((kind, str(title), str(text)))
            say(f"dialog {kind}: {title}: {text}")
            return answer

        return record

    def _file_dialog(self, name):
        def record(*args, **kwargs):
            self.messages.append(("critical", "file dialog", f"{name} was opened"))
            if name == "getExistingDirectory":
                return ""
            return ([], "") if name == "getOpenFileNames" else ("", "")

        return record

    def _excepthook(self, exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        self.exceptions.append(text)
        say(f"unhandled exception in Qt slot:\n{text}")

    def __enter__(self):
        box = QtWidgets.QMessageBox
        self._stack = contextlib.ExitStack()
        patches = {
            "critical": self._recorder("critical", box.Ok),
            "warning": self._recorder("warning", box.Ok),
            "information": self._recorder("information", box.Ok),
            "question": self._recorder("question", box.Yes),
        }
        for name, replacement in patches.items():
            self._stack.enter_context(mock.patch.object(box, name, replacement))
        for name in (
            "getOpenFileName",
            "getOpenFileNames",
            "getSaveFileName",
            "getExistingDirectory",
        ):
            self._stack.enter_context(
                mock.patch.object(QtWidgets.QFileDialog, name, self._file_dialog(name))
            )
        self._stack.enter_context(
            mock.patch.object(sys, "excepthook", self._excepthook)
        )
        return self

    def __exit__(self, *exc_info):
        self._stack.close()
        return False

    @property
    def errors(self):
        errors = [
            f"{title}: {text}"
            for kind, title, text in self.messages
            if kind == "critical"
        ]
        errors += self.exceptions
        return errors


@dataclasses.dataclass
class RemoteSubmission:
    params: dict
    job: object  # Job | None
    failure: str | None = None  # why ``job`` is None


# HTTP statuses after which a run submission is retried. ``None`` means no
# response (timeout or connection error).
RETRYABLE_SUBMIT_STATUSES = {None, 429, 500, 502, 503, 504}
MAX_SUBMIT_RETRY_WAIT_SEC = 900


def _last_api_response():
    client = job_manager.api_client
    record = getattr(client, "last_response", None)
    describe = getattr(client, "describe_last_response", None)
    return record, (describe() if describe else "no API response recorded")


def _as_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value


def find_submitted_execution(task_name, script_id, since):
    """Return the server-side execution for ``task_name`` created after ``since``.

    Used when a run request appears to fail on the client (timeout, dropped
    connection, unparseable response) although the server may have accepted it.
    """
    from LDMP.jobs.manager import _get_job_schema, get_remote_jobs

    if not task_name:
        return None
    remote_jobs = get_remote_jobs() or []
    window_start = since - dt.timedelta(minutes=2)
    for candidate in remote_jobs:
        script = getattr(candidate, "script", None)
        if script is not None and str(script.id) != str(script_id):
            continue
        started = _as_utc(candidate.start_date)
        if started is not None and started < window_start:
            continue
        resp = job_manager.api_client.call_api(
            f"/api/v1/execution/{candidate.id}", method="get", use_token=True
        )
        raw = resp.get("data") if isinstance(resp, dict) else None
        if not raw or (raw.get("params") or {}).get("task_name") != task_name:
            continue
        return _get_job_schema().load(raw)
    return None


def submit_with_recovery(submit, params, script_id):
    """Submit a remote job, distinguishing real rejections from client failures.

    Returns ``(job, failure)``. When the plugin reports no job, check whether the
    server created the execution anyway, and retry rate-limited or transient
    failures. Queued (PENDING) executions are successful submissions.
    """
    attempts = max(1, int(os.environ.get("TE_E2E_SUBMIT_ATTEMPTS") or "4"))
    task_name = params.get("task_name")
    failure = None
    for attempt in range(1, attempts + 1):
        since = dt.datetime.now(dt.UTC)
        job = submit(params, script_id)
        if job is not None:
            return job, None
        record, failure = _last_api_response()
        status = record.get("status") if record else None
        say(f"submission of {task_name!r} failed (attempt {attempt}): {failure}")
        try:
            job = find_submitted_execution(task_name, script_id, since)
        except Exception as exc:  # noqa: BLE001 - lookup is best effort
            say(f"could not look up {task_name!r} on the server: {exc}")
            job = None
        if job is not None:
            say(f"{task_name!r} was accepted by the server as {job.id}")
            with contextlib.suppress(Exception):
                job_manager.write_job_metadata_file(job)
                job_manager._update_known_jobs_with_newly_submitted_job(job)
            return job, None
        if status not in RETRYABLE_SUBMIT_STATUSES or attempt == attempts:
            break
        retry_after = (record or {}).get("retry_after") or 30 * attempt
        if retry_after > MAX_SUBMIT_RETRY_WAIT_SEC:
            failure += f" (Retry-After {retry_after:.0f}s exceeds the retry limit)"
            break
        say(f"retrying {task_name!r} in {retry_after:.0f}s")
        process_events_for(retry_after)
    return None, failure


@dataclasses.dataclass
class DialogRun:
    remote: list  # [RemoteSubmission]
    local: list  # [Job]
    messages: list
    errors: list

    @property
    def warnings(self):
        return [f"{t}: {x}" for kind, t, x in self.messages if kind == "warning"]


class DialogDriver:
    """Open a plugin dialog, configure it, click OK, and capture submissions."""

    def __init__(self, iface):
        self.iface = iface
        self.main_dock = MainDockStub()

    def run(self, dlg_cls, script_name, configure):
        remote = []
        local = []

        original_submit_remote = job_manager.submit_remote_job

        def submit_remote_spy(params, script_id):
            job, failure = submit_with_recovery(
                original_submit_remote, params, script_id
            )
            remote.append(RemoteSubmission(params, job, failure))
            return job

        def on_local(job):
            if all(j.id != job.id for j in local):
                local.append(job)

        with (
            ModalGuard() as guard,
            mock.patch.object(job_manager, "submit_remote_job", submit_remote_spy),
        ):
            job_manager.submitted_local_job.connect(on_local)
            dlg = None
            try:
                dlg = dlg_cls(
                    self.iface, conf.KNOWN_SCRIPTS[script_name], self.main_dock
                )
                dlg.show()
                process_events_for(1.0)
                configure(dlg)
                process_events_for(0.5)
                ok_button = dlg.button_box.button(QtWidgets.QDialogButtonBox.Ok)
                if not ok_button.isEnabled():
                    raise RuntimeError(f"OK button of {dlg_cls.__name__} is disabled")
                ok_button.click()
                process_events_for(1.0)
            finally:
                job_manager.submitted_local_job.disconnect(on_local)
                if dlg is not None:
                    dlg.close()
                    dlg.deleteLater()
                    process_events_for(0.2)
        return DialogRun(
            remote=remote, local=local, messages=guard.messages, errors=guard.errors
        )


def select_dataset_by_job_id(combo, job_id):
    """Select the dataset produced by ``job_id`` in a dataset combo box."""

    def find():
        for i, dataset in enumerate(combo.dataset_list or []):
            if dataset.job.id == job_id:
                return i
        return None

    index = find()
    if index is None:
        data_io.invalidate_usable_data_caches()
        combo.populate()
        index = find()
    if index is None:
        available = [
            f"{d.job.task_name} ({d.job.id})" for d in (combo.dataset_list or [])
        ]
        raise LookupError(
            f"Job {job_id} is not offered by {combo.objectName()}; available: {available}"
        )
    combo.comboBox_datasets.setCurrentIndex(index)
    combo.selected_job_changed()
    current = combo.get_current_job()
    if current is None or current.id != job_id:
        raise LookupError(f"Could not select job {job_id} in {combo.objectName()}")


def layer_matches_job(layer_combo, job_id):
    if not layer_combo.has_valid_selection():
        return False
    band = layer_combo.get_current_band()
    return band is not None and band.job.id == job_id


# ---------------------------------------------------------------------------
# Job tracking
# ---------------------------------------------------------------------------


def find_job(job_id):
    for status, jobs in job_manager.known_jobs.items():
        job = jobs.get(job_id)
        if job is not None:
            return status, job
    return None, None


class LocalJobTracker(QtCore.QObject):
    """Record completion of locally executed jobs."""

    def __init__(self):
        super().__init__()
        self.results = {}
        job_manager.processed_local_job.connect(self._on_done)
        job_manager.failed_local_job.connect(self._on_failed)

    def _on_done(self, job):
        self.results[job.id] = ("ok", job)

    def _on_failed(self, job):
        self.results[job.id] = ("failed", job)

    def disconnect_all(self):
        for signal, slot in (
            (job_manager.processed_local_job, self._on_done),
            (job_manager.failed_local_job, self._on_failed),
        ):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass

    def wait(self, job_id, timeout_min):
        deadline = time.monotonic() + timeout_min * 60
        while job_id not in self.results:
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Local job {job_id} did not finish within {timeout_min} min"
                )
            process_events_for(1.0)
        outcome, job = self.results[job_id]
        if outcome != "ok":
            raise RuntimeError(
                f"Local job {job_id} failed. Log excerpt:\n{local_log_excerpt(job)}"
            )
        _, refreshed = find_job(job_id)
        return refreshed or job


def local_log_excerpt(job, lines=40):
    try:
        from LDMP.jobs.local_logger import read_local_job_logs

        entries = read_local_job_logs(job) or []
        return "\n".join(str(e) for e in entries[-lines:])
    except Exception as exc:  # noqa: BLE001
        return f"(local job log unavailable: {exc})"


def describe_remote_outcome(status, timeout_min):
    """Describe a remote job that did not finish successfully."""
    if status is None:
        return f"was not seen on the server within {timeout_min} min"
    if status in REMOTE_TERMINAL_STATUSES:
        return f"ended as {status.value.lower()}"
    return (
        f"was still {status.value.lower()} after {timeout_min} min "
        "(in progress or queued, not failed; raise TE_E2E_TIMEOUT_MIN)"
    )


def wait_for_remote(job_ids, timeout_min, poll_sec):
    """Poll the API until all ``job_ids`` reach a terminal state.

    Returns ``{job_id: JobStatus | None}`` with the last status seen (``None``
    if the job was never seen). PENDING (including jobs queued by the API's
    per-user concurrency limit), READY, RUNNING and CANCELLING are in progress,
    so a job still in one of those states at the timeout keeps that status
    rather than being reported as failed.
    """
    pending = set(job_ids)
    final = {job_id: None for job_id in job_ids}
    deadline = time.monotonic() + timeout_min * 60
    started = time.monotonic()
    while pending:
        try:
            job_manager.refresh_from_remote_state(emit_signal=True)
        except Exception as exc:  # noqa: BLE001 - transient API errors are retried
            say(f"remote refresh error (will retry): {type(exc).__name__}: {exc}")
        process_events_for(0.5)
        counts = {}
        for job_id in list(pending):
            status, _ = find_job(job_id)
            final[job_id] = status
            label = status.value.lower() if status else "unknown"
            counts[label] = counts.get(label, 0) + 1
            if status in REMOTE_TERMINAL_STATUSES:
                pending.discard(job_id)
        elapsed = (time.monotonic() - started) / 60
        say(f"remote jobs after {elapsed:.0f} min: {counts or 'all done'}")
        if not pending:
            break
        if time.monotonic() > deadline:
            say(f"timed out waiting for {len(pending)} remote job(s)")
            break
        process_events_for(poll_sec)
    return final


def download_jobs(job_ids, timeout_min):
    """Download the results of finished remote jobs.

    Returns ``{job_id: None | error message}``.
    """
    errors = {}
    for job_id in job_ids:
        status, job = find_job(job_id)
        if status == JobStatus.FINISHED:
            job_manager.start_downloading_job(job)
        elif status not in (JobStatus.DOWNLOADED, JobStatus.GENERATED_LOCALLY):
            errors[job_id] = f"cannot download job in status {status}"
    remaining = [j for j in job_ids if j not in errors]
    deadline = time.monotonic() + timeout_min * 60
    while remaining:
        process_events_for(2.0)
        still = []
        for job_id in remaining:
            status, job = find_job(job_id)
            if status in (JobStatus.DOWNLOADED, JobStatus.GENERATED_LOCALLY):
                continue
            if job_id in job_manager._failed_download_job_ids:
                errors[job_id] = "download failed"
                continue
            if (
                status == JobStatus.FINISHED
                and not job_manager._download_in_progress
                and job_id not in job_manager._user_download_queue
            ):
                job_manager.start_downloading_job(job)
            still.append(job_id)
        remaining = still
        if remaining and time.monotonic() > deadline:
            for job_id in remaining:
                errors[job_id] = f"download did not finish within {timeout_min} min"
            break
    data_io.invalidate_usable_data_caches()
    return {job_id: errors.get(job_id) for job_id in job_ids}


# ---------------------------------------------------------------------------
# Outputs and artifacts
# ---------------------------------------------------------------------------


def job_output_path(job):
    results = getattr(job, "results", None)
    uri = getattr(results, "uri", None)
    path = getattr(uri, "uri", None)
    return Path(path) if path else None


def job_output_dir(job):
    path = job_output_path(job)
    return path.parent if path else None


def find_summary_json(job):
    out_dir = job_output_dir(job)
    if out_dir is None or not out_dir.is_dir():
        raise AssertionError(f"Job {job.id} has no output directory")
    matches = sorted(out_dir.glob("*_summary.json"))
    if not matches:
        raise AssertionError(f"No *_summary.json in {out_dir}")
    return matches[0]


def job_band_names(job):
    results = getattr(job, "results", None)
    get_bands = getattr(results, "get_bands", None)
    if get_bands is None:
        return []
    try:
        return [getattr(b, "name", str(b)) for b in get_bands()]
    except Exception:  # noqa: BLE001
        return []


def write_job_json(job, dest_dir):
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        src = job_manager.get_job_file_path(job)
    except Exception:  # noqa: BLE001
        src = None
    if src is not None and Path(src).exists():
        shutil.copy2(src, dest_dir / "job.json")
    else:
        (dest_dir / "job.json").write_text(
            json.dumps({"id": str(job.id), "task_name": job.task_name}, indent=2)
        )


def copy_outputs(paths, dest_dir):
    dest_dir.mkdir(parents=True, exist_ok=True)
    for path in paths:
        path = Path(path)
        if not path.is_file() or path.suffix.lower() in ARTIFACT_SKIP_SUFFIXES:
            continue
        if path.stat().st_size > ARTIFACT_MAX_BYTES:
            continue
        shutil.copy2(path, dest_dir / path.name)


def copy_job_artifacts(job, dest_dir, include_outputs=True):
    write_job_json(job, dest_dir)
    if include_outputs:
        out_dir = job_output_dir(job)
        if out_dir is not None and out_dir.is_dir():
            copy_outputs(sorted(out_dir.iterdir()), dest_dir)


# ---------------------------------------------------------------------------
# Package validation
# ---------------------------------------------------------------------------


def _classify_summary(data):
    if "land_condition" in data:
        return "so1_so2"
    if "drought" in data:
        return "so3"
    return None


def validate_package(tar_path, expect_so1_so2, expect_so3):
    """Check a UNCCD/PRAIS package and return the summary kinds it contains."""
    from te_schemas import reporting

    tar_path = Path(tar_path)
    if not tar_path.is_file():
        raise AssertionError(f"Package {tar_path} does not exist")
    found = {}
    with tarfile.open(tar_path, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile() or not member.name.endswith("_summary.json"):
                continue
            data = json.load(tar.extractfile(member))
            kind = _classify_summary(data)
            if kind is None:
                raise AssertionError(f"{member.name} is not a recognised summary")
            if "metadata" not in data:
                raise AssertionError(f"{member.name} has no metadata section")
            if kind == "so3":
                reporting.TrendsEarthDroughtSummary.Schema().load(data)
            else:
                try:
                    reporting.TrendsEarthLandConditionSummary.Schema().load(data)
                except Exception as exc:
                    # Packages rename progress sections to "report" for PRAIS,
                    # which the schema does not know about; key checks suffice.
                    say(f"{member.name}: schema load skipped ({type(exc).__name__})")
                    if not data.get("land_condition"):
                        raise AssertionError(
                            f"{member.name} has an empty land_condition section"
                        ) from exc
            found.setdefault(kind, []).append(member.name)
    if expect_so1_so2 and "so1_so2" not in found:
        raise AssertionError(f"{tar_path.name} has no SO1/SO2 summary")
    if expect_so3 and "so3" not in found:
        raise AssertionError(f"{tar_path.name} has no SO3 summary")
    if not expect_so1_so2 and "so1_so2" in found:
        raise AssertionError(f"{tar_path.name} unexpectedly has an SO1/SO2 summary")
    if not expect_so3 and "so3" in found:
        raise AssertionError(f"{tar_path.name} unexpectedly has an SO3 summary")
    return found


def as_uuid(value):
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
