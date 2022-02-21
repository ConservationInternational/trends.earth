import copy
import datetime as dt
import json
import re
import typing
import unicodedata
import urllib.parse
import logging
import uuid
from pathlib import Path
from typing import List

from marshmallow.exceptions import ValidationError
from osgeo import gdal
from qgis.core import QgsApplication, QgsTask
from qgis.PyQt import QtCore
from te_algorithms.gdal.util import combine_all_bands_into_vrt
from te_schemas import jobs, results
from te_schemas.algorithms import AlgorithmRunMode
from te_schemas.results import URI
from te_schemas.results import Band as JobBand
from te_schemas.results import (DataType, Raster, RasterFileType,
                                RasterResults, ResultType)

from .. import api, areaofinterest, conf
from .. import download as ldmp_download
from .. import layers, utils
from ..logger import log
from . import models
from .models import Job

logger = logging.getLogger(__name__)

def slugify(value, allow_unicode=False):
    """
    Taken from https://github.com/django/django/blob/master/django/utils/text.py
    Convert to ASCII if 'allow_unicode' is False. Convert spaces or repeated
    dashes to single dashes. Remove characters that aren't alphanumerics,
    underscores, or hyphens. Convert to lowercase. Also strip leading and
    trailing whitespace, dashes, and underscores.
    """
    value = str(value)

    if allow_unicode:
        value = unicodedata.normalize('NFKC', value)
    else:
        value = unicodedata.normalize('NFKD',
                                      value).encode('ascii',
                                                    'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value.lower())

    return re.sub(r'[-\s]+', '-', value).strip('-_')


def is_gdal_vsi_path(path: Path):
    return re.match(r"(\\)|(/)vsi(s3)|(gs)", str(path)) is not None


def _get_extent_tuple(path):
    log(f'Trying to calculate extent of {path}')
    ds = gdal.Open(str(path))
    if ds:
        min_x, xres, _, max_y, _, yres = ds.GetGeoTransform()
        cols = ds.RasterXSize
        rows = ds.RasterYSize
         
        extent = (min_x, max_y + rows*yres, min_x + cols*xres, max_y)
        log(f'Calculated extent {[*extent]}')
        return extent
    else:
        log("Failed to calculate extent - couldn't open dataset")
        return None


def _set_results_extents(job):
    log(f'Setting extents for job {job.id}')
    for raster in job.results.rasters.values():
        if raster.type == results.RasterType.ONE_FILE_RASTER:
            if not hasattr(raster, 'extent') or raster.extent is None:
                raster.extent = _get_extent_tuple(raster.uri.uri)
                log(f'set job {job.id} {raster.datatype} {raster.type} '
                    f'extent to {raster.extent}')
        elif raster.type == results.RasterType.TILED_RASTER:
            if not hasattr(raster, 'extents') or raster.extents is None:
                raster.extents = []
                for raster_tile_uri in raster.tile_uris:
                    raster.extents.append(_get_extent_tuple(raster_tile_uri.uri))
                log(f'set job {job.id} {raster.datatype} {raster.type} '
                    f'extents to {raster.extents}')
        else:
            raise RuntimeError(f"Unknown raster type {raster.type!r}")


def _load_raw_job(raw_job):
    job = Job.Schema().load(raw_job)
    if (
        job.results.type == results.ResultType.RASTER_RESULTS and
        job.status in [jobs.JobStatus.DOWNLOADED, jobs.JobStatus.GENERATED_LOCALLY]
    ):
        _set_results_extents(job)
    return job


class LocalJobTask(QgsTask):
    job: Job
    area_of_interest: areaofinterest.AOI

    processed_job: QtCore.pyqtSignal = QtCore.pyqtSignal(Job)

    def __init__(self, description, job, area_of_interest):
        super().__init__(description, QgsTask.CanCancel)
        self.job = job
        self.area_of_interest = area_of_interest

    def run(self):
        logger.debug('Running task')
        execution_handler = utils.load_object(self.job.script.execution_callable)
        job_output_path, dataset_output_path = _get_local_job_output_paths(self.job)
        self.completed_job = execution_handler(
            self.job, self.area_of_interest, job_output_path, dataset_output_path
        )

        if self.completed_job is None:
            logger.debug('Completed run function - failure')
            return False
        else:
            logger.debug('Completed run function - success')
            return True

    def finished(self, result):
        logger.debug('Finished task')
        if result:
            self.processed_job.emit(self.completed_job)
            logger.debug('Task succeeded')
        else:
            logger.debug('Task failed')


class JobManager(QtCore.QObject):
    _encoding = "utf-8"
    _relevant_job_age_threshold_days = 14

    _known_running_jobs: typing.Dict[uuid.UUID, Job]
    _known_finished_jobs: typing.Dict[uuid.UUID, Job]
    _known_failed_jobs: typing.Dict[uuid.UUID, Job]
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
        self.tm = QgsApplication.taskManager()

    @property
    def known_jobs(self):
        return {
            jobs.JobStatus.RUNNING: self._known_running_jobs,
            jobs.JobStatus.FINISHED: self._known_finished_jobs,
            jobs.JobStatus.FAILED: self._known_failed_jobs,
            jobs.JobStatus.DELETED: self._known_deleted_jobs,
            jobs.JobStatus.DOWNLOADED: self._known_downloaded_jobs,
        }

    @property
    def relevant_jobs(self) -> typing.List[Job]:
        relevant_statuses = (
            jobs.JobStatus.RUNNING,
            jobs.JobStatus.FINISHED,
            jobs.JobStatus.FAILED,
            jobs.JobStatus.DOWNLOADED,
        )
        result = []

        for status in relevant_statuses:
            result.extend(self.known_jobs[status].values())

        return result

    @property
    def running_jobs_dir(self) -> Path:
        return Path(
            conf.settings_manager.get_value(conf.Setting.BASE_DIR)
        ) / "running-jobs"

    @property
    def finished_jobs_dir(self) -> Path:
        return Path(
            conf.settings_manager.get_value(conf.Setting.BASE_DIR)
        ) / "finished-jobs"

    @property
    def failed_jobs_dir(self) -> Path:
        return Path(
            conf.settings_manager.get_value(conf.Setting.BASE_DIR)
        ) / "failed-jobs"

    @property
    def deleted_jobs_dir(self) -> Path:
        return Path(
            conf.settings_manager.get_value(conf.Setting.BASE_DIR)
        ) / "deleted-jobs"

    @property
    def datasets_dir(self) -> Path:
        return Path(
            conf.settings_manager.get_value(conf.Setting.BASE_DIR)
        ) / "datasets"

    @property
    def exports_dir(self) -> Path:
        return Path(
            conf.settings_manager.get_value(conf.Setting.BASE_DIR)
        ) / "exported"

    @classmethod
    def get_job_basename(cls, job: Job, with_uuid=False):
        separator = "_"
        name_fragments = []
        task_name = slugify(job.task_name)

        if task_name:
            name_fragments.append(task_name)

        if job.script:
            name_fragments.append(job.script.name)

        if job.local_context.area_of_interest_name:
            name_fragments.append(job.local_context.area_of_interest_name)

        if len(name_fragments) == 0 or with_uuid:
            name_fragments.append(str(job.id))

        return separator.join(name_fragments)

    def clear_known_jobs(self):
        self._known_running_jobs = {}
        self._known_finished_jobs = {}
        self._known_failed_jobs = {}
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
            j.id: j
            for j in self._get_local_jobs(jobs.JobStatus.RUNNING)
        }
        self._refresh_local_downloaded_jobs()
        # We copy the dictionary before iterating in order to avoid having it
        # change size during the process
        frozen_known_downloaded_jobs = self._known_downloaded_jobs.copy()
        # move any downloaded jobs with missing local paths back to FINISHED

        for j_id, j in frozen_known_downloaded_jobs.items():
            if (
                j.results.uri and not is_gdal_vsi_path(j.results.uri.uri)
                and not j.results.uri.uri.exists()
            ):
                log(
                    f'job {j_id} currently marked as DOWNLOADED but has '
                    'missing paths, so moving back to FINISHED status'
                )
                j.results.uri = None
                self._change_job_status(
                    j, jobs.JobStatus.FINISHED, force_rewrite=True
                )
        # Refresh again to pickup the changes back in the original dictionary
        self._refresh_local_downloaded_jobs()
        # filter list in case any jobs were moved from downloaded to finished
        self._known_downloaded_jobs = {
            j_id: j
            for j_id, j in self._known_downloaded_jobs.items() if j.status in
            [jobs.JobStatus.DOWNLOADED, jobs.JobStatus.GENERATED_LOCALLY]
        }

        # NOTE: finished and failed jobs are treated differently here because
        # we also make sure to delete those that are old and never got
        # downloaded (or are old and failed)
        self._get_local_finished_jobs()
        self._get_local_failed_jobs()
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
        relevant_date = now - dt.timedelta(
            days=self._relevant_job_age_threshold_days
        )
        remote_jobs = get_remote_jobs(end_date=relevant_date)

        if conf.settings_manager.get_value(
            conf.Setting.FILTER_JOBS_BY_BASE_DIR
        ):
            relevant_remote_jobs = get_relevant_remote_jobs(remote_jobs)
        else:
            relevant_remote_jobs = remote_jobs

        self._refresh_local_running_jobs(relevant_remote_jobs)
        self._refresh_local_finished_jobs(relevant_remote_jobs)
        self._refresh_local_downloaded_jobs()
        self._refresh_local_generated_jobs()
        self._refresh_local_deleted_jobs()

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
                log(
                    f"Permissions error on path skipping deletion of {job.id}..."
                )
                # TODO: add back in old code used for removing visible layers
                # prior to deletion

                return
            self._change_job_status(
                job, jobs.JobStatus.DELETED, force_rewrite=False
            )
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
        final_params["local_context"] = jobs.JobLocalContext().Schema().dump(
            _get_local_context()
        )
        url_fragment = f"/api/v1/script/{script_id}/run"
        response = api.call_api(
            url_fragment, "post", final_params, use_token=True
        )
        try:
            raw_job = response["data"]
        except TypeError:
            job = None
        else:
            job = _load_raw_job(raw_job)
            self.write_job_metadata_file(job)
            self._update_known_jobs_with_newly_submitted_job(job)
            self.submitted_remote_job.emit(job)

        return job

    def submit_local_job_as_qgstask(
        self, params: typing.Dict, script_name: str,
        area_of_interest: areaofinterest.AOI
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
            script=models.get_job_local_script(script_name)
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
        job_name = ' - '.join(job_name_parts)

        job_task = LocalJobTask(job_name, job, area_of_interest)
        job_task.processed_job.connect(self.finish_local_job)
        self.tm.addTask(job_task)

    def submit_local_job(
        self, params: typing.Dict, script_name: str,
        area_of_interest: areaofinterest.AOI
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
            script=models.get_job_local_script(script_name)
        )
        self.write_job_metadata_file(job)
        self._update_known_jobs_with_newly_submitted_job(job)
        self.submitted_local_job.emit(job)
        self.process_local_job(job, area_of_interest)

    def process_local_job(
        self, job: Job, area_of_interest: areaofinterest.AOI
    ):
        execution_handler = utils.load_object(job.script.execution_callable)
        job_output_path, dataset_output_path = _get_local_job_output_paths(job)
        done_job = execution_handler(
            job, area_of_interest, job_output_path, dataset_output_path
        )
        self.finish_local_job(done_job)

    def finish_local_job(self, job):
        self._move_job_to_dir(
            job, new_status=jobs.JobStatus.GENERATED_LOCALLY
        )
        self.processed_local_job.emit(job)

    def download_job_results(self, job: Job) -> Job:
        handler = {
            ResultType.RASTER_RESULTS: self._download_cloud_results,
            ResultType.TIME_SERIES_TABLE: self._download_timeseries_table,
        }.get(job.results.type)

        if handler:
            handler: typing.Callable
            output_path = handler(job)

            if output_path is not None:
                job.results.uri = output_path
                self._change_job_status(
                    job, jobs.JobStatus.DOWNLOADED, force_rewrite=True
                )
            self.downloaded_job_results.emit(job)
        else:
            # TODO: show a message noting that can't download this job type,
            # then disable the download button
            pass
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
            for band_index, band in enumerate(
                job.results.get_bands(), start=1
            ):
                if band.add_to_map:
                    layers.add_layer(
                        str(job.results.uri.uri), band_index,
                        JobBand.Schema().dump(band)
                    )

    def display_selected_job_results(self, job: Job, band_numbers):
        if job.results.uri.uri.suffix in [".tif", ".vrt"]:
            for n, band in enumerate(job.results.get_bands(), start=1):
                if n in band_numbers:
                    layers.add_layer(
                        str(job.results.uri.uri), n,
                        JobBand.Schema().dump(band)
                    )

    def import_job(self, job: Job, job_path):
        # First check if data path is relative to job file. If it is, update
        # the data_path and other_path before moving the job file so the data
        # can still be found after moving the job file
        # TODO: Need to handle moving all raster paths, not just the main
        # datapath

        if (
            job.results.uri and not job.results.uri.uri.is_absolute() and
            not is_gdal_vsi_path(job.results.uri.uri
                                 )  # don't change gdal virtual fs references
        ):
            # If the path doesn't exist, but the filename does exist in the
            # same folder as the job, assume that is what is meant
            possible_path = Path(job_path.parent / job.results.uri.uri.name
                                 ).absolute()

            if possible_path.exists():
                job.results.uri.uri = possible_path
            job.results.uri.uri = possible_path
            # # Assume the other_paths also need to be converted
            # job.results.other_paths = [
            #     Path(job_path.parent / p).absolute()
            #     for p in job.results.other_paths
            # ]
        self._move_job_to_dir(job, job.status, force_rewrite=True)

        if job.status == jobs.JobStatus.PENDING:
            status = jobs.JobStatus.RUNNING
        elif job.status == jobs.JobStatus.GENERATED_LOCALLY:
            status = jobs.JobStatus.DOWNLOADED
        else:
            status = job.status
        log(f'job status is: {job.status}')
        log(f'emitting job {job.id}')
        self.known_jobs[status][job.id] = job
        self.imported_job.emit(job)

    def create_job_from_dataset(
        self, dataset_path: Path, band_name: str, band_metadata: typing.Dict
    ) -> Job:
        band_info = JobBand(
            name=band_name,
            no_data_value=-32768.0,
            metadata=band_metadata.copy()
        )

        if band_name == "Land cover (7 class)":
            script = conf.KNOWN_SCRIPTS["local-land-cover"]
        elif band_name == "Soil organic carbon":
            script = conf.KNOWN_SCRIPTS["local-soil-organic-carbon"]
        elif band_name == "Land Productivity Dynamics (LPD)":
            script = conf.KNOWN_SCRIPTS["productivity"]
        else:
            raise RuntimeError(f"Invalid band name: {band_name!r}")
        now = dt.datetime.now(tz=dt.timezone.utc)
        rasters= {
            DataType.INT16.value:
            Raster(
                uri=URI(uri=dataset_path, type='local'),
                bands=[band_info],
                datatype=DataType.INT16,
                filetype=RasterFileType.GEOTIFF,
                extent=_get_extent_tuple(dataset_path)
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
                uri=URI(uri=dataset_path, type='local'),
            ),
            task_name="Imported dataset",
            task_notes="",
            script=script,
            end_date=now
        )

        return job

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
        del self.known_jobs[previous_status][job.id]
        self.known_jobs[job.status][job.id] = job

    def _download_cloud_results(self, job: jobs.Job) -> typing.Optional[Path]:
        base_output_path = self.get_downloaded_dataset_base_file_path(job)

        out_rasters = {}

        if len([*job.results.rasters.values()]) == 0:
            log(f'No results to download for {job.id}')

        for key, raster in job.results.rasters.items():
            file_out_base = f"{base_output_path.name}_{key}"

            if raster.type == results.RasterType.TILED_RASTER:
                tile_uris = []

                for uri_number, uri in enumerate(raster.tile_uris):
                    out_file = (
                        base_output_path.parent /
                        f"{file_out_base}_{uri_number}.tif"
                    )
                    _download_result(
                        uri.uri,
                        base_output_path.parent /
                        f"{file_out_base}_{uri_number}.tif",
                    )
                    tile_uris.append(results.URI(uri=out_file, type='local'))

                raster.tile_uris = tile_uris

                vrt_file = base_output_path.parent / f"{file_out_base}.vrt"
                _get_raster_vrt(
                    tiles=[str(uri.uri) for uri in tile_uris],
                    out_file=vrt_file,
                )
                out_rasters[key] =  results.TiledRaster(
                        tile_uris=tile_uris,
                        bands=raster.bands,
                        datatype=raster.datatype,
                        filetype=raster.filetype,
                        uri=results.URI(uri=vrt_file, type='local'),
                        type=results.RasterType.TILED_RASTER
                    )
            else:
                out_file = base_output_path.parent / f"{file_out_base}.tif"
                _download_result(
                    raster.uri.uri,
                    out_file,
                )
                raster_uri = results.URI(uri=out_file, type='local')
                raster.uri = raster_uri
                out_rasters[key] =  results.Raster(
                    uri=raster_uri,
                    bands=raster.bands,
                    datatype=raster.datatype,
                    filetype=raster.filetype,
                    type=results.RasterType.ONE_FILE_RASTER
                )

        job.results.rasters = out_rasters

        # Setup the main data_path. This could be a vrt (if job.results.rasters
        # has more than one Raster, or if it has one or more TiledRasters)

        if (
            len(job.results.rasters) > 1 or (
                len(job.results.rasters) == 1
                and [*job.results.rasters.values()
                     ][0].type == results.RasterType.TILED_RASTER
            )
        ):
            vrt_file = base_output_path.parent / f"{base_output_path.name}.vrt"
            main_raster_file_paths = [raster.uri.uri for raster in out_rasters.values()]
            combine_all_bands_into_vrt(main_raster_file_paths, vrt_file)
            job.results.uri = results.URI(uri=vrt_file, type='local')
        else:
            job.results.uri = [*job.results.rasters.values()][0].uri

        _set_results_extents(job)

        return job.results.uri

    def _download_timeseries_table(self, job: Job) -> typing.Optional[Path]:
        raise NotImplementedError

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
            j.id: j
            for j in self._get_local_jobs(jobs.JobStatus.FINISHED)
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
        self._known_downloaded_jobs = {
            j.id: j
            for j in self._get_local_jobs(jobs.JobStatus.DOWNLOADED)
        }

    def _refresh_local_generated_jobs(self):
        self._known_downloaded_jobs = {
            j.id: j
            for j in self._get_local_jobs(jobs.JobStatus.GENERATED_LOCALLY)
        }

    def _refresh_local_deleted_jobs(self):
        self._known_deleted_jobs = {
            j.id: j
            for j in self._get_local_jobs(jobs.JobStatus.DELETED)
        }

    def _move_job_to_dir(
        self,
        job: Job,
        new_status: jobs.JobStatus,
        force_rewrite: bool = False
    ):
        """Move job metadata file to another directory based on the desired status.

        This also mutates the input job, updating its current status to the new one.

        """

        log(f'moving job {job.id} to dir')

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

    #@functools.lru_cache(maxsize=None)  # not using functools.cache, as it was only introduced in Python 3.9
    def _get_local_jobs(self, status: jobs.JobStatus) -> typing.List[Job]:
        base_dir = {
            jobs.JobStatus.FINISHED: self.finished_jobs_dir,
            jobs.JobStatus.FAILED: self.failed_jobs_dir,
            jobs.JobStatus.RUNNING: self.running_jobs_dir,
            jobs.JobStatus.DELETED: self.deleted_jobs_dir,
            jobs.JobStatus.DOWNLOADED: self.datasets_dir,
            jobs.JobStatus.GENERATED_LOCALLY: self.datasets_dir,
        }[status]
        result = []

        for job_metadata_path in base_dir.glob("**/*.json"):
            with job_metadata_path.open(encoding=self._encoding) as fh:
                try:
                    raw_job = json.load(fh)
                    job = _load_raw_job(raw_job)
                except (KeyError, json.decoder.JSONDecodeError) as exc:
                    if conf.settings_manager.get_value(conf.Setting.DEBUG):
                        log(
                            f"Unable to decode file {job_metadata_path!r} as valid json"
                        )
                except ValidationError as exc:
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
                            f"Removing job {finished_job.id!r} as it is no longer possible to "
                            f"download its results..."
                        )
                    self._remove_job_metadata_file(finished_job)
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
                log(
                    f"Removing job {failed_job.id} as it is no longer on server"
                )
                self._remove_job_metadata_file(failed_job)
            else:
                self._known_failed_jobs[failed_job.id] = failed_job

        return self._known_failed_jobs

    def get_job_file_path(self, job: Job) -> Path:
        if job.status in (jobs.JobStatus.RUNNING, jobs.JobStatus.PENDING):
            base = self.running_jobs_dir / f"{self.get_job_basename(job, with_uuid=True)}.json"
        elif job.status == jobs.JobStatus.FAILED:
            base = self.failed_jobs_dir / f"{self.get_job_basename(job, with_uuid=True)}.json"
        elif job.status == jobs.JobStatus.FINISHED:
            base = self.finished_jobs_dir / f"{self.get_job_basename(job, with_uuid=True)}.json"
        elif job.status == jobs.JobStatus.DELETED:
            base = self.deleted_jobs_dir / f"{self.get_job_basename(job, with_uuid=True)}.json"
        elif job.status in (
            jobs.JobStatus.DOWNLOADED, jobs.JobStatus.GENERATED_LOCALLY
        ):
            base = self.datasets_dir / f"{job.id!s}" / f"{self.get_job_basename(job)}.json"
        else:
            raise RuntimeError(
                f"Could not retrieve file path for job with state {job.status}"
            )

        return base

    def get_downloaded_dataset_base_file_path(self, job: Job):
        base = self.datasets_dir

        return base / f"{job.id!s}" / f"{self.get_job_basename(job)}"

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
            old_path.unlink(
            )  # not using the `missing_ok` param as it was introduced only in Python 3.8


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
        area_of_interest_name=conf.settings_manager.get_value(
            conf.Setting.AREA_NAME
        )
    )


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
    if conf.settings_manager.get_value(conf.Setting.DEBUG):
        log('Retrieving user id...')
    get_user_reply = api.get_user()

    if get_user_reply:
        user_id = get_user_reply.get("id", None)

        return uuid.UUID(user_id)


def _get_raster_vrt(tiles: List[Path], out_file: Path):
    gdal.BuildVRT(str(out_file), [str(tile) for tile in tiles])


def _download_result(url: str, output_path: Path) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    download_worker = ldmp_download.Download(url, str(output_path))
    download_worker.start()
    result = bool(download_worker.get_resp())

    if not result:
        output_path.unlink()

    return result


def _delete_job_datasets(job: Job):
    if job.results is not None:
        try:
            # not using the `missing_ok` param since it was introduced only on
            # Python 3.8

            if (job.results.uri and not is_gdal_vsi_path(job.results.uri.uri)):
                job.results.uri.uri.unlink()
        except FileNotFoundError:
            log(
                f"Could not find path {job.results.uri.uri!r}, "
                "skipping deletion..."
            )
    else:
        log("This job has no results to be deleted, skipping...")


def get_remote_jobs(
    end_date: typing.Optional[dt.datetime] = None
) -> typing.List[Job]:
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

        if conf.settings_manager.get_value(conf.Setting.DEBUG):
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

            for raw_job in raw_jobs:
                try:
                    job = Job.Schema().load(raw_job)
                    job.script.run_mode = AlgorithmRunMode.REMOTE

                    if (
                        job.results is not None
                        and job.results.type == ResultType.TIME_SERIES_TABLE
                    ):
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
                    log(
                        f"Could not retrieve remote job {raw_job['id']}: {str(exc)}"
                    )

    return remote_jobs


def get_relevant_remote_jobs(
    remote_jobs: typing.List[Job]
) -> typing.List[Job]:
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
