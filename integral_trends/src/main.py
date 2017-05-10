"""
Code for calculating annual integrated NDVI.
"""
# Copyright 2017 Conservation International


from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import ee
import json

def get_region(geom):
    """Return ee.Geometry from supplied GeoJSON object."""
    poly = get_coords(geom)
    ptype = get_type(geom)
    if ptype.lower() == 'multipolygon':
        region = ee.Geometry.MultiPolygon(poly)
    else:
        region = ee.Geometry.Polygon(poly)
    return region


def get_coords(geojson):
    """."""
    if geojson.get('features') is not None:
        return geojson.get('features')[0].get('geometry').get('coordinates')
    elif geojson.get('geometry') is not None:
        return geojson.get('geometry').get('coordinates')
    else:
        return geojson.get('coordinates')


def get_type(geojson):
    """."""
    if geojson.get('features') is not None:
        return geojson.get('features')[0].get('geometry').get('type')
    elif geojson.get('geometry') is not None:
        return geojson.get('geometry').get('type')
    else:
        return geojson.get('type')


def squaremeters_to_ha(value):
    """."""
    tmp = value/10000.
    return float('{0:4.2f}'.format(tmp))


def mann_kendall_stat(imageCollection):
    """Calculate Mann Kendall's S statistic.

    This function returns the Mann Kendall's S statistic, assuming that n is
    less than 40. The significance of a calculated S statistic is found in
    table A.30 of Nonparametric Statistical Methods, second edition by
    Hollander & Wolfe.

    Args:
        imageCollection: A Google Earth Engine image collection.

    Returns:
        A Google Earth Engine image collection with Mann Kendall statistic for
            each pixel.
    """
    TimeSeriesList = imageCollection.toList(50)
    NumberOfItems = TimeSeriesList.length().getInfo()
    ConcordantArray = []
    DiscordantArray = []
    for k in range(0, NumberOfItems-2):
        CurrentImage = ee.Image(TimeSeriesList.get(k))
        for l in range(k+1, NumberOfItems-1):
            nextImage = ee.Image(TimeSeriesList.get(l))
            Concordant = CurrentImage.lt(nextImage)
            ConcordantArray.append(Concordant)
            Discordant = CurrentImage.gt(nextImage)
            DiscordantArray.append(Discordant)
    ConcordantSum = ee.ImageCollection(ConcordantArray).sum()
    DiscordantSum = ee.ImageCollection(DiscordantArray).sum()
    MKSstat = ConcordantSum.subtract(DiscordantSum)
    return MKSstat

def ndvi_annual_integral(year_start, year_end, geojson):
    """Calculate annual trend of integrated NDVI.

    Calculates the trend of annual integrated NDVI using NDVI data from the
    MODIS Collection 6 MOD13Q1 dataset. Areas where changes are not significant
    are masked out using a Mann-Kendall test.

    Args:
        year_start: The starting year (to define the period the trend is
            calculated over).
        year_end: The ending year (to define the period the trend is
            calculated over).
        geojson: A polygon defining the area of interest.

    Returns:
        Output of google earth engine task.
    """

    region = get_coords(geojson)

    # Load a MODIS NDVI collection 6 MODIS/MOD13Q1
    modis_16d_o = ee.ImageCollection('MODIS/006/MOD13Q1')

    # Function to mask pixels based on quality flags
    def qa_filter(img):
        mask = img.select('SummaryQA')
        mask = mask.where(img.select('SummaryQA').eq(-1), 0)
        mask = mask.where(img.select('SummaryQA').eq(0), 1)
        mask = mask.where(img.select('SummaryQA').eq(1), 1)
        mask = mask.where(img.select('SummaryQA').eq(2), 0)
        mask = mask.where(img.select('SummaryQA').eq(3), 0)
        masked = img.select('NDVI').updateMask(mask)
        return masked

    # Function to integrate observed NDVI datasets at the annual level
    def int_16d_1yr_o(ndvi_coll):
        img_coll = ee.List([])
        for k in range(year_start, year_end):
            ndvi_img = ndvi_coll.select('NDVI').filterDate('{}-01-01'.format(k), '{}-12-31'.format(k)).reduce(ee.Reducer.mean()).multiply(0.0001)
            img = ndvi_img.addBands(ee.Image(k).float()).rename(['ndvi','year']).set({'year': k})
            img_coll = img_coll.add(img)
        return ee.ImageCollection(img_coll)

    # Filter modis collection using the quality filter
    modis_16d_o = modis_16d_o.map(qa_filter)

    # Apply function to compute NDVI annual integrals from 15d observed NDVI data
    ndvi_1yr_o = int_16d_1yr_o(modis_16d_o)

    # Compute linear trend function to predict ndvi based on year (ndvi trend)
    lf_trend = ndvi_1yr_o.select(['year', 'ndvi']).reduce(ee.Reducer.linearFit())

    # Define Kendall parameter values for a significance of 0.05
    period = year_end - year_start + 1
    coefficients = ee.Array([4, 6, 9, 11, 14, 16, 19, 21, 24, 26, 31, 33, 36,
                             40, 43, 47, 50, 54, 59, 63, 66, 70, 75, 79, 84,
                             88, 93, 97, 102, 106, 111, 115, 120, 126, 131,
                             137, 142])
    kendall = coefficients.get([period - 4])

    # Compute Kendall statistics
    mk_trend = mann_kendall_stat(ndvi_1yr_o.select('ndvi'))

    export = {'image': lf_trend.select('scale').where(mk_trend.abs().lte(kendall), -99999).where(lf_trend.select('scale').abs().lte(0.000001), -99999).unmask(-99999),
             'description': 'modis_gee_data_gee_int_trends_{}_{}'.format(year_start, year_end),
             'bucket': 'ldmt',
             'maxPixels': 10000000000,
             'scale': 250,
             'region': region}

    # Export final mosaic to assets
    task = ee.batch.Export.image.toCloudStorage(**export)
    task.start()

    return task

def run(params, logger):
    """."""
    year_start = params.get('year_start', 2003)
    year_end = params.get('year_end', 2015)
    default_poly = json.loads('{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},"geometry":{"type":"Polygon","coordinates":[[[-9.4921875,33.7243396617476],[-9.4921875,39.36827914916014],[2.8125,39.36827914916014],[2.8125,33.7243396617476],[-9.4921875,33.7243396617476]]]}}]}')
    geojson = params.get('geojson', default_poly)

    if not geojson:
        return False

    logger.debug('Done')
    return ndvi_annual_integral(year_start, year_end, geojson)
