import datetime as dt
import json
import logging
import math
import os
import re
import shutil
import sys
import time
import traceback
import typing
import urllib.parse
import uuid
from copy import deepcopy
from pathlib import Path
from typing import List

import backoff
import te_algorithms.gdal.land_deg.config as ld_conf
from marshmallow.exceptions import ValidationError
from osgeo import gdal
from qgis.core import Qgis, QgsApplication, QgsFileDownloader, QgsTask, QgsVectorLayer
from qgis.gui import QgsMessageBar
from qgis.PyQt import QtCore
from qgis.PyQt.QtWidgets import QProgressBar, QPushButton
from qgis.utils import iface
from te_algorithms.gdal.util import (
    combine_all_bands_into_vrt,
    generate_sanitized_band_names,
)
from te_schemas import jobs, results
from te_schemas.algorithms import AlgorithmRunMode, ExecutionScript
from te_schemas.productivity import ProductivityMode
from te_schemas.results import (
    URI,
    DataType,
    Raster,
    RasterFileType,
    RasterResults,
    ResultType,
    VectorFalsePositive,
    VectorResults,
    VectorType,
)
from te_schemas.results import Band as JobBand

from .. import api, areaofinterest, conf, layers, metadata, utils
from .. import download as ldmp_download
from ..constants import TIMEOUT, get_api_url
from ..logger import log
from . import models
from .cache import JobCache
from .local_logger import LocalJobLogHandler, setup_local_job_logger
from .models import Job

logger = logging.getLogger(__name__)

_job_schema = None


def _get_job_schema():
    """Return a cached Job.Schema() singleton.

    Lazily initialised so that the module can be imported before Job is fully
    configured (e.g. during testing or early plugin load).
    """
    global _job_schema
    if _job_schema is None:
        _job_schema = Job.Schema()
    return _job_schema


class tr_manager:
    def tr(message):
        return QtCore.QCoreApplication.translate("tr_manager", message)


def _get_etag(uri: typing.Optional[results.URI]) -> typing.Optional[results.Etag]:
    """Extract the Etag from a URI if available."""
    if uri is None or uri.etag is None:
        return None
    return uri.etag


def _find_error_recode_result(job: Job) -> typing.Optional[VectorResults]:
    """Find the error recode VectorResults from a job's results.

    Returns:
        The VectorResults with ERROR_RECODE type, or None if not found.
    """
    for result in job._get_results_list():
        if isinstance(result, VectorResults):
            if (
                result.vector is not None
                and result.vector.type == VectorType.ERROR_RECODE
            ):
                return result
    return None


def is_gdal_vsi_path(path: Path):
    return re.match(r"(\\)|(/)vsi(s3)|(gs)", str(path)) is not None


def update_uris_if_needed(job: Job, job_path):
    "Update uris stored in a job when downloading/importing if it has absolute paths"
    # First check if the data is in the same folder as the job file and relative to
    # it. If it is, update the various uris so they are  can still be found after
    # moving the job file
    # Handle both single results and list of results
    results_list = job._get_results_list() if job.results else []
    for result in results_list:
        if (
            hasattr(result, "uri")
            and result.uri
            and not is_gdal_vsi_path(result.uri.uri)  # ignore gdal virtual fs
            and (not result.uri.uri.is_absolute() or not result.uri.uri.exists())
        ):
            # If the path doesn't exist, but the filename does exist in the
            # same folder as the job, the below function will assume that is what
            # is meant
            result.update_uris(job_path)


def _get_extent_tuple_raster(path):
    if conf.settings_manager.get_value(conf.Setting.DEBUG):
        log(f"Trying to calculate extent of raster {path}")

    try:
        path_str = str(path)
        # For VSI paths (/vsis3/, /vsicurl/, etc), use GDAL's VSIStatL
        if path_str.startswith("/vsi"):
            stat_info = gdal.VSIStatL(path_str)
            if stat_info is None:
                log(
                    f"Failed to calculate extent - VSI file does not exist or not accessible: {path}"
                )
                return None
        elif not os.path.exists(path_str):
            log(f"Failed to calculate extent - file does not exist: {path}")
            return None

        # Use GDAL error handling to prevent crashes
        ds = None
        try:
            ds = gdal.Open(path_str)
            if ds:
                min_x, xres, _, max_y, _, yres = ds.GetGeoTransform()
                cols = ds.RasterXSize
                rows = ds.RasterYSize

                extent = (min_x, max_y + rows * yres, min_x + cols * xres, max_y)
                if conf.settings_manager.get_value(conf.Setting.DEBUG):
                    log(f"Calculated extent {[*extent]}")
                return extent
            else:
                log("Failed to calculate extent - couldn't open dataset")
                return None
        finally:
            # Ensure GDAL dataset is properly closed to prevent memory leaks
            if ds is not None:
                ds = None
    except (OSError, IOError, RuntimeError, MemoryError) as exc:
        log(f"Failed to calculate extent for {path} - {type(exc).__name__}: {exc}")
        return None
    except Exception as exc:
        log(
            f"Unexpected error calculating extent for {path} - {type(exc).__name__}: {exc}"
        )
        return None


def _get_extent_tuple_vector(path):
    if conf.settings_manager.get_value(conf.Setting.DEBUG):
        log(f"Trying to calculate extent of vector {path}")

    try:
        path_str = str(path)
        # Check if file exists before attempting to load
        # For VSI paths (/vsis3/, /vsicurl/, etc), use GDAL's VSIStatL
        if path_str.startswith("/vsi"):
            from osgeo import gdal

            stat_info = gdal.VSIStatL(path_str)
            if stat_info is None:
                log(
                    f"Failed to calculate extent - VSI file does not exist or not accessible: {path}"
                )
                return None
        elif not os.path.exists(path_str):
            log(f"Failed to calculate extent - file does not exist: {path}")
            return None

        layer = QgsVectorLayer(path_str, "vector file", "ogr")

        # Check if layer is valid before accessing extent
        if not layer.isValid():
            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                log(f"Failed to calculate extent - invalid layer: {path}")
            return None

        rect = layer.extent()

        try:
            is_empty = hasattr(rect, "isEmpty") and rect.isEmpty()
        except Exception:
            is_empty = False

        if (not rect) or is_empty:
            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                log(f"Failed to calculate extent for {path} - extent empty/undefined")
            return None

        xmin = rect.xMinimum()
        xmax = rect.xMaximum()
        ymin = rect.yMinimum()
        ymax = rect.yMaximum()

        vals = [xmin, ymin, xmax, ymax]
        if any(
            (v is None) or (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))
            for v in vals
        ):
            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                log(f"Failed to calculate extent for {path} - NaN/Inf in extent {vals}")
            return None

        if any((val > 180 or val < -180) for val in [xmin, xmax]) or any(
            (val > 90 or val < -90) for val in [ymin, ymax]
        ):
            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                log(
                    f"Failed to calculate extent for {path} - appears undefined/out of bounds "
                    f"({xmin}, {ymin}, {xmax}, {ymax})"
                )
            return None
    except (OSError, IOError, RuntimeError, MemoryError) as exc:
        log(f"Failed to calculate extent for {path} - {type(exc).__name__}: {exc}")
        return None
    except Exception as exc:
        log(
            f"Unexpected error calculating extent for {path} - {type(exc).__name__}: {exc}"
        )
        return None

    if conf.settings_manager.get_value(conf.Setting.DEBUG):
        log(f"Calculated extent for {path} - {(xmin, ymin, xmax, ymax)}")
    return (xmin, ymin, xmax, ymax)


def _set_results_extents_raster(raster_result, job, force=False):
    for raster in raster_result.rasters.values():
        if raster.type == results.RasterType.ONE_FILE_RASTER:
            if force or not hasattr(raster, "extent") or raster.extent is None:
                raster.extent = _get_extent_tuple_raster(raster.uri.uri)
                if conf.settings_manager.get_value(conf.Setting.DEBUG):
                    log(
                        f"{'Force ' if force else ''}set job {job.id} {raster.datatype} {raster.type} "
                        f"extent to {raster.extent}"
                    )
        elif raster.type == results.RasterType.TILED_RASTER:
            if force or not hasattr(raster, "extents") or raster.extents is None:
                raster.extents = []
                for raster_tile_uri in raster.tile_uris:
                    extent = _get_extent_tuple_raster(raster_tile_uri.uri)
                    if extent is None:
                        raise RuntimeError(
                            f"Failed to calculate extent for tile {raster_tile_uri.uri} in job {job.id}. "
                            f"File may be missing, corrupted, or inaccessible."
                        )
                    raster.extents.append(extent)
                if conf.settings_manager.get_value(conf.Setting.DEBUG):
                    log(
                        f"{'Force ' if force else ''}set job {job.id} {raster.datatype} {raster.type} "
                        f"extents to {raster.extents}"
                    )
        else:
            raise RuntimeError(f"Unknown raster type {raster.type!r}")


def _set_results_extents_vector(vector_result, job, force=False):
    if conf.settings_manager.get_value(conf.Setting.DEBUG):
        log(f"{'Force ' if force else ''}Setting extents for job {job.id}")
    if force or not hasattr(vector_result, "extent") or vector_result.extent is None:
        # Use the main uri, or fall back to vector.uri for error recode types
        uri_to_use = vector_result.uri
        if uri_to_use is None and vector_result.vector is not None:
            uri_to_use = vector_result.vector.uri

        if uri_to_use is not None and uri_to_use.uri is not None:
            vector_result.extent = _get_extent_tuple_vector(uri_to_use.uri)
            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                vector_type_str = (
                    vector_result.vector.type.value
                    if vector_result.vector
                    else "unknown"
                )
                log(
                    f"{'Force ' if force else ''}set job {job.id} {vector_result.type} {vector_type_str} "
                    f"extent to {vector_result.extent}"
                )


def set_results_extents(job, force=False):
    """
    Set or recalculate extents for job results.

    Args:
        job: The job whose results extents should be set
        force: If True, recalculate extents even if they already exist.
               Useful for fixing missing or corrupted extent data.
    """
    if not job.results:
        return

    # Handle both single results and list of results
    results_list = job._get_results_list()
    for result in results_list:
        if isinstance(result, RasterResults) and job.status in [
            jobs.JobStatus.DOWNLOADED,
            jobs.JobStatus.GENERATED_LOCALLY,
        ]:
            _set_results_extents_raster(result, job, force=force)
        elif isinstance(result, VectorResults) and job.status in [
            jobs.JobStatus.DOWNLOADED,
            jobs.JobStatus.GENERATED_LOCALLY,
        ]:
            _set_results_extents_vector(result, job, force=force)


def _set_results_extents_if_missing(job) -> bool:
    """Compute extents for DOWNLOADED/GENERATED_LOCALLY jobs only when missing."""
    if not job.results:
        return False

    changed = False
    results_list = job._get_results_list()
    for result in results_list:
        if isinstance(result, RasterResults):
            for raster in result.rasters.values():
                if raster.type == results.RasterType.ONE_FILE_RASTER:
                    if not hasattr(raster, "extent") or raster.extent is None:
                        raster.extent = _get_extent_tuple_raster(raster.uri.uri)
                        changed = True
                elif raster.type == results.RasterType.TILED_RASTER:
                    if not hasattr(raster, "extents") or raster.extents is None:
                        raster.extents = []
                        for raster_tile_uri in raster.tile_uris:
                            extent = _get_extent_tuple_raster(raster_tile_uri.uri)
                            if extent is None:
                                raise RuntimeError(
                                    f"Failed to calculate extent for tile {raster_tile_uri.uri} in job {job.id}. "
                                    f"File may be missing, corrupted, or inaccessible."
                                )
                            raster.extents.append(extent)
                        changed = True
        elif isinstance(result, VectorResults):
            if not hasattr(result, "extent") or result.extent is None:
                uri_to_use = result.uri
                if uri_to_use is None and result.vector is not None:
                    uri_to_use = result.vector.uri
                if uri_to_use is not None and uri_to_use.uri is not None:
                    result.extent = _get_extent_tuple_vector(uri_to_use.uri)
                    changed = True
    return changed


def _set_band_descriptions_on_result(
    raster_results: RasterResults,
) -> None:
    """Write sanitized band names as band descriptions into each output file.

    Ensures locally-computed rasters show human-readable band names in QGIS,
    consistent with the names embedded in GEE-exported COGs.
    """
    for raster in raster_results.rasters.values():
        if not raster.uri or not raster.uri.uri:
            continue
        path = Path(raster.uri.uri)
        if not path.exists():
            continue
        names = generate_sanitized_band_names(raster.bands)
        ds = gdal.Open(str(path), gdal.GA_Update)
        if ds is None:
            logger.warning(
                "Could not open %s for update to set band descriptions", path
            )
            continue
        for i, name in enumerate(names, start=1):
            if i <= ds.RasterCount:
                ds.GetRasterBand(i).SetDescription(name)
        ds.FlushCache()
        ds = None


class LocalJobTask(QgsTask):
    job: Job
    area_of_interest: areaofinterest.AOI

    processed_job = QtCore.pyqtSignal(Job)
    failed_job = QtCore.pyqtSignal(Job)
    running_job = QtCore.pyqtSignal()

    def __init__(self, description, job, area_of_interest):
        super().__init__(description, QgsTask.CanCancel)
        self.job = job
        self.job_copy = deepcopy(job)  # ensure job in main thread is not accessed
        self.area_of_interest = area_of_interest
        self.results = None
        self.error_message = None

    def run(self):
        logger.debug("Running task")
        self.running_job.emit()
        self.job_logger = setup_local_job_logger(self.job_copy)
        script_name = getattr(self.job_copy.script, "name", "unknown")
        self.job_logger.info(f"Starting execution of {script_name}")

        # Attach job log handler to algorithm loggers so their messages
        # appear in the job's log file (not just stderr).
        algo_logger = logging.getLogger("te_algorithms")
        prev_algo_level = algo_logger.level
        algo_logger.setLevel(logging.INFO)
        algo_handler = None
        for h in self.job_logger.handlers:
            if isinstance(h, LocalJobLogHandler):
                algo_handler = h
                break
        if algo_handler is not None:
            algo_logger.addHandler(algo_handler)

        execution_handler = utils.load_object(self.job_copy.script.execution_callable)
        job_output_path, dataset_output_path = _get_local_job_output_paths(
            self.job_copy
        )

        # Wrap setProgress so that progress updates are also written to the
        # job log file.  Throttle to every 5 percentage-points.
        last_logged_progress = -5

        def _set_progress_and_log(value):
            nonlocal last_logged_progress
            self.setProgress(value)
            if value - last_logged_progress >= 5:
                self.job_logger.info(f"Progress: {int(value)}%")
                last_logged_progress = value

        try:
            self.results = execution_handler(
                self.job_copy,
                self.area_of_interest,
                job_output_path,
                dataset_output_path,
                _set_progress_and_log,
                self.isCanceled,
            )
        except Exception:
            logger.exception("Execution handler raised an exception")
            self.job_logger.error(traceback.format_exc())
            self.error_message = traceback.format_exc()
            return False
        finally:
            if algo_handler is not None:
                algo_logger.removeHandler(algo_handler)
            algo_logger.setLevel(prev_algo_level)

        if self.isCanceled():
            logger.debug("Task was cancelled")
            self.job_logger.warning("Execution cancelled by user")
            return False

        if self.results is None:
            logger.debug("Completed run function - failure")
            self.job_logger.error("Execution handler returned no results")
            self.error_message = "Execution handler returned no results"
            return False
        else:
            logger.debug("Completed run function - success")
            self.job_logger.info("Execution completed successfully")
            return True

    def finished(self, result):
        logger.debug("Finished task")
        self.job.end_date = dt.datetime.now(dt.timezone.utc)
        self.job.progress = 100
        if result:
            self.job.results = self.results
            if isinstance(self.results, RasterResults):
                _set_band_descriptions_on_result(self.results)
            self.job._cached_has_loadable_result = None
            self.processed_job.emit(self.job)
            logger.debug("Task succeeded")
        else:
            if self.isCanceled():
                self.job.status = jobs.JobStatus.CANCELLED
            else:
                self.job.status = jobs.JobStatus.FAILED
            self.failed_job.emit(self.job)
            logger.debug(f"Task failed with status {self.job.status.value}")


# Multiple QGIS instances share the same datasets/ directory.  A
# file-based lock prevents two instances from downloading the same job
# simultaneously.

_DOWNLOAD_LOCK_FILENAME = ".downloading.lock"
_DOWNLOAD_LOCK_STALE_SECONDS = 1200  # 20 min (2× the 10 min refresh interval)


def _download_lock_path(job_dir: Path) -> Path:
    return job_dir / _DOWNLOAD_LOCK_FILENAME


def _is_pid_alive(pid: int) -> bool:
    """Return True if a process with *pid* is still running."""
    if sys.platform == "win32":
        import ctypes

        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    # Unix: signal 0 checks existence without actually sending a signal.
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True  # process exists but we lack permission
    except OSError:
        return False
    return True


def _is_download_lock_stale(lock_path: Path) -> bool:
    """Return True if the lock file is stale (dead process or too old)."""
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return True  # corrupt or unreadable → treat as stale

    pid = data.get("pid")
    ts = data.get("ts", 0)

    if pid is not None and not _is_pid_alive(pid):
        return True
    if time.time() - ts > _DOWNLOAD_LOCK_STALE_SECONDS:
        return True
    return False


def _try_acquire_download_lock(job_dir: Path) -> bool:
    """Try to create an exclusive lock file.  Returns True if acquired."""
    lock_path = _download_lock_path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    lock_content = json.dumps({"pid": os.getpid(), "ts": time.time()}).encode()

    for _attempt in range(2):  # one retry after stale-lock cleanup
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, lock_content)
            finally:
                os.close(fd)
            return True
        except FileExistsError:
            if _is_download_lock_stale(lock_path):
                try:
                    lock_path.unlink()
                except OSError:
                    return False
                continue  # retry after removing stale lock
            return False  # another live process owns the lock
    return False


def _refresh_download_lock(job_dir: Path) -> None:
    """Update the timestamp in an existing lock so it doesn't look stale.

    Long-running downloads can easily exceed *_DOWNLOAD_LOCK_STALE_SECONDS*.
    Callers should invoke this periodically (e.g. after each file) to prove
    the owning process is still alive and making progress.
    """
    lock_path = _download_lock_path(job_dir)
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        if data.get("pid") != os.getpid():
            return  # not ours
        data["ts"] = time.time()
        lock_path.write_text(json.dumps(data), encoding="utf-8")
    except (json.JSONDecodeError, OSError):
        pass  # lock disappeared or is corrupt — nothing to refresh


def _release_download_lock(job_dir: Path) -> None:
    """Release the lock, but only if this process owns it."""
    lock_path = _download_lock_path(job_dir)
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        if data.get("pid") != os.getpid():
            return  # not ours — leave it alone
    except (json.JSONDecodeError, OSError):
        pass  # corrupt / missing — clean up anyway
    lock_path.unlink(missing_ok=True)


class DownloadJobResultsTask(QgsTask):
    """Download all results for a single job on a background thread.

    Follows the same pattern as LocalJobTask:
    - run()      -> background thread, does all blocking I/O
    - finished() -> main thread, updates job status and emits signals
    """

    _CANCEL_CHECK_INTERVAL_MS = 500
    _LOCK_REFRESH_INTERVAL_S = 600  # refresh lock file every 10 minutes

    def __init__(self, job: Job, job_manager: "JobManager"):
        task_name = job.task_name or str(job.id)
        super().__init__(f"Downloading results: {task_name}", QgsTask.CanCancel)
        self.job = job
        self.job_manager = job_manager
        self.error_message = None
        self._all_successful = True
        self._job_dir = job_manager.datasets_dir / str(job.id)
        self._last_lock_refresh = time.time()

    def run(self) -> bool:
        """Background thread — download all result files."""
        results_list = self.job._get_results_list()
        if not results_list:
            log(f"Job {self.job.id} has empty results list")
            return False

        total_files = self._count_files(results_list)
        files_done = 0

        for result in results_list:
            if self.isCanceled():
                return False

            if not hasattr(result, "type"):
                continue

            if result.type == ResultType.RASTER_RESULTS:
                success, files_done = self._download_cloud_result(
                    result, files_done, total_files
                )
            elif result.type == ResultType.VECTOR_RESULTS:
                success = self._download_vector_result(result)
                files_done += 1
                self.setProgress(files_done * 100 / max(total_files, 1))
            elif result.type == ResultType.TIME_SERIES_TABLE:
                success = True  # no download needed
            else:
                log(f"No handler for result type {result.type}")
                continue

            if not success:
                self._all_successful = False
                return False

        return True

    def _count_files(self, results_list) -> int:
        """Count total files to download for progress tracking."""
        count = 0
        for result in results_list:
            if not hasattr(result, "type"):
                continue
            if result.type == ResultType.RASTER_RESULTS:
                for raster in result.rasters.values():
                    if raster.type == results.RasterType.TILED_RASTER:
                        count += len(raster.tile_uris)
                    else:
                        count += 1
            elif result.type == ResultType.VECTOR_RESULTS:
                count += 1
        return count

    def _download_single_file(
        self,
        url: str,
        output_path: Path,
        expected_etag=None,
        max_retries: int = 5,
    ) -> bool:
        """Download one file with retries using QgsFileDownloader."""
        import time as _time

        output_path.parent.mkdir(parents=True, exist_ok=True)

        for attempt in range(max_retries):
            if self.isCanceled():
                return False

            try:
                success = self._qgs_download(url, output_path)
            except Exception as e:
                log(
                    f"Download attempt {attempt + 1} failed for {output_path.name}: {e}"
                )
                output_path.unlink(missing_ok=True)
                success = False

            if success and expected_etag is not None:
                if not ldmp_download.verify_file_against_etag(
                    output_path, expected_etag
                ):
                    log(f"Etag verification failed for {output_path}")
                    output_path.unlink(missing_ok=True)
                    success = False

            if success:
                return True

            if attempt < max_retries - 1:
                _time.sleep(2**attempt)

        return False  # exhausted retries

    def _qgs_download(self, url: str, output_path: Path) -> bool:
        """Single QgsFileDownloader attempt with local QEventLoop."""
        loop = QtCore.QEventLoop()
        dl_success = False
        dl_error = None

        downloader = QgsFileDownloader(QtCore.QUrl(url), str(output_path))

        def _on_completed():
            nonlocal dl_success
            dl_success = True
            loop.quit()

        def _on_error(errors):
            nonlocal dl_error
            dl_error = str(errors)
            loop.quit()

        downloader.downloadCompleted.connect(_on_completed)
        downloader.downloadError.connect(_on_error)
        downloader.downloadExited.connect(loop.quit)
        downloader.downloadCanceled.connect(loop.quit)

        cancel_timer = QtCore.QTimer()
        cancel_timer.timeout.connect(
            lambda: self._check_dl_cancel(loop, downloader, cancel_timer)
        )
        cancel_timer.start(self._CANCEL_CHECK_INTERVAL_MS)

        downloader.startDownload()
        loop.exec()
        cancel_timer.stop()

        if self.isCanceled():
            output_path.unlink(missing_ok=True)
            return False

        if dl_error:
            output_path.unlink(missing_ok=True)
            return False

        return dl_success

    def _check_dl_cancel(self, loop, downloader, timer):
        if self.isCanceled():
            timer.stop()
            downloader.cancelDownload()
            loop.quit()
            return
        now = time.time()
        if now - self._last_lock_refresh >= self._LOCK_REFRESH_INTERVAL_S:
            _refresh_download_lock(self._job_dir)
            self._last_lock_refresh = now

    def _download_cloud_result(
        self, raster_result: RasterResults, files_done: int, total_files: int
    ) -> typing.Tuple[bool, int]:
        """Download all raster files for one RasterResults.

        Returns (success, new_files_done).
        """
        base_output_path = self.job_manager.get_downloaded_dataset_base_file_path(
            self.job
        )
        result_base_path = (
            base_output_path.parent / f"{base_output_path.name}_{raster_result.name}"
        )

        out_rasters = {}

        for key, raster in raster_result.rasters.items():
            file_out_base = f"{result_base_path.name}_{key}"

            if raster.type == results.RasterType.TILED_RASTER:
                tile_uris = []

                for uri_number, uri in enumerate(raster.tile_uris):
                    if self.isCanceled():
                        return False, files_done

                    out_file = (
                        base_output_path.parent / f"{file_out_base}_{uri_number}.tif"
                    )
                    if not self._download_single_file(
                        str(uri.uri), out_file, expected_etag=_get_etag(uri)
                    ):
                        return False, files_done
                    tile_uris.append(results.URI(uri=out_file))

                    files_done += 1
                    self.setProgress(files_done * 100 / max(total_files, 1))

                raster.tile_uris = tile_uris

                vrt_file = base_output_path.parent / f"{file_out_base}.vrt"
                _get_raster_vrt(
                    tiles=[str(u.uri) for u in tile_uris],
                    out_file=vrt_file,
                )
                out_rasters[key] = results.TiledRaster(
                    tile_uris=tile_uris,
                    bands=raster.bands,
                    datatype=raster.datatype,
                    filetype=raster.filetype,
                    uri=results.URI(uri=vrt_file),
                    type=results.RasterType.TILED_RASTER,
                )
            else:
                out_file = base_output_path.parent / f"{file_out_base}.tif"
                if not self._download_single_file(
                    str(raster.uri.uri),
                    out_file,
                    expected_etag=_get_etag(raster.uri),
                ):
                    return False, files_done

                files_done += 1
                self.setProgress(files_done * 100 / max(total_files, 1))

                raster_uri = results.URI(uri=out_file)
                raster.uri = raster_uri
                out_rasters[key] = results.Raster(
                    uri=raster_uri,
                    bands=raster.bands,
                    datatype=raster.datatype,
                    filetype=raster.filetype,
                    type=results.RasterType.ONE_FILE_RASTER,
                )

        raster_result.rasters = out_rasters

        # Setup the main URI (may be a VRT combining multiple rasters)
        if len(raster_result.rasters) > 1 or (
            len(raster_result.rasters) == 1
            and [*raster_result.rasters.values()][0].type
            == results.RasterType.TILED_RASTER
        ):
            vrt_file = base_output_path.parent / f"{result_base_path.name}.vrt"
            main_raster_file_paths = [r.uri.uri for r in out_rasters.values()]
            all_band_names = [
                b.metadata.get("gee_band_name") or b.name
                for r in out_rasters.values()
                for b in r.bands
            ]
            combine_all_bands_into_vrt(
                main_raster_file_paths, vrt_file, band_names=all_band_names
            )
            raster_result.uri = results.URI(uri=vrt_file)
        else:
            raster_result.uri = [*raster_result.rasters.values()][0].uri

        _set_results_extents_raster(raster_result, self.job)
        return True, files_done

    def _download_vector_result(self, vector_result: VectorResults) -> bool:
        """Download one vector result file."""
        if vector_result.uri is None or vector_result.uri.uri is None:
            log(f"No URI for vector result {vector_result.name}")
            return True  # nothing to download is not a failure

        source_uri = str(vector_result.uri.uri)
        if not source_uri.startswith(("http://", "https://", "/vsi")):
            return True  # already local

        base_output_path = self.job_manager.get_downloaded_dataset_base_file_path(
            self.job
        )
        ext = ".gpkg"
        if source_uri.endswith(".geojson"):
            ext = ".geojson"

        out_file = (
            base_output_path.parent
            / f"{base_output_path.name}_{vector_result.name}{ext}"
        )

        if not self._download_single_file(
            source_uri, out_file, expected_etag=_get_etag(vector_result.uri)
        ):
            return False

        vector_result.vector.uri = results.URI(uri=out_file)
        _set_results_extents_vector(vector_result, self.job)
        return True

    def finished(self, result: bool):
        """Main thread — update job status and emit signals."""
        cancelled = self.isCanceled()
        if result and self._all_successful:
            self.job_manager._change_job_status(
                self.job, jobs.JobStatus.DOWNLOADED, force_rewrite=True
            )
            self.job_manager.downloaded_job_results.emit(self.job)
            metadata.init_dataset_metadata(self.job)
        elif cancelled:
            log(f"Download of job {self.job.id} was cancelled")
        else:
            log(f"Download of job {self.job.id} failed: {self.error_message}")

        # Release cross-process download lock
        _release_download_lock(self._job_dir)

        # Signal that this download is done so the next one can start
        self.job_manager._on_download_task_finished(
            cancelled_job_id=self.job.id if cancelled else None,
            failed_job_id=self.job.id
            if (not cancelled and not (result and self._all_successful))
            else None,
        )


class JobManager(QtCore.QObject):
    _encoding = "utf-8"
    _relevant_job_age_threshold_days = 14
    _light_refresh_days = 2  # Lookback window for quick/light refresh
    _full_refresh_interval_minutes = 30  # Auto-trigger full refresh after this interval

    _known_running_jobs: typing.Dict[uuid.UUID, Job]
    _known_finished_jobs: typing.Dict[uuid.UUID, Job]
    _known_failed_jobs: typing.Dict[uuid.UUID, Job]
    _known_deleted_jobs: typing.Dict[uuid.UUID, Job]
    _known_downloaded_jobs: typing.Dict[uuid.UUID, Job]
    _known_ready_jobs: typing.Dict[uuid.UUID, Job]
    _known_pending_jobs: typing.Dict[uuid.UUID, Job]
    _known_cancelled_jobs: typing.Dict[uuid.UUID, Job]
    _known_expired_jobs: typing.Dict[uuid.UUID, Job]

    refreshed_local_state = QtCore.pyqtSignal()
    refreshed_from_remote = QtCore.pyqtSignal()
    downloaded_job_results = QtCore.pyqtSignal(Job)
    downloaded_available_jobs_results = QtCore.pyqtSignal()
    deleted_job = QtCore.pyqtSignal(Job)
    submitted_remote_job = QtCore.pyqtSignal(Job)
    submitted_local_job = QtCore.pyqtSignal(Job)
    processed_local_job = QtCore.pyqtSignal(Job)
    failed_local_job = QtCore.pyqtSignal(Job)
    imported_job = QtCore.pyqtSignal(Job)
    authentication_failed = QtCore.pyqtSignal(str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Qt5: QMutex(Recursive); Qt6: QRecursiveMutex
        try:
            self._state_update_mutex = QtCore.QMutex(QtCore.QMutex.Recursive)
        except AttributeError:
            self._state_update_mutex = QtCore.QRecursiveMutex()
        self._api_client_mutex = QtCore.QMutex()
        self.clear_known_jobs()
        self.tm = QgsApplication.taskManager()
        self._api_client = None
        self._current_api_url = None
        self._api_client_testing = False  # Track if client was set for testing
        # Per-directory cache. Cleared at the start of each refresh cycle so each directory is
        # globbed and parsed at most once per cycle.
        self._dir_job_cache: typing.Dict[
            Path, typing.Dict[jobs.JobStatus, typing.List[Job]]
        ] = {}
        # SQLite-based persistent cache for Job objects. Survives QGIS restarts,
        # eliminating the need to re-parse large JSON files on every startup.
        self._job_cache = JobCache()
        # Flag to track when background file scanning is in progress.
        # Used to prevent download operations from conflicting with file I/O.
        self._scanning_files = False
        # QgsTask-based download state
        self._download_in_progress = False
        self._current_download_task = None  # active DownloadJobResultsTask
        self._cancelled_download_job_ids: typing.Set[uuid.UUID] = set()
        self._failed_download_job_ids: typing.Set[uuid.UUID] = set()

    @property
    def api_client(self):
        """Get the API client, refreshing if the API URL has changed.

        If the client was set for testing, the URL check is skipped to prevent
        the mock client from being replaced with a production client.

        A mutex serialises access so that concurrent callers never create
        duplicate APIClient instances (and duplicate signal connections).
        """
        self._api_client_mutex.lock()
        try:
            # If client was set for testing, use it as-is
            if self._api_client_testing and self._api_client is not None:
                return self._api_client

            current_url = get_api_url()
            if self._api_client is None or self._current_api_url != current_url:
                self._api_client = api.APIClient(current_url, TIMEOUT)
                self._current_api_url = current_url
                # Connect API client's authentication_failed signal to our signal
                self._api_client.authentication_failed.connect(
                    self.authentication_failed
                )
            return self._api_client
        finally:
            self._api_client_mutex.unlock()

    @api_client.setter
    def api_client(self, client):
        """Set the API client (useful for testing with mock clients)."""
        self._api_client = client
        self._api_client_testing = client is not None
        if client is not None:
            self._current_api_url = getattr(client, "url", None)

    def refresh_api_client(self):
        """Force refresh the API client to use current settings."""
        self._api_client = None
        self._current_api_url = None
        self._api_client_testing = False

    def _is_json_file_safe(self, file_path: Path) -> bool:
        """
        Safely check if a JSON file can be read without causing crashes.
        """
        try:
            stat_info = file_path.stat()
            return stat_info.st_size > 0
        except (OSError, IOError, PermissionError):
            return False
        except Exception:
            return False

    @property
    def known_jobs(self):
        self._state_update_mutex.lock()
        try:
            return {
                jobs.JobStatus.RUNNING: dict(self._known_running_jobs),
                jobs.JobStatus.FINISHED: dict(self._known_finished_jobs),
                jobs.JobStatus.FAILED: dict(self._known_failed_jobs),
                jobs.JobStatus.DELETED: dict(self._known_deleted_jobs),
                jobs.JobStatus.DOWNLOADED: dict(self._known_downloaded_jobs),
                jobs.JobStatus.READY: dict(self._known_ready_jobs),
                jobs.JobStatus.PENDING: dict(self._known_pending_jobs),
                jobs.JobStatus.CANCELLED: dict(self._known_cancelled_jobs),
                jobs.JobStatus.EXPIRED: dict(self._known_expired_jobs),
            }
        finally:
            self._state_update_mutex.unlock()

    @property
    def relevant_jobs(self) -> typing.List[Job]:
        """Return a list of all jobs that are relevant to show to the user."""
        relevant_statuses = (
            jobs.JobStatus.READY,
            jobs.JobStatus.PENDING,
            jobs.JobStatus.RUNNING,
            jobs.JobStatus.FINISHED,
            jobs.JobStatus.FAILED,
            jobs.JobStatus.DOWNLOADED,  # This includes both DOWNLOADED and GENERATED_LOCALLY jobs
            jobs.JobStatus.CANCELLED,
            jobs.JobStatus.EXPIRED,
        )
        result = []
        self._state_update_mutex.lock()
        try:
            for status in relevant_statuses:
                result.extend(self._get_internal_dict_for_status(status).values())
        finally:
            self._state_update_mutex.unlock()
        return result

    def get_job_dropdown_metadata(
        self,
        status_filter: typing.Optional[typing.List[str]] = None,
    ) -> typing.List[typing.Dict[str, typing.Any]]:
        """Get lightweight metadata for all jobs, suitable for dropdown population.

        This reads directly from SQLite indexed columns - no Job unpickling needed.
        Returns job_id, job_status, script_id, script_name, and extent for each job.

        Args:
            status_filter: Optional list of job_status values to include.
                          If None, excludes only FAILED_PARSE entries.

        Returns:
            List of dicts with keys: job_id, job_status, script_id, script_name,
            extent_north, extent_south, extent_east, extent_west, path
        """
        return self._job_cache.get_dropdown_metadata(status_filter)

    @property
    def running_jobs_dir(self) -> Path:
        return (
            Path(conf.settings_manager.get_value(conf.Setting.BASE_DIR))
            / "running-jobs"
        )

    @property
    def finished_jobs_dir(self) -> Path:
        return (
            Path(conf.settings_manager.get_value(conf.Setting.BASE_DIR))
            / "finished-jobs"
        )

    @property
    def failed_jobs_dir(self) -> Path:
        return (
            Path(conf.settings_manager.get_value(conf.Setting.BASE_DIR)) / "failed-jobs"
        )

    @property
    def deleted_jobs_dir(self) -> Path:
        return (
            Path(conf.settings_manager.get_value(conf.Setting.BASE_DIR))
            / "deleted-jobs"
        )

    @property
    def expired_jobs_dir(self) -> Path:
        return (
            Path(conf.settings_manager.get_value(conf.Setting.BASE_DIR))
            / "expired-jobs"
        )

    @property
    def datasets_dir(self) -> Path:
        return Path(conf.settings_manager.get_value(conf.Setting.BASE_DIR)) / "datasets"

    @property
    def exports_dir(self) -> Path:
        return Path(conf.settings_manager.get_value(conf.Setting.BASE_DIR)) / "exported"

    def clear_known_jobs(self):
        self._state_update_mutex.lock()
        try:
            self._known_running_jobs = {}
            self._known_finished_jobs = {}
            self._known_failed_jobs = {}
            self._known_deleted_jobs = {}
            self._known_downloaded_jobs = {}
            self._known_ready_jobs = {}
            self._known_pending_jobs = {}
            self._known_cancelled_jobs = {}
            self._known_expired_jobs = {}
            # Params preserved from jobs transitioning away from RUNNING status.
            # Used to restore params when fetching finished job data from remote.
            self._transitioned_job_params: typing.Dict[uuid.UUID, dict] = {}
            # Metadata preserved from jobs transitioning status. The remote API
            # excludes task_name/task_notes, so we save them for later merging.
            self._transitioned_job_metadata: typing.Dict[
                uuid.UUID, typing.Dict[str, typing.Any]
            ] = {}
            # Track when last full remote refresh was done
            self._last_full_refresh_time: typing.Optional[dt.datetime] = None
            # Also clear the per-directory cache (may not exist yet during __init__)
            if hasattr(self, "_dir_job_cache"):
                self._dir_job_cache.clear()
        finally:
            self._state_update_mutex.unlock()

    def _preserve_job_data(self, job: Job) -> None:
        """Preserve params and metadata from a job before its file is removed.

        The remote API excludes params, task_name, task_notes, and local_context
        to reduce bandwidth. We save these fields so they can be restored when
        the job reappears with a new status.
        """
        self.ensure_params_loaded(job)
        if job.params:
            self._transitioned_job_params[job.id] = job.params
        metadata = {}
        if job.task_name:
            metadata["task_name"] = job.task_name
        if job.task_notes:
            metadata["task_notes"] = job.task_notes
        if job.local_context:
            metadata["local_context"] = job.local_context
        if metadata:
            self._transitioned_job_metadata[job.id] = metadata

    def _restore_job_data(self, job: Job) -> None:
        """Restore preserved params and metadata to a job from remote API.

        This merges data saved by _preserve_job_data back into the job object.
        """
        if not job.params and job.id in self._transitioned_job_params:
            job.params = self._transitioned_job_params.pop(job.id)
        if job.id in self._transitioned_job_metadata:
            metadata = self._transitioned_job_metadata.pop(job.id)
            if not job.task_name and "task_name" in metadata:
                job.task_name = metadata["task_name"]
            if not job.task_notes and "task_notes" in metadata:
                job.task_notes = metadata["task_notes"]
            # Restore local_context if saved metadata has meaningful area name.
            if "local_context" in metadata:
                saved_context = metadata["local_context"]
                if (
                    saved_context
                    and saved_context.area_of_interest_name
                    and saved_context.area_of_interest_name != "unknown-area"
                ):
                    job.local_context = saved_context

    def _get_internal_dict_for_status(
        self, status: jobs.JobStatus
    ) -> typing.Dict[uuid.UUID, Job]:
        """Return the *actual* internal dict for a given status.

        Unlike the ``known_jobs`` property (which returns shallow copies for
        thread-safe reads), this gives back the live dict so that callers can
        mutate the in-memory cache.  **Must only be called while holding
        ``_state_update_mutex``.**
        """
        return {
            jobs.JobStatus.RUNNING: self._known_running_jobs,
            jobs.JobStatus.FINISHED: self._known_finished_jobs,
            jobs.JobStatus.FAILED: self._known_failed_jobs,
            jobs.JobStatus.DELETED: self._known_deleted_jobs,
            jobs.JobStatus.DOWNLOADED: self._known_downloaded_jobs,
            jobs.JobStatus.READY: self._known_ready_jobs,
            jobs.JobStatus.PENDING: self._known_pending_jobs,
            jobs.JobStatus.CANCELLED: self._known_cancelled_jobs,
            jobs.JobStatus.EXPIRED: self._known_expired_jobs,
        }[status]

    def _set_known_job(self, status: jobs.JobStatus, job: Job) -> None:
        """Insert *job* into the internal dict for *status* under the mutex."""
        self._state_update_mutex.lock()
        try:
            self._get_internal_dict_for_status(status)[job.id] = job
        finally:
            self._state_update_mutex.unlock()

    def _remove_known_job(self, status: jobs.JobStatus, job_id: uuid.UUID) -> None:
        """Remove *job_id* from the internal dict for *status* under the mutex.

        Does nothing if *job_id* is not present.
        """
        self._state_update_mutex.lock()
        try:
            self._get_internal_dict_for_status(status).pop(job_id, None)
        finally:
            self._state_update_mutex.unlock()

    def _preload_local_jobs_cache(self):
        """Load all local job directories into cache WITHOUT holding the mutex.

        This method does the slow file I/O work outside of any locks, so that
        the UI thread (which needs `relevant_jobs`) is not blocked while files
        are being parsed.

        Call this BEFORE acquiring _state_update_mutex in refresh methods.
        """
        # Set flag to prevent concurrent file operations (e.g., downloads)
        self._scanning_files = True
        try:
            self._preload_local_jobs_cache_inner()
        finally:
            self._scanning_files = False

    def _preload_local_jobs_cache_inner(self):
        """Inner implementation of cache preloading.

        Always does a full directory scan to ensure job statuses are current.
        The SQLite cache provides speedup via mtime-based caching in
        _load_jobs_from_dir() - files that haven't changed are loaded from
        cache instead of being re-parsed.
        """
        # Always do full directory scan to get current job statuses.
        # SQLite cache is used as a parse cache (via mtime checks in
        # _load_jobs_from_dir), not as a status cache.
        self._dir_job_cache.clear()

        # Preload all directories that will be needed by the refresh methods
        dirs_to_load = [
            self.running_jobs_dir,
            self.finished_jobs_dir,
            self.failed_jobs_dir,
            self.deleted_jobs_dir,
            self.expired_jobs_dir,
            self.datasets_dir,
        ]

        for dir_path in dirs_to_load:
            if dir_path not in self._dir_job_cache:
                self._dir_job_cache[dir_path] = self._load_jobs_from_dir(dir_path)

    def refresh_local_state(self):
        """Update dataset manager's in-memory cache by scanning the local filesystem

        This function should be called periodically in order to ensure eventual
        consistency of the in-memory cache with the actual filesystem state.
        The filesystem is the source of truth for existing job metadata files and
        available results.
        """
        # --- Phase 1: Load all local files WITHOUT holding the mutex -----------
        # This allows the UI thread to continue accessing relevant_jobs while
        # we do the slow file I/O work.
        self._preload_local_jobs_cache()

        # --- Phase 2: Update in-memory state under the mutex -------------------
        self._state_update_mutex.lock()

        try:
            self._known_running_jobs = {}
            for j in self._get_local_jobs(jobs.JobStatus.RUNNING):
                if _is_local_only_job(j) and _is_orphaned_local_job(j):
                    log(
                        f"Marking orphaned local job {j.id} as FAILED "
                        f"(owner PID {getattr(j.local_context, 'owner_pid', None)} "
                        f"is no longer running)"
                    )
                    if j.end_date is None:
                        j.end_date = dt.datetime.now(dt.timezone.utc)
                    self._change_job_status(j, jobs.JobStatus.FAILED)
                else:
                    self._known_running_jobs[j.id] = j

            # Rebuild pending/ready caches from disk so that stale entries
            # (e.g. jobs that finished between refresh cycles) are removed.
            self._known_pending_jobs = {
                j.id: j for j in self._get_local_jobs(jobs.JobStatus.PENDING)
            }
            self._known_ready_jobs = {
                j.id: j for j in self._get_local_jobs(jobs.JobStatus.READY)
            }

            self._refresh_local_downloaded_jobs()
            # We copy the dictionary before iterating in order to avoid having it
            # change size during the process
            frozen_known_downloaded_jobs = self._known_downloaded_jobs.copy()
            # move any downloaded jobs with missing local paths back to FINISHED

            demoted_ids = set()
            for j_id, j in frozen_known_downloaded_jobs.items():
                # Check each result for missing local paths
                has_missing_path = False
                for res in j._get_results_list():
                    if (
                        hasattr(res, "uri")
                        and res.uri
                        and not is_gdal_vsi_path(res.uri.uri)
                        and not res.uri.uri.exists()
                    ):
                        has_missing_path = True
                        # Clear the URI for this result
                        if isinstance(res, VectorResults):
                            res.vector.uri = None
                        else:
                            res.uri = None

                if has_missing_path:
                    log(
                        f"job {j_id} currently marked as DOWNLOADED but has "
                        "missing paths, so moving back to FINISHED status"
                    )
                    self._change_job_status(
                        j, jobs.JobStatus.FINISHED, force_rewrite=True
                    )
                    demoted_ids.add(j_id)

            if demoted_ids:
                self._known_downloaded_jobs = {
                    j_id: j
                    for j_id, j in self._known_downloaded_jobs.items()
                    if j_id not in demoted_ids
                }

            # NOTE: finished and failed jobs are treated differently here because
            # we also make sure to delete those that are old and never got
            # downloaded (or are old and failed)
            self._get_local_finished_jobs()
            self._get_local_failed_jobs()
            self._get_local_expired_jobs()
        finally:
            self._state_update_mutex.unlock()

        self.refreshed_local_state.emit()

    def refresh_from_remote_state(
        self, emit_signal: bool = True, full_refresh: bool = False
    ):
        """Request the latest state from the remote server

         Then update filesystem directories too.

         Args:
            emit_signal: If True, emit refreshed_from_remote signal when done.
            full_refresh: If True, fetch jobs from the full lookback window
                (14 days). If False, do a light refresh (2 days) unless enough
                time has passed since the last full refresh.

         Checking for remote updates entails:

         - Scanning the `running-jobs` local directory, looking for job metadata files
         - Scanning the remote server in order to retrieve a list of all remote job
            metadata files
         - Comparing each remote job with the local job
         - If a job is both on the local jobs list and on the remote jobs list, we
           proceed to update its local job metadata file

        - If a job is only on the local list, then something went wrong with its remote
          processing. We can notify the user and then we remove the job metadata file
          from the `running-jobs` directory immediately. This job is effectively
          discarded. The user will need to retry execution, if needed

        - If a job is only on the remote list, then we might have asked that its
          results be deleted in the past. We look for the job's id on the
          `deleted-datasets` directory.

          - If we find that the results of this job were deleted on purpose, then we
            ignore the remote job.

          - If we cannot find the job on the `deleted-datasets` directory, then we
            assume this is a new job that was created by some other means (another
            client other than QGIS) and we store it locally in either the
            `running-jobs` dir or the `finished-jobs` dir, depending on the job's status

        - If the job is complete we can now download the results. However, we may have
          to do that on demand, so it is not done immediately. Instead, we move the
          job metadata file to the `finished-jobs` directory on disk

        """
        now = dt.datetime.now(tz=dt.timezone.utc)

        # Determine if we need a full refresh (auto-trigger after interval)
        do_full_refresh = full_refresh
        if not do_full_refresh and self._last_full_refresh_time is not None:
            elapsed = now - self._last_full_refresh_time
            if elapsed.total_seconds() >= self._full_refresh_interval_minutes * 60:
                do_full_refresh = True
                log(
                    f"Auto-triggering full refresh ({elapsed.total_seconds() / 60:.1f} "
                    f"min since last full refresh)"
                )
        elif self._last_full_refresh_time is None:
            # First refresh should be full to ensure we have complete state
            do_full_refresh = True
            log("First refresh - doing full refresh")

        # Use appropriate lookback window
        if do_full_refresh:
            lookback_days = self._relevant_job_age_threshold_days
        else:
            lookback_days = self._light_refresh_days
        relevant_date = now - dt.timedelta(days=lookback_days)

        offline_mode = conf.settings_manager.get_value(conf.Setting.OFFLINE_MODE)
        remote_fetch_ok = False  # True only when API returned a real response

        if not offline_mode:
            # Network call happens outside the mutex so that concurrent readers
            # of in-memory state (e.g. the UI) are not blocked.
            remote_jobs = get_remote_jobs(end_date=relevant_date)

            if remote_jobs is None:
                # API call failed (auth / network / timeout).  Fall back to a
                # local-only refresh so that we don't accidentally delete local
                # running-job metadata because of a transient server outage.
                log(
                    "Remote fetch failed — performing local-only refresh to "
                    "avoid deleting local job state"
                )
                relevant_remote_jobs = []
                remote_fetch_ok = False
            else:
                remote_fetch_ok = True
                if conf.settings_manager.get_value(
                    conf.Setting.FILTER_JOBS_BY_BASE_DIR
                ):
                    relevant_remote_jobs = get_relevant_remote_jobs(remote_jobs)
                else:
                    relevant_remote_jobs = remote_jobs
        else:
            relevant_remote_jobs = []

        # This allows the UI thread to continue accessing relevant_jobs while
        # we do the slow file I/O work.
        self._preload_local_jobs_cache()

        # Network calls for individual job results are done here, OUTSIDE the
        # mutex, to avoid blocking the UI thread. We identify which finished
        # jobs need fetching by reading the preloaded dir cache (no mutex
        # needed since only this worker writes to it during refresh).
        prefetched_finished_jobs: typing.Dict[uuid.UUID, typing.Optional[Job]] = {}
        if not offline_mode and remote_fetch_ok:
            # Read local state from the preloaded cache to identify new jobs
            local_deleted_ids = {
                j.id for j in self._get_local_jobs(jobs.JobStatus.DELETED)
            }
            local_finished_ids = {
                j.id for j in self._get_local_jobs(jobs.JobStatus.FINISHED)
            }
            local_downloaded_ids = {
                j.id
                for j in (
                    self._get_local_jobs(jobs.JobStatus.DOWNLOADED)
                    + self._get_local_jobs(jobs.JobStatus.GENERATED_LOCALLY)
                )
            }
            remote_finished = [
                j for j in relevant_remote_jobs if j.status == jobs.JobStatus.FINISHED
            ]
            for rj in remote_finished:
                if (
                    rj.id not in local_deleted_ids
                    and rj.id not in local_downloaded_ids
                    and rj.id not in local_finished_ids
                ):
                    # Fetch full job data (with results) outside the mutex
                    prefetched_finished_jobs[rj.id] = get_remote_job_with_results(rj.id)

        # All network I/O and heavy file parsing is done above. Now do
        # in-memory dict updates. File writes are collected in
        # _deferred_writes and flushed after releasing the mutex.
        deferred_writes: typing.List[Job] = []
        self._state_update_mutex.lock()
        try:
            self._refresh_local_deleted_jobs()

            if not offline_mode and remote_fetch_ok:
                deleted_ids = self._known_deleted_jobs.keys()
                relevant_remote_jobs = [
                    job for job in relevant_remote_jobs if job.id not in deleted_ids
                ]

            self._refresh_local_running_jobs(
                relevant_remote_jobs,
                remote_fetch_ok=remote_fetch_ok,
                deferred_writes=deferred_writes,
            )
            self._refresh_local_finished_jobs(
                relevant_remote_jobs,
                prefetched_finished_jobs=prefetched_finished_jobs,
                deferred_writes=deferred_writes,
            )
            self._refresh_local_downloaded_jobs()
            self._refresh_remote_failed_jobs(
                relevant_remote_jobs, deferred_writes=deferred_writes
            )
            self._refresh_remote_jobs_by_status(
                relevant_remote_jobs, deferred_writes=deferred_writes
            )
            self._get_local_expired_jobs()

            # Track when a successful full refresh was done
            if remote_fetch_ok and do_full_refresh:
                self._last_full_refresh_time = now

            log(
                f"JobManager refresh completed — "
                f"remote_fetch_ok={remote_fetch_ok}, "
                f"full_refresh={do_full_refresh}, "
                f"lookback={lookback_days} days, "
                f"{len(relevant_remote_jobs)} relevant remote jobs"
            )
        finally:
            self._state_update_mutex.unlock()

        # Deferred file writes are done after releasing the mutex to avoid blocking the UI thread.
        for job_to_write in deferred_writes:
            try:
                self.write_job_metadata_file(job_to_write)
            except (OSError, IOError) as exc:
                log(
                    f"Failed to write deferred job file for {job_to_write.id}: "
                    f"{type(exc).__name__}: {exc}"
                )

        if emit_signal:
            # Clear cancelled-download set so freshly-updated jobs are retried
            self._cancelled_download_job_ids.clear()
            self.refreshed_from_remote.emit()

    def delete_job(self, job: Job):
        """Delete a job metadata file and any associated datasets from the local disk

        The job metadata file is moved to the `deleted-jobs` dir. This shall prevent
        subsequent downloads when refreshing the local state from the remote server.

        """

        if job.status != jobs.JobStatus.DELETED:
            try:
                _delete_job_datasets(job)
            except PermissionError:
                log(f"Permissions error on path skipping deletion of {job.id}...")
                # TODO: add back in old code used for removing visible layers
                # prior to deletion

                return
            self._change_job_status(job, jobs.JobStatus.DELETED, force_rewrite=False)
        else:
            log(f"job {job.id} has already been deleted, skipping...")
        self.deleted_job.emit(job)

    def submit_remote_job(
        self,
        params: typing.Dict,
        script_id: uuid.UUID,
    ) -> typing.Optional[Job]:
        """Submit a job for remote execution

        Creation of new jobs entails:
        1. submitting a process for remote execution
        2. waiting server response with a job metadata file
        3. storing returned job metadata file on disk, on the `running-jobs` directory

        """

        # Note - this is a reimplementation of api.run_script
        final_params = params.copy()
        final_params["task_notes"] = params["task_notes"]
        final_params["local_context"] = (
            jobs.JobLocalContext().Schema().dump(_get_local_context())
        )
        url_fragment = f"/api/v1/script/{script_id}/run"
        response = self.api_client.call_api(
            url_fragment, "post", final_params, use_token=True
        )
        try:
            raw_job = response["data"]
        except (TypeError, KeyError):
            job = None
        else:
            job = _get_job_schema().load(raw_job)

            # Safely set result extents to prevent crashes from file access issues
            try:
                set_results_extents(job)
            except Exception as exc:
                log(
                    f"Failed to set extents for job {job.id}: {type(exc).__name__}: {exc}"
                )

            self.write_job_metadata_file(job)
            self._update_known_jobs_with_newly_submitted_job(job)
            self.submitted_remote_job.emit(job)

        return job

    def submit_local_job_as_qgstask(
        self,
        params: typing.Dict,
        script_name: str,
        area_of_interest: areaofinterest.AOI,
    ):
        final_params = params.copy()
        task_name = final_params.pop("task_name")
        task_notes = final_params.pop("task_notes")
        job = Job(
            id=uuid.uuid4(),
            params=final_params,
            progress=0,
            start_date=dt.datetime.now(dt.timezone.utc),
            status=jobs.JobStatus.PENDING,
            local_context=_get_local_context(),
            task_name=task_name,
            task_notes=task_notes,
            results=RasterResults(name=script_name, rasters={}, uri=None),
            script=models.get_job_local_script(script_name),
        )
        self.write_job_metadata_file(job)
        self._update_known_jobs_with_newly_submitted_job(job)
        self.submitted_local_job.emit(job)

        job_name_parts = []
        if task_name:
            job_name_parts.append(task_name)
        elif job.local_context.area_of_interest_name:
            job_name_parts.append(job.local_context.area_of_interest_name)
        job_name_parts.append(script_name)
        job_name = " - ".join(job_name_parts)

        job_task = LocalJobTask(job_name, job, area_of_interest)
        job_task.processed_job.connect(self.finish_local_job)
        job_task.failed_job.connect(self.fail_local_job)
        job_task.running_job.connect(lambda job=job: self._mark_local_job_running(job))

        message_bar_item = QgsMessageBar.createMessage(
            self.tr(f"Processing: {task_name}")
        )
        progress_bar = QProgressBar()
        progress_bar.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        cancel_button = QPushButton()
        cancel_button.setText("Cancel")
        message_bar_item.layout().addWidget(progress_bar)
        message_bar_item.layout().addWidget(cancel_button)
        message_bar = iface.messageBar()
        message_bar.pushWidget(message_bar_item, Qgis.Info)

        def _set_progress_bar_value(value: float):
            try:
                if value <= 100:
                    progress_bar.setValue(int(value))
            except RuntimeError:
                pass  # C++ widget has been deleted

        def cancel_task():
            try:
                job_task.cancel()
                message_bar.close()
            except RuntimeError:
                pass  # C++ widget has been deleted

        def close_messages():
            try:
                message_bar = iface.messageBar()
                message_bar.popWidget(message_bar_item)
            except RuntimeError:
                pass  # C++ widget has been deleted

        job_task.taskCompleted.connect(close_messages)
        job_task.taskTerminated.connect(close_messages)
        cancel_button.clicked.connect(cancel_task)
        job_task.progressChanged.connect(_set_progress_bar_value)

        self.tm.addTask(job_task)

    def submit_local_job(
        self,
        params: typing.Dict,
        script_name: str,
        area_of_interest: areaofinterest.AOI,
    ):
        final_params = params.copy()
        task_name = final_params.pop("task_name")
        task_notes = final_params.pop("task_notes")
        job = Job(
            id=uuid.uuid4(),
            params=final_params,
            progress=0,
            start_date=dt.datetime.now(dt.timezone.utc),
            status=jobs.JobStatus.PENDING,
            local_context=_get_local_context(),
            task_name=task_name,
            task_notes=task_notes,
            results=RasterResults(name=script_name, rasters={}, uri=None),
            script=models.get_job_local_script(script_name),
        )
        self.write_job_metadata_file(job)
        self._update_known_jobs_with_newly_submitted_job(job)
        self.submitted_local_job.emit(job)
        self.process_local_job(job, area_of_interest)

    def process_local_job(self, job: Job, area_of_interest: areaofinterest.AOI):
        job_logger = setup_local_job_logger(job)
        script_name = getattr(job.script, "name", "unknown")
        job_logger.info(f"Starting execution of {script_name}")

        execution_handler = utils.load_object(job.script.execution_callable)
        job_output_path, dataset_output_path = _get_local_job_output_paths(job)
        try:
            done_job = execution_handler(
                job, area_of_interest, job_output_path, dataset_output_path
            )
        except Exception:
            logger.exception("Execution handler raised an exception")
            job_logger.error(traceback.format_exc())
            job.status = jobs.JobStatus.FAILED
            job.end_date = dt.datetime.now(dt.timezone.utc)
            self.fail_local_job(job)
            return

        if done_job is None:
            job_logger.error("Execution handler returned no results")
            job.status = jobs.JobStatus.FAILED
            job.end_date = dt.datetime.now(dt.timezone.utc)
            self.fail_local_job(job)
            return

        job_logger.info("Execution completed successfully")
        self.finish_local_job(done_job)

    def finish_local_job(self, job):
        self._change_job_status(job, jobs.JobStatus.GENERATED_LOCALLY)
        self.processed_local_job.emit(job)

    def fail_local_job(self, job):
        self._change_job_status(job, job.status)
        self.failed_local_job.emit(job)

    def _mark_local_job_running(self, job):
        if job.status == jobs.JobStatus.PENDING:
            job.local_context.owner_pid = os.getpid()
            self._change_job_status(job, jobs.JobStatus.RUNNING)

    def download_job_results(self, job: Job) -> Job:
        if job.results is None:
            log(f"Job {job.id} has no results")
            return None

        if job.status == jobs.JobStatus.DOWNLOADED:
            # TODO:  We should never get here, but we do sometimes... Need to debug
            # more to figure out why
            return None

        # Get list of results (handles both single result and list of results)
        results_list = job._get_results_list()
        if not results_list:
            log(f"Job {job.id} has empty results list")
            return None

        # Download each result
        all_downloads_successful = True
        for result in results_list:
            if not hasattr(result, "type"):
                log(
                    f"Skipping unrecognized result (raw dict or missing type) "
                    f"for job {job.id}: {result!r}"
                )
                continue
            handler = {
                ResultType.RASTER_RESULTS: self._download_cloud_results,
                ResultType.TIME_SERIES_TABLE: self._download_timeseries_table,
                ResultType.VECTOR_RESULTS: self._download_vector_results,
            }.get(result.type)

            if handler is not None:
                output_uri = handler(job, result)

                if output_uri is not None:
                    # For RasterResults, set uri on the result object
                    # For VectorResults, uri is set internally via vector.uri
                    if result.type == ResultType.RASTER_RESULTS:
                        result.uri = output_uri
                    log(f"result.uri is {result.uri}")
                elif result.type != ResultType.TIME_SERIES_TABLE:
                    # TIME_SERIES_TABLE returns None normally (data in job file)
                    all_downloads_successful = False
                    log(
                        f"Failed to download result of type {result.type} for job {job.id}"
                    )
            elif result.type != ResultType.TIME_SERIES_TABLE:
                # Unknown result type - log but don't fail
                log(f"No handler for result type {result.type}")

        if all_downloads_successful:
            self._change_job_status(job, jobs.JobStatus.DOWNLOADED, force_rewrite=True)
            self.downloaded_job_results.emit(job)
        else:
            return None

        metadata.init_dataset_metadata(job)

        # TODO: maybe we don't need to return anything here
        return job

    def download_one_available_result(self) -> bool:
        """Download one finished job's results.

        Returns True if there are more jobs to download, False otherwise.
        This allows calling code to check if it should schedule another download
        cycle without blocking the UI.

        Downloading remote results entails:
        - For each job that is known to be in a FINISHED state, we retrieve the relevant
          download URL(s)
        - We try to download all results into some subdir under the `downloaded-datasets`
          directory
        - If the download was successful, we now create a result metadata file and put it
          in the `downloaded-datasets` directory. If not, we do not do anything and will
          allow the user to retry downloading later
        - When we have created the result metadata file we delete the job metadata file,
          as it is not necessary anymore

        """
        # Skip downloads while background file scanning is in progress to avoid
        # file locking conflicts on Windows (WinError 32)
        if self._scanning_files:
            log("Skipping download - file scanning in progress")
            return True  # Return True to retry later

        # Get the first finished job (if any) and download its results
        finished_jobs = self.known_jobs[jobs.JobStatus.FINISHED]
        if len(finished_jobs) == 0:
            return False

        # Get one job to download (dict.values() returns view, take first)
        job = next(iter(finished_jobs.values()))
        self.download_job_results(job)

        # Return True if there are more jobs to download
        remaining = len(self.known_jobs[jobs.JobStatus.FINISHED])
        if remaining == 0:
            self.downloaded_available_jobs_results.emit()
        return remaining > 0

    def download_available_results(self):
        """Download all finished jobs' results (blocking).

        NOTE: This method downloads ALL jobs sequentially and will block the UI.
        For non-blocking downloads, use download_one_available_result() instead
        and schedule subsequent downloads via QTimer.singleShot().
        """
        while self.download_one_available_result():
            pass

    def start_downloading_one_result(self):
        """Start downloading one finished job's results via QgsTask.

        Non-blocking — the task runs on QgsTaskManager's thread pool.
        When done, finished() calls _on_download_task_finished() to
        schedule the next download.
        """
        if self._scanning_files or self._download_in_progress:
            return

        finished_jobs = self.known_jobs[jobs.JobStatus.FINISHED]
        if not finished_jobs:
            return

        self._download_in_progress = True

        # Skip jobs the user has explicitly cancelled, already failed, or already being
        # downloaded by another QGIS instance (cross-process lock).
        job = None
        for candidate in finished_jobs.values():
            if candidate.id in self._cancelled_download_job_ids:
                continue
            if candidate.id in self._failed_download_job_ids:
                continue
            job_dir = self.datasets_dir / str(candidate.id)
            if _try_acquire_download_lock(job_dir):
                job = candidate
                break
        if job is None:
            self._download_in_progress = False
            return

        task = DownloadJobResultsTask(job, self)
        self._current_download_task = task  # prevent GC until addTask

        # Progress bar in message bar (matching submit_local_job_as_qgstask pattern)
        message_bar_item = QgsMessageBar.createMessage(
            self.tr(f"Downloading: {job.task_name or job.id}")
        )
        progress_bar = QProgressBar()
        progress_bar.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        cancel_button = QPushButton()
        cancel_button.setText("Cancel")
        message_bar_item.layout().addWidget(progress_bar)
        message_bar_item.layout().addWidget(cancel_button)
        iface.messageBar().pushWidget(message_bar_item, Qgis.Info)

        def _set_progress_bar_value(value: float):
            try:
                if value <= 100:
                    progress_bar.setValue(int(value))
            except RuntimeError:
                pass  # C++ widget has been deleted

        cancel_button.clicked.connect(task.cancel)
        task.progressChanged.connect(_set_progress_bar_value)

        def _close_message_bar():
            try:
                iface.messageBar().popWidget(message_bar_item)
            except RuntimeError:
                pass

        task.taskCompleted.connect(_close_message_bar)
        task.taskTerminated.connect(_close_message_bar)

        self.tm.addTask(task)

    def _on_download_task_finished(self, cancelled_job_id=None, failed_job_id=None):
        """Called from DownloadJobResultsTask.finished() on the main thread."""
        self._download_in_progress = False
        self._current_download_task = None

        if cancelled_job_id is not None:
            self._cancelled_download_job_ids.add(cancelled_job_id)
            return  # User cancelled — don't auto-restart

        if failed_job_id is not None:
            self._failed_download_job_ids.add(failed_job_id)

        # Count only jobs that haven't already failed or been cancelled this session
        skip_ids = self._failed_download_job_ids | self._cancelled_download_job_ids
        remaining = sum(
            1
            for j in self.known_jobs[jobs.JobStatus.FINISHED].values()
            if j.id not in skip_ids
        )
        if remaining == 0:
            self.downloaded_available_jobs_results.emit()
        else:
            # Schedule next download after a short delay
            QtCore.QTimer.singleShot(100, self.start_downloading_one_result)

    def ensure_results_loaded(self, job: Job) -> bool:
        """Ensure that ``job.results`` is populated.

        When jobs are loaded from the SQLite cache without results (for fast
        UI display), this method lazily loads the results pickle on demand.
        Returns True if results are available after the call.
        """
        if job.results is not None:
            return True
        return self._job_cache.load_results_for_job(job)

    def ensure_params_loaded(self, job: Job) -> bool:
        """Ensure that ``job.params`` is populated.

        When jobs are loaded from the SQLite cache without params (for fast
        UI display), this method lazily loads the params pickle on demand.
        Returns True if params are available after the call.
        """
        if job.params:
            return True
        return self._job_cache.load_params_for_job(job)

    def display_default_job_results(self, job: Job):
        # Handle list of results
        for result in job._get_results_list():
            if isinstance(result, RasterResults):
                if result.uri.uri.suffix in [".tif", ".vrt"]:
                    for band_index, band in enumerate(result.get_bands(), start=1):
                        if band.add_to_map:
                            layers.add_layer(
                                str(result.uri.uri),
                                band_index,
                                JobBand.Schema().dump(band),
                            )
            elif isinstance(result, VectorResults):
                layer_path = result.uri.uri
                layers.add_vector_layer(str(layer_path), result.name)

    def display_selected_job_results(self, job: Job, band_numbers):
        # For now, only handle raster results with band selection
        raster_result = job.get_first_result_by_type(RasterResults)
        if raster_result and raster_result.uri.uri.suffix in [".tif", ".vrt"]:
            for n, band in enumerate(raster_result.get_bands(), start=1):
                if n in band_numbers:
                    layers.add_layer(
                        str(raster_result.uri.uri), n, JobBand.Schema().dump(band)
                    )

    def display_error_recode_layer(self, job: Job):
        vector_result = _find_error_recode_result(job)
        if vector_result is None:
            log(f"No error recode vector result found for job {job.id}")
            return
        layer_path = vector_result.uri.uri
        layer = layers.add_vector_layer(str(layer_path), vector_result.name)
        if layer is not None:
            layer.setCustomProperty("job_id", str(job.id))
        else:
            log("display_error_recode_layer: layer is None after add_vector_layer")

    def edit_error_recode_layer(self, job: Job):
        vector_result = _find_error_recode_result(job)
        if vector_result is None:
            log(f"No error recode vector result found for job {job.id}")
            return
        layer_path = vector_result.uri.uri
        layers.edit(str(layer_path))

    def import_job(self, job: Job, job_path):
        update_uris_if_needed(job, job_path)

        # Safely set result extents to prevent crashes from file access issues
        try:
            set_results_extents(job)
        except Exception as exc:
            log(
                f"Failed to set extents for imported job {job.id}: {type(exc).__name__}: {exc}"
            )

        self._move_job_to_dir(job, job.status, force_rewrite=True)

        # Handle special case where GENERATED_LOCALLY is tracked as DOWNLOADED in cache
        if job.status == jobs.JobStatus.GENERATED_LOCALLY:
            status = jobs.JobStatus.DOWNLOADED
        else:
            status = job.status

        log(f"job status is: {job.status}")
        log(f"emitting job {job.id}")
        self._set_known_job(status, job)
        self.imported_job.emit(job)

    def move_job_results(self, job: Job):
        """
        Move the datasets in results to the same folder as the job, where
        applicable.
        """
        if job.status not in (
            jobs.JobStatus.GENERATED_LOCALLY,
            jobs.JobStatus.DOWNLOADED,
        ):
            return

        job_path = self.get_job_file_path(job)
        moved_files = {}

        # Process each result in the job
        for result in job._get_results_list():
            if not hasattr(result, "uri") or not result.uri:
                continue

            results_uri = result.uri.uri
            if not results_uri:
                continue

            # Move main result file
            dest_path = Path(
                f"{job_path.parent}/{job_path.stem}_{result.name}{result.uri.uri.suffix}"
            ).resolve()
            if results_uri.exists() and not dest_path.exists():
                log(f"Updating results URI from {results_uri!s} to {dest_path!s}")
                target_path = shutil.copy(results_uri, dest_path)
                moved_files[results_uri] = target_path
                result.uri.uri = target_path

            # Result layers - type-specific handling
            uris = None

            if isinstance(result, RasterResults):
                uris = result.get_main_uris()
            elif isinstance(result, VectorResults):
                uris = [result.uri]
            elif hasattr(result, "other_uris"):
                uris = result.other_uris

            if uris:
                for uri in uris:
                    if not uri:
                        continue

                    # File had already been moved so just update the uri
                    if uri.uri in moved_files:
                        uri.uri = moved_files[uri.uri]
                        continue

                    # Copy the rest
                    new_path = Path(f"{job_path.parent}/{uri.uri.name}").resolve()
                    if uri.uri.exists() and not new_path.exists():
                        shutil.copy(uri.uri, new_path)
                        uri.uri = new_path
                    else:
                        uri.uri = None

        self._remove_job_metadata_file(job)
        self.write_job_metadata_file(job)

    def create_job_from_dataset(
        self,
        dataset_path: Path,
        band_name: str,
        band_metadata: typing.Dict,
        task_name: str,
        task_notes: str = "",
    ) -> Job:
        band_info = JobBand(
            name=band_name, no_data_value=-32768.0, metadata=band_metadata.copy()
        )

        # Mapping of LPD band names to productivity modes
        lpd_band_to_prod_mode = {
            ld_conf.JRC_LPD_BAND_NAME: ProductivityMode.JRC_5_CLASS_LPD.value,
            ld_conf.FAO_WOCAT_LPD_BAND_NAME: ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value,
            ld_conf.TE_LPD_BAND_NAME: ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value,
            ld_conf.CUSTOM_LPD_BAND_NAME: ProductivityMode.CUSTOM_5_CLASS_LPD.value,
        }

        # Determine script and params based on band name
        params = {}
        if band_name in ["Land cover", "Land cover (7 class)"]:
            script = conf.KNOWN_SCRIPTS["local-land-cover"]
        elif band_name == "Soil organic carbon":
            script = conf.KNOWN_SCRIPTS["local-soil-organic-carbon"]
        elif band_name in lpd_band_to_prod_mode:
            script = conf.KNOWN_SCRIPTS["productivity"]
            params["prod_mode"] = lpd_band_to_prod_mode[band_name]
        elif band_name == ld_conf.POPULATION_BAND_NAME:
            script = conf.KNOWN_SCRIPTS["sdg-15-3-1-sub-indicators"]
        else:
            raise RuntimeError(f"Invalid band name: {band_name!r}")
        now = dt.datetime.now(tz=dt.timezone.utc)
        rasters = {
            DataType.INT16.value: Raster(
                uri=URI(uri=dataset_path),
                bands=[band_info],
                datatype=DataType.INT16,
                filetype=RasterFileType.GEOTIFF,
                extent=_get_extent_tuple_raster(dataset_path),
            )
        }
        job = Job(
            id=uuid.uuid4(),
            params=params,
            progress=100,
            start_date=dt.datetime.now(dt.timezone.utc),
            status=jobs.JobStatus.GENERATED_LOCALLY,
            local_context=_get_local_context(),
            results=RasterResults(
                name=f"{band_name} results",
                rasters=rasters,
                uri=URI(uri=dataset_path),
            ),
            task_name=task_name,
            task_notes=task_notes,
            script=script,
            end_date=now,
        )

        return job

    def create_error_recode(self, task_name, lc, soil, prod, sdg):
        now = dt.datetime.now(dt.timezone.utc)
        job_id = uuid.uuid4()
        job = Job(
            id=job_id,
            params={},
            progress=100,
            start_date=now,
            status=jobs.JobStatus.GENERATED_LOCALLY,
            local_context=_get_local_context(),
            results=VectorResults(
                name="False positive/negative",
                vector=VectorFalsePositive(
                    uri=None,
                    type=VectorType.ERROR_RECODE,
                ),
                type=ResultType.VECTOR_RESULTS,
            ),
            script=ExecutionScript(
                id="sdg-15-3-1-error-recode",
                name="sdg-15-3-1-error-recode",
                run_mode=AlgorithmRunMode.LOCAL,
            ),
            task_name=task_name,
            task_notes="",
            end_date=now,
        )

        if prod:
            job.params["prod"] = {
                "path": str(prod.path),
                "band": prod.band_index,
                "band_name": prod.band_info.name,
                "uuid": str(prod.job.id),
            }

        if lc:
            job.params["lc"] = {
                "path": str(lc.path),
                "band": lc.band_index,
                "band_name": lc.band_info.name,
                "uuid": str(lc.job.id),
            }

        if soil:
            job.params["soil"] = {
                "path": str(soil.path),
                "band": soil.band_index,
                "band_name": soil.band_info.name,
                "uuid": str(soil.job.id),
            }
        if sdg:
            job.params["sdg"] = {
                "path": str(sdg.path),
                "band": sdg.band_index,
                "band_name": sdg.band_info.name,
                "uuid": str(sdg.job.id),
            }

        self._init_error_recode_layer(job)
        if not hasattr(job.results, "extent") or job.results.extent is None:
            # Safely set result extents to prevent crashes from file access issues
            try:
                set_results_extents(job)
            except Exception as exc:
                log(
                    f"Failed to set extents for job {job.id}: {type(exc).__name__}: {exc}"
                )
        self.write_job_metadata_file(job)
        # GENERATED_LOCALLY is tracked as DOWNLOADED in the internal cache
        self._set_known_job(jobs.JobStatus.DOWNLOADED, job)
        self.imported_job.emit(job)
        self.display_error_recode_layer(job)

        band_datas = [
            {
                "path": str(prod.path.as_posix()),
                "name": prod.band_info.name,
                "out_name": "land_productivity",
                "index": prod.band_index,
            },
            {
                "path": str(lc.path.as_posix()),
                "name": lc.band_info.name,
                "out_name": "land_cover",
                "index": lc.band_index,
            },
            {
                "path": str(soil.path.as_posix()),
                "name": soil.band_info.name,
                "out_name": "soil_organic_carbon",
                "index": soil.band_index,
            },
            {
                "path": str(sdg.path.as_posix()),
                "name": sdg.band_info.name,
                "out_name": "sdg",
                "index": sdg.band_index,
            },
        ]

        vector_result = job.get_first_result_by_type(VectorResults)
        if vector_result:
            layers.set_default_stats_value(str(vector_result.uri.uri), band_datas)
        self.edit_error_recode_layer(job)

    def get_vector_result_jobs(self) -> List[Job]:
        """
        Returns a list of jobs whose results are of type 'VectorResults'.
        """
        return [
            j
            for j in self.known_jobs[jobs.JobStatus.DOWNLOADED].values()
            if j.is_vector()
        ]

    def get_vector_result_job_by_id(self, job_id: str) -> Job:
        """
        Returns a vector results job by the job ID or None if not found.
        """
        vr_jobs = self.get_vector_result_jobs()
        m_jobs = [vrj for vrj in vr_jobs if str(vrj.id) == job_id]
        if len(m_jobs) > 0:
            return m_jobs[0]

        return None

    def _init_error_recode_layer(self, job: Job):
        output_path = self.get_job_file_path(job).with_suffix(".gpkg")
        output_dir = output_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        locale = QgsApplication.locale()
        path = os.path.join(
            os.path.dirname(__file__),
            os.path.pardir,
            "data",
            "error_recode",
            "error_recode_{}.gpkg".format(locale),
        )
        if os.path.exists(path):
            shutil.copy2(path, output_path)
        else:
            fallback = os.path.join(
                os.path.dirname(__file__),
                os.path.pardir,
                "data",
                "error_recode",
                "error_recode_en.gpkg",
            )
            shutil.copy2(fallback, output_path)
        # Set the vector.uri for error recode results
        job.results.vector.uri = URI(uri=output_path)
        vec_extent = _get_extent_tuple_vector(output_path)

        if vec_extent is not None:
            job.results.extent = vec_extent
        else:

            def _union(ext1, ext2):
                if ext1 is None:
                    return ext2
                if ext2 is None:
                    return ext1
                xmin = min(ext1[0], ext2[0])
                ymin = min(ext1[1], ext2[1])
                xmax = max(ext1[2], ext2[2])
                ymax = max(ext1[3], ext2[3])
                return (xmin, ymin, xmax, ymax)

            union_extent = None
            for key in ("prod", "lc", "soil", "sdg"):
                param = job.params.get(key)
                if param and param.get("path"):
                    try:
                        rext = _get_extent_tuple_raster(Path(param["path"]))
                    except Exception:
                        rext = None
                    union_extent = _union(union_extent, rext)

            job.results.extent = union_extent

    def _update_known_jobs_with_newly_submitted_job(self, job: Job):
        # Track jobs in their actual status - PENDING and RUNNING are different states.
        # Write to the *internal* dict (not the copy returned by known_jobs).
        self._set_known_job(job.status, job)

    def _change_job_status(
        self, job: Job, target: jobs.JobStatus, force_rewrite: bool = True
    ):
        """Modify a job's status both in the in-memory cache and on the filesystem"""
        previous_status = job.status

        # Handle special case where GENERATED_LOCALLY is treated as DOWNLOADED for cache management
        if previous_status == jobs.JobStatus.GENERATED_LOCALLY:
            previous_status = jobs.JobStatus.DOWNLOADED
        # this already sets the new status on the job
        self._move_job_to_dir(job, target, force_rewrite=force_rewrite)

        # Mutate the *internal* dicts directly (under the mutex) rather than
        # the read-only copies returned by the ``known_jobs`` property.
        self._state_update_mutex.lock()
        try:
            if target == jobs.JobStatus.DELETED:
                # Find which internal dictionary actually contains the job
                for status in list(jobs.JobStatus):
                    try:
                        internal = self._get_internal_dict_for_status(status)
                    except KeyError:
                        continue
                    if job.id in internal:
                        del internal[job.id]
                        break
            else:
                # Try the expected previous-status dict first.  If the caller
                # already mutated job.status before calling us (e.g.
                # LocalJobTask.finished sets FAILED before emitting the
                # signal), the job won't be in that dict.  Fall back to a full
                # search so we don't leave a stale entry behind.
                removed = False
                try:
                    prev_dict = self._get_internal_dict_for_status(previous_status)
                    if job.id in prev_dict:
                        del prev_dict[job.id]
                        removed = True
                except KeyError:
                    pass

                if not removed:
                    for status in list(jobs.JobStatus):
                        try:
                            d = self._get_internal_dict_for_status(status)
                        except KeyError:
                            continue
                        if job.id in d:
                            del d[job.id]
                            break

            # Handle GENERATED_LOCALLY -> DOWNLOADED mapping for cache storage
            cache_status = target
            if cache_status == jobs.JobStatus.GENERATED_LOCALLY:
                cache_status = jobs.JobStatus.DOWNLOADED
            self._get_internal_dict_for_status(cache_status)[job.id] = job
        finally:
            self._state_update_mutex.unlock()

    def _download_cloud_results(
        self, job: jobs.Job, raster_result: RasterResults
    ) -> typing.Optional[results.URI]:
        base_output_path = self.get_downloaded_dataset_base_file_path(job)
        # Add result name to base path to support multiple results
        result_base_path = (
            base_output_path.parent / f"{base_output_path.name}_{raster_result.name}"
        )

        out_rasters = {}

        if len([*raster_result.rasters.values()]) == 0:
            log(f"No rasters to download for {job.id} result {raster_result.name}")

        for key, raster in raster_result.rasters.items():
            file_out_base = f"{result_base_path.name}_{key}"

            if raster.type == results.RasterType.TILED_RASTER:
                tile_uris = []

                for uri_number, uri in enumerate(raster.tile_uris):
                    out_file = (
                        base_output_path.parent / f"{file_out_base}_{uri_number}.tif"
                    )
                    download_result = _download_result(
                        str(uri.uri),
                        base_output_path.parent / f"{file_out_base}_{uri_number}.tif",
                        expected_etag=_get_etag(uri),
                    )
                    if not download_result:
                        return None
                    tile_uris.append(results.URI(uri=out_file))

                raster.tile_uris = tile_uris

                vrt_file = base_output_path.parent / f"{file_out_base}.vrt"
                _get_raster_vrt(
                    tiles=[str(uri.uri) for uri in tile_uris],
                    out_file=vrt_file,
                )
                out_rasters[key] = results.TiledRaster(
                    tile_uris=tile_uris,
                    bands=raster.bands,
                    datatype=raster.datatype,
                    filetype=raster.filetype,
                    uri=results.URI(uri=vrt_file),
                    type=results.RasterType.TILED_RASTER,
                )
            else:
                out_file = base_output_path.parent / f"{file_out_base}.tif"
                download_result = _download_result(
                    str(raster.uri.uri),
                    out_file,
                    expected_etag=_get_etag(raster.uri),
                )
                if not download_result:
                    return None
                raster_uri = results.URI(uri=out_file)
                raster.uri = raster_uri
                out_rasters[key] = results.Raster(
                    uri=raster_uri,
                    bands=raster.bands,
                    datatype=raster.datatype,
                    filetype=raster.filetype,
                    type=results.RasterType.ONE_FILE_RASTER,
                )

        raster_result.rasters = out_rasters

        # Setup the main uri. This could be a vrt (if raster_result.rasters
        # has more than one Raster, or if it has one or more TiledRasters)

        if len(raster_result.rasters) > 1 or (
            len(raster_result.rasters) == 1
            and [*raster_result.rasters.values()][0].type
            == results.RasterType.TILED_RASTER
        ):
            vrt_file = base_output_path.parent / f"{result_base_path.name}.vrt"
            main_raster_file_paths = [raster.uri.uri for raster in out_rasters.values()]
            all_band_names = [
                b.metadata.get("gee_band_name") or b.name
                for raster in out_rasters.values()
                for b in raster.bands
            ]
            combine_all_bands_into_vrt(
                main_raster_file_paths, vrt_file, band_names=all_band_names
            )
            raster_result.uri = results.URI(uri=vrt_file)
        else:
            raster_result.uri = [*raster_result.rasters.values()][0].uri

        _set_results_extents_raster(raster_result, job)

        log(f"raster_result.uri in download function is {raster_result.uri!r}")
        return raster_result.uri

    def _download_vector_results(
        self, job: Job, vector_result: VectorResults
    ) -> typing.Optional[results.URI]:
        """Download vector results (GeoJSON, GeoPackage, etc.) from cloud storage."""
        if vector_result.uri is None or vector_result.uri.uri is None:
            log(
                f"No URI to download for vector result {vector_result.name} in job {job.id}"
            )
            return None

        source_uri = str(vector_result.uri.uri)

        # Check if this is already a local file (not a URL)
        if not source_uri.startswith(("http://", "https://", "/vsi")):
            # Already local, just return the existing URI
            log(f"Vector result {vector_result.name} already local: {source_uri}")
            return vector_result.uri

        base_output_path = self.get_downloaded_dataset_base_file_path(job)
        # Determine file extension from source URI
        if source_uri.endswith(".gpkg"):
            ext = ".gpkg"
        elif source_uri.endswith(".geojson"):
            ext = ".geojson"
        else:
            # Default to gpkg
            ext = ".gpkg"

        out_file = (
            base_output_path.parent
            / f"{base_output_path.name}_{vector_result.name}{ext}"
        )

        download_success = _download_result(
            source_uri, out_file, expected_etag=_get_etag(vector_result.uri)
        )
        if not download_success:
            log(
                f"Failed to download vector result {vector_result.name} for job {job.id}"
            )
            return None

        # Update the vector's URI to the downloaded file
        vector_result.vector.uri = results.URI(uri=out_file)

        _set_results_extents_vector(vector_result, job)

        log(f"vector_result.uri in download function is {vector_result.uri!r}")
        return vector_result.uri

    def _download_timeseries_table(
        self, job: Job, result: "results.TimeSeriesTableResult"
    ) -> typing.Optional[results.URI]:
        """
        Plot data already contained in the Job file as such no additional
        output file.
        """
        return None

    def _refresh_local_running_jobs(
        self,
        remote_jobs: typing.List[Job],
        remote_fetch_ok: bool = True,
        deferred_writes: typing.Optional[typing.List[Job]] = None,
    ) -> typing.Dict[uuid.UUID, Job]:
        """Update local directory of running jobs by comparing with the remote jobs.

        When *remote_fetch_ok* is ``False`` (the API call failed), we preserve
        all existing local running-job files instead of deleting them.  This
        prevents a transient server outage from wiping the user's job list.

        If *deferred_writes* is provided, job metadata writes are appended to
        the list instead of being performed immediately. The caller is
        responsible for flushing them after releasing the mutex.
        """
        local_running_jobs = self._get_local_jobs(jobs.JobStatus.RUNNING)
        self._known_running_jobs = {}

        if not remote_fetch_ok:
            # API was unreachable — keep every local running job as-is so the
            # user doesn't lose visibility of their in-progress work.
            log(
                f"Preserving {len(local_running_jobs)} local running job(s) "
                f"because the remote API was unreachable"
            )
            self._known_running_jobs = {j.id: j for j in local_running_jobs}
            return self._known_running_jobs

        # first go over all previously known jobs and check if they are still running

        for old_running_job in local_running_jobs:
            if _is_local_only_job(old_running_job):
                if _is_orphaned_local_job(old_running_job):
                    log(
                        f"Marking orphaned local job {old_running_job.id} as "
                        f"FAILED (owner PID "
                        f"{getattr(old_running_job.local_context, 'owner_pid', None)} "
                        f"is no longer running)"
                    )
                    if old_running_job.end_date is None:
                        old_running_job.end_date = dt.datetime.now(dt.timezone.utc)
                    self._change_job_status(old_running_job, jobs.JobStatus.FAILED)
                else:
                    self._known_running_jobs[old_running_job.id] = old_running_job
                continue

            remote_job = find_job(old_running_job, remote_jobs)

            if remote_job is None:  # unexpected behavior, remove the local job file
                self._remove_job_metadata_file(old_running_job)
                log(
                    f"Could not find job {old_running_job.id!r} on the remote server "
                    f"anymore. Deleting job metadata file from the base directory... "
                )
            elif remote_job.status == jobs.JobStatus.RUNNING:
                self._known_running_jobs[remote_job.id] = remote_job
                self.update_job_from_remote(
                    remote_job, old_running_job, deferred_writes=deferred_writes
                )
            else:  # job is not running anymore - maybe it is finished
                # Preserve params and metadata before removing file. The remote
                # API excludes params/task_name/task_notes to reduce bandwidth,
                # so we save them for later merging when the finished job data
                # is fetched and written to disk.
                self._preserve_job_data(old_running_job)
                self._remove_job_metadata_file(old_running_job)
        # now check for any new jobs (these might have been submitted by another client)
        known_running = [j.id for j in self._known_running_jobs.values()]

        # Build a lookup of local PENDING/READY jobs so we can restore their params
        # when they transition to RUNNING status
        local_pending_jobs = {
            j.id: j for j in self._get_local_jobs(jobs.JobStatus.PENDING)
        }
        local_ready_jobs = {j.id: j for j in self._get_local_jobs(jobs.JobStatus.READY)}

        for remote in remote_jobs:
            remote_running = remote.status == jobs.JobStatus.RUNNING

            if remote_running and remote.id not in known_running:
                log(
                    f"Found new remote job: {remote.id!r}. Adding it to local base "
                    f"directory..."
                )
                # Check if this job was previously PENDING/READY with data
                local_job = local_pending_jobs.get(remote.id) or local_ready_jobs.get(
                    remote.id
                )
                if local_job is not None:
                    # Preserve data from the old status before removing that file
                    self._preserve_job_data(local_job)
                    self._remove_job_metadata_file(local_job)
                # Restore preserved params and metadata
                self._restore_job_data(remote)
                self._known_running_jobs[remote.id] = remote
                if deferred_writes is not None:
                    deferred_writes.append(remote)
                else:
                    self.write_job_metadata_file(remote)

        return self._known_running_jobs

    def _refresh_local_finished_jobs(
        self,
        remote_jobs: typing.List[Job],
        prefetched_finished_jobs: typing.Optional[
            typing.Dict[uuid.UUID, typing.Optional[Job]]
        ] = None,
        deferred_writes: typing.Optional[typing.List[Job]] = None,
    ) -> typing.Dict[uuid.UUID, Job]:
        """Update in-memory cache with finished jobs.

        If *prefetched_finished_jobs* is provided, use pre-fetched full job
        data instead of making network calls.  This avoids blocking the
        mutex with HTTP requests.

        If *deferred_writes* is provided, file writes are appended to the
        list instead of being performed immediately.
        """
        if prefetched_finished_jobs is None:
            prefetched_finished_jobs = {}

        self._known_finished_jobs = {
            j.id: j for j in self._get_local_jobs(jobs.JobStatus.FINISHED)
        }
        local_ids = self._known_finished_jobs.keys()
        deleted_ids = self._known_deleted_jobs.keys()
        downloaded_ids = self._known_downloaded_jobs.keys()
        remote_finished = [
            j for j in remote_jobs if j.status == jobs.JobStatus.FINISHED
        ]

        for remote_job in remote_finished:
            if remote_job.id in deleted_ids:
                continue  # this job has previously been deleted by the user
            elif remote_job.id in downloaded_ids:
                continue  # this job has already been downloaded
            elif remote_job.id in local_ids:
                continue  # we already know about this job
            else:
                # Use pre-fetched data if available, otherwise fetch now
                # (fallback for callers that don't pre-fetch).
                if remote_job.id in prefetched_finished_jobs:
                    full_job = prefetched_finished_jobs[remote_job.id]
                else:
                    full_job = get_remote_job_with_results(remote_job.id)

                if full_job is not None:
                    # Restore preserved params and metadata (task_name, etc.)
                    self._restore_job_data(full_job)
                    self._known_finished_jobs[full_job.id] = full_job
                    if deferred_writes is not None:
                        deferred_writes.append(full_job)
                    else:
                        self.write_job_metadata_file(full_job)
                else:
                    # Fallback: store job without results - user can retry later
                    log(
                        f"Could not fetch results for job {remote_job.id}, storing minimal data"
                    )
                    # Restore preserved params and metadata for the fallback case
                    self._restore_job_data(remote_job)
                    self._known_finished_jobs[remote_job.id] = remote_job
                    if deferred_writes is not None:
                        deferred_writes.append(remote_job)
                    else:
                        self.write_job_metadata_file(remote_job)

        return self._known_finished_jobs

    def _refresh_local_downloaded_jobs(self):
        # Include both DOWNLOADED and GENERATED_LOCALLY jobs since they're stored in the same directory
        downloaded_jobs = self._get_local_jobs(jobs.JobStatus.DOWNLOADED)
        generated_locally_jobs = self._get_local_jobs(jobs.JobStatus.GENERATED_LOCALLY)
        self._known_downloaded_jobs = {
            j.id: j for j in downloaded_jobs + generated_locally_jobs
        }

    def _refresh_local_deleted_jobs(self):
        self._known_deleted_jobs = {
            j.id: j for j in self._get_local_jobs(jobs.JobStatus.DELETED)
        }

    def _move_job_to_dir(
        self, job: Job, new_status: jobs.JobStatus, force_rewrite: bool = False
    ):
        """Move job metadata file to another directory based on the desired status.

        This also mutates the input job, updating its current status to the new one.
        This also moves job metadata file

        """
        # Find the .qmd companion BEFORE removing/rewriting the JSON file,
        # and before job.status is potentially changed.  Use the directory-
        # search helper because job.status may already have been mutated by
        # the caller (e.g. LocalJobTask.finished sets CANCELLED/FAILED
        # before the signal reaches us).
        old_qmd_path = self._find_job_file_in_all_dirs(job, ".qmd")

        log(f"moving job {job.id} to dir")

        if job.status != new_status:  # always write
            self._remove_job_metadata_file(job)
            job.status = new_status
            self.write_job_metadata_file(job)
        else:
            if force_rewrite:
                self._remove_job_metadata_file(job)
                job.status = new_status
                self.write_job_metadata_file(job)
            else:
                log("No need to move the job file, it is already in place")

        if old_qmd_path is not None and old_qmd_path.exists():
            new_path = os.path.splitext(self.get_job_file_path(job))[0] + ".qmd"
            shutil.move(str(old_qmd_path), new_path)

    # @functools.lru_cache(maxsize=None)  # not using functools.cache, as it was only introduced in Python 3.9
    def _load_jobs_from_dir(
        self, base_dir: Path
    ) -> typing.Dict[jobs.JobStatus, typing.List[Job]]:
        """Scan *base_dir* once and return all valid jobs grouped by status."""
        grouped: typing.Dict[jobs.JobStatus, typing.List[Job]] = {}

        if not base_dir.exists() or not base_dir.is_dir():
            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                log(f"Base directory does not exist or is not accessible: {base_dir}")
            return grouped

        try:
            job_paths = list(base_dir.glob("**/*.json"))
        except (OSError, PermissionError, RuntimeError) as exc:
            log(f"Error scanning directory {base_dir}: {type(exc).__name__}: {exc}")
            return grouped
        except Exception as exc:
            log(
                f"Unexpected error scanning directory {base_dir}: {type(exc).__name__}: {exc}"
            )
            return grouped

        schema = _get_job_schema()

        for job_metadata_path in job_paths:
            try:
                # Check file mtime for cache validity
                try:
                    file_mtime = job_metadata_path.stat().st_mtime
                except (OSError, IOError) as exc:
                    if conf.settings_manager.get_value(conf.Setting.DEBUG):
                        log(f"Cannot stat file {job_metadata_path!r}: {exc}")
                    continue

                # Check SQLite cache (persists across QGIS restarts)
                if self._job_cache.is_failed_file(job_metadata_path, file_mtime):
                    # Skip known-bad files until they change
                    continue

                cached_job = self._job_cache.get_cached_job(
                    job_metadata_path,
                    file_mtime,
                    load_params=False,
                    load_results=False,
                )
                if cached_job is not None:
                    grouped.setdefault(cached_job.status, []).append(cached_job)
                    continue

                # File is new or changed - need to parse it
                try:
                    if not self._is_json_file_safe(job_metadata_path):
                        self._job_cache.cache_job(job_metadata_path, file_mtime, None)
                        if conf.settings_manager.get_value(conf.Setting.DEBUG):
                            log(
                                f"Skipping unsafe or corrupted file {job_metadata_path!r}"
                            )
                        continue
                except Exception as exc:
                    self._job_cache.cache_job(job_metadata_path, file_mtime, None)
                    log(
                        f"Error checking safety of file {job_metadata_path!r}: {type(exc).__name__}: {exc}"
                    )
                    continue

                try:
                    with job_metadata_path.open(encoding=self._encoding) as fh:
                        raw_job = json.load(fh)

                    if not isinstance(raw_job, dict):
                        self._job_cache.cache_job(job_metadata_path, file_mtime, None)
                        if conf.settings_manager.get_value(conf.Setting.DEBUG):
                            log(
                                f"File {job_metadata_path!r} does not contain a valid JSON object"
                            )
                        continue

                    job = schema.load(raw_job)

                    extents_changed = False
                    try:
                        if job.status in (
                            jobs.JobStatus.DOWNLOADED,
                            jobs.JobStatus.GENERATED_LOCALLY,
                        ):
                            extents_changed = _set_results_extents_if_missing(job)
                        else:
                            set_results_extents(job)
                    except (OSError, IOError, RuntimeError, MemoryError) as exc:
                        log(
                            f"Failed to set extents for job {job.id} during loading: {type(exc).__name__}: {exc}"
                        )
                    except Exception as exc:
                        log(
                            f"Unexpected error setting extents for job {job.id}: {type(exc).__name__}: {exc}"
                        )

                    if extents_changed:
                        try:
                            self.write_job_metadata_file(job)
                            # Update mtime after writing
                            file_mtime = job_metadata_path.stat().st_mtime
                        except Exception as exc:
                            log(
                                f"Failed to persist extents for job {job.id}: {type(exc).__name__}: {exc}"
                            )

                    # Update SQLite cache with parsed job
                    self._job_cache.cache_job(job_metadata_path, file_mtime, job)
                    grouped.setdefault(job.status, []).append(job)
                except (OSError, IOError, PermissionError) as exc:
                    self._job_cache.cache_job(job_metadata_path, file_mtime, None)
                    if conf.settings_manager.get_value(conf.Setting.DEBUG):
                        log(f"Failed to read file {job_metadata_path!r}: {exc}")
                except (KeyError, json.decoder.JSONDecodeError) as exc:
                    self._job_cache.cache_job(job_metadata_path, file_mtime, None)
                    if conf.settings_manager.get_value(conf.Setting.DEBUG):
                        log(
                            f"Unable to decode file {job_metadata_path!r} as valid json: {exc}"
                        )
                except ValidationError as exc:
                    self._job_cache.cache_job(job_metadata_path, file_mtime, None)
                    if conf.settings_manager.get_value(conf.Setting.DEBUG):
                        log(
                            f"Unable to decode file {job_metadata_path!r} - validation error: {exc}"
                        )
                except (ValueError, TypeError, AttributeError, MemoryError) as exc:
                    self._job_cache.cache_job(job_metadata_path, file_mtime, None)
                    log(
                        f"Error processing file {job_metadata_path!r}: {type(exc).__name__}: {exc}"
                    )
                except RuntimeError as exc:
                    self._job_cache.cache_job(job_metadata_path, file_mtime, None)
                    log(f"Runtime error processing file {job_metadata_path!r}: {exc}")
            except (OSError, IOError, PermissionError) as exc:
                log(f"File system error accessing {job_metadata_path!r}: {exc}")
            except Exception as exc:
                log(
                    f"Unexpected error processing {job_metadata_path!r}: {type(exc).__name__}: {exc}"
                )

        return grouped

    def _get_local_jobs(self, status: jobs.JobStatus) -> typing.List[Job]:
        """Return local jobs with the given *status*."""
        base_dir = {
            jobs.JobStatus.FINISHED: self.finished_jobs_dir,
            jobs.JobStatus.FAILED: self.failed_jobs_dir,
            jobs.JobStatus.RUNNING: self.running_jobs_dir,
            jobs.JobStatus.PENDING: self.running_jobs_dir,
            jobs.JobStatus.READY: self.running_jobs_dir,
            jobs.JobStatus.CANCELLED: self.failed_jobs_dir,
            jobs.JobStatus.DELETED: self.deleted_jobs_dir,
            jobs.JobStatus.EXPIRED: self.expired_jobs_dir,
            jobs.JobStatus.DOWNLOADED: self.datasets_dir,
            jobs.JobStatus.GENERATED_LOCALLY: self.datasets_dir,
        }[status]

        if base_dir not in self._dir_job_cache:
            self._dir_job_cache[base_dir] = self._load_jobs_from_dir(base_dir)

        return list(self._dir_job_cache[base_dir].get(status, []))

    def _get_local_finished_jobs(self) -> typing.Dict[uuid.UUID, Job]:
        """Synchronize the in-memory cache and filesystem with regard to finished jobs.

        This method takes care of checking the local filesystem directory for relevant
        finished jobs and updates the in-memory cache. Relevant finished jobs are those
        which can still be downloaded by the user.

        The remote server is expected to only keep execution results for a certain
        amount of time. As such, if the results are not downloaded within that time
        frame, they will be lost. As such, this also method ensures that any job
        metadata files which correspond to these no longer available job results get
        deleted from disk, in order to avoid showing the user download options that are
        expected to fail.
        """

        def is_naive(d):
            return d.tzinfo is None or d.tzinfo.utcoffset(d) is None

        now = dt.datetime.now(tz=dt.timezone.utc)

        self._known_finished_jobs = {}

        for finished_job in self._get_local_jobs(jobs.JobStatus.FINISHED):
            if finished_job.end_date:
                job_age = now - finished_job.end_date

                if job_age.days > self._relevant_job_age_threshold_days:
                    if conf.settings_manager.get_value(conf.Setting.DEBUG):
                        log(
                            f"Transitioning job {finished_job.id!r} to EXPIRED status "
                            f"as it is no longer possible to download its results..."
                        )
                    self._change_job_status(
                        finished_job, jobs.JobStatus.EXPIRED, force_rewrite=True
                    )
                else:
                    self._known_finished_jobs[finished_job.id] = finished_job

        return self._known_finished_jobs

    def _get_local_failed_jobs(self) -> typing.Dict[uuid.UUID, Job]:
        """Synchronize the in-memory cache and filesystem with regard to failed jobs.

        This method takes care of checking the local filesystem directory for relevant
        failed jobs and updates the in-memory cache. Relevant failed jobs are those
        that still appear on the server.

        The remote server is expected to only keep execution results for a certain
        amount of time.  As such, this also method ensures that any job
        metadata files which correspond to these no longer available job results get
        deleted from disk.
        """

        now = dt.datetime.now(tz=dt.timezone.utc)
        self._known_failed_jobs = {}

        for failed_job in self._get_local_jobs(jobs.JobStatus.FAILED):
            job_age = now - failed_job.end_date

            if job_age.days > self._relevant_job_age_threshold_days:
                log(f"Removing job {failed_job.id} as it is no longer on server")
                self._remove_job_metadata_file(failed_job)
            else:
                self._known_failed_jobs[failed_job.id] = failed_job

        return self._known_failed_jobs

    def _get_local_expired_jobs(self) -> typing.Dict[uuid.UUID, Job]:
        """Synchronize the in-memory cache and filesystem with regard to expired jobs.

        This method takes care of checking the local filesystem directory for expired
        jobs and updates the in-memory cache. Expired jobs are kept for historical
        purposes and to show users what jobs have expired.
        """

        self._known_expired_jobs = {
            j.id: j for j in self._get_local_jobs(jobs.JobStatus.EXPIRED)
        }

        return self._known_expired_jobs

    def get_job_file_path(self, job: Job) -> Path:
        if job.status in (
            jobs.JobStatus.RUNNING,
            jobs.JobStatus.PENDING,
            jobs.JobStatus.READY,
        ):
            base = self.running_jobs_dir / f"{job.get_basename(with_uuid=True)}.json"
        elif job.status in (jobs.JobStatus.FAILED, jobs.JobStatus.CANCELLED):
            base = self.failed_jobs_dir / f"{job.get_basename(with_uuid=True)}.json"
        elif job.status == jobs.JobStatus.FINISHED:
            base = self.finished_jobs_dir / f"{job.get_basename(with_uuid=True)}.json"
        elif job.status == jobs.JobStatus.EXPIRED:
            base = self.expired_jobs_dir / f"{job.get_basename(with_uuid=True)}.json"
        elif job.status == jobs.JobStatus.DELETED:
            base = self.deleted_jobs_dir / f"{job.get_basename(with_uuid=True)}.json"
        elif job.status in (
            jobs.JobStatus.DOWNLOADED,
            jobs.JobStatus.GENERATED_LOCALLY,
        ):
            base = self.datasets_dir / f"{job.id!s}" / f"{job.get_basename()}.json"
        else:
            raise RuntimeError(
                f"Could not retrieve file path for job with state {job.status}"
            )

        return base

    def get_downloaded_dataset_base_file_path(self, job: Job):
        base = self.datasets_dir

        return base / f"{job.id!s}" / f"{job.get_basename()}"

    def write_job_metadata_file(self, job: Job):
        self.ensure_params_loaded(job)
        self.ensure_results_loaded(job)
        output_path = self.get_job_file_path(job)
        output_dir = output_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding=self._encoding) as fh:
            raw_job = _get_job_schema().dump(job)
            json.dump(raw_job, fh, indent=2)
        # Invalidate cache for this directory so subsequent _get_local_jobs
        # calls within the same refresh cycle see the updated file.
        self._invalidate_dir_cache_for_path(output_path)

    def update_job_from_remote(
        self,
        remote_job: Job,
        local_job: typing.Optional[Job],
        deferred_writes: typing.Optional[typing.List[Job]] = None,
    ):
        """Update job metadata file from remote, preserving local data.

        When syncing with the server, we exclude params, task_name, task_notes,
        and local_context from the API response to reduce payload size. This
        method merges remote updates (status, progress) with locally-stored
        data before writing. For RUNNING jobs, results aren't available yet
        so excluding them is fine.

        Args:
            remote_job: Job data from API (may have empty params and no results)
            local_job: Existing local job data, or None if not found locally
            deferred_writes: If provided, append job instead of writing immediately
        """
        if local_job is not None:
            # Remote response excluded params - preserve the local ones
            if not remote_job.params and local_job.params:
                remote_job.params = local_job.params
            # Also preserve task_name, task_notes, and local_context
            if not remote_job.task_name and local_job.task_name:
                remote_job.task_name = local_job.task_name
            if not remote_job.task_notes and local_job.task_notes:
                remote_job.task_notes = local_job.task_notes
            # Preserve local_context if local has meaningful data
            if (
                local_job.local_context
                and local_job.local_context.area_of_interest_name
                and local_job.local_context.area_of_interest_name != "unknown-area"
            ):
                remote_job.local_context = local_job.local_context
        if deferred_writes is not None:
            deferred_writes.append(remote_job)
        else:
            self.write_job_metadata_file(remote_job)

    def _find_job_file_in_all_dirs(
        self, job: Job, suffix: str = ".json"
    ) -> typing.Optional[Path]:
        """Find the actual file for a job by searching all status directories.

        When ``job.status`` has been mutated before the on-disk file was moved,
        ``get_job_file_path`` points to the wrong directory.  This helper
        searches every status directory so the real file is always found.
        """
        # Try expected location first (fast path)
        expected = self.get_job_file_path(job)
        if suffix != ".json":
            expected = expected.with_suffix(suffix)
        if expected.exists():
            return expected

        # Search flat status directories (files use with_uuid=True naming)
        filename = f"{job.get_basename(with_uuid=True)}{suffix}"
        for search_dir in (
            self.running_jobs_dir,
            self.failed_jobs_dir,
            self.finished_jobs_dir,
            self.expired_jobs_dir,
            self.deleted_jobs_dir,
        ):
            candidate = search_dir / filename
            if candidate.exists():
                return candidate

        # Datasets dir uses a different naming convention (no UUID suffix)
        ds_filename = f"{job.get_basename()}{suffix}"
        ds_candidate = self.datasets_dir / f"{job.id!s}" / ds_filename
        if ds_candidate.exists():
            return ds_candidate

        return None

    def _remove_job_metadata_file(self, job: Job):
        old_path = self._find_job_file_in_all_dirs(job, ".json")

        if old_path is not None:
            old_path.unlink()
            # Invalidate cache for this directory so subsequent _get_local_jobs
            # calls within the same refresh cycle don't return stale entries.
            self._invalidate_dir_cache_for_path(old_path)

    def _invalidate_dir_cache_for_path(self, file_path: Path):
        """Remove cached directory scan results for *file_path*.

        The directory cache is keyed by base directory (e.g. ``running_jobs_dir``,
        ``datasets_dir``).  For most statuses the file sits directly inside
        the base directory, so ``file_path.parent`` matches the cache key.
        For DOWNLOADED / GENERATED_LOCALLY the file is one level deeper
        (``datasets_dir/{job_id}/file.json``), so we also check the
        grandparent.
        """
        self._dir_job_cache.pop(file_path.parent, None)
        if file_path.parent != file_path.parent.parent:
            self._dir_job_cache.pop(file_path.parent.parent, None)

    def _refresh_remote_jobs_by_status(
        self,
        remote_jobs: typing.List[Job],
        deferred_writes: typing.Optional[typing.List[Job]] = None,
    ) -> None:
        """Update in-memory cache with READY, PENDING, and CANCELLED jobs from remote server"""
        # Preserve existing local jobs first, then merge with remote
        # This prevents newly submitted jobs from disappearing during refresh

        # Start with existing local jobs for each status
        local_ready_jobs = self._get_local_jobs(jobs.JobStatus.READY)
        local_pending_jobs = self._get_local_jobs(jobs.JobStatus.PENDING)
        local_cancelled_jobs = self._get_local_jobs(jobs.JobStatus.CANCELLED)

        # Initialize caches with existing local jobs
        self._known_ready_jobs = {j.id: j for j in local_ready_jobs}
        self._known_pending_jobs = {j.id: j for j in local_pending_jobs}
        self._known_cancelled_jobs = {j.id: j for j in local_cancelled_jobs}

        # Process remote jobs and merge/update
        remote_ids_by_status = {
            jobs.JobStatus.READY: set(),
            jobs.JobStatus.PENDING: set(),
            jobs.JobStatus.CANCELLED: set(),
        }

        for remote_job in remote_jobs:
            if remote_job.status == jobs.JobStatus.READY:
                # Restore preserved params and metadata if available
                self._restore_job_data(remote_job)
                # Persist to disk if we restored data
                if remote_job.params or remote_job.task_name:
                    if deferred_writes is not None:
                        deferred_writes.append(remote_job)
                    else:
                        self.write_job_metadata_file(remote_job)
                self._known_ready_jobs[remote_job.id] = remote_job
                remote_ids_by_status[jobs.JobStatus.READY].add(remote_job.id)
            elif remote_job.status == jobs.JobStatus.PENDING:
                # Restore preserved params and metadata if available
                self._restore_job_data(remote_job)
                # Persist to disk if we restored data
                if remote_job.params or remote_job.task_name:
                    if deferred_writes is not None:
                        deferred_writes.append(remote_job)
                    else:
                        self.write_job_metadata_file(remote_job)
                self._known_pending_jobs[remote_job.id] = remote_job
                remote_ids_by_status[jobs.JobStatus.PENDING].add(remote_job.id)
            elif remote_job.status == jobs.JobStatus.CANCELLED:
                # Restore preserved params and metadata if available
                self._restore_job_data(remote_job)
                # Persist to disk if we restored data
                if remote_job.params or remote_job.task_name:
                    if deferred_writes is not None:
                        deferred_writes.append(remote_job)
                    else:
                        self.write_job_metadata_file(remote_job)
                self._known_cancelled_jobs[remote_job.id] = remote_job
                remote_ids_by_status[jobs.JobStatus.CANCELLED].add(remote_job.id)

        # Only remove local jobs if they appear in the remote list with a different status
        # This indicates they've actually changed status remotely
        all_remote_job_ids = {job.id for job in remote_jobs}

        for local_job in local_ready_jobs:
            if (
                local_job.id in all_remote_job_ids
                and local_job.id not in remote_ids_by_status[jobs.JobStatus.READY]
            ):
                # Job exists remotely but with different status - it has changed
                # Preserve params and metadata before removing file
                self._preserve_job_data(local_job)
                if local_job.id in self._known_ready_jobs:
                    del self._known_ready_jobs[local_job.id]
                    self._remove_job_metadata_file(local_job)

        for local_job in local_pending_jobs:
            if (
                local_job.id in all_remote_job_ids
                and local_job.id not in remote_ids_by_status[jobs.JobStatus.PENDING]
            ):
                # Job exists remotely but with different status - it has changed
                # Preserve params and metadata before removing file
                self._preserve_job_data(local_job)
                if local_job.id in self._known_pending_jobs:
                    del self._known_pending_jobs[local_job.id]
                    self._remove_job_metadata_file(local_job)

        for local_job in local_cancelled_jobs:
            if (
                local_job.id in all_remote_job_ids
                and local_job.id not in remote_ids_by_status[jobs.JobStatus.CANCELLED]
            ):
                # Job exists remotely but with different status - it has changed
                # Preserve params and metadata before removing file
                self._preserve_job_data(local_job)
                if local_job.id in self._known_cancelled_jobs:
                    del self._known_cancelled_jobs[local_job.id]
                    self._remove_job_metadata_file(local_job)

    def _refresh_remote_failed_jobs(
        self,
        remote_jobs: typing.List[Job],
        deferred_writes: typing.Optional[typing.List[Job]] = None,
    ) -> None:
        """Update in-memory cache with FAILED jobs from remote server"""
        # Start with local failed jobs from disk
        self._known_failed_jobs = {
            j.id: j for j in self._get_local_jobs(jobs.JobStatus.FAILED)
        }
        local_ids = self._known_failed_jobs.keys()
        deleted_ids = self._known_deleted_jobs.keys()
        remote_failed = [j for j in remote_jobs if j.status == jobs.JobStatus.FAILED]

        for remote_job in remote_failed:
            if remote_job.id in deleted_ids:
                continue  # this job has previously been deleted by the user
            elif remote_job.id in local_ids:
                continue  # we already know about this job
            else:
                # this is a new failed job that we are interested in
                # Restore preserved params and metadata (task_name, etc.)
                self._restore_job_data(remote_job)
                self._known_failed_jobs[remote_job.id] = remote_job
                if deferred_writes is not None:
                    deferred_writes.append(remote_job)
                else:
                    self.write_job_metadata_file(remote_job)


def _get_local_job_output_paths(job: Job) -> typing.Tuple[Path, Path]:
    """Retrieve output path for a job so that it can be sent to the local processor.

    Computes the target filepath without mutating the job's status, which avoids
    a data race when background threads observe the job in an inconsistent state.
    """
    # Compute the path that get_job_file_path would return for GENERATED_LOCALLY
    job_output_path = (
        job_manager.datasets_dir / f"{job.id!s}" / f"{job.get_basename()}.json"
    )
    job_output_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_output_path = job_output_path.parent / f"{job_output_path.stem}.tif"

    return job_output_path, dataset_output_path


def _get_local_context() -> str:
    return jobs.JobLocalContext(
        base_dir=conf.settings_manager.get_value(conf.Setting.BASE_DIR),
        area_of_interest_name=conf.settings_manager.get_value(conf.Setting.AREA_NAME),
    )


def find_job(target: Job, source: typing.List[Job]) -> typing.Optional[Job]:
    try:
        result = [j for j in source if j.id == target.id][0]
    except IndexError:
        log(f"Could not find job {target.id!r} on the list of jobs")
        result = None

    return result


def _is_local_only_job(job: Job) -> bool:
    """Return True if *job* was submitted for local execution only."""
    script = getattr(job, "script", None)
    if script is None:
        return False
    run_mode = getattr(script, "run_mode", None)
    if run_mode == AlgorithmRunMode.LOCAL:
        return True
    # Fallback: if the script has a local execution_callable it is local
    execution_callable = getattr(script, "execution_callable", None)
    return bool(execution_callable)


def _is_orphaned_local_job(job: Job) -> bool:
    """Return True if a local-only RUNNING job's owning process is dead.

    Jobs created before ``owner_pid`` was introduced will have
    ``owner_pid=None``.  In that case we cannot determine liveness, so we
    conservatively return False (keep the job as RUNNING and let the user
    delete it manually).
    """
    ctx = getattr(job, "local_context", None)
    if ctx is None:
        return False
    owner_pid = getattr(ctx, "owner_pid", None)
    if owner_pid is None:
        return False
    return not _is_pid_alive(owner_pid)


def _get_access_token():
    login_reply = job_manager.api_client.login()

    if isinstance(login_reply, str) and login_reply:
        # Token-based authentication - login() returns the token directly
        return login_reply
    else:
        # Authentication failed
        return None


def _get_user_id() -> typing.Optional[uuid.UUID]:
    # First try to get cached user ID from settings
    cached_user_id = conf.settings_manager.get_value(conf.Setting.USER_ID)
    if cached_user_id:
        try:
            user_id = uuid.UUID(cached_user_id)
            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                log(f"Using cached user ID: {user_id}")
            return user_id
        except (ValueError, TypeError) as e:
            log(f"Invalid cached user ID, fetching from server: {e}")

    # Fallback to API call if no cached ID or invalid cached ID
    if conf.settings_manager.get_value(conf.Setting.DEBUG):
        log("Retrieving user id from server...")

    get_user_reply = job_manager.api_client.get_user()

    if get_user_reply:
        user_id_str = get_user_reply.get("id", None)
        if user_id_str:
            try:
                user_id = uuid.UUID(user_id_str)
                # Cache the user ID for future use
                conf.settings_manager.write_value(conf.Setting.USER_ID, user_id_str)
                if conf.settings_manager.get_value(conf.Setting.DEBUG):
                    log(f"Retrieved and cached user ID: {user_id}")
                return user_id
            except ValueError as e:
                log(f"Invalid user ID format from server: {e}")

    return None


def _get_raster_vrt(tiles: List[Path], out_file: Path):
    ds = gdal.BuildVRT(str(out_file), [str(tile) for tile in tiles])
    if ds is not None:
        ds.FlushCache()
    ds = None


def backoff_hdlr(details):
    log(
        "Backing off {wait:0.1f} seconds after {tries} tries "
        "calling function {target}".format(**details)
    )


@backoff.on_predicate(
    backoff.expo, lambda x: x is None, max_tries=5, on_backoff=backoff_hdlr
)
def _download_result(
    url: str,
    output_path: Path,
    expected_etag: typing.Optional[results.Etag] = None,
) -> bool:
    """Download a file and optionally verify its hash against an expected etag.

    Args:
        url: URL to download from
        output_path: Local path to save the file
        expected_etag: Optional Etag object to verify file integrity. Supports
            AWS MD5, AWS multipart, GCS MD5, and GCS CRC32C etag types.

    Returns:
        True if download succeeded and hash verified (if provided), False otherwise.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    download_worker = ldmp_download.Download(url, str(output_path))
    download_worker.start()
    result = bool(download_worker.get_resp())

    if not result:
        output_path.unlink(missing_ok=True)
        return result

    # Verify file integrity if etag was provided
    if result and expected_etag is not None:
        if not ldmp_download.verify_file_against_etag(output_path, expected_etag):
            log(f"File verification failed for {output_path}, deleting...")
            output_path.unlink(missing_ok=True)
            return False

    return result


def _delete_job_datasets(job: Job):
    if job.results is not None:
        try:
            path = os.path.split(job_manager.get_job_file_path(job))[0]
            shutil.rmtree(path)
        except OSError:
            log(f"Could not remove directory {path!r}, skipping deletion...")
    else:
        log("This job has no results to be deleted, skipping...")


def get_remote_jobs(
    end_date: typing.Optional[dt.datetime] = None,
) -> typing.Optional[typing.List[Job]]:
    """Get a list of remote jobs, as returned by the server.

    Returns ``None`` when the API could not be reached (auth failure, network
    error, etc.).  Returns an empty list ``[]`` when the API responded
    successfully but there are genuinely no matching jobs.  Callers **must**
    check for ``None`` to avoid treating an API outage as "all jobs deleted".
    """
    # Note - this is a reimplementation of api.get_execution
    user_id = _get_user_id()
    if user_id is None:
        log("Cannot fetch remote jobs: user ID unavailable (auth may have failed)")
        return None

    # Request script info but exclude large params and results fields to reduce
    # response size. The params field can be very large (megabytes) due to geojson
    # geometries, land cover matrices, etc. Results can also be large and are only
    # needed when downloading a completed job. Full job data (with results) is
    # fetched on-demand when a job transitions to FINISHED status.
    query = {"include": "script", "exclude": "params,results"}

    if end_date is not None:
        query["updated_at"] = end_date.strftime("%Y-%m-%d")

    if conf.settings_manager.get_value(conf.Setting.DEBUG):
        log("Retrieving executions...")

    # Use pagination to fetch all results. The API returns up to 100 per page
    # when page/per_page are explicitly provided.
    page = 1
    per_page = 100
    raw_jobs = []

    while True:
        paginated_query = dict(query, page=page, per_page=per_page)
        response = job_manager.api_client.call_api(
            f"/api/v1/execution/user?{urllib.parse.urlencode(paginated_query)}",
            method="get",
            use_token=True,
        )

        if not response:
            if page == 1:
                log("No response from server on first page — treating as API failure")
                return None
            else:
                # We already have some results from earlier pages
                break

        try:
            page_data = response["data"]
            raw_jobs.extend(page_data)

            # Check if there are more pages
            total = response.get("total")
            if total is not None and len(raw_jobs) >= total:
                break

            # If this page returned fewer items than per_page, we're done
            if len(page_data) < per_page:
                break

            page += 1
        except (TypeError, KeyError):
            if page == 1:
                log("Invalid response format on first page — treating as API failure")
                return None
            else:
                break

    log(f"API returned {len(raw_jobs)} executions across {page} page(s)")

    remote_jobs = []
    schema = _get_job_schema()
    log(f"Processing {len(raw_jobs)} raw jobs from API response")
    for raw_job in raw_jobs:
        try:
            # Fill in empty dict/None for excluded fields to satisfy schema.
            # Both params and results are excluded from API response to reduce
            # payload size. The Job schema expects params to exist for pre_load.
            # Results are fetched on-demand when jobs transition to FINISHED.
            if "params" not in raw_job or raw_job["params"] is None:
                raw_job["params"] = {}
            if "results" not in raw_job:
                raw_job["results"] = None

            job = schema.load(raw_job)
            job.script.run_mode = AlgorithmRunMode.REMOTE

            if job is not None:
                remote_jobs.append(job)
        except ValidationError as exc:
            log(
                f"Could not retrieve remote job {raw_job.get('id', 'unknown')}: {str(exc)}"
            )
            log(f"Raw job data keys: {list(raw_job.keys())}")
        except RuntimeError as exc:
            log(str(exc))
        except TypeError as exc:
            log(f"Could not retrieve remote job {raw_job['id']}: {str(exc)}")

    log(f"Successfully processed {len(remote_jobs)} out of {len(raw_jobs)} remote jobs")
    return remote_jobs


def get_remote_job_with_results(job_id: uuid.UUID) -> typing.Optional[Job]:
    """Fetch a single job from the API with results for downloading.

    This is used when a job transitions to FINISHED status and we need
    the results data (download URLs) for downloading. The lightweight job list
    from get_remote_jobs() excludes results to reduce bandwidth.

    Params are excluded as they can be very large and aren't needed for
    downloading - we only need the results URLs.

    Args:
        job_id: The UUID of the job to fetch

    Returns:
        Job with results, or None if fetch failed
    """
    log(f"Fetching job results for {job_id}")

    response = job_manager.api_client.call_api(
        f"/api/v1/execution/{job_id}?exclude=params",
        method="get",
        use_token=True,
    )

    if not response:
        log(f"Failed to fetch job {job_id} from API")
        return None

    try:
        raw_job = response["data"]
        # Ensure params dict exists for schema (excluded from response)
        if "params" not in raw_job or raw_job["params"] is None:
            raw_job["params"] = {}

        schema = _get_job_schema()
        job = schema.load(raw_job)
        job.script.run_mode = AlgorithmRunMode.REMOTE
        log(f"Successfully fetched job results for {job_id}")
        return job
    except (ValidationError, KeyError, TypeError) as exc:
        log(f"Failed to parse job {job_id}: {exc}")
        return None


def get_relevant_remote_jobs(remote_jobs: typing.List[Job]) -> typing.List[Job]:
    """Filter a list of jobs gotten from the remote server for relevant jobs.

    Relevant jobs are those whose ``local_context.base_dir`` matches the
    current base dir.  The comparison normalises paths (resolves separators,
    trailing slashes, and uses case-insensitive matching on Windows) to avoid
    false negatives from cosmetic path differences.
    """

    current_base_dir = conf.settings_manager.get_value(conf.Setting.BASE_DIR)
    result = []

    try:
        normalised_base = Path(current_base_dir).resolve()
    except (TypeError, ValueError):
        log(f"Cannot normalise current base_dir {current_base_dir!r}")
        return remote_jobs  # safe fallback: don't filter

    for job in remote_jobs:
        job_base = job.local_context.base_dir

        if job_base is None:
            # Jobs without a local_context (submitted by another client or
            # older API version) are included so they aren't silently hidden.
            result.append(job)
            continue

        try:
            normalised_job = Path(str(job_base)).resolve()
        except (TypeError, ValueError):
            # Unparseable path — include the job to be safe.
            result.append(job)
            continue

        # On Windows paths are case-insensitive; on POSIX they are not.
        if os.name == "nt":
            match = str(normalised_job).lower() == str(normalised_base).lower()
        else:
            match = normalised_job == normalised_base

        if match:
            result.append(job)

    return result


job_manager = JobManager()
