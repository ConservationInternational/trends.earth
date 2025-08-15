"""
Code for calculating all three SDG 15.3.1 sub-indicators.
"""

# Copyright 2017 Conservation International
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

import ee
from te_algorithms.gdal.land_deg import config
from te_algorithms.gee.download import download
from te_algorithms.gee.land_cover import land_cover
from te_algorithms.gee.productivity import (
    productivity_faowocat,
    productivity_performance,
    productivity_state,
    productivity_trajectory,
)
from te_algorithms.gee.soc import soc
from te_algorithms.gee.util import teimage_v1_to_teimage_v2
from te_schemas import results
from te_schemas.land_cover import LCLegendNesting, LCTransitionDefinitionDeg
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
        fake_data=params.get("fake_data", False),
    )
    lc.selectBands(["Land cover (degradation)", "Land cover transitions", "Land cover"])

    return teimage_v1_to_teimage_v2(lc)


def _run_soc(params, logger):
    logger.debug("Running soil organic carbon indicator.")
    soc_out = soc(
        params.get("year_initial"),
        params.get("year_final"),
        params.get("fl"),
        esa_to_custom_nesting=LCLegendNesting.Schema().load(
            params.get("legend_nesting_esa_to_custom")
        ),
        ipcc_nesting=LCLegendNesting.Schema().load(
            params.get("legend_nesting_custom_to_ipcc")
        ),
        annual_lc=False,
        annual_soc=False,
        logger=logger,
        fake_data=params.get("fake_data", False),
    )
    soc_out.selectBands(["Soil organic carbon (degradation)", "Soil organic carbon"])

    return teimage_v1_to_teimage_v2(soc_out)


def _run_faowocat_for_period(params, max_workers, execution_id, logger):
    """Run indicators using on‑the‑fly FAO‑WOCAT 5‑class LPD algorithm."""

    logger.debug("Setting up FAO‑WOCAT parameters")
    prod_params = params.get("productivity")

    ndvi_ds = prod_params.get("ndvi_gee_dataset")
    low_bio = prod_params.get("low_biomass")
    high_bio = prod_params.get("high_biomass")
    years_interval = prod_params.get("years_interval")
    modis_mode = prod_params.get("modis_mode")
    lpd_year_initial = int(prod_params.get("year_initial"))
    lpd_year_final = int(prod_params.get("year_final"))

    proj = ee.Image(ndvi_ds).projection()

    res = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for idx, geojson in enumerate(params.get("geojsons"), start=1):
            logger.debug(f"Calculating FAO‑WOCAT LPD for AOI {idx}")
            out = productivity_faowocat(
                low_biomass=low_bio,
                high_biomass=high_bio,
                years_interval=years_interval,
                modis_mode=modis_mode,
                prod_asset=ndvi_ds,
                logger=logger,
                year_initial=lpd_year_initial,
                year_final=lpd_year_final,
            )

            out = teimage_v1_to_teimage_v2(out)

            if params.get("annual_lc"):
                lc_years = list(
                    range(
                        params["land_cover"]["year_initial"],
                        params["land_cover"]["year_final"] + 1,
                    )
                )
            else:
                lc_years = [
                    params["land_cover"]["year_initial"],
                    params["land_cover"]["year_final"],
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
                    "Productivity trajectory (significance)",
                    "Productivity state (degradation)",
                    config.FAO_WOCAT_LPD_BAND_NAME,
                ]
            )

            # Population (stored as float)
            out.add_image(**_get_population(params.get("population"), logger))

            out.rmDuplicates()

            logger.debug("Exporting FAO‑WOCAT result")
            res.append(
                executor.submit(
                    out.export,
                    geojsons=[geojson],
                    task_name="sdg_sub_indicators",
                    crs=params.get("crs"),
                    logger=logger,
                    execution_id=f"{execution_id}_{idx}",
                    filetype=results.RasterFileType(
                        params.get("filetype", results.RasterFileType.COG.value)
                    ),
                    proj=proj,
                )
            )

    schema = results.RasterResults.Schema()
    final_output = schema.load(res[0].result())
    for n, this_res in enumerate(as_completed(res[1:]), start=1):
        logger.debug(f"Combining FAO‑WOCAT output with AOI {n}")
        final_output.combine(schema.load(this_res.result()))

    logger.debug("Serializing FAO‑WOCAT combined result")
    return schema.dump(final_output)


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

            if params.get("annual_lc"):
                lc_years = [
                    *range(
                        params.get("land_cover")["year_initial"],
                        params.get("land_cover")["year_final"] + 1,
                    )
                ]
            else:
                lc_years = [
                    params.get("land_cover")["year_initial"],
                    params.get("land_cover")["year_final"],
                ]

            # If the productivity start or end years aren't in the LC period,
            # then need to include additional years in the land cover dataset
            # so that crosstabs can be calculated for land cover class
            additional_years = []
            prod_year_initial = params.get("productivity")["traj_year_initial"]
            prod_year_final = params.get("productivity")["traj_year_final"]
            if prod_year_initial not in lc_years:
                additional_years.append(prod_year_initial)
            if prod_year_final not in lc_years:
                additional_years.append(prod_year_final)

            logger.debug("Converting output to TEImageV2 format")
            out = teimage_v1_to_teimage_v2(out)

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

            logger.debug("Adding population data")
            # Population needs to be saved as floats
            out.add_image(**_get_population(params.get("population"), logger))

            logger.debug("Filtering duplicate layers")
            out.rmDuplicates()

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
    asset = params["asset"]

    # Try to get data for the requested year first
    wp = ee.ImageCollection(asset).filterDate(f"{year}-01-01", f"{year + 1}-01-01")

    if params.get("fake_data", False):
        # Check if data exists for the requested year
        data_exists = wp.size().gt(0)

        # If no data exists and fake_data is enabled, find closest available year
        def use_closest_year():
            # Get all available images and extract years
            all_images = ee.ImageCollection(asset)

            def extract_year(image):
                date = ee.Date(image.get("system:time_start"))
                return image.set("year", date.get("year"))

            # Get all available years, sorted
            images_with_years = all_images.map(extract_year)
            available_years = (
                images_with_years.distinct("year").aggregate_array("year").sort()
            )

            # Find the closest year to our target
            target_year = ee.Number(year)
            differences = available_years.map(
                lambda y: ee.Number(y).subtract(target_year).abs()
            )
            min_diff = differences.reduce(ee.Reducer.min())
            closest_year_index = differences.indexOf(min_diff)
            closest_year = available_years.get(closest_year_index)

            # Log the substitution
            logger.warning(
                f"Population data for year {year} not available. "
                f"Using closest available year {closest_year.getInfo()}"
            )

            # Return collection filtered to closest year
            return ee.ImageCollection(asset).filter(
                ee.Filter.calendarRange(closest_year, closest_year, "year")
            )

        # Use conditional logic to select appropriate data
        wp = ee.ImageCollection(ee.Algorithms.If(data_exists, wp, use_closest_year()))

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
    lpd_image = list(out.images.values())[0]
    lpd_image.image = lpd_image.image.int16().rename(
        f"{prod_mode}_{lpd_year_initial}-{lpd_year_final}"
    )
    lpd_image.bands[0].metadata.update(
        {"year_initial": lpd_year_initial, "year_final": lpd_year_final}
    )

    if params.get("annual_lc"):
        lc_years = [
            *range(
                params.get("land_cover")["year_initial"],
                params.get("land_cover")["year_final"] + 1,
            )
        ]
    else:
        lc_years = [
            params.get("land_cover")["year_initial"],
            params.get("land_cover")["year_final"],
        ]

    # If the LPD start or end years aren't in the LC period, then need to
    # include additional years in the land cover dataset so that crosstabs can
    # be calculated for LPD by land cover class
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
    elif params["productivity"]["mode"] == ProductivityMode.JRC_5_CLASS_LPD.value:
        params.update(_gen_metadata_str_precalculated_lpd(params))
        out = run_precalculated_lpd_for_period(params, EXECUTION_ID, logger)
    elif params["productivity"]["mode"] == ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value:
        params.update(_gen_metadata_str_faowocat(params))
        out = _run_faowocat_for_period(params, max_workers, EXECUTION_ID, logger)
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
            "one liner": f"{params['script']['name']} ({params['period']['name']}, {params['period']['year_initial']}-{params['period']['year_final']})",
            "full": f"{params['script']['name']}\n"
            f"Period: {params['period']['name']} ({params['period']['year_initial']}-{params['period']['year_final']})"
            f"Productivity {params['productivity']['mode']}:\n"
            f"\tTrajectory ({params['productivity']['traj_year_initial']} {params['productivity']['traj_year_final']}",
        }
    }

    return metadata


def _gen_metadata_str_precalculated_lpd(params):
    metadata = {
        "visible_metadata": {
            "one liner": f"{params['script']['name']} ({params['period']['name']}, {params['period']['year_initial']}-{params['period']['year_final']})",
            "full": f"{params['script']['name']}\n"
            f"Period: {params['period']['name']} ({params['period']['year_initial']}-{params['period']['year_final']})"
            f"Productivity {params['productivity']['mode']}: {params['productivity']['year_initial']}-{params['productivity']['year_final']}",
        }
    }

    return metadata


def _gen_metadata_str_faowocat(params):
    years_interval = params["productivity"]["years_interval"]
    metadata = {
        "visible_metadata": {
            "one liner": f"{params['script']['name']} ({params['period']['name']}, 2001-{2001 + years_interval})",
            "full": (
                f"{params['script']['name']}\n"
                f"Period: {params['period']['name']} (2001-{2001 + years_interval})"
                f"Productivity {params['productivity']['mode']}: 2001-{2001 + years_interval}"
            ),
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
