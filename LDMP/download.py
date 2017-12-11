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
import json
import requests
import hashlib

from PyQt4 import QtGui, uic, QtCore
from PyQt4.QtCore import QAbstractTableModel, Qt

from qgis.utils import iface

from LDMP import log

#from LDMP.calculate import DlgCalculateBase
from LDMP.gui.DlgDownload import Ui_DlgDownload
from LDMP.worker import AbstractWorker, start_worker
from LDMP.api import get_header


def check_hash_against_etag(url, filename):
    h = get_header(url)
    expected = h.get('ETag', '').strip('"')

    md5hash = hashlib.md5(open(filename, 'rb').read()).hexdigest()

    if md5hash == expected:
        log("File hash verified for {}".format(filename))
        return True
    else:
        log("Failed verification of file hash for {}. Expected {}, but got {}".format(filename, expected, md5hash), 2)
        return False


def read_json(file, verify=True):
    filename = os.path.join(os.path.dirname(__file__), 'data', file)
    url = 'https://s3.amazonaws.com/trends.earth/sharing/{}'.format(file)

    if os.path.exists(filename) and verify:
        if not check_hash_against_etag(url, filename):
            os.remove(filename)

    if not os.path.exists(filename):
        log('Downloading {}'.format(file))
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
            log('Unexpected HTTP status code ({}) while trying to download {}.'.format(resp.status_code, self.url))
            raise DownloadError('Unable to start download of {}'.format(self.url))

        total_size = int(resp.headers['Content-length'])
        if total_size < 1e5:
            total_size_pretty = '{:.2f} KB'.format(round(total_size / 1024, 2))
        else:
            total_size_pretty = '{:.2f} MB'.format(round(total_size * 1e-6, 2))

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
                    self.progress.emit(100 * float(bytes_dl) / float(total_size))
        f.close()

        if bytes_dl != total_size:
            log("Download error. File size of {} didn't match expected ({} versus {})".format(self.url, bytes_dl, total_size))
            os.remove(self.outfile)
            if not self.killed:
                raise DownloadError('Final file size of {} does not match expected'.format(self.url))
            return None
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
            start_worker(worker, iface,
                         QtGui.QApplication.translate("LDMP", 'Downloading {}').format(self.url.rsplit('/', 1)[-1]))
            pause.exec_()
            if self.get_exception():
                raise self.get_exception()
        except requests.exceptions.ChunkedEncodingError:
            log("Download failed due to ChunkedEncodingError - likely a connection loss")
            QtGui.QMessageBox.critical(None,
                                       QtGui.QApplication.translate("LDMP", "Error"),
                                       QtGui.QApplication.translate("LDMP", "Download failed. Check your internet connection."))
            return False
        except requests.exceptions.ConnectionError:
            log("Download failed due to connection error")
            QtGui.QMessageBox.critical(None,
                                       QtGui.QApplication.translate("LDMP", "Error"),
                                       QtGui.QApplication.translate("LDMP", "Unable to access internet. Check your internet connection."))
            return False
        except requests.exceptions.Timeout:
            log('Download timed out.')
            QtGui.QMessageBox.critical(None,
                                       QtGui.QApplication.translate("LDMP", "Error"),
                                       QtGui.QApplication.translate("LDMP", "Download timed out. Check your internet connection."))
            return False
        except DownloadError:
            log("Download failed.")
            QtGui.QMessageBox.critical(None,
                                       QtGui.QApplication.translate("LDMP", "Error"),
                                       QtGui.QApplication.translate("LDMP", "Download failed. Check your internet connection."))
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


class DataTableModel(QAbstractTableModel):
    def __init__(self, datain, parent=None, *args):
        QAbstractTableModel.__init__(self, parent, *args)
        self.datasets = datain

        # Column names as tuples with json name in [0], pretty name in [1]
        # Note that the columns with json names set to to INVALID aren't loaded
        # into the shell, but shown from a widget.
        colname_tuples = [('category', QtGui.QApplication.translate('LDMPPlugin', 'Category')),
                          ('title', QtGui.QApplication.translate('LDMPPlugin', 'Title')),
                          ('Units/Description', QtGui.QApplication.translate('LDMPPlugin', 'Units')),
                          ('Spatial Resolution', QtGui.QApplication.translate('LDMPPlugin', 'Resolution')),
                          ('Start year', QtGui.QApplication.translate('LDMPPlugin', 'Start year')),
                          ('End year', QtGui.QApplication.translate('LDMPPlugin', 'End year')),
                          ('Extent', QtGui.QApplication.translate('LDMPPlugin', 'Extent'))]
        self.colnames_pretty = [x[1] for x in colname_tuples]
        self.colnames_json = [x[0] for x in colname_tuples]

    def rowCount(self, parent):
        return len(self.datasets)

    def columnCount(self, parent):
        return len(self.colnames_json)

    def data(self, index, role):
        if not index.isValid():
            return None
        elif role != Qt.DisplayRole:
            return None
        return self.datasets[index.row()].get(self.colnames_json[index.column()], '')

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.colnames_pretty[section]
        return QAbstractTableModel.headerData(self, section, orientation, role)

#class DlgDownload(DlgCalculateBase, Ui_DlgDownload):
class DlgDownload(QtGui.QDialog, Ui_DlgDownload):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgDownload, self).__init__(parent)

        self.setupUi(self)

        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                               'data', 'gee_datasets.json')) as f:
           data_dict = json.load(f)

        self.datasets = []
        for cat in data_dict.keys():
            for title in data_dict[cat].keys():
                item = data_dict[cat][title]
                item.update({'category': cat,
                             'title': title})
                self.datasets.append(item)

        self.update_data_table()

    def update_data_table(self):
        table_model = DataTableModel(self.datasets, self)
        proxy_model = QtGui.QSortFilterProxyModel()
        proxy_model.setSourceModel(table_model)
        self.data_view.setModel(proxy_model)

        # Add "Notes" buttons in cell
        for row in range(0, len(self.datasets)):
            btn = QtGui.QPushButton(self.tr("Details"))
            btn.clicked.connect(self.btn_details)
            self.data_view.setIndexWidget(proxy_model.index(row, 7), btn)

        self.data_view.horizontalHeader().setResizeMode(QtGui.QHeaderView.ResizeToContents)

        self.data_view.setSelectionBehavior(QtGui.QAbstractItemView.SelectRows)

    def btn_details(self):
        button = self.sender()
        index = self.jobs_view.indexAt(button.pos())
        #TODO: Code the details view
