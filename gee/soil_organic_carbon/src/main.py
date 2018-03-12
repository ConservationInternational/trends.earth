"""
Code for calculating soil organic carbon indicator.
"""
# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import random
import json

import ee

from landdegradation.soc import soc


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    year_start = params.get('year_start')
    year_end = params.get('year_end')
    fl = params.get('fl')
    dl_annual_lc = params.get('download_annual_lc')
    geojsons = json.loads(params.get('geojsons'))
    crs = params.get('crs')
    remap_matrix = params.get('remap_matrix')

    if len(remap_matrix) != 2 or len(remap_matrix[0]) != 37 or len(remap_matrix[1]) != 37:
        raise GEEIOError("Transition matrix must be a list of two lists with 37 entries each")

    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    logger.debug("Running main script.")
    out = soc(year_start, year_end, fl, remap_matrix, dl_annual_lc, 
              EXECUTION_ID, logger)

    return out.export(geojsons, 'soil_organic_carbon', crs, logger, EXECUTION_ID)
