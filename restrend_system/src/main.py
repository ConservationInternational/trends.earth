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

# Google cloud storage bucket for output
BUCKET = "ldmt"

def restrend_system(year_start, year_end, geojson, EXECUTION_ID, logger):
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

    # Function to integrate NDVI dataset from 15d to 1yr
    def int_15d_1yr_p(img_stack):
        img_coll = ee.List([])
        for k in range(1, 34):
            ndvi_lyr = img_stack.select(ee.List.sequence((k-1)*24,(k*24)-1)).reduce(ee.Reducer.mean()).rename(['ndvi']).set({'year': 1981+k})
            img_coll = img_coll.add(ndvi_lyr)
        return ee.ImageCollection(img_coll)
    
    # Create image collection of residuals
    def ndvi_res(year_start, year_end): 
        img_coll = ee.List([])
        for k in range(year_start, year_end):
            ndvi_o = coll_1yr_o.filter(ee.Filter.eq('year', k)).select('ndvi').median()
            ndvi_p = ndvi_1yr_p.filter(ee.Filter.eq('year', k)).median()
            ndvi_r = ee.Image(k).float().addBands(ndvi_o.subtract(ndvi_p))
            img_coll = img_coll.add(ndvi_r.rename(['year','ndvi_res']))
        return ee.ImageCollection(img_coll)
   
    # Conversion of soil moisture to NDVI using equations developed by NASA presented in the report 1
    # TODO: define clim_15d_o which is the merra-2 soil moisture data. For now, 
    # forcing use of Senegal data for testing.
    clim_15d_o = ee.Image('users/geflanddegradation/soil/sen_soilm_merra2_15d_1982_2015')
    
    ndvi_p1 = clim_15d_o.divide(10000).multiply(0.11).add(0.19)
    ndvi_p2 = clim_15d_o.divide(10000).multiply(6.63).add(-2.22)
    ndvi_p3 = clim_15d_o.divide(10000).pow(3).multiply(1.38).add(clim_15d_o.divide(10000).pow(2).multiply(-3.83)).add(clim_15d_o.divide(10000).multiply(3.83)).add(-0.63)

    # Conditional statement to combine the 3 NDVI estimates into one image
    ndvi_15d_p = ndvi_p2.where(clim_15d_o.lte(0.37*10000), ndvi_p1).where(clim_15d_o.gte(0.39*10000), ndvi_p3)

    # Apply function to compute predicted NDVI annual integrals from 15d predicted NDVI data
    ndvi_1yr_p = int_15d_1yr_p(ndvi_15d_p)

    ndvi_1yr_o = preproc.modis_ndvi_annual_integral(year_start, year_end)

    # Compute differences between observed and predicted NDVI annual integrals
    ndvi_1yr_r = ndvi_res(year_start, year_end)

    # Fit a linear regression to the NDVI differences
    lf_srest = ndvi_1yr_r.select(['year', 'ndvi_res']).reduce(ee.Reducer.linearFit())

    # Compute Kendall statistics
    mk_srest  = stats.mann_kendall(ndvi_1yr_r.select('ndvi_res'))
    
    # Define Kendall parameter values for a significance of 0.05
    period = year_end - year_start + 1
    coefficients = ee.Array([4, 6, 9, 11, 14, 16, 19, 21, 24, 26, 31, 33, 36,
                             40, 43, 47, 50, 54, 59, 63, 66, 70, 75, 79, 84,
                             88, 93, 97, 102, 106, 111, 115, 120, 126, 131,
                             137, 142])
    kendall = coefficients.get([period - 4])

    # Create export function
    export = {'image': lf_srest.select('scale').where(mk_srest.abs().lte(kendall), -99999).where(lf_srest.select('scale').abs().lte(0.000001), -99999).unmask(-99999),
             'description': EXECUTION_ID,
             'fileNamePrefix': EXECUTION_ID,
             'bucket': BUCKET,
             'maxPixels': 10000000000,
             'scale': 250,
             'region': util.get_coords(geojson)}

    # Export final mosaic to assets
    task = ee.batch.Export.image.toCloudStorage(**export)

    task.start()
    task_state = task.status().get('state')
    while task_state == 'READY' or task_state == 'RUNNING':
        task_progress = task.status().get('progress', 0.0)
        # update GEF-EXECUTION progress
        logger.send_progress(task_progress)
        # update variable to check the condition
        task_state = task.status().get('state')
        sleep(5)

    return "https://{}.storage.googleapis.com/{}.tif".format(BUCKET, EXECUTION_ID)

def run(params, logger):
    """."""
    year_start = params.get('year_start', 2003)
    year_end = params.get('year_end', 2015)
    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1, 1000000))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)
    default_poly = json.loads('{"type":"FeatureCollection","features":[{"type":"Feature","id":"SEN","properties":{"name":"Senegal"},"geometry":{"type":"Polygon","coordinates":[[[-16.713729,13.594959],[-17.126107,14.373516],[-17.625043,14.729541],[-17.185173,14.919477],[-16.700706,15.621527],[-16.463098,16.135036],[-16.12069,16.455663],[-15.623666,16.369337],[-15.135737,16.587282],[-14.577348,16.598264],[-14.099521,16.304302],[-13.435738,16.039383],[-12.830658,15.303692],[-12.17075,14.616834],[-12.124887,13.994727],[-11.927716,13.422075],[-11.553398,13.141214],[-11.467899,12.754519],[-11.513943,12.442988],[-11.658301,12.386583],[-12.203565,12.465648],[-12.278599,12.35444],[-12.499051,12.33209],[-13.217818,12.575874],[-13.700476,12.586183],[-15.548477,12.62817],[-15.816574,12.515567],[-16.147717,12.547762],[-16.677452,12.384852],[-16.841525,13.151394],[-15.931296,13.130284],[-15.691001,13.270353],[-15.511813,13.27857],[-15.141163,13.509512],[-14.712197,13.298207],[-14.277702,13.280585],[-13.844963,13.505042],[-14.046992,13.794068],[-14.376714,13.62568],[-14.687031,13.630357],[-15.081735,13.876492],[-15.39877,13.860369],[-15.624596,13.623587],[-16.713729,13.594959]]]}}]}')
    geojson = params.get('geojson', default_poly)

    return restrend_system(year_start, year_end, geojson, EXECUTION_ID, logger)
