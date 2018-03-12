"""
Code for calculating land cover change indicator.
"""
# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import random
import json

import ee

from landdegradation.land_cover import land_cover


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    year_baseline = params.get('year_baseline')
    year_target = params.get('year_target')
    geojsons = json.loads(params.get('geojsons'))
    crs = params.get('crs')
    trans_matrix = params.get('trans_matrix')
    remap_matrix = params.get('remap_matrix')

    if len(trans_matrix) != 49:
        raise GEEIOError("Transition matrix must be a list with 49 entries")
    if len(remap_matrix) != 2 or len(remap_matrix[0]) != 37 or len(remap_matrix[1]) != 37:
        raise GEEIOError("Transition matrix must be a list of two lists with 37 entries each")

    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    logger.debug("Running main script.")
    out = land_cover(year_baseline, year_target, trans_matrix,
                     remap_matrix, EXECUTION_ID, logger)

    return out.export(geojsons, 'land_cover', crs, logger, EXECUTION_ID)
