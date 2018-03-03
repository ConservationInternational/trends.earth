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

from landdegradation import stats
from landdegradation import util
from landdegradation import GEEIOError

from landdegradation.soc import soc

from landdegradation.schemas import BandInfo, URLList, CloudResults, CloudResultsSchema


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
    soc_out, d = soc(year_start, year_end, fl, geojson,
                       remap_matrix, dl_annual_soc, dl_annual_lc, EXECUTION_ID, 
                       logger)

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

    return json_results.data
