"""
Code for calculating all three SDG 15.3.1 sub-indicators.
"""
# Copyright 2017 Conservation International
import random
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor

import ee
from te_algorithms.gdal.land_deg import config
from te_algorithms.gee.download import download
from te_algorithms.gee.land_cover import land_cover
from te_algorithms.gee.productivity import productivity_performance
from te_algorithms.gee.productivity import productivity_state
from te_algorithms.gee.productivity import productivity_trajectory
from te_algorithms.gee.soc import soc
from te_algorithms.gee.util import teimage_v1_to_teimage_v2
from te_schemas import results
from te_schemas.land_cover import LCLegendNesting
from te_schemas.land_cover import LCTransitionDefinitionDeg
from te_schemas.productivity import ProductivityMode


def _run_lc(params, additional_years, logger):
    logger.debug("Running land cover indicator.")
    lc = land_cover(
        params.get("year_initial"),
        params.get("year_final"),
        trans_matrix=LCTransitionDefinitionDeg.Schema().load(
            params.get("trans_matrix")
        ),
        esa_to_custom_nesting=LCLegendNesting.Schema().load(
            params.get("legend_nesting_esa_to_custom")
        ),
        ipcc_nesting=LCLegendNesting.Schema().load(
            params.get("legend_nesting_custom_to_ipcc")
        ),
        additional_years=additional_years,
        logger=logger,
    )
    lc.selectBands(["Land cover (degradation)", "Land cover transitions", "Land cover"])

    return lc


def _run_soc(params, logger):
    logger.debug("Running soil organic carbon indicator.")
    soc_out = soc(
        params.get("year_initial"),
        params.get("year_final"),
        params.get("fl"),
        LCTransitionDefinitionDeg.Schema().load(params.get("trans_matrix")),
        esa_to_custom_nesting=LCLegendNesting.Schema().load(
            params.get("legend_nesting_esa_to_custom")
        ),
        ipcc_nesting=LCLegendNesting.Schema().load(
            params.get("legend_nesting_custom_to_ipcc")
        ),
        dl_annual_lc=False,
        logger=logger,
    )
    soc_out.selectBands(["Soil organic carbon (degradation)", "Soil organic carbon"])

    return soc_out


def run_te_for_period(params, max_workers, EXECUTION_ID, logger):
    """Run indicators using Trends.Earth productivity"""
    proj = ee.ImageCollection(params["population"]["asset"]).toBands().projection()

    prod_params = params.get("productivity")
    prod_asset = prod_params.get("asset_productivity")

    # Need to loop over the geojsons, since performance takes in a
    # geojson.
    res = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for n, geojson in enumerate(params.get("geojsons"), start=1):
            out = productivity_trajectory(
                prod_params.get("traj_year_initial"),
                prod_params.get("traj_year_final"),
                prod_params.get("traj_method"),
                prod_asset,
                prod_params.get("asset_climate"),
                logger,
            )

            # TODO: pass performance a second geojson defining the entire
            # extent of all input geojsons so that the performance is
            # calculated the same over all input areas.
            out.merge(
                productivity_performance(
                    prod_params.get("perf_year_initial"),
                    prod_params.get("perf_year_final"),
                    prod_asset,
                    geojson,
                    logger,
                )
            )

            out.merge(
                productivity_state(
                    prod_params.get("state_year_bl_start"),
                    prod_params.get("state_year_bl_end"),
                    prod_params.get("state_year_tg_start"),
                    prod_params.get("state_year_tg_end"),
                    prod_asset,
                    logger,
                )
            )

            # If the productivity start or end years aren't in the LC period,
            # then need to include additional years in the land cover dataset
            # so that crosstabs can be calculated for land cover class
            lc_years = [
                *range(
                    params.get("land_cover")["year_initial"],
                    params.get("land_cover")["year_final"] + 1,
                )
            ]
            additional_years = []
            prod_year_initial = params.get("productivity")["traj_year_initial"]
            prod_year_final = params.get("productivity")["traj_year_final"]

            if prod_year_initial not in lc_years:
                additional_years.append(prod_year_initial)

            if prod_year_final not in lc_years:
                additional_years.append(prod_year_final)

            out.merge(_run_lc(params.get("land_cover"), additional_years, logger))

            out.merge(_run_soc(params.get("soil_organic_carbon"), logger))

            logger.debug("Setting up layers to add to the map.")
            out.setAddToMap(
                [
                    "Soil organic carbon (degradation)",
                    "Land cover (degradation)",
                    "Productivity trajectory (significance)",
                    "Productivity state (degradation)",
                    "Productivity performance (degradation)",
                ]
            )

            logger.debug("Converting output to TEImageV2 format")

            # Need to use te_image_v2 to support adding another dataset
            # (population) as float32
            out = teimage_v1_to_teimage_v2(out)

            logger.debug("Adding population data")
            # Population needs to be saved as floats
            out.add_image(**_get_population(params.get("population"), logger))

            logger.debug("Exporting results")

            res.append(
                executor.submit(
                    out.export,
                    geojsons=[geojson],
                    task_name="sdg_sub_indicators",
                    crs=params.get("crs"),
                    logger=logger,
                    execution_id=f"{EXECUTION_ID}_{n}",
                    filetype=results.RasterFileType(
                        params.get("filetype", results.RasterFileType.COG.value)
                    ),
                    proj=proj,
                )
            )

    final_output = None
    schema = results.RasterResults.Schema()
    # Deserialize the data that was prepared for output from the
    # productivity functions, so that new urls can be appended if need
    # be from the next result (next geojson)
    final_output = schema.load(res[0].result())
    for n, this_res in enumerate(as_completed(res[1:]), start=1):
        logger.debug(f"Combining main output with output {n}")
        final_output.combine(schema.load(this_res.result()))

    logger.debug("Serializing")
    return schema.dump(final_output)


def _get_population(params, logger):
    """Return WorldPop population data for a given year"""
    logger.debug("Returning population image")
    year = params["year"]

    wp = ee.ImageCollection(params["asset"]).filterDate(
        f"{year}-01-01", f"{year + 1}-01-01"
    )
    wp = (
        wp.select("male")
        .toBands()
        .rename(f"Population_{year}_male")
        .addBands(wp.select("female").toBands().rename(f"Population_{year}_female"))
    )

    return {
        "image": wp,
        "bands": [
            results.Band(
                "Population (number of people)",
                metadata={"year": year, "type": "male", "source": params["source"]},
            ),
            results.Band(
                "Population (number of people)",
                metadata={"year": year, "type": "female", "source": params["source"]},
            ),
        ],
        "datatype": results.DataType.FLOAT32,
    }


def run_precalculated_lpd_for_period(params, EXECUTION_ID, logger):
    """Run indicators using precalculated LPD for productivity"""

    proj = ee.ImageCollection(params["population"]["asset"]).toBands().projection()
    prod_mode = params["productivity"]["mode"]

    if prod_mode == ProductivityMode.JRC_5_CLASS_LPD.value:
        lpd_layer_name = config.JRC_LPD_BAND_NAME
    elif prod_mode == ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value:
        lpd_layer_name = config.FAO_WOCAT_LPD_BAND_NAME
    else:
        raise KeyError

    out = download(
        params.get("productivity").get("asset"),
        lpd_layer_name,
        "one time",
        None,
        None,
        logger,
    )
    lpd_year_initial = params.get("productivity")["year_initial"]
    lpd_year_final = params.get("productivity")["year_final"]
    # Save as int16 to be compatible with other data
    out.image = out.image.int16().rename(
        f"{prod_mode}_{lpd_year_initial}-{lpd_year_final}"
    )
    out.band_info[0].metadata.update(
        {"year_initial": lpd_year_initial, "year_final": lpd_year_final}
    )

    # If the LPD start or end years aren't in the LC period, then need to
    # include additional years in the land cover dataset so that crosstabs can
    # be calculated for LPD by land cover class
    lc_years = [
        *range(
            params.get("land_cover")["year_initial"],
            params.get("land_cover")["year_final"] + 1,
        )
    ]
    additional_years = []

    if lpd_year_initial not in lc_years:
        additional_years.append(lpd_year_initial)

    if lpd_year_final not in lc_years:
        additional_years.append(lpd_year_final)

    out.merge(_run_lc(params.get("land_cover"), additional_years, logger))

    out.merge(_run_soc(params.get("soil_organic_carbon"), logger))

    out.setAddToMap(
        [
            "Soil organic carbon (degradation)",
            "Land cover (degradation)",
            lpd_layer_name,
        ]
    )
    out = teimage_v1_to_teimage_v2(out)

    # Population needs to be saved as floats
    out.add_image(**_get_population(params.get("population"), logger))

    return out.export(
        geojsons=params.get("geojsons"),
        task_name="sdg_sub_indicators",
        crs=params.get("crs"),
        logger=logger,
        execution_id=EXECUTION_ID,
        filetype=results.RasterFileType(
            params.get("filetype", results.RasterFileType.COG.value)
        ),
        proj=proj,
    )


def run_period(params, max_workers, EXECUTION_ID, logger):
    """Run indicators for a given period, using FAO-WOCAT, JRC, or Trends.Earth"""

    if (
        params["productivity"]["mode"]
        == ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value
    ):
        params.update(_gen_metadata_str_te(params))
        out = run_te_for_period(params, max_workers, EXECUTION_ID, logger)
    elif params["productivity"]["mode"] in (
        ProductivityMode.JRC_5_CLASS_LPD.value,
        ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value,
    ):
        params.update(_gen_metadata_str_precalculated_lpd(params))
        out = run_precalculated_lpd_for_period(params, EXECUTION_ID, logger)
    else:
        raise Exception(
            'Unknown productivity mode "{}" chosen'.format(
                params["productivity"]["mode"]
            )
        )

    return out


def _gen_metadata_str_te(params):
    metadata = {
        "visible_metadata": {
            "one liner": f'{params["script"]["name"]} ({params["period"]["name"]}, {params["period"]["year_initial"]}-{params["period"]["year_final"]})',
            "full": f'{params["script"]["name"]}\n'
            f'Period: {params["period"]["name"]} ({params["period"]["year_initial"]}-{params["period"]["year_final"]})'
            f'Productivity {params["productivity"]["mode"]}:\n'
            f'\tTrajectory ({params["productivity"]["traj_year_initial"]} {params["productivity"]["traj_year_final"]}',
        }
    }

    return metadata


def _gen_metadata_str_precalculated_lpd(params):
    metadata = {
        "visible_metadata": {
            "one liner": f'{params["script"]["name"]} ({params["period"]["name"]}, {params["period"]["year_initial"]}-{params["period"]["year_final"]})',
            "full": f'{params["script"]["name"]}\n'
            f'Period: {params["period"]["name"]} ({params["period"]["year_initial"]}-{params["period"]["year_final"]})'
            f'Productivity {params["productivity"]["mode"]}: {params["productivity"]["year_initial"]}-{params["productivity"]["year_final"]}',
        }
    }

    return metadata


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")

    # Check the ENV. Are we running this locally or in prod?

    if params.get("ENV") == "dev":
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get("EXECUTION_ID", None)
    logger.debug(f"Execution ID is {EXECUTION_ID}")

    logger.debug(f"period is {params['period']}")

    max_workers = 4

    return run_period(params, max_workers, EXECUTION_ID, logger)
