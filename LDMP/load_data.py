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

from PyQt4 import QtGui
from PyQt4.QtCore import QSettings, Qt

from qgis.utils import iface
mb = iface.messageBar()

from LDMP import log
from LDMP.jobs import add_layer
from LDMP.gui.DlgLoadData import Ui_DlgLoadData

def get_params(json_file):
    try:
        with open(json_file) as f:
            d = json.load(f)
    except (OSError, IOError, ValueError) as e:
        log('Error loading {}'.format(json_file))
        return None

    try:
        params = d.get('params', None)
        if not params:
            log('Missing key in {}'.format(json_file))
            return None
        else:
            return params
    except AttributeError:
        log('Unable to parse {}'.format(json_file))
        return None


def get_results(json_file):
    try:
        with open(json_file) as f:
            d = json.load(f)
    except (OSError, IOError, ValueError) as e:
        log('Error loading {}'.format(json_file))
        return None

    try:
        results = d.get('results', None)
        if not results \
                or not results.has_key('type') \
                or not results.has_key('datasets') \
                or not results.has_key('urls'):
            log('Missing key in {}'.format(json_file))
            return None
    except AttributeError:
        log('Unable to parse {}'.format(json_file))
        return None
    
    # Check accompanying tif file(s) are there:
    if len(results['urls']['files']) > 1:
        # If more than one file is returned by GEE, then trends.earth will 
        # write a virtual raster table listing these files
        data_file = os.path.splitext(json_file)[0] + '.vrt'
    else:
        data_file = os.path.splitext(json_file)[0] + '.tif'
    if not os.access(data_file, os.R_OK):
        log('Data file {} is missing'.format(data_file))
        return None
    else:
        return results


class DlgLoadData(QtGui.QDialog, Ui_DlgLoadData):
    def __init__(self, parent=None):
        super(DlgLoadData, self).__init__(parent)

        self.setupUi(self)

        self.file_browse_btn.clicked.connect(self.browse_file)

        self.file_lineedit.textChanged.connect(self.update_details)

        #TODO:
        # - disable ok button until a valid file and layer are chosen
        # - update the layer combo box based on the datasets in the chosen file

    def showEvent(self, e):
        super(DlgLoadData, self).showEvent(e)

        self.file_lineedit.clear()
        self.buttonBox.accepted.connect(self.ok_clicked)
        self.buttonBox.rejected.connect(self.cancel_clicked)

    def browse_file(self):
        f = QtGui.QFileDialog.getOpenFileName(self,
                                              self.tr('Select a trends.earth output file'),
                                              QSettings().value("LDMP/output_dir", None),
                                              self.tr('trends.earth metadata file (*.json)'))
        if f:
            if os.access(f, os.R_OK):
                QSettings().setValue("LDMP/output_dir", os.path.dirname(f))
            else:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Cannot read {}. Choose a different file.".format(f)))

            res = get_results(f)
            if not res:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("{} does not appear to be a trends.earth output file".format(f)))
                self.file_lineedit.clear()
                return None
            else:
                self.file_lineedit.setText(f)

    def cancel_clicked(self):
        self.close()

    def ok_clicked(self):
        layer = self.layer_comboBox.currentText()
        if layer:
            log('Adding "{}" layer from {}'.format(layer, self.file_lineedit.text()))
            self.close()
        else:
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Select a layer to load."))
        results = get_results(self.file_lineedit.text())

        band_info = results['datasets']
        add_layer(self.file_lineedit.text(), layer)
            

    def update_details(self):
        if self.file_lineedit.text():
            results = get_results(self.file_lineedit.text())
            if results:
                self.layers_model = QtGui.QStringListModel()
                self.layers_model.setStringList([d['dataset'] for d in results['datasets']])
                self.layers_view.setModel(self.layers_model)
                self.layers_view.selectAll()
            else:
                self.layers_model.setStringList([])

            params = get_params(self.file_lineedit.text())
            if params:
                self.task_name.setText(params.get('task_name', ''))
                self.input.setText(json.dumps(params, indent=4, sort_keys=True))
                self.output.setText(json.dumps(results, indent=4, sort_keys=True))
                self.comments.setText(params.get('task_notes', ''))
            else:
                self.task_name.clear()
                self.input.clear()
                self.output.clear()
                self.comments.clear()
        else:
            self.layers_model.setStringList([])
            self.task_name.clear()
            self.input.clear()
            self.output.clear()
            self.comments.clear()
            return None
