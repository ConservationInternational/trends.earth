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

from landdegradation.urban_area import urban_area
from landdegradation.schemas.schemas import CloudResultsSchema

def urban(isi_thr, ntl_thr, wat_thr, aoi_cr, EXECUTION_ID, logger):
	#Impervious surface index computed by Trends.Earth
	isi_series = ee.ImageCollection("projects/trends_earth/isi_20181024_esa").reduce(ee.Reducer.mean()) \
		.select(['isi2000_mean','isi2005_mean','isi2010_mean','isi2015_mean','isi2018_mean'],
		['isi2000','isi2005','isi2010','isi2015','isi2018'])

	#JRC Global Surface Water Mapping Layers, v1.0 (>20% occurrence)
	water = ee.Image("JRC/GSW1_0/GlobalSurfaceWater").select("occurrence")

	#Gridded Population of the World Version 4, UN-Adjusted Population Density
	gpw4_2000 = ee.Image("CIESIN/GPWv4/unwpp-adjusted-population-density/2000").select(["population-density"],["p2000"])
	gpw4_2005 = ee.Image("CIESIN/GPWv4/unwpp-adjusted-population-density/2005").select(["population-density"],["p2005"])
	gpw4_2010 = ee.Image("CIESIN/GPWv4/unwpp-adjusted-population-density/2010").select(["population-density"],["p2010"])
	gpw4_2015 = ee.Image("CIESIN/GPWv4/unwpp-adjusted-population-density/2015").select(["population-density"],["p2015"])

	#VIIRS Nighttime Day/Night Band Composites Version 1 (Apr 1, 2012 - May 1, 2018)
	ntl = ee.ImageCollection("NOAA/VIIRS/DNB/MONTHLY_V1/VCMCFG").filterDate(ee.Date("2018-01-01"), ee.Date("2018-12-31")).select(["avg_rad"],["ntl"]).median()
          
	#DATA FORMATTING FOR EXPORT

	#Mask urban areas based ntl
	urban2000 = isi_series.select("isi2000").gte(isi_thr).unmask(0).where(ntl.lte(ntl_thr),0).multiply(10000)
	urban2005 = isi_series.select("isi2005").gte(isi_thr).unmask(0).where(ntl.lte(ntl_thr),0).multiply(1000)
	urban2010 = isi_series.select("isi2010").gte(isi_thr).unmask(0).where(ntl.lte(ntl_thr),0).multiply(100)
	urban2015 = isi_series.select("isi2015").gte(isi_thr).unmask(0).where(ntl.lte(ntl_thr),0).multiply(10)
	urban2018 = isi_series.select("isi2018").gte(isi_thr).unmask(0).where(ntl.lte(ntl_thr),0).multiply(1)

	urban_series = urban2000.add(urban2005).add(urban2010).add(urban2015).add(urban2018).select(['isi2000'],['urban'])

	urban_series = urban_series.where(urban_series.eq(    0),0) \
                               .where(urban_series.eq(    1),0) \
                               .where(urban_series.eq(   10),0) \
                               .where(urban_series.eq(   11),4) \
                               .where(urban_series.eq(  100),0) \
                               .where(urban_series.eq(  101),3) \
                               .where(urban_series.eq(  110),3) \
                               .where(urban_series.eq(  111),3) \
                               .where(urban_series.eq( 1000),0) \
                               .where(urban_series.eq( 1001),2) \
                               .where(urban_series.eq( 1010),2) \
                               .where(urban_series.eq( 1011),2) \
                               .where(urban_series.eq( 1100),2) \
                               .where(urban_series.eq( 1101),2) \
                               .where(urban_series.eq( 1110),2) \
                               .where(urban_series.eq( 1111),2) \
                               .where(urban_series.eq(10000),0) \
                               .where(urban_series.eq(10001),0) \
                               .where(urban_series.eq(10010),0) \
                               .where(urban_series.eq(10011),1) \
                               .where(urban_series.eq(10100),0) \
                               .where(urban_series.eq(10101),1) \
                               .where(urban_series.eq(10110),1) \
                               .where(urban_series.eq(10111),1) \
                               .where(urban_series.eq(11000),0) \
                               .where(urban_series.eq(11001),1) \
                               .where(urban_series.eq(11010),1) \
                               .where(urban_series.eq(11011),1) \
                               .where(urban_series.eq(11100),1) \
                               .where(urban_series.eq(11101),1) \
                               .where(urban_series.eq(11110),1) \
                               .where(urban_series.eq(11111),1) \
                               .where(water.gte(wat_thr),-32768)

	rast_export = urban_series.addBands(gpw4_2000).addBands(gpw4_2005).addBands(gpw4_2010).addBands(gpw4_2015)

	out = TEImage(rast_export,
                  [BandInfo("Urban (2000)", add_to_map=True, metadata={'year': 2000}),
				   BandInfo("Urban (2005)", metadata={'year': 2005}),
				   BandInfo("Urban (2010)", metadata={'year': 2010}),
				   BandInfo("Urban (2015)", metadata={'year': 2015}),
				   BandInfo("Urban (2018)", add_to_map=True, metadata={'year': 2018}),
                   BandInfo("Population (2000)", add_to_map=True, metadata={'population': 2000}),
                   BandInfo("Population (2005)", metadata={'population': 2005}),
				   BandInfo("Population (2010)", metadata={'population': 2010}),
                   BandInfo("Population (2015)", add_to_map=True, metadata={'population': 2015})])

    out.image = out.image.unmask(-32768).int16()
    return out
  
def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    isi_thr = params.get('isi_thr')
	ntl_thr = params.get('ntl_thr')
	at_thr = params.get('at_thr')
	aoi_cr = params.get('aoi_cr')

    geojsons = json.loads(params.get('geojsons'))
    crs = params.get('crs')

    proj = ee.Image("users/geflanddegradation/toolbox_datasets/urban_series").projection()

    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    logger.debug("Running main script.")
	 
	out = urban(isi_thr, ntl_thr, wat_thr, aoi_cr,
                    EXECUTION_ID, logger)
   
    # Now serialize the output again and return it
    return schema.dump(out)

