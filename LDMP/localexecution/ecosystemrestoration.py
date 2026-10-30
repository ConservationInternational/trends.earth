import csv
import datetime as dt
import json
from pathlib import Path

from te_schemas.results import URI, FileResults

from ..areaofinterest import AOI
from ..jobs.models import Job
from ..reports.ecosystem_restoration.report import generate_report


def create_ecosystem_restoration_progress_report(
    job: Job,
    area_of_interest: AOI,
    job_output_path: Path,
    dataset_output_path: Path,
    progress_callback,
    killed_callback,
) -> Job:
    """Calculation function for ecosystem restoration progress."""
    data_csv = job.params.get("data_csv")
    inputs = {
        "region": area_of_interest.get_geojson() if area_of_interest else None,
        "execution_name": job.task_name,
        "notes": job.task_notes,
        "data_csv": data_csv,
    }
    job_output_path.write_text(json.dumps(inputs, indent=2))

    if not data_csv:
        raise ValueError("No report data CSV was given.")
    if not Path(data_csv).is_file():
        raise FileNotFoundError(f"Report data CSV not found: {data_csv}")

    with open(data_csv, newline="", encoding="utf-8") as csv_file:
        data = list(csv.DictReader(csv_file))
    if not data:
        raise ValueError(f"Report data CSV has no rows: {data_csv}")

    pdf_path = generate_report(job_output_path.parent, data)

    job.end_date = dt.datetime.now(dt.timezone.utc)
    job.progress = 100
    job.results = FileResults(
        name="ecosystem_restoration",
        uri=URI(uri=pdf_path or job_output_path),
        data=inputs,
    )

    return job.results
