"""
Code for calculating vegetation productivity trajectory.
"""
# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import random
import re
import json

import ee
import pandas as pd

from landdegradation import preproc
from landdegradation import stats
from landdegradation import util
from landdegradation import GEEIOError

from landdegradation.schemas import GEEResults, CloudDataset, CloudUrl, GEEResultsSchema

# Google cloud storage bucket for output
BUCKET = "ldmt"


def zonal_stats(year_start, year_end, method, gee_dataset, geojson, 
        EXECUTION_ID, logger):
    logger.debug("Entering zonal_stats function.")

    region = ee.Geometry(geojson)
    
    image = ee.Image(gee_dataset).clip(region)
    scale = ee.Number(image.projection().nominalScale()).getInfo()
    
    ## This produces an average of the region over the image by year
    ## Source: https://developers.google.com/earth-engine/reducers_reduce_region
    reducers = ee.Reducer.mean() \
        .combine(reducer2=ee.Reducer.min(), sharedInputs=True) \
        .combine(reducer2=ee.Reducer.max(), sharedInputs=True) \
        .combine(reducer2=ee.Reducer.stdDev(), sharedInputs=True)
    statsDictionary = image.reduceRegion(reducer=reducers, geometry=region, scale=scale, maxPixels=1e13)
    
    binaryImage = image.gt(0)
    reducers = ee.Reducer.sum() \
        .combine(reducer2=ee.Reducer.count(), sharedInputs=True)
    countDictionary = binaryImage.reduceRegion(reducer=reducers, geometry=region, scale=scale,  maxPixels=1e13)
    
    ## Creates a combined reducer for both count and sum 
    ## NOTE: sum is the number of pixels greater than 0, (count-sum) is the number of pixels less than or equal to 0.  
    ## Calculate counts of GT 0 and LE 0
    bandNames = image.bandNames()
    keys = ee.List(['{}_count_1'.format(bn) for bn in bandNames.getInfo()])
    values = bandNames.map(lambda bn: ee.Number(countDictionary.get(ee.String(bn).cat('_sum'))))
    count1Dictionary = ee.Dictionary.fromLists(keys, values);
    
    ## Combine the dictionaries at which point you'll have 96 different keys (16 years x 6 statistics).  
    keys = ee.List(['{}_count_0'.format(bn) for bn in bandNames.getInfo()])
    values = bandNames.map(lambda bn: ee.Number(countDictionary.get(ee.String(bn).cat('_count'))). \
                           subtract(ee.Number(countDictionary.get(ee.String(bn).cat('_sum')))))
    count0Dictionary = ee.Dictionary.fromLists(keys, values)
    ## Combine all dictionaries
    combineDictionary = statsDictionary \
        .combine(count1Dictionary) \
        .combine(count0Dictionary)
    
    logger.debug("Calculating zonal_stats.")
    res = combineDictionary.getInfo()
    
    logger.debug("Formatting results.")
    res_clean = {}
    for key, value in res.items():
        field = re.search('(?<=y[0-9]{4}_)\w*', key).group(0)
        year = re.search('(?<=y)[0-9]{4}', key).group(0)
        if field not in res_clean:
            res_clean[field] = {}
        res_clean[field][year] = value

    return pd.DataFrame.from_dict(res_clean).to_json()

def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    year_start = params.get('year_start', 2001)
    year_end = params.get('year_end', 2015)
    geojson = params.get('geojson', None)
    method = params.get('method', 'ndvi_trend')
    ndvi_gee_dataset = params.get('ndvi_gee_dataset', None)
    climate_gee_dataset = params.get('climate_gee_dataset', None)

    logger.debug("Loading geojson.")
    if geojson is None:
        raise GEEIOError("Must specify an input area")
    else:
        geojson = json.loads(geojson)

    if ndvi_gee_dataset is None:
        raise GEEIOError("Must specify an NDVI dataset")

    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    logger.debug("Running main script.")
    stats = zonal_stats(year_start, year_end, method, ndvi_gee_dataset, 
            geojson, EXECUTION_ID, logger)

    logger.debug("Setting up results JSON.")

    return json.dumps(stats)
