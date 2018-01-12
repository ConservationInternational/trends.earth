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

import os
import json
import re

import datetime
from PyQt4 import QtGui
from PyQt4.QtCore import QSettings, QDate, QAbstractTableModel, Qt

from qgis.utils import iface
mb = iface.messageBar()

from qgis.gui import QgsMessageBar

from LDMP import __version__
from LDMP.gui.DlgJobs import Ui_DlgJobs
from LDMP.gui.DlgJobsDetails import Ui_DlgJobsDetails
from LDMP.plot import DlgPlotTimeries

from LDMP import log
from LDMP.download import Download, check_hash_against_etag, DownloadError
from LDMP.load_data import add_layer
from LDMP.api import get_script, get_user_email, get_execution


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    raise TypeError("Type {} not serializable".format(type(obj)))


def create_json_metadata(job, outfile, file_format):
    outfile = os.path.splitext(outfile)[0] + '.json'
    job['raw']['results']['local_format'] = file_format
    job['raw']['results']['ldmp_version'] = __version__
    with open(outfile, 'w') as outfile:
        json.dump(job['raw'], outfile, default=json_serial, sort_keys=True,
                  indent=4, separators=(',', ': '))


def get_scripts():
    scripts = get_script()
    if not scripts:
        return None
    # The scripts endpoint lists scripts in a list of dictionaries. Convert
    # this to a dictionary keyed by script id
    scripts_dict = {}
    for script in scripts:
        script_id = script.pop('id')
        scripts_dict[script_id] = script
    return scripts_dict


class DlgJobsDetails(QtGui.QDialog, Ui_DlgJobsDetails):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgJobsDetails, self).__init__(parent)

        self.setupUi(self)


class DlgJobs(QtGui.QDialog, Ui_DlgJobs):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgJobs, self).__init__(parent)

        self.settings = QSettings()

        self.setupUi(self)

        # Set a variable used to record the necessary window width to view all
        # columns
        self._full_width = None

        self.bar = QgsMessageBar()
        self.bar.setSizePolicy(QtGui.QSizePolicy.Minimum, QtGui.QSizePolicy.Fixed)
        self.layout().addWidget(self.bar, 0, 0, Qt.AlignTop)

        jobs_cache = self.settings.value("LDMP/jobs_cache", None)
        if jobs_cache:
            self.jobs = jobs_cache
            self.update_jobs_table()

        self.refresh.clicked.connect(self.btn_refresh)
        self.download.clicked.connect(self.btn_download)

        # Only enable download button if a job is selected
        self.download.setEnabled(False)

    def resizeWindowToColumns(self):
        if not self._full_width:
            margins = self.layout().contentsMargins()
            self._full_width = margins.left() + margins.right() + \
                self.jobs_view.frameWidth() * 2 + \
                self.jobs_view.verticalHeader().width() + \
                self.jobs_view.horizontalHeader().length() + \
                self.jobs_view.style().pixelMetric(QtGui.QStyle.PM_ScrollBarExtent)
        self.resize(self._full_width, self.height())

    def selection_changed(self):
        if not self.jobs_view.selectedIndexes():
            self.download.setEnabled(False)
        else:
            rows = list(set(index.row() for index in self.jobs_view.selectedIndexes()))
            for row in rows:
                # Don't set button to enabled if any of the tasks aren't yet
                # finished
                if self.jobs[row]['status'] != 'FINISHED':
                    self.download.setEnabled(False)
                    return
            self.download.setEnabled(True)

    def btn_refresh(self):
        self.refresh.setEnabled(False)
        email = get_user_email()
        if email:
            start_date = datetime.datetime.now() + datetime.timedelta(-29)
            self.jobs = get_execution(date=start_date.strftime('%Y-%m-%d'))
            if self.jobs:
                # Add script names and descriptions to jobs list
                self.scripts = get_scripts()
                if not self.scripts:
                    self.refresh.setEnabled(True)
                    return False
                for job in self.jobs:
                    # self.jobs will have prettified data for usage in table,
                    # so save a backup of the original data under key 'raw'
                    job['raw'] = job.copy()
                    script = job.get('script_id', None)
                    if script:
                        job['script_name'] = self.scripts[job['script_id']]['name']
                        # Clean up the script name so the version tag doesn't 
                        # look so odd
                        job['script_name'] = re.sub('([0-9]+)_([0-9]+)$', '(v\g<1>.\g<2>)', job['script_name'])
                        job['script_description'] = self.scripts[job['script_id']]['description']
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

                self.refresh.setEnabled(True)
                return True
        self.refresh.setEnabled(True)
        return False

    def update_jobs_table(self):
        if self.jobs:
            table_model = JobsTableModel(self.jobs, self)
            proxy_model = QtGui.QSortFilterProxyModel()
            proxy_model.setSourceModel(table_model)
            self.jobs_view.setModel(proxy_model)

            # Add "Notes" buttons in cell
            for row in range(0, len(self.jobs)):
                btn = QtGui.QPushButton(self.tr("Details"))
                btn.clicked.connect(self.btn_details)
                self.jobs_view.setIndexWidget(proxy_model.index(row, 5), btn)

            self.jobs_view.horizontalHeader().setResizeMode(QtGui.QHeaderView.ResizeToContents)
            #self.jobs_view.horizontalHeader().setResizeMode(QtGui.QHeaderView.ResizeToContents)
            self.jobs_view.setSelectionBehavior(QtGui.QAbstractItemView.SelectRows)
            self.jobs_view.selectionModel().selectionChanged.connect(self.selection_changed)

            #self.resizeWindowToColumns()

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
        rows = list(set(index.row() for index in self.jobs_view.selectedIndexes()))

        filenames = []
        for row in rows:
            job = self.jobs[row]
            # Check if we need a download filename - some tasks don't need to save
            # data, but if any of the chosen \tasks do, then we need to choose a
            # folder. Right now only TimeSeriesTable doesn't need a filename.
            if job['results'].get('type') != 'TimeSeriesTable':
                f = None
                while not f:
                    # Setup a string to use in filename window
                    if job['task_name']:
                        job_info = '{} ({})'.format(job['script_name'], job['task_name'])
                    else:
                        job_info = job['script_name']
                    f = QtGui.QFileDialog.getSaveFileName(self,
                                                          self.tr('Choose a filename downloading results of: {}'.format(job_info)),
                                                          self.settings.value("LDMP/download_dir", None),
                                                          self.tr('Base filename (*.json)'))

                    # Strip the extension so that it is a basename
                    f = os.path.splitext(f)[0]

                    if f:
                        if os.access(os.path.dirname(f), os.W_OK):
                            self.settings.setValue("LDMP/download_dir", os.path.dirname(f))
                            log("Downloading results to {} with basename {}".format(os.path.dirname(f), os.path.basename(f)))
                        else:
                            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                                       self.tr("Cannot write to {}. Choose a different base filename.".format(f)))
                    else:
                            return False

                filenames.append(f)
            else:
                filenames.append(None)

        self.close()

        for row, f in zip(rows, filenames):
            job = self.jobs[row]
            log("Processing job {}".format(job))
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
        colname_tuples = [('task_name', QtGui.QApplication.translate('LDMPPlugin', 'Task name')),
                          ('script_name', QtGui.QApplication.translate('LDMPPlugin', 'Job')),
                          ('start_date', QtGui.QApplication.translate('LDMPPlugin', 'Start time')),
                          ('end_date', QtGui.QApplication.translate('LDMPPlugin', 'End time')),
                          ('status', QtGui.QApplication.translate('LDMPPlugin', 'Status')),
                          ('INVALID', QtGui.QApplication.translate('LDMPPlugin', 'Details'))]
        self.colnames_pretty = [x[1] for x in colname_tuples]
        self.colnames_json = [x[0] for x in colname_tuples]

    def rowCount(self, parent):
        return len(self.jobs)

    def columnCount(self, parent):
        return len(self.colnames_json)

    def data(self, index, role):
        if not index.isValid():
            return None
        elif role != Qt.DisplayRole:
            return None
        return self.jobs[index.row()].get(self.colnames_json[index.column()], '')

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.colnames_pretty[section]
        return QAbstractTableModel.headerData(self, section, orientation, role)


def download_result(url, outfile, job):
    worker = Download(url, outfile)
    worker.start()
    if worker.get_resp():
        create_json_metadata(job, outfile, 'tif')
        return check_hash_against_etag(url, outfile)
    else:
        return None


def download_cloud_results(job, f, tr):
    results = job['results']
    if len(results['urls']['files']) > 1:
        raise DownloadError('GEE tasks resulting in multiple output files are not yet supported by trends.earth.')
    out_file = f + '.tif'
    resp = download_result(results['urls']['base'] + '/' + results['urls']['files'][0], out_file, job)
    if not resp:
        return
    else:
        for band in results['bands']:
            if band['add_to_map']:
                add_layer(out_file, band)
        mb.pushMessage(tr("Downloaded"),
                       tr("Downloaded results to {}".format(out_file)),
                       level=0, duration=5)


def download_timeseries(job, tr):
    log("processing timeseries results...")
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
