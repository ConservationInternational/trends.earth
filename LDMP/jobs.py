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
from urllib import quote_plus

from PyQt4 import QtGui, uic
from PyQt4.QtCore import QSettings, QDate, QAbstractTableModel, Qt

from . import log

from qgis.core import QgsColorRampShader, QgsRasterShader, QgsSingleBandPseudoColorRenderer

from qgis.utils import iface
mb = iface.messageBar()

from qgis.gui import QgsMessageBar

from DlgJobs import Ui_DlgJobs
from download import download_file
from api import API

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
        # TODO: only enable the download button if a job is selected
        self.download.clicked.connect(self.btn_download)

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
            return True
        else:
            return False

    def btn_download(self):
        # Figure out which file(s) to download
        rows = list(set(index.row() for index in self.jobs_view.selectedIndexes()))

        for row in rows:
            job = self.jobs[row]
            #TODO: check that the job produced a geotiff as output
            dir = self.settings.value("LDMP/download_dir", None)
            outfile = QtGui.QFileDialog.getSaveFileName(self, self.tr("Save file"), dir, self.tr("GeoTIFF (*.tif)"))
            dir = self.settings.setValue("LDMP/download_dir", os.path.dirname(outfile))
            self.close()
            for dataset in job['results'].get('datasets'):
                for url in dataset.get('urls'):
                    log("Downloading {}".format(url))
                    #TODO Name output file based on url
                    download_file(url['url'], outfile)
                    #TODO Check hash of downloaded file
                    #TODO style layer and set layer name based on the info in the dataset json file

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
