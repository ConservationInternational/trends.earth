# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import re
import json
import datetime as dt
import random
import json
import tempfile
import hashlib
import pathlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib import request

import ee
from google.cloud import storage

# Turn off overly informative debug messages
import logging
mpl_logger = logging.getLogger('matplotlib')
mpl_logger.setLevel(logging.WARNING)
pil_logger = logging.getLogger('PIL.PngImagePlugin')
pil_logger.setLevel(logging.WARNING)

from PIL import Image

import numpy as np

import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.colors as colors
from matplotlib_scalebar.scalebar import ScaleBar

import pandas as pd

from landdegradation.schemas.schemas import Url, ImageryPNG, \
        ImageryPNGSchema


class InvalidParameter(Exception):
    pass


# Bucket where results will be uploaded (should be publicly readable)
BUCKET = 'ldmt'
# Bounding box side in meters
BOX_SIDE = 10000

# A lock to ensure multiple matplotlib plots aren't generated at once - 
# necessary due to matplotlib bug that leads to strange errors when plots are 
# generated and saved to PNG in parallel
PLOT_LOCK = threading.Lock()


def upload_to_google_cloud(client, f):
    b = client.get_bucket(BUCKET)
    blob = b.blob(os.path.basename(f))
    blob.upload_from_filename(f)
    return 'https://storage.googleapis.com/{}/{}'.format(BUCKET, os.path.basename(f))


def get_hash(filename):
    with open(filename, 'rb') as f:
       return hashlib.md5(f.read()).hexdigest()


# Dictionary to remap from ESA CCI to 7 classes - used for landtrend_plot
remap_dict = {'0': '0',
              '50': '1',
              '60': '1',
              '61': '1',
              '62': '1',
              '70': '1',
              '71': '1',
              '72': '1',
              '80': '1',
              '81': '1',
              '82': '1',
              '90': '1',
              '100': '1',
              '160': '1',
              '170': '4',
              '110': '2',
              '120': '2',
              '121': '2',
              '122': '2',
              '130': '2',
              '140': '2',
              '150': '2',
              '151': '2',
              '152': '2',
              '153': '2',
              '40': '2',
              '10': '3',
              '11': '3',
              '12': '3',
              '20': '3',
              '30': '3',
              '180': '4',
              '190': '5',
              '200': '6',
              '201': '6',
              '202': '6',
              '220': '6',
              '210': '7'}

remap_dict = {0: 0,
              50: 1,
              60: 1,
              61: 1,
              62: 1,
              70: 1,
              71: 1,
              72: 1,
              80: 1,
              81: 1,
              82: 1,
              90: 1,
              100: 1,
              160: 1,
              170: 4,
              110: 2,
              120: 2,
              121: 2,
              122: 2,
              130: 2,
              140: 2,
              150: 2,
              151: 2,
              152: 2,
              153: 2,
              40: 2,
              10: 3,
              11: 3,
              12: 3,
              20: 3,
              30: 3,
              180: 4,
              190: 5,
              200: 6,
              201: 6,
              202: 6,
              220: 6,
              210: 7}

# Class names and color codes
classes = pd.DataFrame(data={'Label': ["No data", "Forest", "Grassland", "Cropland",
                                       "Wetland", "Artificial", "Bare", "Water"],
                             'Code' : [0, 1, 2, 3, 4, 5, 6, 7],
                             'Color' : ["#000000", "#787F1B", "#FFAC42", "#FFFB6E",
                                        "#00DB84", "#E60017", "#FFF3D7", "#0053C4"]})

te_logo = Image.open(os.path.join(pathlib.Path(__file__).parent.absolute(), 
                                 'trends_earth_logo_bl_print.png'))

def plot_image_to_file(d, title, legend=None):
    PLOT_LOCK.acquire()

    fig = plt.figure(constrained_layout=False, figsize=(15, 11.28), dpi=100)
    ax = fig.add_subplot()
    ax.set_title(title, {'fontsize' :28})
    ax.set_axis_off()
    img = ax.imshow(d)
    scalebar = ScaleBar(35, location=3, box_color='white') 
    plt.gca().add_artist(scalebar)

    ax_img = fig.add_axes([0.15, 0.75, 0.21, 0.2], anchor='NW')
    ax_img.imshow(te_logo)
    ax_img.axis('off')

    if legend:
        ax_legend = fig.add_axes([0.63, 0.02, 0.22, 0.2], anchor='SE')
        ax_legend.imshow(legend)
        ax_legend.axis('off')

    plt.tight_layout()
    f = tempfile.NamedTemporaryFile(suffix='.png').name
    plt.savefig(f, bbox_inches='tight')

    PLOT_LOCK.release()

    return f


###############################################################################
# Code for landtrendplot

def landtrend_get_data(year_start, year_end, geojson):
    # geospatial datasets 
    lcover = "users/geflanddegradation/toolbox_datasets/lcov_esacc_1992_2018"
    vegindex = "users/geflanddegradation/toolbox_datasets/ndvi_modis_2001_2019"
    precip = "users/geflanddegradation/toolbox_datasets/prec_chirps_1981_2019"
    
    point = ee.Geometry(geojson)

    # sets time series of interest
    lcov = ee.Image(lcover).select(ee.List.sequence(year_start - 1992, 26, 1))    
    ndvi = ee.Image(vegindex).select(ee.List.sequence(year_start - 2001, year_end - 2001, 1))
    prec = ee.Image(precip).select(ee.List.sequence(year_start - 1981, year_end - 1981, 1))

    # retrieves value of the pixel that intesects coord_point
    values_lcov = lcov.reduceRegion(ee.Reducer.toList(), point, 1)
    values_ndvi = ndvi.reduceRegion(ee.Reducer.toList(), point, 1)
    values_prec = prec.reduceRegion(ee.Reducer.toList(), point, 1)

    with ThreadPoolExecutor(max_workers=4) as executor:
        res = []
        for b, img in [('land_cover', values_lcov),
                       ('ndvi', values_ndvi),
                       ('precipitation', values_prec)]:
            res.append(executor.submit((lambda b, img: {b: img.getInfo()}), b, img))
        out = {}
        for this_res in as_completed(res):
            out.update(this_res.result())

    ts = []
    for key in out.keys():   
        d = list((int(k.replace('y', '')), int(v[0])) for k, v in out[key].items())
        # Ensure the data is chronological
        d = sorted(d, key=lambda x: x[0]) 
        years = list(x[0] for x in d)
        data = list(x[1] for x in d)
        ts.append(pd.DataFrame(data={key: data}, index=years))
    
    # Join all the timeseries pandas dataframes together
    out = ts[0]
    for this_ts in ts[1:]:
        out = out.join(this_ts, how='outer')
    
    # Recode the ESA codes to IPCC 7 classes
    for n in range(len(out.index)):
        esa_code = out.land_cover.iloc[n]
        if not np.isnan(esa_code):
            out.land_cover.iloc[n] = remap_dict[esa_code]
        
    return out

def landtrend_make_plot(d, year_start, year_end):
    # Make plot
    fig = plt.figure(constrained_layout=False, figsize=(15, 11.28), dpi=100)
    spec = gridspec.GridSpec(ncols=1, nrows=3, figure=fig,
                             height_ratios=[3, 3, 1], hspace=0)

    axs = []
    for row in range(3):
        axs.append(fig.add_subplot(spec[row, 0]))

    # Account for scaling on NDVI
    d.ndvi = d.ndvi / 10000

    axs[0].plot(d.index, d.ndvi, color='#0B6623', linewidth=3)
    axs[0].set_xlim(year_start, year_end)
    axs[0].set_ylim(d.ndvi.min() * .95, d.ndvi.max() * 1.1)
    axs[0].set_ylabel('NDVI\n(annual)', fontsize=32)
    axs[0].tick_params(axis='y', left=False, right=True, labelleft=False, labelright=True, labelsize=28)
    axs[0].tick_params(axis='x', bottom=False, labelbottom=False)

    axs[1].plot(d.index, d.precipitation, color='#1167b1', linewidth=3)
    axs[1].set_xlim(year_start, year_end)
    axs[1].set_ylabel('Precipitation\n(annual, mm)', fontsize=32)
    axs[1].tick_params(axis='y', left=False, right=True, labelleft=False, labelright=True, labelsize=28)
    axs[1].tick_params(axis='x', bottom=False, labelbottom=False)

    pd.options.mode.chained_assignment = None  # default='warn'
    for n in range(len(d.index)):
        if not np.isnan(d.land_cover.iloc[n]):
            axs[2].fill_between([d.index[n], d.index[n] + 1],
                                [0, 0], [1, 1],
                                color=classes.Color.iloc[int(d.land_cover.iloc[n])],
                                label=classes.Label.iloc[int(d.land_cover.iloc[n])])
    axs[2].set_xlim(year_start, year_end)
    axs[2].set_ylim(0, 5)
    axs[2].tick_params(axis='y', left=False, labelleft=False, labelsize=28)
    axs[2].tick_params(axis='x', labelsize=28)
    axs[2].set_xlabel('Year', fontsize=32)
    axs[2].set_ylabel('Land\nCover', fontsize=32)
    handles, labels = axs[2].get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    axs[2].legend(by_label.values(), by_label.keys(), ncol=4, frameon=False, fontsize=26, borderpad=0)

    height = te_logo.size[1]
    # We need a float array between 0-1, rather than
    # a uint8 array between 0-255
    im_array = np.array(te_logo).astype(np.float) / 255
    fig.figimage(im_array, 120, fig.bbox.ymax - height - 40, zorder=-1)
    
    # Set the first axis background to transparent so the trends.earth logo (placed behind it) will show through
    axs[0].patch.set_facecolor('w')
    axs[0].patch.set_alpha(0)
    
    return plt


def landtrend(year_start, year_end, geojson, lang, gc_client, metadata):
    res = landtrend_get_data(year_start, year_end, geojson)

    PLOT_LOCK.acquire()

    plt = landtrend_make_plot(res, year_start, year_end)

    plt.tight_layout()
    f = tempfile.NamedTemporaryFile(suffix='.png').name
    plt.savefig(f, bbox_inches='tight')

    PLOT_LOCK.release()

    h = get_hash(f)

    url = Url(upload_to_google_cloud(gc_client, f), h)

    title = metadata['landtrend_plot']['title']['lang'] + ' ({} - {})'.format(year_start, year_end)
    out = ImageryPNG(name='landtrend_plot',
                     lang=lang,
                     title=title,
                     date=[dt.date(year_start, 1, 1), dt.date(year_end, 12, 31)],
                     about=metadata['landtrend_plot']['about']['lang'],
                     url=url)
    schema = ImageryPNGSchema()
    return {'landtrend_plot' : schema.dump(out)}


###############################################################################
# Code for base image (Landsat 8 RGB plot)

# Function to mask out clouds and cloud-shadows present in Landsat images
def maskL8sr(image):
    # Bits 3 and 5 are cloud shadow and cloud, respectively.
    cloudShadowBitMask = (1 << 3)
    cloudsBitMask = (1 << 5)
    # Get the pixel QA band.
    qa = image.select('pixel_qa')
    # Both flags should be set to zero, indicating clear conditions.
    mask = qa.bitwiseAnd(cloudShadowBitMask).eq(0)
    mask = qa.bitwiseAnd(cloudsBitMask).eq(0)

    return image.updateMask(mask)

# Function to generate the Normalized Diference Vegetation Index, NDVI = (NIR + 
# Red)/(NIR + Red) 
def calculate_ndvi(image):
    return image.normalizedDifference(['B5', 'B4']).rename('NDVI')

OLI_SR_COLL = ee.ImageCollection('LANDSAT/LC08/C01/T1_SR')
def base_image(year, geojson, lang, gc_client, metadata):
    start_date = dt.datetime(year, 1, 1)
    end_date = dt.datetime(year, 12, 31)
    point = ee.Geometry(geojson)
    region = point.buffer(BOX_SIDE / 2).bounds()

    # Mask out clouds and cloud-shadows in the Landsat image
    range_coll = OLI_SR_COLL.filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
    l8sr_y = (range_coll.map(maskL8sr).median().setDefaultProjection(range_coll.first().projection()))
    
    # Define visualization parameter for ndvi trend and apply them
    p_l8sr = {'bands': ['B4', 'B3', 'B2'], 'min': 0, 'max': 3000, 'gamma': 1.5,}
    map_l8sr = l8sr_y.visualize(**p_l8sr)
    map_l8sr_mosaic = ee.ImageCollection.fromImages([map_l8sr, ee.Image().int() \
            .paint(point.buffer(BOX_SIDE / 75), 1) \
            .visualize(**{'palette': ['black'], 'opacity': 1})]) \
            .mosaic()

    # Reproject L8 image so it can retrieve data from every latitute 
    # without deforming the aoi bounding box
    l8sr_mosaic_bands = l8sr_y.reproject(scale=30, crs='EPSG:3857')

    # create thumbnail and retrieve it by url
    l8sr_url = map_l8sr_mosaic.getThumbUrl({'region': region.getInfo(), 'dimensions': 256})
    l8sr_name = 'l8sr.png'
    request.urlretrieve(l8sr_url, l8sr_name)

    # read image and pass it to a 2-d numpy array
    l8sr_frame = Image.open(l8sr_name)
    np_l8sr = np.array(l8sr_frame)
    
    title = metadata['base_image']['title']['lang'] + ' ({})'.format(year)
    f = plot_image_to_file(np_l8sr, title)
    h = get_hash(f)
    url = Url(upload_to_google_cloud(gc_client, f), h)

    out = ImageryPNG(name='base_image',
                     lang=lang,
                     title=title,
                     date=[start_date, end_date],
                     about=metadata['base_image']['about']['lang'],
                     url=url)
    schema = ImageryPNGSchema()
    return {'base_image' : schema.dump(out)}


###############################################################################
# Greenness average

def greenness(year, geojson, lang, gc_client, metadata):
    start_date = dt.datetime(year, 1, 1)
    end_date = dt.datetime(year, 12, 31)
    point = ee.Geometry(geojson)
    region = point.buffer(BOX_SIDE / 2).bounds()
    ndvi_mean = OLI_SR_COLL.filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')) \
            .map(maskL8sr) \
            .map(calculate_ndvi) \
            .mean() \
            .addBands(ee.Image(year).float()) \
            .rename(['ndvi','year'])
    
    # Define visualization parameter for ndvi trend and apply them
    p_ndvi_mean = {'bands':'ndvi', 'min': 0.3, 'max': 0.9, 'palette':['#ffffcc','#006600']}
    map_mean = ndvi_mean.visualize(**p_ndvi_mean)
    map_mean_mosaic = ee.ImageCollection.fromImages([map_mean, ee.Image() \
            .int() \
            .paint(point.buffer(BOX_SIDE / 75), 1) \
            .visualize(**{'palette': ['black'], 'opacity': 1})]) \
            .mosaic()
    
    # Reproject ndvi mean image so it can retrieve data from every latitute 
    # without deforming the aoi bounding box
    ndvi_mean_reproject = ndvi_mean.reproject(scale=30, crs='EPSG:3857')
    
    # create thumbnail and retrieve it by url
    mean_url = map_mean_mosaic.getThumbUrl({'region': region.getInfo(), 'dimensions': 256})
    mean_name = 'ndvi_mean.png'
    request.urlretrieve(mean_url, mean_name)
                       
    # read image and pass it to a 2-d numpy array
    mean_frame = Image.open(mean_name)
    np_mean = np.array(mean_frame)

    legend = Image.open(os.path.join(pathlib.Path(__file__).parent.absolute(), 
                                    'ndvi_avg_{}.png'.format(lang.lower())))
    title = metadata['greenness']['title']['lang'] + ' ({})'.format(start_date.year)
    f = plot_image_to_file(np_mean, title, legend)
    h = get_hash(f)
    url = Url(upload_to_google_cloud(gc_client, f), h)

    about = metadata['greenness']['about']['lang'].format(YEAR_START=start_date.strftime('%Y/%m/%d'),
                                                  YEAR_END=end_date.strftime('%Y/%m/%d'))
    out = ImageryPNG(name='greenness',
                     lang=lang,
                     title=title,
                     date=[start_date, end_date],
                     about=about,
                     url=url)
    schema = ImageryPNGSchema()
    return {'greenness' : schema.dump(out)}


###############################################################################
# Greenness trend

def greenness_trend(year_start, year_end, geojson, lang, gc_client, metadata):
    start_date = dt.datetime(year_start, 1, 1)
    end_date = dt.datetime(year_end, 12, 31)
    point = ee.Geometry(geojson)
    region = point.buffer(BOX_SIDE / 2).bounds()
    ndvi = []
    for y in range(year_start, year_end + 1):
        ndvi.append(OLI_SR_COLL.filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')) \
                .map(maskL8sr) \
                .map(calculate_ndvi) \
                .mean() \
                .addBands(ee.Image(y).float()) \
                .rename(['ndvi','year']))
    ndvi_coll = ee.ImageCollection(ndvi)

    # Compute linear trend function to predict ndvi based on year (ndvi trend)
    lf_trend = ndvi_coll.select(['year', 'ndvi']).reduce(ee.Reducer.linearFit())
    ndvi_trnd = (lf_trend.select('scale').divide(ndvi[0].select("ndvi"))).multiply(100)
                       
    # Define visualization parameter for ndvi trend and apply them
    p_ndvi_trnd = {'min': -10, 'max': 10, 'palette':['#9b2779','#ffffe0','#006500']}
    map_trnd = ndvi_trnd.visualize(**p_ndvi_trnd)
    map_trnd_mosaic = ee.ImageCollection.fromImages([map_trnd, ee.Image() \
            .int() \
            .paint(point.buffer(BOX_SIDE / 75), 1) \
            .visualize(**{'palette': ['black'], 'opacity': 1})]) \
            .mosaic()
    
    # Reproject ndvi mean image so it can retrieve data from every latitute 
    # without deforming the aoi bounding box
    map_trnd_mosaic = map_trnd_mosaic.reproject(**({'crs':'EPSG:3857','scale':30}))
    
    # create thumbnail and retrieve it by url 
    trnd_url = map_trnd_mosaic.getThumbUrl({'region': region.getInfo(), 'dimensions': 256})
    trnd_name = 'ndvi_trnd.png'
    request.urlretrieve(trnd_url, trnd_name)    
    # read image and pass it to a 2-d numpy array
    trnd_frame = Image.open(trnd_name)
    ndvi_arr_trnd = np.array(trnd_frame)

    legend = Image.open(os.path.join(pathlib.Path(__file__).parent.absolute(), 
                             'ndvi_trd_{}.png'.format(lang.lower())))
    title = metadata['greenness_trend']['title']['lang'] + ' ({})'.format(start_date.year)
    f = plot_image_to_file(ndvi_arr_trnd, title, legend)
    h = get_hash(f)
    url = Url(upload_to_google_cloud(gc_client, f), h)

    about = metadata['greenness_trend']['about']['lang'].format(YEAR_START=start_date.strftime('%Y/%m/%d'),
                                                        YEAR_END=end_date.strftime('%Y/%m/%d'))
    out = ImageryPNG(name='greenness_trend',
                     lang=lang,
                     title=title,
                     date=[start_date, end_date],
                     about=about,
                     url=url)
    schema = ImageryPNGSchema()
    return {'greenness_trend' : schema.dump(out)}


###############################################################################
# Main

def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    year_start = int(params.get('year_start', None))
    if year_start < 2001:
        raise InvalidParameter("Invalid starting year {}".format(year_start))
    year_end = int(params.get('year_end', None))
    if year_start > 2019:
        raise InvalidParameter("Invalid ending year {}".format(year_end))
    lang = params.get('lang', None)
    langs =['EN', 'ES', 'PT']
    if lang not in langs:
        logger.debug("Unknown language {}, returning EN".format(lang))
        lang = 'EN'
    geojson = json.loads(params.get('geojson', None))
    if not geojson['type'].lower() == 'point':
        raise InvalidParameter('geojson must be of type "Point"')
    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    logger.debug('Authenticating with AWS...')
    gc_client = storage.Client()
    logger.debug('Authenticated with AWS.')


    with open(os.path.join(pathlib.Path(__file__).parent.absolute(), 
        'landpks_infotext.json')) as f:
        metadata = json.load(f)

    logger.debug("Running main script.")
    threads = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        logger.debug("Starting threads...")
        res = []
        res.append(executor.submit(landtrend, year_start, year_end, 
            geojson, lang, gc_client, metadata))
        res.append(executor.submit(base_image, year_end, geojson, lang, 
            gc_client, metadata))
        res.append(executor.submit(greenness, year_end, geojson, lang, 
            gc_client, metadata))
        res.append(executor.submit(greenness_trend, year_end - 5, year_end, 
            geojson, lang, gc_client, metadata))
        out = {}

    logger.debug("Gathering thread results...")
    for future in as_completed(res):
        out.update(future.result())
    return(out)