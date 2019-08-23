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

from builtins import object
import os
import gzip
import zipfile
import json
import requests
import hashlib

from qgis.PyQt import QtWidgets, uic, QtCore
from qgis.PyQt.QtCore import QAbstractTableModel, Qt

from qgis.utils import iface

from LDMP import log

from LDMP.api import get_header
from LDMP.worker import AbstractWorker, start_worker


def check_hash_against_etag(url, filename, expected=None):
    if not expected:
        h = get_header(url)
        if not h:
            log(u"Failed to fetch expected hash for {}".format(filename))
            return False
        else:
            expected = h.get('ETag', '').strip('"')

    md5hash = hashlib.md5(open(filename, 'rb').read()).hexdigest()

    if md5hash == expected:
        log(u"File hash verified for {}".format(filename))
        return True
    else:
        log(u"Failed verification of file hash for {}. Expected {}, but got {}".format(filename, expected, md5hash))
        return False


def extract_zipfile(file, verify=True):
    filename = os.path.join(os.path.dirname(__file__), 'data', file)
    url = u'https://s3.amazonaws.com/trends.earth/sharing/{}'.format(file)

    if os.path.exists(filename) and verify:
        if not check_hash_against_etag(url, filename):
            os.remove(filename)

    if not os.path.exists(filename):
        log(u'Downloading {}'.format(file))
        # TODO: Dialog box with two options:
        #   1) Download
        #   2) Load from local folder
        worker = Download(url, filename)
        worker.start()
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

def read_json(file, verify=True):
    filename = os.path.join(os.path.dirname(__file__), 'data', file)
    url = u'https://s3.amazonaws.com/trends.earth/sharing/{}'.format(file)

    if os.path.exists(filename) and verify:
        if not check_hash_against_etag(url, filename):
            os.remove(filename)

    if not os.path.exists(filename):
        log(u'Downloading {}'.format(file))
        # TODO: Dialog box with two options:
        #   1) Download
        #   2) Load from local folder
        worker = Download(url, filename)
        worker.start()
        resp = worker.get_resp()
        if not resp:
            return None
        if not check_hash_against_etag(url, filename):
            return None

    with gzip.GzipFile(filename, 'r') as fin:
        json_bytes = fin.read()
        json_str = json_bytes.decode('utf-8')

    return json.loads(json_str)


def get_admin_bounds():
    admin_bounds_key = read_json('admin_bounds_key.json.gz', verify=False)
    return admin_bounds_key


def get_cities():
    cities_key = read_json('cities.json.gz', verify=False)
    return cities_key


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
                         QtWidgets.QApplication.translate("LDMP", u'Downloading {}').format(self.outfile))
            pause.exec_()
            if self.get_exception():
                raise self.get_exception()
        except requests.exceptions.ChunkedEncodingError:
            log("Download failed due to ChunkedEncodingError - likely a connection loss")
            QtWidgets.QMessageBox.critical(None,
                                       QtWidgets.QApplication.translate("LDMP", "Error"),
                                       QtWidgets.QApplication.translate("LDMP", "Download failed. Check your internet connection."))
            return False
        except requests.exceptions.ConnectionError:
            log("Download failed due to connection error")
            QtWidgets.QMessageBox.critical(None,
                                       QtWidgets.QApplication.translate("LDMP", "Error"),
                                       QtWidgets.QApplication.translate("LDMP", "Unable to access internet. Check your internet connection."))
            return False
        except requests.exceptions.Timeout:
            log('Download timed out.')
            QtWidgets.QMessageBox.critical(None,
                                       QtWidgets.QApplication.translate("LDMP", "Error"),
                                       QtWidgets.QApplication.translate("LDMP", "Download timed out. Check your internet connection."))
            return False
        except DownloadError:
            log("Download failed.")
            QtWidgets.QMessageBox.critical(None,
                                       QtWidgets.QApplication.translate("LDMP", "Error"),
                                       QtWidgets.QApplication.translate("LDMP", "Download failed. Check your internet connection."))
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
