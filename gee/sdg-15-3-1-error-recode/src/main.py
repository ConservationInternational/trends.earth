"""
Code for calculating all three SDG 15.3.1 sub-indicators.
"""

# Copyright 2017 Conservation International
import random
import tempfile
from pathlib import Path

import te_algorithms.gdal.land_deg.config as ld_config
from te_algorithms.api import util
from te_algorithms.gdal.land_deg.land_deg_recode import (
    rasterize_error_recode,
    recode_errors,
)
from te_schemas import algorithms, jobs
from te_schemas.aoi import AOI
from te_schemas.error_recode import ErrorRecodePolygons
from te_schemas.productivity import ProductivityMode
from te_schemas.results import Band, JsonResults, RasterResults

S3_PREFIX_RAW_DATA = "prais5-raw"
S3_BUCKET_INPUT = "trends.earth-private"
S3_REGION = "us-east-1"
S3_BUCKET_USER_DATA = "trends.earth-users"
ERROR_RECODE_BAND_NAME = "Error recode"
RECODE_SCRIPT = algorithms.ExecutionScript.Schema().load(
    {
        "name": "sdg-15-3-1-error-recode",
        "version": "1.13",
        "run_mode": algorithms.AlgorithmRunMode.LOCAL,
    }
)

_band_key = {
    "baseline": {
        "name": "SDG 15.3.1 Indicator",
        "filters": [{"field": "year_final", "value": 2015}],
    },
    "reporting_1": {
        "name": "SDG 15.3.1 Indicator",
        "filters": [{"field": "reporting_year_final", "value": 2019}],
    },
    "reporting_2": {
        "name": "SDG 15.3.1 Indicator",
        "filters": [{"field": "reporting_year_final", "value": 2023}],
    },
}


def _recode_band(recode_params, write_tifs, aoi, execution_id, logger):
    logger.debug(f"Recode parameters: {recode_params}")
    logger.info("Starting error recoding calculation")
    with tempfile.TemporaryDirectory() as temp_dir:
        input_job = jobs.Job.Schema().load(recode_params["input_job"])
        recode_params["output_path"] = Path(temp_dir) / input_job.results.uri.uri.stem
        logger.debug(f"Set output path to: {recode_params['output_path']}")
        results = recode_errors(recode_params)
        logger.debug("recode_errors function finished.")

        results.data = {
            "report": results.data,
            "input_job": recode_params["input_job"],
            "baseline_band_index": recode_params["layer_baseline_band_index"],
        }

        if write_tifs:
            logger.info("Writing tifs")
            logger.debug(f"Writing results to S3 with EXECUTION_ID: {execution_id}")
            results = util.write_results_to_s3_cog(
                results,
                aoi,
                filename_base=execution_id,
                s3_prefix="prais-4",
                s3_bucket=S3_BUCKET_USER_DATA,
            )
            logger.debug("Finished writing tifs to S3.")
        return results


def calculate_error_recode(
    aoi,
    error_polygons,
    script_name,
    iso,
    boundary_dataset,
    substr_regexs,
    write_tifs,
    EXECUTION_ID,
    logger,
):
    """
    Calculate error recoding for land degradation indicators.

    Args:
        aoi: Area of Interest object defining the spatial bounds for analysis
        error_polygons (ErrorRecodePolygons): Polygons defining areas to be recoded
        script_name (str): Name of the script used to generate the input data
        iso (str): ISO country code for the analysis area
        boundary_dataset (str): Name of the boundary dataset used (e.g., "UN")
        substr_regexs (list): List of substring regex patterns for job identification
        write_tifs (bool): Whether to write output as GeoTIFF files to S3
        EXECUTION_ID (str): Unique identifier for this execution
        logger: Logger instance for logging messages

    Returns:
        dict: Serialized RasterResults or JsonResults containing the recoded data

    Raises:
        IndexError: If no input job is found matching the specified criteria
        Exception: If no bands are found matching the band_name and filters
    """

    # Get input job
    logger.debug("Entering calculate_error_recode function")
    filename_base = iso + "_" + boundary_dataset + "_" + script_name
    s3_prefix = f"{S3_PREFIX_RAW_DATA}/" + filename_base
    logger.info(f"Looking for prefix {s3_prefix}")
    logger.debug(f"Searching with substr_regexs: {substr_regexs}")
    try:
        input_job = util.get_job_json_from_s3(
            s3_prefix=s3_prefix, s3_bucket=S3_BUCKET_INPUT, substr_regexs=substr_regexs
        )
        if input_job is None:
            raise IndexError(
                f"No job found for prefix {s3_prefix} "
                f" with substr_regexs {substr_regexs}"
            )
        logger.debug(f"Found input job: {input_job.id}")
    except IndexError as exc:
        logger.error(f"Failed to load input job from prefix {s3_prefix}: {exc}")
        raise exc

    # Rasterize the error recode polygons
    error_recode_tif = tempfile.NamedTemporaryFile(
        suffix="_error_recode.tif", delete=False
    ).name
    logger.debug(f"Created temporary file for error recode raster: {error_recode_tif}")
    rasterize_error_recode(error_recode_tif, input_job.results.uri.uri, error_polygons)

    # Create band definition for the error recode raster (first band)
    error_recode_band = Band(
        name=ERROR_RECODE_BAND_NAME,
        metadata={},
        no_data_value=int(ld_config.NODATA_VALUE),
        activated=True,
    )

    # Determine which bands to process based on periods_affected values in error_polygons
    periods_to_process = set()
    for polygon in error_polygons.features:
        if (
            hasattr(polygon.properties, "periods_affected")
            and polygon.properties.periods_affected
        ):
            for period in polygon.properties.periods_affected:
                periods_to_process.add(period)

    if not periods_to_process:
        raise Exception(
            "No periods specified in error polygons; at least one period is required."
        )
    # Convert to a dictionary
    periods_to_process = {period: {} for period in periods_to_process}

    logger.debug(f"Periods to process based on error polygons: {periods_to_process}")

    for period, value in periods_to_process.items():
        band_name = _band_key[period]["name"]
        filters = _band_key[period]["filters"]

        try:
            input_band = util.get_band_by_name(
                input_job,
                band_name,
                filters,
            )
        except IndexError:
            logger.exception(f"Failed to load band name {band_name}")
            raise
        except Exception as exc:
            logger.exception(f"Failed to load band {band_name} with filters {filters}")
            raise exc

        if input_band is None:
            raise Exception(f"Failed to load band {band_name}")
        logger.debug(
            f"Found input band: {input_band.band.name} (band number {input_band.band_number})"
        )
        value["band"] = input_band.band
        value["band_number"] = input_band.band_number

    # Build recode_params with multi-band support
    recode_params = {
        "write_tifs": write_tifs,
        "local_context": jobs.JobLocalContext.Schema().dump(input_job.local_context),
        "task_name": input_job.task_name,
        "metadata": periods_to_process["baseline"]["band"].metadata,
        "task_notes": input_job.task_notes,
        "layer_baseline_band_path": str(input_job.results.uri.uri),
        "layer_baseline_band": Band.Schema().dump(
            periods_to_process["baseline"]["band"]
        ),
        "layer_baseline_band_index": periods_to_process["baseline"]["band_number"],
        "layer_error_recode_path": str(error_recode_tif),
        "layer_error_recode_band": Band.Schema().dump(error_recode_band),
        "error_polygons": ErrorRecodePolygons.Schema().dump(error_polygons),
        "input_job": jobs.Job.Schema().dump(input_job),
        "aoi": AOI.Schema().dump(aoi),
    }

    if "reporting_1" in periods_to_process:
        recode_params.update(
            {
                "layer_reporting_1_band_path": str(input_job.results.uri.uri),
                "layer_reporting_1_band": Band.Schema().dump(
                    periods_to_process["reporting_1"]["band"]
                ),
                "layer_reporting_1_band_index": periods_to_process["reporting_1"][
                    "band_number"
                ],
            }
        )

    if "reporting_2" in periods_to_process:
        recode_params.update(
            {
                "layer_reporting_2_band_path": str(input_job.results.uri.uri),
                "layer_reporting_2_band": Band.Schema().dump(
                    periods_to_process["reporting_2"]["band"]
                ),
                "layer_reporting_2_band_index": periods_to_process["reporting_2"][
                    "band_number"
                ],
            }
        )

    logger.debug(f"aoi is: {AOI.Schema().dump(aoi)}")

    results = _recode_band(recode_params, write_tifs, aoi, EXECUTION_ID, logger)

    if isinstance(results, RasterResults):
        results = RasterResults.Schema().dump(results)

    elif isinstance(results, JsonResults):
        results = JsonResults.Schema().dump(results)
    else:
        raise Exception

    logger.debug("calculate_error_recode function finished, returning results.")
    return results


def run(params, logger):
    """
    Run error recoding for land degradation indicators.

    Supports both single-period and multi-period land degradation jobs.
    For multi-period jobs, include a reporting year filter in the filters parameter:
    filters = [{"field": "reporting_year_final", "value": 2020}]

    Args:
        params (dict): Dictionary containing all required parameters:
            - aoi: Area of Interest specification
            - error_polygons: Error polygons for recoding
            - iso (str): ISO country code
            - boundary_dataset (str, optional): Boundary dataset name (default: "UN")
            - productivity_dataset (str, optional): Productivity dataset mode (default: TRENDS_EARTH_5_CLASS_LPD)
            - write_tifs (bool, optional): Whether to write GeoTIFF outputs (default: False)
            - substr_regexs (list, optional): Additional regex patterns for job matching
            - ENV (str, optional): Environment ("dev" for development)
            - EXECUTION_ID (str, optional): Execution identifier (auto-generated in dev)
        logger: Logger instance for logging messages

    Returns:
        dict: Serialized results from the error recoding process
    """
    logger.debug("Loading parameters.")
    logger.debug(f"Initial params: {params}")

    # Check the ENV. Are we running this locally or in prod?

    if params.get("ENV") == "dev":
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get("EXECUTION_ID", None)
    logger.debug(f"Execution ID is {EXECUTION_ID}")

    aoi = AOI(params["aoi"])
    logger.debug("AOI loaded.")
    error_polygons = ErrorRecodePolygons.Schema().load(params["error_polygons"])
    logger.debug("Error polygons loaded.")
    iso = params["iso"]
    boundary_dataset = params.get("boundary_dataset", "UN")
    productivity_dataset = params.get(
        "productivity_dataset", ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value
    )
    write_tifs = params.get("write_tifs", False)

    substr_regexs = params.get("substr_regexs", [])
    substr_regexs.append(productivity_dataset)
    logger.debug(
        f"Final parameters for calculate_error_recode: "
        f"iso={iso}, productivity_dataset={productivity_dataset}, "
        f"boundary_dataset={boundary_dataset}, "
        f"substr_regexs={substr_regexs}, write_tifs={write_tifs}"
    )

    logger.debug("Calling calculate_error_recode.")
    return calculate_error_recode(
        aoi,
        error_polygons,
        "sdg-15-3-1-summary-2-1-17",
        iso,
        boundary_dataset,
        substr_regexs,
        write_tifs,
        EXECUTION_ID,
        logger,
    )
