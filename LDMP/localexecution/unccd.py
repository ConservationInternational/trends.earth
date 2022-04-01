import dataclasses
import datetime as dt
import re
import tarfile
import zipfile
from pathlib import Path
from typing import Dict
from typing import Optional

import marshmallow_dataclass
import numpy as np
import qgis.core
from osgeo import gdal
from osgeo import osr
from PyQt5 import QtWidgets
from te_schemas import land_cover
from te_schemas import reporting
from te_schemas import SchemaBase
from te_schemas import schemas
from te_schemas.results import FileResults
from te_schemas.results import URI

from .. import __release_date__
from .. import __revision__
from .. import __version__
from .. import areaofinterest
from .. import data_io
from ..jobs.models import Job
from ..logger import log


@dataclasses.dataclass()
class UNCCDReportWidgets:
    """Combo boxes and methods used in UNCCD report generation"""

    combo_dataset_so1_so2: data_io.WidgetDataIOSelectTEDatasetExisting
    combo_dataset_so3: data_io.WidgetDataIOSelectTEDatasetExisting

    def populate(self):
        self.combo_dataset_so1_so2.populate()
        self.combo_dataset_so3.populate()


@dataclasses.dataclass()
class UNCCDReportInputInfo:
    path: Path
    summary_path: Path
    all_paths: Path


def _get_unccd_report_inputs(combo_box):
    path = combo_box.get_current_data_file()
    summary_path = [
        p
        for p in path.parents[0].glob("*.json")
        if bool(re.search("_summary.json", str(p)))
    ]
    all_paths = [p for p in path.parents[0].glob("*")]
    all_files = [x for x in all_paths if x.is_file()]
    return UNCCDReportInputInfo(path, summary_path, all_files)


def get_main_unccd_report_job_params(
    task_name: str,
    combo_dataset_so1_so2: data_io.WidgetDataIOSelectTEDatasetExisting,
    combo_dataset_so3: data_io.WidgetDataIOSelectTEDatasetExisting,
    include_so1_so2: bool,
    include_so3: bool,
    task_notes: Optional[str] = "",
) -> Dict:

    params = {
        "task_name": task_name,
        "task_notes": task_notes
    }

    if include_so1_so2:
        so1_so2_inputs = _get_unccd_report_inputs(combo_dataset_so1_so2)
        params.update({
            "so1_so2_path": str(so1_so2_inputs.path),
            "so1_so2_summary_path": str(so1_so2_inputs.summary_path),
            "so1_so2_all_paths": [str(p) for p in so1_so2_inputs.all_paths],
        })

    if include_so3:
        so3_inputs = _get_unccd_report_inputs(combo_dataset_so3)
        params.update({
            "so3_path": str(so3_inputs.path),
            "so3_summary_path": str(so3_inputs.summary_path),
            "so3_all_paths": [str(p) for p in so3_inputs.all_paths],
        })

    return params


def _make_tar_gz(out_tar_gz, in_files):
    with tarfile.open(out_tar_gz, "w:gz") as tar:
        for in_file in in_files:
            tar.add(in_file, arcname=in_file.name)


def compute_unccd_report(
    report_job: Job,
    area_of_interest: areaofinterest.AOI,
    job_output_path: Path,
    dataset_output_path: Path,
) -> Job:
    """Generate UNCCD report from SO1/SO2 and SO3 datasets"""

    params = report_job.params

    tar_gz_path = job_output_path.parent / f"{job_output_path.stem}.tar.gz"

    paths = []
    if params["include_so1_so2"]:
        paths += [Path(p) for p in params["so1_so2_all_paths"]]
    if params["include_so3"]:
        paths += [Path(p) for p in params["so3_all_paths"]]

    if params["affected_only"]:
        # TODO: Finish this should to add this flag to the JSONs within the report only
        # if selected on the window. But to do this will need to re-read the JSONs and
        # then modify them before writing copies to a temp file
        pass

    log(f"Building tar.gz file with {paths}...")
    _make_tar_gz(tar_gz_path, paths)

    report_job.results

    report_job.results = FileResults(
        name="unccd_report",
        uri=URI(uri=tar_gz_path, type="local"),
    )
    report_job.results.data_path = tar_gz_path
    report_job.end_date = dt.datetime.now(dt.timezone.utc)
    report_job.progress = 100

    return report_job
