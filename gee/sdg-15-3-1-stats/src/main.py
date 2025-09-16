"""
Code for calculating all three SDG 15.3.1 sub-indicators.
"""

# Copyright 2017 Conservation International
import hashlib
import json
import random
from typing import Dict

from marshmallow import Schema, ValidationError, fields, validate, validates_schema
from te_algorithms.api import util
from te_algorithms.gdal.land_deg.land_deg_stats import calculate_statistics
from te_schemas.error_recode import ErrorRecodePolygons
from te_schemas.productivity import ProductivityMode
from te_schemas.results import JsonResults

S3_PREFIX_RAW_DATA = "prais5-raw"
S3_BUCKET_INPUT = "trends.earth-private"
S3_REGION = "us-east-1"
S3_BUCKET_USER_DATA = "trends.earth-users"


class SDGStatsParametersSchema(Schema):
    """
    Marshmallow schema for validating SDG 15.3.1 statistics calculation parameters.

    This schema ensures that all required parameters are provided and validates
    their types and values for the land degradation statistics calculation.
    """

    polygons = fields.Nested(
        ErrorRecodePolygons.Schema,
        required=True,
        metadata={
            "description": "Error polygons for statistics calculation. Must be valid ErrorRecodePolygons data that will be automatically validated and deserialized."
        },
    )

    iso = fields.Str(
        required=True,
        validate=validate.Length(equal=3),
        metadata={
            "description": "ISO country code (exactly 3 characters). Used for data identification and S3 prefix construction."
        },
    )

    periods = fields.List(
        fields.Str(validate=validate.OneOf(["baseline", "report_1", "report_2"])),
        load_default=["baseline"],
        metadata={
            "description": "List of periods to include in statistics calculation. Valid values: baseline, report_1, report_2."
        },
    )

    crosstabs = fields.List(
        fields.Tuple(
            (
                fields.Str(
                    validate=validate.OneOf(["baseline", "report_1", "report_2"])
                ),
                fields.Str(
                    validate=validate.OneOf(["baseline", "report_1", "report_2"])
                ),
            )
        ),
        load_default=[],
        metadata={
            "description": "List of period pairs for crosstab analysis. Each tuple contains two different period names to compare."
        },
    )

    boundary_dataset = fields.Str(
        load_default="UN",
        validate=validate.OneOf(["UN", "NaturalEarth"]),
        metadata={
            "description": "Boundary dataset name used for analysis. Valid values: 'UN' or 'NaturalEarth'. Defaults to 'UN'."
        },
    )

    productivity_dataset = fields.Str(
        load_default=ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value,
        validate=validate.OneOf([mode.value for mode in ProductivityMode]),
        metadata={
            "description": f"Productivity dataset mode. Valid values: {[mode.value for mode in ProductivityMode]}. Defaults to TRENDS_EARTH_5_CLASS_LPD."
        },
    )

    substr_regexs = fields.List(
        fields.Str(),
        load_default=[],
        metadata={
            "description": "Additional regex patterns for job matching when searching S3 data."
        },
    )

    ENV = fields.Str(
        load_default=None,
        validate=validate.OneOf(["dev", "staging", "prod"]),
        allow_none=True,
        metadata={
            "description": "Environment setting. When 'dev', generates random execution ID for local development."
        },
    )

    EXECUTION_ID = fields.Str(
        load_default=None,
        allow_none=True,
        metadata={
            "description": "Execution identifier. Auto-generated in development environment if not provided."
        },
    )

    @validates_schema
    def validate_crosstabs(self, data, **kwargs):
        """
        Validate that crosstab pairs contain different periods.

        Args:
            data: The input data dictionary

        Raises:
            ValidationError: If any crosstab pair contains identical periods
        """
        crosstabs = data.get("crosstabs", [])
        for i, (period1, period2) in enumerate(crosstabs):
            if period1 == period2:
                raise ValidationError(
                    f"Crosstab pair {i + 1} contains identical periods '{period1}'. "
                    "Each crosstab pair must contain two different periods.",
                    field_name="crosstabs",
                )


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

    This function validates input parameters using marshmallow schema before processing,
    ensuring data integrity and providing clear error messages for invalid inputs.

    Supports both single-period and multi-period land degradation jobs.
    The function builds a dictionary mapping period names to band configurations based
    on the periods parameter, making the relationship between periods and data clear.

    The function automatically calculates crosstabs between baseline and reporting
    periods when multiple periods are provided, showing land degradation transitions over time.

    Args:
        params (dict): Dictionary containing all required parameters, validated by SDGStatsParametersSchema:
            - polygons (required): Error polygons for statistics calculation (ErrorRecodePolygons data)
            - iso (required, str): ISO country code (exactly 3 characters)
            - periods (optional, list): List of periods ["baseline", "report_1", "report_2"]. Defaults to ["baseline"]
            - crosstabs (optional, list[tuple]): Period pairs for crosstab analysis (pairs must be different). Defaults to []
            - boundary_dataset (optional, str): Boundary dataset name ("UN" or "NaturalEarth"). Defaults to "UN"
            - productivity_dataset (optional, str): Productivity dataset mode. Defaults to TRENDS_EARTH_5_CLASS_LPD
            - substr_regexs (optional, list): Additional regex patterns for job matching. Defaults to []
            - ENV (optional, str): Environment ("dev", "staging", "prod"). Auto-generates execution ID in dev
            - EXECUTION_ID (optional, str): Execution identifier. Auto-generated in dev if not provided
        logger: Logger instance for logging messages

    Returns:
        dict: Serialized JsonResults containing statistics for each band and polygon,
              plus crosstab analysis between specified periods when applicable

    Raises:
        ValueError: If parameter validation fails or required parameters are missing/invalid
        ValidationError: If marshmallow schema validation fails
    """
    logger.debug("Loading parameters.")

    # Validate and deserialize parameters using marshmallow schema
    try:
        schema = SDGStatsParametersSchema()
        validated_params = schema.load(params)
        logger.debug("Parameters validated successfully")
    except ValidationError as e:
        logger.error(f"Parameter validation failed: {e.messages}")
        raise ValueError(f"Invalid parameters: {e.messages}")

    # Ensure we have a valid dictionary (marshmallow should return dict)
    if not isinstance(validated_params, dict):
        raise ValueError("Parameter validation returned unexpected result")

    # Check the ENV. Are we running this locally or in prod?
    env_value = validated_params.get("ENV")
    if env_value == "dev":
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = validated_params.get("EXECUTION_ID")
    logger.debug(f"Execution ID is {EXECUTION_ID}")

    polygons = validated_params.get("polygons")

    iso = validated_params["iso"]
    boundary_dataset = validated_params.get("boundary_dataset", "UN")
    productivity_dataset = validated_params.get(
        "productivity_dataset", ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value
    )
    periods = validated_params.get("periods", ["baseline"])
    crosstabs = validated_params.get("crosstabs", [])
    substr_regexs_list = validated_params.get("substr_regexs", [])
    substr_regexs = list(substr_regexs_list) if substr_regexs_list else []

    # Add productivity dataset to regex filters
    if productivity_dataset:
        substr_regexs.append(productivity_dataset)

    return run_stats(
        polygons,
        "sdg-15-3-1-summary",
        iso,
        periods,
        crosstabs,
        boundary_dataset,
        substr_regexs,
        logger,
    )
