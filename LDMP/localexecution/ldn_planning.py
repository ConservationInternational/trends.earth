"""Local execution callables for the LDN Planning Tool.

Handlers, one per script:
  - compute_arr_local          (ldn-planning-arr)
  - compute_hotspots_local     (ldn-planning-hotspots)
  - compute_planning_local     (ldn-planning-projection) — BAU + scenario + comparison
  - compute_create_land_types_local (ldn-planning-land-types)

All follow the same signature and mirror localexecution/counterbalancing.py.
"""

import logging
from pathlib import Path

from te_algorithms.gdal.land_deg import zones as _zones
from te_algorithms.gdal.land_deg.ldn_planning import (
    apply_scenario,
    compute_arr_classification,
    compute_bau_rate,
    compute_hotspots,
    project_scenario_against_bau,
)
from te_algorithms.gdal.land_deg.ldn_planning_report import (
    save_ldn_planning_excel,
    save_ldn_planning_json,
)
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
    arr_path = str(job_output_path.with_suffix("")) + "_arr.tif"

    summary, arr_raster_path = compute_arr_classification(
        status_path=params["status_layer_path"],
        status_band_index=params.get("status_band_index", 1),
        output_path=arr_path,
        trajectory_path=params.get("trajectory_path"),
        trajectory_band_index=params.get("trajectory_band_index", 1),
        risk_layer_path=params.get("risk_layer_path"),
        risk_band_index=params.get("risk_band_index", 1),
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
                    )
                ],
                datatype=DataType.INT16,
                filetype=RasterFileType.GEOTIFF,
            ),
        },
        data={"report": report_data},
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

    # Build per-zone list from the output vector for the Excel report
    from osgeo import ogr as _ogr

    hotspot_zones = []
    ds = _ogr.Open(vector_path, 0)
    if ds:
        lyr = ds.GetLayer(0)
        for feat in lyr:
            hotspot_zones.append(
                {
                    "fid": feat.GetFID(),
                    "zone_id": feat.GetField("zone_id")
                    if feat.GetFieldIndex("zone_id") >= 0
                    else feat.GetFID(),
                    "total_pixels": feat.GetField("total_pixels"),
                    "deg_pixels": feat.GetField("deg_pixels"),
                    "deg_area_km2": feat.GetField("deg_area_km2"),
                    "deg_fraction": feat.GetField("deg_fraction"),
                    "priority_rank": feat.GetField("priority_rank"),
                }
            )
        del ds

    save_ldn_planning_excel(excel_path, hotspot_zones=hotspot_zones)
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

    year_initial = params.get("year_initial", 2000)
    year_final = params.get("year_final", 2015)
    target_year = params.get("target_year", 2030)

    # JSON serialises dict keys as strings; restore int keys where needed.
    raw_labels = params.get("land_type_labels")
    land_type_labels = (
        {int(k): v for k, v in raw_labels.items()} if raw_labels else None
    )
    jurisdictions_path = params.get("jurisdictions_path")

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
        progress_callback=lambda p: (
            progress_callback(40 + p * 0.5) if progress_callback else None
        ),
        killed_callback=killed_callback,
    )

    # 3. Compare scenario against BAU over the horizon
    projection = project_scenario_against_bau(
        bau_summary, scenario_summary, target_year
    )

    excel_path = job_output_path.parent / f"{job_output_path.stem}.xlsx"
    json_path = job_output_path.parent / f"{job_output_path.stem}.json"
    save_ldn_planning_excel(
        excel_path,
        bau_summary=bau_summary,
        scenario_summary=scenario_summary,
        projection_summary=projection,
    )
    report_data = save_ldn_planning_json(
        json_path,
        task_name=params.get("task_name", "LDN Planning — Scenario & BAU"),
        bau_summary=bau_summary,
        scenario_summary=scenario_summary,
        projection_summary=projection,
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

    # Extract AOI bounding box so create_zones can clip large/global rasters
    # before any array is allocated (prevents OOM on global datasets).
    #
    # aoi.get_geojson() may return a plain Geometry, a Feature, or a
    # FeatureCollection — ogr.CreateGeometryFromJson only handles the plain
    # Geometry case, so we must unwrap Feature/FeatureCollection ourselves.
    aoi_bounds = None
    try:
        import json as _json

        from osgeo import ogr as _ogr

        geojson = aoi.get_geojson()
        if geojson is not None:
            gtype = geojson.get("type", "")

            def _env_from_geom_dict(g):
                ogr_geom = _ogr.CreateGeometryFromJson(_json.dumps(g))
                if ogr_geom is not None:
                    return ogr_geom.GetEnvelope()  # (minx, maxx, miny, maxy)
                return None

            envs = []
            if gtype == "FeatureCollection":
                for feat in geojson.get("features", []):
                    g = (feat or {}).get("geometry")
                    if g:
                        e = _env_from_geom_dict(g)
                        if e is not None:
                            envs.append(e)
            elif gtype == "Feature":
                g = geojson.get("geometry")
                if g:
                    e = _env_from_geom_dict(g)
                    if e is not None:
                        envs.append(e)
            else:
                # Plain GeoJSON geometry
                e = _env_from_geom_dict(geojson)
                if e is not None:
                    envs.append(e)

            if envs:
                aoi_bounds = (
                    min(e[0] for e in envs),  # minx
                    min(e[2] for e in envs),  # miny
                    max(e[1] for e in envs),  # maxx
                    max(e[3] for e in envs),  # maxy
                )
                logger.info(
                    "Define Land Types: AOI clip bounds (%.4f, %.4f, %.4f, %.4f)",
                    *aoi_bounds,
                )
            else:
                logger.warning(
                    "Define Land Types: could not extract AOI bounds from GeoJSON "
                    "(type=%s); processing full raster extent.",
                    gtype,
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "compute_create_land_types_local: AOI bounds extraction failed: %s", exc
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
        data={"land_types_key": land_types_key},
    )
    return job.results
