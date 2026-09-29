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

from qgis.PyQt import QtCore, QtWidgets

from . import stac_conf
from .jobs.manager import job_manager


def _stac_dataset_item(category, collection_id, stac):
    collection = stac["collection"]
    features = stac["items"]["features"]
    min_x = min(f["bbox"][0] for f in features)
    min_y = min(f["bbox"][1] for f in features)
    max_x = max(f["bbox"][2] for f in features)
    max_y = max(f["bbox"][3] for f in features)
    temporal = collection["extent"].get("temporal", {})
    interval = temporal.get("interval", [[None, None]])[0]
    start_year = "NA"
    end_year = "NA"
    if (interval[0] or "")[:4]:
        start_year = int(interval[0][:4])
    if (interval[1] or "")[:4]:
        end_year = int(interval[1][:4])

    if start_year == end_year:
        start_year = "NA"
        end_year = "NA"

    gsd = collection.get("summaries", {}).get("gsd", [])
    assets = {
        key: asset
        for feature in features
        for key, asset in feature["assets"].items()
        if "data" in asset.get("roles", [])
    }
    return {
        "category": category,
        "title": collection.get("title", collection_id),
        "Units": "",
        "Spatial Resolution": f"{gsd[0]} m" if gsd else "",
        "Start year": start_year,
        "End year": end_year,
        "extent_lat": f"{min_y:.3f} - {max_y:.3f}",
        "extent_lon": f"{min_x:.3f} - {max_x:.3f}",
        "Data source": ", ".join(p["name"] for p in collection.get("providers", [])),
        "Source": collection_id,
        "Citation": collection.get("sci:citation", ""),
        "stac_collection": collection_id,
        "assets": {key: asset["href"] for key, asset in assets.items()},
        "layers": {
            layer: {
                key: assets[key].get("title", key) for key in layer_config["assets"]
            }
            for layer, layer_config in stac["layers"].items()
        },
        "styles": {
            key: layer_config["style"]
            for layer_config in stac["layers"].values()
            for key in layer_config["assets"]
        },
    }


def _stac_params(dataset, keys, task_name):
    titles = {
        key: title
        for assets in dataset["layers"].values()
        for key, title in assets.items()
    }
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
        for cat, collections in stac_conf.STAC_DATASETS.items():
            for collection_id, stac in collections.items():
                self.datasets.append(_stac_dataset_item(cat, collection_id, stac))

    def stac_selection_changed(self):
        index = self.data_view.selectedIndexes()[0]
        self.update_layers_tree(
            self.datasets[self.proxy_model.mapToSource(index).row()]
        )

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
                asset_item.setFlags(asset_item.flags() | QtCore.Qt.ItemIsUserCheckable)
                asset_item.setCheckState(0, QtCore.Qt.Unchecked)
        self.update_show_online_button()

    def update_show_online_button(self):
        self.button_show_online.setEnabled(len(self.checked_layers()) == 1)

    def checked_layers(self):
        keys = []
        for i in range(self.layers_selector.topLevelItemCount()):
            layer_item = self.layers_selector.topLevelItem(i)
            for j in range(layer_item.childCount()):
                asset_item = layer_item.child(j)
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
