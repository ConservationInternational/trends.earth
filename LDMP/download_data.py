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
import os
from pathlib import Path


import qgis.gui
from qgis.PyQt import (
    QtCore,
    QtGui,
    QtWidgets,
    uic,
)
from . import (
    calculate,
    conf,
)
from .algorithms import models
from .jobs.manager import job_manager
from .logger import log

DlgDownloadUi, _ = uic.loadUiType(str(Path(__file__).parent / "gui/DlgDownload.ui"))


class tool_tipper(QtCore.QObject):
    def __init__(self, parent=None):
        super().__init__(parent)

    def eventFilter(self, obj, event):
        if (event.type() == QtCore.QEvent.ToolTip):
            view = obj.parent()
            if not view:
                return False

            pos = event.pos()
            index = view.indexAt(pos)
            if not index.isValid():
                return False

            itemText = str(view.model().data(index))
            itemTooltip = view.model().data(index, QtCore.Qt.ToolTipRole)

            fm = QtGui.QFontMetrics(view.font())
            itemTextWidth = fm.width(itemText)
            rect = view.visualRect(index)
            rectWidth = rect.width()

            if (itemTextWidth > rectWidth) and itemTooltip:
                QtWidgets.QToolTip.showText(event.globalPos(), itemTooltip, view, rect)
            else:
                QtWidgets.QToolTip.hideText()
            return True
        return False


class DataTableModel(QtCore.QAbstractTableModel):
    def __init__(self, datain, parent=None, *args):
        QtCore.QAbstractTableModel.__init__(self, parent, *args)
        self.datasets = datain

        # Column names as tuples with json name in [0], pretty name in [1]
        # Note that the columns with json names set to to INVALID aren't loaded
        # into the shell, but shown from a widget.
        colname_tuples = [('category', self.tr('Category')),
                          ('title', self.tr('Title')),
                          ('Units', self.tr('Units')),
                          ('Spatial Resolution', self.tr('Resolution')),
                          ('Start year', self.tr('Start year')),
                          ('End year', self.tr('End year')),
                          ('extent_lat', self.tr('Extent (lat)')),
                          ('extent_lon', self.tr('Extent (lon)')),
                          ('INVALID', self.tr('Details'))]
        self.colnames_pretty = [x[1] for x in colname_tuples]
        self.colnames_json = [x[0] for x in colname_tuples]

    def rowCount(self, parent):
        return len(self.datasets)

    def columnCount(self, parent):
        return len(self.colnames_json)

    def data(self, index, role):
        if not index.isValid():
            return None
        elif role == QtCore.Qt.TextAlignmentRole and index.column() in [2, 3, 4, 5, 6, 7]:
            return QtCore.Qt.AlignCenter
        elif role != QtCore.Qt.DisplayRole:
            return None
        return self.datasets[index.row()].get(self.colnames_json[index.column()], '')

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if role == QtCore.Qt.DisplayRole and orientation == QtCore.Qt.Horizontal:
            return self.colnames_pretty[section]
        return QtCore.QAbstractTableModel.headerData(self, section, orientation, role)


class DlgDownload(calculate.DlgCalculateBase, DlgDownloadUi):

    def __init__(
            self,
            iface: qgis.gui.QgisInterface,
            script: models.ExecutionScript,
            parent: QtWidgets.QWidget = None
    ):
        super().__init__(iface, script, parent)

        # Allow the download tool to support data downloads of any size (in
        # terms of area)
        self._max_area = 1e10
        self.setupUi(self)
        self.button_calculate.clicked.connect(self.btn_calculate)
        self.datasets = []
        for cat in list(conf.REMOTE_DATASETS.keys()):
            for title in list(conf.REMOTE_DATASETS[cat].keys()):
                item = conf.REMOTE_DATASETS[cat][title].copy()
                item.update({'category': cat, 'title': title})
                min_x = item.get('Min Longitude', None)
                max_x = item.get('Max Longitude', None)
                min_y = item.get('Min Latitude', None)
                max_y = item.get('Max Latitude', None)
                if not None in (min_x, max_x, min_y, max_y):
                    extent_lat = '{} - {}'.format(min_y, max_y)
                    extent_lon = '{} - {}'.format(min_x, max_x)
                    item.update({'extent_lat': extent_lat,
                                 'extent_lon': extent_lon})
                self.datasets.append(item)

        self.update_data_table()
        self.data_view.selectionModel().selectionChanged.connect(self.selection_changed)
        self.data_view.viewport().installEventFilter(tool_tipper(self.data_view))

    def selection_changed(self):
        if self.data_view.selectedIndexes():
            # Note there can only be one row selected at a time by default
            row = list(set(index.row() for index in self.data_view.selectedIndexes()))[0]
            first_year = self.datasets[row]['Start year']
            last_year = self.datasets[row]['End year']
            if (first_year == 'NA') or (last_year == 'NA'):
                self.first_year.setEnabled(False)
                self.last_year.setEnabled(False)
            else:
                self.first_year.setEnabled(True)
                self.last_year.setEnabled(True)
                first_year = QtCore.QDate(first_year, 12, 31)
                last_year = QtCore.QDate(last_year, 12, 31)
                self.first_year.setMinimumDate(first_year)
                self.first_year.setMaximumDate(last_year)
                self.last_year.setMinimumDate(first_year)
                self.last_year.setMaximumDate(last_year)

    def tab_changed(self):
        super(DlgDownload, self).tab_changed()
        if (self.TabBox.currentIndex() == (self.TabBox.count() - 1)) \
                and not self.data_view.selectedIndexes():
            # Only enable download if a dataset is selected
            self.button_calculate.setEnabled(False)

    def firstShow(self):
        super(DlgDownload, self).firstShow()
        # Don't show the time selector for now
        self.TabBox.removeTab(1)
        self.button_prev.setHidden(True)
        self.button_next.setHidden(True)

    def showEvent(self, event):
        super(DlgDownload, self).showEvent(event)

        # Don't local/cloud selector for this dialog
        self.options_tab.toggle_show_where_to_run(False)

    def update_data_table(self):
        table_model = DataTableModel(self.datasets, self)
        self.proxy_model = QtCore.QSortFilterProxyModel()
        self.proxy_model.setSourceModel(table_model)
        self.data_view.setModel(self.proxy_model)

        # Add "Notes" buttons in cell
        for row in range(0, len(self.datasets)):
            btn = QtWidgets.QPushButton(self.tr("Details"))
            btn.clicked.connect(self.btn_details)
            self.data_view.setIndexWidget(self.proxy_model.index(row, 8), btn)

        self.data_view.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.data_view.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.data_view.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        self.data_view.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        self.data_view.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeToContents)
        self.data_view.horizontalHeader().setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeToContents)
        self.data_view.horizontalHeader().setSectionResizeMode(6, QtWidgets.QHeaderView.ResizeToContents)
        self.data_view.horizontalHeader().setSectionResizeMode(7, QtWidgets.QHeaderView.ResizeToContents)
        self.data_view.horizontalHeader().setSectionResizeMode(8, QtWidgets.QHeaderView.ResizeToContents)

        self.data_view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)

    def btn_details(self):
        button = self.sender()
        index = self.data_view.indexAt(button.pos())
        #TODO: Code the details view

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        log("btn_calculate clicked")
        ret = super(DlgDownload, self).btn_calculate()
        log(f"ret: {ret}")
        if not ret:
            return
        log(f"continuing...")

        rows = list(set(index.row() for index in self.data_view.selectedIndexes()))
        # Construct unique dataset names as the concatenation of the category
        # and the title
        selected_names = [self.proxy_model.index(row, 0).data() + self.proxy_model.index(row, 1).data()for row in rows]
        selected_datasets = [d for d in self.datasets if d['category'] + d['title'] in selected_names]

        self.close()

        crosses_180th, geojsons = self.gee_bounding_box
        log(f"selected_datasets: {selected_datasets}")
        for dataset in selected_datasets:
            payload = {
                'geojsons': json.dumps(geojsons),
                'crs': self.aoi.get_crs_dst_wkt(),
                'year_start': self.first_year.date().year(),
                'year_end': self.last_year.date().year(),
                'crosses_180th': crosses_180th,
                'asset': dataset['GEE Dataset'],
                'name': dataset['title'],
                'temporal_resolution': dataset['Temporal resolution'],
                'task_name': self.options_tab.task_name.text(),
                'task_notes': self.options_tab.task_notes.toPlainText()
            }

            resp = job_manager.submit_remote_job(payload, self.script.id)
            if resp:
                main_msg = "Success"
                description = "Download request submitted to Google Earth Engine."

            else:
                main_msg = "Error"
                description = (
                    "Unable to submit download request to Google Earth Engine.")
            self.mb.pushMessage(
                self.tr(main_msg),
                self.tr(description),
                level=0,
                duration=5
            )
