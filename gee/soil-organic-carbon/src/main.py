"""
Code for calculating soil organic carbon indicator.
"""

# Copyright 2017 Conservation International
import json
import random

from te_schemas.land_cover import LCLegendNesting


def _run_gee(params, logger):
    """Run SOC calculation using Google Earth Engine."""
    from te_algorithms.gee.soc import soc
    from te_algorithms.gee.util import teimage_v1_to_teimage_v2

    year_initial = params.get("year_initial")
    year_final = params.get("year_final")
    fl = params.get("fl")
    annual_lc = params.get("download_annual_lc")
    annual_soc = params.get("download_annual_soc")
    geojsons = json.loads(params.get("geojsons"))
    crs = params.get("crs")
    esa_to_custom_nesting = LCLegendNesting.Schema().load(
        params.get("legend_nesting_esa_to_custom")
    )
    ipcc_nesting = LCLegendNesting.Schema().load(
        params.get("legend_nesting_custom_to_ipcc")
    )

    if params.get("ENV") == "dev":
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get("EXECUTION_ID", None)
    logger.debug(f"Execution ID is {EXECUTION_ID}")

    logger.debug("Running GEE SOC script.")
    out = soc(
        year_initial,
        year_final,
        fl,
        esa_to_custom_nesting,
        ipcc_nesting,
        annual_lc,
        annual_soc,
        logger,
    )

    out = teimage_v1_to_teimage_v2(out)
    return out.export(geojsons, "soil_organic_carbon", crs, logger, EXECUTION_ID)


def _run_openeo(params, logger):
    """Run SOC calculation using openEO."""
    from gefcore.runner import initialize_openeo_connection
    from te_algorithms.openeo.soc import soc as openeo_soc

    year_initial = params.get("year_initial")
    year_final = params.get("year_final")
    fl = params.get("fl")
    annual_lc = params.get("download_annual_lc")
    annual_soc = params.get("download_annual_soc")
    geojsons = json.loads(params.get("geojsons"))

    esa_to_custom_nesting = LCLegendNesting.Schema().load(
        params.get("legend_nesting_esa_to_custom")
    )
    ipcc_nesting = LCLegendNesting.Schema().load(
        params.get("legend_nesting_custom_to_ipcc")
    )

    if params.get("ENV") == "dev":
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get("EXECUTION_ID", None)
    logger.debug(f"Execution ID is {EXECUTION_ID}")

    connection = initialize_openeo_connection()

    logger.debug("Running openEO SOC script.")
    job = openeo_soc(
        year_initial=year_initial,
        year_final=year_final,
        fl=fl,
        esa_to_custom_nesting=esa_to_custom_nesting,
        ipcc_nesting=ipcc_nesting,
        annual_lc=annual_lc,
        annual_soc=annual_soc,
        logger=logger,
        connection=connection,
        geojsons=geojsons,
        execution_id=EXECUTION_ID,
    )

    return {
        "openeo_job_id": job.job_id,
        "status": "submitted",
        "execution_id": EXECUTION_ID,
    }


def run(params, logger):
    """Entry point for the soil organic carbon script.

    Dispatches to either the GEE or openEO backend based on
    the ``EXECUTION_PROVIDER`` parameter.
    """
    logger.debug("Loading parameters.")

    execution_provider = params.get("EXECUTION_PROVIDER", "gee").lower()

    if execution_provider == "openeo":
        return _run_openeo(params, logger)
    else:
        return _run_gee(params, logger)
