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

from qgis.utils import iface
mb = iface.messageBar()

from PyQt4 import QtGui, QtCore
from PyQt4.QtCore import QSettings, QAbstractTableModel, Qt

from LDMP import log

from LDMP.calculate import DlgCalculateBase, get_script_slug
from LDMP.gui.DlgDownload import Ui_DlgDownload
from LDMP.api import run_script


class DataTableModel(QAbstractTableModel):
    def __init__(self, datain, parent=None, *args):
        QAbstractTableModel.__init__(self, parent, *args)
        self.datasets = datain

        # Column names as tuples with json name in [0], pretty name in [1]
        # Note that the columns with json names set to to INVALID aren't loaded
        # into the shell, but shown from a widget.
        colname_tuples = [('category', QtGui.QApplication.translate('LDMPPlugin', 'Category')),
                          ('title', QtGui.QApplication.translate('LDMPPlugin', 'Title')),
                          ('Units/Description', QtGui.QApplication.translate('LDMPPlugin', 'Units')),
                          ('Spatial Resolution', QtGui.QApplication.translate('LDMPPlugin', 'Resolution')),
                          ('Start year', QtGui.QApplication.translate('LDMPPlugin', 'Start year')),
                          ('End year', QtGui.QApplication.translate('LDMPPlugin', 'End year')),
                          ('Extent', QtGui.QApplication.translate('LDMPPlugin', 'Extent')),
                          ('INVALID', QtGui.QApplication.translate('LDMPPlugin', 'Details'))]
        self.colnames_pretty = [x[1] for x in colname_tuples]
        self.colnames_json = [x[0] for x in colname_tuples]

    def rowCount(self, parent):
        return len(self.datasets)

    def columnCount(self, parent):
        return len(self.colnames_json)

    def data(self, index, role):
        if not index.isValid():
            return None
        elif role != Qt.DisplayRole:
            return None
        return self.datasets[index.row()].get(self.colnames_json[index.column()], '')

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.colnames_pretty[section]
        return QAbstractTableModel.headerData(self, section, orientation, role)


class DlgDownload(DlgCalculateBase, Ui_DlgDownload):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgDownload, self).__init__(parent)

        self.settings = QSettings()

        self.setupUi(self)

        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                               'data', 'gee_datasets.json')) as f:
            data_dict = json.load(f)

        self.datasets = []
        for cat in data_dict.keys():
            for title in data_dict[cat].keys():
                item = data_dict[cat][title]
                item.update({'category': cat,
                             'title': title})
                self.datasets.append(item)

        self.update_data_table()

    def tab_changed(self):
        super(DlgDownload, self).tab_changed()
        if (self.TabBox.currentIndex() == (self.TabBox.count() - 1)) \
                and not self.data_view.selectedIndexes():
            # Only enable download if a dataset is selected
            self.button_calculate.setEnabled(False)

    def showEvent(self, event):
        super(DlgDownload, self).showEvent(event)

        # Don't local/cloud selector for this dialog
        self.options_tab.toggle_show_where_to_run(False)

    def update_data_table(self):
        table_model = DataTableModel(self.datasets, self)
        proxy_model = QtGui.QSortFilterProxyModel()
        proxy_model.setSourceModel(table_model)
        self.data_view.setModel(proxy_model)

        # Add "Notes" buttons in cell
        for row in range(0, len(self.datasets)):
            btn = QtGui.QPushButton(self.tr("Details"))
            btn.clicked.connect(self.btn_details)
            self.data_view.setIndexWidget(proxy_model.index(row, 7), btn)

        self.data_view.horizontalHeader().setResizeMode(QtGui.QHeaderView.ResizeToContents)

        self.data_view.setSelectionBehavior(QtGui.QAbstractItemView.SelectRows)

    def btn_details(self):
        button = self.sender()
        index = self.data_view.indexAt(button.pos())
        #TODO: Code the details view

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgDownload, self).btn_calculate()
        if not ret:
            return

        rows = list(set(index.row() for index in self.data_view.selectedIndexes()))

        self.close()

        for row in rows:
            payload = {'geojson': json.dumps(self.aoi.bounding_box_gee_geojson()),
                       'asset': self.datasets[row]['GEE Dataset'],
                       'name': self.datasets[row]['title'],
                       'temporal_resolution': self.datasets[row]['Temporal resolution'],
                       'task_name': self.options_tab.task_name.text(),
                       'task_notes': self.options_tab.task_notes.toPlainText()}

            resp = run_script(get_script_slug('download-data'), payload)

            if resp:
                mb.pushMessage(QtGui.QApplication.translate("LDMP", "Sucess"),
                               QtGui.QApplication.translate("LDMP", "Download request submitted to Google Earth Engine."),
                               level=0, duration=5)
            else:
                mb.pushMessage(QtGui.QApplication.translate("LDMP", "Error"),
                               QtGui.QApplication.translate("LDMP", "Unable to submit download request to Google Earth Engine."),
                               level=0, duration=5)
