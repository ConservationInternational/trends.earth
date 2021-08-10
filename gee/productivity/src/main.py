"""
Code for calculating vegetation productivity.
"""
# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from builtins import str
import random
import json

import ee

from landdegradation.productivity import productivity_trajectory, \
    productivity_performance, productivity_state
from landdegradation.download import download
from te_schemas.schemas import CloudResultsSchema


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    prod_mode = params.get('prod_mode')
    calc_traj = params.get('calc_traj')
    calc_state = params.get('calc_state')
    calc_perf = params.get('calc_perf')
    prod_traj_year_initial = int(params.get('prod_traj_year_initial'))
    prod_traj_year_final = int(params.get('prod_traj_year_final'))
    prod_perf_year_initial = int(params.get('prod_perf_year_initial'))
    prod_perf_year_final = int(params.get('prod_perf_year_final'))
    prod_state_year_bl_start = int(params.get('prod_state_year_bl_start'))
    prod_state_year_bl_end = int(params.get('prod_state_year_bl_end'))
    prod_state_year_tg_start = int(params.get('prod_state_year_tg_start'))
    prod_state_year_tg_end = int(params.get('prod_state_year_tg_end'))
    geojsons = json.loads(params.get('geojsons'))
    crs = params.get('crs')
    prod_traj_method = params.get('trajectory_method')
    ndvi_gee_dataset = params.get('ndvi_gee_dataset')
    climate_gee_dataset = params.get('climate_gee_dataset')

    # Check the ENV. Are we running this locally or in prod?

    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    logger.debug("Running productivity indicators.")

    proj = ee.Image(ndvi_gee_dataset).projection()

    if prod_mode == 'Trends.Earth productivity':
        outs = []

        for geojson in geojsons:
            this_out = None

            if calc_traj:
                traj = productivity_trajectory(int(prod_traj_year_initial),
                                               int(prod_traj_year_final), prod_traj_method,
                                               ndvi_gee_dataset, climate_gee_dataset,
                                               logger)

                if not this_out:
                    this_out = traj

            if calc_perf:
                perf = productivity_performance(prod_perf_year_initial,
                                                prod_perf_year_final, ndvi_gee_dataset,
                                                geojson, logger)

                if not this_out:
                    this_out = perf
                else:
                    this_out.merge(perf)

            if calc_state:
                state = productivity_state(prod_state_year_bl_start,
                                           prod_state_year_bl_end,
                                           prod_state_year_tg_start,
                                           prod_state_year_tg_end,
                                           ndvi_gee_dataset, logger)

                if not this_out:
                    this_out = state
                else:
                    this_out.merge(state)

            outs.append(this_out.export([geojson], 'productivity', crs, logger,
                                        EXECUTION_ID, proj))

        # First need to deserialize the data that was prepared for output from
        # the productivity functions, so that new urls can be appended
        schema = CloudResultsSchema()
        logger.debug("Deserializing")
        final_output = schema.load(outs[0])

        for o in outs[1:]:
            this_out = schema.load(o)
            final_output.urls.extend(this_out.urls)
        logger.debug("Serializing")
        # Now serialize the output again and return it

        return schema.dump(final_output)

    elif prod_mode == 'JRC LPD':
        out = download('users/geflanddegradation/toolbox_datasets/lpd_300m_longlat',
                       'Land Productivity Dynamics (LPD)', 'one time',
                       None, None, logger)

        return out.export(geojsons, 'productivity', crs, logger, EXECUTION_ID, proj)
    else:
        raise Exception('Unknown productivity mode "{}" chosen'.format(prod_mode))
