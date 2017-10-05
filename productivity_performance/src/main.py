"""
Code for calculating vegetation productivity performance.
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

def productivity_performance(year_start, year_end, ndvi_gee_dataset, geojson, 
        EXECUTION_ID, logger):
    logger.debug("Entering productivity_performance function.")

    ndvi_1yr = ee.Image(ndvi_gee_dataset)

    # land cover data from esa cci
    lc = ee.Image("users/geflanddegradation/toolbox_datasets/lcov_esacc_1992_2015")

    # global agroecological zones from IIASA
    gaez = ee.Image("users/geflanddegradation/toolbox_datasets/gaez_iiasa")

    # compute mean ndvi for the period
    ndvi_avg = ndvi_1yr.select(ee.List(['y{}'.format(i) for i in range(year_start, year_end + 1)])) \
            .reduce(ee.Reducer.mean()).rename(['ndvi']).clip(geojson)

    # reclassify lc to ipcc classes
    lc_ipcc = lc.select('y{}'.format(year_start)) \
		    .remap([10,11,12,20,30,40,50,60,61,62,70,71,72,80,81,82,90,100,160,170,110,130,180,190,120,121,122,140,150,151,152,153,200,201,202,210],
			   [ 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2,  2,  2,  2,  3,  3,  4,  5,  6,  6,  6,  6,  6,  6,  6,  6,  6,  6,  6,  6])

    # create a binary mask.
    mask = ndvi_avg.neq(0)

    # define modis projection attributes
    modis_proj =  ee.Image("users/geflanddegradation/toolbox_datasets/ndvi_modis_2001_2016").projection()

    # reproject land cover, gaez and avhrr to modis resolution
    lc_proj = lc_ipcc.reproject(crs=modis_proj)
    gaez_proj = gaez.reproject(crs=modis_proj)
    ndvi_avg_proj = ndvi_avg.reproject(crs=modis_proj)

    # define unit of analysis as the intersect of gaez and land cover 
    units = gaez_proj.multiply(1000).add(lc_proj)

    # create a 2 band raster to compute 90th percentile per unit (analysis restricted by mask and study area)
    ndvi_id = ndvi_avg_proj.addBands(units).updateMask(mask)

    # compute 90th percentile by unit
    perc90 = ndvi_id.reduceRegion(reducer=ee.Reducer.percentile([90]). \
            group(groupField=1, groupName='code'),
            geometry=ee.Geometry(geojson),
            scale=ee.Number(modis_proj.nominalScale()).getInfo(),
            maxPixels=1e13)

    # Extract the cluster IDs and the 90th percentile
    groups = ee.List(perc90.get("groups"))
    ids = groups.map(lambda d: ee.Dictionary(d).get('code'))
    perc = groups.map(lambda d: ee.Dictionary(d).get('p90'))

    # remap the units raster using their 90th percentile value
    raster_perc = units.remap(ids, perc)

    # compute the ration of observed ndvi to 90th for that class
    obs_ratio = ndvi_avg_proj.divide(raster_perc)

    # aggregate obs_ratio to original NDVI data resolution (for modis this step does not change anything)
    obs_ratio_2 = obs_ratio.reduceResolution(reducer=ee.Reducer.mean(), maxPixels=2000) \
            .reproject(crs=ndvi_1yr.projection())

    # select lc for final map and resample to ndvi data resolution (using original esa cci classes, not ipcc)
    lc_proj_esa = lc.select('y{}'.format(year_start)) \
            .reduceResolution(reducer=ee.Reducer.mode(), maxPixels=2000) \
            .reproject(crs=ndvi_1yr.projection())

    # create final degradation output layer (9997 is background), 0 is not 
    # degreaded, -1 is degraded, 9998 is water, and 9999 is urban
    lp_perf_deg = ee.Image(9997).where(obs_ratio_2.gte(0.5), 0) \
            .where(obs_ratio_2.lte(0.5), -1) \
            .where(lc_proj_esa.eq(210), 9998) \
            .where(lc_proj_esa.eq(190), 9999)

    export = {'image': lp_perf_deg.int16(),
              'description': EXECUTION_ID,
              'fileNamePrefix': EXECUTION_ID,
              'bucket': BUCKET,
              'maxPixels': 10000000000,
              'scale': ee.Number(ndvi_1yr.projection().nominalScale()).getInfo(),
              'region': util.get_coords(geojson)}

    logger.debug("Setting up GEE task.")
    task = util.gee_task(ee.batch.Export.image.toCloudStorage(**export), 
            'productivity_performance', logger)
    task.join()

    return "http://{}.storage.googleapis.com/{}.tif".format(BUCKET, EXECUTION_ID)

def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    year_start = params.get('year_start', 2001)
    year_end = params.get('year_end', 2010)
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
    url = productivity_performance(year_start, year_end, ndvi_gee_dataset, 
            geojson, EXECUTION_ID, logger)

    logger.debug("Setting up results JSON.")
    results_url = CloudUrl(url)
    cloud_dataset = CloudDataset('geotiff', 'productivity_performance', [results_url])
    gee_results = GEEResults('productivity_performance', [cloud_dataset])
    results_schema = GEEResultsSchema()
    json_result = results_schema.dump(gee_results)

    return json_result.data
