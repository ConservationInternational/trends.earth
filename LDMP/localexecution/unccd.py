import dataclasses
import json
import re
import tarfile
import tempfile
from pathlib import Path
from typing import Dict
from typing import Optional

from osgeo import ogr
from te_schemas import reporting
from te_schemas.error_recode import ErrorRecodePolygons
from te_schemas.results import FileResults
from te_schemas.results import URI

from .. import areaofinterest
from .. import data_io
from ..jobs.models import Job
from ..logger import log


@dataclasses.dataclass()
class UNCCDReportWidgets:
    """Combo boxes and methods used in UNCCD report generation"""

    combo_dataset_so1_so2: data_io.WidgetDataIOSelectTEDatasetExisting
    combo_dataset_error_recode: data_io.WidgetDataIOSelectTEDatasetExisting
    combo_dataset_so3: data_io.WidgetDataIOSelectTEDatasetExisting

    def populate(self):
        self.combo_dataset_so1_so2.populate()
        self.combo_dataset_so3.populate()
        self.combo_dataset_error_recode.populate()


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
    ][0]
    all_paths = [p for p in path.parents[0].glob("*")]
    all_files = [x for x in all_paths if x.is_file()]
    return UNCCDReportInputInfo(path, summary_path, all_files)


def get_main_unccd_report_job_params(
    task_name: str,
    combo_dataset_so1_so2: data_io.WidgetDataIOSelectTEDatasetExisting,
    combo_dataset_so3: data_io.WidgetDataIOSelectTEDatasetExisting,
    combo_dataset_error_recode: data_io.WidgetDataIOSelectTEDatasetExisting,
    include_so1_so2: bool,
    include_so3: bool,
    include_error_recode: bool,
    task_notes: Optional[str] = "",
) -> Dict:
    params = {"task_name": task_name, "task_notes": task_notes}

    if include_so1_so2:
        so1_so2_inputs = _get_unccd_report_inputs(combo_dataset_so1_so2)
        params.update(
            {
                "so1_so2_path": str(so1_so2_inputs.path),
                "so1_so2_summary_path": str(so1_so2_inputs.summary_path),
                "so1_so2_all_paths": [str(p) for p in so1_so2_inputs.all_paths],
            }
        )

    if include_so3:
        so3_inputs = _get_unccd_report_inputs(combo_dataset_so3)
        params.update(
            {
                "so3_path": str(so3_inputs.path),
                "so3_summary_path": str(so3_inputs.summary_path),
                "so3_all_paths": [str(p) for p in so3_inputs.all_paths],
            }
        )

    if include_error_recode:
        params.update(
            {
                "error_recode_path": str(
                    combo_dataset_error_recode.get_current_data_file()
                )
            }
        )

    return params


def _make_tar_gz(out_tar_gz, in_files):
    with tarfile.open(out_tar_gz, "w:gz") as tar:
        for in_file in in_files:
            tar.add(in_file, arcname=in_file.name)


def _set_affected_areas_only(in_file, out_file, schema):
    with open(in_file) as f:
        summary = schema.load(json.load(f))
    summary.metadata.affected_areas_only = True
    out_json = json.loads(schema.dumps(summary))
    with open(out_file, "w") as f:
        json.dump(out_json, f, indent=4)
    return out_file


def _get_error_recode_polygons(in_file):
    ds_in = ogr.Open(in_file)
    layer_in = ds_in.GetLayer()
    out_file = tempfile.mktemp(suffix=".geojson")
    print(out_file)
    out_ds = ogr.GetDriverByName("GeoJSON").CreateDataSource(out_file)
    layer_out = out_ds.CopyLayer(layer_in, "error_recode")
    del layer_out
    del out_ds
    with open(out_file) as f:
        polys = ErrorRecodePolygons.Schema().load(json.load(f))
    return polys


def _set_error_recode(in_file, out_file, error_recode_polys):
    with open(in_file) as f:
        summary = reporting.TrendsEarthLandConditionSummary.Schema().load(json.load(f))

    # Add polygons
    summary.land_condition["integrated"].error_recode = error_recode_polys

    # Keys fields in the summary json to those in the error recode polygons
    field_key = {
        "No data": "nodata_pct",
        "Degraded": "degraded_pct",
        "Stable": "stable_pct",
        "Improved": "improved_pct",
    }

    sdg_areas = {
        item.name: item.area for item in summary.land_condition["integrated"].sdg.areas
    }
    total_area_initial = sum(sdg_areas.values())
    for feat in error_recode_polys.features:
        for recode_from, recode_to in zip(
            ["Degraded", "Stable", "Improved"],
            [
                feat.properties.recode_deg_to,
                feat.properties.recode_stable_to,
                feat.properties.recode_imp_to,
            ],
        ):
            # *.01 to convert hectares to sq km, and /100 to convert from
            # percent to a fraction
            area = (
                feat.properties.stats["sdg"]["area_ha"]
                * 0.01
                * (feat.properties.stats["sdg"][field_key[recode_from]] / 100)
            )
            if recode_to is None:
                continue
            elif recode_to == -32768:
                sdg_areas[recode_from] -= area
                sdg_areas["No data"] += area
            elif recode_to == -1:
                sdg_areas[recode_from] -= area
                sdg_areas["Degraded"] += area
            elif recode_to == 0:
                sdg_areas[recode_from] -= area
                sdg_areas["Stable"] += area
            elif recode_to == 1:
                sdg_areas[recode_from] -= area
                sdg_areas["Improved"] += area

    assert all(
        value >= 0 for value in sdg_areas.values()
    ), f"sdg_areas should all be greater than zero, but values are {sdg_areas}"
    total_area_final = sum(sdg_areas.values())
    assert abs(total_area_initial - total_area_final) < 0.001, (
        f"total_area_initial ({total_area_initial}) differs "
        f"from total_area_final ({total_area_final})"
    )

    summary.land_condition["integrated"].sdg_error_recode = reporting.AreaList(
        "SDG Indicator 15.3.1 (progress since baseline), with errors recoded",
        "sq km",
        [reporting.Area(name, area) for name, area in sdg_areas.items()],
    )
    out_json = json.loads(
        reporting.TrendsEarthLandConditionSummary.Schema().dumps(summary)
    )
    with open(out_file, "w") as f:
        json.dump(out_json, f, indent=4)
    return out_file


def compute_unccd_report(
    report_job: Job,
    area_of_interest: areaofinterest.AOI,
    job_output_path: Path,
    dataset_output_path: Path,
) -> Job:
    """Generate UNCCD report from SO1/SO2 and SO3 datasets"""

    params = report_job.params

    tar_gz_path = job_output_path.parent / f"{job_output_path.stem}.tar.gz"

    with tempfile.TemporaryDirectory() as temp_dir:
        paths = []
        if params["include_error_recode"]:
            orig_summary_path_so1_so2 = Path(params["so1_so2_summary_path"])
            new_summary_path_so1_so2 = Path(temp_dir) / orig_summary_path_so1_so2.name
            error_recode_polys = _get_error_recode_polygons(params["error_recode_path"])
            _set_error_recode(
                orig_summary_path_so1_so2, new_summary_path_so1_so2, error_recode_polys
            )
            # Make sure this modified file is used as basis for the SO1/SO2 summary
            # below (if affected_only is set)
            params["so1_so2_summary_path"] = str(new_summary_path_so1_so2)
            # Make sure this mofified file is used if affected_areas_only is NOT set
            for i in range(len(params["so1_so2_all_paths"])):
                if params["so1_so2_all_paths"][i] == str(orig_summary_path_so1_so2):
                    log(
                        f'Replacing {str(params["so1_so2_all_paths"][i])} with '
                        f"{str(new_summary_path_so1_so2)}"
                    )
                    params["so1_so2_all_paths"][i] = str(new_summary_path_so1_so2)

            params["so1_so2_summary_path"] = str(new_summary_path_so1_so2)

        if params["affected_only"]:
            if params["include_so1_so2"]:
                summary_path_so1_so2 = Path(params["so1_so2_summary_path"])
                paths += [
                    _set_affected_areas_only(
                        summary_path_so1_so2,
                        Path(temp_dir) / summary_path_so1_so2.name,
                        reporting.TrendsEarthLandConditionSummary.Schema(),
                    )
                ]
            if params["include_so3"]:
                summary_path_so3 = Path(params["so3_summary_path"])
                paths += [
                    _set_affected_areas_only(
                        summary_path_so3,
                        Path(temp_dir) / summary_path_so3.name,
                        reporting.TrendsEarthDroughtSummary.Schema(),
                    )
                ]
            for path in paths:
                log(f"{path} exists {path.exists()} (in context manager)")
        else:
            if params["include_so1_so2"]:
                paths += [Path(p) for p in params["so1_so2_all_paths"]]
            if params["include_so3"]:
                paths += [Path(p) for p in params["so3_all_paths"]]

        for path in paths:
            log(f"{path} exists: {path.exists()}")
        log(f"Building tar.gz file with {paths}...")
        _make_tar_gz(tar_gz_path, paths)

    return FileResults(
        name="unccd_report",
        uri=URI(uri=tar_gz_path),
    )
