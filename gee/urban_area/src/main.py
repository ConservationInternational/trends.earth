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
from landdegradation.schemas.schemas import CloudResultsSchema


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    un_adju = params.get('un_adju')
    geojsons = json.loads(params.get('geojsons'))
    crs = params.get('crs')

    proj = ee.Image("users/geflanddegradation/toolbox_datasets/urban_series").projection()

    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    logger.debug("Running main script.")
    outs = []
    for geojson in geojsons:
        this_out = None
        urb = urban_area(geojson, un_adju, EXECUTION_ID, logger)
        if not this_out:
            this_out = urb
        else:
            this_out.merge(urb)
        outs.append(this_out.export([geojson], 'urban_area', crs, logger, 
                                    EXECUTION_ID, proj))
    schema = CloudResultsSchema()
    logger.debug("Deserializing")
    final_output = schema.load(outs[0])
    for o in outs[1:]:
        this_out = schema.load(o)
        final_output.urls.extend(this_out.urls)
    logger.debug("Serializing")
    # Now serialize the output again and return it
    return schema.dump(final_output)
