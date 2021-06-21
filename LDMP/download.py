# -*- coding: utf-8 -*-
"""
/***************************************************************************
 LDMP - A QGIS plugin
 This plugin supports monitoring and reporting of land degradation to the UNCCD 
 and in support of the SDG Land Degradation Neutrality (LDN) target.
                              -------------------
        begin                : 2017-05-23
        git sha              : $Format:%H$
        copyright            : (C) 2017 by Conservation International
        email                : trends.earth@conservation.org
 ***************************************************************************/
"""

import dataclasses
import os
import gzip
import typing
import zipfile
import json
import requests
import hashlib
from pathlib import Path

from qgis.PyQt import QtWidgets, uic, QtCore
from qgis.PyQt.QtCore import QAbstractTableModel, Qt, QCoreApplication

from qgis.utils import iface

from .logger import log

from .api import get_header
from .worker import AbstractWorker, start_worker


@dataclasses.dataclass()
class City:
    wof_id: str
    name: str
    geojson: typing.Dict
    name_de: str
    name_en: str
    name_es: str
    name_fr: str
    name_pt: str
    name_ru: str
    name_zh: str

    @classmethod
    def deserialize(cls, wof_id: str, raw_city: typing.Dict):
        return cls(
            wof_id=wof_id,
            name=raw_city["ADM1NAME"],
            geojson=raw_city["geojson"],
            name_de=raw_city["name_de"],
            name_en=raw_city["name_en"],
            name_es=raw_city["name_es"],
            name_fr=raw_city["name_fr"],
            name_pt=raw_city["name_pt"],
            name_ru=raw_city["name_ru"],
            name_zh=raw_city["name_zh"],
        )


@dataclasses.dataclass()
class Country:
    name: str
    code: str
    crs: str
    wrap: bool
    level1_regions: typing.Dict[str, str]

    @classmethod
    def deserialize(cls, name: str, raw_country: typing.Dict):
        regions = {}
        for admin_level1_name, details in raw_country.get("admin1").items():
            regions[admin_level1_name] = details["code"]

        return cls(
            name=name,
            code=raw_country["code"],
            crs=raw_country["crs"],
            wrap=raw_country["wrap"],
            level1_regions=regions
        )



class tr_download(object):
    def tr(message):
        return QCoreApplication.translate("tr_download", message)


def local_check_hash_against_etag(path: Path, expected: str) -> bool:
    try:
        path_hash = hashlib.md5(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        result = False
    else:
        result = path_hash == expected
        if result:
            log(f"File hash verified for {path}")
        else:
            log(
                f"Failed verification of file hash for {path}. Expected {expected}, "
                f"but got {path_hash}"
            )
    return result


def check_hash_against_etag(url, filename, expected=None):
    if not expected:
        h = get_header(url)
        if not h:
            log(u"Failed to fetch expected hash for {}".format(filename))
            return False
        else:
            expected = h.get('ETag', '').strip('"')

    with open(filename, 'rb') as f:
        md5hash = hashlib.md5(f.read()).hexdigest()

    if md5hash == expected:
        log(u"File hash verified for {}".format(filename))
        return True
    else:
        log(u"Failed verification of file hash for {}. Expected {}, but got {}".format(filename, expected, md5hash))
        return False


def extract_zipfile(f, verify=True):
    filename = os.path.join(os.path.dirname(__file__), 'data', f)
    url = u'https://s3.amazonaws.com/trends.earth/sharing/{}'.format(f)

    if os.path.exists(filename) and verify:
        if not check_hash_against_etag(url, filename):
            os.remove(filename)

    if not os.path.exists(filename):
        log(u'Downloading {}'.format(f))
        # TODO: Dialog box with two options:
        #   1) Download
        #   2) Load from local folder
        worker = Download(url, filename)
        try:
            worker.start()
        except PermissionError:
            QtWidgets.QMessageBox.critical(None,
                                       tr_download.tr("Error"),
                                       tr_download.tr("Unable to write to {}.".format(filename)))
            return None
        resp = worker.get_resp()
        if not resp:
            return None
        if not check_hash_against_etag(url, filename):
            return None

    try:
        with zipfile.ZipFile(filename, 'r') as fin:
            fin.extractall(os.path.join(os.path.dirname(__file__), 'data'))
        return True
    except zipfile.BadZipfile:
        os.remove(filename)
        return False

def read_json(f, verify=True):
    filename = os.path.join(os.path.dirname(__file__), 'data', f)
    url = u'https://s3.amazonaws.com/trends.earth/sharing/{}'.format(f)

    if os.path.exists(filename) and verify:
        if not check_hash_against_etag(url, filename):
            os.remove(filename)

    if not os.path.exists(filename):
        log(u'Downloading {}'.format(f))
        # TODO: Dialog box with two options:
        #   1) Download
        #   2) Load from local folder
        worker = Download(url, filename)
        try:
            worker.start()
        except PermissionError:
            QtWidgets.QMessageBox.critical(None,
                                       tr_download.tr("Error"),
                                       tr_download.tr("Unable to write to {}. Do you need administrator permissions?".format(filename)))
            return None
        resp = worker.get_resp()
        if not resp:
            return None
        if not check_hash_against_etag(url, filename):
            return None

    with gzip.GzipFile(filename, 'r') as fin:
        json_bytes = fin.read()
        json_str = json_bytes.decode('utf-8')

    return json.loads(json_str)

def download_files(urls, out_folder):
    if out_folder == '':
        QtWidgets.QMessageBox.critical(None,
                                   tr_download.tr("Folder does not exist"),
                                   tr_download.tr("Folder {} does not exist.".format(out_folder)))
        return None

    if not os.access(out_folder, os.W_OK):
        QtWidgets.QMessageBox.critical(None,
                                   tr_download.tr("Error"),
                                   tr_download.tr("Unable to write to {}.".format(out_folder)))
        return None

    downloads = []
    for url in urls:
        out_path = os.path.join(out_folder, os.path.basename(url))
        if not os.path.exists(out_path) or not check_hash_against_etag(url, out_path):
            log(u'Downloading {} to {}'.format(url, out_path))

            worker = Download(url, out_path)
            try:
                worker.start()
            except PermissionError:
                log(u'Unable to write to {}.'.format(out_folder))
                QtWidgets.QMessageBox.critical(None,
                                           tr_download.tr("Error"),
                                           tr_download.tr("Unable to write to {}.".format(out_folder)))
                return None

            resp = worker.get_resp()
            if not resp:
                log(u'Error accessing {}.'.format(url))
                QtWidgets.QMessageBox.critical(None,
                                           tr_download.tr("Error"),
                                           tr_download.tr("Error accessing {}.".format(url)))
                return None
            if not check_hash_against_etag(url, out_path):
                log(u'File verification failed for {}.'.format(out_path))
                QtWidgets.QMessageBox.critical(None,
                                           tr_download.tr("Error"),
                                           tr_download.tr("File verification failed for {}.".format(out_path)))
                return None

            downloads.extend(out_path)

    return downloads


def get_admin_bounds() -> typing.Dict[str, Country]:
    raw_admin_bounds = read_json('admin_bounds_key.json.gz', verify=False)
    countries_regions = {}
    for country_name, raw_country in raw_admin_bounds.items():
        countries_regions[country_name] = Country.deserialize(country_name, raw_country)
    return countries_regions


def get_cities() -> typing.Dict[str, typing.Dict[str, City]]:
    cities_key = read_json('cities.json.gz', verify=False)
    countries_cities = {}
    for country_code, city_details in cities_key.items():
        country_cities = {}
        for wof_id, further_details in city_details.items():
            country_cities[wof_id] = City.deserialize(wof_id, further_details)
        countries_cities[country_code] = country_cities
    return countries_cities


class DownloadError(Exception):
    def __init__(self, message):
        self.message = message


class DownloadWorker(AbstractWorker):
    """worker, implement the work method here and raise exceptions if needed"""

    def __init__(self, url, outfile):
        AbstractWorker.__init__(self)
        self.url = url
        self.outfile = outfile

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        resp = requests.get(self.url, stream=True)
        if resp.status_code != 200:
            log(u'Unexpected HTTP status code ({}) while trying to download {}.'.format(resp.status_code, self.url))
            raise DownloadError(u'Unable to start download of {}'.format(self.url))

        total_size = int(resp.headers['Content-length'])
        if total_size < 1e5:
            total_size_pretty = '{:.2f} KB'.format(round(total_size / 1024, 2))
        else:
            total_size_pretty = '{:.2f} MB'.format(round(total_size * 1e-6, 2))

        log(u'Downloading {} ({}) to {}'.format(self.url, total_size_pretty, self.outfile))

        bytes_dl = 0
        r = requests.get(self.url, stream=True)
        with open(self.outfile, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                if self.killed == True:
                    log(u"Download {} killed by user".format(self.url))
                    break
                elif chunk: # filter out keep-alive new chunks
                    f.write(chunk)
                    bytes_dl += len(chunk)
                    self.progress.emit(100 * float(bytes_dl) / float(total_size))
        f.close()

        if bytes_dl != total_size:
            log(u"Download error. File size of {} didn't match expected ({} versus {})".format(self.url, bytes_dl, total_size))
            os.remove(self.outfile)
            if not self.killed:
                raise DownloadError(u'Final file size of {} does not match expected'.format(self.url))
            return None
        else:
            log(u"Download of {} complete".format(self.url))
            return True


class Download(object):
    def __init__(self, url, outfile):
        self.resp = None
        self.exception = None
        self.url = url
        self.outfile = outfile

    def start(self):
        try:
            worker = DownloadWorker(self.url, self.outfile)
            pause = QtCore.QEventLoop()
            worker.finished.connect(pause.quit)
            worker.successfully_finished.connect(self.save_resp)
            worker.error.connect(self.save_exception)
            start_worker(worker, iface,
                         tr_download.tr(u'Downloading {}').format(self.outfile))
            pause.exec_()
            if self.get_exception():
                raise self.get_exception()
        except requests.exceptions.ChunkedEncodingError:
            log("Download failed due to ChunkedEncodingError - likely a connection loss")
            QtWidgets.QMessageBox.critical(None,
                                       tr_download.tr("Error"),
                                       tr_download.tr("Download failed. Check your internet connection."))
            return False
        except requests.exceptions.ConnectionError:
            log("Download failed due to connection error")
            QtWidgets.QMessageBox.critical(None,
                                       tr_download.tr("Error"),
                                       tr_download.tr("Unable to access internet. Check your internet connection."))
            return False
        except requests.exceptions.Timeout:
            log('Download timed out.')
            QtWidgets.QMessageBox.critical(None,
                                       tr_download.tr("Error"),
                                       tr_download.tr("Download timed out. Check your internet connection."))
            return False
        except DownloadError:
            log("Download failed.")
            QtWidgets.QMessageBox.critical(None,
                                       tr_download.tr("Error"),
                                       tr_download.tr("Download failed. Check your internet connection."))
            return False
        return True

    def save_resp(self, resp):
        self.resp = resp

    def get_resp(self):
        return self.resp

    def save_exception(self, exception):
        self.exception = exception

    def get_exception(self):
        return self.exception
