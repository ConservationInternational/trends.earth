"""
Code for downloading dataset.
"""
# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import random
import json

import ee

from landdegradation import preproc
from landdegradation import stats
from landdegradation import util
from landdegradation import GEEIOError

from landdegradation.schemas import GEEResults, CloudDataset, CloudUrl, GEEResultsSchema

def download(geojson, asset, EXECUTION_ID, logger):
    """
    Download dataset from GEE assets.
    """
    logger.debug("Entering download function.")

    d = ee.Image(asset)

    task = util.export_to_cloudstorage(d.int16(), 
            d.projection(), geojson, 'download', logger, 
            EXECUTION_ID)
    task.join()

    logger.debug("Setting up results JSON.")
    cloud_dataset = CloudDataset('geotiff', 'download', [CloudUrl(task.url())])
    gee_results = GEEResults('download', [cloud_dataset])
    results_schema = GEEResultsSchema()
    json_results = results_schema.dump(gee_results)

    return json_results

def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    geojson = params.get('geojson', util.tza_geojson)
    asset = params.get('asset', None)

    logger.debug("Loading geojson.")
    if geojson is None:
        raise GEEIOError("Must specify an input area")
    else:
        geojson = json.loads(geojson)

    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    logger.debug("Running main script.")
    json_results = download(geojson, asset, EXECUTION_ID, logger)

    return json_results.data
