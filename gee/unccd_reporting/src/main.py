"""
Code for calculating total carbon.
"""
# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from builtins import str
import random
import json

import ee

# TODO:
#  1) take in an AOI
#  2) need to move JSON generation code to here, to run in GDAL on our server - 
#     for now limit the total area that can be processed so we don't kill our 
#     server
#  3) return a summary for that AOI
#  4) figure out how to parcel out tasks to AWS lambda workers
#  4) add an AWS lambda worker that can generate land deg statistics


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    parameters = params.get('parameters')
    geojsons = json.loads(params.get('geojsons'))
    crs = params.get('crs')

    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    logger.debug("Running main script.")
    out = tc(fc_threshold, year_start, year_end, method, biomass_data, 
             EXECUTION_ID, logger)

    return out.export(geojsons, 'total_carbon', crs, logger, EXECUTION_ID)
