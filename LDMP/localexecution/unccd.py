import os
import dataclasses
import datetime as dt
import enum
import json
import tempfile
import re
import shutil
import zipfile
import tarfile

from typing import (
    List,
    Dict,
    Tuple,
    Optional
)
from pathlib import Path

from PyQt5 import QtWidgets

import numpy as np
from osgeo import (
    gdal,
    osr,
)
import qgis.core

from te_schemas import (
    schemas,
    land_cover,
    reporting,
    SchemaBase
)

from ..conf import (
    settings_manager,
    Setting
)

from .. import (
    areaofinterest,
    data_io,
    tr,
    utils,
    worker,
    __version__,
    __revision__,
    __release_date__
)
from ..jobs import Job
from ..logger import log

import marshmallow_dataclass


@dataclasses.dataclass()
class UNCCDReportWidgets:
    '''Combo boxes and methods used in UNCCD report generation'''
    combo_dataset_so1_so2: data_io.WidgetDataIOSelectTEDatasetExisting
    combo_dataset_so3: data_io.WidgetDataIOSelectTEDatasetExisting
    combo_layer_jrc_vulnerability: data_io.WidgetDataIOSelectTELayerExisting

    def populate(self):
        self.combo_dataset_so1_so2.populate()
        self.combo_dataset_so3.populate()
        self.combo_layer_jrc_vulnerability.populate()


@dataclasses.dataclass()
class UNCCDReportInputInfo:
    path: Path
    summary_path: Path
    all_paths: Path


def _get_unccd_report_inputs(combo_box):
    path = combo_box.get_current_data_file()
    summary_path = [
        p for p in path.parents[0].glob('*.json')
        if bool(re.search('_summary.json', str(p)))
    ]
    all_paths = [
        p for p in path.parents[0].glob('*')
    ]
    return UNCCDReportInputInfo(
        path,
        summary_path,
        all_paths
    )

def get_main_unccd_report_job_params(
        task_name: str,
        combo_dataset_so1_so2: data_io.WidgetDataIOSelectTEDatasetExisting,
        combo_dataset_so3: data_io.WidgetDataIOSelectTEDatasetExisting,
        combo_layer_jrc_vulnerability: data_io.WidgetDataIOSelectTELayerExisting,
        task_notes: Optional[str] = "",
) -> Dict:

    so1_so2_inputs = _get_unccd_report_inputs(combo_dataset_so1_so2)
    so3_inputs = _get_unccd_report_inputs(combo_dataset_so3)

    return {
        "task_name": task_name,
        "task_notes": task_notes,
        "so1_so2_path": str(so1_so2_inputs.path),
        "so1_so2_summary_path": str(so1_so2_inputs.summary_path),
        "so1_so2_all_paths": [str(p) for p in so1_so2_inputs.all_paths],
        "so3_path": str(so3_inputs.path),
        "so3_summary_path": str(so3_inputs.summary_path),
        "so3_all_paths": [str(p) for p in so3_inputs.all_paths]
    }


def _make_zip(out_zip, in_files):
    with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for in_file in in_files:
            zf.write(in_file, in_file.name)


def _make_tar_gz(out_tar_gz, in_files):
    with tarfile.open(out_tar_gz, "w:gz") as tar:
        for in_file in in_files:
            tar.add(in_file, arcname=in_file.name)

def compute_unccd_report(
    report_job: Job,
    area_of_interest: areaofinterest.AOI
) -> Job:
    """Generate UNCCD report from SO1/SO2 and SO3 datasets"""

    params = report_job.params

    job_output_path, _ = utils.get_local_job_output_paths(report_job)

    tar_gz_path = job_output_path.parent / f"{job_output_path.stem}.tar.gz"

    log('Building tar.gz file...')
    _make_tar_gz(
        tar_gz_path,
        [Path(p) for p in params['so1_so2_all_paths']] + [Path(p) for p in params['so3_all_paths']]
    )
    
    # summary_json_output_path = job_output_path.parent / f"{job_output_path.stem}_summary.json"
    # save_reporting_json(
    #     summary_json_output_path,
    #     summary_table,
    #     report_job.params,
    #     report_job.task_name,
    #     area_of_interest,
    #     summary_table_stable_kwargs
    # )

    report_job.results.data_path = tar_gz_path
    report_job.end_date = dt.datetime.now(dt.timezone.utc)
    report_job.progress = 100

    return report_job
