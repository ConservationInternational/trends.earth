"""
Code for calculating urban area.
"""
# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import random
import json

import ee

from landdegradation.util import get_coords, TEImage
from landdegradation.urban_area import urban_area
from landdegradation.schemas.schemas import BandInfo, CloudResultsSchema

def urban(isi_thr, ntl_thr, wat_thr, cap_ope, crs, geojsons, EXECUTION_ID, 
        logger):
    # Impervious surface index computed by Trends.Earth
    isi_series = ee.ImageCollection("projects/trends_earth/isi_20181024_esa").reduce(ee.Reducer.mean()) \
        .select(['isi2000_mean', 'isi2005_mean', 'isi2010_mean', 'isi2015_mean', 'isi2018_mean'],
        ['isi2000', 'isi2005', 'isi2010', 'isi2015', 'isi2018'])

    # JRC Global Surface Water Mapping Layers, v1.0 (>20% occurrence)
    water = ee.Image("JRC/GSW1_0/GlobalSurfaceWater").select("occurrence")

    # Define nighttime lights mask from VIIRS Nighttime Day/Night Band 
    # Composites Version 1 (Apr 1, 2012 - May 1, 2018)
    ntl = ee.ImageCollection("NOAA/VIIRS/DNB/MONTHLY_V1/VCMCFG")
    ntl = ntl.filterDate(ee.Date("2015-01-01"), ee.Date("2015-12-31")).select(["avg_rad"], ["ntl"]).median() \
            .clip(ee.Geometry.Polygon([-180, 57, 0, 57, 180, 57, 180, -88, 0, -88, -180, -88], None, False)).unmask(10)
          
    # Mask urban areas based ntl
    urban00 = isi_series.select("isi2000").gte(isi_thr).unmask(0).where(ntl.lte(ntl_thr), 0).multiply(10000)
    urban05 = isi_series.select("isi2005").gte(isi_thr).unmask(0).where(ntl.lte(ntl_thr), 0).multiply(1000)
    urban10 = isi_series.select("isi2010").gte(isi_thr).unmask(0).where(ntl.lte(ntl_thr), 0).multiply(100)
    urban15 = isi_series.select("isi2015").gte(isi_thr).unmask(0).where(ntl.lte(ntl_thr), 0).multiply(10)
    urban18 = isi_series.select("isi2018").gte(isi_thr).unmask(0).where(ntl.lte(ntl_thr), 0).multiply(1)

    urban_series = urban00.add(urban05).add(urban10).add(urban15).add(urban18)
    proj = urban_series.projection()

    # Gridded Population of the World Version 4, UN-Adjusted Population Density
    gpw4_2000 = ee.Image("CIESIN/GPWv4/unwpp-adjusted-population-density/2000").select(["population-density"], ["p2000"]).reproject(crs=proj)
    gpw4_2005 = ee.Image("CIESIN/GPWv4/unwpp-adjusted-population-density/2005").select(["population-density"], ["p2005"]).reproject(crs=proj)
    gpw4_2010 = ee.Image("CIESIN/GPWv4/unwpp-adjusted-population-density/2010").select(["population-density"], ["p2010"]).reproject(crs=proj)
    gpw4_2015 = ee.Image("CIESIN/GPWv4/unwpp-adjusted-population-density/2015").select(["population-density"], ["p2015"]).reproject(crs=proj)

    urban_series = urban_series.where(urban_series.eq(0), 0) \
            .where(urban_series.eq(    1), 0) \
            .where(urban_series.eq(   10), 0) \
            .where(urban_series.eq(   11), 4) \
            .where(urban_series.eq(  100), 0) \
            .where(urban_series.eq(  101), 3) \
            .where(urban_series.eq(  110), 3) \
            .where(urban_series.eq(  111), 3) \
            .where(urban_series.eq( 1000), 0) \
            .where(urban_series.eq( 1001), 2) \
            .where(urban_series.eq( 1010), 2) \
            .where(urban_series.eq( 1011), 2) \
            .where(urban_series.eq( 1100), 2) \
            .where(urban_series.eq( 1101), 2) \
            .where(urban_series.eq( 1110), 2) \
            .where(urban_series.eq( 1111), 2) \
            .where(urban_series.eq(10000), 0) \
            .where(urban_series.eq(10001), 0) \
            .where(urban_series.eq(10010), 0) \
            .where(urban_series.eq(10011), 1) \
            .where(urban_series.eq(10100), 0) \
            .where(urban_series.eq(10101), 1) \
            .where(urban_series.eq(10110), 1) \
            .where(urban_series.eq(10111), 1) \
            .where(urban_series.eq(11000), 0) \
            .where(urban_series.eq(11001), 1) \
            .where(urban_series.eq(11010), 1) \
            .where(urban_series.eq(11011), 1) \
            .where(urban_series.eq(11100), 1) \
            .where(urban_series.eq(11101), 1) \
            .where(urban_series.eq(11110), 1) \
            .where(urban_series.eq(11111), 1) \
            .where(water.gte(wat_thr), -32768)

    ## define function to do zonation of cities
    def f_city_zones(built_up, geojson):
        dens = built_up.reduceNeighborhood(reducer=ee.Reducer.mean(), kernel=ee.Kernel.circle(1000, "meters"))
        ##rural built up (-32768 no-data), suburban, urban
        city = ee.Image(10).where(dens.lte(0.25).And(built_up.eq(1)), 3) \
                .where(dens.gt(0.25).And(built_up.eq(1)), 2) \
                .where(dens.gt(0.50).And(built_up.eq(1)), 1) 
  
        dist = city.lte(2).fastDistanceTransform(100).sqrt()

        ## fringe open space, rural built up
        city = city.where(dist.gt(0).And(dist.lte(3)), 4) \
                .where(city.eq(3), 3)
  
        open_space = city.updateMask(city.eq(10)).addBands(ee.Image.pixelArea())
        open_space_poly = open_space.reduceToVectors(
            reducer=ee.Reducer.sum().setOutputs(['area']), 
            geometry=geojson,
            scale=30,               
            maxPixels=1e10)
      
        open_space_img = open_space_poly.reduceToImage(properties=['area'], reducer=ee.Reducer.first())
        ## captured open space, rural open space
        city = city.where(city.eq(10).And(open_space_img.gt(0).And(open_space_img.lte(cap_ope*10000))), 5) \
                .where(city.eq(10).And(open_space_img.gt(cap_ope*10000)), 6)

        return city.where(city.eq(4).And(water.gte(wat_thr)), 7) \
                .where(city.eq(5).And(water.gte(wat_thr)), 8) \
                .where(city.eq(6).And(water.gte(wat_thr)), 9) \
                .where(city.eq(10), -32768)

    logger.debug("Processing geojsons")
    outs = []
    for geojson in geojsons:
        city00 = f_city_zones(urban_series.eq(1), geojson)
        city05 = f_city_zones(urban_series.gte(1).And(urban_series.lte(2)), geojson)
        city10 = f_city_zones(urban_series.gte(1).And(urban_series.lte(3)), geojson)
        city15 = f_city_zones(urban_series.gte(1).And(urban_series.lte(4)), geojson)
        rast_export = urban_series.addBands(city00).addBands(city05).addBands(city10).addBands(city15) \
                .addBands(gpw4_2000).addBands(gpw4_2005).addBands(gpw4_2010).addBands(gpw4_2015)
        rast_export = rast_export.unmask(-32768).int16()
        this_out = TEImage(rast_export,
            [BandInfo("Urban series", add_to_map=True),
             BandInfo("Urban", add_to_map=True, metadata={'year': 2000}),
             BandInfo("Urban", metadata={'year': 2005}),
             BandInfo("Urban", metadata={'year': 2010}),
             BandInfo("Urban", add_to_map=True, metadata={'year': 2015}),
             BandInfo("Population", add_to_map=True, metadata={'year': 2000}),
             BandInfo("Population", metadata={'year': 2005}),
             BandInfo("Population", metadata={'year': 2010}),
             BandInfo("Population", add_to_map=True, metadata={'year': 2015})])
        outs.append(this_out.export([geojson], 'urban', crs, logger, EXECUTION_ID, proj))
    
    return outs

def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    un_adju = bool(params.get('un_adju', None))
    isi_thr = float(params.get('isi_thr', None))
    ntl_thr = float(params.get('ntl_thr', None))
    wat_thr = float(params.get('wat_thr', None))
    cap_ope = float(params.get('cap_ope', None))
    geojsons = json.loads(params.get('geojsons', None))
    crs = params.get('crs', None)
    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)
        
    logger.debug("Running main script.")
    
    out = urban(isi_thr, ntl_thr, wat_thr, cap_ope, crs, geojsons, 
                EXECUTION_ID, logger)

    schema = CloudResultsSchema()
    logger.debug("Deserializing")
    final_output = schema.load(out[0])
    for o in out[1:]:
        this_out = schema.load(o)
        final_output.urls.extend(this_out.urls)
    logger.debug("Serializing")
    # Now serialize the output again and return it
    return schema.dump(final_output)
