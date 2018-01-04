"""
Code for calculating soil organic carbon indicator.
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

from landdegradation.schemas import BandInfo, URLList, CloudResults, CloudResultsSchema


def soc(year_bl_start, year_bl_end, year_target, fl, geojson, remap_matrix,
        EXECUTION_ID, logger):
    """
    Calculate SOC indicator.
    """
    logger.debug("Entering soc function.")

    ## land cover
    lc = ee.Image("users/geflanddegradation/toolbox_datasets/lcov_esacc_1992_2015")

    ## target land cover map reclassified to IPCC 6 classes
    lc_tg = lc.select('y{}'.format(year_target))\
        .remap(remap_matrix[0], remap_matrix[1])

    ## baseline land cover map reclassified to IPCC 6 classes
    lc_bl = lc.select(ee.List.sequence(year_bl_start - 1992, year_bl_end - 1992, 1))\
        .reduce(ee.Reducer.mode())\
        .remap(remap_matrix[0], remap_matrix[1])

    ## compute transition map (first digit for baseline land cover, and second digit for target year land cover)
    lc_tr = lc_bl.multiply(10).add(lc_tg)

    ## soc
    soc = ee.Image("users/geflanddegradation/toolbox_datasets/soc_sgrid_30cm")
    soc_ini = soc.updateMask(soc.neq(-32768))

    # stock change factor for land use - note the 99 and -99 will be recoded 
    # using the chosen Fl option
    lc_tr_fl_0 = lc_tr.remap([11, 12, 13, 14, 15, 16, 17,
                              21, 22, 23, 24, 25, 26, 27,
                              31, 32, 33, 34, 35, 36, 37,
                              41, 42, 43, 44, 45, 46, 47,
                              51, 52, 53, 54, 55, 56, 57,
                              61, 62, 63, 64, 65, 66, 67,
                              71, 72, 73, 74, 75, 76, 77],
                             [1, 1, 99, 1, 0.1, 0.1, 0,
                              1, 1, 99, 1, 0.1, 0.1, 0,
                              -99, -99, 1, 1 / 0.71, 0.1, 0.1, 0,
                              1, 1, 0.71, 1, 0.1, 0.1, 0,
                              10, 10, 10, 10, 1, 1, 0,
                              10, 10, 10, 10, 1, 1, 0,
                              0, 0, 0, 0, 0, 0, 0])

    if fl == 'per pixel':
        ## Setup a raster of climate regimes to use for coding Fl automatically
        climate = ee.Image("users/geflanddegradation/toolbox_datasets/ipcc_climate_zones")\
            .remap([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], 
                   [0, 2, 1, 2, 1, 2, 1, 2, 1, 5, 4, 4, 3])
        var clim_fl = climate.remap([0, 1, 2, 3, 4, 5],
                                    [0, 0.8, 0.69, 0.58, 0.48, 0.64])
        lc_tr_fl = lc_tr_fl_0.where(lc_tr_fl_0.eq( 99), clim_fl)\
                             .where(lc_tr_fl_0.eq(-99), ee.Image(1).divide(clim_fl))
    else:
        lc_tr_fl = lc_tr_fl_0.where(lc_tr_fl_0.eq( 99), fl)
                             .where(lc_tr_fl_0.eq(-99), ee.Image(1).divide(fl))

    # stock change factor for management regime
    lc_tr_fm = lc_tr.remap([11, 12, 13, 14, 15, 16, 17,
                            21, 22, 23, 24, 25, 26, 27,
                            31, 32, 33, 34, 35, 36, 37,
                            41, 42, 43, 44, 45, 46, 47,
                            51, 52, 53, 54, 55, 56, 57,
                            61, 62, 63, 64, 65, 66, 67,
                            71, 72, 73, 74, 75, 76, 77],
                           [1, 1, 1, 1, 1, 1, 1,
                            1, 1, 1, 1, 1, 1, 1,
                            1, 1, 1, 1, 1, 1, 1,
                            1, 1, 1, 1, 1, 1, 1,
                            1, 1, 1, 1, 1, 1, 1,
                            1, 1, 1, 1, 1, 1, 1,
                            1, 1, 1, 1, 1, 1, 1])

    # stock change factor for input of organic matter
    lc_tr_fo = lc_tr.remap([11, 12, 13, 14, 15, 16, 17,
                            21, 22, 23, 24, 25, 26, 27,
                            31, 32, 33, 34, 35, 36, 37,
                            41, 42, 43, 44, 45, 46, 47,
                            51, 52, 53, 54, 55, 56, 57,
                            61, 62, 63, 64, 65, 66, 67,
                            71, 72, 73, 74, 75, 76, 77],
                           [1, 1, 1, 1, 1, 1, 1,
                            1, 1, 1, 1, 1, 1, 1,
                            1, 1, 1, 1, 1, 1, 1,
                            1, 1, 1, 1, 1, 1, 1,
                            1, 1, 1, 1, 1, 1, 1,
                            1, 1, 1, 1, 1, 1, 1,
                            1, 1, 1, 1, 1, 1, 1])

    soc_fin = soc_ini.subtract((((soc_ini.subtract((soc_ini.
                                                    multiply(lc_tr_fl).
                                                    multiply(lc_tr_fm).
                                                    multiply(lc_tr_fo)))).
                                 divide(20)).multiply(year_target - year_bl_start)))

    soc_pch = ((soc_fin.subtract(soc_ini)).divide(soc_ini)).multiply(100)

    soc_out = soc_pch.addBands(soc_ini).addBands(soc_fin)

    task = util.export_to_cloudstorage(soc_out.int16(),
                                       soc_out.projection(), geojson, 
                                       'soil_organic_carbon', logger,
                                       EXECUTION_ID)
    task.join()

    logger.debug("Setting up results JSON.")
    d = [BandInfo("Soil organic carbon (degradation)", 1, no_data_value=-32768, add_to_map=True),
         BandInfo("Soil organic carbon (baseline)", 2, no_data_value=-32768, add_to_map=True),
         BandInfo("Soil organic carbon (target)", 3, no_data_value=-32768, add_to_map=True)]
    u = URLList(task.get_URL_base(), task.get_files())
    gee_results = CloudResults('soil_organic_carbon', d, u)
    results_schema = CloudResultsSchema()
    json_results = results_schema.dump(gee_results)

    return json_results


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    year_bl_start = params.get('year_bl_start', 2002)
    year_bl_end = params.get('year_bl_end', 2015)
    year_target = params.get('year_target', 2015)
    fl = params.get('fl', .80) # Default to fl of .80 (temperate dry)

    geojson = params.get('geojson', util.tza_geojson)
    remap_matrix_default = [[10, 11, 12, 20, 30, 40, 50, 60, 61, 62, 70, 71, 72,
                             80, 81, 82, 90, 100, 110, 120, 121, 122, 130, 140,
                             150, 151, 152, 153, 160, 170, 180, 190, 200, 201,
                             202, 210, 220],
                            [3, 3, 3, 3, 3, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
                             1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1, 4, 4, 5, 6, 6,
                             6, 7, 6]]
    remap_matrix = params.get('remap_matrix', remap_matrix_default)

    if len(remap_matrix) != 2 or len(remap_matrix[0]) != 37 or len(remap_matrix[1]) != 37:
        raise GEEIOError("Transition matrix must be a list of two lists with 37 entries each")

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
    json_results = soc(year_bl_start, year_bl_end, year_target, fl, geojson,
                       remap_matrix, EXECUTION_ID, logger)

    return json_results.data
