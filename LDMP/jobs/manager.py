import datetime as dt
import json
import typing
import urllib.parse
import uuid
from pathlib import Path

from qgis.PyQt import QtCore
from osgeo import gdal

from .. import (
    api,
    areaofinterest,
    conf,
    download as ldmp_download,
    layers,
    utils,
)
from . import models
from .models import Job
from ..logger import log


class JobManager(QtCore.QObject):
    _encoding = "utf-8"
    _relevant_job_age_threshold_days = 15

    _known_running_jobs: typing.Dict[uuid.UUID, Job]
    _known_finished_jobs: typing.Dict[uuid.UUID, Job]
    _known_deleted_jobs: typing.Dict[uuid.UUID, Job]
    _known_downloaded_jobs: typing.Dict[uuid.UUID, Job]

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

    @property
    def known_jobs(self):
        return {
            models.JobStatus.RUNNING: self._known_running_jobs,
            models.JobStatus.FINISHED: self._known_finished_jobs,
            models.JobStatus.DELETED: self._known_deleted_jobs,
            models.JobStatus.DOWNLOADED: self._known_downloaded_jobs,
        }

    @property
    def relevant_jobs(self) -> typing.List[Job]:
        relevant_statuses = (
            models.JobStatus.RUNNING,
            models.JobStatus.FINISHED,
            models.JobStatus.DOWNLOADED,
        )
        result = []
        for status in relevant_statuses:
            result.extend(self.known_jobs[status].values())
        return result

    @property
    def running_jobs_dir(self) -> Path:
        return Path(
            conf.settings_manager.get_value(conf.Setting.BASE_DIR)) / "running-jobs"

    @property
    def finished_jobs_dir(self) -> Path:
        return Path(
            conf.settings_manager.get_value(conf.Setting.BASE_DIR)) / "finished-jobs"

    @property
    def deleted_jobs_dir(self) -> Path:
        return Path(
            conf.settings_manager.get_value(conf.Setting.BASE_DIR)) / "deleted-jobs"

    @property
    def datasets_dir(self) -> Path:
        return Path(
            conf.settings_manager.get_value(conf.Setting.BASE_DIR)) / "datasets"

    @property
    def exports_dir(self) -> Path:
        return Path(
            conf.settings_manager.get_value(conf.Setting.BASE_DIR)) / \
               "exported"

    @classmethod
    def get_job_basename(cls, job: Job):
        separator = "_"
        name_fragments = []
        task_name = job.params.task_name
        if task_name != "":
            name_fragments.append(task_name)
        name_fragments.extend([
            job.script.name,
            job.params.task_notes.local_context.area_of_interest_name,
            job.start_date.strftime("%Y%m%d%H%M"),
            str(job.id)
        ])
        return separator.join(name_fragments)

    def clear_known_jobs(self):
        self._known_running_jobs = {}
        self._known_finished_jobs = {}
        self._known_deleted_jobs = {}
        self._known_downloaded_jobs = {}

    def refresh_local_state(self):
        """Update dataset manager's in-memory cache by scanning the local filesystem

        This function should be called periodically in order to ensure eventual
        consistency of the in-memory cache with the actual filesystem state.
        The filesystem is the source of truth for existing job metadata files and
        available results.

        """

        self._known_running_jobs = {
            j.id: j for j in self._get_local_jobs(models.JobStatus.RUNNING)}
        self._known_downloaded_jobs = {
            j.id: j for j in self._get_local_jobs(models.JobStatus.DOWNLOADED)}
        self._known_deleted_jobs = {
            j.id: j for j in self._get_local_jobs(models.JobStatus.DELETED)}
        # NOTE: finished jobs are treated differently here because we also make sure
        # to delete those that are old and never got downloaded
        self._get_local_finished_jobs()
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

        now = dt.datetime.now(tz=dt.timezone.utc)
        relevant_date = now - dt.timedelta(days=self._relevant_job_age_threshold_days)
        remote_jobs = get_remote_jobs(end_date=relevant_date)
        relevant_remote_jobs = get_relevant_remote_jobs(remote_jobs)

        self._refresh_local_running_jobs(relevant_remote_jobs)
        self._refresh_local_finished_jobs(relevant_remote_jobs)
        self._refresh_local_generated_jobs()
        self._refresh_local_deleted_jobs()

        if emit_signal:
            self.refreshed_from_remote.emit()

    def delete_job(self, job: Job):
        """Delete a job metadata file and any associated datasets from the local disk

        The job metadata file is moved to the `deleted-jobs` dir. This shall prevent
        subsequent downloads when refreshing the local state from the remote server.

        """

        if job.status != models.JobStatus.DELETED:
            try:
                _delete_job_datasets(job)
            except PermissionError:
                log(f"Permissions error on path skipping deletion of {job.id}...")
                # TODO: add back in old code used for removing visible layers
                # prior to deletion
                return
            self._change_job_status(job, models.JobStatus.DELETED, force_rewrite=False)
        else:
            log(f"job {job!r} has already been deleted, skipping...")
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
        final_params["task_notes"] = _add_local_context_to_task_notes(
            params["task_notes"])
        url_fragment = f"/api/v1/script/{script_id}/run"
        response = api.call_api(url_fragment, "post", final_params, use_token=True)
        try:
            raw_job = response["data"]
        except TypeError:
            job = None
        else:
            job = Job.deserialize(raw_job)
            self.write_job_metadata_file(job)
            self._update_known_jobs_with_newly_submitted_job(job)
            self.submitted_remote_job.emit(job)
        return job

    def submit_local_job(
            self,
            params: typing.Dict,
            script_name: str,
            area_of_interest: areaofinterest.AOI
    ):
        final_params = params.copy()
        final_params["task_notes"] = _add_local_context_to_task_notes(
            params["task_notes"])
        job = Job(
            id=uuid.uuid4(),
            params=models.JobParameters.deserialize(final_params),
            progress=0,
            results=models.JobLocalResults(
                name=script_name,
                bands=[],
                local_paths=[]
            ),
            script=models.get_job_local_script(script_name),
            status=models.JobStatus.PENDING,
            start_date=dt.datetime.now(dt.timezone.utc)
        )
        self.write_job_metadata_file(job)
        self._update_known_jobs_with_newly_submitted_job(job)
        self.submitted_local_job.emit(job)
        self.process_local_job(job, area_of_interest)

    def process_local_job(self, job: Job, area_of_interest: areaofinterest.AOI):
        execution_callable_python_path = job.script.additional_configuration[
            "execution_callable"]
        execution_handler = utils.load_object(execution_callable_python_path)
        done_job = execution_handler(job, area_of_interest)
        self._move_job_to_dir(done_job, new_status=models.JobStatus.GENERATED_LOCALLY)
        self.processed_local_job.emit(done_job)

    def download_job_results(self, job: Job) -> Job:
        handler = {
            models.JobResult.CLOUD_RESULTS: self._download_cloud_results,
            models.JobResult.TIME_SERIES_TABLE: self._download_timeseries_table,
        }[job.results.type]
        handler: typing.Callable
        output_path = handler(job)
        if output_path is not None:
            job.results.local_paths = [output_path]
            self._change_job_status(
                job, models.JobStatus.DOWNLOADED, force_rewrite=True)
        self.downloaded_job_results.emit(job)
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
        frozen_finished_jobs = self.known_jobs[models.JobStatus.FINISHED].copy()
        if len(frozen_finished_jobs) > 0:
            for job in frozen_finished_jobs.values():
                self.download_job_results(job)
            self.downloaded_available_jobs_results.emit()

    def display_job_results(self, job: Job):
        for path in job.results.local_paths:
            if path.suffix == ".tif":
                for band_index, band in enumerate(job.results.bands):
                    if band.add_to_map:
                        layers.add_layer(str(path), band_index+1, band.serialize())

    def import_job(self, job: Job):
        self._move_job_to_dir(job, job.status, force_rewrite=True)
        if job.status == models.JobStatus.PENDING:
            status = models.JobStatus.RUNNING
        elif job.status == models.JobStatus.GENERATED_LOCALLY:
            status = models.JobStatus.DOWNLOADED
        else:
            status = job.status
        self.known_jobs[status][job.id] = job
        self.imported_job.emit(job)

    def create_job_from_dataset(
            self,
            dataset_path: Path,
            band_name: str,
            band_metadata: typing.Dict
    ) -> Job:
        band_info = models.JobBand(
            name=band_name, no_data_value=-32768.0, metadata=band_metadata.copy())
        if band_name == "Land cover (7 class)":
            script = conf.KNOWN_SCRIPTS["local-land-cover"]
        elif band_name == "Soil organic carbon":
            script = conf.KNOWN_SCRIPTS["local-soil-organic-carbon"]
        elif band_name == "Land Productivity Dynamics (LPD)":
            script = conf.KNOWN_SCRIPTS["productivity"]
        else:
            raise RuntimeError(f"Invalid band name: {band_name!r}")
        now = dt.datetime.now(dt.timezone.utc)
        job = Job(
            id=uuid.uuid4(),
            params=models.JobParameters(
                task_name="Imported dataset",
                task_notes=models.JobNotes(
                    user_notes="",
                    local_context=models.JobLocalContext.create_default()
                ),
                params={}
            ),
            progress=100,
            results=models.JobLocalResults(
                name=f"{band_name} results",
                bands=[band_info],
                local_paths=[dataset_path]
            ),
            script=script,
            status=models.JobStatus.GENERATED_LOCALLY,
            start_date=now,
            end_date=now,
        )
        return job

    def _update_known_jobs_with_newly_submitted_job(self, job: Job):
        status = job.status
        if status == models.JobStatus.PENDING:
            status = models.JobStatus.RUNNING
        self.known_jobs[status][job.id] = job

    def _change_job_status(
            self, job: Job, target: models.JobStatus, force_rewrite: bool = True):
        """Modify a job's status both in the in-memory cache and on the filesystem"""
        previous_status = job.status
        if previous_status == models.JobStatus.PENDING:
            previous_status = models.JobStatus.RUNNING
        elif previous_status == models.JobStatus.GENERATED_LOCALLY:
            previous_status = models.JobStatus.DOWNLOADED
        # this already sets the new status on the job
        self._move_job_to_dir(job, target, force_rewrite=force_rewrite)
        del self.known_jobs[previous_status][job.id]
        self.known_jobs[job.status][job.id] = job

    def _download_cloud_results(self, job: Job) -> typing.Optional[Path]:
        base_output_path = self.get_downloaded_dataset_base_file_path(job)
        output_path = None
        if len(job.results.urls) > 0:
            if len(job.results.urls) == 1:
                final_output_path = (
                        base_output_path.parent / f"{base_output_path.name}.tif")
                output_path = _get_single_cloud_result(
                    job.results.urls[0], final_output_path)
            else:  # multiple files, download them then save VRT
                output_path = self._get_multiple_cloud_results(job, base_output_path)
        else:
            log(f"job {job} does not have downloadable results")
        return output_path

    def _get_multiple_cloud_results(self, job: Job, base_output_path: Path) -> Path:
        vrt_tiles = []
        for index, url in enumerate(job.results.urls):
            output_path = (
                    base_output_path.parent /
                    f"{base_output_path.name}_{index}.tif"
            )
            tile_path = _get_single_cloud_result(url, output_path)
            if tile_path is not None:
                vrt_tiles.append(tile_path)
        vrt_file_path = base_output_path.parent / f"{base_output_path.name}.vrt"
        log(f'vrt_file_path: {vrt_file_path}')
        log(f'vrt_tiles: {[str(vrt_tile) for vrt_tile in vrt_tiles]}')

        gdal.BuildVRT(str(vrt_file_path), [str(vrt_tile) for vrt_tile in vrt_tiles])
        return vrt_file_path

    def _download_timeseries_table(self, job: Job) -> typing.Optional[Path]:
        raise NotImplementedError

    def _refresh_local_running_jobs(
            self, remote_jobs: typing.List[Job]) -> typing.Dict[uuid.UUID, Job]:
        """Update local directory of running jobs by comparing with the remote jobs"""
        local_running_jobs = self._get_local_jobs(models.JobStatus.RUNNING)
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
            elif remote_job.status == models.JobStatus.RUNNING:
                self._known_running_jobs[remote_job.id] = remote_job
                self.write_job_metadata_file(remote_job)
            else:  # job is not running anymore - maybe it is finished
                self._remove_job_metadata_file(old_running_job)
        # now check for any new jobs (these might have been submitted by another client)
        known_running = [j.id for j in self._known_running_jobs.values()]
        for remote in remote_jobs:
            remote_running = remote.status == models.JobStatus.RUNNING
            if remote_running and remote.id not in known_running:
                log(
                    f"Found new remote job: {remote.id!r}. Adding it to local base "
                    f"directory..."
                )
                self._known_running_jobs[remote.id] = remote
                self.write_job_metadata_file(remote)
        return self._known_running_jobs

    def _refresh_local_finished_jobs(
            self, remote_jobs: typing.List[Job]) -> typing.Dict[uuid.UUID, Job]:
        self._known_finished_jobs = {
            j.id: j for j in self._get_local_jobs(models.JobStatus.FINISHED)}
        local_ids = self._known_finished_jobs.keys()
        deleted_ids = self._known_deleted_jobs.keys()
        downloaded_ids = self._known_downloaded_jobs.keys()
        remote_finished = [
            j for j in remote_jobs if j.status == models.JobStatus.FINISHED]
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

    def _refresh_local_generated_jobs(self):
        self._known_downloaded_jobs = {
            j.id: j for j in self._get_local_jobs(models.JobStatus.DOWNLOADED)}

    def _refresh_local_deleted_jobs(self):
        self._known_deleted_jobs = {
            j.id: j for j in self._get_local_jobs(models.JobStatus.DELETED)}

    def _move_job_to_dir(
            self, job: Job, new_status: models.JobStatus, force_rewrite: bool = False):
        """Move job metadata file to another directory based on the desired status.

        This also mutates the input job, updating its current status to the new one.

        """

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

    def _get_local_jobs(self, status: models.JobStatus) -> typing.List[Job]:
        base_dir = {
            models.JobStatus.FINISHED: self.finished_jobs_dir,
            models.JobStatus.RUNNING: self.running_jobs_dir,
            models.JobStatus.DELETED: self.deleted_jobs_dir,
            models.JobStatus.DOWNLOADED: self.datasets_dir,
        }[status]
        result = []
        for job_metadata_path in base_dir.glob("*.json"):
            with job_metadata_path.open(encoding=self._encoding) as fh:
                try:
                    raw_job = json.load(fh)
                    job = Job.deserialize(raw_job)
                except json.decoder.JSONDecodeError as exc:
                    log(f"Unable to decode file {job_metadata_path!r} as valid json")
                except KeyError:
                    log(f"Unable to decode file {job_metadata_path!r} as job json - no script_id in file")
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

        now = dt.datetime.now(tz=dt.timezone.utc)
        self._known_finished_jobs = {}
        for finished_job in self._get_local_jobs(models.JobStatus.FINISHED):
            job_age = now - finished_job.end_date
            if job_age.days > self._relevant_job_age_threshold_days:
                log(
                    f"Removing job {finished_job!r} as it is no longer possible to "
                    f"download its results..."
                )
                self._remove_job_metadata_file(finished_job)
            else:
                self._known_finished_jobs[finished_job.id] = finished_job
        return self._known_finished_jobs

    def get_job_file_path(self, job: Job) -> Path:
        if job.status in (models.JobStatus.RUNNING, models.JobStatus.PENDING):
            base = self.running_jobs_dir
        elif job.status == models.JobStatus.FINISHED:
            base = self.finished_jobs_dir
        elif job.status == models.JobStatus.DELETED:
            base = self.deleted_jobs_dir
        elif job.status in (
                models.JobStatus.DOWNLOADED, models.JobStatus.GENERATED_LOCALLY):
            base = self.datasets_dir
        else:
            raise RuntimeError(
                f"Could not retrieve file path for job with state {job.status}")
        return base / f"{self.get_job_basename(job)}.json"

    def get_downloaded_dataset_base_file_path(self, job: Job):
        base = self.datasets_dir
        return base / f"{self.get_job_basename(job)}"

    def write_job_metadata_file(self, job: Job):
        output_path = self.get_job_file_path(job)
        output_dir = output_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding=self._encoding) as fh:
            raw_job = job.serialize()
            json.dump(raw_job, fh, indent=2)

    def _remove_job_metadata_file(self, job: Job):
        old_path = self.get_job_file_path(job)
        if old_path.exists():
            old_path.unlink()  # not using the `missing_ok` param as it was introduced only in Python 3.8


def _add_local_context_to_task_notes(task_notes: str) -> str:
    separator = conf.settings_manager.get_value(conf.Setting.LOCAL_CONTEXT_SEPARATOR)
    context = models.JobLocalContext(
        base_dir=conf.settings_manager.get_value(conf.Setting.BASE_DIR),
        area_of_interest_name=conf.settings_manager.get_value(conf.Setting.AREA_NAME)
    )
    return separator.join((task_notes, context.serialize()))


def find_job(target: Job, source: typing.List[Job]) -> typing.Optional[Job]:
    try:
        result = [j for j in source if j.id == target.id][0]
    except IndexError:
        log(f"Could not find job {target.id!r} on the list of jobs")
        result = None
    return result


def _get_access_token():
    login_reply = api.login()
    return login_reply["access_token"]


def _get_user_id() -> uuid:
    log('Retrieving user id...')
    get_user_reply = api.get_user()
    log(f"get_user_reply: {get_user_reply}")
    if get_user_reply:
        user_id = get_user_reply.get("id", None)
        return uuid.UUID(user_id)


def _get_single_cloud_result(
        url: models.JobUrl, output_path: Path) -> typing.Optional[Path]:
    path_exists = output_path.is_file()
    hash_matches = ldmp_download.local_check_hash_against_etag(
        output_path, url.decoded_md5_hash)
    if path_exists and hash_matches:
        log(f"No download necessary, result already present in {output_path!r}")
        result = output_path
    else:
        _download_result(url.url, output_path)
        downloaded_hash_matches = (
            ldmp_download.local_check_hash_against_etag(
                output_path, url.decoded_md5_hash)
        )
        result = output_path if downloaded_hash_matches else None
    return result


def _download_result(url: str, output_path: Path) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    download_worker = ldmp_download.Download(url, str(output_path))
    download_worker.start()
    result = bool(download_worker.get_resp())
    if not result:
        try:
            output_path.parent.rmdir()
        except PermissionError:
            pass
    return result


def _delete_job_datasets(job: Job):
    if job.results is not None:
        for path in job.results.local_paths:
            try:
                # not using the `missing_ok` param since it was introduced only on Python 3.8
                path.unlink()
            except FileNotFoundError:
                log(f"Could not find path {path!r}, skipping deletion...")
        job.results.local_paths = []
    else:
        log("This job has no results to be deleted, skipping...")


def get_remote_jobs(end_date: typing.Optional[dt.datetime] = None) -> typing.List[Job]:
    """Get a list of remote jobs, as returned by the server"""
    # Note - this is a reimplementation of api.get_execution
    try:
        user_id = _get_user_id()
    except TypeError:
        log("Unable to load user id")
        remote_jobs = []
    else:
        query = {
            "include": "script",
            "user_id": str(user_id),
        }
        if end_date is not None:
            # NOTE: Even though the API query param is called `updated_at`, inspecting the
            # source code at:
            #
            # https://github.com/ConservationInternational/trends.earth-API/blob/
            # 2421eb0a5d44151d1b17c0c0841b72b55359b258/gefapi/services/
            # execution_service.py#L45
            #
            # we can verify that the server is actually checking for job's end_date
            query["updated_at"] = end_date.strftime("%Y-%m-%d")
        log('Retrieving executions...')
        response = api.call_api(
            f"/api/v1/execution?{urllib.parse.urlencode(query)}",
            method="get",
            use_token=True
        )
        try:
            raw_jobs = response["data"]
        except TypeError:
            log("Invalid response format")
            remote_jobs = []
        else:
            remote_jobs = []
            log(f'Processing {len(raw_jobs)} raw jobs...')
            for raw_job in raw_jobs:
                try:
                    job = Job.deserialize(raw_job)
                    has_results = job.results is not None
                    if (job.results is not None and
                            job.results.type == models.JobResult.TIME_SERIES_TABLE):
                        log(
                            f"Ignoring job {job.id!r} because it contains "
                            "timeseries results. Support for timeseries results "
                            "is not currently implemented"
                        )
                    else:
                        remote_jobs.append(job)
                except RuntimeError as exc:
                    log(str(exc))
                except TypeError as exc:
                    log(f"Could not retrieve remote job {raw_job['id']}: {str(exc)}")
    return remote_jobs


def get_relevant_remote_jobs(remote_jobs: typing.List[Job]) -> typing.List[Job]:
    """Filter a list of jobs gotten from the remote server for relevant jobs

    Relevant jobs are those that whose `local_context.base_dir` matches the current
    base dir.

    """

    current_base_dir = conf.settings_manager.get_value(conf.Setting.BASE_DIR)
    result = []
    for job in remote_jobs:
        if str(job.params.task_notes.local_context.base_dir) == str(current_base_dir):
            result.append(job)
    return result


job_manager = JobManager()
