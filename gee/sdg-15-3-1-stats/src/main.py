"""
Code for calculating all three SDG 15.3.1 sub-indicators.
"""

# Copyright 2017 Conservation International
import random
from typing import Dict

from te_algorithms.api import util
from te_algorithms.gdal.land_deg.land_deg_stats import calculate_statistics
from te_schemas.error_recode import ErrorRecodePolygons
from te_schemas.productivity import ProductivityMode
from te_schemas.results import JsonResults

S3_PREFIX_RAW_DATA = "prais5-raw"
S3_BUCKET_INPUT = "trends.earth-private"
S3_REGION = "us-east-1"
S3_BUCKET_USER_DATA = "trends.earth-users"


def run_stats(
    error_polygons,
    script_name: str,
    iso: str,
    bands: Dict,
    boundary_dataset: str,
    substr_regexs,
    logger,
):
    """
    Calculate statistics for land degradation indicators.

    This function supports both single-period and multi-period land degradation jobs.
    For multi-period jobs, specify the reporting year using filters in the bands parameter:
    bands = {"name": "Band Name", "filters": [{"field": "reporting_year_final", "value": 2020}]}

    Args:
        error_polygons: Error polygons for which to calculate statistics
        script_name (str): Name of the script used to generate input data
        iso (str): ISO country code
        bands (Dict): Dictionary of bands to process, each with 'name' and optional 'filters'.
                     For multi-period jobs, include filters with reporting year:
                     {"name": "Band Name", "filters": [{"field": "reporting_year_final", "value": year}]}
        boundary_dataset (str): Boundary dataset name
        substr_regexs: List of regex patterns for job matching
        logger: Logger instance for logging messages

    Returns:
        dict: Serialized JsonResults containing statistics for each band and polygon
    """
    filename_base = iso
    filename_base += "_" + boundary_dataset
    filename_base += "_" + script_name
    s3_prefix = f"{S3_PREFIX_RAW_DATA}/" + filename_base
    logger.info(f"Looking for prefix {s3_prefix}")
    try:
        input_job = util.get_job_json_from_s3(
            s3_prefix=s3_prefix, s3_bucket=S3_BUCKET_INPUT, substr_regexs=substr_regexs
        )
        if input_job is None:
            raise IndexError(
                f"No job found for prefix {s3_prefix} "
                f" with substr_regexs {substr_regexs}"
            )
    except IndexError as exc:
        logger.error(f"Failed to load input job from prefix {s3_prefix}: {exc}")
        raise exc

    try:
        band_datas = []
        for band in bands:
            band_data = None
            try:
                band_data = util.get_band_by_name(
                    input_job, band["name"], band.get("filters", None)
                )
            except Exception as exc:
                logger.exception(
                    f"Failed to load band {band['name']} with filters {band.get('filters')}"
                )
                raise exc

            if band_data is not None:
                band_datas.append(
                    {"name": band["name"], "index": band_data.band_number}
                )
            else:
                logger.warning(f"Failed to load band {band['name']}, skipping")

    except Exception as exc:
        logger.error(f"Error processing bands: {exc}")
        raise exc

    logger.info(f"Using band_datas {band_datas}")

    params = {
        "path": str(input_job.results.uri.uri),
        "band_datas": band_datas,
        "error_polygons": ErrorRecodePolygons.Schema().dump(error_polygons),
    }

    logger.info("Starting statistics calculation")

    return JsonResults.Schema().dump(calculate_statistics(params))


def run(params, logger):
    """
    Run statistics calculation for land degradation indicators.

    Supports both single-period and multi-period land degradation jobs.
    For multi-period jobs, include reporting year filters in the bands parameter:
    bands = [{"name": "Band Name", "filters": [{"field": "reporting_year_final", "value": 2020}]}]

    Args:
        params (dict): Dictionary containing all required parameters:
            - error_polygons: Error polygons for statistics calculation
            - script_name (str): Name of the script used to generate input data
            - iso (str): ISO country code
            - bands (list): List of band specifications, each with 'name' and optional 'filters'.
                           For multi-period jobs, include filters with reporting year:
                           [{"name": "Band Name", "filters": [{"field": "reporting_year_final", "value": year}]}]
            - boundary_dataset (str, optional): Boundary dataset name (default: "UN")
            - productivity_dataset (str, optional): Productivity dataset mode (default: JRC_5_CLASS_LPD)
            - substr_regexs (list, optional): Additional regex patterns for job matching
            - ENV (str, optional): Environment ("dev" for development)
            - EXECUTION_ID (str, optional): Execution identifier (auto-generated in dev)
        logger: Logger instance for logging messages

    Returns:
        dict: Serialized JsonResults containing statistics for each band and polygon
    """
    logger.debug("Loading parameters.")

    # Check the ENV. Are we running this locally or in prod?

    if params.get("ENV") == "dev":
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get("EXECUTION_ID", None)
    logger.debug(f"Execution ID is {EXECUTION_ID}")

    error_polygons = ErrorRecodePolygons.Schema().load(params["error_polygons"])
    script_name = params["script_name"]
    iso = params["iso"]
    bands = params["bands"]
    boundary_dataset = params.get("boundary_dataset", "UN")
    productivity_dataset = params.get(
        "productivity_dataset", ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value
    )

    substr_regexs = params.get("substr_regexs", [])
    substr_regexs.append(productivity_dataset)

    return run_stats(
        error_polygons,
        script_name,
        iso,
        bands,
        boundary_dataset,
        substr_regexs,
        logger,
    )
