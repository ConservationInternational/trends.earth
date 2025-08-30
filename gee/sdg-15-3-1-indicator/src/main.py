"""
Code for calculating final SDG 15.3.1 indicator.
"""

# Copyright 2017 Conservation International
import random

import ee
from te_algorithms.gdal.land_deg import config
from te_algorithms.gee.land_cover import land_cover_deg
from te_algorithms.gee.productivity import (
    productivity_performance,
    productivity_state,
    productivity_trajectory,
)
from te_algorithms.gee.soc import soc_deg
from te_algorithms.gee.util import TEImage, teimage_v1_to_teimage_v2
from te_schemas import results
from te_schemas.land_cover import LCLegendNesting, LCTransitionDefinitionDeg
from te_schemas.productivity import ProductivityMode
from te_schemas.schemas import BandInfo

NODATA_VALUE = -32768


def _run_lc_deg(params, logger):
    logger.debug("Running land cover indicator.")
    return land_cover_deg(
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
        logger=logger,
        fake_data=params.get("fake_data", False),
    )


def _run_soc_deg(params, logger):
    logger.debug("Running soil organic carbon indicator.")
    return soc_deg(
        params.get("year_initial"),
        params.get("year_final"),
        params.get("fl"),
        esa_to_custom_nesting=LCLegendNesting.Schema().load(
            params.get("legend_nesting_esa_to_custom")
        ),
        ipcc_nesting=LCLegendNesting.Schema().load(
            params.get("legend_nesting_custom_to_ipcc")
        ),
        logger=logger,
        fake_data=params.get("fake_data", False),
    )


def _calc_prod5(traj_signif, perf_deg, state_classes):
    # Trajectory significance layer is coded as:
    # -3: 99% signif decline
    # -2: 95% signif decline
    # -1: 90% signif decline
    #  0: stable
    #  1: 90% signif increase
    #  2: 95% signif increase
    #  3: 99% signif increase
    # -1 and 1 are not signif at 95%, so stable
    traj_deg = (
        traj_signif.where(traj_signif.gte(-1).And(traj_signif.lte(1)), 0)
        .where(traj_signif.gte(-3).And(traj_signif.lt(-1)), -1)
        .where(traj_signif.gt(1).And(traj_signif.lte(3)), 1)
    )

    # Recode state into deg, stable, imp. Note the >= -10 is so no data
    # isn't coded as degradation. More than two changes in class is defined
    # as degradation in state.
    state_deg = (
        state_classes.where(state_classes.gt(-2).And(state_classes.lt(2)), 0)
        .where(state_classes.gte(-10).And(state_classes.lte(-2)), -1)
        .where(state_classes.gte(2), 1)
    )

    return (
        traj_deg.where(traj_deg.eq(-1), 1)
        .where(traj_deg.eq(0), 4)
        .where(traj_deg.eq(1), 5)
        .where(
            traj_deg.eq(0).And(state_deg.eq(0)).And(perf_deg.eq(-1)),
            3,
        )
        .where(
            traj_deg.eq(1).And(state_deg.eq(-1)).And(perf_deg.eq(-1)),
            2,
        )
        .where(
            traj_deg.eq(0).And(state_deg.eq(-1)).And(perf_deg.eq(0)),
            2,
        )
        .where(
            traj_deg.eq(0).And(state_deg.eq(-1)).And(perf_deg.eq(-1)),
            1,
        )
        .where(
            traj_deg.eq(NODATA_VALUE)
            .Or(state_deg.eq(NODATA_VALUE))
            .Or(perf_deg.eq(NODATA_VALUE)),
            NODATA_VALUE,
        )
    )


def _calc_prod3(prod5):
    return (
        prod5.where(prod5.eq(1).Or(prod5.eq(2)), -1)
        .where(prod5.eq(3).Or(prod5.eq(4)), 0)
        .where(prod5.eq(5), 1)
    )


def _calc_deg_sdg(deg_prod5, deg_lc, deg_soc):
    deg_prod3 = _calc_prod3(deg_prod5)
    deg_sdg = deg_prod3.where(deg_lc.eq(-1).Or(deg_soc.eq(-1)), -1)
    deg_sdg = deg_sdg.where(deg_sdg.eq(0).And(deg_lc.eq(1).Or(deg_soc.eq(1))), 1)
    deg_sdg = deg_sdg.where(
        deg_prod3.eq(NODATA_VALUE)
        .Or(deg_lc.eq(NODATA_VALUE))
        .Or(deg_soc.eq(NODATA_VALUE)),
        NODATA_VALUE,
    )
    return deg_sdg


def _calc_sdg_status(sdg_bl, sdg_tg, baseline_year_initial, period_year_final):
    return (
        (
            ee.Image(-32768)
            .where(sdg_bl.eq(-1).And(sdg_tg.eq(-1)), 1)
            .where(sdg_bl.eq(0).And(sdg_tg.eq(-1)), 2)
            .where(sdg_bl.eq(1).And(sdg_tg.eq(-1)), 2)
            .where(sdg_bl.eq(-1).And(sdg_tg.eq(0)), 3)
            .where(sdg_bl.eq(0).And(sdg_tg.eq(0)), 4)
            .where(sdg_bl.eq(1).And(sdg_tg.eq(0)), 5)
            .where(sdg_bl.eq(-1).And(sdg_tg.eq(1)), 6)
            .where(sdg_bl.eq(0).And(sdg_tg.eq(1)), 6)
            .where(sdg_bl.eq(1).And(sdg_tg.eq(1)), 7)
        )
        .rename(
            f"SDG_Indicator_15_3_1_Status_{baseline_year_initial}-{period_year_final}"
        )
        .int16()
    )


def _setup_output(prod5, lc, soc, sdg, params):
    prod_mode = params["productivity"]["mode"]
    if prod_mode == ProductivityMode.JRC_5_CLASS_LPD.value:
        lpd_band_name = config.JRC_LPD_BAND_NAME
        lpd_year_initial = params.get("productivity")["year_initial"]
        lpd_year_final = params.get("productivity")["year_final"]
    elif prod_mode == ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value:
        lpd_band_name = config.FAO_WOCAT_LPD_BAND_NAME
        lpd_year_initial = params.get("productivity")["year_initial"]
        lpd_year_final = params.get("productivity")["year_final"]
    elif prod_mode == ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value:
        lpd_band_name = config.TE_LPD_BAND_NAME
        lpd_year_initial = params.get("productivity")["traj_year_initial"]
        lpd_year_final = params.get("productivity")["traj_year_final"]
    else:
        raise KeyError

    prod5 = prod5.rename(f"{prod_mode}_{lpd_year_initial}-{lpd_year_final}")

    lc_year_initial = params.get("land_cover")["year_initial"]
    lc_year_final = params.get("land_cover")["year_final"]
    lc = lc.rename(f"Land_cover_degradation_{lc_year_initial}-{lc_year_final}")

    soc_year_initial = params.get("soil_organic_carbon")["year_initial"]
    soc_year_final = params.get("soil_organic_carbon")["year_final"]
    soc = soc.rename(f"SOC_degradation_{soc_year_initial}-{soc_year_final}")

    sdg = sdg.rename(f"SDG_Indicator_15_3_1_{lpd_year_initial}-{lpd_year_final}")

    out = TEImage(
        sdg.addBands(prod5).addBands(lc).addBands(soc).unmask(-32768).int16(),
        [
            BandInfo(
                config.SDG_BAND_NAME,
                add_to_map=True,
                metadata={
                    "year_initial": params["period"]["year_initial"],
                    "year_final": params["period"]["year_final"],
                },
            ),
            BandInfo(
                lpd_band_name,
                add_to_map=False,
                metadata={
                    "year_initial": params["productivity"]["traj_year_initial"],
                    "year_final": params["productivity"]["traj_year_final"],
                },
            ),
            BandInfo(
                config.LC_DEG_BAND_NAME,
                add_to_map=False,
                metadata={
                    "year_initial": params["land_cover"]["year_initial"],
                    "year_final": params["land_cover"]["year_final"],
                },
            ),
            BandInfo(
                config.SOC_DEG_BAND_NAME,
                add_to_map=False,
                metadata={
                    "year_initial": params["soil_organic_carbon"]["year_initial"],
                    "year_final": params["soil_organic_carbon"]["year_final"],
                },
            ),
        ],
    )

    out = teimage_v1_to_teimage_v2(out)

    return out


def _run_te_period(params, all_geojsons, logger):
    """Run Trends.Earth productivity calculations for a given period"""
    logger.debug("Starting _run_te_period processing")
    prod_params = params.get("productivity")
    prod_asset = prod_params.get("asset_productivity")

    logger.debug("Computing productivity trajectory...")
    out = productivity_trajectory(
        prod_params.get("traj_year_initial"),
        prod_params.get("traj_year_final"),
        prod_params.get("traj_method"),
        prod_asset,
        prod_params.get("asset_climate"),
        logger,
    )

    logger.debug("Computing productivity performance...")
    logger.debug(
        f"Performance period: {prod_params.get('perf_year_initial')}-{prod_params.get('perf_year_final')}"
    )

    try:
        perf_result = productivity_performance(
            prod_params.get("perf_year_initial"),
            prod_params.get("perf_year_final"),
            prod_asset,
            all_geojsons,  # Use all geojsons for unified percentile calculation
            logger,
        )
        logger.debug("Productivity performance computation completed successfully")
        out.merge(perf_result)
    except Exception as e:
        logger.error(f"Productivity performance computation failed: {e}")
        raise

    logger.debug("Computing productivity state...")
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

    prod_traj_signif = out.getImages(
        ["Productivity trajectory (significance)"],
    )
    prod_perf_deg = out.getImages(
        ["Productivity performance (degradation)"],
    )
    prod_state_classes = out.getImages(
        ["Productivity state (degradation)"],
    )

    ### Calculate productivity trend degradation
    deg_prod5 = _calc_prod5(prod_traj_signif, prod_perf_deg, prod_state_classes)
    deg_lc = _run_lc_deg(params.get("land_cover"), logger)
    deg_soc = _run_soc_deg(params.get("soil_organic_carbon"), logger)
    deg_sdg = _calc_deg_sdg(deg_prod5, deg_lc, deg_soc)

    return _setup_output(deg_prod5, deg_lc, deg_soc, deg_sdg, params)


def _get_sdg(out):
    # _run_te_period returns a TEImageV2, so the getImages function returns a list of images
    sdg_image = out.getImages(config.SDG_BAND_NAME)
    assert len(sdg_image) == 1
    return sdg_image[0]


def run_te(params, EXECUTION_ID, logger):
    """Run indicators using Trends.Earth productivity"""
    proj = ee.Image(
        params["baseline_period"]["productivity"]["asset_productivity"]
    ).projection()

    all_geojsons = params.get("geojsons")
    logger.debug(f"Using unified percentiles across {len(all_geojsons)} geojson areas")

    out = _run_te_period(params["baseline_period"], all_geojsons, logger)
    baseline_sdg = _get_sdg(out)
    baseline_year_initial = params["baseline_period"]["period"]["year_initial"]
    baseline_year_final = params["baseline_period"]["period"]["year_final"]

    for period_params in params["status_periods"]:
        period_out = _run_te_period(period_params, all_geojsons, logger)

        period_out.add_image(
            _calc_sdg_status(
                baseline_sdg,
                _get_sdg(period_out),
                baseline_year_initial,
                period_params["period"]["year_final"],
            ),
            [
                results.Band(
                    name=config.SDG_STATUS_BAND_NAME,
                    add_to_map=True,
                    metadata={
                        "baseline_year_initial": baseline_year_initial,
                        "baseline_year_final": baseline_year_final,
                        "reporting_year_initial": period_params["period"][
                            "year_initial"
                        ],
                        "reporting_year_final": period_params["period"]["year_final"],
                    },
                )
            ],
        )
        out.merge(period_out)

    return out.export(
        geojsons=params.get("geojsons"),
        task_name="sdg_indicator",
        crs=params.get("crs"),
        logger=logger,
        execution_id=EXECUTION_ID,
        filetype=results.RasterFileType(
            params.get("filetype", results.RasterFileType.COG.value)
        ),
        proj=proj,
    )


def _run_precalculated_lpd_period(params, logger):
    deg_prod5 = ee.Image(params.get("productivity").get("asset"))
    deg_lc = _run_lc_deg(params.get("land_cover"), logger)
    deg_soc = _run_soc_deg(params.get("soil_organic_carbon"), logger)
    deg_sdg = _calc_deg_sdg(deg_prod5, deg_lc, deg_soc)

    return _setup_output(deg_prod5, deg_lc, deg_soc, deg_sdg, params)


def run_precalculated_lpd(params, EXECUTION_ID, logger):
    """Run indicators using precalculated LPD for productivity"""
    proj = ee.Image(params["baseline_period"]["productivity"]["asset"]).projection()

    out = _run_precalculated_lpd_period(params["baseline_period"], logger)
    baseline_sdg = _get_sdg(out)
    baseline_year_initial = params["baseline_period"]["period"]["year_initial"]
    baseline_year_final = params["baseline_period"]["period"]["year_final"]
    for period_params in params["status_periods"]:
        period_out = _run_precalculated_lpd_period(period_params, logger)

        period_out.add_image(
            _calc_sdg_status(
                baseline_sdg,
                _get_sdg(period_out),
                baseline_year_initial,
                period_params["period"]["year_final"],
            ),
            [
                results.Band(
                    name=config.SDG_STATUS_BAND_NAME,
                    add_to_map=True,
                    metadata={
                        "baseline_year_initial": baseline_year_initial,
                        "baseline_year_final": baseline_year_final,
                        "reporting_year_initial": period_params["period"][
                            "year_initial"
                        ],
                        "reporting_year_final": period_params["period"]["year_final"],
                    },
                )
            ],
        )
        out.merge(period_out)

    return out.export(
        geojsons=params.get("geojsons"),
        task_name="sdg_indicator",
        crs=params.get("crs"),
        logger=logger,
        execution_id=EXECUTION_ID,
        filetype=results.RasterFileType(
            params.get("filetype", results.RasterFileType.COG.value)
        ),
        proj=proj,
    )


def run_all_periods(params, EXECUTION_ID, logger):
    """Run indicators for a given period, using FAO-WOCAT, JRC, or Trends.Earth"""

    baseline_params = params["baseline_period"]

    if (
        baseline_params["productivity"]["mode"]
        == ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value
    ):
        out = run_te(params, EXECUTION_ID, logger)
    elif baseline_params["productivity"]["mode"] in (
        ProductivityMode.JRC_5_CLASS_LPD.value,
        ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value,
    ):
        out = run_precalculated_lpd(params, EXECUTION_ID, logger)
    else:
        raise Exception(
            'Unknown productivity mode "{}" chosen'.format(
                params["productivity"]["mode"]
            )
        )

    return out


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")

    # Check the ENV. Are we running this locally or in prod?

    if params.get("ENV") == "dev":
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get("EXECUTION_ID", None)
    logger.debug(f"Execution ID is {EXECUTION_ID}")

    return run_all_periods(params, EXECUTION_ID, logger)
