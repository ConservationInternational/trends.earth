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

from PyQt4 import QtGui, uic

from PyQt4.QtCore import QDate

from LDMP.calculate import DlgCalculateBase
from LDMP.gui.DlgTimeseries import Ui_DlgTimeseries

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

        self.setup_dialog()

        icon = QtGui.QIcon(QtGui.QPixmap(':/plugins/LDMP/icons/icon-map-marker.png'))
        self.choose_point.setIcon(icon)
        self.choose_point.show()

        self.area_from_point.toggled.connect(self.area_from_point_toggle)
        self.area_from_point_toggle()

    def area_from_point_toggle(self):
        if self.area_from_point.isChecked():
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
        # Note that the super class has several tests in it - if they fail it 
        # returns False, which would mean this function should stop execution 
        # as well.
        ret = super(DlgTimeseries, self).btn_calculate()
        if not ret:
            return

        ndvi_dataset = self.datasets['NDVI'][self.dataset_ndvi.currentText()]['GEE Dataset']

        self.calculate_timeseries(self.bbox, ndvi_dataset)
