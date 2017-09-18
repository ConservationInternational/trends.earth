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
        year_emerg_bl_start, year_emerg_bl_end, 
        year_emerg_tg_start, year_emerg_tg_end,
        ndvi_gee_dataset, geojson, EXECUTION_ID, logger):

    logger.debug("Entering productivity_state function.")

    ndvi_1yr = ee.Image(ndvi_gee_dataset)

    geojson_geometry = ee.Geometry(geojson)

    sample_size = geojson_geometry.area().divide(1000000).divide(100).toLong() # 1 point every 100km2

    # land cover
    landc = ee.Image("users/geflanddegradation/toolbox_datasets/lcov_esacc_1992_2015").select('y{}'.format(year_emerg_tg_end))

    # define pixel output size based on ndvi product used
    pixel =  ee.Number(ndvi_1yr.projection().nominalScale()).getInfo()

    # define function to cluster ndvi data into 10 bins (using k-means)
    def f_cluster_ndvi(bl_start,bl_end,tg_start,tg_end):
        # compute mean ndvi for the baseline period
        bl_ndvi = ndvi_1yr.select(ee.List(['y{}'.format(i) for i in range(bl_start, bl_end + 1)])) \
                          .reduce(ee.Reducer.mean()).clip(geojson_geometry).rename(['ndvi'])
        # compute mean ndvi for the target period
        tg_ndvi = ndvi_1yr.select(ee.List(['y{}'.format(i) for i in range(tg_start, tg_end + 1)])) \
                          .reduce(ee.Reducer.mean()).clip(geojson_geometry).rename(['ndvi'])
        # make the training dataset for clustering using baseline ndvi
        training = bl_ndvi.sample(region=geojson_geometry, scale=pixel, numPixels=sample_size)
        # instantiate the clusterer and train it
        clusterer = ee.Clusterer.wekaKMeans(10).train(training)
        # cluster the baseline and target mean ndvi using the trained clusterer
        bl_clusters = bl_ndvi.cluster(clusterer)
        tg_clusters = tg_ndvi.cluster(clusterer)
        # recluster the training data and compute the mean for each cluster
        clusters = training.cluster(clusterer, "cluster")
        groups = clusters.reduceColumns(ee.Reducer.mean().group(0), ["cluster", "ndvi"])
        # Extract the cluster IDs and the means
        groups = ee.List(groups.get("groups"))
        ids = groups.map(lambda d: ee.Dictionary(d).get('group'))
        means = groups.map(lambda d: ee.Dictionary(d).get('mean'))

        # sort the IDs using the means as keys
        sorted = ee.Array(ids).sort(means).toList()

        #print(means, ids,sorted)
        # remap the clustered baseline and target mean ndvi images to put the clusters in order
        bl_clusters_sort = bl_clusters.remap(sorted, ids)
        tg_clusters_sort = tg_clusters.remap(sorted, ids)
        result = bl_clusters_sort.addBands(tg_clusters_sort).rename(['bl','tg'])

        return result

    # resample the land cover dataset to match ndvi projection
    ndviProjection = ndvi_1yr.projection()
    lc_res = landc.reduceResolution(reducer=ee.Reducer.mode(), maxPixels=1024) \
                  .reproject(crs=ndviProjection)

    # call function to cluster ndvi data
    ini_clusters = f_cluster_ndvi(year_init_bl_start, year_init_bl_end, year_init_tg_start, year_init_tg_end)
    eme_clusters = f_cluster_ndvi(year_emerg_bl_start, year_emerg_bl_end, year_emerg_tg_start, year_emerg_tg_end)

    # initial degradation: tg in ini_clusters <= 50%, then degraded
    # reclassify state as potential degradation (-1), no change (0), water (2), or urban (3)
    ini_degr = ee.Image(0).where(ini_clusters.select('tg').lte( 4), -1) \
                          .where(lc_res.eq(210),2) \
                          .where(lc_res.eq(190),3)

    # emerging degradation: difference between start and end clusters >= 2
    eme_clusters_chg = eme_clusters.select('tg').subtract(eme_clusters.select('bl'))

    # reclassify change as potential degradation (-1), no change (0), improvement (1), water (2), or urban (3)
    eme_degr = ee.Image(0).where(eme_clusters_chg.gte( 2), 1) \
                          .where(eme_clusters_chg.lte(-2), -1) \
                          .where(lc_res.eq(210),2) \
                          .where(lc_res.eq(190),3)

    tasks = []
    export_ini_degr = {'image': ini_degr.int16(),
                       'description': '{}_ini_degr'.format(EXECUTION_ID),
                       'fileNamePrefix': '{}_ini_degr'.format(EXECUTION_ID),
                       'bucket': BUCKET,
                       'maxPixels': 10000000000,
                       'scale': ee.Number(ndvi_1yr.projection().nominalScale()).getInfo(),
                       'region': util.get_coords(geojson)}
    tasks.append(util.gee_task(ee.batch.Export.image.toCloudStorage(**export_ini_degr), 'ini_degr', logger))

    export_eme_degr = {'image': eme_degr.int16(),
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
        results_url = CloudUrl("https://{}.storage.googleapis.com/{}_{}.tif".format(BUCKET, EXECUTION_ID, task.name))
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
    year_init_bl_end = params.get('year_init_bl_end', 2010)
    year_init_tg_start = params.get('year_init_tg_start', 2012)
    year_init_tg_end = params.get('year_init_tg_end', 2015)
    year_emerg_bl_start = params.get('year_emerg_bl_start', 2001)
    year_emerg_bl_end = params.get('year_emerg_bl_end', 2011)
    year_emerg_tg_start = params.get('year_emerg_tg_start', 2012)
    year_emerg_tg_end = params.get('year_emerg_tg_end', 2015)
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
            year_emerg_bl_start, year_emerg_bl_end,
            year_emerg_tg_start, year_emerg_tg_end,
            ndvi_gee_dataset, geojson, EXECUTION_ID, logger)

    return json_results.data
