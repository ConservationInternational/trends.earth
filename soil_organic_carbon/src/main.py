"""
Code for calculating soil organic carbon indicator.
"""
# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from . import __version__

import random
import json

import ee

from landdegradation import preproc
from landdegradation import stats
from landdegradation import util
from landdegradation import GEEIOError

from landdegradation.schemas import BandInfo, URLList, CloudResults, CloudResultsSchema


def soc(year_start, year_end, fl, geojson, remap_matrix,
        dl_annual_soc, dl_annual_lc, EXECUTION_ID, logger):
    """
    Calculate SOC indicator.
    """
    logger.debug("Entering soc function.")

    # soc
    #soc = ee.Image("users/geflanddegradation/toolbox_datasets/soc_sgrid_30cm")
    soc = ee.Image("users/geflanddegradation/toolbox_datasets/soc_sgrid_30cm_unccd_20180111")
    soc_t0 = soc.updateMask(soc.neq(-32768))

    # land cover - note it needs to be reprojected to match soc so that it can 
    # be output to cloud storage in the same stack
    lc = ee.Image("users/geflanddegradation/toolbox_datasets/lcov_esacc_1992_2015") \
            .select(ee.List.sequence(year_start - 1992, year_end - 1992, 1)) \
            .reproject(crs=soc.projection())
    lc = lc.where(lc.eq(9999), -32768)
    lc = lc.updateMask(lc.neq(-32768))

    if fl == 'per pixel':
        # Setup a raster of climate regimes to use for coding Fl automatically
        climate = ee.Image("users/geflanddegradation/toolbox_datasets/ipcc_climate_zones")\
            .remap([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], 
                   [0, 2, 1, 2, 1, 2, 1, 2, 1, 5, 4, 4, 3])
        clim_fl = climate.remap([0, 1, 2, 3, 4, 5],
                                [0, 0.8, 0.69, 0.58, 0.48, 0.64])
    # create empty stacks to store annual land cover maps
    stack_lc  = ee.Image().select()

    # create empty stacks to store annual soc maps
    stack_soc = ee.Image().select()

    # loop through all the years in the period of analysis to compute changes in SOC
    for k in range(year_end - year_start):
        # land cover map reclassified to UNCCD 7 classes (1: forest, 2: 
        # grassland, 3: cropland, 4: wetland, 5: artifitial, 6: bare, 7: water)
        lc_t0 = lc.select(k).remap(remap_matrix[0], remap_matrix[1])

        lc_t1 = lc.select(k + 1).remap(remap_matrix[0], remap_matrix[1])

        if (k == 0):
            # compute transition map (first digit for baseline land cover, and 
            # second digit for target year land cover) 
            lc_tr = lc_t0.multiply(10).add(lc_t1)
          
            # compute raster to register years since transition
            tr_time = ee.Image(2).where(lc_t0.neq(lc_t1), 1)
        else:
            # Update time since last transition. Add 1 if land cover remains 
            # constant, and reset to 1 if land cover changed.
            tr_time = tr_time.where(lc_t0.eq(lc_t1), tr_time.add(ee.Image(1))) \
                .where(lc_t0.neq(lc_t1), ee.Image(1))
                               
            # compute transition map (first digit for baseline land cover, and 
            # second digit for target year land cover), but only update where 
            # changes actually ocurred.
            lc_tr_temp = lc_t0.multiply(10).add(lc_t1)
            lc_tr = lc_tr.where(lc_t0.neq(lc_t1), lc_tr_temp)

        # stock change factor for land use - note the 99 and -99 will be 
        # recoded using the chosen Fl option
        lc_tr_fl_0 = lc_tr.remap([11, 12, 13, 14, 15, 16, 17,
                                  21, 22, 23, 24, 25, 26, 27,
                                  31, 32, 33, 34, 35, 36, 37,
                                  41, 42, 43, 44, 45, 46, 47,
                                  51, 52, 53, 54, 55, 56, 57,
                                  61, 62, 63, 64, 65, 66, 67,
                                  71, 72, 73, 74, 75, 76, 77],
                                 [1, 1, 99, 1, 0.1, 0.1, 1,
                                  1, 1, 99, 1, 0.1, 0.1, 1,
                                  -99, -99, 1, 1 / 0.71, 0.1, 0.1, 1,
                                  1, 1, 0.71, 1, 0.1, 0.1, 1,
                                  2, 2, 2, 2, 1, 1, 1,
                                  2, 2, 2, 2, 1, 1, 1,
                                  1, 1, 1, 1, 1, 1, 1])

        if fl == 'per pixel':
            lc_tr_fl = lc_tr_fl_0.where(lc_tr_fl_0.eq(99), clim_fl)\
                                 .where(lc_tr_fl_0.eq(-99), ee.Image(1).divide(clim_fl))
        else:
            lc_tr_fl = lc_tr_fl_0.where(lc_tr_fl_0.eq(99), fl)\
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

        if (k == 0):
            soc_chg = (soc_t0.subtract((soc_t0.multiply(lc_tr_fl).multiply(lc_tr_fm).multiply(lc_tr_fo)))).divide(20)
          
            # compute final SOC stock for the period
            soc_t1 = soc_t0.subtract(soc_chg)
            
            # add to land cover and soc to stacks from both dates for the first 
            # period
            stack_lc = stack_lc.addBands(lc_t0).addBands(lc_t1)
            stack_soc = stack_soc.addBands(soc_t0).addBands(soc_t1)

        else:
            # compute annual change in soc (updates from previous period based 
            # on transition and time <20 years)
            soc_chg = soc_chg.where(lc_t0.neq(lc_t1),
                                    (stack_soc.select(k).subtract(stack_soc.select(k) \
                                                                  .multiply(lc_tr_fl) \
                                                                  .multiply(lc_tr_fm) \
                                                                  .multiply(lc_tr_fo))).divide(20)) \
                             .where(tr_time.gt(20), 0)
          
            # compute final SOC for the period
            socn = stack_soc.select(k).subtract(soc_chg)
          
            # add land cover and soc to stacks only for the last year in the 
            # period
            stack_lc = stack_lc.addBands(lc_t1)
            stack_soc = stack_soc.addBands(socn)

    # compute soc percent change for the analysis period
    soc_pch = ((stack_soc.select(year_end - year_start).subtract(stack_soc.select(0))).divide(stack_soc.select(0))) \
        .multiply(100)


    logger.debug("Setting up results JSON.")
    soc_out = soc_pch
    d = [BandInfo("Soil organic carbon (degradation)", 1, no_data_value=-32768, add_to_map=True, metadata={'year_start': year_start, 'year_end': year_end})]

    if not dl_annual_soc:
        # Output percent change and initial and final SOC layers
        soc_out = soc_out.addBands(stack_soc.select(0)).addBands(stack_soc.select(year_end - year_start))
        d.extend([BandInfo("Soil organic carbon", 2, no_data_value=-32768, add_to_map=True, metadata={'year': year_start}),
                  BandInfo("Soil organic carbon", 3, no_data_value=-32768, add_to_map=True, metadata={'year': year_end})])
    else:
        # Output percent change and annual SOC layers
        soc_out = soc_out.addBands(stack_soc)
        for year in range(year_start, year_end + 1):
            if (year == year_start) or (year == year_end):
                add_to_map = True
            else:
                add_to_map = False
            d.extend([BandInfo("Soil organic carbon", len(d) + 1, no_data_value=-32768, add_to_map=add_to_map, metadata={'year': year})])

    if not dl_annual_lc:
        # Output percent change and initial and final SOC layers
        soc_out = soc_out.addBands(stack_lc.select(0)).addBands(stack_lc.select(year_end - year_start))
        d.extend([BandInfo("Land cover (7 class)", len(d) + 1, no_data_value=-32768, add_to_map=True, metadata={'year': year_start}),
                  BandInfo("Land cover (7 class)", len(d) + 1, no_data_value=-32768, add_to_map=True, metadata={'year': year_end})])
    else:
        soc_out = soc_out.addBands(stack_lc)
        for year in range(year_start, year_end + 1):
            if (year == year_start) or (year == year_end):
                add_to_map = True
            else:
                add_to_map = False
            d.extend([BandInfo("Land cover (7 class)", len(d) + 1, no_data_value=-32768, add_to_map=add_to_map, metadata={'year': year})])

    task = util.export_to_cloudstorage(soc_out.unmask(-32768).int16(),
                                       soc_out.projection(), geojson, 
                                       'soil_organic_carbon', logger,
                                       EXECUTION_ID)
    task.join()

    u = URLList(task.get_URL_base(), task.get_files())
    gee_results = CloudResults('soil_organic_carbon', __version__, d, u)
    results_schema = CloudResultsSchema()
    json_results = results_schema.dump(gee_results)

    return json_results


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    year_start = params.get('year_start', 2000)
    year_end = params.get('year_end', 2015)
    fl = params.get('fl', .80) # Default to fl of .80 (temperate dry)
    dl_annual_soc = params.get('download_annual_soc', False)
    dl_annual_lc = params.get('download_annual_lc', False)

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
    json_results = soc(year_start, year_end, fl, geojson,
                       remap_matrix, dl_annual_soc, dl_annual_lc, EXECUTION_ID, 
                       logger)

    return json_results.data
