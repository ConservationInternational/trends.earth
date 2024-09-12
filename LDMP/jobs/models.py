"""Job and dataset utilities"""

import enum
import functools
import re
import unicodedata
import uuid

import marshmallow_dataclass
from marshmallow import pre_load
from te_schemas.algorithms import AlgorithmRunMode, ExecutionScript
from te_schemas.jobs import Job as JobBase
from te_schemas.jobs import RemoteScript

from .. import api, conf
from ..logger import log


class SortField(enum.Enum):
    NAME = "name"
    DATE = "date"
    ALGORITHM = "algorithm"
    STATUS = "status"


class TypeFilter(enum.Enum):
    ALL = "all"
    RASTER = "raster"
    VECTOR = "vector"


def _slugify(value, allow_unicode=False):
    """
    Taken from https://github.com/django/django/blob/master/django/utils/text.py
    Convert to ASCII if 'allow_unicode' is False. Convert spaces or repeated
    dashes to single dashes. Remove characters that aren't alphanumerics,
    underscores, or hyphens. Convert to lowercase. Also strip leading and
    trailing whitespace, dashes, and underscores.
    """
    value = str(value)

    if allow_unicode:
        value = unicodedata.normalize("NFKC", value)
    else:
        value = (
            unicodedata.normalize("NFKD", value)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
    value = re.sub(r"[^\w\s-]", "", value.lower())

    return re.sub(r"[-\s]+", "-", value).strip("-_")


@marshmallow_dataclass.dataclass
class Job(JobBase):
    @pre_load
    def set_script_name_version(self, data, **kwargs):
        script_id = data.pop("script_id", None)
        params_script = data["params"].pop("script", None)

        if not data.get("script"):
            if params_script:
                script = ExecutionScript.Schema().load(params_script)
            elif script_id:
                script = _get_job_script(script_id)

                if script is None:
                    log(f"Failed to get script by id for {script_id}")
                    script = get_job_local_script(data["script_name"])
                else:
                    log(f"Got script from id {script_id}")
                    script = ExecutionScript(
                        script_id, run_mode=AlgorithmRunMode.NOT_APPLICABLE
                    )
            else:
                script = ExecutionScript(
                    "Unknown script", run_mode=AlgorithmRunMode.NOT_APPLICABLE
                )

            data["script"] = ExecutionScript.Schema().dump(script)

        script_name_regex = re.compile("([0-9a-zA-Z -]*)(?: *)([0-9]+(_[0-9]+)+)")
        matches = script_name_regex.search(data["script"].get("name"))

        if matches:
            data["script"]["name"] = matches.group(1).rstrip()
            data["script"]["version"] = matches.group(2).replace("_", ".")

        return data

    def get_basename(self, with_uuid=False):
        separator = "_"
        name_fragments = []
        task_name = _slugify(self.task_name)

        if task_name:
            name_fragments.append(task_name)

        if self.script:
            name_fragments.append(self.script.name)

        if self.local_context.area_of_interest_name:
            name_fragments.append(self.local_context.area_of_interest_name)

        if len(name_fragments) == 0 or with_uuid:
            name_fragments.append(str(self.id))

        return separator.join(name_fragments)

    def get_display_name(self):
        job_name_parts = []
        if self.task_name:
            job_name_parts.append(self.task_name)
        elif self.local_context.area_of_interest_name:
            job_name_parts.append(self.local_context.area_of_interest_name)
        elif self.script.name:
            job_name_parts.append(self.script.name)
        return " - ".join(job_name_parts)


@functools.lru_cache(
    maxsize=None
)  # not using functools.cache, as it was only introduced in Python 3.9
def get_remote_scripts():
    """Query the remote server for existing scripts

    The information returned from the remote shall be enough to at least
    display Jobs which came from a version which is not known locally.

    """

    raw_remote = api.default_api_client.get_script()

    if raw_remote is None:
        return
    else:
        return [RemoteScript.Schema().load(r) for r in raw_remote]


def get_job_local_script(script_name: str) -> ExecutionScript:
    return conf.KNOWN_SCRIPTS.get(script_name, None)


def _get_script_by_id_from_remote(script_id: str) -> ExecutionScript:
    remote_scripts = get_remote_scripts()
    if remote_scripts is None:
        return
    try:
        script = [s for s in remote_scripts if str(s.id) == str(script_id)][0]
    except IndexError:
        log(
            f"script {script_id!r} not found on remote server "
            "by id - checking for matches by slug"
        )
        try:
            script = [s for s in remote_scripts if str(s.slug) == str(script_id)][0]
        except IndexError:
            log(f"script {script_id!r} is not known on remote")
            raise IndexError
    script = ExecutionScript.Schema().load(RemoteScript.Schema().dump(script))

    return script


def _get_script_by_id_from_local(script_id: str) -> ExecutionScript:
    try:
        script = [s for s in conf.KNOWN_SCRIPTS.values() if s.id == script_id][0]
    except IndexError:
        log(f"script {script_id!r} is not known locally")
        raise IndexError

    return script


def _get_job_script(script_id: uuid.UUID) -> ExecutionScript:
    try:
        script = _get_script_by_id_from_local(script_id)
    except IndexError:
        log(f"script {script_id!r} is not known locally - checking remote")
        try:
            script = _get_script_by_id_from_remote(script_id)
        except IndexError:
            log(f"script {script_id!r} is not known")
            raise IndexError

    return script
