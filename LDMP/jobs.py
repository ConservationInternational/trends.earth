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
from urllib import quote_plus

from PyQt4 import QtGui, uic
from PyQt4.QtCore import QSettings, QDate

from DlgJobs import Ui_DlgJobs as UiDialog

from api import API

class DlgJobs(QtGui.QDialog, UiDialog):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgJobs, self).__init__(parent)

        self.settings = QSettings()

        self.setupUi(self)

        self.api = API()
        self.api.login()
        self.executions = self.api.get_execution(user=self.settings.value("LDMP/user_id", None))

    def btn_cancel(self):
        self.close()

    def btn_ok(self):
        self.close()
