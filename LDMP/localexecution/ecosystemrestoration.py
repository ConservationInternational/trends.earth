import datetime as dt
import json
import shutil
from pathlib import Path

from qgis.core import Qgis, QgsVectorLayer
from te_schemas.results import URI, FileResults

from .. import __revision__, __version__
from ..areaofinterest import AOI
from ..jobs.models import Job
from ..reports.ecosystem_restoration.manifest import write_manifest
from ..reports.ecosystem_restoration.report import (
    CHARTS_DIR_NAME,
    DATA_XLSX_NAME,
    GEF_CP_ID,
    TEMPLATE_PATH,
    generate_report,
    read_data,
    validate_data,
)
from ..reports.ecosystem_restoration.spatial import (
    GEF_CP_ID_FIELD,
    LAYER_NAME_REGEX,
    calculate_spatially_supported,
    layer_dates,
    layer_files,
    read_countries,
)
from ..reports.ecosystem_restoration.spatial_validation import LayerValidation

# Folder of the copies of the spatial input layers, in the output folder
SPATIAL_DATA_DIR_NAME = "spatial_data"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _relative(path: Path, output_dir: Path) -> str:
    """Path of a file of the output folder, in the folder."""
    return Path(path).relative_to(output_dir).as_posix()


def _open_layer(spatial_layer: dict) -> QgsVectorLayer:
    """Open a spatial input layer."""
    name = spatial_layer.get("name")
    layer = QgsVectorLayer(
        spatial_layer.get("source"), name, spatial_layer.get("provider") or "ogr"
    )
    if not layer.isValid():
        raise ValueError(f"Spatial input layer {name} cannot be opened.")
    return layer


def _filter_child_project(layer: QgsVectorLayer, gef_cp_id: str):
    """Keep only the restoration sites of the child project in the layer."""
    field = layer.fields().field(layer.fields().lookupField(GEF_CP_ID_FIELD))
    quoted_id = gef_cp_id.replace("'", "''")
    subset = f"\"{field.name()}\" = '{quoted_id}'"
    if layer.subsetString():
        subset = f"({layer.subsetString()}) AND {subset}"
    if not layer.setSubsetString(subset):
        raise ValueError(f"Spatial input layer {layer.name()} cannot be filtered.")


def _create_manifest(job: Job, project_name: str, gef_cp_id: str | None) -> dict:
    """Manifest of the report, before its inputs are read."""
    script = getattr(job, "script", None)
    return {
        "job": {
            "id": str(getattr(job, "id", "") or ""),
            "name": job.task_name,
            "notes": job.task_notes,
            "start_date": getattr(job, "start_date", None),
            "end_date": None,
        },
        "scope": {
            "project_name": project_name,
            "gef_child_project": gef_cp_id or "All projects",
            "countries": [],
            "reporting_period": None,
            "spatial_data_version": None,
        },
        "inputs": {"report_data": None, "spatial_layers": []},
        "versions": {
            "trends_earth": __version__,
            "trends_earth_revision": __revision__,
            "script": {
                "name": getattr(script, "name", None),
                "version": getattr(script, "version", None),
            },
            "qgis": Qgis.version(),
            "report_template": TEMPLATE_PATH.name,
        },
        "parameters": job.params,
        "checksums": {},
        "validation": {
            "status": "not run",
            "report_data": None,
            "layer_names": None,
            "spatial_layers": [],
        },
        "export": {"status": "not run"},
    }


def _validation(errors: list[str]) -> dict:
    return {"status": "failed" if errors else "passed", "errors": errors}


def create_ecosystem_restoration_progress_report(
    job: Job,
    area_of_interest: AOI,
    job_output_path: Path,
    dataset_output_path: Path,
    progress_callback,
    killed_callback,
) -> Job:
    """Calculation function for ecosystem restoration progress.

    Report_Manifest.json is written in the output folder, also when the
    report cannot be created, with the error in its export status.
    """
    output_dir = job_output_path.parent
    project_name = (job.params.get("project_name") or "").strip()
    # GEF_CP_ID of the child project, None for all the child projects
    gef_cp_id = (job.params.get("gef_cp_id") or "").strip() or None
    manifest = _create_manifest(job, project_name, gef_cp_id)
    try:
        results = _create_report(
            job, area_of_interest, job_output_path, project_name, gef_cp_id, manifest
        )
    except Exception as error:
        if manifest["validation"]["status"] != "passed":
            manifest["validation"]["status"] = "failed"
        manifest["export"] = {"status": "failed", "error": str(error)}
        manifest["job"]["end_date"] = _now()
        write_manifest(output_dir, manifest)
        raise

    manifest_path = write_manifest(output_dir, manifest)
    results.other_uris.append(URI(uri=manifest_path))
    return results


def _create_report(
    job: Job,
    area_of_interest: AOI,
    job_output_path: Path,
    project_name: str,
    gef_cp_id: str | None,
    manifest: dict,
) -> FileResults:
    """Create the report, and fill the manifest."""
    output_dir = job_output_path.parent
    data_xlsx = job.params.get("data_xlsx")
    # Name, source and provider of each spatial input layer
    spatial_layers = job.params.get("spatial_layers") or []
    inputs = {
        "region": area_of_interest.get_geojson() if area_of_interest else None,
        "execution_name": job.task_name,
        "notes": job.task_notes,
        "project_name": project_name,
        "data_xlsx": data_xlsx,
        "gef_cp_id": gef_cp_id,
        "spatial_layers": spatial_layers,
    }
    job_output_path.write_text(json.dumps(inputs, indent=2))
    validation = manifest["validation"]

    if not project_name:
        raise ValueError("No project name was given.")

    # Report data
    if not data_xlsx:
        raise ValueError("No report data XLSX was given.")
    if not Path(data_xlsx).is_file():
        raise FileNotFoundError(f"Report data XLSX not found: {data_xlsx}")

    columns, all_data = read_data(data_xlsx)
    data = all_data
    if gef_cp_id:
        data = [row for row in data if (row.get(GEF_CP_ID) or "").strip() == gef_cp_id]
    manifest["inputs"]["report_data"] = {
        "source": data_xlsx,
        "file": DATA_XLSX_NAME,
        "rows": len(all_data),
        "rows_reported": len(data),
    }
    errors = validate_data(columns, data)
    if not all_data:
        errors.insert(0, f"Report data XLSX has no rows: {data_xlsx}")
    elif not data:
        errors.insert(0, f"Report data XLSX has no rows of child project {gef_cp_id}")
    validation["report_data"] = _validation(errors)
    if errors:
        raise ValueError("\n".join(errors))

    # Copy the report data XLSX, as it is, with the rows of all the child projects
    data_xlsx_path = Path(shutil.copy2(data_xlsx, output_dir / DATA_XLSX_NAME))

    # Spatial layers, dates from their names, sorted by date
    if not spatial_layers:
        raise ValueError("No spatial input layer was given.")
    layers_by_name = {
        spatial_layer.get("name"): spatial_layer for spatial_layer in spatial_layers
    }
    dates, errors = layer_dates(list(layers_by_name))
    validation["layer_names"] = _validation(errors)
    if errors:
        raise ValueError("\n".join(errors))

    # Reporting period, from the date of the first layer to the date of the last
    reporting_period = (min(dates.values()), max(dates.values()))
    # Names of the layers of the last year, for every country
    spatial_data_version = " • ".join(
        name for name, date in dates.items() if date.year == reporting_period[1].year
    )

    # Spatially supported area of each layer, for the year of its name
    spatial_data = []
    sites_paths = []
    countries = set()
    # Copies of the files of the spatial input layers
    spatial_data_dir = output_dir / SPATIAL_DATA_DIR_NAME
    spatial_data_dir.mkdir(parents=True, exist_ok=True)
    for name, date in dates.items():
        layer = _open_layer(layers_by_name[name])
        errors = LayerValidation(layer).run()
        validation["spatial_layers"].append({"name": name, **_validation(errors)})
        if errors:
            raise ValueError(
                f"Spatial input layer {name} is not valid:\n" + "\n".join(errors)
            )

        # Copy the files of the validated restoration sites, as they are,
        # with the sites of all the child projects
        files = [
            Path(shutil.copy2(file, spatial_data_dir / file.name))
            for file in layer_files(layer.source())
        ]
        sites_paths.extend(files)
        manifest["inputs"]["spatial_layers"].append(
            {
                "name": name,
                "source": layers_by_name[name].get("source"),
                "country": LAYER_NAME_REGEX.match(name).group(1),
                "date": date,
                "sites": layer.featureCount(),
                "files": [_relative(file, output_dir) for file in files],
            }
        )

        # The report has only the restoration sites of the child project
        if gef_cp_id:
            _filter_child_project(layer, gef_cp_id)
        spatial_data.extend(calculate_spatially_supported(layer, date.year))
        countries.update(read_countries(layer))
    validation["status"] = "passed"

    manifest["scope"].update(
        {
            "countries": sorted(countries),
            "reporting_period": {
                "baseline_date": reporting_period[0],
                "latest_monitoring_date": reporting_period[1],
            },
            "spatial_data_version": spatial_data_version,
        }
    )

    pdf_path = generate_report(
        output_dir,
        project_name,
        data,
        spatial_data,
        sorted(countries),
        reporting_period,
        spatial_data_version,
        f"{gef_cp_id} • {project_name}" if gef_cp_id else "All projects",
    )

    job.end_date = dt.datetime.now(dt.timezone.utc)
    job.progress = 100
    manifest["job"]["end_date"] = job.end_date
    charts_dir = output_dir / CHARTS_DIR_NAME
    manifest["export"] = {
        "status": "success" if pdf_path else "failed",
        "error": None if pdf_path else "The PDF of the report cannot be exported.",
        "date": _now(),
        "report": _relative(pdf_path, output_dir) if pdf_path else None,
        "charts": [
            _relative(chart, output_dir) for chart in sorted(charts_dir.glob("*.png"))
        ],
        "report_data": _relative(data_xlsx_path, output_dir),
        "spatial_data": [_relative(path, output_dir) for path in sites_paths],
    }

    job.results = FileResults(
        name="ecosystem_restoration",
        uri=URI(uri=pdf_path or job_output_path),
        other_uris=[URI(uri=data_xlsx_path)]
        + [URI(uri=sites_path) for sites_path in sites_paths],
        data=inputs,
    )
    return job.results
