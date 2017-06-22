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

from DlgJobs import Ui_DlgJobs as UiDialog

from api import API
from download import download_data

class DlgJobs(QtGui.QDialog, UiDialog):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgJobs, self).__init__(parent)

        self.settings = QSettings()

        self.setupUi(self)

        self.api = API()
        self.api.login()
        self.btn_refresh()

        self.refresh.clicked.connect(self.btn_refresh)
        self.download.clicked.connect(self.btn_download)

    def btn_refresh(self):
        jobs = self.api.get_execution(user=self.settings.value("LDMP/user_id", None))
        tablemodel = JobsTableModel(jobs, self)
        self.jobs_view.setModel(tablemodel)

    def btn_download(self):
        QtGui.QMessageBox.critical(None, self.tr("Error"),
                self.tr("Download function coming soon!"), None)

class JobsTableModel(QAbstractTableModel):
    def __init__(self, datain, parent=None, *args):
        QAbstractTableModel.__init__(self, parent, *args)
        self.jobs = datain

        # Column names as tuples with json name in [0], pretty name in [1]
        colname_tuples = [('start_date', 'Start time'),
                          ('script_id', 'Job'),
                          ('status', 'Status'),
                          ('progress', 'Progress')]
        self.colnames_pretty = [x[1] for x in colname_tuples]
        self.colnames_json = [x[0] for x in colname_tuples]

        # Replace script IDs with script names
        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'data', 'scripts.json')) as script_file:
            scripts = json.load(script_file)
        # The scripts file lists scripts by tool, so need to loop over the 
        # tools to get all the scripts.
        scripts_id_dict = {}
        for tool in scripts.keys():
            these_scripts = scripts[tool]
            for script_name in these_scripts.keys():
                scripts_id_dict[these_scripts[script_name]['id']] = script_name

        # Replace script IDs with script names
        for job in self.jobs:
            job['script_id'] = scripts_id_dict[job['script_id']]

        # Pretty print dates
        for job in self.jobs:
            job['start_date'] = datetime.datetime.strftime(job['start_date'], '%a %b %d (%H:%M)')

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
