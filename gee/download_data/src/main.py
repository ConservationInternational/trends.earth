"""
Code for downloading dataset.
"""
# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from builtins import str
import random
import json

import ee

from landdegradation import GEEIOError
from landdegradation.download import download


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    asset = params.get('asset')
    name = params.get('name')
    start_year = None
    end_year = None
    temporal_resolution = params.get('temporal_resolution')
    geojsons = json.loads(params.get('geojsons'))
    crs = params.get('crs')

    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    logger.debug("Running main script.")
    out = download(asset, name, temporal_resolution, start_year, end_year, 
                   EXECUTION_ID, logger)
    return out.export(geojsons, 'download', crs, logger, EXECUTION_ID)
