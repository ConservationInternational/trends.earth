"""
Code for calculating vegetation productivity trajectory.
"""
# Copyright 2017 Conservation International
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import json
import random
import re
from builtins import str
from builtins import zip

import ee
from te_schemas.schemas import TimeSeries
from te_schemas.schemas import TimeSeriesTable
from te_schemas.schemas import TimeSeriesTableSchema

from te_algorithms.gee.productivity import productivity_series


def zonal_stats(
    geojsons,
    year_initial,
    year_final,
    trajectory_method,
    ndvi_gee_dataset,
    climate_gee_dataset,
    logger,
):
    logger.debug("Entering zonal_stats function.")

    image = (
        productivity_series(
            int(year_initial),
            int(year_final),
            trajectory_method,
            ndvi_gee_dataset,
            climate_gee_dataset,
            logger,
        )
        .select("ndvi")
        .toBands()
    )

    region = ee.Geometry(geojsons)

    scale = ee.Number(image.projection().nominalScale()).getInfo()

    ## This produces an average of the region over the image by year
    ## Source: https://developers.google.com/earth-engine/reducers_reduce_region
    reducers = (
        ee.Reducer.mean()
        .combine(reducer2=ee.Reducer.min(), sharedInputs=True)
        .combine(reducer2=ee.Reducer.max(), sharedInputs=True)
        .combine(reducer2=ee.Reducer.mode(), sharedInputs=True)
        .combine(reducer2=ee.Reducer.stdDev(), sharedInputs=True)
    )
    statsDictionary = image.reduceRegion(
        reducer=reducers, geometry=region, scale=scale, maxPixels=1e13
    )

    logger.debug("Calculating zonal_stats.")
    res = statsDictionary.getInfo()

    logger.debug("Formatting results.")
    res_clean = {}

    years = [*range(year_initial, year_final + 1)]
    for key, value in list(res.items()):
        re_groups = re.search("(\d*)_ndvi_(\w*)", key).groups()
        index = re_groups[0]
        year = years[int(index)]
        field = re_groups[1]

        if field not in res_clean:
            res_clean[field] = {}
            res_clean[field]["value"] = []
            res_clean[field]["year"] = []
        res_clean[field]["value"].append(float(value))
        res_clean[field]["year"].append(int(year))

    logger.debug("Setting up results JSON")
    timeseries = []

    for key in list(res_clean.keys()):
        # Ensure the lists are in chronological order
        year, value = list(
            zip(*sorted(zip(res_clean[key]["year"], res_clean[key]["value"])))
        )
        ts = TimeSeries(list(year), list(value), key)
        timeseries.append(ts)

    timeseries_table = TimeSeriesTable("timeseries", timeseries)
    timeseries_table_schema = TimeSeriesTableSchema()
    json_result = timeseries_table_schema.dump(timeseries_table)

    return json_result


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    geojsons = json.loads(params.get("geojsons"))
    year_initial = int(params.get("year_initial"))
    year_final = int(params.get("year_final"))
    trajectory_method = params.get("trajectory_method")
    ndvi_gee_dataset = params.get("ndvi_gee_dataset")
    climate_gee_dataset = params.get("climate_gee_dataset")

    # Check the ENV. Are we running this locally or in prod?

    if params.get("ENV") == "dev":
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get("EXECUTION_ID", None)
    logger.debug(f"Execution ID is {EXECUTION_ID}")

    logger.debug("Running main script.")
    # TODO: Right now timeseries will only work on the first geojson - this is
    # somewhat ok since for the most part this uses points, but should fix in
    # the future
    json_result = zonal_stats(
        geojsons[0],
        year_initial,
        year_final,
        trajectory_method,
        ndvi_gee_dataset,
        climate_gee_dataset,
        logger,
    )

    return json_result
