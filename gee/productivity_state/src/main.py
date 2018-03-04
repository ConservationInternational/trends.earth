"""
Code for calculating vegetation productivity state.
"""
# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import random
import json

import ee

from landdegradation.productivity import productivity_state


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    year_bl_start = params.get('year_bl_start')
    year_bl_end = params.get('year_bl_end')
    year_tg_start = params.get('year_tg_start')
    year_tg_end = params.get('year_tg_end')
    geojson = json.loads(params.get('geojson'))
    ndvi_gee_dataset = params.get('ndvi_gee_dataset')

    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    logger.debug("Running main script.")
    out = productivity_state(year_bl_start, year_bl_end, year_tg_start,
                             year_tg_end, ndvi_gee_dataset, geojson, 
                             EXECUTION_ID, logger)

    proj = ee.Image(ndvi_gee_dataset).projection()
    return out.export(geojson, 'prod_state', logger, EXECUTION_ID, proj)
