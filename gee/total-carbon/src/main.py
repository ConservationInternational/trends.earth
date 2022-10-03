"""
Code for calculating total carbon.
"""
# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import json
import random
from builtins import str

from te_algorithms.gee.carbon import tc
from te_algorithms.gee.util import teimage_v1_to_teimage_v2


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    fc_threshold = params.get("fc_threshold")
    year_initial = params.get("year_initial")
    year_final = params.get("year_final")
    method = params.get("method")
    biomass_data = params.get("biomass_data")
    geojsons = json.loads(params.get("geojsons"))
    crs = params.get("crs")

    # Check the ENV. Are we running this locally or in prod?

    if params.get("ENV") == "dev":
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get("EXECUTION_ID", None)
    logger.debug(f"Execution ID is {EXECUTION_ID}")

    logger.debug("Running main script.")
    out = tc(
        fc_threshold,
        year_initial,
        year_final,
        method,
        biomass_data,
        EXECUTION_ID,
        logger,
    )

    out = teimage_v1_to_teimage_v2(out)

    return out.export(geojsons, "total_carbon", crs, logger, EXECUTION_ID)
