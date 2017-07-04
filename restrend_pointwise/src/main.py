"""
Code for calculating temporal NDVI analysis.
"""
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

def restrend_pointwise(year_start, year_end, geojson, resolution, dataset, 
        EXECUTION_ID, logger):
    """Calculate temporal NDVI analysis.
    Calculates the trend of temporal NDVI using NDVI data from the
    MODIS Collection 6 MOD13Q1 dataset. Areas where changes are not significant
    are masked out using a Mann-Kendall test.
    Args:
        year_start: The starting year (to define the period the trend is
            calculated over).
        year_end: The ending year (to define the period the trend is
            calculated over).
        geojson: A polygon defining the area of interest.
    Returns:
        Output of google earth engine task.
    """
    logger.debug("Entering restrend_pointwise function.")

    # Function to integrate NDVI dataset from 15d to 1yr
    def int_15d_1yr_clim(img_stack):
        img_coll = ee.List([])
        for k in range(1, 34):
            ndvi_lyr = img_stack.select(ee.List.sequence((k-1)*24,(k*24)-1)).reduce(ee.Reducer.mean()).rename(['ndvi']).set({'year': 1981+k})
            img_coll = img_coll.add(ndvi_lyr)
        return ee.ImageCollection(img_coll)

    # Function to compute differences between observed and predicted NDVI and comilation in an image collection
    def stack(year_start, year_end):
        img_coll = ee.List([])
        for k in range(year_start, year_end):
            ndvi = ndvi_1yr_o.filter(ee.Filter.eq('year', k)).select('ndvi').median()
            clim = clim_1yr_o.filter(ee.Filter.eq('year', k)).select('ndvi').median()
            img = ndvi.addBands(clim.addBands(ee.Image(k).float())).rename(['ndvi','clim','year']).set({'year': k})
            img_coll = img_coll.add(img)
        return ee.ImageCollection(img_coll)

    # Function to predict NDVI from climate
    first = ee.List([])
    def ndvi_clim_p(image, list):
        ndvi = lf_clim_ndvi.select('offset').add((lf_clim_ndvi.select('scale').multiply(image))).set({'year': image.get('year')})
        return ee.List(list).add(ndvi)


    # Create image collection of residuals
    def ndvi_res(year_start, year_end): 
        img_coll = ee.List([])
        for k in range(year_start, year_end):
            ndvi_o = coll_1yr_o.filter(ee.Filter.eq('year', k)).select('ndvi').median()
            ndvi_p = ndvi_1yr_p.filter(ee.Filter.eq('year', k)).median()
            ndvi_r = ee.Image(k).float().addBands(ndvi_o.subtract(ndvi_p))
            img_coll = img_coll.add(ndvi_r.rename(['year','ndvi_res']))
        return ee.ImageCollection(img_coll)

    ndvi_1yr_o = preproc.modis_ndvi_annual_integral(year_start, year_end)

    # TODO: define clim_15d_o which is the merra-2 soil moisture data. For now, 
    # forcing use of Senegal data for testing.
    clim_15d_o = ee.Image('users/geflanddegradation/soil/sen_soilm_merra2_15d_1982_2015')

    # Apply function to compute climate annual integrals from 15d observed data
    clim_1yr_o = int_15d_1yr_clim(clim_15d_o.divide(10000))

    # Apply function to create image collection with stack of NDVI int, climate int and year
    coll_1yr_o = stack(year_start, year_end)

    # Reduce the collection with the linear fit reducer (independent var are followed by dependent var)
    lf_clim_ndvi = coll_1yr_o.select(['clim', 'ndvi']).reduce(ee.Reducer.linearFit())

    # Apply function to  predict NDVI based on climate
    ndvi_1yr_p = ee.ImageCollection(ee.List(coll_1yr_o.select('clim').iterate(ndvi_clim_p, first)))

    # Apply function to compute NDVI annual residuals
    ndvi_1yr_r  = ndvi_res(year_start, year_end)

    # Fit a linear regression to the NDVI residuals
    lf_prest = ndvi_1yr_r.select(['year', 'ndvi_res']).reduce(ee.Reducer.linearFit())

    # Compute Kendall statistics
    mk_prest  = stats.mann_kendall(ndvi_1yr_r.select('ndvi_res'))

    # Define Kendall parameter values for a significance of 0.05
    period = year_end - year_start + 1
    coefficients = ee.Array([4, 6, 9, 11, 14, 16, 19, 21, 24, 26, 31, 33, 36,
                             40, 43, 47, 50, 54, 59, 63, 66, 70, 75, 79, 84,
                             88, 93, 97, 102, 106, 111, 115, 120, 126, 131,
                             137, 142])
    kendall = coefficients.get([period - 4])

    # Create export function
    export = {'image': lf_prest.select('scale').where(mk_prest.abs().lte(kendall), -99999).where(lf_prest.select('scale').abs().lte(0.000001), -99999).unmask(-99999),
             'description': EXECUTION_ID,
             'fileNamePrefix': EXECUTION_ID,
             'bucket': BUCKET,
             'maxPixels': 10000000000,
             'scale': 250,
             'region': util.get_coords(geojson)}

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
    url = restrend_pointwise(year_start, year_end, geojson, resolution, dataset, 
            EXECUTION_ID, logger)

    logger.debug("Setting up results JSON.")
    results_url = CloudUrl(url, 'TODO_HASH_GOES_HERE') 
    cloud_dataset = CloudDataset('geotiff', 'integral_trends', results_url)
    gee_results = GEEResults('cloud_dataset', cloud_dataset)
    results_schema = GEEResultsSchema()
    json_result = results_schema.dump(gee_results)

    logger.debug("Setting up results JSON.")
    return json_result.data
