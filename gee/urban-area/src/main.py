"""
Code for calculating urban area.
"""
# Copyright 2017 Conservation International
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import json
import random

import ee
from te_algorithms.gee.util import get_coords
from te_algorithms.gee.util import TEImage
from te_algorithms.gee.util import teimage_v1_to_teimage_v2
from te_schemas import results
from te_schemas.schemas import BandInfo


def urban(
    isi_thr,
    ntl_thr,
    wat_thr,
    cap_ope,
    pct_suburban,
    pct_urban,
    un_adju,
    crs,
    geojsons,
    EXECUTION_ID,
    logger,
):
    # Impervious surface index computed by Trends.Earth
    isi_series = (
        ee.ImageCollection("projects/trends_earth/isi_1998_2018_20190403")
        .reduce(ee.Reducer.mean())
        .select(
            [
                "isi1998_mean",
                "isi2000_mean",
                "isi2005_mean",
                "isi2010_mean",
                "isi2015_mean",
                "isi2018_mean",
            ],
            ["isi1998", "isi2000", "isi2005", "isi2010", "isi2015", "isi2018"],
        )
    )
    proj = isi_series.select("isi2000").projection()

    # JRC Global Surface Water Mapping Layers, v1.0 (>20% occurrence)
    water = ee.Image("JRC/GSW1_0/GlobalSurfaceWater").select("occurrence")

    # Define nighttime lights mask from VIIRS Nighttime Day/Night Band
    # Composites Version 1 (Apr 1, 2012 - May 1, 2018)
    ntl = ee.ImageCollection("NOAA/VIIRS/DNB/MONTHLY_V1/VCMCFG")
    ntl = (
        ntl.filterDate(ee.Date("2015-01-01"), ee.Date("2015-12-31"))
        .select(["avg_rad"], ["ntl"])
        .median()
        .clip(
            ee.Geometry.Polygon(
                [-180, 57, 0, 57, 180, 57, 180, -88, 0, -88, -180, -88], None, False
            )
        )
        .unmask(10)
    )

    # Mask urban areas based ntl
    urban98 = (
        isi_series.select("isi1998")
        .gte(isi_thr)
        .unmask(0)
        .where(ntl.lte(-1 + ntl_thr * 31 / 100), 0)
    )
    urban00 = (
        isi_series.select("isi2000")
        .gte(isi_thr)
        .unmask(0)
        .where(ntl.lte(-1 + ntl_thr * 31 / 100), 0)
    )
    urban05 = (
        isi_series.select("isi2005")
        .gte(isi_thr)
        .unmask(0)
        .where(ntl.lte(-1 + ntl_thr * 31 / 100), 0)
    )
    urban10 = (
        isi_series.select("isi2010")
        .gte(isi_thr)
        .unmask(0)
        .where(ntl.lte(-1 + ntl_thr * 31 / 100), 0)
    )
    urban15 = (
        isi_series.select("isi2015")
        .gte(isi_thr)
        .unmask(0)
        .where(ntl.lte(-1 + ntl_thr * 31 / 100), 0)
    )
    urban18 = (
        isi_series.select("isi2018")
        .gte(isi_thr)
        .unmask(0)
        .where(ntl.lte(-1 + ntl_thr * 31 / 100), 0)
    )

    urban_series = (
        (urban98.multiply(100000))
        .add(urban00.multiply(10000))
        .add(urban05.multiply(1000))
        .add(urban10.multiply(100))
        .add(urban15.multiply(10))
        .add(urban18.multiply(1))
    )

    urban_sum = urban98.add(urban00).add(urban05).add(urban10).add(urban15).add(urban18)

    if un_adju:
        # Gridded Population of the World Version 4, UN-Adjusted Population
        # Density
        gpw4_2000 = (
            ee.Image("CIESIN/GPWv4/unwpp-adjusted-population-density/2000")
            .select(["population-density"], ["p2000"])
            .reproject(crs=proj, scale=30)
        )
        gpw4_2005 = (
            ee.Image("CIESIN/GPWv4/unwpp-adjusted-population-density/2005")
            .select(["population-density"], ["p2005"])
            .reproject(crs=proj, scale=30)
        )
        gpw4_2010 = (
            ee.Image("CIESIN/GPWv4/unwpp-adjusted-population-density/2010")
            .select(["population-density"], ["p2010"])
            .reproject(crs=proj, scale=30)
        )
        gpw4_2015 = (
            ee.Image("CIESIN/GPWv4/unwpp-adjusted-population-density/2015")
            .select(["population-density"], ["p2015"])
            .reproject(crs=proj, scale=30)
        )
    else:
        gpw4_2000 = (
            ee.Image("CIESIN/GPWv4/population-density/2000")
            .select(["population-density"], ["p2000"])
            .reproject(crs=proj, scale=30)
        )
        gpw4_2005 = (
            ee.Image("CIESIN/GPWv4/population-density/2005")
            .select(["population-density"], ["p2005"])
            .reproject(crs=proj, scale=30)
        )
        gpw4_2010 = (
            ee.Image("CIESIN/GPWv4/population-density/2010")
            .select(["population-density"], ["p2010"])
            .reproject(crs=proj, scale=30)
        )
        gpw4_2015 = (
            ee.Image("CIESIN/GPWv4/population-density/2015")
            .select(["population-density"], ["p2015"])
            .reproject(crs=proj, scale=30)
        )

    urban_series = (
        urban_series.where(urban_series.eq(0), 0)
        .where(urban_series.eq(1), 0)
        .where(urban_series.eq(10), 1)
        .where(urban_series.eq(11), 4)
        .where(urban_series.eq(100), 0)
        .where(urban_series.eq(101), 3)
        .where(urban_series.eq(110), 3)
        .where(urban_series.eq(111), 3)
        .where(urban_series.eq(1000), 0)
        .where(urban_series.eq(1001), 2)
        .where(urban_series.eq(1010), 2)
        .where(urban_series.eq(1011), 2)
        .where(urban_series.eq(1100), 2)
        .where(urban_series.eq(1101), 2)
        .where(urban_series.eq(1110), 2)
        .where(urban_series.eq(1111), 2)
        .where(urban_series.eq(10000), 0)
        .where(urban_series.eq(10001), 0)
        .where(urban_series.eq(10010), 0)
        .where(urban_series.eq(10011), 1)
        .where(urban_series.eq(10100), 0)
        .where(urban_series.eq(10101), 1)
        .where(urban_series.eq(10110), 1)
        .where(urban_series.eq(10111), 1)
        .where(urban_series.eq(11000), 0)
        .where(urban_series.eq(11001), 1)
        .where(urban_series.eq(11010), 1)
        .where(urban_series.eq(11011), 1)
        .where(urban_series.eq(11100), 1)
        .where(urban_series.eq(11101), 1)
        .where(urban_series.eq(11110), 1)
        .where(urban_series.eq(11111), 1)
        .where(urban_series.gte(100000).And(urban_sum.gte(3)), 1)
        .where(urban_series.gte(100000).And(urban_sum.lte(2)), 0)
        .where(water.gte(wat_thr), -1)
        .reproject(crs=proj, scale=30)
    )

    ## define function to do zonation of cities
    def f_city_zones(built_up, geojson):
        dens = built_up.reduceNeighborhood(
            reducer=ee.Reducer.mean(), kernel=ee.Kernel.circle(564, "meters")
        )
        ##rural built up (-32768 no-data), suburban, urban
        city = (
            ee.Image(10)
            .where(dens.lte(pct_suburban).And(built_up.eq(1)), 3)
            .where(dens.gt(pct_suburban).And(built_up.eq(1)), 2)
            .where(dens.gt(pct_urban).And(built_up.eq(1)), 1)
        )

        dist = city.lte(2).fastDistanceTransform(100).sqrt()

        ## fringe open space, rural built up
        city = city.where(dist.gt(0).And(dist.lte(3)), 4).where(city.eq(3), 3)

        open_space = city.updateMask(city.eq(10)).addBands(ee.Image.pixelArea())
        open_space_poly = open_space.reduceToVectors(
            reducer=ee.Reducer.sum().setOutputs(["area"]),
            geometry=geojson,
            scale=30,
            maxPixels=1e10,
        )

        open_space_img = open_space_poly.reduceToImage(
            properties=["area"], reducer=ee.Reducer.first()
        )
        ## captured open space, rural open space
        city = city.where(
            city.eq(10).And(
                open_space_img.gt(0).And(open_space_img.lte(cap_ope * 10000))
            ),
            5,
        ).where(city.eq(10).And(open_space_img.gt(cap_ope * 10000)), 6)

        return (
            city.where(city.eq(4).And(water.gte(wat_thr)), 7)
            .where(city.eq(5).And(water.gte(wat_thr)), 8)
            .where(city.eq(6).And(water.gte(wat_thr)), 9)
            .where(city.eq(10), -32768)
        )

    logger.debug("Processing geojsons")
    outs = []

    for geojson in geojsons:
        city00 = f_city_zones(urban_series.eq(1), geojson)
        city05 = f_city_zones(urban_series.gte(1).And(urban_series.lte(2)), geojson)
        city10 = f_city_zones(urban_series.gte(1).And(urban_series.lte(3)), geojson)
        city15 = f_city_zones(urban_series.gte(1).And(urban_series.lte(4)), geojson)
        rast_export = (
            city00.addBands(city05)
            .addBands(city10)
            .addBands(city15)
            .addBands(gpw4_2000)
            .addBands(gpw4_2005)
            .addBands(gpw4_2010)
            .addBands(gpw4_2015)
            .addBands(urban_series)
        )
        rast_export = rast_export.unmask(-32768).int16().reproject(crs=proj, scale=30)
        this_out = TEImage(
            rast_export,
            [
                BandInfo("Urban", metadata={"year": 2000}),
                BandInfo("Urban", metadata={"year": 2005}),
                BandInfo("Urban", metadata={"year": 2010}),
                BandInfo("Urban", metadata={"year": 2015}),
                BandInfo("Population", metadata={"year": 2000}),
                BandInfo("Population", metadata={"year": 2005}),
                BandInfo("Population", metadata={"year": 2010}),
                BandInfo("Population", metadata={"year": 2015}),
                BandInfo("Urban series", add_to_map=True),
            ],
        )
        this_out = teimage_v1_to_teimage_v2(this_out)
        outs.append(this_out.export([geojson], "urban", crs, logger, EXECUTION_ID))

    return outs


def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    un_adju = params.get("un_adju", None)
    isi_thr = float(params.get("isi_thr", None))
    ntl_thr = float(params.get("ntl_thr", None))
    wat_thr = float(params.get("wat_thr", None))
    cap_ope = float(params.get("cap_ope", None))
    pct_suburban = float(params.get("pct_suburban", None))
    pct_urban = float(params.get("pct_urban", None))
    geojsons = json.loads(params.get("geojsons", None))
    crs = params.get("crs", None)
    # Check the ENV. Are we running this locally or in prod?

    if params.get("ENV") == "dev":
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get("EXECUTION_ID", None)
    logger.debug(f"Execution ID is {EXECUTION_ID}")

    logger.debug("Checking total area of supplied geojsons:")
    area = 0

    for geojson in geojsons:
        aoi = ee.Geometry.MultiPolygon(get_coords(geojson))
        area += aoi.area().getInfo() / (1000 * 1000)
    # QGIS code limits area of bounding box to 25,000 sq km, so we shouldn't
    # ever have bounding boxes exceeding that area, but add an additional check
    # here (with an error margin of 10,000 sq km...) just in case.

    if area > 35000:
        logger.debug("Area ({:.6n} km sq) is too large - failing task".format(area))
        raise Exception
    else:
        logger.debug("Processing total area of {:.6n} km sq".format(area))

    logger.debug("Running main script.")

    out = urban(
        isi_thr,
        ntl_thr,
        wat_thr,
        cap_ope,
        pct_suburban,
        pct_urban,
        un_adju,
        crs,
        geojsons,
        EXECUTION_ID,
        logger,
    )

    schema = results.RasterResults.Schema()
    logger.debug("Deserializing")
    final_output = schema.load(out[0])

    for o in out[1:]:
        # Ensure uris are included for each geojson if there is more than 1
        this_out = schema.load(o)

        for datatype, raster in this_out.data.items():
            final_output.data[datatype].uri.extend(raster.uri)
    logger.debug("Serializing")
    # Now serialize the output again and return it

    return schema.dump(final_output)
