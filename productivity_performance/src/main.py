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

from . import __version__

from landdegradation import preproc
from landdegradation import stats
from landdegradation import util
from landdegradation import GEEIOError

from landdegradation.schemas import BandInfo, URLList, CloudResults, CloudResultsSchema


def productivity_performance(year_start, year_end, ndvi_gee_dataset, geojson,
                             EXECUTION_ID, logger):
    logger.debug("Entering productivity_performance function.")

    ndvi_1yr = ee.Image(ndvi_gee_dataset)

    # land cover data from esa cci
    lc = ee.Image("users/geflanddegradation/toolbox_datasets/lcov_esacc_1992_2015")

    # global agroecological zones from IIASA
    soil_tax_usda = ee.Image("users/geflanddegradation/toolbox_datasets/soil_tax_usda_sgrid")

    # compute mean ndvi for the period
    ndvi_avg = ndvi_1yr.select(ee.List(['y{}'.format(i) for i in range(year_start, year_end + 1)])) \
        .reduce(ee.Reducer.mean()).rename(['ndvi']).clip(geojson)

    # Handle case of year_start that isn't included in the CCI data
    if year_start > 2015:
        year_start = 2015
    elif year_start < 1992:
        year_start = 1992
    # reclassify lc to ipcc classes
    lc_start_year = lc.select('y{}'.format(year_start)) \
                      .remap([10, 11, 12, 20, 30, 40, 50, 60, 61, 62, 70, 71, 72, 80, 81, 82, 90, 100, 160, 170, 110, 130, 180, 190, 120, 121, 122, 140, 150, 151, 152, 153, 200, 201, 202, 210], 
                             [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36])

    # create a binary mask.
    mask = ndvi_avg.neq(0)

    # define modis projection attributes
    modis_proj = ee.Image("users/geflanddegradation/toolbox_datasets/ndvi_modis_2001_2016").projection()

    # reproject land cover, soil_tax_usda and avhrr to modis resolution
    lc_proj = lc_start_year.reproject(crs=modis_proj)
    soil_tax_usda_proj = soil_tax_usda.reproject(crs=modis_proj)
    ndvi_avg_proj = ndvi_avg.reproject(crs=modis_proj)

    # define unit of analysis as the intersect of soil_tax_usda and land cover
    units = soil_tax_usda_proj.multiply(100).add(lc_proj)

    # create a 2 band raster to compute 90th percentile per unit (analysis restricted by mask and study area)
    ndvi_id = ndvi_avg_proj.addBands(units).updateMask(mask)

    # compute 90th percentile by unit
    perc90 = ndvi_id.reduceRegion(reducer=ee.Reducer.percentile([90]).
                                  group(groupField=1, groupName='code'),
                                  geometry=ee.Geometry(geojson),
                                  scale=ee.Number(modis_proj.nominalScale()).getInfo(),
                                  maxPixels=1e15)

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

    # create final degradation output layer (9999 is background), 0 is not
    # degreaded, -1 is degraded
    lp_perf_deg = ee.Image(9999).where(obs_ratio_2.gte(0.5), 0) \
        .where(obs_ratio_2.lte(0.5), -1)

    lp_perf = lp_perf_deg.addBands(obs_ratio_2.multiply(10000)) \
        .addBands(raster_perc) \
        .addBands(units)

    task = util.export_to_cloudstorage(lp_perf.int16(),
                                       ndvi_1yr.projection(), geojson, 'prod_performance', logger,
                                       EXECUTION_ID)
    task.join()

    logger.debug("Setting up results JSON.")
    d = [BandInfo("Productivity performance (degradation)", 1, no_data_value=9999, add_to_map=True, title_strings=[year_start, year_end]),
         BandInfo("Productivity performance (ratio)", 2, no_data_value=9999, add_to_map=False, title_strings=[year_start, year_end]),
         BandInfo("Productivity performance (percentile)", 3, no_data_value=9999, add_to_map=False, title_strings=[year_start, year_end]),
         BandInfo("Productivity performance (units)", 4, no_data_value=9999, add_to_map=False, title_strings=[year_start])]
    u = URLList(task.get_URL_base(), task.get_files())
    gee_results = CloudResults('prod_performance', __version__, d, u)
    results_schema = CloudResultsSchema()
    json_results = results_schema.dump(gee_results)

    return json_results


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
    json_results = productivity_performance(year_start, year_end, ndvi_gee_dataset,
                                            geojson, EXECUTION_ID, logger)

    return json_results.data
