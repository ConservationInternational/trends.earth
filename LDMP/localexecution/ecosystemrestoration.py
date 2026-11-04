import csv
import datetime as dt
import json
from pathlib import Path

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsVectorFileWriter,
    QgsVectorLayer,
)
from te_schemas.results import URI, FileResults

from ..areaofinterest import AOI
from ..jobs.models import Job
from ..reports.ecosystem_restoration.report import CSV_DELIMITER, generate_report
from ..reports.ecosystem_restoration.spatial import (
    REQUIRED_SPATIAL_FIELDS,
    calculate_spatially_supported,
    read_countries,
)


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
    spatial_layer = job.params.get("spatial_layer")
    spatial_layer_provider = job.params.get("spatial_layer_provider") or "ogr"
    spatial_layer_name = job.params.get("spatial_layer_name") or ""
    baseline_date = job.params.get("baseline_date")
    latest_monitoring_date = job.params.get("latest_monitoring_date")
    inputs = {
        "region": area_of_interest.get_geojson() if area_of_interest else None,
        "execution_name": job.task_name,
        "notes": job.task_notes,
        "project_name": project_name,
        "data_csv": data_csv,
        "spatial_layer": spatial_layer,
        "spatial_layer_name": spatial_layer_name,
        "baseline_date": baseline_date,
        "latest_monitoring_date": latest_monitoring_date,
    }
    job_output_path.write_text(json.dumps(inputs, indent=2))

    if not project_name:
        raise ValueError("No project name was given.")

    # Reporting period
    try:
        reporting_period = (
            dt.date.fromisoformat(baseline_date),
            dt.date.fromisoformat(latest_monitoring_date),
        )
    except (TypeError, ValueError):
        raise ValueError(
            "The baseline date and the latest monitoring date must be dates "
            f"as YYYY-MM-DD: {baseline_date!r}, {latest_monitoring_date!r}"
        )
    if reporting_period[0] > reporting_period[1]:
        raise ValueError("The baseline date is after the latest monitoring date.")

    if not data_csv:
        raise ValueError("No report data CSV was given.")
    if not Path(data_csv).is_file():
        raise FileNotFoundError(f"Report data CSV not found: {data_csv}")

    with open(data_csv, newline="", encoding="utf-8") as csv_file:
        data = list(csv.DictReader(csv_file, delimiter=CSV_DELIMITER))
    if not data:
        raise ValueError(f"Report data CSV has no rows: {data_csv}")

    # Open the layer
    if not spatial_layer:
        raise ValueError("No spatial input layer was given.")
    layer = QgsVectorLayer(spatial_layer, "restoration_sites", spatial_layer_provider)
    if not layer.isValid():
        raise ValueError(f"Spatial input layer cannot be opened: {spatial_layer}")

    missing = [f for f in REQUIRED_SPATIAL_FIELDS if layer.fields().indexOf(f) < 0]
    if missing:
        raise ValueError(f"Spatial input layer has no field: {', '.join(missing)}")
    spatial_data = calculate_spatially_supported(layer)
    countries = read_countries(layer)

    pdf_path = generate_report(
        job_output_path.parent,
        project_name,
        data,
        spatial_data,
        countries,
        reporting_period,
        spatial_layer_name,
    )

    # Save the validated restoration sites as GeoJSON, in WGS 84
    sites_path = job_output_path.parent / "Validated_Restoration_Sites.geojson"
    transform_context = QgsCoordinateTransformContext()
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GeoJSON"
    options.fileEncoding = "UTF-8"
    options.ct = QgsCoordinateTransform(
        layer.crs(), QgsCoordinateReferenceSystem("EPSG:4326"), transform_context
    )
    error, message, *_ = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, str(sites_path), transform_context, options
    )
    if error != QgsVectorFileWriter.NoError:
        raise RuntimeError(f"Validated restoration sites not saved: {message}")

    job.end_date = dt.datetime.now(dt.timezone.utc)
    job.progress = 100
    job.results = FileResults(
        name="ecosystem_restoration",
        uri=URI(uri=pdf_path or job_output_path),
        other_uris=[URI(uri=sites_path)],
        data=inputs,
    )

    return job.results
