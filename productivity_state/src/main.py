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

def productivity_state(year_bl_start, year_bl_end, year_tg_start, year_tg_end,
	ndvi_gee_dataset, geojson, EXECUTION_ID, logger):
    logger.debug("Entering productivity_state function.")

    ndvi_1yr = ee.Image(ndvi_gee_dataset)

    def f_img_coll(ndvi_stack, year_start, year_end):
        img_coll = ee.List([])
        for k in range(year_start, year_end):
            ndvi_img = ndvi_stack.select('y' + str(k)).addBands(ee.Image(k).float()).rename(['ndvi', 'year'])
            img_coll = img_coll.add(ndvi_img)
        return ee.ImageCollection(img_coll)

    clip_geometry = ee.Geometry(geojson)

    # compute mean ndvi for the baseline period
    ndvi_bl_coll = f_img_coll(ndvi_1yr, year_bl_start, year_bl_end)
    ndvi_bl = ndvi_bl_coll.reduce(ee.Reducer.mean()).clip(clip_geometry)

    # compute mean ndvi for the target period
    ndvi_tg_coll = f_img_coll(ndvi_1yr, year_tg_start, year_tg_end)
    ndvi_tg = ndvi_tg_coll.reduce(ee.Reducer.mean()).clip(clip_geometry)

    perc_bl = ndvi_bl.reduce(ee.Reducer.percentile([10, 20, 30, 40, 50, 60, 70, 80, 90, 100]))
    perc_tg = ndvi_tg.reduce(ee.Reducer.percentile([10, 20, 30, 40, 50, 60, 70, 80, 90, 100]))
                           
    tasks = []
    export_ndvi_bl  = {'image': ndvi_bl.int16(),
                       'description': '{}_ndvi_bl'.format(EXECUTION_ID),
                       'fileNamePrefix': '{}_ndvi_bl'.format(EXECUTION_ID),
                       'bucket': BUCKET,
                       'maxPixels': 10000000000,
                       'scale': ee.Number(ndvi_bl.projection().nominalScale()).getInfo(),
                       'region': util.get_coords(geojson)}
    tasks.append(util.gee_task(ee.batch.Export.image.toCloudStorage(**export_ndvi_bl), 'ndvi_bl', logger))

    export_ndvi_tg  = {'image': ndvi_tg.int16(),
                       'description': '{}_ndvi_tg'.format(EXECUTION_ID),
                       'fileNamePrefix': '{}_ndvi_tg'.format(EXECUTION_ID),
                       'bucket': BUCKET,
                       'maxPixels': 10000000000,
                       'scale': ee.Number(ndvi_tg.projection().nominalScale()).getInfo(),
                       'region': util.get_coords(geojson)}
    tasks.append(util.gee_task(ee.batch.Export.image.toCloudStorage(**export_ndvi_tg), 'ndvi_tg', logger))

    export_perc_bl  = {'image': perc_bl.int16(),
                       'description': '{}_perc_bl'.format(EXECUTION_ID),
                       'fileNamePrefix': '{}_perc_bl'.format(EXECUTION_ID),
                       'bucket': BUCKET,
                       'maxPixels': 10000000000,
                       'scale': ee.Number(perc_bl.projection().nominalScale()).getInfo(),
                       'region': util.get_coords(geojson)}
    tasks.append(util.gee_task(ee.batch.Export.image.toCloudStorage(**export_perc_bl), 'perc_bl', logger))

    export_perc_tg  = {'image': perc_tg.int16(),
                       'description': '{}_perc_tg'.format(EXECUTION_ID),
                       'fileNamePrefix': '{}_perc_tg'.format(EXECUTION_ID),
                       'bucket': BUCKET,
                       'maxPixels': 10000000000,
                       'scale': ee.Number(perc_tg.projection().nominalScale()).getInfo(),
                       'region': util.get_coords(geojson)}
    tasks.append(util.gee_task(ee.batch.Export.image.toCloudStorage(**export_perc_tg), 'perc_tg', logger))

    logger.debug("Waiting for GEE tasks to complete.")
    cloud_datasets = []
    for task in tasks:
        task.join()
        results_url = CloudUrl("https://{}.storage.googleapis.com/{}_{}.tif".format(BUCKET, EXECUTION_ID, task.name))
        cloud_datasets.append(CloudDataset('geotiff', task.name, [results_url]))

    logger.debug("Setting up results JSON.")
    gee_results = GEEResults('land_cover', cloud_datasets)
    results_schema = GEEResultsSchema()
    json_results = results_schema.dump(gee_results)

    return json_results

def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    year_bl_start = params.get('year_bl_start', 2001)
    year_bl_end = params.get('year_bl_end', 2010)
    year_tg_start = params.get('year_tg_start', 2013)
    year_tg_end = params.get('year_tg_end', 2015)
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
    json_results = productivity_state(year_bl_start, year_bl_end,
	year_tg_start, year_tg_end, ndvi_gee_dataset, geojson, EXECUTION_ID,
        logger)

    return json_results.data
