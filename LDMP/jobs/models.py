"""Job and dataset utilities"""

import base64
import binascii
import dataclasses
import datetime as dt
import enum
import functools
import json
import typing
import uuid
from pathlib import Path

from .. import (
    api,
    conf,
)
from ..algorithms.models import ExecutionScript
from ..logger import log

from te_schemas import jobs

import marshmallow_dataclass

class SortField(enum.Enum):
    NAME = 'name'
    DATE = 'date'
    ALGORITHM = 'algorithm'
    STATUS = 'status'


@dataclasses.dataclass()
class Job:
    id: uuid.UUID
    params: jobs.JobParameters
    progress: int
    results: typing.Optional[
        typing.Union[
            jobs.JobCloudResults,
            jobs.JobLocalResults,
            jobs.TimeSeriesTableResult
        ]
    ]
    script: ExecutionScript
    status: jobs.JobStatus
    start_date: dt.datetime
    end_date: typing.Optional[dt.datetime] = None
    user_id: typing.Optional[uuid.UUID] = None

    _date_format: str = "%Y-%m-%dT%H:%M:%S.%f"

    @classmethod
    def deserialize(cls, raw_job: typing.Dict):
        raw_end_date = raw_job.get("end_date")
        if raw_end_date is not None:
            end_date = dt.datetime.strptime(
                raw_end_date, cls._date_format).replace(tzinfo=dt.timezone.utc)
        else:
            end_date = None

        raw_results = raw_job.get("results") or {}
        try:
            type_ = jobs.JobResultType(raw_results["type"])
        except KeyError:
            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                log(f"Could not extract type of results from job {raw_job['id']} with raw_results {raw_results!r}")
            results = None
        else:
            if type_ == jobs.JobResultType.CLOUD_RESULTS:
                results = jobs.JobCloudResults.Schema().load(raw_results)
            elif type_ == jobs.JobResultType.LOCAL_RESULTS:
                results = jobs.JobLocalResults.Schema().load(raw_results)
            elif type_ == jobs.JobResultType.TIME_SERIES_TABLE:
                results = jobs.TimeSeriesTableResult.Schema().load(raw_results)
            else:
                raise RuntimeError(f"Invalid results type: {type_!r}")
        try:
            script_id = uuid.UUID(raw_job["script_id"])
            script = _get_job_script(script_id)
            if script is None:
                log(f"Failed to get script by id for {script_id}")
                raise ValueError
        except ValueError:
            script_name = raw_job["script_id"]
            script = get_job_local_script(script_name)
        raw_user_id = raw_job.get("user_id")
        return cls(
            id=uuid.UUID(raw_job["id"]),
            params=jobs.JobParameters.Schema().load(raw_job["params"]),
            progress=raw_job["progress"],
            results=results,
            script=script,
            status=jobs.JobStatus(raw_job["status"]),
            user_id=uuid.UUID(raw_user_id) if raw_user_id is not None else None,
            start_date=dt.datetime.strptime(
                raw_job["start_date"],
                cls._date_format
            ).replace(tzinfo=dt.timezone.utc),
            end_date=end_date
        )

    @property
    def visible_name(self) -> str:
        task_name = self.params.task_name
        if task_name != "" and self.script is not None:
            name = f"{task_name} ({self.script.name_readable})"
        elif self.script is not None:
            name = self.script.name_readable
        else:
            name = "Unknown script"
        return name

    def serialize(self) -> typing.Dict:
        # local scripts are identified by their name, they do not have an id
        script_identifier = (
            str(self.script.id) if self.script.id is not None else self.script.name)

        if self.results is None:
            results_serial = None
        elif self.results.type == jobs.JobResultType.CLOUD_RESULTS:
            results_serial = jobs.JobCloudResults.Schema().dump(self.results)
        elif self.results.type == jobs.JobResultType.LOCAL_RESULTS:
            results_serial = jobs.JobLocalResults.Schema().dump(self.results)
        elif self.results.type == jobs.JobResultType.TIME_SERIES_TABLE:
            results_serial = jobs.TimeSeriesTableResult.Schema().dump(self.results)

        raw_job = {
            "id": str(self.id),
            "params": jobs.JobParameters.Schema().dump(self.params),
            "progress": self.progress,
            "results": results_serial,
            "script_id": script_identifier,
            "status": self.status.value,
            "user_id": str(self.user_id) if self.user_id is not None else None,
            "start_date": self.start_date.strftime(self._date_format)
        }
        if self.end_date is not None:
            raw_job["end_date"] = self.end_date.strftime(self._date_format)
        return raw_job



@functools.lru_cache(maxsize=None)  # not using functools.cache, as it was only introduced in Python 3.9
def get_remote_scripts():
    """Query the remote server for existing scripts

    The information returned from the remote shall be enough to at least
    display Jobs which came from a version which is not known locally.

    """

    raw_remote = api.get_script()
    if raw_remote is None:
        return
    else:
        return [
            jobs.RemoteScript.Schema().load(r)
            for r in raw_remote
        ]


def get_job_local_script(script_name: str) -> ExecutionScript:
    return conf.KNOWN_SCRIPTS.get(script_name, None)


def _get_job_script(script_id: uuid.UUID) -> ExecutionScript:
    try:
        script = [
            s for s in conf.KNOWN_SCRIPTS.values() if s.id == script_id
        ][0]
    except IndexError:
        if conf.settings_manager.get_value(conf.Setting.DEBUG):
            log(f"script {script_id!r} is not known locally")
        remote_scripts = get_remote_scripts()
        if remote_scripts is None:
            return
        try:
            script = [s for s in remote_scripts if s.id == script_id][0]
        except IndexError:
            raise RuntimeError(
                f"script {script_id!r} is not known on the remote server")
        else:
            script = ExecutionScript.Schema().load(
                jobs.RemoteScript.Schema().dump(script)
            )
    return script
