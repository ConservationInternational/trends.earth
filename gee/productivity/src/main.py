"""
Code for calculating vegetation productivity.
"""

# Copyright 2017 Conservation International
import json
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

import ee
from te_algorithms.gdal.land_deg import config
from te_algorithms.gee.download import download
from te_algorithms.gee.productivity import (
    calc_prod5,
    productivity_faowocat,
    productivity_performance,
    productivity_state,
    productivity_trajectory,
)
from te_algorithms.gee.util import TEImageV2, teimage_v1_to_teimage_v2
from te_schemas import results
from te_schemas.productivity import ProductivityMode


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    productivity = params.get("productivity")
    prod_mode = productivity.get("mode")
    geojsons = json.loads(params.get("geojsons"))
    crs = params.get("crs")

    # Check the ENV. Are we running this locally or in prod?

    if params.get("ENV") == "dev":
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get("EXECUTION_ID", None)
    logger.debug(f"Execution ID is {EXECUTION_ID}")

    logger.debug("Running productivity indicators.")

    if prod_mode == ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value:
        calc_traj = productivity.get("calc_traj", True)
        calc_state = productivity.get("calc_state", True)
        calc_perf = productivity.get("calc_perf", True)
        traj_year_initial = int(productivity.get("traj_year_initial"))
        traj_year_final = int(productivity.get("traj_year_final"))
        perf_year_initial = int(productivity.get("perf_year_initial"))
        perf_year_final = int(productivity.get("perf_year_final"))
        state_year_bl_start = int(productivity.get("state_year_bl_start"))
        state_year_bl_end = int(productivity.get("state_year_bl_end"))
        state_year_tg_start = int(productivity.get("state_year_tg_start"))
        state_year_tg_end = int(productivity.get("state_year_tg_end"))
        trajectory_method = productivity.get("trajectory_method")
        ndvi_gee_dataset = productivity.get("ndvi_gee_dataset")
        climate_gee_dataset = productivity.get("climate_gee_dataset")

        # Calculate productivity components globally (not per geojson) for unified percentiles
        global_output = None
        proj = ee.Image(ndvi_gee_dataset).projection()

        if calc_traj:
            logger.debug("Calculating productivity trajectory...")
            traj = productivity_trajectory(
                traj_year_initial,
                traj_year_final,
                trajectory_method,
                ndvi_gee_dataset,
                climate_gee_dataset,
                logger,
            )
            global_output = traj

        if calc_perf:
            logger.debug(
                "Calculating productivity performance with unified percentiles across all geojsons..."
            )
            perf = productivity_performance(
                perf_year_initial,
                perf_year_final,
                ndvi_gee_dataset,
                geojsons,  # Pass all geojsons for unified percentile calculation
                logger,
            )

            if not global_output:
                global_output = perf
            else:
                global_output.merge(perf)

        if calc_state:
            logger.debug("Calculating productivity state...")
            state = productivity_state(
                state_year_bl_start,
                state_year_bl_end,
                state_year_tg_start,
                state_year_tg_end,
                ndvi_gee_dataset,
                logger,
            )

            if not global_output:
                global_output = state
            else:
                global_output.merge(state)

        # Calculate 5-class LPD layer if all three sub-indicators were computed
        deg_prod5 = None
        if calc_traj and calc_perf and calc_state:
            logger.debug("Calculating 5-class Land Productivity Dynamics (LPD) layer")
            prod_traj_signif = global_output.getImages(
                ["Productivity trajectory (significance)"],
            )
            prod_perf_deg = global_output.getImages(
                ["Productivity performance (degradation)"],
            )
            prod_state_classes = global_output.getImages(
                ["Productivity state (degradation)"],
            )
            deg_prod5 = calc_prod5(prod_traj_signif, prod_perf_deg, prod_state_classes)
            deg_prod5 = deg_prod5.rename(
                f"{prod_mode}_{traj_year_initial}-{traj_year_final}"
            )

        logger.debug("Converting output to TEImageV2 format")
        global_output = teimage_v1_to_teimage_v2(global_output)

        if deg_prod5 is not None:
            logger.debug("Adding 5-class LPD layer to output")
            prod5_teimage_v2 = TEImageV2()
            prod5_teimage_v2.add_image(
                deg_prod5.unmask(-32768).int16(),
                [
                    results.Band(
                        config.TE_LPD_BAND_NAME,
                        metadata={
                            "year_initial": traj_year_initial,
                            "year_final": traj_year_final,
                        },
                    )
                ],
                results.DataType.INT16,
            )
            global_output.merge(prod5_teimage_v2)

        logger.debug("Exporting global productivity results")
        return global_output.export(
            geojsons=geojsons,
            task_name="productivity",
            crs=crs,
            logger=logger,
            execution_id=EXECUTION_ID,
            proj=proj,
        )

    elif prod_mode == ProductivityMode.JRC_5_CLASS_LPD.value:
        data_source = productivity.get("data_source", "Joint Research Commission (JRC)")
        if data_source == "Joint Research Commission (JRC)":
            lpd_layer_name = config.JRC_LPD_BAND_NAME
        else:
            lpd_layer_name = config.FAO_WOCAT_LPD_BAND_NAME
        prod_asset = productivity.get("asset")
        year_initial = productivity.get("year_initial")
        year_final = productivity.get("year_final")
        out = download(prod_asset, lpd_layer_name, "one time", None, None, logger)
        proj = ee.Image(prod_asset).projection()
        assert len(out.images) == 1, "multiple bands returned - should be 1"
        (image,) = out.images.values()
        image.image = image.image.int16().rename(
            f"{'prod_mode'}_{year_initial}-{year_final}"
        )
        image.bands[0].metadata.update(
            {"year_initial": year_initial, "year_final": year_final}
        )
        return out.export(geojsons, "productivity", crs, logger, EXECUTION_ID, proj)
    elif prod_mode == ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value:
        ndvi_gee_dataset = productivity.get("ndvi_gee_dataset")
        low_biomass = float(productivity.get("low_biomass"))
        high_biomass = float(productivity.get("high_biomass"))
        years_interval = int(productivity.get("years_interval"))
        year_initial = int(productivity.get("year_initial"))
        year_final = int(productivity.get("year_final"))
        modis_mode = productivity.get("modis_mode")

        logger.debug(
            "Running FAO\u2011WOCAT algorithm "
            f"({year_initial}\u2013{year_final}) using {ndvi_gee_dataset}"
        )

        res = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            for idx, geojson in enumerate(geojsons, start=1):
                lpd_img = productivity_faowocat(
                    low_biomass=low_biomass,
                    high_biomass=high_biomass,
                    years_interval=years_interval,
                    modis_mode=modis_mode,
                    prod_asset=ndvi_gee_dataset,
                    logger=logger,
                    year_initial=year_initial,
                    year_final=year_final,
                )

                lpd_img = teimage_v1_to_teimage_v2(lpd_img)

                proj = ee.Image(ndvi_gee_dataset).projection()
                res.append(
                    executor.submit(
                        lpd_img.export,
                        geojsons=[geojson],
                        task_name="productivity",
                        crs=crs,
                        logger=logger,
                        execution_id=f"{EXECUTION_ID}_{idx}",
                        proj=proj,
                    )
                )
        schema = results.RasterResults.Schema()
        final_output = schema.load(res[0].result())
        for n, this_res in enumerate(as_completed(res[1:]), start=1):
            logger.debug(f"Combining FAO‑WOCAT output with AOI {n}")
            final_output.combine(schema.load(this_res.result()))

        logger.debug("Serializing FAO‑WOCAT result")
        return schema.dump(final_output)
    else:
        raise Exception('Unknown productivity mode "{}" chosen'.format(prod_mode))
