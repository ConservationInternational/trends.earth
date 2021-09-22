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
from landdegradation.util import TEImage

from te_schemas.schemas import CloudResultsSchema, BandInfo
from te_schemas.land_cover import LCTransitionDefinitionDeg, LCLegendNesting


def _run_lc(params, logger):
    logger.debug("Running land cover indicator.")
    lc = land_cover(
        params.get('year_initial'),
        params.get('year_final'),
        LCTransitionDefinitionDeg.Schema().load(
            params.get('trans_matrix')
        ),
        LCLegendNesting.Schema().load(
            params.get('legend_nesting')
        ),
        logger
    )
    lc.selectBands(['Land cover (degradation)',
                    'Land cover (7 class)'])

    return lc


def _run_soc(params, logger):
    logger.debug("Running soil organic carbon indicator.")
    soc_out = soc(
        params.get('year_initial'),
        params.get('year_final'),
        params.get('fl'),
        LCTransitionDefinitionDeg.Schema().load(
            params.get('trans_matrix')
        ),
        LCLegendNesting.Schema().load(
            params.get('legend_nesting')
        ),
        False,
        logger
    )
    soc_out.selectBands(['Soil organic carbon (degradation)',
                         'Soil organic carbon'])

    return soc_out


def run_te_for_period(params, max_workers, EXECUTION_ID, logger):
    '''Run indicators using Trends.Earth productivity'''
    prod_params = params.get('productivity')

    prod_asset = prod_params.get('prod_asset')
    proj = ee.Image(prod_asset).projection()

    # Need to loop over the geojsons, since performance takes in a
    # geojson.
    outs = []

    for geojson in params.get('geojsons'):
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            res = []

            res.append(
                executor.submit(
                    productivity_trajectory,
                    prod_params.get('traj_year_initial'),
                    prod_params.get('traj_year_final'),
                    prod_params.get('traj_method'),
                    prod_asset,
                    prod_params.get('climate_asset'),
                    logger
                )
            )

            # TODO: pass performance a second geojson defining the entire
            # extent of all input geojsons so that the performance is
            # calculated the same over all input areas.
            res.append(
                executor.submit(
                    productivity_performance,
                    prod_params.get('perf_year_initial'),
                    prod_params.get('perf_year_final'),
                    prod_asset,
                    geojson,
                    logger
                )
            )

            res.append(
                executor.submit(
                    productivity_state,
                    prod_params.get('state_year_bl_start'),
                    prod_params.get('state_year_bl_end'),
                    prod_params.get('state_year_tg_start'),
                    prod_params.get('state_year_tg_end'),
                    prod_asset,
                    logger
                )
            )

            res.append(
                executor.submit(
                    _run_lc,
                    params.get('land_cover'),
                    logger
                )
            )

            res.append(
                executor.submit(
                    _run_soc,
                    params.get('soil_organic_carbon'),
                    logger
                )
            )

            res.append(
                executor.submit(
                    _get_population,
                    params.get('population'),
                    logger
                )
            )

            res.append(
                executor.submit(
                    _get_spi,
                    params.get('spi'),
                    logger
                )
            )

            out = None
            for this_res in as_completed(res):
                if out is None:
                    out = this_res.result()
                else:
                    out.merge(this_res.result())

        logger.debug("Setting up layers to add to the map.")
        out.setAddToMap(['Soil organic carbon (degradation)',
                         'Land cover (degradation)',
                         'Productivity trajectory (significance)',
                         'Productivity state (degradation)',
                         'Productivity performance (degradation)'])

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



def _get_population(params, logger):
    '''Return worldpop population data for a given year'''
    logger.debug("Returning population image")
    year = params.get('year')

    wp_col = ee.Image("users/geflanddegradation/toolbox_datasets/worldpop_ppp_2000_2020_1km_global")
    wp = wp_col.select(f'p{year}')

    return TEImage(
        wp.unmask(-32768).divide(10).int16(),
        [BandInfo(
            "Population (number of people)",
            metadata={'year': year, 'data source': 'WorldPop', 'scaling': 10}
        )]
    )


def _get_spi(params, logger):
    '''Return SPI image for a particular year and lag'''
    logger.debug("Returning SPI image")
    year = params.get('year')
    lag = params.get('lag')

    spi_series = ee.Image(f'projects/trends_earth/spi/spi_GPCC_monthly_v2020_1971-2019_monthly_gamma_SPI_lag{lag}')
    spi_img = spi_series.select(f'spi_{year}_12')

    return TEImage(
        spi_img.unmask(-32768).int16(),
        [BandInfo(
            "Standardized Precipitation Index (SPI)",
            metadata={'year': year, 'lag': lag, 'data source': 'GPCC'}
        )]
    )


def run_jrc_for_period(params, EXECUTION_ID, logger):
    '''Run indicators using JRC LPD for productivity'''
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

    out.merge(_run_lc(params.get('land_cover'), logger))

    out.merge(_run_soc(params.get('soil_organic_carbon'), logger))

    out.setAddToMap(['Soil organic carbon (degradation)',
                     'Land cover (degradation)',
                     'Land Productivity Dynamics (LPD)'])

    return out.export(
        params.get('geojsons'),
        'sdg_sub_indicators',
        params.get('crs'),
        logger,
        EXECUTION_ID,
        proj
    )

def run_period(params, max_workers, EXECUTION_ID, logger):
    '''Run indicators for a given period, using JRC or Trends.Earth'''

    if params['productivity']['mode'] == 'Trends.Earth productivity':
        out = run_te_for_period(params, max_workers, EXECUTION_ID, logger)
    elif params['productivity']['mode'] == 'JRC LPD':
        out = run_jrc_for_period(params, EXECUTION_ID, logger)
    else:
        raise Exception(
            'Unknown productivity mode "{}" chosen'.format(
                params['productivity']['mode']
            )
        )

    return out


def _gen_metadata_str(params):
    metadata = {
        'visible_metadata': {
            'one liner': f'{params["script"]["name"]} ({params["period"]["name"]}, {params["period"]["year_start"]}-{params["period"]["year_final"]})',
            'full': f'{params["script"]["name"]}\n'
                    f'Period: {params["period"]["name"]} ({params["period"]["year_start"]}-{params["period"]["year_final"]})'
                    f'Productivity {params["productivity"]["mode"]}:\n'
                    f'\tTrajectory ({params["productivity"]["traj_year_initial"]} {params["productivity"]["traj_year_final"]}'
        }
    }
    return metadata


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")

    # Check the ENV. Are we running this locally or in prod?

    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    max_workers = 4

    # Add metadata strings into parameters
    params.update(_gen_metadata_str(params))

    out = run_period(params, max_workers, EXECUTION_ID, logger)

    return out
