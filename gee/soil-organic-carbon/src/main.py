"""
Code for calculating soil organic carbon indicator.
"""
# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import json
import random
from builtins import str

from te_algorithms.gee.soc import soc
from te_algorithms.gee.util import teimage_v1_to_teimage_v2
from te_schemas.land_cover import LCLegendNesting
from te_schemas.land_cover import LCTransitionDefinitionDeg


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    year_initial = params.get("year_initial")
    year_final = params.get("year_final")
    fl = params.get("fl")
    dl_annual_lc = params.get("download_annual_lc")
    geojsons = json.loads(params.get("geojsons"))
    crs = params.get("crs")
    trans_matrix = LCTransitionDefinitionDeg.Schema().load(params.get("trans_matrix"))
    legend_nesting = LCLegendNesting.Schema().load(params.get("legend_nesting"))

    # Check the ENV. Are we running this locally or in prod?

    if params.get("ENV") == "dev":
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get("EXECUTION_ID", None)
    logger.debug(f"Execution ID is {EXECUTION_ID}")

    logger.debug("Running main script.")
    out = soc(
        year_initial, year_final, fl, trans_matrix, legend_nesting, dl_annual_lc, logger
    )

    out = teimage_v1_to_teimage_v2(out)

    return out.export(geojsons, "soil_organic_carbon", crs, logger, EXECUTION_ID)
