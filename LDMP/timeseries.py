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

from qgis.PyQt import QtWidgets, uic

from qgis.PyQt.QtCore import QDate, QTextCodec

from LDMP import log
from LDMP.calculate import DlgCalculateBase, get_script_slug
from LDMP.gui.DlgTimeseries import Ui_DlgTimeseries
from LDMP.api import run_script

from qgis.gui import QgsMapToolEmitPoint, QgsMapToolPan
from qgis.utils import iface

mb = iface.messageBar()


class DlgTimeseries(DlgCalculateBase, Ui_DlgTimeseries):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgTimeseries, self).__init__(parent)

        self.setupUi(self)

        ndvi_datasets = [x for x in list(self.datasets['NDVI'].keys()) if self.datasets['NDVI'][x]['Temporal resolution'] == 'annual']
        self.dataset_ndvi.addItems(ndvi_datasets)

        self.start_year_climate = 0
        self.end_year_climate = 9999
        self.start_year_ndvi = 0
        self.end_year_ndvi = 9999

        self.dataset_ndvi_changed()
        self.traj_climate_changed()
        self.traj_indic.currentIndexChanged.connect(self.traj_indic_changed)

        self.dataset_climate_update()

        self.dataset_ndvi.currentIndexChanged.connect(self.dataset_ndvi_changed)
        self.traj_climate.currentIndexChanged.connect(self.traj_climate_changed)

        # TODO:Temporary until fixed:
        self.TabBox.removeTab(1)

    def traj_indic_changed(self):
        self.dataset_climate_update()

    def dataset_climate_update(self):
        self.traj_climate.clear()
        self.climate_datasets = {}
        # Can't use any of the methods but NDVI Trends on the 16 day data, so
        # don't need climate datasets
        if self.datasets['NDVI'][self.dataset_ndvi.currentText()]['Temporal resolution'] == 'annual':
            climate_types = self.scripts['productivity']['trajectory functions'][self.traj_indic.currentText()]['climate types']
            for climate_type in climate_types:
                self.climate_datasets.update(self.datasets[climate_type])
                self.traj_climate.addItems(list(self.datasets[climate_type].keys()))

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

        # Don't try to update the climate datasets while traj_indic is empty,
        # so block signals while clearing it.
        self.traj_indic.blockSignals(True)
        self.traj_indic.clear()
        self.traj_indic.blockSignals(False)
        # Can't use any of the methods but NDVI Trends on the 16 day data
        if this_ndvi_dataset['Temporal resolution'] == '16 day':
            self.traj_indic.addItems(['NDVI trends'])
        else:
            self.traj_indic.addItems(list(self.scripts['productivity']['trajectory functions'].keys()))

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
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgTimeseries, self).btn_calculate()
        if not ret:
            return

        self.close()

        # Limit area that can be processed
        aoi_area = self.aoi.get_area() / (1000 * 1000)
        log(u'AOI area is: {:n}'.format(aoi_area))
        if aoi_area > 1e7:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("The bounding box of the requested area (approximately {:.6n} sq km) is too large. The timeseries tool can process a maximum area of 10 million sq km at a time. Choose a smaller area to process.".format(aoi_area)))
            return False

        if self.traj_climate.currentText() != "":
            climate_gee_dataset = self.climate_datasets[self.traj_climate.currentText()]['GEE Dataset']
            log('climate_gee_dataset {}'.format(climate_gee_dataset))
        else:
            climate_gee_dataset = None
        ndvi_dataset = self.datasets['NDVI'][self.dataset_ndvi.currentText()]['GEE Dataset']

        crosses_180th, geojsons = self.gee_bounding_box
        payload = {'year_start': self.traj_year_start.date().year(),
                   'year_end': self.traj_year_end.date().year(),
                   'crosses_180th': crosses_180th,
                   'geojsons': json.dumps(geojsons),
                   'crs': self.aoi.get_crs_dst_wkt(),
                   'ndvi_gee_dataset': ndvi_dataset,
                   'task_name': self.options_tab.task_name.text(),
                   'task_notes': self.options_tab.task_notes.toPlainText(),
                   'climate_gee_dataset': climate_gee_dataset}
        # This will add in the method parameter
        payload.update(self.scripts['productivity']['trajectory functions'][self.traj_indic.currentText()]['params'])

        resp = run_script(get_script_slug('time-series'), payload)

        if resp:
            mb.pushMessage(self.tr("Submitted"),
                           self.tr("Time series calculation task submitted to Google Earth Engine."),
                           level=0, duration=5)
        else:
            mb.pushMessage(self.tr("Error"),
                           self.tr("Unable to submit time series calculation task to Google Earth Engine."),
                           level=1, duration=5)
