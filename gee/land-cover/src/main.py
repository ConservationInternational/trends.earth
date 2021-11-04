"""
Code for calculating land cover change indicator.
"""
# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from builtins import str
import random
import json

import ee

from te_algorithms.gee.land_cover import land_cover
from te_schemas.land_cover import LCTransitionDefinitionDeg, LCLegendNesting


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    year_initial = params.get('year_initial')
    year_final = params.get('year_final')
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
    out = land_cover(
        year_initial,
        year_final,
        trans_matrix,
        legend_nesting,
        [],
        logger
    )

    return out.export(geojsons, 'land_cover', crs, logger, EXECUTION_ID)
