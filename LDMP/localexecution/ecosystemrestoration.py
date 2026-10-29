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
    inputs = {
        "region": area_of_interest.get_geojson() if area_of_interest else None,
        "execution_name": job.task_name,
        "notes": job.task_notes,
    }
    job_output_path.write_text(json.dumps(inputs, indent=2))

    pdf_path = generate_report(job_output_path.parent)

    job.end_date = dt.datetime.now(dt.timezone.utc)
    job.progress = 100
    job.results = FileResults(
        name="ecosystem_restoration",
        uri=URI(uri=pdf_path or job_output_path),
        data=inputs,
    )

    return job.results
