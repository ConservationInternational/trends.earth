import dataclasses
import json
import re
import tarfile
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from osgeo import ogr
from te_schemas import reporting
from te_schemas.error_recode import ErrorRecodePolygons
from te_schemas.results import URI, FileResults

from .. import areaofinterest, data_io
from ..jobs.models import Job
from ..logger import log


def _infer_periods_affected_from_summary(summary_path: Path) -> List[str]:
    """Infer which periods exist in the SO1/SO2 summary and map them to the
    allowed names required by ErrorRecodeProperties.periods_affected
    ("baseline", "reporting_1", "reporting_2").
    """
    try:
        with open(summary_path, "r") as f:
            summary = json.load(f)
    except Exception:
        # Fall back to baseline only if we cannot read the summary
        return ["baseline"]

    periods: List[str] = []
    lc = summary.get("land_condition", {})
    if not isinstance(lc, dict):
        return ["baseline"]

    if "baseline" in lc or True:
        if "baseline" not in periods:
            periods.append("baseline")

    import re as _re

    for key in lc.keys():
        sk = str(key).lower()
        m_prog = _re.match(r"^progress(?:_(\d+))?$", sk)
        m_report = _re.match(r"^report_(\d+)$", sk)
        m_reporting = _re.match(r"^reporting_(\d+)$", sk)
        if m_prog:
            idx = int(m_prog.group(1)) if m_prog.group(1) else 1
            val = f"reporting_{idx}"
        elif m_report:
            idx = int(m_report.group(1))
            val = f"reporting_{idx}"
        elif m_reporting:
            idx = int(m_reporting.group(1))
            val = f"reporting_{idx}"
        else:
            continue
        if val not in periods:
            periods.append(val)

    reporting = [p for p in periods if p.startswith("reporting_")]
    if len(reporting) > 2:
        reporting = reporting[:2]
        periods = [p for p in periods if p == "baseline"] + reporting

    return periods or ["baseline"]


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


def _aoi_to_geojson_dict(aoi) -> dict:
    if hasattr(aoi, "geojson"):
        gj = getattr(aoi, "geojson")
        if isinstance(gj, str):
            return json.loads(gj)
        return gj
    raise ValueError("Cannot export AOI to GeoJSON")


def _write_aoi_geojson(summary_path, out_path: Path) -> Path:
    """Write AOI as GeoJSON to out_path and return the path."""
    aoi = None
    with open(summary_path) as f:
        summary = reporting.TrendsEarthLandConditionSummary.Schema().load(json.load(f))
        aoi = summary.metadata.area_of_interest
    geojson_dict = _aoi_to_geojson_dict(aoi)
    with open(out_path, "w") as f:
        json.dump(geojson_dict, f, indent=2)
    return out_path


def _write_summary_without_aoi(summary_path, out_path: Path) -> Path:
    """Write summary without AOI."""
    with open(summary_path) as f:
        summary = json.load(f)

    if "metadata" in summary:
        summary["metadata"].pop("area_of_interest")

    summary = _rename_progress_to_report_sections(summary)

    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    return out_path


def _rename_progress_to_report_sections(summary: dict) -> dict:
    """Rename keys like 'progress', 'progress_2', ... to 'report_1', 'report_2', ..."""

    def _rename_in_section(section_dict):
        if not isinstance(section_dict, dict):
            return section_dict
        new_section = {}
        progress_entries = []
        for k, v in section_dict.items():
            m = re.match(r"^progress(?:_(\d+))?$", str(k), flags=re.IGNORECASE)
            if m:
                idx = int(m.group(1)) if m.group(1) else 1
                progress_entries.append((idx, v))
            else:
                new_section[k] = v
        if progress_entries:
            progress_entries.sort(key=lambda x: x[0])
            for idx, val in progress_entries:
                new_section[f"report_{idx}"] = val
        return new_section

    for top_key in ("land_condition", "affected_population"):
        if top_key in summary and isinstance(summary[top_key], dict):
            summary[top_key] = _rename_in_section(summary[top_key])
    return summary


def _set_affected_areas_only(in_file, out_file, schema):
    with open(in_file) as f:
        summary = schema.load(json.load(f))
    summary.metadata.affected_areas_only = True
    out_json = json.loads(schema.dumps(summary))
    # Rename progress* keys to report_* in relevant sections
    out_json = _rename_progress_to_report_sections(out_json)
    with open(out_file, "w") as f:
        json.dump(out_json, f, indent=4)
    return out_file


def _get_error_recode_polygons(in_file, periods_affected=None):
    ds_in = ogr.Open(in_file)
    if ds_in is None:
        raise RuntimeError(f"Unable to open vector dataset: {in_file}")

    layer_in = ds_in.GetLayerByName("error_recode")
    if layer_in is None:
        chosen = None
        try:
            layer_count = ds_in.GetLayerCount()
        except Exception:
            layer_count = 0
        for i in range(layer_count):
            try:
                lyr = ds_in.GetLayerByIndex(i)
            except Exception:
                lyr = None
            if lyr is None:
                continue
            try:
                if lyr.GetFeatureCount() > 0:
                    chosen = lyr
                    break
            except Exception:
                continue
        if chosen is None and layer_count > 0:
            try:
                chosen = ds_in.GetLayerByIndex(0)
            except Exception:
                chosen = None
        layer_in = chosen

    if layer_in is None:
        raise RuntimeError(f"No readable layers found in: {in_file}")

    try:
        src_name = layer_in.GetName()
    except Exception:
        src_name = "<unknown>"

    try:
        feat_count = layer_in.GetFeatureCount()
    except Exception:
        feat_count = -1

    if feat_count == 0:
        log(f"Error recode source layer '{src_name}' has 0 features")
        empty_fc = {
            "type": "FeatureCollection",
            "name": "error_recode",
            "crs": {
                "type": "name",
                "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
            },
            "features": [],
        }
        return ErrorRecodePolygons.Schema().load(empty_fc)

    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td) / "error_recode.geojson"
        driver = ogr.GetDriverByName("GeoJSON")
        if tmp_path.exists():
            try:
                driver.DeleteDataSource(str(tmp_path))
            except Exception:
                pass
        out_ds = driver.CreateDataSource(str(tmp_path))
        if out_ds is None:
            raise RuntimeError("Failed to create temporary GeoJSON data source")
        out_ds.CopyLayer(layer_in, "error_recode")
        out_ds = None
        ds_in = None
        with open(tmp_path, "r") as f:
            as_json = json.load(f)
            try:
                for feat in as_json.get("features", []):
                    props = feat.get("properties")
                    if props is None:
                        feat["properties"] = {}
                        props = feat["properties"]
                    val = props.get("periods_affected")
                    if isinstance(val, str):
                        val_list = [val]
                    elif isinstance(val, (list, tuple)):
                        val_list = [x for x in val if isinstance(x, str)]
                    else:
                        val_list = []
                    val_list = [x for x in val_list if "baseline" in x or "report" in x]
                    if not val_list:
                        if periods_affected:
                            props["periods_affected"] = periods_affected
                        else:
                            props["periods_affected"] = ["baseline"]
                    else:
                        props["periods_affected"] = val_list
            except Exception:
                pass
            polys = ErrorRecodePolygons.Schema().load(as_json)

    try:
        parsed_count = len(polys.features)
    except Exception:
        parsed_count = -1

    if feat_count > 0 and parsed_count == 0:
        layer_names = []
        try:
            ds_check = ogr.Open(in_file)
            if ds_check:
                for i in range(ds_check.GetLayerCount()):
                    try:
                        layer_names.append(ds_check.GetLayerByIndex(i).GetName())
                    except Exception:
                        continue
        except Exception:
            pass
        raise RuntimeError(
            f"Layer '{src_name}' in '{in_file}' reported {feat_count} features "
            f"but parsed 0. Available layers: {layer_names}. "
        )
    return polys


def _set_error_recode(in_file, out_file, error_recode_polys):
    with open(in_file) as f:
        summary = reporting.TrendsEarthLandConditionSummary.Schema().load(json.load(f))

    lc = summary.land_condition
    key_to_norm = {}
    norm_to_key = {}

    for k in lc.keys():
        sk = str(k).lower()
        if sk == "baseline":
            norm = "baseline"
        else:
            m_prog = re.match(r"^progress(?:_(\d+))?$", sk)
            m_report = re.match(r"^report_(\d+)$", sk)
            m_reporting = re.match(r"^reporting_(\d+)$", sk)
            if m_prog:
                idx = int(m_prog.group(1)) if m_prog.group(1) else 1
                norm = f"reporting_{idx}"
            elif m_report:
                idx = int(m_report.group(1))
                norm = f"reporting_{idx}"
            elif m_reporting:
                idx = int(m_reporting.group(1))
                norm = f"reporting_{idx}"
            else:
                continue
        key_to_norm[k] = norm
        if norm not in norm_to_key:
            norm_to_key[norm] = k

    affected_periods = set()
    for feat in getattr(error_recode_polys, "features", []):
        props = getattr(feat, "properties", None)
        pa = getattr(props, "periods_affected", None) if props is not None else None
        if pa:
            for p in pa:
                affected_periods.add(str(p))

    if not affected_periods:
        affected_periods.add("baseline")

    def _apply_recode_to_period(actual_key: str, normalized_name: str):
        period = lc[actual_key]
        pa_obj = getattr(period, "period_assessment", None)
        if pa_obj is None or getattr(pa_obj, "sdg", None) is None:
            return

        pa_obj.error_recode = error_recode_polys

        field_key = {
            "No data": "nodata_pct",
            "Degraded": "degraded_pct",
            "Stable": "stable_pct",
            "Improved": "improved_pct",
        }

        sdg_areas = {item.name: item.area for item in pa_obj.sdg.summary.areas}
        total_area_initial = sum(sdg_areas.values())

        for feat in error_recode_polys.features:
            feat_props = getattr(feat, "properties", None)
            feat_periods = (
                getattr(feat_props, "periods_affected", []) if feat_props else []
            )
            feat_periods = [str(p) for p in feat_periods]
            if normalized_name not in feat_periods:
                continue

            for recode_from, recode_to in zip(
                ["Degraded", "Stable", "Improved"],
                [
                    feat_props.recode_deg_to,
                    feat_props.recode_stable_to,
                    feat_props.recode_imp_to,
                ],
            ):
                area = (
                    feat_props.stats["sdg"]["area_ha"]
                    * 0.01
                    * (feat_props.stats["sdg"][field_key[recode_from]] / 100)
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

        # Validate area accounting and persist error-recode summary for this period
        assert all(value >= 0 for value in sdg_areas.values()), (
            f"sdg_areas should all be greater than zero, but values are {sdg_areas}"
        )
        total_area_final = sum(sdg_areas.values())
        assert abs(total_area_initial - total_area_final) < 0.001, (
            f"total_area_initial ({total_area_initial}) differs "
            f"from total_area_final ({total_area_final})"
        )

        pa_obj.sdg_error_recode = reporting.AreaList(
            "SDG Indicator 15.3.1 (progress since baseline), with errors recoded",
            "sq km",
            [reporting.Area(name, area) for name, area in sdg_areas.items()],
        )

    # Apply to each affected period that exists in the summary
    for norm_name in sorted(affected_periods):
        actual_key = norm_to_key.get(norm_name)
        if actual_key is None:
            continue
        _apply_recode_to_period(actual_key, norm_name)

    out_json = json.loads(
        reporting.TrendsEarthLandConditionSummary.Schema().dumps(summary)
    )
    out_json = _rename_progress_to_report_sections(out_json)

    with open(out_file, "w") as f:
        json.dump(out_json, f, indent=4)

    return out_file


def compute_unccd_report(
    report_job: Job,
    area_of_interest: areaofinterest.AOI,
    job_output_path: Path,
    dataset_output_path: Path,
    progress_callback,
    kill_callback,
) -> Job:
    """Generate UNCCD report from SO1/SO2 and SO3 datasets"""

    params = report_job.params

    tar_gz_path = job_output_path.parent / f"{job_output_path.stem}.tar.gz"

    with tempfile.TemporaryDirectory() as temp_dir:
        paths = []
        orig_summary_path_so1_so2 = Path(params["so1_so2_summary_path"])

        if params["include_error_recode"]:
            new_summary_path_so1_so2 = Path(temp_dir) / orig_summary_path_so1_so2.name
            inferred_periods = _infer_periods_affected_from_summary(
                orig_summary_path_so1_so2
            )

            error_recode_polys = _get_error_recode_polygons(
                params["error_recode_path"], inferred_periods
            )

            _set_error_recode(
                orig_summary_path_so1_so2, new_summary_path_so1_so2, error_recode_polys
            )
            # Make sure this modified file is used as basis for the SO1/SO2 summary
            # below (if affected_only is set)
            params["so1_so2_summary_path"] = str(new_summary_path_so1_so2)
            # Make sure this modified file is used if affected_areas_only is NOT set
            for i in range(len(params["so1_so2_all_paths"])):
                if params["so1_so2_all_paths"][i] == str(orig_summary_path_so1_so2):
                    log(
                        f"Replacing {str(params['so1_so2_all_paths'][i])} with "
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

        if params.get("include_error_recode") and params.get("include_so1_so2"):
            so1_so2_summary_name = Path(params["so1_so2_summary_path"]).name
            cand = next((p for p in paths if p.name == so1_so2_summary_name), None)
            if cand is not None:
                aoi_path = _write_aoi_geojson(
                    cand,
                    Path(temp_dir)
                    / so1_so2_summary_name.replace("summary.json", "aoi.geojson"),
                )
                summary_without_aoi_path = _write_summary_without_aoi(
                    cand,
                    Path(temp_dir) / so1_so2_summary_name,
                )
                paths.append(aoi_path)
                paths.remove(cand)
                paths.append(summary_without_aoi_path)
        elif orig_summary_path_so1_so2 in paths:
            aoi_path = _write_aoi_geojson(
                orig_summary_path_so1_so2,
                Path(temp_dir)
                / orig_summary_path_so1_so2.name.replace("summary.json", "aoi.geojson"),
            )
            summary_without_aoi_path = _write_summary_without_aoi(
                orig_summary_path_so1_so2,
                Path(temp_dir) / orig_summary_path_so1_so2.name,
            )
            paths.append(aoi_path)
            paths.remove(orig_summary_path_so1_so2)
            paths.append(summary_without_aoi_path)

        for path in paths:
            log(f"{path} exists: {path.exists()}")
        log(f"Building tar.gz file with {paths}...")
        _make_tar_gz(tar_gz_path, paths)

    return FileResults(
        name="unccd_report",
        uri=URI(uri=tar_gz_path),
    )
