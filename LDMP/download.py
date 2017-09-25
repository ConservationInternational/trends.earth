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
import requests
import re
import crcmod.predefined

from PyQt4 import QtGui, uic, QtCore

from qgis.utils import iface

from LDMP import log

from LDMP.gui.DlgDownload import Ui_DlgDownload
from LDMP.worker import AbstractWorker, start_worker

def check_goog_cloud_store_hash(url, filename):
    h = requests.head(url)
    try:
        #TODO not sure why this isn't working...
        expected_crc32c = re.search('crc32c=(.+?), md5=', h.headers.get('x-goog-hash', '')).group(1)
        if not check_hash(filename, expected_crc32c):
            log("File hash doesn't match expected value for {}.".format(filename), 2)
        else:
            log("File hash verified for {}.".format(filename))
    except AttributeError:
        log("CRC32c file hash not found in header for {}. Skipping hash check. WARNING file may not be complete.".format(filename), 2)
        #TODO delete file and suggest attempting download again

def check_hash(file, expected):
    BUF_SIZE = 65536
    crc = crcmod.predefined.mkCrcFun('crc-32-c')
    with open(file, 'rb') as f:
        while True:
            data = f.read(BUF_SIZE)
            if not data:
                break
            crc.update(data)
    if crc.crcValue == expected:
        return True
    else:
        log("Failed verification of file hash for {}. Expected {}, but got {}.".format(filename, expected, crc.crcValue), 2)
        return False

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
                    log("Download {} killed by user".format(self.url))
                    break
                elif chunk: # filter out keep-alive new chunks
                    f.write(chunk)
                    bytes_dl += len(chunk)
                    self.progress.emit(100* float(bytes_dl) / float(total_size))
        f.close()

        if bytes_dl != total_size:
            log("Download error. File size of {} didn't match expected ({} versus {})".format(self.url, bytes_dl, total_size))
            os.remove(self.outfile)
            if not self.killed:
                raise DownloadError('Final file size of {} does not match expected'.format(self.url))
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
            start_worker(worker, iface, 'Downloading {}'.format(self.url.rsplit('/', 1)[-1]))
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
        except DownloadError:
            log("Download failed - file size doesn't match expected")
            QtGui.QMessageBox.critical(None, "Error", "Download failed. Check your internet connection.")
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

class DlgDownload(QtGui.QDialog, Ui_DlgDownload):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgDownload, self).__init__(parent)
        # Set up the user interface from Designer.
        # After setupUI you can access any designer object by doing
        # self.<objectname>, and you can use autoconnect slots - see
        # http://qt-project.org/doc/qt-4.8/designer-using-a-ui-file.html
        # #widgets-and-dialogs-with-auto-connect
        self.setupUi(self)
