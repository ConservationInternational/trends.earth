"""
Code for calculating annual integrated NDVI.
"""
# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import random
import json
from time import sleep

import ee

# Google cloud storage bucket for output
BUCKET = "ldmt"

def get_region(geom):
    """Return ee.Geometry from supplied GeoJSON object."""
    poly = get_coords(geom)
    ptype = get_type(geom)
    if ptype.lower() == 'multipolygon':
        region = ee.Geometry.MultiPolygon(poly)
    else:
        region = ee.Geometry.Polygon(poly)
    return region


def get_coords(geojson):
    """."""
    if geojson.get('features') is not None:
        return geojson.get('features')[0].get('geometry').get('coordinates')
    elif geojson.get('geometry') is not None:
        return geojson.get('geometry').get('coordinates')
    else:
        return geojson.get('coordinates')


def get_type(geojson):
    """."""
    if geojson.get('features') is not None:
        return geojson.get('features')[0].get('geometry').get('type')
    elif geojson.get('geometry') is not None:
        return geojson.get('geometry').get('type')
    else:
        return geojson.get('type')


def mann_kendall_stat(imageCollection):
    """Calculate Mann Kendall's S statistic.

    This function returns the Mann Kendall's S statistic, assuming that n is
    less than 40. The significance of a calculated S statistic is found in
    table A.30 of Nonparametric Statistical Methods, second edition by
    Hollander & Wolfe.

    Args:
        imageCollection: A Google Earth Engine image collection.

    Returns:
        A Google Earth Engine image collection with Mann Kendall statistic for
            each pixel.
    """
    TimeSeriesList = imageCollection.toList(50)
    NumberOfItems = TimeSeriesList.length().getInfo()
    ConcordantArray = []
    DiscordantArray = []
    for k in range(0, NumberOfItems-2):
        CurrentImage = ee.Image(TimeSeriesList.get(k))
        for l in range(k+1, NumberOfItems-1):
            nextImage = ee.Image(TimeSeriesList.get(l))
            Concordant = CurrentImage.lt(nextImage)
            ConcordantArray.append(Concordant)
            Discordant = CurrentImage.gt(nextImage)
            DiscordantArray.append(Discordant)
    ConcordantSum = ee.ImageCollection(ConcordantArray).sum()
    DiscordantSum = ee.ImageCollection(DiscordantArray).sum()
    MKSstat = ConcordantSum.subtract(DiscordantSum)
    return MKSstat

def ndvi_annual_integral(year_start, year_end, geojson, EXECUTION_ID, logger):
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

    Returns:
        Output of google earth engine task.
    """

    #EE_CREDENTIALS = ee.ServiceAccountCredentials(os.getenv('EE_SERVICE_ACCOUNT'), key_data=os.getenv('EE_PRIVATE_KEY'))
    #ee.Initialize(EE_CREDENTIALS, 'https://earthengine.googleapis.com')

    region = get_coords(geojson)

    # Load a MODIS NDVI collection 6 MODIS/MOD13Q1
    modis_16d_o = ee.ImageCollection('MODIS/006/MOD13Q1')

    # Function to mask pixels based on quality flags
    def qa_filter(img):
        mask = img.select('SummaryQA')
        mask = mask.where(img.select('SummaryQA').eq(-1), 0)
        mask = mask.where(img.select('SummaryQA').eq(0), 1)
        mask = mask.where(img.select('SummaryQA').eq(1), 1)
        mask = mask.where(img.select('SummaryQA').eq(2), 0)
        mask = mask.where(img.select('SummaryQA').eq(3), 0)
        masked = img.select('NDVI').updateMask(mask)
        return masked

    # Function to integrate observed NDVI datasets at the annual level
    def int_16d_1yr_o(ndvi_coll):
        img_coll = ee.List([])
        for k in range(year_start, year_end):
            ndvi_img = ndvi_coll.select('NDVI').filterDate('{}-01-01'.format(k), '{}-12-31'.format(k)).reduce(ee.Reducer.mean()).multiply(0.0001)
            img = ndvi_img.addBands(ee.Image(k).float()).rename(['ndvi','year']).set({'year': k})
            img_coll = img_coll.add(img)
        return ee.ImageCollection(img_coll)

    # Filter modis collection using the quality filter
    modis_16d_o = modis_16d_o.map(qa_filter)

    # Apply function to compute NDVI annual integrals from 15d observed NDVI data
    ndvi_1yr_o = int_16d_1yr_o(modis_16d_o)

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
    mk_trend = mann_kendall_stat(ndvi_1yr_o.select('ndvi'))

    export = {
        'image': lf_trend.select('scale').where(mk_trend.abs().lte(kendall), -99999).where(lf_trend.select('scale').abs().lte(0.000001), -99999).unmask(-99999),
        'description': EXECUTION_ID,
        'fileNamePrefix': EXECUTION_ID,
        'bucket': BUCKET,
        'maxPixels': 10000000000,
        'scale': 250,
        'region': region
    }

    # Export final mosaic to assets
    task = ee.batch.Export.image.toCloudStorage(**export)

    # Task -> READY
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

    return ndvi_annual_integral(year_start, year_end, geojson, EXECUTION_ID, logger)
