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

import json

from qgis.utils import iface
mb = iface.messageBar()

from PyQt4 import QtGui

from LDMP import log
from LDMP.calculate_lc import DlgCalculateLCBase
from LDMP.gui.DlgCalculateSOC import Ui_DlgCalculateSOC
from LDMP.api import run_script


class DlgCalculateSOC(DlgCalculateLCBase, Ui_DlgCalculateSOC):
    def __init__(self, parent=None):
        super(DlgCalculateSOC, self).__init__(parent)

        self.setupUi(self)

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateSOC, self).btn_calculate()
        if not ret:
            return

        self.close()

        payload = {'year_bl_start': self.year_bl_start.date().year(),
                   'year_bl_end': self.year_bl_end.date().year(),
                   'year_target': self.year_target.date().year(),
                   'geojson': json.dumps(self.bbox),
                   'remap_matrix': self.remap_matrix,
                   'task_name': self.task_name.text(),
                   'task_notes': self.task_notes.toPlainText()}

        gee_script = self.scripts['soil_organic_carbon']['script id']

        resp = run_script(gee_script, payload)

        if resp:
            mb.pushMessage(QtGui.QApplication.translate("LDMP", "Submitted"),
                           QtGui.QApplication.translate("LDMP", "Soil organic carbon submitted to Google Earth Engine."),
                           level=0, duration=5)
        else:
            mb.pushMessage(QtGui.QApplication.translate("LDMP", "Error"),
                           QtGui.QApplication.translate("LDMP", "Unable to submit soil organic carbon task to Google Earth Engine."),
                           level=0, duration=5)
