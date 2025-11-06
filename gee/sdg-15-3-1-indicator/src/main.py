"""
Code for calculating final SDG 15.3.1 indicator.

Optional productivity bands:
  To include additional productivity bands (trajectory trend, performance ratio/units,
  state classes, NDVI means) in the output, set the parameter 'include_productivity_bands'
  to True in the input parameters. This option is only available when using Trends.Earth
  productivity calculations (ProductivityMode.TRENDS_EARTH_5_CLASS_LPD).

  Additional bands included:
  - Productivity trajectory (significance): Significance values from productivity trajectory analysis
  - Productivity state (degradation): Degradation values from productivity state analysis
  - Productivity performance (degradation): Degradation values from productivity performance analysis

  Example usage:
    params = {
        'include_productivity_bands': True,  # Enable additional productivity bands
        'baseline_period': {
            'productivity': {
                'mode': ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value,
                # ... other productivity params
            },
            # ... other baseline period params
        },
        # ... other params
    }
    result = run(params, logger)
"""

# Copyright 2017 Conservation International
import random

import ee
from te_algorithms.gdal.land_deg import config
from te_algorithms.gee.land_cover import land_cover_deg
from te_algorithms.gee.productivity import (
    calc_prod3,
    calc_prod5,
    productivity_faowocat,
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


def _calc_deg_sdg(deg_prod5, deg_lc, deg_soc):
    deg_prod3 = calc_prod3(deg_prod5)
    deg_sdg = deg_prod3.where(deg_lc.eq(-1).Or(deg_soc.lt(-10)), -1)
    deg_sdg = deg_sdg.where(deg_sdg.eq(0).And(deg_lc.eq(1).Or(deg_soc.gt(10))), 1)
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


def _setup_output(prod5, lc, soc, sdg, params, extra_prod_bands=None):
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

    # Build the base image with core bands
    base_image = sdg.addBands(prod5).addBands(lc).addBands(soc)

    # Build the base band info list
    base_band_infos = [
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
                "year_initial": lpd_year_initial,
                "year_final": lpd_year_final,
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
    ]

    # Add extra productivity bands if provided and if include_productivity_bands is enabled
    include_productivity_bands = params.get("include_productivity_bands", False)
    if include_productivity_bands and extra_prod_bands is not None:
        # Add the extra productivity bands to the image
        for band_data in extra_prod_bands:
            base_image = base_image.addBands(band_data["image"])
            base_band_infos.append(band_data["band_info"])

    out = TEImage(
        base_image.unmask(-32768).int16(),
        base_band_infos,
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
    deg_prod5 = calc_prod5(prod_traj_signif, prod_perf_deg, prod_state_classes)
    deg_lc = _run_lc_deg(params.get("land_cover"), logger)
    deg_soc = _run_soc_deg(params.get("soil_organic_carbon"), logger)
    deg_sdg = _calc_deg_sdg(deg_prod5, deg_lc, deg_soc)

    # Collect extra productivity bands if include_productivity_bands is enabled
    extra_prod_bands = None
    include_productivity_bands = params.get("include_productivity_bands", False)
    if include_productivity_bands:
        logger.debug("Including additional productivity bands in output")
        extra_prod_bands = []

        # Get the three core productivity bands: significance, state degradation, and performance degradation
        # These are the same bands used in setAddToMap for the sub-indicators script

        # Get trajectory significance band (already extracted above)
        if prod_traj_signif:
            extra_prod_bands.append(
                {
                    "image": prod_traj_signif[0],
                    "band_info": BandInfo(
                        config.TRAJ_BAND_NAME,
                        add_to_map=False,
                        metadata={
                            "year_initial": prod_params.get("traj_year_initial"),
                            "year_final": prod_params.get("traj_year_final"),
                        },
                    ),
                }
            )

        # Get performance degradation band (already extracted above)
        if prod_perf_deg:
            extra_prod_bands.append(
                {
                    "image": prod_perf_deg[0],
                    "band_info": BandInfo(
                        config.PERF_BAND_NAME,
                        add_to_map=False,
                        metadata={
                            "year_initial": prod_params.get("perf_year_initial"),
                            "year_final": prod_params.get("perf_year_final"),
                        },
                    ),
                }
            )

        # Get state degradation band (already extracted above)
        if prod_state_classes:
            extra_prod_bands.append(
                {
                    "image": prod_state_classes[0],
                    "band_info": BandInfo(
                        config.STATE_BAND_NAME,
                        add_to_map=False,
                        metadata={
                            "year_bl_start": prod_params.get("state_year_bl_start"),
                            "year_bl_end": prod_params.get("state_year_bl_end"),
                            "year_tg_start": prod_params.get("state_year_tg_start"),
                            "year_tg_end": prod_params.get("state_year_tg_end"),
                        },
                    ),
                }
            )

        logger.debug(
            f"Added {len(extra_prod_bands)} extra productivity bands to output"
        )

    return _setup_output(deg_prod5, deg_lc, deg_soc, deg_sdg, params, extra_prod_bands)


def _run_fao_wocat_period(params, logger):
    """Run FAO-WOCAT productivity calculations for a given period"""
    logger.debug("Starting _run_fao_wocat_period processing")
    prod_params = params.get("productivity")

    ndvi_gee_dataset = prod_params.get("ndvi_gee_dataset")
    low_biomass = float(prod_params.get("low_biomass", 0.4))
    high_biomass = float(prod_params.get("high_biomass", 0.7))
    years_interval = int(prod_params.get("years_interval", 3))
    year_initial = int(prod_params.get("year_initial"))
    year_final = int(prod_params.get("year_final"))
    modis_mode = prod_params.get("modis_mode", "MannKendal + MTID")

    logger.debug(f"Computing FAO-WOCAT productivity ({year_initial}-{year_final})...")
    logger.debug(f"Using dataset: {ndvi_gee_dataset}")
    logger.debug(
        f"Parameters: low_biomass={low_biomass}, high_biomass={high_biomass}, years_interval={years_interval}"
    )

    fao_wocat_result = productivity_faowocat(
        low_biomass=low_biomass,
        high_biomass=high_biomass,
        years_interval=years_interval,
        modis_mode=modis_mode,
        prod_asset=ndvi_gee_dataset,
        logger=logger,
        year_initial=year_initial,
        year_final=year_final,
    )

    # Extract the productivity degradation layer (5-class LPD)
    deg_prod5 = fao_wocat_result.getImages(config.FAO_WOCAT_LPD_BAND_NAME)
    if not deg_prod5:
        raise RuntimeError(
            "FAO-WOCAT productivity calculation did not produce expected LPD band"
        )

    # Calculate land cover and SOC degradation
    deg_lc = _run_lc_deg(params.get("land_cover"), logger)
    deg_soc = _run_soc_deg(params.get("soil_organic_carbon"), logger)
    deg_sdg = _calc_deg_sdg(deg_prod5, deg_lc, deg_soc)

    # For FAO-WOCAT, no extra productivity bands are available
    if params.get("include_productivity_bands", False):
        logger.warning(
            "include_productivity_bands parameter ignored for FAO-WOCAT mode. "
            "Extra productivity bands are only available with Trends.Earth productivity calculations."
        )

    return _setup_output(deg_prod5, deg_lc, deg_soc, deg_sdg, params, None)


def _run_jrc_period(params, logger):
    """Run JRC precalculated productivity for a given period"""
    logger.debug("Starting _run_jrc_period processing")
    prod_params = params.get("productivity")

    # Get JRC asset
    jrc_asset = prod_params.get("asset")
    logger.debug(f"Using JRC asset: {jrc_asset}")

    # Load precalculated JRC LPD data
    deg_prod5 = ee.Image(jrc_asset)

    # Calculate land cover and SOC degradation
    deg_lc = _run_lc_deg(params.get("land_cover"), logger)
    deg_soc = _run_soc_deg(params.get("soil_organic_carbon"), logger)
    deg_sdg = _calc_deg_sdg(deg_prod5, deg_lc, deg_soc)

    # For JRC precalculated LPD, no extra productivity bands are available
    if params.get("include_productivity_bands", False):
        logger.warning(
            "include_productivity_bands parameter ignored for JRC mode. "
            "Extra productivity bands are only available with Trends.Earth productivity calculations."
        )

    return _setup_output(deg_prod5, deg_lc, deg_soc, deg_sdg, params, None)


def _get_sdg(out):
    # _run_te_period returns a TEImageV2, so the getImages function returns a list of images
    sdg_image = out.getImages(config.SDG_BAND_NAME)
    assert len(sdg_image) == 1
    return sdg_image[0]


def _get_lc_deg(out):
    # _run_te_period returns a TEImageV2, so the getImages function returns a list of images
    sdg_image = out.getImages(config.LC_DEG_BAND_NAME)
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
    LC_DEG_BAND_NAME
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


def run_fao_wocat(params, EXECUTION_ID, logger):
    """Run indicators using FAO-WOCAT productivity calculations"""
    # Use NDVI dataset for projection
    proj = ee.Image(
        params["baseline_period"]["productivity"]["ndvi_gee_dataset"]
    ).projection()

    logger.debug("Running FAO-WOCAT productivity calculations")
    out = _run_fao_wocat_period(params["baseline_period"], logger)
    baseline_sdg = _get_sdg(out)
    baseline_year_initial = params["baseline_period"]["period"]["year_initial"]
    baseline_year_final = params["baseline_period"]["period"]["year_final"]

    for period_params in params["status_periods"]:
        period_out = _run_fao_wocat_period(period_params, logger)

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


def run_jrc(params, EXECUTION_ID, logger):
    """Run indicators using JRC precalculated LPD for productivity"""
    logger.debug("Running JRC precalculated productivity")
    out = _run_jrc_period(params["baseline_period"], logger)
    baseline_sdg = _get_sdg(out)
    # JRC layer is at 1km - assign output resolution that of land cover data (~300m)
    proj = _get_lc_deg(out).projection()
    baseline_year_initial = params["baseline_period"]["period"]["year_initial"]
    baseline_year_final = params["baseline_period"]["period"]["year_final"]

    for period_params in params["status_periods"]:
        period_out = _run_jrc_period(period_params, logger)

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
    prod_mode = baseline_params["productivity"]["mode"]

    if prod_mode == ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value:
        out = run_te(params, EXECUTION_ID, logger)
    elif prod_mode == ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value:
        out = run_fao_wocat(params, EXECUTION_ID, logger)
    elif prod_mode == ProductivityMode.JRC_5_CLASS_LPD.value:
        out = run_jrc(params, EXECUTION_ID, logger)
    else:
        raise Exception(f'Unknown productivity mode "{prod_mode}" chosen')

    return out


def run(params, logger):
    """Run SDG 15.3.1 indicator calculation.

    Args:
        params: Dictionary of parameters including:
            - include_productivity_bands (bool, optional): If True, includes additional
              productivity bands in the output. Only works with Trends.Earth productivity
              calculations. Default is False.
        logger: Logger instance for debug output.

    Returns:
        TEImageV2 object containing SDG indicator and related bands.
    """
    logger.debug("Loading parameters.")

    # Check the ENV. Are we running this locally or in prod?

    if params.get("ENV") == "dev":
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get("EXECUTION_ID", None)
    logger.debug(f"Execution ID is {EXECUTION_ID}")

    return run_all_periods(params, EXECUTION_ID, logger)
