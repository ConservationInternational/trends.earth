"""
Code for calculating soil organic carbon indicator.
"""

# Copyright 2017 Conservation International
import json
import random

from te_algorithms.gee.soc import soc
from te_algorithms.gee.util import teimage_v1_to_teimage_v2
from te_schemas.land_cover import LCLegendNesting


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
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

    # Check the ENV. Are we running this locally or in prod?

    if params.get("ENV") == "dev":
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get("EXECUTION_ID", None)
    logger.debug(f"Execution ID is {EXECUTION_ID}")

    logger.debug("Running main script.")
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
