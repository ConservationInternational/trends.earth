"""
Code for calculating all three SDG 15.3.1 sub-indicators.
"""
# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from builtins import str
import random
import json

import ee

from landdegradation.productivity import (
        productivity_trajectory, productivity_performance, productivity_state)
from landdegradation.land_cover import land_cover
from landdegradation.soc import soc
from landdegradation.download import download

from te_schemas.schemas import CloudResultsSchema
from te_schemas.land_cover import LCTransMatrix, LCLegendNesting


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    prod_mode = params.get('prod_mode')
    prod_traj_year_initial = params.get('prod_traj_year_initial')
    prod_traj_year_final = params.get('prod_traj_year_final')
    prod_perf_year_initial = params.get('prod_perf_year_initial')
    prod_perf_year_final = params.get('prod_perf_year_final')
    prod_state_year_bl_start = params.get('prod_state_year_bl_start')
    prod_state_year_bl_end = params.get('prod_state_year_bl_end')
    prod_state_year_tg_start = params.get('prod_state_year_tg_start')
    prod_state_year_tg_end = params.get('prod_state_year_tg_end')
    lc_year_initial = params.get('lc_year_initial')
    lc_year_final = params.get('lc_year_final')
    soc_year_initial = params.get('soc_year_initial')
    soc_year_final = params.get('soc_year_final')
    geojsons = params.get('geojsons')
    crs = params.get('crs')
    prod_traj_method = params.get('prod_traj_method')
    ndvi_gee_dataset = params.get('ndvi_gee_dataset')
    climate_gee_dataset = params.get('climate_gee_dataset')
    fl = params.get('fl')
    trans_matrix = LCTransMatrix.Schema().load(params.get('trans_matrix'))
    nesting = LCLegendNesting.Schema().load(params.get('nesting'))

    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    proj = ee.Image(ndvi_gee_dataset).projection()

    logger.debug("Running productivity indicators.")
    if prod_mode == 'Trends.Earth productivity':
        outs = []
        for geojson in geojsons:
            # Need to loop over the geojsons, since performance takes in a 
            # geojson.
            # TODO: pass performance a second geojson defining the entire extent of 
            # all input geojsons so that the performance is calculated the same 
            # over all input areas.
            out = productivity_trajectory(prod_traj_year_initial, 
                                          prod_traj_year_final, prod_traj_method,
                                          ndvi_gee_dataset, climate_gee_dataset, 
                                          logger)

            prod_perf = productivity_performance(prod_perf_year_initial, 
                                                 prod_perf_year_final, 
                                                 ndvi_gee_dataset, geojson, 
                                                 EXECUTION_ID, logger)
            out.merge(prod_perf)

            prod_state = productivity_state(prod_state_year_bl_start, 
                                            prod_state_year_bl_end, 
                                            prod_state_year_tg_start, 
                                            prod_state_year_tg_end,
                                            ndvi_gee_dataset, EXECUTION_ID, logger)
            out.merge(prod_state)

            logger.debug("Running land cover indicator.")
            lc = land_cover(lc_year_initial, lc_year_final, trans_matrix, nesting, 
                            EXECUTION_ID, logger)
            lc.selectBands(['Land cover (degradation)',
                            'Land cover (7 class)'])
            out.merge(lc)

            logger.debug("Running soil organic carbon indicator.")
            soc_out = soc(soc_year_initial, soc_year_final, fl, nesting, False, 
                          EXECUTION_ID, logger)
            soc_out.selectBands(['Soil organic carbon (degradation)',
                                 'Soil organic carbon'])
            out.merge(soc_out)

            logger.debug("Setting up layers to add to the map.")
            out.setAddToMap(['Soil organic carbon (degradation)',
                             'Land cover (degradation)',
                             'Productivity trajectory (significance)',
                             'Productivity state (degradation)',
                             'Productivity performance (degradation)',
                             'Land Productivity Dynamics (LPD)'])

            outs.append(out.export([geojson], 'sdg_sub_indicators', crs, logger,
                                   EXECUTION_ID, proj))

        # First need to deserialize the data that was prepared for output from
        # the productivity functions, so that new urls can be appended
        schema = CloudResultsSchema()
        logger.debug("Deserializing")
        final_prod = schema.load(outs[0])
        for o in outs[1:]:
            this_out = schema.load(o)
            final_prod.urls.extend(this_out.urls)
        logger.debug("Serializing")
        # Now serialize the output again so the remaining layers can be added
        # to it
        return schema.dump(final_prod)

    elif prod_mode == 'JRC LPD':
        out = download('users/geflanddegradation/toolbox_datasets/lpd_300m_longlat',
                       'Land Productivity Dynamics (LPD)', 'one time', 
                       None, None, EXECUTION_ID, logger)
        # Save as int16 to be compatible with other data
        out.image = out.image.int16()

        logger.debug("Running land cover indicator.")
        lc = land_cover(lc_year_initial, lc_year_final, trans_matrix, nesting,
                        EXECUTION_ID, logger)
        lc.selectBands(['Land cover (degradation)',
                        'Land cover (7 class)'])
        out.merge(lc)

        logger.debug("Running soil organic carbon indicator.")
        soc_out = soc(soc_year_initial, soc_year_final, fl, nesting, False,
                      EXECUTION_ID, logger)
        soc_out.selectBands(['Soil organic carbon (degradation)',
                             'Soil organic carbon'])
        out.merge(soc_out)

        out.setAddToMap(['Soil organic carbon (degradation)',
                         'Land cover (degradation)',
                         'Productivity trajectory (significance)',
                         'Productivity state (degradation)',
                         'Productivity performance (degradation)',
                         'Land Productivity Dynamics (LPD)'])

        return out.export(geojsons, 'sdg_sub_indicators', crs, logger,
                          EXECUTION_ID, proj)
    else:
        raise Exception('Unknown productivity mode "{}" chosen'.format(prod_mode))
