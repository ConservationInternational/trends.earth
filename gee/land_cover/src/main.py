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

from landdegradation.land_cover import land_cover
from te_schemas.land_cover import LCTransMatrix, LCLegendNesting


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    year_baseline = params.get('year_baseline')
    year_target = params.get('year_target')
    geojsons = json.loads(params.get('geojsons'))
    crs = params.get('crs')
    trans_matrix = LCTransMatrix.Schema().loads(params.get('trans_matrix'))
    nesting = LCLegendNesting.Schema().loads(params.get('nesting'))

    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    logger.debug("Running main script.")
    out = land_cover(year_baseline, year_target, trans_matrix,
                     nesting, EXECUTION_ID, logger)

    return out.export(geojsons, 'land_cover', crs, logger, EXECUTION_ID)
