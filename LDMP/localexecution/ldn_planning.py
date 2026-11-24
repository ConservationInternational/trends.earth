"""Local execution callables for the LDN Planning Tool.

Handlers, one per script:
  - compute_arr_local          (ldn-planning-arr)
  - compute_hotspots_local     (ldn-planning-hotspots)
  - compute_planning_local     (ldn-planning-projection) — BAU + scenario + comparison
  - compute_create_land_types_local (ldn-planning-land-types)

All follow the same signature and mirror localexecution/counterbalancing.py.
"""

import logging
import shutil
from pathlib import Path

from osgeo import gdal
from te_algorithms.common.band_names import generate_sanitized_band_names
from te_algorithms.common.checksum import file_checksum
from te_algorithms.gdal.land_deg import zones as _zones
from te_algorithms.gdal.land_deg.ldn_planning import (
    apply_scenario,
    compare_scenarios,
    compute_arr_classification,
    compute_bau_rate,
    compute_hotspots,
    project_scenario_against_bau,
    summarize_land_types,
)
from te_algorithms.gdal.land_deg.ldn_planning_inputs import area_checksum
from te_algorithms.gdal.land_deg.ldn_planning_report import (
    load_hotspot_zones,
    save_ldn_planning_excel,
    save_ldn_planning_json,
    save_priority_reports,
)
from te_algorithms.gdal.util import dataset_checksums, geojson_bounds
from te_schemas.aoi import AOI
from te_schemas.results import (
    URI,
    Band,
    DataType,
    Raster,
    RasterFileType,
    RasterResults,
)

from ..jobs.models import Job

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Handler 1 — ARR classification
# ---------------------------------------------------------------------------


def compute_arr_local(
    job: Job,
    aoi: AOI,
    job_output_path: Path,
    dataset_output_path: Path,
    progress_callback=None,
    killed_callback=None,
) -> RasterResults:
    """Local handler: Avoid / Reduce / Reverse classification.

    Expected ``job.params`` keys:
        status_layer_path (str): Path to SDG 15.3.1 status raster.
        status_band_index (int): 1-based band index (default 1).
        trajectory_path (str | None): Optional productivity trajectory raster.
        trajectory_band_index (int): Band index for trajectory (default 1).
        risk_layer_path (str | None): Optional binary risk layer.
        risk_band_index (int): Band index for risk layer (default 1).
        task_name (str): User-provided task label.
    """
    params = job.params
    if aoi is not None:
        params["aoi_checksum"] = area_checksum(aoi.get_geojson())
    arr_path = str(job_output_path.with_suffix("")) + "_arr.tif"

    summary, arr_raster_path = compute_arr_classification(
        status_path=params["status_layer_path"],
        status_band_index=params.get("status_band_index", 1),
        output_path=arr_path,
        trajectory_path=params.get("trajectory_path"),
        trajectory_band_index=params.get("trajectory_band_index", 1),
        risk_layer_path=params.get("risk_layer_path"),
        risk_band_index=params.get("risk_band_index", 1),
        risk_threshold=params.get("risk_threshold", 0),
        status_type=params.get("status_type", "auto"),
        aoi=aoi,
        progress_callback=lambda p: (
            progress_callback(p * 0.85) if progress_callback else None
        ),
        killed_callback=killed_callback,
    )

    # Reports
    excel_path = job_output_path.parent / f"{job_output_path.stem}_arr.xlsx"
    json_path = job_output_path.parent / f"{job_output_path.stem}_arr.json"
    save_ldn_planning_excel(excel_path, arr_summary=summary)
    report_data = save_ldn_planning_json(
        json_path, task_name=params.get("task_name", "LDN ARR"), arr_summary=summary
    )

    if progress_callback:
        progress_callback(100.0)

    year_initial = params.get("year_initial")
    year_final = params.get("year_final")

    job.results = RasterResults(
        name="ldn-planning-arr",
        uri=URI(uri=Path(arr_raster_path)),
        rasters={
            DataType.INT16.value: Raster(
                uri=URI(uri=Path(arr_raster_path)),
                bands=[
                    Band(
                        name="LDN Planning - Avoid/Reduce/Reverse",
                        metadata={
                            "arr": True,
                            "year_initial": year_initial,
                            "year_final": year_final,
                        },
                    ),
                    Band(
                        name="LDN Planning - ARR Assignment Reason",
                        no_data_value=255,
                        metadata={
                            "arr_reason": True,
                            "reason_codes": summary["reason_codes"],
                        },
                    ),
                ],
                datatype=DataType.INT16,
                filetype=RasterFileType.GEOTIFF,
            ),
        },
        data={"report": report_data},
    )
    return job.results


def compute_priority_local(
    job,
    aoi,
    job_output_path,
    dataset_output_path,
    progress_callback=None,
    killed_callback=None,
):
    from te_algorithms.gdal.land_deg.ldn_priority import compute_prioritization

    params = job.params
    if aoi is not None:
        params["aoi_checksum"] = area_checksum(aoi.get_geojson())
    summary, path = compute_prioritization(
        arr_path=params["arr_layer_path"],
        arr_band_index=params.get("arr_band_index", 1),
        criteria=params["criteria"],
        output_path=str(job_output_path.with_suffix(".tif")),
        exclusion_path=params.get("exclusion_path"),
        land_type_path=params.get("land_type_path"),
        zones_path=params.get("zones_path"),
        aoi=aoi,
        land_type_labels=params.get("land_type_labels"),
        progress_callback=progress_callback,
        killed_callback=killed_callback,
    )
    report = save_priority_reports(
        job_output_path.parent / f"{job_output_path.stem}_priority.json",
        summary,
        params,
    )
    job.results = RasterResults(
        name="ldn-planning-priority",
        uri=URI(uri=Path(path)),
        rasters={
            DataType.FLOAT32.value: Raster(
                uri=URI(uri=Path(path)),
                bands=[
                    Band(
                        name=f"LDN Planning - Priority ({key})",
                        metadata={"priority_class": key},
                    )
                    for key in ("avoid", "reduce", "reverse")
                ],
                datatype=DataType.FLOAT32,
                filetype=RasterFileType.GEOTIFF,
            ),
            DataType.BYTE.value: Raster(
                uri=URI(uri=Path(summary["coverage_path"])),
                bands=[
                    Band(
                        name=f"LDN Planning - Priority coverage ({key})",
                        no_data_value=255,
                        metadata={"coverage_class": key},
                    )
                    for key in ("avoid", "reduce", "reverse")
                ],
                datatype=DataType.BYTE,
                filetype=RasterFileType.GEOTIFF,
            ),
        },
        data={"report": report},
    )
    return job.results


def compute_selection_local(
    job,
    aoi,
    job_output_path,
    dataset_output_path,
    progress_callback=None,
    killed_callback=None,
):
    from te_algorithms.gdal.land_deg.ldn_priority import select_priority_areas

    params = job.params
    source_area = (params.get("priority_params") or {}).get("aoi_checksum")
    if source_area:
        params["aoi_checksum"] = source_area
    summary, path = select_priority_areas(
        score_path=params["score_path"],
        output_path=str(job_output_path.with_suffix(".tif")),
        selections=params["selections"],
        progress_callback=progress_callback,
        killed_callback=killed_callback,
    )
    band = Band(
        name="LDN Planning - Candidate areas",
        metadata={
            "candidate_areas": True,
            "priority_job_id": params["priority_job_id"],
        },
    )
    # Write final band descriptions before hashing the candidate mask.
    dataset = gdal.Open(str(path), gdal.GA_Update)
    dataset.GetRasterBand(1).SetDescription(generate_sanitized_band_names([band])[0])
    dataset = None
    summary["mask_sha256"] = file_checksum(path)
    report = save_priority_reports(
        job_output_path.parent / f"{job_output_path.stem}_candidates.json",
        summary,
        params,
    )
    job.results = RasterResults(
        name="ldn-planning-selection",
        uri=URI(uri=Path(path)),
        rasters={
            DataType.INT16.value: Raster(
                uri=URI(uri=Path(path)),
                bands=[band],
                datatype=DataType.INT16,
                filetype=RasterFileType.GEOTIFF,
            )
        },
        data={"report": report},
    )
    return job.results


# ---------------------------------------------------------------------------
# Handler 2 — Hotspot prioritization
# ---------------------------------------------------------------------------


def compute_hotspots_local(
    job: Job,
    aoi: AOI,
    job_output_path: Path,
    dataset_output_path: Path,
    progress_callback=None,
    killed_callback=None,
) -> RasterResults:
    """Local handler: degradation hotspot prioritization.

    Expected ``job.params`` keys:
        status_layer_path (str): SDG 15.3.1 status raster.
        status_band_index (int): Band index (default 1).
        status_type (str): Declared 3-class or 7-class encoding.
        zones_path (str | None): Zones vector layer; if None a fishnet is used.
        grid_size_km (float): Fishnet cell size in km (default 50).
        task_name (str): User label.
    """
    params = job.params
    vec_path = str(job_output_path.with_suffix("")) + "_hotspots.gpkg"
    ras_path = str(job_output_path.with_suffix("")) + "_hotspots_rank.tif"

    summary, vector_path, raster_path = compute_hotspots(
        status_path=params["status_layer_path"],
        status_band_index=params.get("status_band_index", 1),
        status_type=params.get("status_type", "auto"),
        zones_path=params.get("zones_path"),
        grid_size_km=float(params.get("grid_size_km", 25.0)),
        output_vector_path=vec_path,
        output_raster_path=ras_path,
        progress_callback=lambda p: (
            progress_callback(p * 0.9) if progress_callback else None
        ),
        killed_callback=killed_callback,
    )

    excel_path = job_output_path.parent / f"{job_output_path.stem}_hotspots.xlsx"
    json_path = job_output_path.parent / f"{job_output_path.stem}_hotspots.json"

    save_ldn_planning_excel(excel_path, hotspot_zones=load_hotspot_zones(vector_path))
    report_data = save_ldn_planning_json(
        json_path,
        task_name=params.get("task_name", "LDN Hotspots"),
        hotspot_summary=summary,
    )

    if progress_callback:
        progress_callback(100.0)

    year_initial = params.get("year_initial")
    year_final = params.get("year_final")

    job.results = RasterResults(
        name="ldn-planning-hotspots",
        uri=URI(uri=Path(ras_path)),
        rasters={
            DataType.INT16.value: Raster(
                uri=URI(uri=Path(ras_path)),
                bands=[
                    Band(
                        name="LDN Planning - Degradation Hotspots",
                        metadata={
                            "hotspot_pct": True,
                            "year_initial": year_initial,
                            "year_final": year_final,
                        },
                    )
                ],
                datatype=DataType.INT16,
                filetype=RasterFileType.GEOTIFF,
            ),
        },
        data={"report": report_data, "vector_path": vector_path},
    )
    return job.results


# ---------------------------------------------------------------------------
# Handler 3 — Scenario & BAU Projection (combined)
# ---------------------------------------------------------------------------


def compute_planning_local(
    job: Job,
    aoi: AOI,
    job_output_path: Path,
    dataset_output_path: Path,
    progress_callback=None,
    killed_callback=None,
) -> RasterResults:
    """Local handler: combined Scenario & BAU Projection.

    Computes the Business-As-Usual degradation trajectory, applies the planning
    targets over the same horizon, and compares the scenario against BAU.

    Expected ``job.params`` keys:
        arr_layer_path (str): ARR raster (from the ARR classification tool).
        arr_band_index (int): Band index (default 1).
        status_baseline_path (str): Baseline period status raster.
        status_baseline_band_index (int): Band index (default 1).
        status_reporting_path (str | None): Reporting period status raster.
        status_reporting_band_index (int): Band index (default 1).
        year_initial (int), year_final (int), target_year (int).
        targets (list[dict]): wkt_geometry, intervention, effectiveness.
        land_type_path (str | None), land_type_band_index (int),
        land_type_labels (dict | None).
        jurisdictions_path (str | None): Optional vector layer for per-jurisdiction breakdown.
        task_name (str): User label.
    """
    params = job.params
    out_path = str(job_output_path.with_suffix("")) + "_scenario.tif"
    input_keys = (
        "arr_layer_path",
        "status_baseline_path",
        "status_reporting_path",
        "land_type_path",
        "jurisdictions_path",
    )
    input_checksums = {
        key: dataset_checksums(params[key]) for key in input_keys if params.get(key)
    }
    if params.get("input_checksums") and params["input_checksums"] != input_checksums:
        raise ValueError("Scenario inputs changed since this job was saved.")
    params["input_checksums"] = input_checksums
    aoi_checksum = area_checksum(aoi.get_geojson() if aoi is not None else None)
    if "aoi_checksum" in params and params["aoi_checksum"] != aoi_checksum:
        raise ValueError("Scenario AOI changed since this job was saved.")
    params["aoi_checksum"] = aoi_checksum

    year_initial = params.get("year_initial", 2000)
    year_final = params.get("year_final", 2015)
    target_year = params.get("target_year", 2030)

    # JSON serialises dict keys as strings; restore int keys where needed.
    raw_labels = params.get("land_type_labels")
    land_type_labels = (
        {int(k): v for k, v in raw_labels.items()} if raw_labels else None
    )
    jurisdictions_path = params.get("jurisdictions_path")
    copied_masks = {}
    for target in params.get("targets", []):
        mask_path = target.get("selected_mask_path")
        if not mask_path:
            continue
        configuration = target.get("configuration_context") or target.get(
            "approval_context"
        )
        configured_effectiveness = target.get(
            "configured_effectiveness", target.get("approved_effectiveness")
        )
        if (
            configuration is not None
            and (
                configuration.get("area_sha256") != params["aoi_checksum"]
                or configuration.get("arr_job_id") != params.get("arr_job_id")
            )
        ) or (
            configured_effectiveness is not None
            and configured_effectiveness != target.get("effectiveness")
        ):
            raise ValueError(
                "Candidate target settings no longer match this scenario's "
                "area, ARR or effectiveness."
            )
        checksum = file_checksum(mask_path)
        if checksum != target.get("mask_sha256"):
            raise ValueError(
                "Candidate raster changed. Generate new candidate areas and "
                "update the scenario targets."
            )
        if mask_path not in copied_masks:
            snapshot = job_output_path.parent / (
                f"{job_output_path.stem}_candidate_targets_{len(copied_masks)}.tif"
            )
            if Path(mask_path).resolve() != snapshot.resolve():
                shutil.copyfile(mask_path, snapshot)
            if file_checksum(snapshot) != checksum:
                raise ValueError(
                    "Candidate raster changed while copying. Generate new "
                    "candidate areas and update the scenario targets."
                )
            copied_masks[mask_path] = str(snapshot)
        target["selected_mask_path"] = copied_masks[mask_path]

    # 1. BAU projection (0–40%)
    bau_summary = compute_bau_rate(
        status_baseline_path=params["status_baseline_path"],
        status_baseline_band_index=params.get("status_baseline_band_index", 1),
        status_reporting_path=params.get("status_reporting_path"),
        status_reporting_band_index=params.get("status_reporting_band_index", 1),
        year_initial=year_initial,
        year_final=year_final,
        target_year=target_year,
        zones_path=jurisdictions_path,
        zones_raster_path=None,
        zones_raster_labels=None,
        land_type_path=params.get("land_type_path"),
        land_type_band_index=params.get("land_type_band_index", 1),
        land_type_labels=land_type_labels,
        status_baseline_type=params.get("status_baseline_type", "auto"),
        status_reporting_type=params.get("status_reporting_type", "auto"),
        aoi=aoi,
        progress_callback=lambda p: (
            progress_callback(p * 0.4) if progress_callback else None
        ),
        killed_callback=killed_callback,
    )

    # 2. Scenario / target setting (40–90%)
    scenario_summary, scenario_raster = apply_scenario(
        arr_path=params["arr_layer_path"],
        arr_band_index=params.get("arr_band_index", 1),
        targets=params.get("targets", []),
        output_path=out_path,
        land_type_path=params.get("land_type_path"),
        land_type_band_index=params.get("land_type_band_index", 1),
        land_type_labels=land_type_labels,
        zones_path=jurisdictions_path,
        zones_raster_path=None,
        zones_raster_labels=None,
        aoi=aoi,
        progress_callback=lambda p: (
            progress_callback(40 + p * 0.5) if progress_callback else None
        ),
        killed_callback=killed_callback,
    )

    # 3. Compare scenario against BAU over the horizon
    projection = project_scenario_against_bau(
        bau_summary, scenario_summary, target_year
    )
    if any(
        dataset_checksums(params[key]) != value
        for key, value in input_checksums.items()
    ):
        raise ValueError("Scenario inputs changed during execution.")
    comparison = compare_scenarios(params, projection)

    excel_path = job_output_path.parent / f"{job_output_path.stem}_scenario.xlsx"
    json_path = job_output_path.parent / f"{job_output_path.stem}_scenario.json"
    save_ldn_planning_excel(
        excel_path,
        bau_summary=bau_summary,
        scenario_summary=scenario_summary,
        projection_summary=projection,
        scenario_comparison=comparison,
    )
    extra_data = {
        "target_provenance": params.get("targets", []),
        "input_checksums": input_checksums,
        "aoi_checksum": aoi_checksum,
    }
    if comparison:
        extra_data["scenario_comparison"] = comparison
    report_data = save_ldn_planning_json(
        json_path,
        task_name=params.get("task_name", "LDN Planning — Scenario"),
        bau_summary=bau_summary,
        scenario_summary=scenario_summary,
        projection_summary=projection,
        extra_data=extra_data,
    )

    if progress_callback:
        progress_callback(100.0)

    def _band(name, key):
        return Band(
            name=name,
            metadata={
                key: True,
                "year_initial": year_initial,
                "year_final": year_final,
            },
        )

    job.results = RasterResults(
        name="ldn-planning-projection",
        uri=URI(uri=Path(scenario_raster)),
        rasters={
            DataType.INT16.value: Raster(
                uri=URI(uri=Path(scenario_raster)),
                bands=[
                    _band(
                        "LDN Planning - Scenario P(restoration)",
                        "scenario_p_reverse",
                    ),
                    _band(
                        "LDN Planning - Scenario P(reduction)",
                        "scenario_p_reduce",
                    ),
                    _band(
                        "LDN Planning - Scenario P(avoidance)",
                        "scenario_p_avoid",
                    ),
                ],
                datatype=DataType.INT16,
                filetype=RasterFileType.GEOTIFF,
            ),
        },
        data={
            "report": report_data,
            "bau_summary": bau_summary,
            "projection": projection,
        },
    )
    return job.results


# ---------------------------------------------------------------------------
# Handler 4 — Create Analysis Zones
# ---------------------------------------------------------------------------


def compute_create_land_types_local(
    job: Job,
    aoi: AOI,
    job_output_path: Path,
    dataset_output_path: Path,
    progress_callback=None,
    killed_callback=None,
) -> RasterResults:
    """Local handler: combine categorical rasters into a reusable land types layer.

    Expected ``job.params`` keys:
        raster_paths (list[str]): Categorical rasters to combine.
        band_indices (list[int] | None): Band index per raster (default 1s).
        task_name (str): User label.
    """
    params = job.params
    raster_paths = params["raster_paths"]
    band_indices = params.get("band_indices")
    out_path = str(job_output_path.with_suffix("")) + "_land_types.tif"

    aoi_bounds = None
    if aoi is not None:
        params["aoi_checksum"] = area_checksum(aoi.get_geojson())
        aoi_bounds = geojson_bounds(aoi.get_geojson())
        logger.info(
            "Define Land Types: AOI clip bounds (%.4f, %.4f, %.4f, %.4f)",
            *aoi_bounds,
        )

    land_types_raster, labels, layer_names = _zones.create_zones(
        raster_paths=raster_paths,
        output_path=out_path,
        band_indices=band_indices,
        aoi_bounds=aoi_bounds,
        progress_callback=progress_callback,
        killed_callback=killed_callback,
    )

    land_types_key = {
        "description": (
            "Maps each land type id to the combination of source-raster class values."
        ),
        "layer_names": layer_names,
        "units": {
            str(zid): {"label": label, "values": label.split("_")}
            for zid, label in sorted(labels.items())
        },
    }

    summary = summarize_land_types(land_types_raster, labels, layer_names)
    report_base = job_output_path.parent / f"{job_output_path.stem}_land_types"
    save_ldn_planning_excel(
        report_base.parent / f"{report_base.name}.xlsx", land_types_summary=summary
    )
    report = save_ldn_planning_json(
        report_base.parent / f"{report_base.name}.json",
        task_name=params.get("task_name", "LDN land types"),
        land_types_summary=summary,
    )

    if progress_callback:
        progress_callback(100.0)

    job.results = RasterResults(
        name="ldn-planning-land-types",
        uri=URI(uri=Path(land_types_raster)),
        rasters={
            DataType.INT32.value: Raster(
                uri=URI(uri=Path(land_types_raster)),
                bands=[
                    Band(
                        name="LDN Planning - Land Types",
                        no_data_value=0,
                        metadata={
                            "land_types": True,
                            "n_land_types": len(labels),
                            "layer_names": layer_names,
                        },
                    ),
                ],
                datatype=DataType.INT32,
                filetype=RasterFileType.GEOTIFF,
            ),
        },
        data={"land_types_key": land_types_key, "report": report},
    )
    return job.results
