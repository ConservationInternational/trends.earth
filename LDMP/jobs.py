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
import json

import datetime
from math import floor, log10

import numpy as np
from osgeo import gdal

from PyQt4 import QtGui
from PyQt4.QtCore import QSettings, QDate, QAbstractTableModel, Qt, QCoreApplication

from qgis.core import QgsColorRampShader, QgsRasterShader, QgsSingleBandPseudoColorRenderer, QgsRasterBandStats

from qgis.utils import iface
mb = iface.messageBar()

from qgis.gui import QgsMessageBar

from LDMP.gui.DlgJobs import Ui_DlgJobs
from LDMP.gui.DlgJobsDetails import Ui_DlgJobsDetails
from LDMP.plot import DlgPlotTimeries

from LDMP import log
from LDMP.download import Download, check_hash_against_etag
from LDMP.api import get_script, get_user_email, get_execution

def tr(t):
    return QCoreApplication.translate('LDMPPlugin', t)

# Store layer titles and label text in a dictionary here so that it can be 
# translated - if it were in the syles JSON then gettext would not have access 
# to these strings.
style_text_dict = {
        # Productivity trajectory
        'prod_traj_trend_title': tr('Productivity trajectory (NDVI x 10000 / yr)'),
        'prod_traj_trend_min': tr('{}'),
        'prod_traj_trend_zero': tr('0'),
        'prod_traj_trend_max': tr('{}'),

        'prod_traj_signif_title': tr('Productivity tradecrease (p < .01)'),
        'prod_traj_signif_dec_99': tr('Significant decrease (p < .01)'),
        'prod_traj_signif_dec_95': tr('Significant decrease (p < .05)'),
        'prod_traj_signif_dec_90': tr('Significant decrease (p < .1)'),
        'prod_traj_signif_zero': tr('No significant change'),
        'prod_traj_signif_inc_90': tr('Significant increase (p < .1)'),
        'prod_traj_signif_inc_95': tr('Significant increase (p < .05)'),
        'prod_traj_signif_inc_99': tr('Significant increase (p < .01)'),
        'prod_traj_signif_nodata': tr('No data'),

        # Productivity performance
        'prod_perf_title': tr('Productivity performance'),
        'prod_perf_potential_deg': tr('Potentially degraded'),
        'prod_perf_not_potential_deg': tr('Not potentially degraded'),
        'prod_perf_nodata': tr('No data'),

        # Productivity state
        'prod_state_change_title': tr('Productivity state'),
        'prod_state_change_potential_deg': tr('Potentially degraded'),
        'prod_state_change_stable': tr('Stable'),
        'prod_state_change_potential_improvement': tr('Potentially improved'),
        'prod_state_change_nodata': tr('No data'),


        'prod_state_classes_bl_title': tr('Productivity state baseline classes'),
        'prod_state_classes_bl_nodata': tr('No data'),

        'prod_state_classes_tg_title': tr('Productivity state target classes'),
        'prod_state_classes_tg_nodata': tr('No data'),

        # Land cover
        'lc_bl_title': tr('Land cover (baseline)'),
        'lc_tg_title': tr('Land cover (target)'),
        'lc_tr_title': tr('Land cover (transitions)'),

        'lc_class_forest': tr('Forest'),
        'lc_class_grassland': tr('Grassland'),
        'lc_class_cropland': tr('Cropland'),
        'lc_class_wetland': tr('Wetland'),
        'lc_class_artificial': tr('Artificial area'),
        'lc_class_bare': tr('Bare land'),
        'lc_class_water': tr('Water body'),
        'lc_class_nodata': tr('No data'),

        'lc_tr_forest_persist': tr('Forest persistence'),
        'lc_tr_forest_loss': tr('Forest loss'),
        'lc_tr_grassland_persist': tr('Grassland persistence'),
        'lc_tr_grassland_loss': tr('Grassland loss'),
        'lc_tr_cropland_persist': tr('Cropland persistence'),
        'lc_tr_cropland_loss': tr('Cropland loss'),
        'lc_tr_wetland_persist': tr('Wetland persistence'),
        'lc_tr_wetland_loss': tr('Wetland loss'),
        'lc_tr_artificial_persist': tr('Artificial area persistence'),
        'lc_tr_artificial_loss': tr('Artificial area loss'),
        'lc_tr_bare_persist': tr('Bare land persistence'),
        'lc_tr_bare_loss': tr('Bare land loss'),
        'lc_tr_water_persist': tr('Water body persistence'),
        'lc_tr_water_loss': tr('Water body loss'),
        'lc_tr_nodata': tr('No data'),

        'lc_deg_title': tr('Land cover degradation'),
        'lc_deg_deg': tr('Degradation'),
        'lc_deg_stable': tr('Stable'),
        'lc_deg_imp': tr('Improvement'),
        'lc_deg_nodata': tr('No data'),

        
        # Soil organic carbon
        'soc_2000_title': tr('Soil organic carbon (tons / ha)'),
        'soc_2000_nodata': tr('No data'),

        'soc_deg_title': tr('Soil organic carbon degradation'),
        'soc_deg_deg': tr('Degradation'),
        'soc_deg_stable': tr('Stable'),
        'soc_deg_imp': tr('Improvement'),
        'soc_deg_nodata': tr('No data'),

        # Degradation SDG final layer
        'sdg_prod_combined_title': tr('Productivity degradation (combined - SDG 15.3.1)'),
        'sdg_prod_combined_deg_deg': tr('Degradation'),
        'sdg_prod_combined_deg_stable': tr('Stable'),
        'sdg_prod_combined_deg_imp': tr('Improvement'),
        'sdg_prod_combined_deg_nodata': tr('No data'),

        'combined_sdg_title': tr('Degradation (combined - SDG 15.3.1)'),
        'combined_sdg_deg_deg': tr('Degradation'),
        'combined_sdg_deg_stable': tr('Stable'),
        'combined_sdg_deg_imp': tr('Improvement'),
        'combined_sdg_deg_nodata': tr('No data'),
    }

def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    raise TypeError("Type {} not serializable".format(type(obj)))


def create_json_metadata(job, outfile):
    outfile = os.path.splitext(outfile)[0] + '.json'
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


def _round_to_n(x, sf=3):
    'Function to round a positive value to n significant figures'
    return round(x, -int(floor(log10(x))) + (sf - 1))


#TODO: Figure out how to do block by block percentile
def get_percentile(f, band_info, p):
    '''Get percentiles of a raster dataset by block'''
    ds = gdal.Open(outfile)
    b = ds.GetRasterBand(band_info['band number'])

    block_sizes = b.GetBlockSize()
    x_block_size = block_sizes[0]
    y_block_size = block_sizes[1]
    xsize = b.XSize
    ysize = b.YSize

    for y in xrange(0, ysize, y_block_size):
        if y + y_block_size < ysize:
            rows = y_block_size
        else:
            rows = ysize - y
        for x in xrange(0, xsize, x_block_size):
            if x + x_block_size < xsize:
                cols = x_block_size
            else:
                cols = xsize - x
            d = np.array(b.ReadAsArray(x, y, cols, rows)).astype(np.float)
            for nodata_value in band_info['no data value']:
                d[d == nodata_value] = np.nan
            cutoffs = np.nanpercentile(d, p)
            # get rounded extreme value
            extreme = max([round_to_n(abs(cutoffs[0]), sf), round_to_n(abs(cutoffs[1]), sf)])


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
        # Check if we need a download directory - some tasks don't need to save
        # data, but if any of the chosen \tasks do, then we need to choose a
        # folder.
        need_dir = False
        for row in rows:
            job = self.jobs[row]
            if job['results'].get('type') != 'timeseries':
                need_dir = True
                break

        if need_dir:
            f = QtGui.QFileDialog.getSaveFileName(self,
                                                  self.tr('Choose a base filename for this download'),
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
                    return False
            else:
                return False

        self.close()

        for row in rows:
            job = self.jobs[row]
            log("Processing job {}".format(job))
            if job['results'].get('type') in ['prod_trajectory',
                                              'prod_state',
                                              'prod_performance',
                                              'land_cover',
                                              'soil_organic_carbon']:
                download_job(job, f)
            elif job['results'].get('type') == 'timeseries':
                download_timeseries(job, self.tr)
            elif job['results'].get('type') == 'download':
                download_dataset(job, f, self.tr)
            else:
                raise ValueError("Unrecognized result type in download results: {}".format(job['results'].get('type')))


class DlgJobsDetails(QtGui.QDialog, Ui_DlgJobsDetails):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgJobsDetails, self).__init__(parent)

        self.setupUi(self)


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
        create_json_metadata(job, outfile)
        return check_hash_against_etag(url, outfile)
    else:
        return None


def download_dataset(job, f, tr):
    log("downloading dataset...")
    for dataset in job['results'].get('datasets'):
        for url in dataset.get('urls'):
            log('Output basename: {}'.format(f))
            resp = download_result(url['url'], f, job)
            if not resp:
                return
            mb.pushMessage(tr("Downloaded"),
                           tr("Downloaded dataset to {}".format(f)),
                           level=0, duration=5)


def download_job(job, f):
    log("downloading land_cover results...")
    for dataset in job['results'].get('datasets'):
        for url in dataset.get('urls'):
            resp = download_result(url['url'], f + '.tif', job)
            if not resp:
                return
                add_layer(outfile, band_info, style)
            else:
                raise ValueError("Unrecognized dataset type in download results: {}".format(dataset['dataset']))


def add_layer(f, band_info, style):
    l = iface.addRasterLayer(f, style_text_dict[style['title']])
    if not l.isValid():
        log('Failed to add layer')
        return None

    if style['ramp']['type'] == 'categorical':
        r = []
        for item in style['ramp']['items']:
            r.append(QgsColorRampShader.ColorRampItem(item['value'],
                     QtGui.QColor(item['color']),
                     style_text_dict[item['label']]))

    elif style['ramp']['type'] == 'zero-centered 2 percent stretch':
        # TODO: This should be done block by block to prevent running out of 
        # memory on large rasters - and it should be done in GEE for GEE loaded 
        # rasters.
        # Set a colormap centred on zero, going to the extreme value 
        # significant to three figures (after a 2 percent stretch)
        ds = gdal.Open(f)
        d = np.array(ds.GetRasterBand(band_info['band number']).ReadAsArray()).astype(np.float)
        for nodata_value in band_info['no data value']:
            d[d == nodata_value] = np.nan
        ds = None
        cutoffs = np.nanpercentile(d, [2, 98])
        log('Cutoffs for 2 percent stretch: {}'.format(cutoffs))
        extreme = max([round_to_n(abs(cutoffs[0]), sf),
                       round_to_n(abs(cutoffs[1]), sf)])
        r = []
        r.append(QgsColorRampShader.ColorRampItem(-extreme,
                 QtGui.QColor(style['ramp']['min']['color']),
                 '{}'.format(-extreme)))
        r.append(QgsColorRampShader.ColorRampItem(0,
                 QtGui.QColor(style['ramp']['zero']['color']),
                 '0'))
        r.append(QgsColorRampShader.ColorRampItem(extreme,
                 QtGui.QColor(style['ramp']['max']['color']),
                 '{}'.format(extreme)))
        r.append(QgsColorRampShader.ColorRampItem(style['ramp']['no data']['value'],
                 QtGui.QColor(style['ramp']['no data']['color']),
                 style_text_dict[style['ramp']['no data']['label']]))

    elif style['ramp']['type'] == 'min zero max 98 percent stretch':
        # TODO: This should be done block by block to prevent running out of 
        # memory on large rasters - and it should be done in GEE for GEE loaded 
        # rasters.
        # Set a colormap from zero to 98th percentile significant to
        # three figures (after a 2 percent stretch)
        ds = gdal.Open(f)
        d = np.array(ds.GetRasterBand(band_info['band number']).ReadAsArray()).astype(np.float)
        for nodata_value in band_info['no data value']:
            d[d == nodata_value] = np.nan
        ds = None
        cutoff = round_to_n(np.nanpercentile(d, [98]), 3)
        log('Cutoff for min zero max 98 stretch: {}'.format(cutoff))
        r = []
        r.append(QgsColorRampShader.ColorRampItem(0,
                 QtGui.QColor(style['ramp']['zero']['color']),
                 '0'))
        r.append(QgsColorRampShader.ColorRampItem(cutoff,
                 QtGui.QColor(style['ramp']['max']['color']),
                 '{}'.format(cutoff)))
        r.append(QgsColorRampShader.ColorRampItem(style['ramp']['no data']['value'],
                 QtGui.QColor(style['ramp']['no data']['color']),
                 style_text_dict[style['ramp']['no data']['label']]))

    else:
        log('Failed to load trends.earth style. Adding layer using QGIS defaults.')
        QtGui.QMessageBox.critical(None,
                tr("Error"),
                tr("Failed to load trends.earth style. Adding layer using QGIS defaults."))
        return None

    fcn = QgsColorRampShader()
    if style['ramp']['shader'] == 'exact':
        fcn.setColorRampType("EXACT")
    elif style['ramp']['shader'] == 'discrete':
        fcn.setColorRampType("DISCRETE")
    elif style['ramp']['shader'] == 'interpolated':
        fcn.setColorRampType("INTERPOLATED")
    else:
        raise TypeError("Unrecognized color ramp type: {}".format(style['ramp']['shader']))
    fcn.setColorRampItemList(r)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(fcn)
    pseudoRenderer = QgsSingleBandPseudoColorRenderer(l.dataProvider(),
                                                      band_info['band number'],
                                                      shader)
    l.setRenderer(pseudoRenderer)
    l.triggerRepaint()
    iface.legendInterface().refreshLayerSymbology(l)


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
