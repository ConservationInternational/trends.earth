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

from builtins import zip
from builtins import range
import os
import json
import re
import copy
import base64
import binascii

import datetime
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import (QSettings, QAbstractTableModel, Qt, pyqtSignal, 
        QSortFilterProxyModel, QSize, QObject, QEvent)
from qgis.PyQt.QtGui import QFontMetrics

from osgeo import gdal

from qgis.utils import iface
mb = iface.messageBar()

from qgis.gui import QgsMessageBar

from LDMP.gui.DlgJobs import Ui_DlgJobs
from LDMP.gui.DlgJobsDetails import Ui_DlgJobsDetails
from LDMP.plot import DlgPlotTimeries

from LDMP import log
from LDMP.api import get_user_email, get_execution
from LDMP.download import Download, check_hash_against_etag, DownloadError
from LDMP.layers import add_layer
from LDMP.schemas.schemas import LocalRaster, LocalRasterSchema


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    raise TypeError("Type {} not serializable".format(type(obj)))


def create_gee_json_metadata(json_file, job, data_file):
    # Create a copy of the job so bands can be moved to a different place in 
    # the output
    metadata = copy.deepcopy(job)
    bands = metadata['results'].pop('bands')
    metadata.pop('raw')

    out = LocalRaster(os.path.basename(os.path.normpath(data_file)), bands, metadata)
    local_raster_schema = LocalRasterSchema()
    with open(json_file, 'w') as f:
        json.dump(local_raster_schema.dump(out), f, default=json_serial, 
                  sort_keys=True, indent=4, separators=(',', ': '))


class DlgJobsDetails(QtWidgets.QDialog, Ui_DlgJobsDetails):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgJobsDetails, self).__init__(parent)

        self.setupUi(self)


class DlgJobs(QtWidgets.QDialog, Ui_DlgJobs):
    # When a connection to the api starts, emit true. When it ends, emit False
    connectionEvent = pyqtSignal(bool)

    def __init__(self, parent=None):
        """Constructor."""
        super(DlgJobs, self).__init__(parent)

        self.settings = QSettings()

        self.setupUi(self)

        self.connection_in_progress = False

        self.bar = QgsMessageBar()
        self.bar.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        self.layout().addWidget(self.bar, 0, 0, Qt.AlignTop)

        self.refresh.clicked.connect(self.btn_refresh)
        self.download.clicked.connect(self.btn_download)

        self.connectionEvent.connect(self.connection_event_changed)

        # Only enable download button if a job is selected
        self.download.setEnabled(False)

        self.jobs_view.viewport().installEventFilter(tool_tipper(self.jobs_view))

    def showEvent(self, event):
        super(DlgJobs, self).showEvent(event)

        #######################################################################
        #######################################################################
        # Hack to download multiple countries at once for workshop preparation
        #######################################################################
        #######################################################################
        # from qgis.PyQt.QtCore import QTimer, Qt
        # from qgis.PyQt.QtWidgets import QMessageBox, QApplication
        # from qgis.PyQt.QtTest import QTest
        # from time import sleep
        #
        # self.btn_refresh()
        #
        # search_string = '_TE_Land_Productivity'
        #
        # # Ensure any message boxes that open are closed within 1 second
        # def close_msg_boxes():
        #     for w in QApplication.topLevelWidgets():
        #         if isinstance(w, QMessageBox):
        #             print('Closing message box')
        #             QTest.keyClick(w, Qt.Key_Enter)
        # timer = QTimer()
        # timer.timeout.connect(close_msg_boxes)
        # timer.start(1000)
        # jobs = [job for job in self.jobs if job['status'] == 'FINISHED' and \
        #                                     job['results']['type'] == 'CloudResults' and \
        #                                     re.search(search_string, job['task_name'])]
        # for job in jobs:
        #     name = job['task_name']
        #     country = name.replace(search_string, '')
        #     out_file = os.path.join(u'H:/Data/Trends.Earth/USB Stick Data/Trends.Earth_Data', country, u'{}.json'.format(name))
        #     #out_file = os.path.join(u'C:/Users/azvol/Desktop/TE_Indicators_For_USB', country, u'{}.json'.format(name))
        #     if not os.path.exists(out_file):
        #         if not os.path.exists(os.path.dirname(out_file)):
        #             os.makedirs(os.path.dirname(out_file))
        #         log(u'Downloading {} to {}'.format(name, out_file))
        #         download_cloud_results(job,
        #                                os.path.splitext(out_file)[0],
        #                                self.tr,
        #                                add_to_map=False)
        #         sleep(2)
        #######################################################################
        #######################################################################
        # End hack
        #######################################################################
        #######################################################################

        jobs_cache = self.settings.value("LDMP/jobs_cache", None)
        if jobs_cache:
            self.jobs = jobs_cache
            self.update_jobs_table()

    def connection_event_changed(self, flag):
        if flag:
            self.connection_in_progress = True
            self.download.setEnabled(False)
            self.refresh.setEnabled(False)
        else:
            self.connection_in_progress = False
            # Enable the download button if there is a selection
            self.selection_changed()
            self.refresh.setEnabled(True)

    def selection_changed(self):
        if self.connection_in_progress:
            return
        elif not self.jobs_view.selectedIndexes():
            self.download.setEnabled(False)
        else:
            rows = set(list(index.row() for index in self.jobs_view.selectedIndexes()))
            job_ids = [self.proxy_model.index(row, 4).data() for row in rows]
            statuses = [job.get('status', None) for job in self.jobs if job.get('id', None) in job_ids]

            if len(statuses) > 0:
                for status in statuses:
                    # Don't set button to enabled if any of the tasks aren't 
                    # yet finished, or if any are invalid
                    if status != 'FINISHED':
                        self.download.setEnabled(False)
                        return
                self.download.setEnabled(True)

    def btn_refresh(self):
        self.connectionEvent.emit(True)
        email = get_user_email()
        if email:
            start_date = datetime.datetime.now() + datetime.timedelta(-14)
            jobs = get_execution(date=start_date.strftime('%Y-%m-%d'))
            if jobs:
                self.jobs = jobs
                # Add script names and descriptions to jobs list
                for job in self.jobs:
                    # self.jobs will have prettified data for usage in table,
                    # so save a backup of the original data under key 'raw'
                    job['raw'] = job.copy()
                    script = job.get('script_id', None)
                    if script:
                        job['script_name'] = job['script']['name']
                        # Clean up the script name so the version tag doesn't 
                        # look so odd
                        job['script_name'] = re.sub(r'([0-9]+)_([0-9]+)$', r'(v\g<1>.\g<2>)', job['script_name'])
                        job['script_description'] = job['script']['description']
                    else:
                        # Handle case of scripts that have been removed or that are
                        # no longer supported
                        job['script_name'] = self.tr('Script not found')
                        job['script_description'] = self.tr('Script not found')

                # Pretty print dates and pull the metadata sent as input params
                for job in self.jobs:
                    job['start_date'] = datetime.datetime.strftime(job['start_date'], '%Y/%m/%d (%H:%M)')
                    job['end_date'] = datetime.datetime.strftime(job['end_date'], '%Y/%m/%d (%H:%M)')
                    job['task_name'] = job['params'].get('task_name', '')
                    job['task_notes'] = job['params'].get('task_notes', '')
                    job['params'] = job['params']

                # Cache jobs for later reuse
                self.settings.setValue("LDMP/jobs_cache", self.jobs)

                self.update_jobs_table()

                self.connectionEvent.emit(False)
                return True
        self.connectionEvent.emit(False)
        return False

    def update_jobs_table(self):
        if self.jobs:
            table_model = JobsTableModel(self.jobs, self)
            self.proxy_model = QSortFilterProxyModel()
            self.proxy_model.setSourceModel(table_model)
            self.jobs_view.setModel(self.proxy_model)
            # Add "Details" buttons in cell
            for row in range(0, len(self.jobs)):
                btn = QtWidgets.QPushButton(self.tr("Details"))
                btn.clicked.connect(self.btn_details)
                self.jobs_view.setIndexWidget(self.proxy_model.index(row, 6), btn)

            self.jobs_view.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
            self.jobs_view.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
            self.jobs_view.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
            self.jobs_view.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
            self.jobs_view.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.Fixed)
            self.jobs_view.horizontalHeader().setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeToContents)
            self.jobs_view.horizontalHeader().setSectionResizeMode(6, QtWidgets.QHeaderView.ResizeToContents)

            self.jobs_view.selectionModel().selectionChanged.connect(self.selection_changed)


    def btn_details(self):
        button = self.sender()
        index = self.jobs_view.indexAt(button.pos())

        details_dlg = DlgJobsDetails(self)

        job = self.jobs[index.row()]

        details_dlg.task_name.setText(job.get('task_name', ''))
        details_dlg.task_status.setText(job.get('status', ''))
        details_dlg.comments.setText(job.get('task_notes', ''))
        details_dlg.input.setText(json.dumps(job.get('params', ''), indent=4, sort_keys=True))
        details_dlg.output.setText(json.dumps(job.get('results', ''), indent=4, sort_keys=True))

        details_dlg.show()
        details_dlg.exec_()

    def btn_download(self):
        # Use set below in case multiple cells within the same row are selected
        rows = set(list(index.row() for index in self.jobs_view.selectedIndexes()))
        job_ids = [self.proxy_model.index(row, 4).data() for row in rows]
        jobs = [job for job in self.jobs if job['id'] in job_ids]

        filenames = []
        for job in jobs:
            # Check if we need a download filename - some tasks don't need to 
            # save data, but if any of the chosen tasks do, then we need to 
            # choose a folder. Right now only TimeSeriesTable doesn't need a 
            # filename.
            if job['results'].get('type') != 'TimeSeriesTable':
                f = None
                while not f:
                    # Setup a string to use in filename window
                    if job['task_name']:
                        job_info = u'{} ({})'.format(job['script_name'], job['task_name'])
                    else:
                        job_info = job['script_name']
                    f, _ = QtWidgets.QFileDialog.getSaveFileName(self,
                                                          self.tr(u'Choose a filename. Downloading results of: {}'.format(job_info)),
                                                          self.settings.value("LDMP/output_dir", None),
                                                          self.tr('Base filename (*.json)'))

                    # Strip the extension so that it is a basename
                    f = os.path.splitext(f)[0]

                    if f:
                        if os.access(os.path.dirname(f), os.W_OK):
                            self.settings.setValue("LDMP/output_dir", os.path.dirname(f))
                            log(u"Downloading results to {} with basename {}".format(os.path.dirname(f), os.path.basename(f)))
                        else:
                            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                                       self.tr(u"Cannot write to {}. Choose a different base filename.".format(f)))
                    else:
                            return False

                filenames.append(f)
            else:
                filenames.append(None)

        self.close()

        for row, f in zip(rows, filenames):
            job = self.jobs[row]
            log(u"Processing job {}.".format(job.get('id', None)))
            result_type = job['results'].get('type')
            if result_type == 'CloudResults':
                download_cloud_results(job, f, self.tr)
            elif result_type == 'TimeSeriesTable':
                download_timeseries(job, self.tr)
            else:
                raise ValueError("Unrecognized result type in download results: {}".format(result_type))


class JobsTableModel(QAbstractTableModel):
    def __init__(self, datain, parent=None, *args):
        QAbstractTableModel.__init__(self, parent, *args)
        self.jobs = datain

        # Column names as tuples with json name in [0], pretty name in [1]
        # Note that the columns with json names set to to INVALID aren't loaded
        # into the shell, but shown from a widget.
        colname_tuples = [('task_name', QtWidgets.QApplication.translate('LDMPPlugin', 'Task name')),
                          ('script_name', QtWidgets.QApplication.translate('LDMPPlugin', 'Job')),
                          ('start_date', QtWidgets.QApplication.translate('LDMPPlugin', 'Start time')),
                          ('end_date', QtWidgets.QApplication.translate('LDMPPlugin', 'End time')),
                          ('id', QtWidgets.QApplication.translate('LDMPPlugin', 'ID')),
                          ('status', QtWidgets.QApplication.translate('LDMPPlugin', 'Status')),
                          ('INVALID', QtWidgets.QApplication.translate('LDMPPlugin', 'Details'))]
        self.colnames_pretty = [x[1] for x in colname_tuples]
        self.colnames_json = [x[0] for x in colname_tuples]

    def rowCount(self, parent):
        return len(self.jobs)

    def columnCount(self, parent):
        return len(self.colnames_json)

    def data(self, index, role):
        if not index.isValid():
            return None
        elif role == Qt.TextAlignmentRole:
            return Qt.AlignCenter
        elif role == Qt.DisplayRole or role == Qt.ToolTipRole:
            return self.jobs[index.row()].get(self.colnames_json[index.column()], '')
        else:
            return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.colnames_pretty[section]
        return QAbstractTableModel.headerData(self, section, orientation, role)


class tool_tipper(QObject):
    def __init__(self, parent=None):
        super(QObject, self).__init__(parent)

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.ToolTip):
            view = obj.parent()
            if not view:
                return False

            pos = event.pos()
            index = view.indexAt(pos)
            if not index.isValid():
                return False

            itemText = view.model().data(index)
            itemTooltip = view.model().data(index, Qt.ToolTipRole)

            fm = QFontMetrics(view.font())
            itemTextWidth = fm.width(itemText)
            rect = view.visualRect(index)
            rectWidth = rect.width()

            if (itemTextWidth > rectWidth) and itemTooltip:
                QtWidgets.QToolTip.showText(event.globalPos(), itemTooltip, view, rect)
            else:
                QtWidgets.QToolTip.hideText()
            return True
        return False


def download_result(url, out_file, job, expected_etag):
    worker = Download(url, out_file)
    worker.start()
    if worker.get_resp():
        return check_hash_against_etag(url, out_file, expected_etag)
    else:
        return None


def download_cloud_results(job, f, tr, add_to_map=True):
    results = job['results']
    json_file = f + '.json'
    if len(results['urls']) > 1:
        # Save a VRT if there are multiple files for this download
        urls = results['urls'] 
        tiles = []
        for n in range(len(urls)):
            tiles.append(f + '_{}.tif'.format(n))
            # If file already exists, check its hash and skip redownloading if 
            # it matches
            if os.access(tiles[n], os.R_OK):
                if check_hash_against_etag(urls[n]['url'], tiles[n], binascii.hexlify(base64.b64decode(urls[n]['md5Hash'])).decode()):
                    continue
            resp = download_result(urls[n]['url'], tiles[n], job, 
                                   binascii.hexlify(base64.b64decode(urls[n]['md5Hash'])).decode())
            if not resp:
                return
        # Make a VRT mosaicing the tiles so they can be treated as one file 
        # during further processing
        out_file = f + '.vrt'
        gdal.BuildVRT(out_file, tiles)
    else:
        url = results['urls'][0]
        out_file = f + '.tif'
        resp = download_result(url['url'], out_file, job, 
                               binascii.hexlify(base64.b64decode(url['md5Hash'])).decode())
        if not resp:
            return

    create_gee_json_metadata(json_file, job, out_file)

    if add_to_map:
        for band_number in range(1, len(results['bands']) + 1):
            # The minus 1 is because band numbers start at 1, not zero
            band_info = results['bands'][band_number - 1]
            if band_info['add_to_map']:
                add_layer(out_file, band_number, band_info)

    mb.pushMessage(tr("Downloaded"),
                   tr(u"Downloaded results to {}".format(out_file)),
                   level=0, duration=5)


def download_timeseries(job, tr):
    log("Processing timeseries results...")
    table = job['results'].get('table', None)
    if not table:
        return None
    data = [x for x in table if x['name'] == 'mean'][0]
    dlg_plot = DlgPlotTimeries()
    labels = {'title': job['task_name'],
              'bottom': tr('Time'),
              'left': [tr('Integrated NDVI'), tr('NDVI x 10000')]}
    dlg_plot.plot_data(data['time'], data['y'], labels)
    dlg_plot.show()
    dlg_plot.exec_()
