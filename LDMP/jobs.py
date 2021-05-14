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
from typing import Optional, List, Dict, Tuple
import threading
import os
import json
import re
import copy
import base64
import binascii
import copy
import datetime
from dateutil import tz
import pprint
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import (QSettings, QAbstractTableModel, Qt, pyqtSignal, 
        QSortFilterProxyModel, QSize, QObject, QEvent, QCoreApplication, QObject)
from qgis.PyQt.QtGui import QFontMetrics

from osgeo import gdal

from qgis.utils import iface
mb = iface.messageBar()

from qgis.gui import QgsMessageBar
from qgis.core import QgsLogger

from LDMP.gui.DlgJobs import Ui_DlgJobs
from LDMP.gui.DlgJobsDetails import Ui_DlgJobsDetails
from LDMP.plot import DlgPlotTimeries

from LDMP import log, singleton, json_serial, traverse
from LDMP.api import get_user_email, get_execution
from LDMP.download import Download, check_hash_against_etag, DownloadError
from LDMP.layers import add_layer
from LDMP.schemas.schemas import LocalRaster, LocalRasterSchema, APIResponseSchema
from LDMP.calculate import get_script_group

import marshmallow

class tr_jobs(object):
    def tr(message):
        return QCoreApplication.translate("tr_jobs", message)


def create_gee_json_metadata(json_file, job, data_file):
    # Create a copy of the job so bands can be moved to a different place in 
    # the output
    metadata = copy.deepcopy(job)
    bands = metadata['results'].pop('bands')
    metadata.pop('raw')

    # TODO: how to link dumped LocalRaster data with Job class in self.jobsStore

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

        self.jobs = Jobs()

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

        self.jobs.sync()
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
            statuses = [job.get('status', None) for job in self.jobs.list() if job.get('id', None) in job_ids]

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
                self.jobs.set(jobs)
                jobs_list = self.jobs.list()
                # Add script names and descriptions to jobs list
                for job in jobs_list:
                    # self.jobs will have prettified data for usage in table,
                    # so save a backup of the original data under key 'raw'
                    job['raw'] = job.copy()
                    script = job.get('script_id', None)
                    if script:
                        job['script_name'] = job['script']['name']
                        # Clean up the script name so the version tag doesn't 
                        # look so odd
                        job['script_name'] = re.sub(r'([0-9]+(_[0-9]+)+)$', r'(v\g<1>)', job['script_name'])
                        job['script_name'] = job['script_name'].replace('_', '.')
                        job['script_description'] = job['script']['description']
                    else:
                        # Handle case of scripts that have been removed or that are
                        # no longer supported
                        job['script_name'] = self.tr('Script not found')
                        job['script_description'] = self.tr('Script not found')

                # Pretty print dates and pull the metadata sent as input params
                for job in jobs_list:
                    job['start_date'] = Job.datetimeRepr(job['start_date'])
                    job['end_date'] = Job.datetimeRepr(job['end_date'])
                    job['task_name'] = job['params'].get('task_name', '')
                    job['task_notes'] = job['params'].get('task_notes', '')
                    job['params'] = job['params']

                # Cache jobs for later reuse
                QSettings().setValue("LDMP/jobs_cache", json.dumps(jobs_list, default=json_serial))

                self.update_jobs_table()
                self.connectionEvent.emit(False)
                return True

        self.connectionEvent.emit(False)
        return False

    def update_jobs_table(self):
        if self.jobs:
            table_model = JobsTableModel(self.jobs.list(), self)
            self.proxy_model = QSortFilterProxyModel()
            self.proxy_model.setSourceModel(table_model)
            self.jobs_view.setModel(self.proxy_model)
            # Add "Details" buttons in cell
            for row in range(0, len(self.jobs.list())):
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

        job = self.jobs.list()[index.row()]

        details_dlg.task_name.setText(job.get('task_name', ''))
        details_dlg.task_status.setText(job.get('status', ''))
        details_dlg.comments.setText(job.get('task_notes', ''))
        details_dlg.input.setText(json.dumps(job.get('params', ''), indent=4, sort_keys=True))
        details_dlg.output.setText(json.dumps(job.get('results', ''), indent=4, sort_keys=True))

        details_dlg.show()
        details_dlg.exec_()

    def btn_download(self):
        # Use set below in case multiple cells within the same row are selected
        jobs_list = self.jobs.list()

        rows = set(list(index.row() for index in self.jobs_view.selectedIndexes()))
        job_ids = [self.proxy_model.index(row, 4).data() for row in rows]
        jobs = [job for job in jobs_list if job['id'] in job_ids]

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
                                                          QSettings().value("trends_earth/advanced/base_data_directory", None),
                                                          self.tr('Base filename (*.json)'))

                    # Strip the extension so that it is a basename
                    f = os.path.splitext(f)[0]

                    if f:
                        if os.access(os.path.dirname(f), os.W_OK):
                            # QSettings().setValue("LDMP/output_dir", os.path.dirname(f))
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
            job = jobs_list[row]
            log(u"Processing job {}.".format(job.get('id', None)))
            result_type = job['results'].get('type')
            if result_type == 'CloudResults':
                download_cloud_results(job, f, self.tr)
            elif result_type == 'TimeSeriesTable':
                download_timeseries(job, self.tr)
            else:
                raise ValueError("Unrecognized result type in download results: {}".format(result_type))


class JobsTableModel(QAbstractTableModel):
    def __init__(self, datain: List[dict], parent=None, *args):
        QAbstractTableModel.__init__(self, parent, *args)
        self.jobs = datain

        # Column names as tuples with json name in [0], pretty name in [1]
        # Note that the columns with json names set to to INVALID aren't loaded
        # into the shell, but shown from a widget.
        colname_tuples = [('task_name', self.tr('Task name')),
                          ('script_name', self.tr('Job')),
                          ('start_date', self.tr('Start time')),
                          ('end_date', self.tr('End time')),
                          ('id', self.tr('ID')),
                          ('status', self.tr('Status')),
                          ('INVALID', self.tr('Details'))]
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
            value = self.jobs[index.row()].get(self.colnames_json[index.column()], '')
            if isinstance(value, datetime.datetime):
                value = Job.datetimeRepr(value)
            return value
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
                    QgsLogger.debug(tr_jobs.tr(u"No download necessary for tile already in cache: {}".format(urls[n]['url'])), debuglevel=3)
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
        do_download = True
        if os.access(out_file, os.R_OK):
            if check_hash_against_etag(url['url'], out_file, binascii.hexlify(base64.b64decode(url['md5Hash'])).decode()):
                QgsLogger.debug(tr_jobs.tr(u"No download necessary for Dataset in cache: {}".format(out_file)), debuglevel=3)
                do_download = False
            else:
                do_download = True

        if do_download:
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

    mb.pushMessage(tr_jobs.tr("Downloaded"),
                   tr_jobs.tr(u"Downloaded results to {}".format(out_file)),
                   level=0, duration=5)


def download_timeseries(job, tr):
    log("Processing timeseries results...")
    table = job['results'].get('table', None)
    if not table:
        return None
    data = [x for x in table if x['name'] == 'mean'][0]
    dlg_plot = DlgPlotTimeries()
    labels = {'title': job['task_name'],
              'bottom': tr_jobs.tr('Time'),
              'left': [tr_jobs.tr('Integrated NDVI'), tr_jobs.tr('NDVI x 10000')]}
    dlg_plot.plot_data(data['time'], data['y'], labels)
    dlg_plot.show()
    dlg_plot.exec_()


################################################################################
# Job class and Schema for Job descriptor build from APIResponseSchema
class Job(QObject):

    # TODO: create a uniform way to manage Jobs. or self.jobs is a list of dict 
    # or a list of Job instances. Temporarly maintaining the two structure to reduce
    # side effects

    # emit signal when a Job is dumped (useful in case have to update Datasets)
    dumped = pyqtSignal(str) 

    def __init__(self, response: APIResponseSchema):
        super().__init__()

        QgsLogger.debug('* Build Job from response: ' + pprint.pformat(response), debuglevel=5)

        self.raw = response

        self.response = {}
        self.response['id'] = response.get('id', 'Unknown')
        self.response['start_date'] = response.get('start_date', datetime.datetime(1,1,1,0,0))
        self.response['end_date'] = response.get('end_date', datetime.datetime(1,1,1,0,0))
        self.response['status'] = response.get('status', '')
        self.response['progress'] = response.get('progress', 0)
        self.response['params'] = response.get('params', {})
        self.response['results'] = response.get('results', None)
        self.response['script'] = response.get('script', {})
        self.response['logs'] = response.get('logs', '')

    @property
    def status(self) -> str:
        # return processing status
        return self.response['status']

    @property
    def progress(self) -> int:
        # return processing progress
        return self.response['progress']

    @property
    def taskName(self) -> Optional[str]:
        return self.response['params'].get('task_name', '')

    @property
    def scriptName(self) -> Optional[str]:
        return self.response['script'].get('name', '')

    @property
    def runId(self) -> str:
        return self.response['id']

    @property
    def startDate(self) -> datetime.datetime:
        return self.response['start_date']

    @property
    def results(self) -> Optional[dict]:
        return self.response['results']

    @staticmethod
    def datetimeRepr(dt: datetime.datetime) -> str:
        return datetime.datetime.strftime(dt, '%Y/%m/%d (%H:%M)')

    @staticmethod
    def toDatetime(dt: str) -> datetime.datetime:
        return datetime.datetime.strptime(dt, '%Y/%m/%d (%H:%M)')

    def dump(self) -> str:
        """Dump Job as JSON in a programmatically set folder with a programmaticaly set filename.
        """
        # create path and filname where to dump Job descriptor
        out_path = ''
        base_data_directory = QSettings().value("trends_earth/advanced/base_data_directory", None, type=str)
        out_path = os.path.join(base_data_directory, 'jobs')

        # set location where to save basing on script(alg) used
        script_name = self.response['script']['name']
        components = script_name.split()
        components = components[:-1] if len(components) > 1 else components # eventually remove version that return when get exeutions list
        formatted_script_name = '-'.join(components) # remove al version and substitutes ' ' with '-'
        formatted_script_name = formatted_script_name.lower()

        # get alg group to setup subfolder
        group = get_script_group(formatted_script_name)
        if not group:
            log(tr_jobs.tr('Cannot get group of the script: ') + formatted_script_name)
            group = 'UNKNOW_GROUP_FOR_' + formatted_script_name

        # get exectuion date as subfolder name
        processing_date_string = self.response['start_date'].strftime('%Y_%m_%d')

        out_path = os.path.join(out_path, group, processing_date_string)
        if not os.path.exists(out_path):
            os.makedirs(out_path)

        job_descriptor_file_name = self.response['id'] + '.json'
        job_descriptor_file_name = os.path.join(out_path, job_descriptor_file_name)
        QgsLogger.debug('* Dump job descriptor into file: '+ job_descriptor_file_name, debuglevel=4)

        job_schema = JobSchema()
        with open(job_descriptor_file_name, 'w') as f:
            json_to_write = json.dump(
                job_schema.dump(self),
                f, default=json_serial, sort_keys=True, indent=4, separators=(',', ': ')
            )
        self.dumped.emit(job_descriptor_file_name)
        return job_descriptor_file_name


@singleton
class Jobs(QObject):
    """Singleton container to separate Dialog to Job operations as retrieve and update."""

    updated = pyqtSignal()
    jobsStore = {}
    lock = threading.RLock()

    def __init__(self):
        super().__init__()

    def set(self, jobs_dict: Optional[List[dict]] = None):
        with self.lock:
            # remove previous jobs but not trigger event
            self.reset(emit=False)

            if jobs_dict is None:
                return

            # set new ones
            for job_dict in jobs_dict:
                self.append(job_dict)

        self.updated.emit()

    def sync(self) -> None:
        """Sync Jobs from cache."""
        try:
            jobs_cache = json.loads(QSettings().value("LDMP/jobs_cache", '{}'))
        except TypeError:
            # For backward compatibility need to handle case of jobs caches 
            # that were stored inappropriately in past version of Trends.Earth
            jobs_cache = {}
        if jobs_cache is not {}:
            self.set(jobs_cache)

        # remove any Job not present in the jobs_cache
        base_data_directory = QSettings().value("trends_earth/advanced/base_data_directory", None, type=str)
        if not base_data_directory:
            return
        jobs_subpath = os.path.join(base_data_directory, 'Jobs')

        current_jobs = list(traverse(jobs_subpath))
        for job_json in current_jobs:
            # check if job descriptor is in job cache
            if job_json in self.jobsStore.keys():
                continue

            try:
                os.remove(job_json)
            except:
                pass

    def append(self, job_dict: dict) -> (str, Job):
        """Append a job dictionay and Job json contrepart in base_data_directory."""
        # save Job descriptor in data directory
        # in this way there is also a mimimum sanity check
        # NOTE! need to adapt start and stop date to datetime object and not string to be used in 
        # JobSchema based on APIResponseSchema
        cloned_job = dict(job_dict)

        if isinstance(cloned_job['start_date'], str):
            cloned_job['start_date'] = Job.toDatetime(cloned_job['start_date'])
        cloned_job['start_date'] = cloned_job['start_date'].replace(tzinfo=tz.tzutc())
        if isinstance(cloned_job['end_date'], str):
            cloned_job['end_date'] = Job.toDatetime(cloned_job['end_date'])
        cloned_job['end_date'] = cloned_job['end_date'].replace(tzinfo=tz.tzutc())
        cloned_job['end_date'] = cloned_job['end_date'].astimezone(tz.tzlocal())

        schema = JobSchema()
        response = schema.load(cloned_job, partial=True, unknown=marshmallow.INCLUDE)
        job = Job(response)
        dump_file_name = job.dump() # doing save in default location

        # add in memory store .e.g a dictionary
        self.jobsStore[dump_file_name] = job

        return (dump_file_name, job)

    def list(self):
        """Return response dictionary generated the Job.

        This method is to manitain good compatibility with older code e.g. with minimal refactoring
        """
        return [ job.raw for job in self.jobsStore.values() ]

    def jobById(self, id: str) -> Optional[Tuple[str, Job]]:
        """Return Job and related descriptor asociated file."""
        jobs = [(k, j) for k,j in self.jobsStore.items() if j.runId == id]
        return jobs[0] if len(jobs) else None

    def classes(self):
        return [ job for job in self.jobsStore.values() ]

    def reset(self, emit: bool = True):
        """Remove any jobs and related json contrepart."""
        # remove any json of the available Jobs in self.jobs
        with self.lock:
            for file_name in self.jobsStore.keys():
                try:
                    os.remove(file_name)
                except:
                    pass
            self.jobsStore = {}

        if emit:
            self.updated.emit()

class JobSchema(marshmallow.Schema):
    response = marshmallow.fields.Nested(APIResponseSchema, many=False)
