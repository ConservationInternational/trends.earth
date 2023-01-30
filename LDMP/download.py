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
import gzip
import hashlib
import json
import os
import typing
import zipfile
from functools import partial
from pathlib import Path

import requests
from qgis.core import QgsApplication
from qgis.core import QgsFileDownloader
from qgis.core import QgsSettings
from qgis.core import QgsTask
from qgis.PyQt import QtCore
from qgis.PyQt import QtNetwork
from qgis.PyQt import QtWidgets
from qgis.utils import iface

from .api import APIClient
from .constants import API_URL
from .constants import TIMEOUT
from .logger import log
from .worker import AbstractWorker
from .worker import start_worker


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
            level1_regions=regions,
        )


class tr_download:
    def tr(message):
        return QtCore.QCoreApplication.translate("tr_download", message)


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
        h = APIClient(API_URL, TIMEOUT).get_header(url)
        if not h:
            log("Failed to fetch expected hash for {}".format(filename))
            return False
        else:
            expected = h.get("ETag", "").strip('"')

    with open(filename, "rb") as f:
        md5hash = hashlib.md5(f.read()).hexdigest()

    if md5hash == expected:
        log("File hash verified for {}".format(filename))
        return True
    else:
        log(
            "Failed verification of file hash for {}. Expected {}, but got {}".format(
                filename, expected, md5hash
            )
        )
        return False


def extract_zipfile(f, verify=True):
    filename = os.path.join(os.path.dirname(__file__), "data", f)
    url = "https://s3.amazonaws.com/trends.earth/sharing/{}".format(f)

    if os.path.exists(filename) and verify:
        if not check_hash_against_etag(url, filename):
            os.remove(filename)

    if not os.path.exists(filename):
        log("Downloading {}".format(f))
        # TODO: Dialog box with two options:
        #   1) Download
        #   2) Load from local folder
        worker = Download(url, filename)
        try:
            worker.start()
        except PermissionError:
            QtWidgets.QMessageBox.critical(
                None,
                tr_download.tr("Error"),
                tr_download.tr("Unable to write to {}.".format(filename)),
            )
            return False
        resp = worker.get_resp()
        if not resp:
            return False
        if not check_hash_against_etag(url, filename):
            return False

    try:
        with zipfile.ZipFile(filename, "r") as fin:
            fin.extractall(os.path.join(os.path.dirname(__file__), "data"))
        return True
    except zipfile.BadZipfile:
        os.remove(filename)
        return False


def read_json(f, verify=True):
    filename = os.path.join(os.path.dirname(__file__), "data", f)
    url = "https://s3.amazonaws.com/trends.earth/sharing/{}".format(f)

    if os.path.exists(filename) and verify:
        if not check_hash_against_etag(url, filename):
            os.remove(filename)

    if not os.path.exists(filename):
        log("Downloading {}".format(f))
        # TODO: Dialog box with two options:
        #   1) Download
        #   2) Load from local folder
        worker = Download(url, filename)
        try:
            worker.start()
        except PermissionError:
            QtWidgets.QMessageBox.critical(
                None,
                tr_download.tr("Error"),
                tr_download.tr(
                    "Unable to write to {}. Do you need administrator permissions?".format(
                        filename
                    )
                ),
            )
            return None
        resp = worker.get_resp()
        if not resp:
            return None
        if not check_hash_against_etag(url, filename):
            return None

    with gzip.GzipFile(filename, "r") as fin:
        json_bytes = fin.read()
        json_str = json_bytes.decode("utf-8")

    return json.loads(json_str)


def download_files(urls, out_folder):
    if out_folder == "":
        QtWidgets.QMessageBox.critical(
            None,
            tr_download.tr("Folder does not exist"),
            tr_download.tr("Folder {} does not exist.".format(out_folder)),
        )
        return None

    if not os.access(out_folder, os.W_OK):
        QtWidgets.QMessageBox.critical(
            None,
            tr_download.tr("Error"),
            tr_download.tr("Unable to write to {}.".format(out_folder)),
        )
        return None

    downloads = []
    for url in urls:
        out_path = os.path.join(out_folder, os.path.basename(url))
        if not os.path.exists(out_path) or not check_hash_against_etag(url, out_path):
            log("Downloading {} to {}".format(url, out_path))

            worker = Download(url, out_path)
            try:
                worker.start()
            except PermissionError:
                log("Unable to write to {}.".format(out_folder))
                QtWidgets.QMessageBox.critical(
                    None,
                    tr_download.tr("Error"),
                    tr_download.tr("Unable to write to {}.".format(out_folder)),
                )
                return None

            resp = worker.get_resp()
            if not resp:
                log("Error accessing {}.".format(url))
                QtWidgets.QMessageBox.critical(
                    None,
                    tr_download.tr("Error"),
                    tr_download.tr("Error accessing {}.".format(url)),
                )
                return None
            if not check_hash_against_etag(url, out_path):
                log("File verification failed for {}.".format(out_path))
                QtWidgets.QMessageBox.critical(
                    None,
                    tr_download.tr("Error"),
                    tr_download.tr("File verification failed for {}.".format(out_path)),
                )
                return None

            downloads.extend(out_path)

    return downloads


def get_admin_bounds() -> typing.Dict[str, Country]:
    raw_admin_bounds = read_json("admin_bounds_key.json.gz", verify=False)
    countries_regions = {}
    for country_name, raw_country in raw_admin_bounds.items():
        countries_regions[country_name] = Country.deserialize(country_name, raw_country)
    return countries_regions


def get_cities() -> typing.Dict[str, typing.Dict[str, City]]:
    cities_key = read_json("cities.json.gz", verify=False)
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

        self.download_file(self.url, self.outfile)

        return True

    def download_file(self, url, outfile):
        try:
            loop = QtCore.QEventLoop()

            download_exit = partial(self.download_exit, loop)

            downloader = QgsFileDownloader(QtCore.QUrl(url), outfile)
            downloader.downloadCompleted.connect(self.download_finished)
            downloader.downloadExited.connect(download_exit)
            downloader.downloadCanceled.connect(download_exit)
            downloader.downloadError.connect(self.download_error)
            downloader.downloadProgress.connect(self.update_progress)

            if self.killed:
                downloader.downloadProgress.connect(downloader.cancelDownload)

            loop.exec_()

        except Exception as e:
            log(tr_download.tr("Error in downloading file, {}").format(str(e)))

    def update_progress(self, value, total):
        if total > 0:
            self.progress.emit(value * 100 / total)

    def download_error(self, error):
        log(
            tr_download.tr(
                f"Error while downloading file to" f" {self.outfile}, {error}"
            )
        )
        raise DownloadError(
            "Unable to start download of {}, {}".format(self.url, error)
        )

    def download_finished(self):
        log(tr_download.tr(f"Finished downloading file to {self.outfile}"))

    def download_exit(self, loop):
        log(tr_download.tr(f"Download exited {self.outfile}"))
        loop.exit()


class Download:
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
            start_worker(
                worker, iface, tr_download.tr("Downloading {}").format(self.outfile)
            )
            pause.exec_()
            if self.get_exception():
                raise self.get_exception()

        except DownloadError:
            log("Download failed.")
            QtWidgets.QMessageBox.critical(
                None,
                tr_download.tr("Error"),
                tr_download.tr("Download failed. Check your internet connection."),
            )
        except Exception as err:
            QtWidgets.QMessageBox.critical(
                None,
                tr_download.tr("Error"),
                tr_download.tr("Problem running task for downloading file"),
            )
            log(tr_download.tr("An error occured when running task for"))
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
