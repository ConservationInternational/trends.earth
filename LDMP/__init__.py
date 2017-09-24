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
        email                : GEF-LDMP@conservation.org
 ***************************************************************************/
"""

import os
import gzip
import requests
import json
import site

from PyQt4 import QtGui, QtCore, uic

from qgis.core import QgsMessageLog
from qgis.utils import iface

site.addsitedir(os.path.abspath(os.path.dirname(__file__) + '/ext-libs'))

debug = QtCore.QSettings().value('LDMP/debug', True)

def log(message, level=QgsMessageLog.INFO):
    if debug:
        QgsMessageLog.logMessage(message, tag="LDMP", level=level)

class DownloadError(Exception):
     def __init__(self, message):
        self.message = message

from LDMP.worker import AbstractWorker, start_worker

class DownloadWorker(AbstractWorker):
    """worker, implement the work method here and raise exceptions if needed"""
    def __init__(self, url, outfile):
        AbstractWorker.__init__(self)
        self.url = url
        self.outfile = outfile
 
    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        total_size = int(requests.get(self.url, stream=True).headers['Content-length'])
        if total_size < 1e5:
            total_size_pretty = '{:.2f} KB'.format(round(total_size/1024, 2))
        else:
            total_size_pretty = '{:.2f} MB'.format(round(total_size*1e-6, 2))
        
        log('Downloading {} ({}) to {}'.format(self.url, total_size_pretty, self.outfile))

        bytes_dl = 0
        r = requests.get(self.url, stream=True)
        with open(self.outfile, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192): 
                if self.killed == True:
                    return None
                elif chunk: # filter out keep-alive new chunks
                    f.write(chunk)
                    bytes_dl += len(chunk)
                    self.progress.emit(100* float(bytes_dl) / float(total_size))

        if bytes_dl != total_size:
            log("Download error. File size of {} didn't match expected ({} versus {})".format(self.url, bytes_dl, total_size))
            os.remove(self.outfile)
            raise DownloadError('Final file size does not match expected')
        else:
            log("Download of {} complete".format(self.url))
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
            start_worker(worker, iface, 'Downloading {}'.format(self.url))
            pause.exec_()
            if self.get_exception():
                raise self.get_exception()
        except requests.exceptions.ChunkedEncodingError:
            log("Download failed due to ChunkedEncodingError - likely a connection loss")
            QtGui.QMessageBox.critical(None, "Error", "Download failed. Check your internet connection.")
            return False
        except requests.exceptions.ConnectionError:
            log("Download failed due to connection error")
            QtGui.QMessageBox.critical(None, "Error", "Unable to access internet. Check your internet connection.")
            return False
        except requests.exceptions.Timeout:
            log('Download timed out')
            QtGui.QMessageBox.critical(None, "Error", "Download timed out. Check your internet connection.")
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

def read_json(file):
    filename = os.path.join(os.path.dirname(__file__), 'data', file)
    if not os.path.exists(filename):
        # TODO: Check a crc checksum on these files to catch partial downloads 
        # other potential problems with the .JSONs. Delete the files if there 
        # is an error.
        #
        # If not found, offer to download the files from github or to load them 
        # from a local folder
        # TODO: Dialog box with two options:
        #   1) Download
        #   2) Load from local folder
        worker = Download('https://landdegradation.s3.amazonaws.com/Sharing/{}'.format(file), filename)
        worker.start()
        resp = worker.get_resp()
        if not resp:
            return None

    with gzip.GzipFile(filename, 'r') as fin:
        json_bytes = fin.read()
        json_str = json_bytes.decode('utf-8')

    return json.loads(json_str)

admin_0 = read_json('admin_0.json.gz')
QtCore.QSettings().setValue('LDMP/admin_0', json.dumps(admin_0))

admin_1 = read_json('admin_1.json.gz')
QtCore.QSettings().setValue('LDMP/admin_1', json.dumps(admin_1))

# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load LDMPPlugin class from file LDMP.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """

    from LDMP.ldmp import LDMPPlugin
    return LDMPPlugin(iface)
