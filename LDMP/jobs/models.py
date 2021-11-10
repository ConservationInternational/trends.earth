"""Job and dataset utilities"""

import enum
import functools
import uuid
import re
from pathlib import Path

from .. import (
    api,
    conf,
)
from ..logger import log

import marshmallow_dataclass
from marshmallow import pre_load

from te_schemas.jobs import Job as JobBase
from te_schemas.jobs import RemoteScript
from te_schemas.algorithms import AlgorithmRunMode, ExecutionScript


class SortField(enum.Enum):
    NAME = 'name'
    DATE = 'date'
    ALGORITHM = 'algorithm'
    STATUS = 'status'


@marshmallow_dataclass.dataclass
class Job(JobBase):
    @pre_load
    def set_script_name_version(self, data, **kwargs):
        script_id = data.pop('script_id', None)
        params_script = data['params'].pop('script', None)
        if not data.get('script'):
            if params_script:
                script = ExecutionScript.Schema().load(params_script)
            elif script_id:
                script = _get_job_script(script_id)
                if script is None:
                    log(f"Failed to get script by id for {script_id}")
                    script = get_job_local_script(data["script_name"])
                else:
                    log(f"Failed to get script by id for {script_id}")
                    script = ExecutionScript(
                        script_id, run_mode=AlgorithmRunMode.NOT_APPLICABLE)
            else:
                script = ExecutionScript(
                    "Unknown script", run_mode=AlgorithmRunMode.NOT_APPLICABLE)

            data['script'] = ExecutionScript.Schema().dump(script)

        script_name_regex = re.compile('([0-9a-zA-Z -]*)(?: *)([0-9]+(_[0-9]+)+)')
        matches = script_name_regex.search(data['script'].get('name'))
        if matches:
            data['script']['name'] = matches.group(1).rstrip()
            data['script']['version'] = matches.group(2).replace('_', '.')

        return data


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
            RemoteScript.Schema().load(r)
            for r in raw_remote
        ]


def get_job_local_script(script_name: str) -> ExecutionScript:
    return conf.KNOWN_SCRIPTS.get(script_name, None)


def _get_script_by_id_from_remote(script_id: str) -> ExecutionScript:
    remote_scripts = get_remote_scripts()
    log(f'remote_scripts: {remote_scripts}')
    if remote_scripts is None:
        return
    try:
        script = [s for s in remote_scripts if str(s.id) == str(script_id)][0]
    except IndexError:
        log(f"script {script_id!r} not found on remote server "
            "by id - checking for matches by slug")
        try:
            script = [s for s in remote_scripts if str(s.slug) == str(script_id)][0]
        except IndexError:
            log(f"script {script_id!r} is not known on remote")
            raise IndexError
    script = ExecutionScript.Schema().load(
        RemoteScript.Schema().dump(script)
    )
    return script


def _get_script_by_id_from_local(script_id: str) -> ExecutionScript:
    try:
        script = [
            s for s in conf.KNOWN_SCRIPTS.values() if s.id == script_id
        ][0]
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
