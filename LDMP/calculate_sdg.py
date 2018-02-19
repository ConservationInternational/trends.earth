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
from urllib import quote_plus

from PyQt4 import QtGui
from PyQt4.QtCore import QSettings, QDate, Qt, QSize, QRect,  \
    QPoint, QAbstractTableModel, pyqtSignal, QRegExp

from qgis.utils import iface
mb = iface.messageBar()

from LDMP import log
from LDMP.calculate import DlgCalculateBase
from LDMP.calculate_lc import DlgCalculateLCBase
from LDMP.gui.DlgCalculateSDG import Ui_DlgCalculateSDG
from LDMP.gui.DlgCalculateLCSetAggregation import Ui_DlgCalculateLCSetAggregation
from LDMP.api import run_script

# Number of classes in land cover dataset
NUM_CLASSES = 7


class DlgCalculateSDG(DlgCalculateLCBase, Ui_DlgCalculateSDG):
    def __init__(self, parent=None):
        super(DlgCalculateSDG, self).__init__(parent)

        self.setupUi(self)

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateSDG, self).btn_calculate()
        if not ret:
            return

        self.close()

        #######################################################################
        # Online

        payload = {'year_baseline': self.year_baseline.date().year(),
                   'year_target': self.year_target.date().year(),
                   'geojson': json.dumps(self.aoi.bounding_box_geojson),
                   'trans_matrix': self.trans_matrix_get(),
                   'remap_matrix': self.remap_matrix,
                   'task_name': self.task_name.text(),
                   'task_notes': self.task_notes.toPlainText()}

        gee_script = 'land-cover' + '-' + self.scripts['land-cover']['script version']

        resp = run_script(gee_script, payload)

        if resp:
            mb.pushMessage(QtGui.QApplication.translate("LDMP", "Submitted"),
                           QtGui.QApplication.translate("LDMP", "Land cover task submitted to Google Earth Engine."),
                           level=0, duration=5)
        else:
            mb.pushMessage(QtGui.QApplication.translate("LDMP", "Error"),
                           QtGui.QApplication.translate("LDMP", "Unable to submit land cover task to Google Earth Engine."),
                           level=0, duration=5)

        #######################################################################
        # TODO: Add offline calculation
