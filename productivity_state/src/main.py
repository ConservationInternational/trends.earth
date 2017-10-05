"""
Code for calculating vegetation productivity state.
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

# Google cloud storage bucket for output
BUCKET = "ldmt"

def productivity_state(year_init_bl_start, year_init_bl_end, 
        year_init_tg_start, year_init_tg_end,
        ndvi_gee_dataset, geojson, EXECUTION_ID, logger):

    logger.debug("Entering productivity_state function.")

    ndvi_1yr = ee.Image(ndvi_gee_dataset)

    # land cover data from esa cci
    lc = ee.Image("users/geflanddegradation/toolbox_datasets/lcov_esacc_1992_2015")
    # Handle case of end year that isn't included in the CCI data
    year_end_esa_cci = year_init_tg_end
    if year_init_tg_end > 2015:
        year_end_esa_cci = 2015
    elif year_init_tg_end < 1992:
        year_end_esa_cci = 1992
    # select lc for final map and resample to ndvi data resolution
    lc_proj_esa = lc.select('y{}'.format(year_end_esa_cci)). \
            reduceResolution(reducer=ee.Reducer.mode(), maxPixels=2000). \
            reproject(crs=ndvi_1yr.projection())

    # compute percentiles of annual ndvi for the baseline period
    bl_ndvi_perc = ndvi_1yr.select(ee.List(['y{}'.format(i) for i in range(year_init_bl_start, year_init_bl_end + 1)])) \
            .reduce(ee.Reducer.percentile([10,20,30,40,50,60,70,80,90,100]))

    # compute mean ndvi for the baseline and target period period
    bl_ndvi_mean = ndvi_1yr.select(ee.List(['y{}'.format(i) for i in range(year_init_bl_start, year_init_bl_end + 1)])) \
            .reduce(ee.Reducer.mean()).rename(['ndvi'])
    tg_ndvi_mean = ndvi_1yr.select(ee.List(['y{}'.format(i) for i in range(year_init_tg_start, year_init_tg_end + 1)])) \
            .reduce(ee.Reducer.mean()).rename(['ndvi'])

    # initial degradation
    # reclassify mean ndvi for baseline period based on 50th percentile. -1 is 
    # degreaded, 0 is not degreade, 2 is water ,and 3 is urban
    ini_deg = ee.Image(-2).where(bl_ndvi_mean.lt(bl_ndvi_perc.select('p50')), -1) \
            .where(bl_ndvi_mean.gte(bl_ndvi_perc.select('p50')), 0) \
            .where(lc_proj_esa.eq(210),2) \
            .where(lc_proj_esa.eq(190),3)

    # emerging degradation
    # reclassify mean ndvi for baseline period based on the percentiles
    bl_classes = ee.Image(1).where(bl_ndvi_mean.gt(bl_ndvi_perc.select('p10')), 2) \
        .where(bl_ndvi_mean.gt(bl_ndvi_perc.select('p20')), 3) \
        .where(bl_ndvi_mean.gt(bl_ndvi_perc.select('p30')), 4) \
        .where(bl_ndvi_mean.gt(bl_ndvi_perc.select('p40')), 5) \
        .where(bl_ndvi_mean.gt(bl_ndvi_perc.select('p50')), 6) \
        .where(bl_ndvi_mean.gt(bl_ndvi_perc.select('p60')), 7) \
        .where(bl_ndvi_mean.gt(bl_ndvi_perc.select('p70')), 8) \
        .where(bl_ndvi_mean.gt(bl_ndvi_perc.select('p80')), 9) \
        .where(bl_ndvi_mean.gt(bl_ndvi_perc.select('p90')),10)

    # reclassify mean ndvi for target period based on the percentiles
    tg_classes = ee.Image(1).where(tg_ndvi_mean.gt(bl_ndvi_perc.select('p10')), 2) \
        .where(tg_ndvi_mean.gt(bl_ndvi_perc.select('p20')), 3) \
        .where(tg_ndvi_mean.gt(bl_ndvi_perc.select('p30')), 4) \
        .where(tg_ndvi_mean.gt(bl_ndvi_perc.select('p40')), 5) \
        .where(tg_ndvi_mean.gt(bl_ndvi_perc.select('p50')), 6) \
        .where(tg_ndvi_mean.gt(bl_ndvi_perc.select('p60')), 7) \
        .where(tg_ndvi_mean.gt(bl_ndvi_perc.select('p70')), 8) \
        .where(tg_ndvi_mean.gt(bl_ndvi_perc.select('p80')), 9) \
        .where(tg_ndvi_mean.gt(bl_ndvi_perc.select('p90')),10) 

    # emerging degradation: difference between start and end clusters >= 2
    classes_chg = tg_classes.subtract(bl_classes)
    # create final degradation output layer (9997 is background), 0 is not 
    # degreaded, -1 is degraded, 1 is degraded, 9998 is water, and 9999 is urban
    eme_deg = ee.Image(9997).where(classes_chg.lte(-2),-1) \
          .where(classes_chg.gte(-1).And(classes_chg.lte( 1)), 0) \
          .where(classes_chg.gte( 2), 1) \
          .where(lc_proj_esa.eq(210),9998) \
          .where(lc_proj_esa.eq(190),9999)

    tasks = []
    export_ini_degr = {'image': ini_deg.int16(),
                       'description': '{}_ini_degr'.format(EXECUTION_ID),
                       'fileNamePrefix': '{}_ini_degr'.format(EXECUTION_ID),
                       'bucket': BUCKET,
                       'maxPixels': 10000000000,
                       'scale': ee.Number(ndvi_1yr.projection().nominalScale()).getInfo(),
                       'region': util.get_coords(geojson)}
    tasks.append(util.gee_task(ee.batch.Export.image.toCloudStorage(**export_ini_degr), 'ini_degr', logger))

    export_eme_degr = {'image': eme_deg.int16(),
                       'description': '{}_eme_degr'.format(EXECUTION_ID),
                       'fileNamePrefix': '{}_eme_degr'.format(EXECUTION_ID),
                       'bucket': BUCKET,
                       'maxPixels': 10000000000,
                       'scale': ee.Number(ndvi_1yr.projection().nominalScale()).getInfo(),
                       'region': util.get_coords(geojson)}
    tasks.append(util.gee_task(ee.batch.Export.image.toCloudStorage(**export_eme_degr), 'eme_degr', logger))

    logger.debug("Waiting for GEE tasks to complete.")
    cloud_datasets = []
    for task in tasks:
        task.join()
        results_url = CloudUrl("http://{}.storage.googleapis.com/{}_{}.tif".format(BUCKET, EXECUTION_ID, task.name))
        cloud_datasets.append(CloudDataset('geotiff', task.name, [results_url]))

    logger.debug("Setting up results JSON.")
    gee_results = GEEResults('productivity_state', cloud_datasets)
    results_schema = GEEResultsSchema()
    json_results = results_schema.dump(gee_results)

    return json_results

def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    year_init_bl_start = params.get('year_init_bl_start', 2001)
    year_init_bl_end = params.get('year_init_bl_end', 2012)
    year_init_tg_start = params.get('year_init_tg_start', 2013)
    year_init_tg_end = params.get('year_init_tg_end', 2015)
    geojson = params.get('geojson', None)
    ndvi_gee_dataset = params.get('ndvi_gee_dataset', None)

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
    json_results = productivity_state(year_init_bl_start, year_init_bl_end, 
            year_init_tg_start, year_init_tg_end,
            ndvi_gee_dataset, geojson, EXECUTION_ID, logger)

    return json_results.data
