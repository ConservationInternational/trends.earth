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

from qgis.core import QgsNetworkAccessManager
from qgis.PyQt import QtCore, QtNetwork, QtWidgets

from . import stac_conf
from .jobs.manager import job_manager
from .logger import log

GEOTIFF_TYPE = "image/tiff; application=geotiff"
VSIAZ_PREFIX = "/vsiaz/"

try:
    _NO_ERROR = QtNetwork.QNetworkReply.NetworkError.NoError  # PyQt6
except AttributeError:
    _NO_ERROR = QtNetwork.QNetworkReply.NoError  # PyQt5 fallback


def _stac_dataset_item(category, collection_id, stac):
    return {
        "category": category,
        "title": stac.get("title", collection_id),
        "Units": "",
        "Spatial Resolution": stac["Spatial Resolution"],
        "Start year": stac["Start year"],
        "End year": stac["End year"],
        "extent_lat": f"{stac['Min Latitude']} - {stac['Max Latitude']}",
        "extent_lon": f"{stac['Min Longitude']} - {stac['Max Longitude']}",
        "Data source": stac.get("Data source", ""),
        "Source": collection_id,
        "Citation": stac.get("Citation", ""),
        "stac_collection": collection_id,
        "stac_items_url": f"{stac['collection_url'].rstrip('/')}/items",
        "stac_style": stac["style"],
        "stac_asset_styles": stac.get("asset_styles", {}),
        "stac_storage_domain": stac.get("storage_domain"),
    }


def _public_href(href, storage_domain):
    if storage_domain and href.startswith(VSIAZ_PREFIX):
        return f"{storage_domain.rstrip('/')}/{href[len(VSIAZ_PREFIX) :]}"
    return href


def _set_stac_assets(dataset, items):
    assets = {
        key: asset
        for feature in items["features"]
        for key, asset in feature["assets"].items()
        if asset.get("type") == GEOTIFF_TYPE
    }
    dataset["assets"] = {
        key: _public_href(asset["href"], dataset["stac_storage_domain"])
        for key, asset in assets.items()
    }
    dataset["asset_titles"] = {
        key: asset.get("title", key) for key, asset in assets.items()
    }
    dataset["styles"] = {
        key: dataset["stac_asset_styles"].get(key, dataset["stac_style"])
        for key in assets
    }


def _stac_params(dataset, keys, task_name):
    titles = dataset["asset_titles"]
    return {
        "task_name": task_name,
        "task_notes": "",
        "stac_collection": dataset["stac_collection"],
        "assets": [
            {
                "key": key,
                "title": titles[key],
                "href": dataset["assets"][key],
                "style": dataset["styles"][key],
            }
            for key in keys
        ],
    }


def show_on_map_on_finish(job):
    def _processed(done_job):
        if done_job.id != job.id:
            return
        _disconnect()
        job_manager.display_default_job_results(done_job)

    def _failed(failed_job):
        if failed_job.id == job.id:
            _disconnect()

    def _disconnect():
        job_manager.processed_local_job.disconnect(_processed)
        job_manager.failed_local_job.disconnect(_failed)

    job_manager.processed_local_job.connect(_processed)
    job_manager.failed_local_job.connect(_failed)


class DlgDownloadStacMixin:
    """STAC support for DlgDownload."""

    def setup_stac(self):
        self.button_show_online.clicked.connect(self.btn_show_online)
        self.layers_selector.itemChanged.connect(self.update_show_online_button)
        self._stac_reply = None
        for cat, collections in stac_conf.STAC_DATASETS.items():
            for collection_id, stac in collections.items():
                self.datasets.append(_stac_dataset_item(cat, collection_id, stac))

    def _show_layers_loading(self, text):
        self.layers_loading.setText(text)
        self.layers_loading.setVisible(True)

    def _hide_layers_loading(self):
        self.layers_loading.setVisible(False)

    def stac_selection_changed(self):
        index = self.data_view.selectedIndexes()[0]
        dataset = self.datasets[self.proxy_model.mapToSource(index).row()]
        self._abort_stac_request()
        if "stac_collection" in dataset and "assets" not in dataset:
            self._load_stac_items(dataset)
        else:
            self._hide_layers_loading()
            self.update_layers_tree(dataset)

    def _abort_stac_request(self):
        reply = self._stac_reply
        self._stac_reply = None
        if reply is not None:
            reply.abort()

    def _load_stac_items(self, dataset):
        self.layers_selector.clear()
        self.layers_selector_group.setVisible(True)
        self.update_show_online_button()
        self._show_layers_loading(self.tr("Loading layers..."))

        request = QtNetwork.QNetworkRequest(QtCore.QUrl(dataset["stac_items_url"]))
        reply = QgsNetworkAccessManager.instance().get(request)
        self._stac_reply = reply
        reply.finished.connect(lambda: self._stac_items_loaded(reply, dataset))

    def _stac_items_loaded(self, reply, dataset):
        reply.deleteLater()
        if reply is not self._stac_reply:
            return
        self._stac_reply = None

        try:
            if reply.error() != _NO_ERROR:
                raise RuntimeError(reply.errorString())
            _set_stac_assets(dataset, json.loads(bytes(reply.readAll())))
        except Exception as exc:
            log(f"Failed to load STAC items from {dataset['stac_items_url']}: {exc}")
            self._show_layers_loading(self.tr("Failed to load layers: {}").format(exc))
            return

        self._hide_layers_loading()
        self.update_layers_tree(dataset)

    def update_layers_tree(self, dataset):
        self.layers_selector.clear()
        self.layers_selector_group.setVisible("stac_collection" in dataset)
        for key, title in dataset.get("asset_titles", {}).items():
            asset_item = QtWidgets.QTreeWidgetItem(self.layers_selector, [title])
            asset_item.setData(0, QtCore.Qt.UserRole, key)
            asset_item.setFlags(asset_item.flags() | QtCore.Qt.ItemIsUserCheckable)
            asset_item.setCheckState(0, QtCore.Qt.Unchecked)
        self.update_show_online_button()

    def update_show_online_button(self):
        self.button_show_online.setEnabled(len(self.checked_layers()) == 1)

    def checked_layers(self):
        keys = []
        for i in range(self.layers_selector.topLevelItemCount()):
            asset_item = self.layers_selector.topLevelItem(i)
            if asset_item.checkState(0) == QtCore.Qt.Checked:
                keys.append(asset_item.data(0, QtCore.Qt.UserRole))
        return keys

    def check_stac_layers(self, selected_datasets):
        if any("stac_collection" in d for d in selected_datasets) and (
            not self.checked_layers()
        ):
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"), self.tr("Choose at least one layer.")
            )
            return False
        return True

    def submit_stac_download(self, dataset):
        params = _stac_params(
            dataset, self.checked_layers(), self.execution_name_le.text()
        )
        job_manager.submit_local_job_as_qgstask(params, "download-stac", self.aoi)

    def btn_show_online(self):
        ret = super().btn_calculate()
        if not ret:
            return

        index = self.data_view.selectedIndexes()[0]
        dataset = self.datasets[self.proxy_model.mapToSource(index).row()]
        params = _stac_params(
            dataset, self.checked_layers(), self.execution_name_le.text()
        )
        self.close()
        job = job_manager.submit_local_job_as_qgstask(params, "view-stac", self.aoi)
        show_on_map_on_finish(job)
