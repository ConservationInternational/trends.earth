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

from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed
)

import ee

from landdegradation.productivity import (
    productivity_trajectory,
    productivity_performance,
    productivity_state
)
from landdegradation.land_cover import land_cover
from landdegradation.soc import soc
from landdegradation.download import download

from te_schemas.schemas import CloudResultsSchema
from te_schemas.land_cover import LCTransitionDefinitionDeg, LCLegendNesting


def run_te_for_period(params, EXECUTION_ID, logger):
    '''Run indicators using Trends.Earth productivity'''
    prod_params = params.get('productivity')
    lc_params = params.get('land_cover')
    soc_params = params.get('soil_organic_carbon')

    prod_asset = prod_params.get('prod_asset')
    proj = ee.Image(prod_asset).projection()

    # Need to loop over the geojsons, since performance takes in a
    # geojson.
    outs = []

    for geojson in params.get('geojsons'):
        # TODO: pass performance a second geojson defining the entire
        # extent of all input geojsons so that the performance is
        # calculated the same over all input areas.
        out = productivity_trajectory(
            prod_params.get('traj_year_initial'),
            prod_params.get('traj_year_final'),
            prod_params.get('traj_method'),
            prod_asset,
            prod_params.get('climate_asset'),
            logger
        )

        prod_perf = productivity_performance(
            prod_params.get('perf_year_initial'),
            prod_params.get('perf_year_final'),
            prod_asset,
            geojson,
            logger
        )
        out.merge(prod_perf)

        prod_state = productivity_state(
            prod_params.get('state_year_bl_start'),
            prod_params.get('state_year_bl_end'),
            prod_params.get('state_year_tg_start'),
            prod_params.get('state_year_tg_end'),
            prod_asset,
            logger
        )
        out.merge(prod_state)

        logger.debug("Running land cover indicator.")
        lc = land_cover(
            lc_params.get('year_initial'),
            lc_params.get('year_final'),
            LCTransitionDefinitionDeg.Schema().load(
                lc_params.get('trans_matrix')
            ),
            LCLegendNesting.Schema().load(
                lc_params.get('legend_nesting')
            ),
            logger
        )
        lc.selectBands(['Land cover (degradation)',
                        'Land cover (7 class)'])
        out.merge(lc)

        logger.debug("Running soil organic carbon indicator.")
        soc_out = soc(
            soc_params.get('year_initial'),
            soc_params.get('year_final'),
            soc_params.get('fl'),
            LCTransitionDefinitionDeg.Schema().load(
                soc_params.get('trans_matrix')
            ),
            LCLegendNesting.Schema().load(
                soc_params.get('legend_nesting')
            ),
            False,
            logger
        )
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

        outs.append(
            out.export(
                [geojson],
                'sdg_sub_indicators',
                params.get('crs'),
                logger,
                EXECUTION_ID,
                proj
            )
        )

    # Deserialize the data that was prepared for output from the productivity
    # functions, so that new urls can be appended
    schema = CloudResultsSchema()
    logger.debug("Deserializing")
    final_prod = schema.load(outs[0])

    for o in outs[1:]:
        this_out = schema.load(o)
        final_prod.urls.extend(this_out.urls)
    logger.debug("Serializing")
    # Now serialize the output again so the remaining layers can be
    # added to it

    return schema.dump(final_prod)


def run_jrc_for_period(params, EXECUTION_ID, logger):
    '''Run indicators using JRC LPD for productivity'''
    lc_params = params.get('land_cover')
    soc_params = params.get('soil_organic_carbon')

    prod_asset = params.get('prod_asset')
    proj = ee.Image(prod_asset).projection()
    out = download(
        prod_asset,
        'Land Productivity Dynamics (LPD)',
        'one time',
        None,
        None,
        logger
    )
    # Save as int16 to be compatible with other data
    out.image = out.image.int16()

    logger.debug("Running land cover indicator.")
    lc = land_cover(
        lc_params.get('year_initial'),
        lc_params.get('year_final'),
        LCTransitionDefinitionDeg.Schema().load(
            lc_params.get('trans_matrix')
        ),
        LCLegendNesting.Schema().load(
            lc_params.get('legend_nesting')
        ),
        logger
    )
    lc.selectBands(['Land cover (degradation)',
                    'Land cover (7 class)'])
    out.merge(lc)

    logger.debug("Running soil organic carbon indicator.")
    soc_out = soc(
        soc_params.get('year_initial'),
        soc_params.get('year_final'),
        soc_params.get('fl'),
        LCTransitionDefinitionDeg.Schema().load(
            soc_params.get('trans_matrix')
        ),
        LCLegendNesting.Schema().load(
            soc_params.get('legend_nesting')
        ),
        False,
        logger
    )
    soc_out.selectBands(['Soil organic carbon (degradation)',
                         'Soil organic carbon'])
    out.merge(soc_out)

    out.setAddToMap(['Soil organic carbon (degradation)',
                     'Land cover (degradation)',
                     'Productivity trajectory (significance)',
                     'Productivity state (degradation)',
                     'Productivity performance (degradation)',
                     'Land Productivity Dynamics (LPD)'])

    return out.export(
        params.get('geojsons'),
        'sdg_sub_indicators',
        params.get('crs'),
        logger,
        EXECUTION_ID,
        proj
    )

    return out

def run_period(params, EXECUTION_ID, logger):
    '''Run indicators for a given period, using JRC or Trends.Earth'''

    if params['productivity']['mode'] == 'Trends.Earth productivity':
        out = run_te_for_period(params, EXECUTION_ID, logger)
    elif params['productivity']['mode'] == 'JRC LPD':
        out = run_jrc_for_period(params, EXECUTION_ID, logger)
    else:
        raise Exception(
            'Unknown productivity mode "{}" chosen'.format(
                params['productivity']['mode']
            )
        )

    return out


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")

    period_params = {'baseline': params.get('baseline')}

    if 'progress' in params:
        period_params['progress'] = params.get('progress')

    # Check the ENV. Are we running this locally or in prod?

    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    with ThreadPoolExecutor(max_workers=2) as executor:
        res = []

        for period, values in period_params.items():
            values.update(
                {
                    'geojsons': params.get('geojsons'),
                    'crs': params.get('crs')
                }
            )
            res.append(
                executor.submit(
                    run_period,
                    values,
                    EXECUTION_ID,
                    logger
                )
            )
        out = []

        for this_res in as_completed(res):
            out.append(this_res.result())

    return out
