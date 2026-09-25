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
from functools import partial
from pathlib import Path

import qgis.gui
from qgis.PyQt import QtCore, QtGui, QtWidgets, uic
from te_schemas.algorithms import ExecutionScript

from . import calculate, conf
from .conf import Setting, settings_manager
from .dataset_additional_metadata import DataSetAdditionalMetadataDialog
from .download_data_stac import _stac_dataset_item
from .jobs.manager import job_manager
from .logger import log
from .utils import push_message

DlgDownloadUi, _ = uic.loadUiType(str(Path(__file__).parent / "gui/DlgDownload.ui"))

ICON_PATH = os.path.join(os.path.dirname(__file__), "icons")


class tool_tipper(QtCore.QObject):
    def __init__(self, parent=None):
        super().__init__(parent)

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.ToolTip:
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
            itemTextWidth = fm.horizontalAdvance(itemText)
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
        colname_tuples = [
            ("category", self.tr("Category")),
            ("title", self.tr("Title")),
            ("Units", self.tr("Units")),
            ("Spatial Resolution", self.tr("Resolution")),
            ("Start year", self.tr("Start year")),
            ("End year", self.tr("End year")),
            ("extent_lat", self.tr("Extent (lat)")),
            ("extent_lon", self.tr("Extent (lon)")),
            ("INVALID", self.tr("Details")),
        ]
        self.colnames_pretty = [x[1] for x in colname_tuples]
        self.colnames_json = [x[0] for x in colname_tuples]

    def rowCount(self, parent=None):
        return len(self.datasets)

    def columnCount(self, parent=None):
        return len(self.colnames_json)

    def data(self, index, role):
        if not index.isValid():
            return None
        elif role == QtCore.Qt.TextAlignmentRole and index.column() in [
            2,
            3,
            4,
            5,
            6,
            7,
        ]:
            return QtCore.Qt.AlignCenter
        elif role in [QtCore.Qt.DisplayRole, QtCore.Qt.ToolTipRole]:
            return self.datasets[index.row()].get(
                self.colnames_json[index.column()], ""
            )
        else:
            return None

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if role == QtCore.Qt.DisplayRole and orientation == QtCore.Qt.Horizontal:
            return self.colnames_pretty[section]
        return QtCore.QAbstractTableModel.headerData(self, section, orientation, role)


class DlgDownload(calculate.DlgCalculateBase, DlgDownloadUi):
    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        script: ExecutionScript,
        parent: QtWidgets.QWidget = None,
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
                item.update({"category": cat, "title": title})
                min_x = item.get("Min Longitude", None)
                max_x = item.get("Max Longitude", None)
                min_y = item.get("Min Latitude", None)
                max_y = item.get("Max Latitude", None)
                if None not in (min_x, max_x, min_y, max_y):
                    extent_lat = f"{min_y} - {max_y}"
                    extent_lon = f"{min_x} - {max_x}"
                    item.update({"extent_lat": extent_lat, "extent_lon": extent_lon})
                self.datasets.append(item)

        # STAC Datasets for STAC download
        for cat, collections in conf.STAC_DATASETS.items():
            for collection_id, stac in collections.items():
                self.datasets.append(_stac_dataset_item(cat, collection_id, stac))

        self.update_data_table()
        self.data_view.selectionModel().selectionChanged.connect(self.selection_changed)
        self.data_view.viewport().installEventFilter(tool_tipper(self.data_view))

        self.update_current_region()
        self.region_button.setIcon(QtGui.QIcon(os.path.join(ICON_PATH, "wrench.svg")))
        self.region_button.clicked.connect(self.run_settings)

    def update_current_region(self):
        region = settings_manager.get_value(Setting.AREA_NAME)
        self.region_la.setText(self.tr(f"Current region: {region}"))
        self.changed_region.emit()

    def update_layers_tree(self, dataset):
        self.layers_selector.clear()
        self.layers_selector_group.setVisible("layers" in dataset)
        for layer, assets in dataset.get("layers", {}).items():
            layer_item = QtWidgets.QTreeWidgetItem(self.layers_selector, [layer])
            layer_item.setFlags(
                layer_item.flags()
                | QtCore.Qt.ItemIsUserCheckable
                | QtCore.Qt.ItemIsAutoTristate
            )
            layer_item.setCheckState(0, QtCore.Qt.Unchecked)
            for key, title in assets.items():
                asset_item = QtWidgets.QTreeWidgetItem(layer_item, [title])
                asset_item.setData(0, QtCore.Qt.UserRole, key)
                asset_item.setFlags(
                    asset_item.flags() | QtCore.Qt.ItemIsUserCheckable
                )
                asset_item.setCheckState(0, QtCore.Qt.Unchecked)

    def checked_layers(self):
        keys = []
        for i in range(self.layers_selector.topLevelItemCount()):
            layer_item = self.layers_selector.topLevelItem(i)
            for j in range(layer_item.childCount()):
                asset_item = layer_item.child(j)
                if asset_item.checkState(0) == QtCore.Qt.Checked:
                    keys.append(asset_item.data(0, QtCore.Qt.UserRole))
        return keys

    def selection_changed(self):
        if self.data_view.selectedIndexes():
            # Note there can only be one row selected at a time by default
            row = list({index.row() for index in self.data_view.selectedIndexes()})[0]
            year_initial = self.datasets[row]["Start year"]
            year_final = self.datasets[row]["End year"]
            if (year_initial == "NA") or (year_final == "NA"):
                self.year_initial.setEnabled(False)
                self.year_final.setEnabled(False)
            else:
                self.year_initial.setEnabled(True)
                self.year_final.setEnabled(True)
                year_initial = QtCore.QDate(year_initial, 12, 31)
                year_final = QtCore.QDate(year_final, 12, 31)
                self.year_initial.setMinimumDate(year_initial)
                self.year_initial.setMaximumDate(year_final)
                self.year_initial.setDate(year_initial)
                self.year_final.setMinimumDate(year_initial)
                self.year_final.setMaximumDate(year_final)
                self.year_final.setDate(year_final)

            # for update_layers_tree for stack dataset
            index = self.data_view.selectedIndexes()[0]
            self.update_layers_tree(
                self.datasets[self.proxy_model.mapToSource(index).row()]
            )

    def update_data_table(self):
        table_model = DataTableModel(self.datasets, self)
        self.proxy_model = QtCore.QSortFilterProxyModel()
        self.proxy_model.setSourceModel(table_model)
        self.data_view.setModel(self.proxy_model)

        # Add "Notes" buttons in cell
        for row in range(len(self.datasets)):
            btn = QtWidgets.QPushButton(self.tr("Details"))
            btn_details = partial(self.btn_details, self.datasets[row])
            btn.clicked.connect(btn_details)
            self.data_view.setIndexWidget(self.proxy_model.index(row, 8), btn)

        # Category
        self.data_view.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.Interactive
        )
        # Title
        self.data_view.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.Stretch
        )
        # Units
        self.data_view.horizontalHeader().setSectionResizeMode(
            2, QtWidgets.QHeaderView.Interactive
        )
        # Resolution
        self.data_view.horizontalHeader().setSectionResizeMode(
            3, QtWidgets.QHeaderView.ResizeToContents
        )
        # Start year
        self.data_view.horizontalHeader().setSectionResizeMode(
            4, QtWidgets.QHeaderView.ResizeToContents
        )
        # End year
        self.data_view.horizontalHeader().setSectionResizeMode(
            5, QtWidgets.QHeaderView.ResizeToContents
        )
        # Extent (lat)
        self.data_view.horizontalHeader().setSectionResizeMode(
            6, QtWidgets.QHeaderView.ResizeToContents
        )
        # Extent (long)
        self.data_view.horizontalHeader().setSectionResizeMode(
            7, QtWidgets.QHeaderView.ResizeToContents
        )
        # Details button
        self.data_view.horizontalHeader().setSectionResizeMode(
            8, QtWidgets.QHeaderView.ResizeToContents
        )

        self.data_view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)

    def btn_details(self, dataset):
        # button = self.sender()
        # index = self.data_view.indexAt(button.pos())
        # TODO: Code the details view
        dlg = DataSetAdditionalMetadataDialog(dataset)
        dlg.exec()

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super().btn_calculate()
        if not ret:
            return

        rows = list({index.row() for index in self.data_view.selectedIndexes()})
        # Construct unique dataset names as the concatenation of the category
        # and the title
        selected_names = [
            self.proxy_model.index(row, 0).data()
            + self.proxy_model.index(row, 1).data()
            for row in rows
        ]
        selected_datasets = [
            d for d in self.datasets if d["category"] + d["title"] in selected_names
        ]

        # Check if it is stac, check layer selected
        selected_layer = self.checked_layers()
        if any("stac_collection" in d for d in selected_datasets) and not selected_layer:
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"), self.tr("Choose at least one layer.")
            )
            return

        self.close()

        crosses_180th, geojsons = self.gee_bounding_box
        log(f"selected_datasets: {selected_datasets}")
        for dataset in selected_datasets:
            if "stac_collection" in dataset:
                titles = {
                    key: title
                    for assets in dataset["layers"].values()
                    for key, title in assets.items()
                }
                params = {
                    "task_name": self.execution_name_le.text(),
                    "task_notes": "",
                    "stac_collection": dataset["stac_collection"],
                    "assets": [
                        {
                            "key": key,
                            "title": titles[key],
                            "href": dataset["assets"][key],
                        }
                        for key in selected_layer
                    ],
                }
                job_manager.submit_local_job_as_qgstask(
                    params, "download-stac", self.aoi
                )
                continue

            payload = {
                "geojsons": json.dumps(geojsons),
                "crs": self.aoi.get_crs_dst_wkt(),
                "year_initial": self.year_initial.date().year(),
                "year_final": self.year_final.date().year(),
                "crosses_180th": crosses_180th,
                "asset": dataset["GEE Dataset"],
                "name": dataset["title"],
                "temporal_resolution": dataset["Temporal resolution"],
                "task_name": self.execution_name_le.text(),
                "task_notes": "",
            }

            band_number = dataset.get("Band number")
            if band_number not in (None, ""):
                payload["band_number"] = int(band_number)

            band_name = dataset.get("Band name")
            if band_name:
                payload["band_name"] = band_name

            band_metadata = dataset.get("Band metadata")
            if isinstance(band_metadata, dict):
                payload["band_metadata"] = band_metadata

            band_add_to_map = dataset.get("Band add_to_map")
            if isinstance(band_add_to_map, bool):
                payload["band_add_to_map"] = band_add_to_map

            resp = job_manager.submit_remote_job(payload, self.script.id)
            if resp:
                main_msg = "Success"
                description = "Download request submitted to Trends.Earth server."

            else:
                main_msg = "Error"
                description = (
                    "Unable to submit download request to Trends.Earth server."
                )
            push_message(
                self.mb, self.tr(main_msg), self.tr(description), level=0, duration=5
            )
