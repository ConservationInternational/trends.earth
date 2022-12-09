"""
Code for calculating vegetation productivity.
"""
# Copyright 2017 Conservation International
import json
import random
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor

import ee
from te_algorithms.gdal.land_deg import config
from te_algorithms.gee.download import download
from te_algorithms.gee.productivity import productivity_performance
from te_algorithms.gee.productivity import productivity_state
from te_algorithms.gee.productivity import productivity_trajectory
from te_algorithms.gee.util import teimage_v1_to_teimage_v2
from te_schemas import results
from te_schemas.productivity import ProductivityMode


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    prod_mode = params.get("prod_mode")
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
        calc_traj = params.get("calc_traj")
        calc_state = params.get("calc_state")
        calc_perf = params.get("calc_perf")
        prod_traj_year_initial = int(params.get("prod_traj_year_initial"))
        prod_traj_year_final = int(params.get("prod_traj_year_final"))
        prod_perf_year_initial = int(params.get("prod_perf_year_initial"))
        prod_perf_year_final = int(params.get("prod_perf_year_final"))
        prod_state_year_bl_start = int(params.get("prod_state_year_bl_start"))
        prod_state_year_bl_end = int(params.get("prod_state_year_bl_end"))
        prod_state_year_tg_start = int(params.get("prod_state_year_tg_start"))
        prod_state_year_tg_end = int(params.get("prod_state_year_tg_end"))
        prod_traj_method = params.get("trajectory_method")
        ndvi_gee_dataset = params.get("ndvi_gee_dataset")
        climate_gee_dataset = params.get("climate_gee_dataset")

        res = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            for n, geojson in enumerate(geojsons, start=1):
                this_out = None

                if calc_traj:
                    traj = productivity_trajectory(
                        int(prod_traj_year_initial),
                        int(prod_traj_year_final),
                        prod_traj_method,
                        ndvi_gee_dataset,
                        climate_gee_dataset,
                        logger,
                    )

                    if not this_out:
                        this_out = traj

                if calc_perf:
                    perf = productivity_performance(
                        prod_perf_year_initial,
                        prod_perf_year_final,
                        ndvi_gee_dataset,
                        geojson,
                        logger,
                    )

                    if not this_out:
                        this_out = perf
                    else:
                        this_out.merge(perf)

                if calc_state:
                    state = productivity_state(
                        prod_state_year_bl_start,
                        prod_state_year_bl_end,
                        prod_state_year_tg_start,
                        prod_state_year_tg_end,
                        ndvi_gee_dataset,
                        logger,
                    )

                    if not this_out:
                        this_out = state
                    else:
                        this_out.merge(state)

                logger.debug("Converting output to TEImageV2 format")
                this_out = teimage_v1_to_teimage_v2(this_out)
                proj = ee.Image(ndvi_gee_dataset).projection()
                res.append(
                    executor.submit(
                        this_out.export,
                        geojsons=[geojson],
                        task_name="productivity",
                        crs=crs,
                        logger=logger,
                        execution_id=str(EXECUTION_ID) + str(n),
                        proj=proj,
                    )
                )
        final_output = None
        schema = results.RasterResults.Schema()
        for n, this_res in enumerate(as_completed(res), start=1):
            if final_output is None:
                # Deserialize the data that was prepared for output from the
                # productivity functions, so that new urls can be appended if need
                # be from the next result (next geojson)
                final_output = schema.load(this_res.result())
            else:
                logger.debug(f"Combining main output with output {n}")
                final_output.combine(schema.load(this_res.result()))
        logger.debug("Serializing")
        return schema.dump(final_output)

    elif prod_mode in (
        ProductivityMode.JRC_5_CLASS_LPD.value,
        ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value,
    ):
        if prod_mode == ProductivityMode.JRC_5_CLASS_LPD.value:
            lpd_layer_name = config.JRC_LPD_BAND_NAME
        elif prod_mode == ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value:
            lpd_layer_name = config.FAO_WOCAT_LPD_BAND_NAME
        else:
            raise KeyError
        prod_asset = params.get("prod_asset")
        year_initial = params.get("year_initial")
        year_final = params.get("year_final")
        out = download(prod_asset, lpd_layer_name, "one time", None, None, logger)
        proj = ee.Image(prod_asset).projection()
        out.image = out.image.int16().rename(
            f"{'prod_mode'}_{year_initial}-{year_final}"
        )
        out.band_info[0].metadata.update(
            {"year_initial": year_initial, "year_final": year_final}
        )

        logger.debug("Converting output to TEImageV2 format")
        out = teimage_v1_to_teimage_v2(out)

        return out.export(geojsons, "productivity", crs, logger, EXECUTION_ID, proj)
    else:
        raise Exception('Unknown productivity mode "{}" chosen'.format(prod_mode))
