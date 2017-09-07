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

    def f_img_coll(ndvi_stack, year_start, year_end):
        img_coll = ee.List([])
        for k in range(year_start, year_end):
            ndvi_img = ndvi_stack.select('y{}'.format(k)).addBands(ee.Image(k).float()).rename(['ndvi', 'year'])
            img_coll = img_coll.add(ndvi_img)
        return ee.ImageCollection(img_coll)

    clip_geometry = ee.Geometry(geojson)

    # compute mean ndvi for the baseline period
    ndvi_1yr = f_img_coll(ndvi_1yr, year_start, year_end)
    avg_ndvi = ndvi_1yr.reduce(ee.Reducer.mean()).rename(['ndvi'])

    # land cover data from esa cci
    lc = ee.Image("users/geflanddegradation/toolbox_datasets/lcov_esacc_1992_2015")

    # global agroecological zones from IIASA
    gaez = ee.Image("users/geflanddegradation/toolbox_datasets/gaez_iiasa")

    lc_ipcc = lc.select('y{}'.format(year_start)) \
                    .remap([10, 11, 12, 20, 30, 40, 50, 60, 61, 62, 70, 71, 72, 80, 
                        81, 82, 90, 100, 160, 170, 110, 130, 180, 190, 120, 121, 
                        122, 140, 150, 151, 152, 153, 200, 201, 202, 210],
                        [ 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2,  2,  
                          2,  2,  3,  3,  4,  5,  6,  6,  6,  6,  6,  6,  6,  6,  
                          6,  6,  6,  6])

    # resample to modis projection (only changing pixel size)
    modis_proj =  ee.Image("users/geflanddegradation/toolbox_datasets/ndvi_modis_2001_2016").projection()

    landc_reducer = {'reducer': ee.Reducer.mode(),
                     'maxPixels': 2000}
    landc_reproject = {'crs': modis_proj.crs().getInfo(),
                       'scale': ee.Number(modis_proj.nominalScale()).getInfo()}
    landc_proj = lc_ipcc.reduceResolution(**landc_reducer)\
            .reproject(**landc_reproject)

    gaez_reducer = {'reducer': ee.Reducer.mode(),
                     'maxPixels': 2000}
    gaez_reproject = {'crs': modis_proj.crs().getInfo(),
                       'scale': ee.Number(modis_proj.nominalScale()).getInfo()}
    gaez_proj = gaez.reduceResolution(**gaez_reducer)\
            .reproject(**gaez_reproject)

    # biophysical units (intersect of land cover ipcc and gaez)
    units = gaez_proj.multiply(1000).add(landc_proj)

    units_filt_reducer = {'reducer': ee.Reducer.mode(),
                          'kernel': ee.Kernel.circle(10)}
    units_filt = units.reduceNeighborhood(**units_filt_reducer)

    ndvi_id = avg_ndvi.addBands(units_filt)

    # compute 90th percentile by unit
    perc90_group_reducer = ee.Reducer.percentile([90]).group(groupField=1, groupName='code')
    perc90_reducer = {'reducer': perc90_group_reducer,
                      'geometry': clip_geometry,
                      'scale': ee.Number(modis_proj.nominalScale()).getInfo(),
                      'maxPixels': 1e13}
    perc90 = ndvi_id.reduceRegion(**perc90_reducer)

    # Extract the cluster IDs and the 90th percentile
    groups = ee.List(perc90.get("groups"))
    def get_code(d):
        return ee.Dictionary(d).get('code')
    ids = groups.map(get_code)
    def get_p90(d):
        return ee.Dictionary(d).get('p90')
    perc = groups.map(get_p90)

    # remap the clustered baseline and target mean ndvi images to put the 
    # clusters in order
    raster_perc = units.remap(ids, perc)

    obs_ratio = avg_ndvi.divide(raster_perc)

    degradation = ee.Image(0).where(obs_ratio.gte(0.5), 0)\
            .where(obs_ratio.lte(0.5),-1)

    export = {'image': degradation.int16(),
              'description': EXECUTION_ID,
              'fileNamePrefix': EXECUTION_ID,
              'bucket': BUCKET,
              'maxPixels': 10000000000,
              'scale': ee.Number(modis_proj.nominalScale()).getInfo(),
              'region': util.get_coords(geojson)}

    logger.debug("Setting up GEE task.")
    task = util.gee_task(ee.batch.Export.image.toCloudStorage(**export), 
            'productivity_trajectory', logger)
    task.join()

    return "https://{}.storage.googleapis.com/{}.tif".format(BUCKET, EXECUTION_ID)

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
    json_results = productivity_performance(year_start, year_end,
	ndvi_gee_dataset, geojson, EXECUTION_ID, logger)

    logger.debug("Setting up results JSON.")
    results_url = CloudUrl(url)
    cloud_dataset = CloudDataset('geotiff', method, [results_url])
    gee_results = GEEResults('productivity_performance', [cloud_dataset])
    results_schema = GEEResultsSchema()
    json_result = results_schema.dump(gee_results)

    return json_result.data
