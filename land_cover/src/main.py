"""
Code for calculating land cover change indicator.
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

def land_cover(year_bl_start, year_bl_end, year_target, geojson, EXECUTION_ID, 
        logger):
    """
    Calculate land cover indicator.
    """
    logger.debug("Entering land_cover function.")

    ## land cover
    lc = ee.Image("users/geflanddegradation/toolbox_datasets/lcov_esacc_1992_2015")

    ## target land cover map reclassified to IPCC 6 classes
    lc_tg = lc.select('y{}'\
            .format(year_target))\
            .remap([10, 11, 12, 20, 30, 40,50, 60, 61, 62, 70, 71, 72, 80, 81, 
                82, 90, 100, 160, 170, 110, 130, 180, 190, 120, 121, 122, 140, 
                150, 151, 152, 153, 200, 201, 202, 210],
                [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 
                 3, 4, 5, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6])

    ## baseline land cover map reclassified to IPCC 6 classes
    lc_bl = lc.select(ee.List\
            .sequence(year_bl_start - 1992, year_bl_end - 1992, 1)) \
            .reduce(ee.Reducer.mode())\
            .remap([10, 11, 12, 20, 30, 40, 50, 60, 61, 62, 70, 71, 72, 80, 81, 
                    82, 90, 100, 160, 170, 110, 130, 180, 190, 120, 121, 122, 
                    140, 150, 151, 152, 153, 200, 201, 202, 210],
                   [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 
                    3, 3, 4, 5, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6])

    ## compute transition map (first digit for baseline land cover, and second digit for target year land cover)
    lc_tr = lc_bl.multiply(10).add(lc_tg)

    ## definition of land cover transitions as degradation (-1), improvement (1), or no relevant change (0)
    lc_dg = lc_tr\
            .remap([11, 12, 13, 14, 15, 16, 21, 22, 23, 24, 25, 26, 31, 32, 33, 
                    34, 35, 36, 41, 42, 43, 44, 45, 46, 51, 52, 53, 54, 55, 56, 
                    61, 62, 63, 64, 65, 66],
                   [0, 1, 1, 1, -1, 0, -1, 0, -1, -1, -1, -1, -1, 1, 0, 0, -1, 
                    -1, -1, -1, -1, 0, -1, -1, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1,
                    -1, 0])

    clip_geometry = ee.Geometry(geojson)

    tasks = []
    # Create export function to export baseline land cover
    export_lc_baseline = {'image': lc_bl.clip(clip_geometry).int16(),
                          'description': '{}_lc_baseline'.format(EXECUTION_ID),
                          'fileNamePrefix': '{}_lc_baseline'.format(EXECUTION_ID),
                          'bucket': BUCKET,
                          'maxPixels': 10000000000,
                          'scale': ee.Number(lc.projection().nominalScale()).getInfo(),
                          'region': util.get_coords(geojson)}
    tasks.append(util.gee_task(ee.batch.Export.image.toCloudStorage(**export_lc_baseline),
                              'lc_baseline', logger))

    # Create export function to export target year land cover
    export_lc_target = {'image': lc_tg.clip(clip_geometry).int16(),
                        'description': '{}_lc_target'.format(EXECUTION_ID),
                        'fileNamePrefix': '{}_lc_target'.format(EXECUTION_ID),
                        'bucket': BUCKET,
                        'maxPixels': 10000000000,
                        'scale': ee.Number(lc.projection().nominalScale()).getInfo(),
                        'region': util.get_coords(geojson)}
    tasks.append(util.gee_task(ee.batch.Export.image.toCloudStorage(**export_lc_target),
                              'lc_target', logger))

    # Create export function to export land cover transition
    export_lc_change = {'image': lc_tr.clip(clip_geometry).int16(),
                        'description': '{}_lc_change'.format(EXECUTION_ID),
                        'fileNamePrefix': '{}_lc_change'.format(EXECUTION_ID),
                        'bucket': BUCKET,
                        'maxPixels': 10000000000,
                        'scale': ee.Number(lc.projection().nominalScale()).getInfo(),
                        'region': util.get_coords(geojson)}
    tasks.append(util.gee_task(ee.batch.Export.image.toCloudStorage(**export_lc_change),
                              'lc_change', logger))

    # Create export function to export land deg image
    export_land_deg = {'image': lc_dg.clip(clip_geometry).int16(),
                       'description': '{}_land_deg'.format(EXECUTION_ID),
                       'fileNamePrefix': '{}_land_deg'.format(EXECUTION_ID),
                       'bucket': BUCKET,
                       'maxPixels': 10000000000,
                       'scale': ee.Number(lc.projection().nominalScale()).getInfo(),
                       'region': util.get_coords(geojson)}
    tasks.append(util.gee_task(ee.batch.Export.image.toCloudStorage(**export_land_deg),
                              'land_deg', logger))

    logger.debug("Waiting for GEE tasks to complete.")
    cloud_datasets = []
    for task in tasks:
        task.join()
        cloud_datasets.append(CloudDataset('geotiff', task.name, ['{}_{}'.format(EXECUTION_ID, task.name)]))

    logger.debug("Setting up results JSON.")
    gee_results = GEEResults('cloud_dataset', cloud_datasets)
    results_schema = GEEResultsSchema()
    json_results = results_schema.dump(gee_results)

    return json_results

def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    year_bl_start = params.get('year_bl_start', 2002)
    year_bl_end = params.get('year_bl_end', 2015)
    year_target = params.get('year_target', 2015)
    geojson = params.get('geojson', util.tza_geojson)

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
    json_results = land_cover(year_bl_start, year_bl_end, year_target, geojson, 
                              EXECUTION_ID, logger)

    return json_results.data
