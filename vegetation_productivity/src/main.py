"""
Code for calculating temporal NDVI analysis.
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

def ndvi_trend(year_start, year_end, ndvi_1yr, logger):
    """Calculate temporal NDVI analysis.
    Calculates the trend of temporal NDVI using NDVI data from the
    MODIS Collection 6 MOD13Q1 dataset. Areas where changes are not significant
    are masked out using a Mann-Kendall test.
    Args:
        year_start: The starting year (to define the period the trend is
            calculated over).
        year_end: The ending year (to define the period the trend is
            calculated over).
    Returns:
        Output of google earth engine task.
    """
    logger.debug("Entering ndvi_trend function.")

    def f_img_coll(ndvi_stack):
        img_coll = ee.List([])
        for k in range(year_start, year_end):
            ndvi_img = ndvi_stack.select('y' + str(k)).addBands(ee.Image(k).float()).rename(['ndvi', 'year'])
            img_coll = img_coll.add(ndvi_img)
        return ee.ImageCollection(img_coll)
    
    ## Apply function to compute NDVI annual integrals from 15d observed NDVI data
    ndvi_1yr_coll = f_img_coll(ndvi_1yr)
    
    ## Compute linear trend function to predict ndvi based on year (ndvi trend)
    lf_trend = ndvi_1yr_coll.select(['year', 'ndvi']).reduce(ee.Reducer.linearFit())

    ## Compute Kendall statistics
    mk_trend  = stats.mann_kendall(ndvi_1yr_coll.select('ndvi'))

    return (lf_trend, mk_trend)

def p_restrend(year_start, year_end, ndvi_1yr, climate_1yr, logger):
    logger.debug("Entering p_restrend function.")

    def f_img_coll(ndvi_stack):
        img_coll = ee.List([])
        for k in range(year_start, year_end):
            ndvi_img = ndvi_stack.select('y{}'.format(k))\
                .addBands(climate_1yr.select('y{}'.format(k)))\
                .rename(['ndvi','clim']).set({'year': k})
            img_coll = img_coll.add(ndvi_img)
        return ee.ImageCollection(img_coll)

    ## Function to predict NDVI from climate
    first = ee.List([])
    def f_ndvi_clim_p(image, list):
        ndvi = lf_clim_ndvi.select('offset').add((lf_clim_ndvi.select('scale').multiply(image))).set({'year': image.get('year')})
        return ee.List(list).add(ndvi)

    ## Function to compute residuals (ndvi obs - ndvi pred)
    def f_ndvi_clim_r_img(year): 
        ndvi_o = ndvi_1yr_coll.filter(ee.Filter.eq('year', year)).select('ndvi').median()
        ndvi_p = ndvi_1yr_p.filter(ee.Filter.eq('year', year)).median()
        ndvi_r = ee.Image(year).float().addBands(ndvi_o.subtract(ndvi_p))
        return ndvi_r.rename(['year','ndvi_res'])

    # Function to compute differences between observed and predicted NDVI and compilation in an image collection
    def stack(year_start, year_end):
        img_coll = ee.List([])
        for k in range(year_start, year_end):
            ndvi = ndvi_1yr_o.filter(ee.Filter.eq('year', k)).select('ndvi').median()
            clim = clim_1yr_o.filter(ee.Filter.eq('year', k)).select('ndvi').median()
            img = ndvi.addBands(clim.addBands(ee.Image(k).float())).rename(['ndvi','clim','year']).set({'year': k})
            img_coll = img_coll.add(img)
        return ee.ImageCollection(img_coll)

    ## Function create image collection of residuals
    def f_ndvi_clim_r_coll(year_start, year_end): 
        res_list = ee.List([])
        #for(i = year_start i <= year_end i += 1):
        for i in range(year_start, year_end):
            res_image = f_ndvi_clim_r_img(i)
            res_list = res_list.add(res_image)
        return ee.ImageCollection(res_list)

    ## Apply function to create image collection of ndvi and climate
    ndvi_1yr_coll = f_img_coll(ndvi_1yr)
    
    ## Compute linear trend function to predict ndvi based on climate (independent are followed by dependent var
    lf_clim_ndvi = ndvi_1yr_coll.select(['clim', 'ndvi']).reduce(ee.Reducer.linearFit())

    ## Apply function to  predict NDVI based on climate
    ndvi_1yr_p = ee.ImageCollection(ee.List(ndvi_1yr_coll.select('clim').iterate(f_ndvi_clim_p, first)))

    ## Apply function to compute NDVI annual residuals
    ndvi_1yr_r  = f_ndvi_clim_r_coll(year_start,year_end)

    ## Fit a linear regression to the NDVI residuals
    lf_trend = ndvi_1yr_r.select(['year', 'ndvi_res']).reduce(ee.Reducer.linearFit())

    ## Compute Kendall statistics
    mk_trend  = stats.mann_kendall(ndvi_1yr_r.select('ndvi_res'))

    return (lf_trend, mk_trend)

def s_restrend(year_start, year_end, ndvi_1yr, climate_1yr, logger):
    #TODO: Copy this code over
    logger.debug("Entering s_restrend function.")

def ue_trend(year_start, year_end, ndvi_1yr, climate_1yr, logger):
    # Convert the climate layer to meters (for precip) so that RUE layer can be 
    # scaled correctly
    # TODO: Need to handle scaling for ET for WUE
    climate_1yr = climate_1yr.divide(1000)
    logger.debug("Entering ue_trend function.")
    def f_img_coll(ndvi_stack):
        img_coll = ee.List([])
        for k in range(year_start, year_end):
            ndvi_img = ndvi_stack.select('y{}'.format(k)).divide(climate_1yr.select('y{}'.format(k)))\
                                .addBands(ee.Image(k).float())\
                                .rename(['ue','year']).set({'year': k})
            img_coll = img_coll.add(ndvi_img)
        return ee.ImageCollection(img_coll)

    ## Apply function to compute ue and store as a collection
    ue_1yr_coll = f_img_coll(ndvi_1yr)

    ## Compute linear trend function to predict ndvi based on year (ndvi trend)
    lf_trend = ue_1yr_coll.select(['year', 'ue']).reduce(ee.Reducer.linearFit())

    ## Compute Kendall statistics
    mk_trend  = stats.mann_kendall(ue_1yr_coll.select('ue'))

    return (lf_trend, mk_trend)

def vegetation_productivity(year_start, year_end, method, sensor, climate, 
        geojson, EXECUTION_ID, logger):
    """Calculate temporal NDVI analysis.
    Calculates the trend of temporal NDVI using NDVI data from the
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
    logger.debug("Entering vegetation_productivity function.")

    # Climate
    if climate == 'et_mod16a2':
        climate_1yr = ee.Image("users/geflanddegradation/toolbox_datasets/et_modis_2000_2014")
    elif climate == 'prec_gpcp':
        climate_1yr = ee.Image("users/geflanddegradation/toolbox_datasets/prec_gpcp23_1979_2016")
    elif climate == 'prec_gpcc':
        climate_1yr = ee.Image("users/geflanddegradation/toolbox_datasets/prec_gpcc_1901_2016")
    elif climate == 'prec_chirps':
        climate_1yr =  ee.Image("users/geflanddegradation/toolbox_datasets/prec_chirps_1981_2016")
    elif climate == 'prec_persian':
        climate_1yr = ee.Image("users/geflanddegradation/toolbox_datasets/prec_persian_1983_2015")
    elif climate == 'soilm_merra2':
        climate_1yr = ee.Image("users/geflanddegradation/toolbox_datasets/soilm_merra2_1980_2016")
    elif climate == 'soilm_erai':
        climate_1yr = ee.Image("users/geflanddegradation/toolbox_datasets/soilm_erai_1979_2016")
    elif climate == None:
        if method == 'ndvi_trend':
            pass
        else: 
            raise GEEIOError("Must specify a climate dataset")
    else:
        raise GEEIOError("Unrecognized climate dataset '{}'".format(climate))

    # Sensors        
    if (sensor == 'AVHRR'):
        ndvi_1yr = ee.Image("users/geflanddegradation/toolbox_datasets/ndvi_avhrr_1982_2015")
    elif (sensor == 'MODIS'):
        ndvi_1yr = ee.Image("users/geflanddegradation/toolbox_datasets/ndvi_modis_2001_2016")
    else:
        raise GEEIOError("Unrecognized sensor '{}'".format(sensor))

    # Run the selected algorithm
    if method == 'ndvi_trend':
        lf_trend, mk_trend = ndvi_trend(year_start, year_end, ndvi_1yr, logger)
    elif method == 'p_restrend':
        lf_trend, mk_trend = p_restrend(year_start, year_end, ndvi_1yr, climate_1yr, logger)
        if climate_1yr == None: climate_1yr = precp_gpcc
    elif method == 's_restrend':
        #TODO: need to code this
        raise GEEIOError("s_restrend method not yet supported")
    elif method == 'ue':
        lf_trend, mk_trend = ue_trend(year_start, year_end, ndvi_1yr, climate_1yr, logger)
    else:
        raise GEEIOError("Unrecognized method '{}'".format(method))

    # Define Kendall parameter values for a significance of 0.05
    period = year_end - year_start + 1
    coefficients = ee.Array([4, 6, 9, 11, 14, 16, 19, 21, 24, 26, 31, 33, 36,
                            40, 43, 47, 50, 54, 59, 63, 66, 70, 75, 79, 84,
                            88, 93, 97, 102, 106, 111, 115, 120, 126, 131,
                            137, 142])
    kendall = coefficients.get([period - 4])

    # Land cover data is used to mask water and urban
    landc = ee.Image("users/geflanddegradation/toolbox_datasets/lcov_esacc_1992_2015").select('y{}'.format(year_end))
    # Resample the land cover dataset to match ndvi projection
    ndviProjection = ndvi_1yr.projection()
    landc_reducer = {'reducer': ee.Reducer.mode(),
                     'maxPixels': 1024}
    landc_reproject = {'crs': ndviProjection.crs().getInfo(),
                       'scale': ee.Number(ndviProjection.nominalScale()).getInfo()}

    landc_res = landc.reduceResolution(**landc_reducer)\
            .reproject(**landc_reproject)
 
    attri = ee.Image(0).where(lf_trend.select('scale').gt(0).And(mk_trend.abs().gte(kendall)),  1)\
        .where(lf_trend.select('scale').lt(0).And(mk_trend.abs().gte(kendall)), -1)\
        .where(mk_trend.abs().lte(kendall), 0)\
        .where(landc_res.eq(210),2)\
        .where(landc_res.eq(190),3)
                           
    output = lf_trend.select('scale').addBands(attri).rename(['slope','attri'])

    export = {'image': output.int16(),
             'description': EXECUTION_ID,
             'fileNamePrefix': EXECUTION_ID,
             'bucket': BUCKET,
             'maxPixels': 10000000000,
             'scale': ee.Number(ndviProjection.nominalScale()).getInfo(),
             'region': util.get_coords(geojson)}

    logger.debug("Setting up GEE task.")
    task = ee.batch.Export.image.toCloudStorage(**export)

    task_state = util.run_task(task, logger)

    return "https://{}.storage.googleapis.com/{}.tif".format(BUCKET, EXECUTION_ID)

def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    year_start = params.get('year_start', 2001)
    year_end = params.get('year_end', 2015)
    geojson_str = params.get('geojson', None)
    method = params.get('method', 'ndvi_trend')
    sensor = params.get('sensor', 'MODIS')
    climate = params.get('climate', None)

    if geojson_str is None:
        raise GEEIOError("Must specify an input area")
    else: 
        geojson = json.loads(geojson_str)

    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    logger.debug("Running main script.")
    url = vegetation_productivity(year_start, year_end, method, sensor, 
            climate, geojson, EXECUTION_ID, logger)

    logger.debug("Setting up results JSON.")
    results_url = CloudUrl(url, 'TODO_HASH_GOES_HERE') 
    cloud_dataset = CloudDataset('geotiff', method, results_url)
    gee_results = GEEResults('cloud_dataset', cloud_dataset)
    results_schema = GEEResultsSchema()
    json_result = results_schema.dump(gee_results)

    logger.debug("Setting up results JSON.")
    return json_result.data
