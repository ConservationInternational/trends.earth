"""
Code for calculating soil organic carbon indicator.
"""
# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from builtins import str
import random
import json

import ee

from landdegradation.soc import soc
from te_schemas.land_cover import LCTransitionDefinitionDeg, LCLegendNesting


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    year_start = params.get('year_start')
    year_end = params.get('year_end')
    fl = params.get('fl')
    dl_annual_lc = params.get('download_annual_lc')
    geojsons = json.loads(params.get('geojsons'))
    crs = params.get('crs')
    trans_matrix = LCTransitionDefinitionDeg.Schema().load(
        params.get('trans_matrix')
    )
    legend_nesting = LCLegendNesting.Schema().load(
        params.get('legend_nesting')
    )

    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    logger.debug("Running main script.")
    out = soc(
        year_start,
        year_end,
        fl,
        trans_matrix,
        legend_nesting,
        dl_annual_lc,
        logger
    )

    return out.export(geojsons, 'soil_organic_carbon', crs, logger, EXECUTION_ID)
