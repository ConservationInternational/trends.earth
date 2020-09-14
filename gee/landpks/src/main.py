"""
Code for calculating urban area.
"""
# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import datetime as dt
import random
import json
import requests
import tempfile
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed

import ee
from google.cloud import storage

from landdegradation.schemas.schemas import Url, ImageryPNG, \
        ImageryPNGSchema

BUCKET = 'ldmt'


def upload_to_google_cloud(client, f):
    b = client.get_bucket(BUCKET)
    blob = b.blob(os.path.basename(f))
    blob.upload_from_filename(f)
    return 'https://storage.googleapis.com/{}/{}'.format(BUCKET, os.path.basename(f))


def get_hash(filename):
    with open(filename, 'rb') as f:
       return hashlib.md5(f.read()).hexdigest()


def landtrend_plot(lang, geojsons, crs, EXECUTION_ID, logger, gc_client):
    # TEMPORARY ##############################################################
    #TODO: TEMPORARY - replace with real code when available
    r = requests.get('http://trends.earth-shared.s3.us-east-1.amazonaws.com/trendsearth_01_timeseries.PNG', allow_redirects=True)
    f = tempfile.NamedTemporaryFile(suffix='.png').name
    with open(f, 'wb') as f_write:
        f_write.write(r.content)
    h = get_hash(f)
    url = Url(upload_to_google_cloud(gc_client, f), h)
    # /TEMPORARY #############################################################

    out = ImageryPNG(name='landtrend_plot',
                     lang='EN',
                     title='This is a title',
                     date=dt.date(2019, 12, 6),
                     about="This is some about text, with a link in it to the <a href='http://trends.earth'>Trends.Earth</a> web page.",
                     url=url)
    schema = ImageryPNGSchema()
    return {'landtrend_plot' : schema.dump(out)}


def base_image(lang, geojsons, crs, EXECUTION_ID, logger, gc_client):
    # TEMPORARY ##############################################################
    #TODO: TEMPORARY - replace with real code when available
    r = requests.get('http://trends.earth-shared.s3.us-east-1.amazonaws.com/trendsearth_02_satellite.PNG', allow_redirects=True)
    f = tempfile.NamedTemporaryFile(suffix='.png').name
    with open(f, 'wb') as f_write:
        f_write.write(r.content)
    h = get_hash(f)
    url = Url(upload_to_google_cloud(gc_client, f), h)
    # /TEMPORARY #############################################################

    out = ImageryPNG(name='base_image',
                     lang='EN',
                     title='This is a title',
                     date=dt.date(2019, 12, 6),
                     about="This is some about text, with a link in it to the <a href='http://trends.earth'>Trends.Earth</a> web page.",
                     url=url)
    schema = ImageryPNGSchema()
    return {'base_image' : schema.dump(out)}


def greenness(lang, geojsons, crs, EXECUTION_ID, logger, gc_client):
    # TEMPORARY ##############################################################
    #TODO: TEMPORARY - replace with real code when available
    r = requests.get('http://trends.earth-shared.s3.us-east-1.amazonaws.com/trendsearth_03_mean.PNG', allow_redirects=True)
    f = tempfile.NamedTemporaryFile(suffix='.png').name
    with open(f, 'wb') as f_write:
        f_write.write(r.content)
    h = get_hash(f)
    url = Url(upload_to_google_cloud(gc_client, f), h)
    # /TEMPORARY #############################################################

    out = ImageryPNG(name='greenness',
                     lang='EN',
                     title='This is a title',
                     date=dt.date(2019, 1, 1),
                     about="This is some about text, with a link in it to the <a href='http://trends.earth'>Trends.Earth</a> web page.",
                     url=url)
    schema = ImageryPNGSchema()
    return {'greenness' : schema.dump(out)}

def greenness_trend(lang, geojsons, crs, EXECUTION_ID, logger, gc_client):
    # TEMPORARY ##############################################################
    #TODO: TEMPORARY - replace with real code when available
    r = requests.get('http://trends.earth-shared.s3.us-east-1.amazonaws.com/trendsearth_04_trends.PNG', allow_redirects=True)
    f = tempfile.NamedTemporaryFile(suffix='.png').name
    with open(f, 'wb') as f_write:
        f_write.write(r.content)
    h = get_hash(f)
    url = Url(upload_to_google_cloud(gc_client, f), h)
    # /TEMPORARY #############################################################

    out = ImageryPNG(name='greenness_trend',
                     lang='EN',
                     title='This is a title',
                     date=dt.date(2019, 1, 1),
                     about="This is some about text, with a link in it to the <a href='http://trends.earth'>Trends.Earth</a> web page.",
                     url=url)
    schema = ImageryPNGSchema()
    return {'greenness_trend' : schema.dump(out)}

def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    lang = params.get('lang', None)
    geojsons = json.loads(params.get('geojsons', None))
    crs = params.get('crs', None)
    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    logger.debug('Authenticating with AWS...')
    gc_client = storage.Client()
    logger.debug('Authenticated with AWS.')

    logger.debug("Running main script.")
    threads = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        logger.debug("Starting threads...")
        futures = []
        futures.append(executor.submit(landtrend_plot, lang, geojsons, crs,
            EXECUTION_ID, logger, gc_client))
        futures.append(executor.submit(base_image, lang, geojsons, crs, EXECUTION_ID, 
            logger, gc_client))
        futures.append(executor.submit(greenness, lang, geojsons, crs, EXECUTION_ID, 
            logger, gc_client))
        futures.append(executor.submit(greenness_trend, lang, geojsons, crs, 
            EXECUTION_ID, logger, gc_client))
        out = {}
        logger.debug("Gathering thread results...")
        for future in as_completed(futures):
            out.update(future.result())
        return(out)
