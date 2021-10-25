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

from te_algorithms.gee.productivity import (
    productivity_trajectory,
    productivity_performance,
    productivity_state
)
from te_algorithms.gee.land_cover import land_cover
from te_algorithms.gee.soc import soc
from te_algorithms.gee.download import download
from te_algorithms.gee.util import TEImage

from te_schemas.schemas import CloudResultsSchema, BandInfo
from te_schemas.land_cover import LCTransitionDefinitionDeg, LCLegendNesting


def _run_lc(params, additional_years, logger):
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
        additional_years,
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

    for geojson_num, geojson in enumerate(params.get('geojsons')):
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
                    [],
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
                    proj,
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
                str(EXECUTION_ID) + str(geojson_num),
                proj
            )
        )

    schema = CloudResultsSchema()
    logger.debug("Deserializing")
    final_output = schema.load(outs[0])

    for o in outs[1:]:
        this_out = schema.load(o)
        final_output.urls.extend(this_out.urls)
    logger.debug("Serializing")
    # Now serialize the output again so the remaining layers can be
    # added to it

    return schema.dump(final_output)


def _get_population(params, proj, logger):
    '''Return worldpop population data for a given year'''
    logger.debug("Returning population image")
    year = params['year']

    wp = ee.Image(params['population_asset']).select(f'p{year}')
    wp = wp.select(f'p{year}')
    # Convert to population density per sq km (ee.image.pixelArea gives area in 
    # sq meters, so need to convert). Then scale by 10 so max densities will 
    # fit in an int16
    wp = wp.divide(ee.Image.pixelArea()).multiply(1000*1000).divide(10).int16()
    wp = wp.reduceResolution(
        reducer=ee.Reducer.first(), maxPixels=1024
    ).reproject(proj)

    return TEImage(
        wp,
        [BandInfo(
            "Population (density, persons per sq km / 10)",
            metadata={
                'year': year,
                'data_source': params['population_source_name'],
                'scaling': .1
            }
        )]
    )


def run_jrc_for_period(params, EXECUTION_ID, logger):
    '''Run indicators using JRC LPD for productivity'''
    prod_asset = params.get('productivity').get('prod_asset')
    proj = ee.Image(prod_asset).projection()
    out = download(
        prod_asset,
        'Land Productivity Dynamics (from JRC)',
        'one time',
        None,
        None,
        logger
    )
    lpd_year_initial = params.get('productivity')['year_initial']
    lpd_year_final = params.get('productivity')['year_final']
    # Save as int16 to be compatible with other data
    out.image = out.image.int16().rename(
        f'JRC_LPD_{lpd_year_initial}-{lpd_year_final}')
    out.band_info[0].metadata.update({
        'year_initial': lpd_year_initial,
        'year_final': lpd_year_final
    })

    # If the LPD start or end years aren't in the LC period, then need to 
    # include additional years in the land cover dataset so that crosstabs can 
    # be calculated for LPD by land cover class
    lc_years = [*range(
        params.get('land_cover')['year_initial'],
        params.get('land_cover')['year_final'] + 1
    )]
    additional_years = []
    if lpd_year_initial not in lc_years:
        additional_years.append(lpd_year_initial)
    if lpd_year_final not in lc_years:
        additional_years.append(lpd_year_final)

    out.merge(_run_lc(params.get('land_cover'), additional_years, logger))

    out.merge(_run_soc(params.get('soil_organic_carbon'), logger))

    out.merge(_get_population, params.get('population'), proj, logger)

    out.setAddToMap(['Soil organic carbon (degradation)',
                     'Land cover (degradation)',
                     'Land Productivity Dynamics (LPD)'])

    return out.export(
        geojsons=params.get('geojsons'),
        task_name='sdg_sub_indicators',
        crs=params.get('crs'),
        logger=logger,
        execution_id=EXECUTION_ID,
        proj=proj
    )


def run_period(params, max_workers, EXECUTION_ID, logger):
    '''Run indicators for a given period, using JRC or Trends.Earth'''

    if params['productivity']['mode'] == 'Trends.Earth productivity':
        params.update(_gen_metadata_str_te(params))
        out = run_te_for_period(params, max_workers, EXECUTION_ID, logger)
    elif params['productivity']['mode'] == 'JRC LPD':
        params.update(_gen_metadata_str_jrc_lpd(params))
        out = run_jrc_for_period(params, EXECUTION_ID, logger)
    else:
        raise Exception(
            'Unknown productivity mode "{}" chosen'.format(
                params['productivity']['mode']
            )
        )

    return out


def _gen_metadata_str_te(params):
    metadata = {
        'visible_metadata': {
            'one liner': f'{params["script"]["name"]} ({params["period"]["name"]}, {params["period"]["year_initial"]}-{params["period"]["year_final"]})',
            'full': f'{params["script"]["name"]}\n'
                    f'Period: {params["period"]["name"]} ({params["period"]["year_initial"]}-{params["period"]["year_final"]})'
                    f'Productivity {params["productivity"]["mode"]}:\n'
                    f'\tTrajectory ({params["productivity"]["traj_year_initial"]} {params["productivity"]["traj_year_final"]}'
        }
    }
    return metadata


def _gen_metadata_str_jrc_lpd(params):
    metadata = {
        'visible_metadata': {
            'one liner': f'{params["script"]["name"]} ({params["period"]["name"]}, {params["period"]["year_initial"]}-{params["period"]["year_final"]})',
            'full': f'{params["script"]["name"]}\n'
                    f'Period: {params["period"]["name"]} ({params["period"]["year_initial"]}-{params["period"]["year_final"]})'
                    f'Productivity {params["productivity"]["mode"]}: {params["productivity"]["year_initial"]}-{params["productivity"]["year_final"]}'
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

    out = run_period(params, max_workers, EXECUTION_ID, logger)

    return out
