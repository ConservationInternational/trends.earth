# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import random
import json
from time import sleep

import ee

from landdegradation import preproc
from landdegradation import stats
from landdegradation import util

from landdegradation.schemas import GEEResults, CloudDataset, CloudUrl, GEEResultsSchema

# Google cloud storage bucket for output
BUCKET = "ldmt"

def integral_trend(year_start, year_end, geojson, resolution, dataset, 
        EXECUTION_ID, logger):
    """Calculate annual trend of integrated NDVI.

    Calculates the trend of annual integrated NDVI using NDVI data from the
    MODIS Collection 6 MOD13Q1 dataset. Areas where changes are not significant
    are masked out using a Mann-Kendall test.

    Args:
        year_start: The starting year (to define the period the trend is
            calculated over).
        year_end: The ending year (to define the period the trend is
            calculated over).
        geojson: A polygon defining the area of interest.
        EXECUTION_ID: String identifying this process, used in naming the 
            results.

    Returns:
        Location of output on google cloud storage.
    """ 

    logger.debug("Entering integral_trend function.")

    # Compute NDVI annual integrals from 15d observed NDVI data
    ndvi_1yr_o = preproc.modis_ndvi_annual_integral(year_start, year_end)

    # Compute linear trend function to predict ndvi based on year (ndvi trend)
    lf_trend = ndvi_1yr_o.select(['year', 'ndvi']).reduce(ee.Reducer.linearFit())

    # Define Kendall parameter values for a significance of 0.05
    period = year_end - year_start + 1
    coefficients = ee.Array([4, 6, 9, 11, 14, 16, 19, 21, 24, 26, 31, 33, 36,
                             40, 43, 47, 50, 54, 59, 63, 66, 70, 75, 79, 84,
                             88, 93, 97, 102, 106, 111, 115, 120, 126, 131,
                             137, 142])
    kendall = coefficients.get([period - 4])

    # Compute Kendall statistics
    mk_trend = stats.mann_kendall(ndvi_1yr_o.select('ndvi'))

    export = {
        'image': lf_trend.select('scale').where(mk_trend.abs().lte(kendall), -99999).where(lf_trend.select('scale').abs().lte(0.000001), -99999).unmask(-99999),
        'description': EXECUTION_ID,
        'fileNamePrefix': EXECUTION_ID,
        'bucket': BUCKET,
        'maxPixels': 10000000000,
        'scale': 250,
        'region': util.get_coords(geojson)
    }

    logger.debug("Setting up task.")
    task = ee.batch.Export.image.toCloudStorage(**export)

    logger.debug("Starting task.")
    task.start()
    task_state = task.status().get('state')
    while task_state == 'READY' or task_state == 'RUNNING':
        task_progress = task.status().get('progress', 0.0)
        # update GEF-EXECUTION progress
        logger.send_progress(task_progress)
        logger.debug("Task progress {}.".format(task_progress))
        # update variable to check the condition
        task_state = task.status().get('state')
        sleep(5)

    logger.debug("Leaving integral_trends function.")
    return "https://{}.storage.googleapis.com/{}.tif".format(BUCKET, EXECUTION_ID)

def run(params, logger):
    """."""
    logger.debug("Loading parameters.")

    year_start = params.get('year_start', 2003)
    year_end = params.get('year_end', 2015)
    geojson = json.loads(params.get('geojson', util.sen_geojson))
    resolution = params.get('resolution', 250)
    dataset = params.get('dataset', 'AVHRR')

    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    logger.debug("Running main script.")
    url = integral_trend(year_start, year_end, geojson, resolution, dataset, 
            EXECUTION_ID, logger)

    logger.debug("Setting up results JSON.")
    results_url = CloudUrl(url, 'TODO_HASH_GOES_HERE') 
    cloud_dataset = CloudDataset('geotiff', 'integral_trends', results_url)
    gee_results = GEEResults('cloud_dataset', cloud_dataset)
    results_schema = GEEResultsSchema()
    json_result = results_schema.dump(gee_results)

    logger.debug("Leaving run function.")
    return json_result.data
