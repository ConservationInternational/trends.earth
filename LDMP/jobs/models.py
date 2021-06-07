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
    log,
)
from ..conf import (
    Setting,
    settings_manager,
)


class SortField(enum.Enum):
    NAME = 'name'
    DATE = 'date'
    ALGORITHM = 'algorithm'
    STATUS = 'status'


class ScriptStatus(enum.Enum):
    SUCCESS = "SUCCESS"
    FAIL = "FAIL"


class JobStatus(enum.Enum):
    PENDING = "PENDING"
    FINISHED = "FINISHED"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    DELETED = "DELETED"
    DOWNLOADED = "DOWNLOADED"


class JobResult(enum.Enum):
    CLOUD_RESULTS = "CloudResults"
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

    @classmethod
    def deserialize(cls, raw_local_context: str):
        parsed = json.loads(raw_local_context)
        return cls(base_dir=Path(parsed["base_dir"]))

    @classmethod
    def create_default(cls):
        """Create a default local context.

        The created instance specifies the current base dir as its base dir

        """

        return cls(base_dir=Path(settings_manager.get_value(Setting.BASE_DIR)))

    def serialize(self) -> str:
        return json.dumps(
            {
                "base_dir": str(self.base_dir),
            }
        )


@dataclasses.dataclass()
class JobNotes:
    user_notes: str
    local_context: JobLocalContext

    _local_context_separator: str = "-*-*-*-local_context-*-*-*-"

    @classmethod
    def deserialize(cls, raw_notes: str):
        user_notes, raw_local_context = raw_notes.partition(
            cls._local_context_separator)[::2]
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
        return self._local_context_separator.join(
            (self.user_notes, serialized_local_context))


@dataclasses.dataclass()
class JobParameters:
    task_name: str
    task_notes: JobNotes
    params: typing.Dict

    @classmethod
    def deserialize(cls, raw_params: typing.Dict):
        params = raw_params.copy()
        name = params.pop("task_name")
        notes = JobNotes.deserialize(params.pop("task_notes"))
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
    activated: bool
    add_to_map: bool
    metadata: typing.Dict
    name: str
    no_data_value: float

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
    type: JobResult
    bands: typing.List[JobBand]
    urls: typing.List[JobUrl]
    local_paths: typing.List[Path]

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
    type: JobResult
    table: typing.List[typing.Dict]

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
class Job:
    id: uuid.UUID
    params: JobParameters
    progress: int
    results: typing.Union[JobCloudResults, TimeSeriesTableResult]
    script: RemoteScript
    # script_id: uuid.UUID
    status: JobStatus
    user_id: uuid.UUID
    start_date: dt.datetime
    end_date: typing.Optional[dt.datetime] = None

    _date_format: str = "%Y-%m-%dT%H:%M:%S.%f"

    @classmethod
    def deserialize(cls, raw_job: typing.Dict):
        raw_end_date = raw_job.get("end_date")
        if raw_end_date is not None:
            end_date = dt.datetime.strptime(
                raw_end_date, cls._date_format).replace(tzinfo=dt.timezone.utc)
        else:
            end_date = None

        raw_results = raw_job["results"]
        try:
            type_ = JobResult(raw_results["type"])
        except KeyError:
            log(f"Could not extract type of results from {raw_results!r}")
            results = None
        else:
            if type_ == JobResult.CLOUD_RESULTS:
                results = JobCloudResults.deserialize(raw_results)
            elif type_ == JobResult.TIME_SERIES_TABLE:
                results = TimeSeriesTableResult.deserialize(raw_results)
            else:
                raise RuntimeError(f"Invalid results type: {type_!r}")
        script_id = uuid.UUID(raw_job["script_id"])
        known_scripts = get_remote_scripts()
        script = [script for script in known_scripts if script.id == script_id][0]
        return cls(
            id=uuid.UUID(raw_job["id"]),
            params=JobParameters.deserialize(raw_job["params"]),
            progress=raw_job["progress"],
            results=results,
            script=script,
            # script_id=uuid.UUID(raw_job["script_id"]),
            status=JobStatus(raw_job["status"]),
            user_id=uuid.UUID(raw_job["user_id"]),
            start_date=dt.datetime.strptime(
                raw_job["start_date"],
                cls._date_format
            ).replace(tzinfo=dt.timezone.utc),
            end_date=end_date
        )

    def serialize(self) -> typing.Dict:
        raw_job = {
            "id": str(self.id),
            "params": self.params.serialize(),
            "progress": self.progress,
            "results": None if self.results is None else self.results.serialize(),
            # "script_id": str(self.script_id),
            "script_id": str(self.script.id),
            "status": self.status.value,
            "user_id": str(self.user_id),
            "start_date": self.start_date.strftime(self._date_format)
        }
        if self.end_date is not None:
            raw_job["end_date"] = self.end_date.strftime(self._date_format)
        return raw_job


@functools.lru_cache(maxsize=None)  # not using functools.cache, as it was only introduced in Python 3.9
def get_remote_scripts():
    return [RemoteScript.deserialize(raw_script) for raw_script in api.get_script()]
