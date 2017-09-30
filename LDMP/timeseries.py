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

import pyqtgraph as pg

from PyQt4 import QtGui, uic

from PyQt4.QtCore import QDate, QTextCodec

from LDMP import log
from LDMP.calculate import DlgCalculateBase
from LDMP.gui.DlgTimeseries import Ui_DlgTimeseries
from LDMP.api import run_script

from qgis.core import QgsGeometry, QgsPoint, QgsJSONUtils, QgsVectorLayer
from qgis.gui import QgsMapToolEmitPoint, QgsMapToolPan
from qgis.utils import iface

mb = iface.messageBar()

class DlgTimeseries(DlgCalculateBase, Ui_DlgTimeseries):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgTimeseries, self).__init__(parent)

        self.setupUi(self)

        self.traj_indic.addItems(self.scripts['productivity_trajectory'].keys())
        self.traj_indic.currentIndexChanged.connect(self.traj_indic_changed)

        self.dataset_climate_update()
        self.dataset_ndvi.addItems(self.datasets['NDVI'].keys())

        self.start_year_climate = 0
        self.end_year_climate = 9999
        self.start_year_ndvi = 0
        self.end_year_ndvi = 9999

        self.dataset_ndvi_changed()
        self.traj_climate_changed()

        self.dataset_ndvi.currentIndexChanged.connect(self.dataset_ndvi_changed)
        self.traj_climate.currentIndexChanged.connect(self.traj_climate_changed)

        # Setup point chooser
        icon = QtGui.QIcon(QtGui.QPixmap(':/plugins/LDMP/icons/icon-map-marker.png'))
        self.choose_point.setIcon(icon)
        self.choose_point.clicked.connect(self.point_chooser)
        self.canvas = iface.mapCanvas()
        self.choose_point_tool = QgsMapToolEmitPoint(self.canvas)
        self.choose_point_tool.canvasClicked.connect(self.set_point_coords)
        #TODO: Set range to only accept valid coordinates for current map coordinate system
        self.point_x.setValidator(QtGui.QDoubleValidator())
        #TODO: Set range to only accept valid coordinates for current map coordinate system
        self.point_y.setValidator(QtGui.QDoubleValidator())

        self.area_frompoint.toggled.connect(self.area_frompoint_toggle)
        self.area_frompoint_toggle()

        self.setup_dialog()

    def point_chooser(self):
        log("Choosing point from canvas...")
        self.hide()
        self.canvas.setMapTool(self.choose_point_tool)
        QtGui.QMessageBox.critical(None, self.tr("Point chooser"), self.tr("Click the map to choose a point."))

    def set_point_coords(self, point, button):
        log("Set point coords")
        #TODO: Show a messagebar while tool is active, and then remove the bar when a point is chosen.
        self.point = point
        # Disable the choose point tool
        self.canvas.setMapTool(QgsMapToolPan(self.canvas))
        self.show()
        self.point = self.canvas.getCoordinateTransform().toMapCoordinates(self.point.x(), self.point.y())
        log("Chose point: {}, {}.".format(self.point.x(), self.point.y()))
        self.point_x.setText("{:.8f}".format(self.point.x()))
        self.point_y.setText("{:.8f}".format(self.point.y()))

    def area_frompoint_toggle(self):
        if self.area_frompoint.isChecked():
            self.point_x.setEnabled(True)
            self.point_y.setEnabled(True)
            self.choose_point.setEnabled(True)
        else:
            self.point_x.setEnabled(False)
            self.point_y.setEnabled(False)
            self.choose_point.setEnabled(False)

    def open_shp_browse(self):
        shpfile = QtGui.QFileDialog.getOpenFileName()

    def traj_indic_changed(self):
        self.dataset_climate_update()

    def dataset_climate_update(self):
        self.traj_climate.clear()
        self.climate_datasets = {}
        climate_types = self.scripts['productivity_trajectory'][self.traj_indic.currentText()]['climate types']
        for climate_type in climate_types:
            self.climate_datasets.update(self.datasets[climate_type])
            self.traj_climate.addItems(self.datasets[climate_type].keys())

    def traj_climate_changed(self):
        if self.traj_climate.currentText() == "":
            self.start_year_climate = 0
            self.end_year_climate = 9999
        else:
            self.start_year_climate = self.climate_datasets[self.traj_climate.currentText()]['Start year']
            self.end_year_climate = self.climate_datasets[self.traj_climate.currentText()]['End year']
        self.update_time_bounds()

    def dataset_ndvi_changed(self):
        this_ndvi_dataset = self.datasets['NDVI'][self.dataset_ndvi.currentText()]
        self.start_year_ndvi = this_ndvi_dataset['Start year']
        self.end_year_ndvi = this_ndvi_dataset['End year']

        self.update_time_bounds()

    def update_time_bounds(self):
        # TODO: need to also account for GAEZ and/or CCI data dates for 
        # stratification
        start_year = QDate(self.start_year_ndvi, 1, 1)
        end_year = QDate(self.end_year_ndvi, 12, 31)

        # Trajectory - needs to also account for climate data
        start_year_traj = QDate(max(self.start_year_ndvi, self.start_year_climate), 1, 1)
        end_year_traj = QDate(min(self.end_year_ndvi, self.end_year_climate), 12, 31)

        self.traj_year_start.setMinimumDate(start_year_traj)
        self.traj_year_start.setMaximumDate(end_year_traj)
        self.traj_year_end.setMinimumDate(start_year_traj)
        self.traj_year_end.setMaximumDate(end_year_traj)
            
    def btn_cancel(self):
        self.close()

    def btn_calculate(self):
        if self.area_admin.isChecked():
            if not self.area_admin_0.currentText():
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                        self.tr("Choose a first level administrative boundary."), None)
                return False
            self.button_calculate.setEnabled(False)
            geojson = self.load_admin_polys()
            self.button_calculate.setEnabled(True)
            if not geojson:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                        self.tr("Unable to load administrative boundaries."), None)
                return False
        elif self.area_fromfile.isChecked():
            if not self.area_fromfile_file.text():
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                        self.tr("Choose a file to define the area of interest."), None)
                return False
            layer = QgsVectorLayer(self.area_fromfile_file.text(), 'calculation boundary', 'ogr')
            geojson = json.loads(QgsGeometry.fromRect(layer.extent()).exportToGeoJSON())
        else:
            # Area from point
            if not self.point_x.text() and not self.point_y.text():
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                        self.tr("Choose a point to define the area of interest."), None)
                return False
            point = QgsPoint(float(self.point_x.text()), float(self.point_y.text()))
            geojson = json.loads(QgsGeometry.fromPoint(point).exportToGeoJSON())

        # Calculate bounding box of input polygon and then convert back to 
        # geojson
        fields = QgsJSONUtils.stringToFields(json.dumps(geojson), QTextCodec.codecForName('UTF8'))
        features = QgsJSONUtils.stringToFeatureList(json.dumps(geojson), fields, QTextCodec.codecForName('UTF8'))
        if len(features) > 1:
            log("Found {} features in geojson - using first feature only.".format(len(features)))
        #self.bbox = json.loads(features[0].geometry().convexHull().exportToGeoJSON())
        self.bbox = json.loads(QgsGeometry.fromRect(features[0].geometry().boundingBox()).exportToGeoJSON())
        log("Calculating timeseries for: {}.".format(self.bbox))

        ndvi_dataset = self.datasets['NDVI'][self.dataset_ndvi.currentText()]['GEE Dataset']

        self.calculate_timeseries(self.bbox, ndvi_dataset)

    def calculate_timeseries(self, geojson, ndvi_dataset):
        if self.traj_climate.currentText() != "":
            climate_gee_dataset = self.climate_datasets[self.traj_climate.currentText()]['GEE Dataset']
            log('climate_gee_dataset {}'.format(climate_gee_dataset))
        else:
            climate_gee_dataset = None

        payload = {'year_start': self.traj_year_start.date().year(),
                   'year_end': self.traj_year_end.date().year(),
                   'geojson': json.dumps(self.bbox),
                   'ndvi_gee_dataset': ndvi_dataset,
                   'climate_gee_dataset': climate_gee_dataset}
        # This will add in the method parameter
        payload.update(self.scripts['productivity_trajectory'][self.traj_indic.currentText()]['params'])

        gee_script = self.scripts['timeseries']['script id']

        resp = run_script(gee_script, payload)

        if resp:
            mb.pushMessage(self.tr("Submitted"),
                    self.tr("Time series calculation task submitted to Google Earth Engine."),
                    level=0, duration=5)
        else:
            mb.pushMessage(self.tr("Error"),
                    self.tr("Unable to submit time series calculation task to Google Earth Engine."),
                    level=1, duration=5)
