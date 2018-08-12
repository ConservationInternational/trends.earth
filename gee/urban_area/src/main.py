"""
Code for calculating urban area.
"""
# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import random
import json

import ee

from landdegradation.urban_area import urban_area


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    un_adju = params.get('un_adju')
    geojsons = json.loads(params.get('geojsons'))
    crs = params.get('crs')

    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    logger.debug("Running main script.")
    out = urban_area(un_adju, EXECUTION_ID, logger)

    return out.export(geojsons, 'urban_area', crs, logger, EXECUTION_ID)
