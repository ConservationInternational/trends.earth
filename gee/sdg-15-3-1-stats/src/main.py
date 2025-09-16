"""
Code for calculating all three SDG 15.3.1 sub-indicators.
"""

# Copyright 2017 Conservation International
import hashlib
import json
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


def _load_band(name, filters, input_job, logger, return_band=True):
    try:
        band_data, band = util.get_band_by_name(input_job, name, filters, return_band)
    except Exception as exc:
        logger.exception(f"Failed to load band {name} with filters {filters}")
        raise exc

    if band_data is not None:
        return {
            "name": name,
            "index": band_data.band_number,
            "metadata": band.metadata if hasattr(band, "metadata") else {},
        }
    else:
        logger.exception(f"Failed to load band {name}")
        raise ValueError(f"Band {name} could not be loaded")


def _hash_band(band: Dict) -> str:
    """Generate a unique hash for a band based on its properties."""
    return hashlib.md5(
        f"{band['name']}_{band['index']}_"
        f"{json.dumps(band.get('metadata', {}), sort_keys=True)}".encode()
    ).hexdigest()


_band_key = {
    "baseline": {
        "name": "SDG 15.3.1 Indicator",
        "filters": [{"field": "year_final", "value": 2015}],
    },
    "report_1": {
        "name": "SDG 15.3.1 Indicator (status)",
        "filters": [{"field": "reporting_year_final", "value": 2019}],
    },
    "report_2": {
        "name": "SDG 15.3.1 Indicator (status)",
        "filters": [{"field": "reporting_year_final", "value": 2023}],
    },
}

_crosstabs = [("baseline", "report_1"), ("baseline", "report_2")]


def run_stats(
    polygons,
    script_name: str,
    iso: str,
    stats_periods: list,
    crosstabs: list,
    boundary_dataset: str,
    substr_regexs,
    logger,
):
    """
    Calculate statistics for land degradation indicators.

    This function processes multiple bands and calculates statistics for each polygon,
    with optional crosstab analysis between specified band pairs.

    Args:
        polygons: Error polygons for which to calculate statistics
        script_name (str): Name of the script used to generate input data
        iso (str): ISO country code
        stats_periods (list): List of periods to calculate statistics for. Valid values are:
                             baseline, report_1, report_2
        crosstabs (list): List of period pairs for crosstab analysis.
                          Example: [(baseline, report_1), (baseline, report_2)]
        boundary_dataset (str): Boundary dataset name
        substr_regexs: List of regex patterns for job matching
        logger: Logger instance for logging messages

    Returns:
        dict: Serialized JsonResults containing statistics for each band and polygon,
              plus crosstab analysis for specified band pairs when applicable
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
        stats_band_datas = {}
        for period, value in _band_key.items():
            band_info = _load_band(
                value["name"], value.get("filters", None), input_job, logger
            )
            stats_band_datas[period] = {
                "name": band_info["name"],
                "index": band_info["index"],
                "metadata": band_info["metadata"],
            }

        crosstab_band_datas = []
        for period1, period2 in crosstabs:
            band1 = _band_key[period1]
            band2 = _band_key[period2]
            if period1 not in stats_band_datas or period2 not in stats_band_datas:
                logger.error(
                    f"Crosstab bands must be included in stats bands. Missing: "
                    f"{band1['name']} or {band2['name']}"
                )
                raise ValueError(
                    f"Crosstab bands must be included in stats bands. Missing: "
                    f"{band1['name']} or {band2['name']}"
                )
            crosstab_band_datas.append((period1, period2))

    except Exception as exc:
        logger.error(f"Error processing bands: {exc}")
        raise exc

    # Use the original band_datas without period suffixes so mask functions work correctly
    params = {
        "path": str(input_job.results.uri.uri),
        "band_datas": stats_band_datas,
        "polygons": ErrorRecodePolygons.Schema().dump(polygons),
        "crosstabs": crosstab_band_datas if crosstab_band_datas else None,
    }

    return JsonResults.Schema().dump(calculate_statistics(params))


def run(params, logger):
    """
    Run statistics calculation for land degradation indicators.

    Supports both single-period and multi-period land degradation jobs.
    The function builds a dictionary mapping period names to band configurations based
    on the periods parameter, making the relationship between periods and data clear.

    The function automatically calculates crosstabs between baseline and reporting
    periods when multiple periods are provided, showing land degradation transitions over time.

    Args:
        params (dict): Dictionary containing all required parameters:
            - polygons: Error polygons for statistics calculation
            - script_name (str): Name of the script used to generate input data
            - iso (str): ISO country code
            - periods (list, optional): List of periods to include. Defaults to ["baseline"].
                                        Can include "baseline", "report_1", "report_2"
            - crosstabs(list[tuple], optional): periods to compare using crosstabs, as list of tuples.
                                                Can include "baseline", "report_1", "report_2"
            - boundary_dataset (str, optional): Boundary dataset name (default: "UN")
            - productivity_dataset (str, optional): Productivity dataset mode (default: TRENDS_EARTH_5_CLASS_LPD)
            - substr_regexs (list, optional): Additional regex patterns for job matching
            - ENV (str, optional): Environment ("dev" for development)
            - EXECUTION_ID (str, optional): Execution identifier (auto-generated in dev)
        logger: Logger instance for logging messages

    Returns:
        dict: Serialized JsonResults containing statistics for each band and polygon,
              plus crosstab analysis between baseline and reporting periods when applicable
    """
    logger.debug("Loading parameters.")

    # Check the ENV. Are we running this locally or in prod?

    if params.get("ENV") == "dev":
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get("EXECUTION_ID", None)
    logger.debug(f"Execution ID is {EXECUTION_ID}")

    polygons = ErrorRecodePolygons.Schema().load(params["polygons"])
    script_name = params["script_name"]
    iso = params["iso"]
    boundary_dataset = params.get("boundary_dataset", "UN")
    productivity_dataset = params.get(
        "productivity_dataset", ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value
    )

    substr_regexs = params.get("substr_regexs", [])
    substr_regexs.append(productivity_dataset)

    return run_stats(
        polygons,
        script_name,
        iso,
        params.get("periods", ["baseline"]),
        params.get("crosstabs", []),
        boundary_dataset,
        substr_regexs,
        logger,
    )
