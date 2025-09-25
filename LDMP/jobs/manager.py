import datetime as dt
import json
import logging
import os
import re
import shutil
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
from qgis.core import Qgis, QgsApplication, QgsTask, QgsVectorLayer
from qgis.gui import QgsMessageBar
from qgis.PyQt import QtCore
from qgis.PyQt.QtWidgets import QProgressBar, QPushButton
from qgis.utils import iface
from te_algorithms.gdal.util import combine_all_bands_into_vrt
from te_schemas import jobs, results
from te_schemas.algorithms import AlgorithmRunMode
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
from ..constants import API_URL, TIMEOUT
from ..logger import log
from . import models
from .models import Job

logger = logging.getLogger(__name__)


class tr_manager:
    def tr(message):
        return QtCore.QCoreApplication.translate("tr_manager", message)


def is_gdal_vsi_path(path: Path):
    return re.match(r"(\\)|(/)vsi(s3)|(gs)", str(path)) is not None


def update_uris_if_needed(job: Job, job_path):
    "Update uris stored in a job when downloading/importing if it has absolute paths"
    # First check if the data is in the same folder as the job file and relative to
    # it. If it is, update the various uris so they are  can still be found after
    # moving the job file
    if (
        hasattr(job.results, "uri")
        and job.results.uri
        and not is_gdal_vsi_path(job.results.uri.uri)  # ignore gdal virtual fs
        and (not job.results.uri.uri.is_absolute() or not job.results.uri.uri.exists())
    ):
        # If the path doesn't exist, but the filename does exist in the
        # same folder as the job, the below function will assume that is what
        # is meant
        job.results.update_uris(job_path)


def _get_extent_tuple_raster(path):
    if conf.settings_manager.get_value(conf.Setting.DEBUG):
        log(f"Trying to calculate extent of raster {path}")

    if not os.path.exists(str(path)):
        log(f"Failed to calculate extent - file does not exist: {path}")
        return None

    ds = gdal.Open(str(path))
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


def _get_extent_tuple_vector(path):
    if conf.settings_manager.get_value(conf.Setting.DEBUG):
        log(f"Trying to calculate extent of vector {path}")
    rect = QgsVectorLayer(str(path), "vector file", "ogr").extent()
    if rect:
        xmin = rect.xMinimum()
        xmax = rect.xMaximum()
        ymin = rect.yMinimum()
        ymax = rect.yMaximum()
        if any([(val > 180 or val < -180) for val in [xmin, xmax]]) or any(
            [(val > 90 or val < -90) for val in [ymin, ymax]]
        ):
            # If there are not yet any features, then the extent will be set as ranging
            # from -infinite to infinite - so catch this with above check
            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                log(f"Failed to calculate extent for {path} - appears undefined")
            return None
        else:
            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                log(f"Calculated extent for {path} - {(xmin, ymin, xmax, ymax)}")
            return (xmin, ymin, xmax, ymax)
    else:
        log("Failed to calculate extent - couldn't open dataset")
        return None


def _set_results_extents_raster(job):
    for raster in job.results.rasters.values():
        if raster.type == results.RasterType.ONE_FILE_RASTER:
            if not hasattr(raster, "extent") or raster.extent is None:
                raster.extent = _get_extent_tuple_raster(raster.uri.uri)
                if conf.settings_manager.get_value(conf.Setting.DEBUG):
                    log(
                        f"set job {job.id} {raster.datatype} {raster.type} "
                        f"extent to {raster.extent}"
                    )
        elif raster.type == results.RasterType.TILED_RASTER:
            if not hasattr(raster, "extents") or raster.extents is None:
                raster.extents = []
                for raster_tile_uri in raster.tile_uris:
                    raster.extents.append(_get_extent_tuple_raster(raster_tile_uri.uri))
                if conf.settings_manager.get_value(conf.Setting.DEBUG):
                    log(
                        f"set job {job.id} {raster.datatype} {raster.type} "
                        f"extents to {raster.extents}"
                    )
        else:
            raise RuntimeError(f"Unknown raster type {raster.type!r}")


def _set_results_extents_vector(job):
    if conf.settings_manager.get_value(conf.Setting.DEBUG):
        log(f"Setting extents for job {job.id}")
    if not hasattr(job.results, "extent") or job.results.extent is None:
        job.results.extent = _get_extent_tuple_vector(job.results.vector.uri.uri)
        if conf.settings_manager.get_value(conf.Setting.DEBUG):
            log(
                f"set job {job.id} {job.results.type} {job.results.vector.type} "
                f"extent to {job.results.extent}"
            )


def set_results_extents(job):
    if not job.results:
        return
    if job.results.type == results.ResultType.RASTER_RESULTS and job.status in [
        jobs.JobStatus.DOWNLOADED,
        jobs.JobStatus.GENERATED_LOCALLY,
    ]:
        _set_results_extents_raster(job)
    elif job.results.type == results.ResultType.VECTOR_RESULTS and job.status in [
        jobs.JobStatus.DOWNLOADED,
        jobs.JobStatus.GENERATED_LOCALLY,
    ]:
        _set_results_extents_vector(job)


class LocalJobTask(QgsTask):
    job: Job
    area_of_interest: areaofinterest.AOI

    processed_job: QtCore.pyqtSignal = QtCore.pyqtSignal(Job)

    def __init__(self, description, job, area_of_interest):
        super().__init__(description, QgsTask.CanCancel)
        self.job = job
        self.job_copy = deepcopy(job)  # ensure job in main thread is not accessed
        self.area_of_interest = area_of_interest
        self.results = None

    def run(self):
        logger.debug("Running task")
        execution_handler = utils.load_object(self.job_copy.script.execution_callable)
        job_output_path, dataset_output_path = _get_local_job_output_paths(
            self.job_copy
        )
        self.results = execution_handler(
            self.job_copy,
            self.area_of_interest,
            job_output_path,
            dataset_output_path,
            self.setProgress,
            self.cancel,
        )

        if self.results is None:
            logger.debug("Completed run function - failure")
            return False
        else:
            logger.debug("Completed run function - success")
            return True

    def finished(self, result):
        logger.debug("Finished task")
        self.job.end_date = dt.datetime.now(dt.timezone.utc)
        self.job.progress = 100
        if result:
            self.job.results = self.results
            self.processed_job.emit(self.job)
            logger.debug("Task succeeded")
        else:
            logger.debug("Task failed")


class JobManager(QtCore.QObject):
    _encoding = "utf-8"
    _relevant_job_age_threshold_days = 14

    _known_running_jobs: typing.Dict[uuid.UUID, Job]
    _known_finished_jobs: typing.Dict[uuid.UUID, Job]
    _known_failed_jobs: typing.Dict[uuid.UUID, Job]
    _known_deleted_jobs: typing.Dict[uuid.UUID, Job]
    _known_downloaded_jobs: typing.Dict[uuid.UUID, Job]
    _known_ready_jobs: typing.Dict[uuid.UUID, Job]
    _known_pending_jobs: typing.Dict[uuid.UUID, Job]
    _known_cancelled_jobs: typing.Dict[uuid.UUID, Job]
    _known_expired_jobs: typing.Dict[uuid.UUID, Job]

    refreshed_local_state: QtCore.pyqtSignal = QtCore.pyqtSignal()
    refreshed_from_remote: QtCore.pyqtSignal = QtCore.pyqtSignal()
    downloaded_job_results: QtCore.pyqtSignal = QtCore.pyqtSignal(Job)
    downloaded_available_jobs_results: QtCore.pyqtSignal = QtCore.pyqtSignal()
    deleted_job: QtCore.pyqtSignal = QtCore.pyqtSignal(Job)
    submitted_remote_job: QtCore.pyqtSignal = QtCore.pyqtSignal(Job)
    submitted_local_job: QtCore.pyqtSignal = QtCore.pyqtSignal(Job)
    processed_local_job: QtCore.pyqtSignal = QtCore.pyqtSignal(Job)
    imported_job: QtCore.pyqtSignal = QtCore.pyqtSignal(Job)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.clear_known_jobs()
        self.tm = QgsApplication.taskManager()
        self._state_update_mutex = QtCore.QMutex()
        self.api_client = api.APIClient(API_URL, TIMEOUT)

    @property
    def known_jobs(self):
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
        }

    @property
    def relevant_jobs(self) -> typing.List[Job]:
        """Return a list of all jobs that are relevant to show to the user"""
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

        result = []

        for status in relevant_statuses:
            result.extend(self.known_jobs[status].values())

        return result

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
        self._known_running_jobs = {}
        self._known_finished_jobs = {}
        self._known_failed_jobs = {}
        self._known_deleted_jobs = {}
        self._known_downloaded_jobs = {}
        self._known_ready_jobs = {}
        self._known_pending_jobs = {}
        self._known_cancelled_jobs = {}
        self._known_expired_jobs = {}

    def refresh_local_state(self):
        """Update dataset manager's in-memory cache by scanning the local filesystem

        This function should be called periodically in order to ensure eventual
        consistency of the in-memory cache with the actual filesystem state.
        The filesystem is the source of truth for existing job metadata files and
        available results.
        """
        self._state_update_mutex.lock()

        self._known_running_jobs = {
            j.id: j for j in self._get_local_jobs(jobs.JobStatus.RUNNING)
        }
        self._refresh_local_downloaded_jobs()
        # We copy the dictionary before iterating in order to avoid having it
        # change size during the process
        frozen_known_downloaded_jobs = self._known_downloaded_jobs.copy()
        # move any downloaded jobs with missing local paths back to FINISHED

        for j_id, j in frozen_known_downloaded_jobs.items():
            if (
                j.results.uri
                and not is_gdal_vsi_path(j.results.uri.uri)
                and not j.results.uri.uri.exists()
            ):
                log(
                    f"job {j_id} currently marked as DOWNLOADED but has "
                    "missing paths, so moving back to FINISHED status"
                )
                j.results.uri = None
                self._change_job_status(j, jobs.JobStatus.FINISHED, force_rewrite=True)
        # Refresh again to pickup the changes back in the original dictionary
        self._refresh_local_downloaded_jobs()
        # filter list in case any jobs were moved from downloaded to finished
        self._known_downloaded_jobs = {
            j_id: j
            for j_id, j in self._known_downloaded_jobs.items()
            if j.status in [jobs.JobStatus.DOWNLOADED, jobs.JobStatus.GENERATED_LOCALLY]
        }

        # NOTE: finished and failed jobs are treated differently here because
        # we also make sure to delete those that are old and never got
        # downloaded (or are old and failed)
        self._get_local_finished_jobs()
        self._get_local_failed_jobs()
        self._get_local_expired_jobs()

        self._state_update_mutex.unlock()

        self.refreshed_local_state.emit()

    def refresh_from_remote_state(self, emit_signal: bool = True):
        """Request the latest state from the remote server

         Then update filesystem directories too.

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
        self._state_update_mutex.lock()

        now = dt.datetime.now(tz=dt.timezone.utc)
        relevant_date = now - dt.timedelta(days=self._relevant_job_age_threshold_days)

        offline_mode = conf.settings_manager.get_value(conf.Setting.OFFLINE_MODE)
        if not offline_mode:
            # Remote jobs will be taken into account
            remote_jobs = get_remote_jobs(end_date=relevant_date)

            if conf.settings_manager.get_value(conf.Setting.FILTER_JOBS_BY_BASE_DIR):
                relevant_remote_jobs = get_relevant_remote_jobs(remote_jobs)
            else:
                relevant_remote_jobs = remote_jobs

            self._refresh_local_deleted_jobs()

            deleted_ids = self._known_deleted_jobs.keys()
            relevant_remote_jobs = [
                job for job in relevant_remote_jobs if job.id not in deleted_ids
            ]
        else:
            # Remote jobs will be excluded
            relevant_remote_jobs = []
            self._refresh_local_deleted_jobs()

        self._refresh_local_running_jobs(relevant_remote_jobs)
        self._refresh_local_finished_jobs(relevant_remote_jobs)
        self._refresh_local_downloaded_jobs()
        self._refresh_remote_failed_jobs(relevant_remote_jobs)
        self._refresh_remote_jobs_by_status(relevant_remote_jobs)
        self._get_local_expired_jobs()

        log(
            f"JobManager refresh completed - found {len(relevant_remote_jobs)} relevant remote jobs"
        )

        self._state_update_mutex.unlock()

        if emit_signal:
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
            job = Job.Schema().load(raw_job)
            set_results_extents(job)
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
            if value <= 100:
                progress_bar.setValue(int(value))

        def cancel_task():
            job_task.cancel()
            message_bar.close()

        def close_messages():
            message_bar = iface.messageBar()
            message_bar.popWidget(message_bar_item)

        job_task.taskCompleted.connect(close_messages)
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
        execution_handler = utils.load_object(job.script.execution_callable)
        job_output_path, dataset_output_path = _get_local_job_output_paths(job)
        done_job = execution_handler(
            job, area_of_interest, job_output_path, dataset_output_path
        )
        self.finish_local_job(done_job)

    def finish_local_job(self, job):
        self._move_job_to_dir(job, new_status=jobs.JobStatus.GENERATED_LOCALLY)
        self.processed_local_job.emit(job)

    def download_job_results(self, job: Job) -> Job:
        handler = {
            ResultType.RASTER_RESULTS: self._download_cloud_results,
            ResultType.TIME_SERIES_TABLE: self._download_timeseries_table,
        }.get(job.results.type)

        if job.status == jobs.JobStatus.DOWNLOADED:
            # TODO:  We should never get here, but we do sometimes... Need to debug
            # more to figure out why
            return None

        if handler:
            handler: typing.Callable
            output_uri = handler(job)

            if output_uri is not None:
                job.results.uri = output_uri
                log(f"job.results.uri is {job.results.uri}")
                self._change_job_status(
                    job, jobs.JobStatus.DOWNLOADED, force_rewrite=True
                )
                self.downloaded_job_results.emit(job)
            else:
                return None
        else:
            # TODO: show a message noting that can't download this job type,
            # then disable the download button
            pass

        metadata.init_dataset_metadata(job)

        # TODO: maybe we don't need to return anything here
        return job

    def download_available_results(self):
        """Download all finished jobs' results.

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
        # NOTE: We copy the dictionary before iterating in order to avoid having it
        # change size during the bulk download process. The original
        # `self.known_jobs[JobStatus.FINISHED]` dict is being updated as each
        # job result is being downloaded
        frozen_finished_jobs = self.known_jobs[jobs.JobStatus.FINISHED].copy()

        if len(frozen_finished_jobs) > 0:
            for job in frozen_finished_jobs.values():
                self.download_job_results(job)
            self.downloaded_available_jobs_results.emit()

    def display_default_job_results(self, job: Job):
        if job.results.uri.uri.suffix in [".tif", ".vrt"]:
            for band_index, band in enumerate(job.results.get_bands(), start=1):
                if band.add_to_map:
                    layers.add_layer(
                        str(job.results.uri.uri),
                        band_index,
                        JobBand.Schema().dump(band),
                    )

    def display_selected_job_results(self, job: Job, band_numbers):
        if job.results.uri.uri.suffix in [".tif", ".vrt"]:
            for n, band in enumerate(job.results.get_bands(), start=1):
                if n in band_numbers:
                    layers.add_layer(
                        str(job.results.uri.uri), n, JobBand.Schema().dump(band)
                    )

    def display_error_recode_layer(self, job: Job):
        layer_path = job.results.vector.uri.uri
        layer = layers.add_vector_layer(str(layer_path), job.results.name)
        if layer is not None:
            layer.setCustomProperty("job_id", str(job.id))

    def edit_error_recode_layer(self, job: Job):
        layer_path = job.results.vector.uri.uri
        layers.edit(str(layer_path))

    def import_job(self, job: Job, job_path):
        update_uris_if_needed(job, job_path)

        set_results_extents(job)

        self._move_job_to_dir(job, job.status, force_rewrite=True)

        if job.status == jobs.JobStatus.PENDING:
            status = jobs.JobStatus.RUNNING
        elif job.status == jobs.JobStatus.GENERATED_LOCALLY:
            status = jobs.JobStatus.DOWNLOADED
        else:
            status = job.status

        log(f"job status is: {job.status}")
        log(f"emitting job {job.id}")
        self.known_jobs[status][job.id] = job
        self.imported_job.emit(job)

    def move_job_results(self, job: Job):
        """
        Move the datasets in results to the same folder as the job, where
        applicable.
        """
        if not hasattr(job.results, "uri") or not job.results.uri:
            return

        if job.status not in (
            jobs.JobStatus.GENERATED_LOCALLY,
            jobs.JobStatus.DOWNLOADED,
        ):
            return

        results_uri = job.results.uri.uri
        if not results_uri:
            return

        moved_files = {}

        # Job results
        job_path = self.get_job_file_path(job)
        dest_path = Path(
            f"{job_path.parent}/{job_path.stem}{job.results.uri.uri.suffix}"
        ).resolve()
        if results_uri.exists() and not dest_path.exists():
            log(f"Updating results URI from {results_uri!s} to {dest_path!s}")
            target_path = shutil.copy(results_uri, dest_path)
            moved_files[results_uri] = target_path
            job.results.uri.uri = target_path

        # Result layers
        uris = None

        if job.results.type == ResultType.RASTER_RESULTS:
            uris = job.results.get_main_uris()
        elif job.results.type == ResultType.VECTOR_RESULTS:
            uris = [job.results.vector.uri]
        elif job.results.type == ResultType.FILE_RESULTS:
            uris = job.results.other_uris

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
    ) -> Job:
        band_info = JobBand(
            name=band_name, no_data_value=-32768.0, metadata=band_metadata.copy()
        )

        if band_name in ["Land cover", "Land cover (7 class)"]:
            script = conf.KNOWN_SCRIPTS["local-land-cover"]
        elif band_name == "Soil organic carbon":
            script = conf.KNOWN_SCRIPTS["local-soil-organic-carbon"]
        elif band_name in [
            ld_conf.JRC_LPD_BAND_NAME,
            ld_conf.FAO_WOCAT_LPD_BAND_NAME,
            ld_conf.TE_LPD_BAND_NAME,
        ]:
            script = conf.KNOWN_SCRIPTS["productivity"]
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
            params={},
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
            task_notes="",
            script=script,
            end_date=now,
        )

        return job

    def create_error_recode(self, task_name, lc, soil, prod, sdg):
        log("create_error_recode called")

        now = dt.datetime.now(dt.timezone.utc)
        job_id = uuid.uuid4()
        job = Job(
            id=job_id,
            params={},
            progress=100,
            start_date=now,
            status=jobs.JobStatus.DOWNLOADED,
            local_context=_get_local_context(),
            results=VectorResults(
                name="False positive/negative",
                type=ResultType.VECTOR_RESULTS,
                vector=VectorFalsePositive(
                    uri=None,
                    type=VectorType.ERROR_RECODE,
                ),
                uri=None,
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
        self.write_job_metadata_file(job)
        self.known_jobs[job.status][job.id] = job
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

        log("setting default stats value")

        layers.set_default_stats_value(str(job.results.vector.uri.uri), band_datas)
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
            shutil.copy2(
                os.path.join(
                    os.path.dirname(__file__),
                    os.path.pardir,
                    "data",
                    "error_recode",
                    "error_recode_en.gpkg",
                ),
                output_path,
            )
        job.results.vector.uri = URI(uri=output_path)

    def _update_known_jobs_with_newly_submitted_job(self, job: Job):
        status = job.status

        if status == jobs.JobStatus.PENDING:
            status = jobs.JobStatus.RUNNING
        self.known_jobs[status][job.id] = job

    def _change_job_status(
        self, job: Job, target: jobs.JobStatus, force_rewrite: bool = True
    ):
        """Modify a job's status both in the in-memory cache and on the filesystem"""
        previous_status = job.status

        if previous_status == jobs.JobStatus.PENDING:
            previous_status = jobs.JobStatus.RUNNING
        elif previous_status == jobs.JobStatus.GENERATED_LOCALLY:
            previous_status = jobs.JobStatus.DOWNLOADED
        # this already sets the new status on the job
        self._move_job_to_dir(job, target, force_rewrite=force_rewrite)

        if target == jobs.JobStatus.DELETED:
            # Find which status dictionary actually contains the job
            for status, jobs_dict in self.known_jobs.items():
                if job.id in jobs_dict:
                    del jobs_dict[job.id]
                    break
        else:
            if job.id in self.known_jobs.get(previous_status, {}):
                del self.known_jobs[previous_status][job.id]
        self.known_jobs[job.status][job.id] = job

    def _download_cloud_results(self, job: jobs.Job) -> typing.Optional[Path]:
        base_output_path = self.get_downloaded_dataset_base_file_path(job)

        out_rasters = {}

        if len([*job.results.rasters.values()]) == 0:
            log(f"No results to download for {job.id}")

        for key, raster in job.results.rasters.items():
            file_out_base = f"{base_output_path.name}_{key}"

            if raster.type == results.RasterType.TILED_RASTER:
                tile_uris = []

                for uri_number, uri in enumerate(raster.tile_uris):
                    out_file = (
                        base_output_path.parent / f"{file_out_base}_{uri_number}.tif"
                    )
                    result = _download_result(
                        uri.uri,
                        base_output_path.parent / f"{file_out_base}_{uri_number}.tif",
                    )
                    if not result:
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
                result = _download_result(
                    raster.uri.uri,
                    out_file,
                )
                if not result:
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

        job.results.rasters = out_rasters

        # Setup the main uri. This could be a vrt (if job.results.rasters
        # has more than one Raster, or if it has one or more TiledRasters)

        if len(job.results.rasters) > 1 or (
            len(job.results.rasters) == 1
            and [*job.results.rasters.values()][0].type
            == results.RasterType.TILED_RASTER
        ):
            vrt_file = base_output_path.parent / f"{base_output_path.name}.vrt"
            main_raster_file_paths = [raster.uri.uri for raster in out_rasters.values()]
            combine_all_bands_into_vrt(main_raster_file_paths, vrt_file)
            job.results.uri = results.URI(uri=vrt_file)
        else:
            job.results.uri = [*job.results.rasters.values()][0].uri

        _set_results_extents_raster(job)

        log(f"job.results.uri in download function is {job.results.uri!r}")
        return job.results.uri

    def _download_timeseries_table(self, job: Job) -> typing.Optional[Path]:
        """
        Plot data already contained in the Job file as such no additional
        output file.
        """
        return None

    def _refresh_local_running_jobs(
        self, remote_jobs: typing.List[Job]
    ) -> typing.Dict[uuid.UUID, Job]:
        """Update local directory of running jobs by comparing with the remote jobs"""
        local_running_jobs = self._get_local_jobs(jobs.JobStatus.RUNNING)
        self._known_running_jobs = {}
        # first go over all previously known jobs and check if they are still running

        for old_running_job in local_running_jobs:
            remote_job = find_job(old_running_job, remote_jobs)

            if remote_job is None:  # unexpected behavior, remove the local job file
                self._remove_job_metadata_file(old_running_job)
                log(
                    f"Could not find job {old_running_job.id!r} on the remote server "
                    f"anymore. Deleting job metadata file from the base directory... "
                )
            elif remote_job.status == jobs.JobStatus.RUNNING:
                self._known_running_jobs[remote_job.id] = remote_job
                self.write_job_metadata_file(remote_job)
            else:  # job is not running anymore - maybe it is finished
                self._remove_job_metadata_file(old_running_job)
        # now check for any new jobs (these might have been submitted by another client)
        known_running = [j.id for j in self._known_running_jobs.values()]

        for remote in remote_jobs:
            remote_running = remote.status == jobs.JobStatus.RUNNING

            if remote_running and remote.id not in known_running:
                log(
                    f"Found new remote job: {remote.id!r}. Adding it to local base "
                    f"directory..."
                )
                self._known_running_jobs[remote.id] = remote
                self.write_job_metadata_file(remote)

        return self._known_running_jobs

    def _refresh_local_finished_jobs(
        self, remote_jobs: typing.List[Job]
    ) -> typing.Dict[uuid.UUID, Job]:
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
                # this is a new job that we are interested in, lets get it
                self._known_finished_jobs[remote_job.id] = remote_job
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
        old_path = os.path.splitext(self.get_job_file_path(job))[0] + ".qmd"

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

        if os.path.exists(old_path):
            new_path = os.path.splitext(self.get_job_file_path(job))[0] + ".qmd"
            shutil.move(old_path, new_path)

    # @functools.lru_cache(maxsize=None)  # not using functools.cache, as it was only introduced in Python 3.9
    def _get_local_jobs(self, status: jobs.JobStatus) -> typing.List[Job]:
        base_dir = {
            jobs.JobStatus.FINISHED: self.finished_jobs_dir,
            jobs.JobStatus.FAILED: self.failed_jobs_dir,
            jobs.JobStatus.RUNNING: self.running_jobs_dir,
            jobs.JobStatus.DELETED: self.deleted_jobs_dir,
            jobs.JobStatus.EXPIRED: self.expired_jobs_dir,
            jobs.JobStatus.DOWNLOADED: self.datasets_dir,
            jobs.JobStatus.GENERATED_LOCALLY: self.datasets_dir,
        }[status]
        result = []

        for job_metadata_path in base_dir.glob("**/*.json"):
            with job_metadata_path.open(encoding=self._encoding) as fh:
                try:
                    raw_job = json.load(fh)
                    job = Job.Schema().load(raw_job)
                    set_results_extents(job)
                except (KeyError, json.decoder.JSONDecodeError):
                    if conf.settings_manager.get_value(conf.Setting.DEBUG):
                        log(
                            f"Unable to decode file {job_metadata_path!r} as valid json"
                        )
                except ValidationError:
                    if conf.settings_manager.get_value(conf.Setting.DEBUG):
                        log(
                            f"Unable to decode file {job_metadata_path!r} - validation error decoding job"
                        )
                except RuntimeError as exc:
                    log(str(exc))
                else:
                    result.append(job)

        return result

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
        output_path = self.get_job_file_path(job)
        output_dir = output_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding=self._encoding) as fh:
            raw_job = Job.Schema().dump(job)
            json.dump(raw_job, fh, indent=2)

    def _remove_job_metadata_file(self, job: Job):
        old_path = self.get_job_file_path(job)

        if old_path.exists():
            old_path.unlink()  # not using the `missing_ok` param as it was introduced only in Python 3.8

    def _refresh_remote_jobs_by_status(self, remote_jobs: typing.List[Job]) -> None:
        """Update in-memory cache with READY, PENDING, and CANCELLED jobs from remote server"""
        # Initialize all caches
        self._known_ready_jobs = {}
        self._known_pending_jobs = {}
        self._known_cancelled_jobs = {}

        # Single loop to populate all caches
        for remote_job in remote_jobs:
            if remote_job.status == jobs.JobStatus.READY:
                self._known_ready_jobs[remote_job.id] = remote_job
            elif remote_job.status == jobs.JobStatus.PENDING:
                self._known_pending_jobs[remote_job.id] = remote_job
            elif remote_job.status == jobs.JobStatus.CANCELLED:
                self._known_cancelled_jobs[remote_job.id] = remote_job

    def _refresh_remote_failed_jobs(self, remote_jobs: typing.List[Job]) -> None:
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
                self._known_failed_jobs[remote_job.id] = remote_job
                self.write_job_metadata_file(remote_job)


def _get_local_job_output_paths(job: Job) -> typing.Tuple[Path, Path]:
    """Retrieve output path for a job so that it can be sent to the local processor"""
    # NOTE: temporarily setting the status as the final value in order to determine
    # the target filepath for the processing's outputs
    previous_status = job.status
    job.status = jobs.JobStatus.GENERATED_LOCALLY
    job_output_path = job_manager.get_job_file_path(job)
    job_output_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_output_path = job_output_path.parent / f"{job_output_path.stem}.tif"
    job.status = previous_status

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


def _get_access_token():
    api_client = api.APIClient(API_URL, TIMEOUT)
    login_reply = api_client.login()

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

    api_client = api.APIClient(API_URL, TIMEOUT)

    get_user_reply = api_client.get_user()

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
    gdal.BuildVRT(str(out_file), [str(tile) for tile in tiles])


def backoff_hdlr(details):
    log(
        "Backing off {wait:0.1f} seconds after {tries} tries "
        "calling function {target}".format(**details)
    )


@backoff.on_predicate(
    backoff.expo, lambda x: x is None, max_tries=5, on_backoff=backoff_hdlr
)
def _download_result(url: str, output_path: Path) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    download_worker = ldmp_download.Download(url, str(output_path))
    download_worker.start()
    result = bool(download_worker.get_resp())

    if not result:
        output_path.unlink(missing_ok=True)

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


def get_remote_jobs(end_date: typing.Optional[dt.datetime] = None) -> typing.List[Job]:
    """Get a list of remote jobs, as returned by the server"""
    # Note - this is a reimplementation of api.get_execution
    user_id = _get_user_id()
    if user_id is None:
        return []

    query = {"include": "script"}

    if end_date is not None:
        query["updated_at"] = end_date.strftime("%Y-%m-%d")

    if conf.settings_manager.get_value(conf.Setting.DEBUG):
        log("Retrieving executions...")

    response = job_manager.api_client.call_api(
        f"/api/v1/execution/user?{urllib.parse.urlencode(query)}",
        method="get",
        use_token=True,
    )

    if not response:
        log("No response from server")
        return []

    try:
        raw_jobs = response["data"]
        log(f"API returned {len(raw_jobs)} executions")
    except (TypeError, KeyError):
        log("Invalid response format")
        return []

    remote_jobs = []
    log(f"Processing {len(raw_jobs)} raw jobs from API response")
    for raw_job in raw_jobs:
        try:
            job = Job.Schema().load(raw_job)
            job.script.run_mode = AlgorithmRunMode.REMOTE

            if job is not None:
                remote_jobs.append(job)
                log(f"Successfully processed job {job.id} - {job.task_name}")
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


def get_relevant_remote_jobs(remote_jobs: typing.List[Job]) -> typing.List[Job]:
    """Filter a list of jobs gotten from the remote server for relevant jobs

    Relevant jobs are those that whose `local_context.base_dir` matches the current
    base dir.

    """

    current_base_dir = conf.settings_manager.get_value(conf.Setting.BASE_DIR)
    result = []

    for job in remote_jobs:
        if str(job.local_context.base_dir) == str(current_base_dir):
            result.append(job)

    return result


job_manager = JobManager()
