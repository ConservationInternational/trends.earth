import csv
import datetime as dt
import json
import shutil
from pathlib import Path

from qgis.core import QgsVectorLayer
from te_schemas.results import URI, FileResults

from ..areaofinterest import AOI
from ..jobs.models import Job
from ..reports.ecosystem_restoration.report import (
    CSV_DELIMITER,
    GEF_CP_ID,
    generate_report,
)
from ..reports.ecosystem_restoration.spatial import (
    GEF_CP_ID_FIELD,
    calculate_spatially_supported,
    check_layer_file,
    layer_dates,
    layer_files,
    missing_fields,
    read_countries,
    validate_sites,
)


def _open_layer(spatial_layer: dict) -> QgsVectorLayer:
    """Open and validate a spatial input layer."""
    name = spatial_layer.get("name")
    layer = QgsVectorLayer(
        spatial_layer.get("source"), name, spatial_layer.get("provider") or "ogr"
    )
    if not layer.isValid():
        raise ValueError(f"Spatial input layer {name} cannot be opened.")

    errors = check_layer_file(layer)
    if errors:
        raise ValueError("\n".join(errors))
    missing = missing_fields(layer)
    if missing:
        raise ValueError(
            f"Spatial input layer {name} has no field: {', '.join(missing)}"
        )
    errors = validate_sites(layer)
    if errors:
        raise ValueError(
            f"Spatial input layer {name} has invalid restoration sites:\n"
            + "\n".join(errors)
        )
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


def create_ecosystem_restoration_progress_report(
    job: Job,
    area_of_interest: AOI,
    job_output_path: Path,
    dataset_output_path: Path,
    progress_callback,
    killed_callback,
) -> Job:
    """Calculation function for ecosystem restoration progress."""
    project_name = (job.params.get("project_name") or "").strip()
    data_csv = job.params.get("data_csv")
    # GEF_CP_ID of the child project, None for all the child projects
    gef_cp_id = (job.params.get("gef_cp_id") or "").strip() or None
    # Name, source and provider of each spatial input layer
    spatial_layers = job.params.get("spatial_layers") or []
    inputs = {
        "region": area_of_interest.get_geojson() if area_of_interest else None,
        "execution_name": job.task_name,
        "notes": job.task_notes,
        "project_name": project_name,
        "data_csv": data_csv,
        "gef_cp_id": gef_cp_id,
        "spatial_layers": spatial_layers,
    }
    job_output_path.write_text(json.dumps(inputs, indent=2))

    if not project_name:
        raise ValueError("No project name was given.")

    if not data_csv:
        raise ValueError("No report data CSV was given.")
    if not Path(data_csv).is_file():
        raise FileNotFoundError(f"Report data CSV not found: {data_csv}")

    with open(data_csv, newline="", encoding="utf-8") as csv_file:
        data = list(csv.DictReader(csv_file, delimiter=CSV_DELIMITER))
    if not data:
        raise ValueError(f"Report data CSV has no rows: {data_csv}")
    if gef_cp_id:
        data = [row for row in data if (row.get(GEF_CP_ID) or "").strip() == gef_cp_id]
        if not data:
            raise ValueError(
                f"Report data CSV has no rows of child project {gef_cp_id}"
            )

    # Check spatial layers
    if not spatial_layers:
        raise ValueError("No spatial input layer was given.")

    # Dates of the layers, from their names, sorted by date
    layers_by_name = {
        spatial_layer.get("name"): spatial_layer for spatial_layer in spatial_layers
    }
    dates, errors = layer_dates(list(layers_by_name))
    if errors:
        raise ValueError("\n".join(errors))

    # Reporting period, from the date of the first layer to the date of the last
    reporting_period = (min(dates.values()), max(dates.values()))

    # Spatially supported area of each layer, for the year of its name
    spatial_data = []
    sites_paths = []
    countries = set()
    for name, date in dates.items():
        layer = _open_layer(layers_by_name[name])

        # Copy the files of the validated restoration sites, as they are,
        # with the sites of all the child projects
        for file in layer_files(layer.source()):
            sites_paths.append(
                Path(shutil.copy2(file, job_output_path.parent / file.name))
            )

        # The report has only the restoration sites of the child project
        if gef_cp_id:
            _filter_child_project(layer, gef_cp_id)
        spatial_data.extend(calculate_spatially_supported(layer, date.year))
        countries.update(read_countries(layer))

    pdf_path = generate_report(
        job_output_path.parent,
        project_name,
        data,
        spatial_data,
        sorted(countries),
        reporting_period,
        # Names of the layers of the last year, for every country
        " • ".join(
            name
            for name, date in dates.items()
            if date.year == reporting_period[1].year
        ),
        f"{gef_cp_id} • {project_name}" if gef_cp_id else "All projects",
    )

    job.end_date = dt.datetime.now(dt.timezone.utc)
    job.progress = 100
    job.results = FileResults(
        name="ecosystem_restoration",
        uri=URI(uri=pdf_path or job_output_path),
        other_uris=[URI(uri=sites_path) for sites_path in sites_paths],
        data=inputs,
    )

    return job.results
