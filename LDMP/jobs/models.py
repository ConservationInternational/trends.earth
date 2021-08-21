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


class SortField(enum.Enum):
    NAME = 'name'
    DATE = 'date'
    ALGORITHM = 'algorithm'
    STATUS = 'status'


class ScriptStatus(enum.Enum):
    SUCCESS = "SUCCESS"
    FAIL = "FAIL"


class JobStatus(enum.Enum):
    READY = "READY"
    PENDING = "PENDING"
    FINISHED = "FINISHED"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    DELETED = "DELETED"
    DOWNLOADED = "DOWNLOADED"
    GENERATED_LOCALLY = "GENERATED_LOCALLY"


class JobResult(enum.Enum):
    CLOUD_RESULTS = "CloudResults"
    LOCAL_RESULTS = "LocalResults"
    TIME_SERIES_TABLE = "TimeSeriesTable"


@dataclasses.dataclass()
class RemoteScript:
    id: uuid.UUID
    name: str
    slug: str
    description: str
    status: str
    created_at: dt.datetime
    updated_at: dt.datetime
    user_id: uuid.UUID
    public: bool

    _date_format: str = "%Y-%m-%dT%H:%M:%S.%f"

    @classmethod
    def deserialize(cls, raw_script: typing.Dict):
        return cls(
            id=uuid.UUID(raw_script["id"]),
            name=raw_script["name"],
            slug=raw_script["slug"],
            description=raw_script["description"],
            status=ScriptStatus(raw_script["status"]),
            created_at=dt.datetime.strptime(
                raw_script["created_at"],
                cls._date_format
            ).replace(tzinfo=dt.timezone.utc),
            updated_at=dt.datetime.strptime(
                raw_script["updated_at"],
                cls._date_format
            ).replace(tzinfo=dt.timezone.utc),
            user_id=uuid.UUID(raw_script["user_id"]),
            public=raw_script["public"]
        )


@dataclasses.dataclass()
class JobLocalContext:
    base_dir: Path
    area_of_interest_name: str

    _unknown_area_of_interest: str = "unknown-area"

    @classmethod
    def deserialize(cls, raw_local_context: str):
        parsed = json.loads(raw_local_context)
        return cls(
            base_dir=Path(parsed["base_dir"]),
            area_of_interest_name=parsed.get(
                "area_of_interest_name", cls._unknown_area_of_interest)
        )

    @classmethod
    def create_default(cls):
        """Create a default local context.

        The created instance specifies the current base dir as its base dir

        """

        return cls(
            base_dir=Path(conf.settings_manager.get_value(conf.Setting.BASE_DIR)),
            area_of_interest_name=cls._unknown_area_of_interest
        )

    def serialize(self) -> str:
        return json.dumps(
            {
                "base_dir": str(self.base_dir),
                "area_of_interest_name": self.area_of_interest_name,
            }
        )


@dataclasses.dataclass()
class JobNotes:
    user_notes: str
    local_context: JobLocalContext

    @classmethod
    def deserialize(cls, raw_notes: str):
        separator = conf.settings_manager.get_value(
            conf.Setting.LOCAL_CONTEXT_SEPARATOR)
        user_notes, raw_local_context = raw_notes.partition(separator)[::2]
        if raw_local_context != "":
            local_context = JobLocalContext.deserialize(raw_local_context)
        else:
            local_context = JobLocalContext.create_default()
        return cls(user_notes=user_notes, local_context=local_context)

    def serialize(self) -> str:
        if self.local_context is not None:
            serialized_local_context = self.local_context.serialize()
        else:
            serialized_local_context = ""
        separator = conf.settings_manager.get_value(
            conf.Setting.LOCAL_CONTEXT_SEPARATOR)
        return separator.join(
            (self.user_notes, serialized_local_context))


@dataclasses.dataclass()
class JobParameters:
    task_name: str
    task_notes: JobNotes
    params: typing.Dict

    @classmethod
    def deserialize(cls, raw_params: typing.Dict):
        params = raw_params.copy()
        name = params.pop("task_name", "")
        notes = JobNotes.deserialize(params.pop("task_notes", ""))
        return cls(
            task_name=name,
            task_notes=notes,
            params=params
        )

    def serialize(self) -> typing.Dict:
        result = {
            "task_name": self.task_name,
            "task_notes": self.task_notes.serialize(),
        }
        result.update(self.params)
        return result


@dataclasses.dataclass()
class JobBand:
    metadata: typing.Dict
    name: str
    no_data_value: typing.Optional[float] = -32768.0
    activated: typing.Optional[bool] = True
    add_to_map: typing.Optional[bool] = True

    @classmethod
    def deserialize(cls, raw_band: typing.Dict):
        return cls(
            activated=raw_band["activated"],
            add_to_map=raw_band["add_to_map"],
            metadata=raw_band["metadata"],
            name=raw_band["name"],
            no_data_value=raw_band["no_data_value"]
        )

    def serialize(self) -> typing.Dict:
        return {
            "activated": self.activated,
            "add_to_map": self.add_to_map,
            "metadata": self.metadata,
            "name": self.name,
            "no_data_value": self.no_data_value,
        }


@dataclasses.dataclass()
class JobUrl:
    url: str
    md5_hash: str

    @property
    def decoded_md5_hash(self):
        return binascii.hexlify(base64.b64decode(self.md5_hash)).decode()

    @classmethod
    def deserialize(cls, raw_url: typing.Dict):
        return cls(
            url=raw_url["url"],
            md5_hash=raw_url["md5Hash"]
        )

    def serialize(self) -> typing.Dict:
        return {
            "url": self.url,
            "md5Hash": self.md5_hash
        }


@dataclasses.dataclass()
class JobCloudResults:
    name: str
    bands: typing.List[JobBand]
    urls: typing.List[JobUrl]
    local_paths: typing.List[Path]
    type: JobResult = JobResult.CLOUD_RESULTS

    @classmethod
    def deserialize(cls, raw_results: typing.Dict):
        return cls(
            name=raw_results["name"],
            type=JobResult(raw_results["type"]),
            bands=[JobBand.deserialize(raw_band) for raw_band in raw_results["bands"]],
            urls=[JobUrl.deserialize(raw_url) for raw_url in raw_results["urls"]],
            local_paths=[Path(p) for p in raw_results.get("local_paths", [])]
        )

    def serialize(self) -> typing.Dict:
        return {
            "name": self.name,
            "type": self.type.value,
            "bands": [band.serialize() for band in self.bands],
            "urls": [url.serialize() for url in self.urls],
            "local_paths": [str(p) for p in self.local_paths]
        }


@dataclasses.dataclass()
class TimeSeriesTableResult:
    name: str
    table: typing.List[typing.Dict]
    type: JobResult = JobResult.TIME_SERIES_TABLE

    @classmethod
    def deserialize(cls, raw_results: typing.Dict):
        return cls(
            name=raw_results["name"],
            type=JobResult(raw_results["type"]),
            table=raw_results["table"]
        )

    def serialize(self) -> typing.Dict:
        return {
            "name": self.name,
            "type": self.type.value,
            "table": self.table.copy()
        }


@dataclasses.dataclass()
class JobLocalResults:
    name: str
    bands: typing.List[JobBand]
    local_paths: typing.List[Path]
    type: JobResult = JobResult.LOCAL_RESULTS

    @classmethod
    def deserialize(cls, raw_results: typing.Dict):
        return cls(
            name=raw_results["name"],
            bands=[JobBand.deserialize(raw_band) for raw_band in raw_results["bands"]],
            local_paths=[Path(local_path) for local_path in raw_results["local_paths"]],
        )

    def serialize(self) -> typing.Dict:
        return {
            "name": self.name,
            "type": self.type.value,
            "bands": [band.serialize() for band in self.bands],
            "local_paths": [str(path) for path in self.local_paths]
        }


@dataclasses.dataclass()
class Job:
    id: uuid.UUID
    params: JobParameters
    progress: int
    results: typing.Optional[
        typing.Union[JobCloudResults, JobLocalResults, TimeSeriesTableResult]
    ]
    script: ExecutionScript
    status: JobStatus
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
            type_ = JobResult(raw_results["type"])
        except KeyError:
            log(f"Could not extract type of results from job {raw_job['id']} with raw_results {raw_results!r}")
            results = None
        else:
            if type_ == JobResult.CLOUD_RESULTS:
                results = JobCloudResults.deserialize(raw_results)
            elif type_ == JobResult.LOCAL_RESULTS:
                results = JobLocalResults.deserialize(raw_results)
            elif type_ == JobResult.TIME_SERIES_TABLE:
                results = TimeSeriesTableResult.deserialize(raw_results)
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
            params=JobParameters.deserialize(raw_job["params"]),
            progress=raw_job["progress"],
            results=results,
            script=script,
            status=JobStatus(raw_job["status"]),
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
        if task_name != "":
            name = f"{task_name} ({self.script.name_readable})"
        else:
            name = self.script.name_readable
        return name

    def serialize(self) -> typing.Dict:
        # local scripts are identified by their name, they do not have an id
        script_identifier = (
            str(self.script.id) if self.script.id is not None else self.script.name)
        raw_job = {
            "id": str(self.id),
            "params": self.params.serialize(),
            "progress": self.progress,
            "results": None if self.results is None else self.results.serialize(),
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

    The information returned from the remote shall be enough to at least display Jobs
    which came from a version which is not known locally.

    """

    raw_remote = api.get_script()
    if raw_remote is None:
        return
    else:
        return [ExecutionScript.deserialize_from_remote_response(r) for r in raw_remote]


def get_job_local_script(script_name: str) -> ExecutionScript:
    return conf.KNOWN_SCRIPTS[script_name]


def _get_job_script(script_id: uuid.UUID) -> ExecutionScript:
    try:
        script = [s for s in conf.KNOWN_SCRIPTS.values() if s.id == script_id][0]
    except IndexError:
        log(f"script {script_id!r} is not known locally")
        remote_scripts = get_remote_scripts()
        if remote_scripts is None:
            return
        try:
            script = [s for s in remote_scripts if s.id == script_id][0]
        except IndexError:
            raise RuntimeError(
                f"script {script_id!r} is not known on the remote server")
    return script
