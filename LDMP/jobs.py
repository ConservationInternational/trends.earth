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

from PyQt4 import QtGui
from PyQt4.QtCore import QSettings, QDate, QAbstractTableModel, Qt

from LDMP import log

from qgis.core import QgsColorRampShader, QgsRasterShader, QgsSingleBandPseudoColorRenderer

from qgis.utils import iface
mb = iface.messageBar()

from qgis.gui import QgsMessageBar

from LDMP.gui.DlgJobs import Ui_DlgJobs

from LDMP.download import download_file
from LDMP.api import API

def get_scripts(api):
    scripts = api.get_script()
    # The scripts endpoint lists scripts in a list of dictionaries. Convert 
    # this to a dictionary keyed by script id
    scripts_dict = {}
    for script in scripts:
        script_id = script.pop('id')
        scripts_dict[script_id] = script
    return scripts_dict

class DlgJobs(QtGui.QDialog, Ui_DlgJobs):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgJobs, self).__init__(parent)

        self.settings = QSettings()

        self.setupUi(self)

        self.api = API()

        self.bar = QgsMessageBar()
        self.bar.setSizePolicy(QtGui.QSizePolicy.Minimum, QtGui.QSizePolicy.Fixed)
        self.layout().addWidget(self.bar)

        self.refresh.clicked.connect(self.btn_refresh)
        self.download.clicked.connect(self.btn_download)

        # Only enable download button if a job is selected
        self.download.setEnabled(False)

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
        # TODO: Handle loss of internet and connection error on button refresh
        self.bar.pushMessage("Updating", "Contacting server to update job list.", level=QgsMessageBar.INFO)
        self.jobs = self.api.get_execution(user=self.settings.value("LDMP/user_id", None))
        if self.jobs:
            # Add script names and descriptions to jobs list
            self.scripts = get_scripts(self.api)
            for job in self.jobs:
                script = job.get('script_id', None)
                if script:
                    job['script_name'] = self.scripts[job['script_id']]['name']
                    job['script_description'] = self.scripts[job['script_id']]['description']
                else:
                    # Handle case of scripts that have been removed or that are 
                    # no longer supported
                    job['script_name'] =  'Script not found'
                    job['script_description'] = 'Script not found'

            # Pretty print dates
            for job in self.jobs:
                job['start_date'] = datetime.datetime.strftime(job['start_date'], '%a %b %d (%H:%M)')
                job['end_date'] = datetime.datetime.strftime(job['end_date'], '%a %b %d (%H:%M)')

            tablemodel = JobsTableModel(self.jobs, self)
            self.jobs_view.setModel(tablemodel)
            self.jobs_view.horizontalHeader().setResizeMode(QtGui.QHeaderView.ResizeToContents)
            self.jobs_view.setSelectionBehavior(QtGui.QAbstractItemView.SelectRows)
            self.jobs_view.selectionModel().selectionChanged.connect(self.selection_changed)
            return True
        else:
            return False

    def btn_download(self):
        download_dir = self.settings.value("LDMP/download_dir", None)
        while True:
            download_dir = QtGui.QFileDialog.getExistingDirectory(self, self.tr("Directory to save files"), download_dir)
            if os.access(download_dir, os.W_OK):
                self.settings.setValue("LDMP/download_dir", download_dir)
                break
            else:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                        self.tr("Cannot write to {}. Choose a different folder.".format(download_dir), None))

        rows = list(set(index.row() for index in self.jobs_view.selectedIndexes()))
        for row in rows:
            job = self.jobs[row]
            if job['results'].get('type') == 'productivity_trajectory':
                download_prod_traj(job, download_dir)
            elif job['results'].get('type') == 'land_cover':
                download_land_cover(job, download_dir)
        self.close()

def download_land_cover(job, download_dir):
    for dataset in job['results'].get('datasets'):
        for url in dataset.get('urls'):
            #TODO style layer and set layer name based on the info in the dataset json file
            log("Downloading {}".format(url))
            outfile = os.path.join(download_dir, url['url'].rsplit('/', 1)[-1])
            #TODO: Check if this file was already downloaded
            download_file(url['url'], outfile)
            if dataset['dataset'] == 'lc_baseline':
                style_land_cover_lc_baseline(outfile)
            elif dataset['dataset'] == 'lc_target':
                style_land_cover_lc_target(outfile)
            elif dataset['dataset'] == 'lc_change':
                style_land_cover_lc_change(outfile)
            elif dataset['dataset'] == 'land_deg':
                style_land_cover_land_deg(outfile)
            else:
                raise ValueError("Unrecognized dataset type in download results: {}".format(dataset['dataset']))

def style_land_cover_lc_baseline(outfile):
    layer_lc_baseline = iface.addRasterLayer(outfile, 'Land cover (baseline)')
    fcn = QgsColorRampShader()
    fcn.setColorRampType(QgsColorRampShader.EXACT)
    lst = [QgsColorRampShader.ColorRampItem(1, QtGui.QColor('#a50f15'), 'Cropland'),
           QgsColorRampShader.ColorRampItem(2, QtGui.QColor('#006d2c'), 'Forest land'),
           QgsColorRampShader.ColorRampItem(3, QtGui.QColor('#d8d800'), 'Grassland'),
           QgsColorRampShader.ColorRampItem(4, QtGui.QColor('#08519c'), 'Wetlands'),
           QgsColorRampShader.ColorRampItem(5, QtGui.QColor('#54278f'), 'Settlements'),
           QgsColorRampShader.ColorRampItem(6, QtGui.QColor('#252525'), 'Other land')]
    fcn.setColorRampItemList(lst)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(fcn)
    pseudoRenderer = QgsSingleBandPseudoColorRenderer(layer_lc_baseline.dataProvider(), 1, shader)
    layer_lc_baseline.setRenderer(pseudoRenderer)
    layer_lc_baseline.triggerRepaint()
    iface.legendInterface().refreshLayerSymbology(layer_lc_baseline)

def style_land_cover_lc_target(outfile):
    layer_lc_target = iface.addRasterLayer(outfile, 'Land cover (target)')
    fcn = QgsColorRampShader()
    fcn.setColorRampType(QgsColorRampShader.EXACT)
    lst = [QgsColorRampShader.ColorRampItem(1, QtGui.QColor('#a50f15'), 'Cropland'),
           QgsColorRampShader.ColorRampItem(2, QtGui.QColor('#006d2c'), 'Forest land'),
           QgsColorRampShader.ColorRampItem(3, QtGui.QColor('#d8d800'), 'Grassland'),
           QgsColorRampShader.ColorRampItem(4, QtGui.QColor('#08519c'), 'Wetlands'),
           QgsColorRampShader.ColorRampItem(5, QtGui.QColor('#54278f'), 'Settlements'),
           QgsColorRampShader.ColorRampItem(6, QtGui.QColor('#252525'), 'Other land')]
    fcn.setColorRampItemList(lst)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(fcn)
    pseudoRenderer = QgsSingleBandPseudoColorRenderer(layer_lc_target.dataProvider(), 1, shader)
    layer_lc_target.setRenderer(pseudoRenderer)
    layer_lc_target.triggerRepaint()
    iface.legendInterface().refreshLayerSymbology(layer_lc_target)

def style_land_cover_lc_change(outfile):
    layer_lc_change = iface.addRasterLayer(outfile, 'Land cover change')
    fcn = QgsColorRampShader()
    fcn.setColorRampType(QgsColorRampShader.EXACT)
    lst = [QgsColorRampShader.ColorRampItem(11, QtGui.QColor('#a50f15'), 'Croplands-Croplands'),
           QgsColorRampShader.ColorRampItem(12, QtGui.QColor('#de2d26'), 'Croplands-Forest land'),
           QgsColorRampShader.ColorRampItem(13, QtGui.QColor('#fb6a4a'), 'Croplands-Grassland'),
           QgsColorRampShader.ColorRampItem(14, QtGui.QColor('#fc9272'), 'Croplands-Wetlands'),
           QgsColorRampShader.ColorRampItem(15, QtGui.QColor('#fcbba1'), 'Croplands-Settlements'),
           QgsColorRampShader.ColorRampItem(16, QtGui.QColor('#fee5d9'), 'Croplands-Other land'),
           QgsColorRampShader.ColorRampItem(22, QtGui.QColor('#006d2c'), 'Forest land-Forest land'),
           QgsColorRampShader.ColorRampItem(21, QtGui.QColor('#31a354'), 'Forest land-Croplands'),
           QgsColorRampShader.ColorRampItem(23, QtGui.QColor('#74c476'), 'Forest land-Grassland'),
           QgsColorRampShader.ColorRampItem(24, QtGui.QColor('#a1d99b'), 'Forest land-Wetlands'),
           QgsColorRampShader.ColorRampItem(25, QtGui.QColor('#c7e9c0'), 'Forest land-Settlements'),
           QgsColorRampShader.ColorRampItem(26, QtGui.QColor('#edf8e9'), 'Forest land-Other land'),
           QgsColorRampShader.ColorRampItem(33, QtGui.QColor('#d8d800'), 'Grassland-Grassland'),
           QgsColorRampShader.ColorRampItem(31, QtGui.QColor('#bebe00'), 'Grassland-Croplands'),
           QgsColorRampShader.ColorRampItem(32, QtGui.QColor('#a5a500'), 'Grassland-Forest land'),
           QgsColorRampShader.ColorRampItem(34, QtGui.QColor('#8b8b00'), 'Grassland-Wetlands'),
           QgsColorRampShader.ColorRampItem(35, QtGui.QColor('#727200'), 'Grassland-Settlements'),
           QgsColorRampShader.ColorRampItem(36, QtGui.QColor('#585800'), 'Grassland-Other land'),
           QgsColorRampShader.ColorRampItem(44, QtGui.QColor('#08519c'), 'Wetlands-Wetlands'),
           QgsColorRampShader.ColorRampItem(41, QtGui.QColor('#3182bd'), 'Wetlands-Croplands'),
           QgsColorRampShader.ColorRampItem(42, QtGui.QColor('#6baed6'), 'Wetlands-Forest land'),
           QgsColorRampShader.ColorRampItem(43, QtGui.QColor('#9ecae1'), 'Wetlands-Grassland'),
           QgsColorRampShader.ColorRampItem(45, QtGui.QColor('#c6dbef'), 'Wetlands-Settlements'),
           QgsColorRampShader.ColorRampItem(46, QtGui.QColor('#eff3ff'), 'Wetlands-Other land'),
           QgsColorRampShader.ColorRampItem(55, QtGui.QColor('#54278f'), 'Settlements-Settlements'),
           QgsColorRampShader.ColorRampItem(51, QtGui.QColor('#756bb1'), 'Settlements-Croplands'),
           QgsColorRampShader.ColorRampItem(52, QtGui.QColor('#9e9ac8'), 'Settlements-Forest land'),
           QgsColorRampShader.ColorRampItem(53, QtGui.QColor('#bcbddc'), 'Settlements-Grassland'),
           QgsColorRampShader.ColorRampItem(54, QtGui.QColor('#dadaeb'), 'Settlements-Wetlands'),
           QgsColorRampShader.ColorRampItem(56, QtGui.QColor('#f2f0f7'), 'Settlements-Other land'),
           QgsColorRampShader.ColorRampItem(66, QtGui.QColor('#252525'), 'Other land-Other land'),
           QgsColorRampShader.ColorRampItem(61, QtGui.QColor('#636363'), 'Other land-Croplands'),
           QgsColorRampShader.ColorRampItem(62, QtGui.QColor('#969696'), 'Other land-Forest land'),
           QgsColorRampShader.ColorRampItem(63, QtGui.QColor('#bdbdbd'), 'Other land-Grassland'),
           QgsColorRampShader.ColorRampItem(64, QtGui.QColor('#d9d9d9'), 'Other land-Wetlands'),
           QgsColorRampShader.ColorRampItem(65, QtGui.QColor('#f7f7f7'), 'Other land-Settlements')]
    fcn.setColorRampItemList(lst)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(fcn)
    pseudoRenderer = QgsSingleBandPseudoColorRenderer(layer_lc_change.dataProvider(), 1, shader)
    layer_lc_change.setRenderer(pseudoRenderer)
    layer_lc_change.triggerRepaint()
    layer_lc_change.triggerRepaint()
    iface.legendInterface().refreshLayerSymbology(layer_lc_change)

def style_land_cover_land_deg(outfile):
    layer_deg = iface.addRasterLayer(outfile, 'Land cover (degradation)')
    fcn = QgsColorRampShader()
    fcn.setColorRampType(QgsColorRampShader.EXACT)
    #TODO The GPG doesn't seem to allow for possibility of improvement...?
    lst = [QgsColorRampShader.ColorRampItem(-1, QtGui.QColor(153, 51, 4), 'Degradation'),
           QgsColorRampShader.ColorRampItem(0, QtGui.QColor(245, 245, 219), 'Stable'),
           QgsColorRampShader.ColorRampItem(1, QtGui.QColor(0, 140, 121), 'Improvement')]
    fcn.setColorRampItemList(lst)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(fcn)
    pseudoRenderer = QgsSingleBandPseudoColorRenderer(layer_deg.dataProvider(), 1, shader)
    layer_deg.setRenderer(pseudoRenderer)
    layer_deg.triggerRepaint()
    iface.legendInterface().refreshLayerSymbology(layer_deg)

def download_prod_traj(job, download_dir):
    for dataset in job['results'].get('datasets'):
        for url in dataset.get('urls'):
            #TODO style layer and set layer name based on the info in the dataset json file
            log("Downloading {}".format(url))
            outfile = os.path.join(download_dir, url['url'].rsplit('/', 1)[-1])
            #TODO: Check if this file was already downloaded
            download_file(url['url'], outfile)
            style_prod_traj_trend(outfile)
            style_prod_traj_signif(outfile)

def style_prod_traj_trend(outfile):
    # Significance layer
    layer_signif = iface.addRasterLayer(outfile, 'NDVI Trends (significance)')
    fcn = QgsColorRampShader()
    fcn.setColorRampType(QgsColorRampShader.EXACT)
    lst = [QgsColorRampShader.ColorRampItem(-1, QtGui.QColor(153, 51, 4), 'Significant decrease'),
           QgsColorRampShader.ColorRampItem(0, QtGui.QColor(245, 245, 219), 'No significant change'),
           QgsColorRampShader.ColorRampItem(1, QtGui.QColor(0, 140, 121), 'Significant increase'),
           QgsColorRampShader.ColorRampItem(2, QtGui.QColor(58, 77, 214), 'Water'),
           QgsColorRampShader.ColorRampItem(3, QtGui.QColor(192, 105, 223), 'Urban land cover')]
    fcn.setColorRampItemList(lst)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(fcn)
    pseudoRenderer = QgsSingleBandPseudoColorRenderer(layer_signif.dataProvider(), 2, shader)
    layer_signif.setRenderer(pseudoRenderer)
    layer_signif.triggerRepaint()
    iface.legendInterface().refreshLayerSymbology(layer_signif)

def style_prod_traj_signif(outfile):
    # Trends layer
    layer_ndvi = iface.addRasterLayer(outfile, 'NDVI Trends')
    fcn = QgsColorRampShader()
    fcn.setColorRampType(QgsColorRampShader.INTERPOLATED)
    lst = [QgsColorRampShader.ColorRampItem(-100, QtGui.QColor(153, 51, 4), '-100 (declining)'),
           QgsColorRampShader.ColorRampItem(0, QtGui.QColor(245, 245, 219), '0 (stable)'),
           QgsColorRampShader.ColorRampItem(100, QtGui.QColor(0, 140, 121), '100 (increasing)')]
    fcn.setColorRampItemList(lst)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(fcn)
    pseudoRenderer = QgsSingleBandPseudoColorRenderer(layer_ndvi.dataProvider(), 1, shader)
    layer_ndvi.setRenderer(pseudoRenderer)
    layer_ndvi.triggerRepaint()
    iface.legendInterface().refreshLayerSymbology(layer_ndvi)

class JobsTableModel(QAbstractTableModel):
    def __init__(self, datain, parent=None, *args):
        QAbstractTableModel.__init__(self, parent, *args)
        self.jobs = datain

        # Column names as tuples with json name in [0], pretty name in [1]
        colname_tuples = [('script_name', 'Job'),
                          ('start_date', 'Start time'),
                          ('end_date', 'End time'),
                          ('status', 'Status'),
                          ('progress', 'Progress')]
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
        return self.jobs[index.row()][self.colnames_json[index.column()]]

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.colnames_pretty[section]
        return QAbstractTableModel.headerData(self, section, orientation, role)
