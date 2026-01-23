"""
Code for calculating all three SDG 15.3.1 sub-indicators.
"""

# Copyright 2017 Conservation International
import hashlib
import json
import os
import random
import tempfile
from pathlib import Path
from typing import Dict

import te_algorithms.gdal.land_deg.config as ld_config
from te_algorithms.api import util
from te_algorithms.gdal.land_deg.land_deg_recode import (
    rasterize_error_recode,
    recode_errors,
)
from te_algorithms.gdal.land_deg.land_deg_stats import calculate_statistics
from te_schemas import algorithms
from te_schemas.aoi import AOI
from te_schemas.error_recode import ErrorRecodePolygons
from te_schemas.productivity import ProductivityMode
from te_schemas.results import Band, JsonResults, RasterResults

S3_PREFIX_RAW_DATA = "prais5-raw"
S3_BUCKET_INPUT = "trends.earth-private"
S3_REGION = "us-east-1"
S3_BUCKET_USER_DATA = "trends-earth-users"
ERROR_RECODE_BAND_NAME = "Error recode"
# Create ExecutionScript object directly since Schema() is not available
RECODE_SCRIPT = algorithms.ExecutionScript(
    id="sdg-15-3-1-error-recode",
    name="sdg-15-3-1-error-recode",
    version="1.13",
    run_mode=algorithms.AlgorithmRunMode.LOCAL,
)

_band_key = {
    "baseline": {
        "name": "SDG 15.3.1 Indicator",
        "filters": [{"field": "year_final", "value": 2015}],
    },
    "report_1": {
        "name": "SDG 15.3.1 Indicator",
        "filters": [{"field": "year_final", "value": 2019}],
    },
    "report_2": {
        "name": "SDG 15.3.1 Indicator",
        "filters": [{"field": "year_final", "value": 2023}],
    },
}


def _hash_band(band: Dict) -> str:
    """Generate a unique hash for a band based on its properties."""
    return hashlib.md5(
        f"{band['name']}_{band['index']}_"
        f"{json.dumps(band.get('metadata', {}), sort_keys=True)}".encode()
    ).hexdigest()


def _band_to_dict(band) -> Dict:
    """Convert a Band object to a dictionary format.

    Args:
        band: A Band object with name, no_data_value, metadata, add_to_map, and activated attributes.

    Returns:
        A dictionary representation of the band.
    """
    return {
        "name": band.name,
        "no_data_value": getattr(band, "no_data_value", int(ld_config.NODATA_VALUE)),
        "metadata": getattr(band, "metadata", {}),
        "add_to_map": getattr(band, "add_to_map", False),
        "activated": getattr(band, "activated", False),
    }


def _calculate_image_wide_crosstabs(input_job, aoi, periods_to_process, logger):
    """
    Calculate crosstab statistics for the entire image area.

    Args:
        input_job: The job containing the recoded raster data
        aoi: Area of interest geometry
        periods_to_process: Dictionary of periods and their band information
        logger: Logger instance

    Returns:
        List of crosstab dictionaries for baseline-to-reporting period combinations
    """
    logger.debug("Calculating image-wide crosstab statistics for error recoded data")

    crosstabs = []

    # Only calculate crosstabs between baseline and reporting periods
    if "baseline" not in periods_to_process:
        logger.warning("No baseline period found, cannot calculate crosstabs")
        return crosstabs

    baseline_period = periods_to_process["baseline"]

    for period_name, period_data in periods_to_process.items():
        if period_name == "baseline":
            continue  # Skip baseline vs baseline

        logger.debug(f"Calculating crosstab: baseline vs {period_name}")

        # Build band_datas dictionary for this crosstab pair
        baseline_band_info = {
            "name": baseline_period["band"].name,
            "index": baseline_period["band_number"],
            "metadata": baseline_period["band"].metadata
            if hasattr(baseline_period["band"], "metadata")
            else {},
        }

        period_band_info = {
            "name": period_data["band"].name,
            "index": period_data["band_number"],
            "metadata": period_data["band"].metadata
            if hasattr(period_data["band"], "metadata")
            else {},
        }

        baseline_hash = _hash_band(baseline_band_info)
        period_hash = _hash_band(period_band_info)

        band_datas = {
            baseline_hash: baseline_band_info,
            period_hash: period_band_info,
        }

        # Create a single polygon covering the entire AOI for image-wide analysis
        aoi_polygon_dict = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "uuid": "image_wide_analysis",
                    },
                    "geometry": aoi.geojson["features"][0][
                        "geometry"
                    ],  # Use AOI geometry
                }
            ],
        }

        # Prepare parameters for calculate_statistics
        stats_params = {
            "path": str(input_job.results.uri.uri),
            "band_datas": band_datas,
            "polygons": aoi_polygon_dict,
            "crosstabs": [(baseline_hash, period_hash)],
        }

        try:
            stats_result = calculate_statistics(stats_params)

            # Extract crosstab data and convert to the desired format
            if (
                hasattr(stats_result, "data")
                and stats_result.data
                and "stats" in stats_result.data
                and "image_wide_analysis" in stats_result.data["stats"]
                and "crosstabs" in stats_result.data["stats"]["image_wide_analysis"]
            ):
                crosstab_data = stats_result.data["stats"]["image_wide_analysis"][
                    "crosstabs"
                ][0]

                # Convert from area_ha to area_km2 and format for report
                crosstab_formatted = {
                    "from_period": "baseline",
                    "to_period": period_name,
                    "total_area_km2": round(
                        crosstab_data["total_area_ha"] / 100, 3
                    ),  # Convert ha to km2
                    "transitions": {},
                }

                # Process the crosstab matrix and convert to km2
                for from_class, to_classes in crosstab_data["crosstab"].items():
                    crosstab_formatted["transitions"][from_class] = {}
                    for to_class, stats in to_classes.items():
                        crosstab_formatted["transitions"][from_class][to_class] = {
                            "area_km2": round(
                                stats["area_ha"] / 100, 3
                            ),  # Convert ha to km2
                            "area_pct": round(stats["area_pct"], 2),
                        }

                crosstabs.append(crosstab_formatted)
                logger.debug(
                    f"Successfully calculated crosstab for baseline vs {period_name}"
                )

        except Exception as e:
            logger.warning(
                f"Failed to calculate crosstab for baseline vs {period_name}: {e}"
            )
            continue

    return crosstabs


def _recode_band(recode_params, write_tifs, aoi, execution_id, logger):
    logger.info("Starting error recoding calculation")
    with tempfile.TemporaryDirectory() as temp_dir:
        input_job_data = recode_params["input_job"]
        output_path_stem = Path(input_job_data.get("results_uri", "output")).stem

        recode_params["output_path"] = Path(temp_dir) / output_path_stem
        logger.debug(f"Set output path to: {recode_params['output_path']}")
        results = recode_errors(recode_params)
        logger.debug("recode_errors function finished.")

        # The results object is a Job, we need to work with its structure properly
        # Since we can't directly access .data attribute on Job, we'll handle this in the caller
        logger.debug(
            "_recode_band function completed, results structure will be handled in calculate_error_recode"
        )

        if write_tifs:
            logger.info("Writing tifs")
            logger.debug(f"Writing results to S3 with EXECUTION_ID: {execution_id}")
            results = util.write_results_to_s3_cog(
                results,
                aoi,
                filename_base=execution_id,
                s3_prefix="prais5-recode",
                s3_bucket=S3_BUCKET_USER_DATA,
            )
            logger.debug("Finished writing tifs to S3.")
        return results


def calculate_error_recode(
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

    aoi = AOI(
        input_job.results.data["report"]["metadata"]["area_of_interest"]["geojson"]
    )

    # Rasterize the error recode polygons
    with tempfile.TemporaryDirectory() as temp_dir:
        error_recode_tif = os.path.join(temp_dir, f"{EXECUTION_ID}_error_recode.vrt")
        logger.debug(
            f"Created temporary file for error recode raster: {error_recode_tif}"
        )
        try:
            rasterize_error_recode(
                Path(error_recode_tif), input_job.results.uri.uri, error_polygons
            )
            logger.debug(
                f"Successfully created error recode raster: {error_recode_tif}"
            )

            # Verify the file was created and exists
            if not os.path.exists(error_recode_tif):
                raise FileNotFoundError(
                    f"Error recode file was not created: {error_recode_tif}"
                )

        except Exception as exc:
            logger.error(f"Failed to rasterize error recode polygons: {exc}")
            raise

        # Create band definition for the error recode raster (first band)
        error_recode_band = Band(
            name=ERROR_RECODE_BAND_NAME,
            metadata={},
            no_data_value=int(ld_config.NODATA_VALUE),
            activated=True,
        )

        # Continue with processing inside the temp directory context
        # Determine which periods are directly affected by error polygons
        periods_affected = set()
        for polygon in error_polygons.features:
            if (
                hasattr(polygon.properties, "periods_affected")
                and polygon.properties.periods_affected
            ):
                for period in polygon.properties.periods_affected:
                    periods_affected.add(period)

        if not periods_affected:
            raise Exception(
                "No periods specified in error polygons; at least one period is required."
            )

        logger.debug(f"Periods directly affected by recoding: {periods_affected}")

        # Determine which periods to include in output:
        # - If baseline is affected, all periods need to be in output (baseline changes affect status calculations)
        # - If report_1 is affected, report_2 also needs to be included (report_1 changes affect report_2 context)
        # - If only report_2 is affected, only report_2 is included in output
        if "baseline" in periods_affected:
            periods_to_output = {"baseline", "report_1", "report_2"}
        elif "report_1" in periods_affected:
            periods_to_output = {"report_1", "report_2"}
        else:
            periods_to_output = periods_affected.copy()

        # Determine which periods to load for processing:
        # - Always need baseline for internal calculations (status maps require baseline reference)
        # - Plus any directly affected periods
        periods_to_load = periods_affected.copy()
        periods_to_load.add("baseline")  # Always need baseline for status calculations
        # Also need to load any period that will be in output
        periods_to_load.update(periods_to_output)

        # Convert to a dictionary for band loading
        periods_to_process = {period: {} for period in periods_to_load}

        logger.debug(f"Periods to load for processing: {periods_to_process}")
        logger.debug(f"Periods to include in output: {periods_to_output}")

        for period, value in periods_to_process.items():
            band_name = _band_key[period]["name"]
            filters = _band_key[period]["filters"]

            try:
                input_band_data = util.get_band_by_name(
                    input_job,
                    band_name,
                    filters,
                    return_band=True,
                )
            except IndexError:
                logger.exception(f"Failed to load band name {band_name}")
                raise
            except Exception as exc:
                logger.exception(
                    f"Failed to load band {band_name} with filters {filters}"
                )
                raise exc

            if input_band_data is None:
                raise Exception(f"Failed to load band {band_name}")

            # Handle the tuple returned by get_band_by_name
            if isinstance(input_band_data, tuple) and len(input_band_data) == 2:
                band_data, band = input_band_data
                logger.debug(
                    f"Found input band: {band.name} (band number {band_data.band_number})"
                )
                value["band"] = band
                value["band_number"] = band_data.band_number
            else:
                # Fallback if different format
                logger.debug("Found input band with unexpected format")
                value["band"] = input_band_data
                value["band_number"] = 1  # Default band number

        # Build recode_params with multi-band support
        # Include only essential input job metadata to reduce memory/size
        input_job_metadata = {
            "id": input_job.id,
            "task_name": input_job.task_name,
            "task_notes": input_job.task_notes,
            "created": getattr(input_job, "created", None),
            "results_uri": str(input_job.results.uri.uri)
            if input_job.results and input_job.results.uri
            else None,
        }

        # Convert Band objects to dict format
        baseline_band_dict = _band_to_dict(periods_to_process["baseline"]["band"])
        error_recode_band_dict = _band_to_dict(error_recode_band)

        # Convert error_polygons to dict format manually
        error_polygons_dict = {
            "type": "FeatureCollection",
            "features": [],
            "name": getattr(error_polygons, "name", None),
            "crs": getattr(error_polygons, "crs", None),
        }

        for feature in error_polygons.features:
            feature_dict = {
                "type": "Feature",
                "properties": {
                    "uuid": str(feature.properties.uuid),
                    "periods_affected": getattr(
                        feature.properties, "periods_affected", []
                    ),
                    "location_name": getattr(feature.properties, "location_name", None),
                    "area_km_sq": getattr(feature.properties, "area_km_sq", None),
                    "process_driving_change": getattr(
                        feature.properties, "process_driving_change", None
                    ),
                    "basis_for_judgement": getattr(
                        feature.properties, "basis_for_judgement", None
                    ),
                    "recode_deg_to": getattr(feature.properties, "recode_deg_to", None),
                    "recode_stable_to": getattr(
                        feature.properties, "recode_stable_to", None
                    ),
                    "recode_imp_to": getattr(feature.properties, "recode_imp_to", None),
                },
                "geometry": feature.geometry,
            }
            error_polygons_dict["features"].append(feature_dict)

        recode_params = {
            "write_tifs": write_tifs,
            "local_context": input_job.local_context,  # Use directly instead of Schema().dump()
            "task_name": input_job.task_name,
            "metadata": periods_to_process["baseline"]["band"].metadata,
            "task_notes": input_job.task_notes,
            "layer_baseline_band_path": str(input_job.results.uri.uri),
            "layer_baseline_band": baseline_band_dict,
            "layer_baseline_band_index": periods_to_process["baseline"]["band_number"],
            "layer_error_recode_path": str(error_recode_tif),
            "layer_error_recode_band": error_recode_band_dict,
            "error_polygons": error_polygons_dict,
            "input_job": input_job_metadata,  # Use minimal metadata instead of full job
            "aoi": aoi.geojson,
            # Control which periods appear in output (summaries and rasters)
            "periods_to_output": list(periods_to_output),
        }

        # Include report_1 band if it's in output or needed for processing
        if "report_1" in periods_to_process:
            recode_params.update(
                {
                    "layer_reporting_1_band_path": str(input_job.results.uri.uri),
                    "layer_reporting_1_band": _band_to_dict(
                        periods_to_process["report_1"]["band"]
                    ),
                    "layer_reporting_1_band_index": periods_to_process["report_1"][
                        "band_number"
                    ],
                }
            )

        # Include report_2 band if it's in output or needed for processing
        if "report_2" in periods_to_process:
            recode_params.update(
                {
                    "layer_reporting_2_band_path": str(input_job.results.uri.uri),
                    "layer_reporting_2_band": _band_to_dict(
                        periods_to_process["report_2"]["band"]
                    ),
                    "layer_reporting_2_band_index": periods_to_process["report_2"][
                        "band_number"
                    ],
                }
            )

        results = _recode_band(recode_params, write_tifs, aoi, EXECUTION_ID, logger)

        # Generate crosstab statistics if baseline and at least one reporting period are in output
        # Crosstabs show transitions from baseline to reporting periods, so they require both
        crosstab_data = None
        has_baseline_in_output = "baseline" in periods_to_output
        has_reporting_in_output = (
            "report_1" in periods_to_output or "report_2" in periods_to_output
        )

        if has_baseline_in_output and has_reporting_in_output:
            logger.info(
                "Calculating image-wide crosstab statistics for error recoded data"
            )
            # Filter periods_to_process to only include periods that are in output
            periods_for_crosstab = {
                k: v for k, v in periods_to_process.items() if k in periods_to_output
            }
            try:
                crosstab_data = _calculate_image_wide_crosstabs(
                    input_job, aoi, periods_for_crosstab, logger
                )

                if crosstab_data:
                    logger.debug(
                        f"Successfully calculated {len(crosstab_data)} crosstab(s)"
                    )
                else:
                    logger.warning("No crosstab data generated")

            except Exception as e:
                logger.exception(f"Failed to calculate crosstab statistics: {e}")
        else:
            logger.debug(
                "Skipping crosstab calculation - requires both baseline and reporting periods in output"
            )

        # Convert results to dictionary format using marshmallow Schema serialization
        if isinstance(results, RasterResults):
            results_dict = RasterResults.Schema().dump(results)
        elif isinstance(results, JsonResults):
            results_dict = JsonResults.Schema().dump(results)
        else:
            raise Exception("Unknown results type")

        # Add crosstab data to the report section if available
        if crosstab_data and len(crosstab_data) > 0:
            if "data" not in results_dict:
                results_dict["data"] = {}
            if "report" not in results_dict["data"]:
                results_dict["data"]["report"] = {}

            # Add crosstabs to the report structure
            results_dict["data"]["report"]["crosstabs"] = crosstab_data
            logger.debug(
                f"Successfully added {len(crosstab_data)} crosstab(s) to results report"
            )

        logger.debug("calculate_error_recode function finished, returning results.")
        return results_dict


def run(params, logger):
    """
    Run error recoding for land degradation indicators.

    Supports both single-period and multi-period land degradation jobs.
    For multi-period jobs, include a reporting year filter in the filters parameter:
    filters = [{"field": "reporting_year_final", "value": 2020}]

    Args:
        params (dict): Dictionary containing all required parameters:
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

    # Check the ENV. Are we running this locally or in prod?

    if params.get("ENV") == "dev":
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get("EXECUTION_ID", None)
    logger.debug(f"Execution ID is {EXECUTION_ID}")

    # Load and deserialize error polygons using the schema
    error_polygons_data = params["error_polygons"]
    error_polygons = ErrorRecodePolygons.Schema().load(error_polygons_data)
    logger.debug("Error polygons loaded.")
    iso = params["iso"]
    boundary_dataset = params.get("boundary_dataset", "UN")
    productivity_dataset = params.get(
        "productivity_dataset", ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value
    )
    write_tifs = params.get("write_tifs", False)

    substr_regexs = params.get("substr_regexs", [])
    substr_regexs.append(productivity_dataset)

    logger.debug("Calling calculate_error_recode.")
    return calculate_error_recode(
        error_polygons,
        "sdg-15-3-1-summary-2-1-17",
        iso,
        boundary_dataset,
        substr_regexs,
        write_tifs,
        EXECUTION_ID,
        logger,
    )
