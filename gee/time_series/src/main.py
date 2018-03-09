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

from landdegradation.productivity import productivity_trajectory
from landdegradation.schemas.schemas import TimeSeries, TimeSeriesTable, TimeSeriesTableSchema


def zonal_stats(gee_dataset, geojsons, EXECUTION_ID, logger):
    logger.debug("Entering zonal_stats function.")

    region = ee.Geometry(geojsons)

    image = ee.Image(gee_dataset).clip(region)
    scale = ee.Number(image.projection().nominalScale()).getInfo()

    ## This produces an average of the region over the image by year
    ## Source: https://developers.google.com/earth-engine/reducers_reduce_region
    reducers = ee.Reducer.mean() \
        .combine(reducer2=ee.Reducer.min(), sharedInputs=True) \
        .combine(reducer2=ee.Reducer.max(), sharedInputs=True) \
        .combine(reducer2=ee.Reducer.mode(), sharedInputs=True) \
        .combine(reducer2=ee.Reducer.stdDev(), sharedInputs=True)
    statsDictionary = image.reduceRegion(reducer=reducers, geometry=region, scale=scale, maxPixels=1e13)

    logger.debug("Calculating zonal_stats.")
    res = statsDictionary.getInfo()

    logger.debug("Formatting results.")
    res_clean = {}
    for key, value in res.items():
        field = re.search('(?<=y[0-9]{4}_)\w*', key).group(0)
        year = re.search('(?<=y)[0-9]{4}', key).group(0)
        if field not in res_clean:
            res_clean[field] = {}
            res_clean[field]['value'] = []
            res_clean[field]['year'] = []
        res_clean[field]['value'].append(float(value))
        res_clean[field]['year'].append(int(year))

    logger.debug("Setting up results JSON.")
    timeseries = []
    for key in res_clean.keys():
        # Ensure the lists are in chronological order
        year, value = zip(*sorted(zip(res_clean[key]['year'], res_clean[key]['value'])))
        ts = TimeSeries(list(year), list(value), key)
        timeseries.append(ts)

    timeseries_table = TimeSeriesTable('timeseries', timeseries)
    timeseries_table_schema = TimeSeriesTableSchema()
    json_result = timeseries_table_schema.dump(timeseries_table)

    return json_result


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    year_start = params.get('year_start')
    year_end = params.get('year_end')
    geojsons = json.loads(params.get('geojsons'))
    crs = params.get('crs')
    method = params.get('method')
    ndvi_gee_dataset = params.get('ndvi_gee_dataset')
    climate_gee_dataset = params.get('climate_gee_dataset')

    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    logger.debug("Running main script.")
    # TODO: Right now timeseries will only work on the first geojson - this is 
    # somewhat ok since for the most part this uses points, but should fix in 
    # the future
    json_result = zonal_stats(ndvi_gee_dataset, geojsons[0], EXECUTION_ID, 
                              logger)

    return json_result.data
