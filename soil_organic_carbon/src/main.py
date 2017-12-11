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

from landdegradation.schemas import GEEResults, CloudDataset, CloudUrl, GEEResultsSchema

def soc(year_bl_start, year_bl_end, year_target, geojson, remap_matrix, 
        EXECUTION_ID, logger):
    """
    Calculate SOC indicator.
    """
    logger.debug("Entering soc function.")

    # TODO: code the SOC indicator. Right now this function just returns the 
    # soilgrids 0-30cm SOC data for use in the UNCCD reporting function in 
    # trends.earth.

    # ## land cover
    # lc = ee.Image("users/geflanddegradation/toolbox_datasets/lcov_esacc_1992_2015")
    #
    # ## target land cover map reclassified to IPCC 6 classes
    # lc_tg = lc.select('y{}'.format(year_target))\
    #         .remap(remap_matrix[0], remap_matrix[1])
    #
    # ## baseline land cover map reclassified to IPCC 6 classes
    # lc_bl = lc.select(ee.List.sequence(year_bl_start - 1992, year_bl_end - 1992, 1))\
    #         .reduce(ee.Reducer.mode())\
    #         .remap(remap_matrix[0], remap_matrix[1])
    #
    # ## compute transition map (first digit for baseline land cover, and second digit for target year land cover)
    # lc_tr = lc_bl.multiply(10).add(lc_tg)

    ## soc
    soc = ee.Image("users/geflanddegradation/toolbox_datasets/soc_sgrid_30cm")

    #lc_out = lc_bl.addBands(lc_tg).addBands(lc_tr).addBands(lc_dg).addBands(soc)
    lc_out = soc

    # Create export function to export land deg image
    task = util.export_to_cloudstorage(lc_out.int16(), 
            lc.projection(), geojson, 'soc', logger, 
            EXECUTION_ID)
    task.join()

    logger.debug("Setting up results JSON.")
    cloud_dataset = CloudDataset('geotiff', 'soc', [CloudUrl(task.url())])
    gee_results = GEEResults('soc', [cloud_dataset])
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
    json_results = soc(year_bl_start, year_bl_end, year_target, geojson, 
                       remap_matrix, EXECUTION_ID, logger)

    return json_results.data
