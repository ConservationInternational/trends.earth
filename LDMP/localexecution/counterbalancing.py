"""Local execution callable for LDN counterbalancing assessment."""

import logging
from pathlib import Path

from osgeo import gdal
from te_algorithms.gdal.land_deg.counterbalancing import compute_counterbalancing
from te_algorithms.gdal.land_deg.counterbalancing_report import (
    save_counterbalancing_excel,
    save_counterbalancing_json,
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


def compute_counterbalancing_local(
    job: Job,
    aoi: AOI,
    job_output_path: Path,
    dataset_output_path: Path,
    progress_callback=None,
    killed_callback=None,
) -> Job:
    """Run the LDN counterbalancing assessment locally.

    Expected ``job.params`` keys:
        status_layer_path: str — path to the 7-class expanded status raster
        status_band_index: int — 1-based band index for the status layer
        land_type_layer_paths: list[str] — raster layers defining land types
        task_name: str — user-provided task label
    """
    params = job.params

    cb_kwargs = dict(
        status_path=params["status_layer_path"],
        status_band_index=params.get("status_band_index", 1),
        land_type_layer_paths=params["land_type_layer_paths"],
        output_path=str(job_output_path),
        aoi=AOI(aoi.get_geojson()),
    )
    if "n_cpus" in params:
        cb_kwargs["n_cpus"] = params["n_cpus"]

    summary_table, land_type_results, gl_path, ach_path = compute_counterbalancing(
        **cb_kwargs
    )

    # Save Excel report
    excel_path = (
        job_output_path.parent / f"{job_output_path.stem}_counterbalancing.xlsx"
    )
    save_counterbalancing_excel(excel_path, land_type_results, summary_table)

    # Save JSON report
    json_path = job_output_path.parent / f"{job_output_path.stem}_counterbalancing.json"
    save_counterbalancing_json(
        json_path,
        land_type_results,
        task_name=params.get("task_name", "LDN Counterbalancing"),
        aoi=AOI(aoi.get_geojson()),
    )

    # Combine gains/losses + achievement into a multi-band output
    output_vrt = str(
        job_output_path.parent / f"{job_output_path.stem}_counterbalancing.vrt"
    )
    gdal.BuildVRT(output_vrt, [gl_path, ach_path], separate=True)

    bands = [
        Band(
            name="Counterbalancing gains and losses",
            metadata={
                "gains_losses": True,
            },
        ),
        Band(
            name="Land Type LDN Achievement",
            metadata={
                "land_type_achievement": True,
            },
        ),
    ]

    job.results = RasterResults(
        name="ldn_counterbalancing",
        uri=URI(uri=output_vrt),
        rasters={
            DataType.INT16.value: Raster(
                uri=URI(uri=output_vrt),
                bands=bands,
                datatype=DataType.INT16,
                filetype=RasterFileType.GEOTIFF,
            ),
        },
    )

    return job
