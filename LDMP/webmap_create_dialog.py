"""Prepare, review and publish an unlisted web-map snapshot."""

import json
import math
import os
import re
import tempfile
import time
from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsProviderRegistry,
    QgsRasterLayer,
    QgsTask,
    QgsVectorLayer,
)
from qgis.PyQt import QtCore, QtWidgets
from te_schemas.jobs import JobStatus
from te_schemas.results import Band as JobBand
from te_schemas.results import RasterResults, VectorResults

from . import api
from .constants import TIMEOUT, get_api_url
from .jobs.manager import job_manager
from .layers import _create_color_ramp, _get_band_scale
from .layers import styles as default_raster_styles
from .webmap_sharing import ShareCancelled, ShareClient, ShareError
from .webmap_snapshots import export_raster, export_vector


def _local_layer(layer):
    if not isinstance(layer, (QgsRasterLayer, QgsVectorLayer)) or not layer.isValid():
        raise ShareError("Only valid local raster and vector layers can be shared")
    if isinstance(layer, QgsVectorLayer):
        if layer.providerType() != "ogr" or layer.isEditable() or layer.subsetString():
            raise ShareError(
                "Save vector edits and remove provider filters before sharing; "
                "only local OGR vector layers are supported"
            )
    elif layer.providerType() != "gdal":
        raise ShareError("Only local GDAL raster layers are supported")
    uri = QgsProviderRegistry.instance().decodeUri(layer.providerType(), layer.source())
    path = uri.get("path")
    if not path or not os.path.isfile(path):
        raise ShareError("The layer source must be a local file")
    if isinstance(layer, QgsVectorLayer) and uri.get("layerId") is not None:
        raise ShareError("Load the vector by layer name before sharing")
    return str(path), uri.get("layerName") or None


def _raster_style(path, band_index, band_info):
    style_config = default_raster_styles.get(band_info["name"])
    if style_config is None:
        raise ShareError(
            f"No default Trends.Earth style is defined for {band_info['name']}"
        )
    try:
        items = _create_color_ramp(path, band_index, style_config, band_info)
        band_scale = _get_band_scale(path, band_index)
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
        raise ShareError(
            f"Could not convert the default style for {band_info['name']}: {exc}"
        ) from exc

    nodata = band_info.get("no_data_value")
    configured_nodata = style_config.get("ramp", {}).get("no data", {}).get("value")
    if configured_nodata is not None:
        configured_nodata *= band_scale
    ramp_type = style_config["ramp"]["type"]
    is_categorical = ramp_type.startswith("categorical") and (
        ramp_type != "categorical with dynamic ramp"
    )
    colors = []
    for item in items:
        if item.value == nodata or item.value == configured_nodata:
            continue
        if item.color.alpha() != 255 or not math.isfinite(item.value):
            raise ShareError(
                f"The default style for {band_info['name']} uses unsupported colors"
            )
        value = float(item.value)
        if not is_categorical and band_scale not in (0, 1):
            value /= band_scale
        colors.append((value, item.color.name().lower()))

    if is_categorical:
        values = {}
        for value, color in colors:
            if not value.is_integer():
                raise ShareError(
                    f"The default categories for {band_info['name']} are not integers"
                )
            values[str(int(value))] = color
        if not values or len(values) > 256:
            raise ShareError(
                f"The default categories for {band_info['name']} are unsupported"
            )
        return {"kind": "categorical", "values": values}

    colors.sort(key=lambda item: item[0])
    stops = []
    for value, color in colors:
        if stops and value == stops[-1]["value"]:
            stops[-1]["color"] = color
        else:
            stops.append({"value": value, "color": color})
    if len(stops) < 2 or len(stops) > 32:
        raise ShareError(
            f"The default color ramp for {band_info['name']} is unsupported"
        )
    return {
        "kind": "continuous",
        "min": stops[0]["value"],
        "max": stops[-1]["value"],
        "stops": stops,
    }


def _vector_style(layer):
    style = {
        "kind": "vector",
        "stroke": "#333333",
        "fill": "#cccccc",
        "width": 1,
        "fill_opacity": 0.5,
        "radius": 4,
    }
    renderer = layer.renderer()
    if renderer is None:
        raise ShareError("This vector output has no supported default style")
    if renderer.type() == "singleSymbol" and renderer.symbol():
        color = renderer.symbol().color()
        style["stroke"] = color.name()
        style["fill"] = color.name()
        style["fill_opacity"] = color.alphaF() * renderer.symbol().opacity()
    elif renderer.type() == "categorizedSymbol":
        field = renderer.classAttribute()
        values = {}
        for category in renderer.categories():
            if not category.renderState() or category.symbol() is None:
                raise ShareError(
                    "This categorized vector output has an unsupported default style"
                )
            raw_value = category.value()
            if raw_value is None:
                raise ShareError(
                    "This categorized vector output has an unsupported default style"
                )
            if isinstance(raw_value, bool):
                value = str(raw_value).lower()
            elif isinstance(raw_value, float):
                if not math.isfinite(raw_value) or not raw_value.is_integer():
                    raise ShareError(
                        "This categorized vector output has an unsupported category"
                    )
                value = str(int(raw_value))
            else:
                value = str(raw_value)
            if not value or len(value) > 120 or value in values:
                raise ShareError(
                    "This categorized vector output has unsupported categories"
                )
            values[value] = category.symbol().color().name()
        if field and 1 <= len(values) <= 256:
            style["category"] = {"field": field, "values": values}
        else:
            raise ShareError(
                "This categorized vector output has no supported category field"
            )
    else:
        raise ShareError("This vector output has an unsupported default style")
    return style


_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,119}$")


def _validate_style(style, kind, fields):
    def number(value, lower, upper):
        return (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            and lower <= value <= upper
        )

    def colors(values, integer_keys=False):
        if not isinstance(values, dict) or not 1 <= len(values) <= 256:
            return False
        for key, color in values.items():
            if (
                not isinstance(key, str)
                or not 1 <= len(key) <= 120
                or not isinstance(color, str)
                or not _COLOR.fullmatch(color)
            ):
                return False
            if integer_keys:
                try:
                    if str(int(key)) != key:
                        return False
                except ValueError:
                    return False
        return True

    if kind == "raster" and style.get("kind") == "categorical":
        valid = set(style) == {"kind", "values"} and colors(style.get("values"), True)
    elif kind == "raster" and style.get("kind") == "continuous":
        valid = (
            number(style.get("min"), -float("inf"), float("inf"))
            and number(style.get("max"), -float("inf"), float("inf"))
            and style["min"] < style["max"]
        )
        if valid and set(style) == {"kind", "min", "max", "palette"}:
            valid = style["palette"] in {
                "viridis",
                "plasma",
                "magma",
                "inferno",
                "cividis",
                "turbo",
            }
        elif valid and set(style) == {"kind", "min", "max", "stops"}:
            stops = style["stops"]
            valid = (
                isinstance(stops, list)
                and 2 <= len(stops) <= 32
                and all(
                    isinstance(stop, dict)
                    and set(stop) == {"value", "color"}
                    and number(stop["value"], style["min"], style["max"])
                    and isinstance(stop["color"], str)
                    and _COLOR.fullmatch(stop["color"])
                    and (index == 0 or stop["value"] > stops[index - 1]["value"])
                    for index, stop in enumerate(stops)
                )
                and stops[0]["value"] == style["min"]
                and stops[-1]["value"] == style["max"]
            )
        else:
            valid = False
    elif kind == "vector" and style.get("kind") == "vector":
        required = {"kind", "stroke", "fill", "width", "fill_opacity", "radius"}
        valid = (
            required <= style.keys()
            and not style.keys() - required - {"category"}
            and all(
                isinstance(style[key], str) and _COLOR.fullmatch(style[key])
                for key in ("stroke", "fill")
            )
            and number(style["width"], 0, 10)
            and number(style["fill_opacity"], 0, 1)
            and number(style["radius"], 0, 20)
        )
        if valid and "category" in style:
            category = style["category"]
            valid = (
                isinstance(category, dict)
                and set(category) == {"field", "values"}
                and isinstance(category["field"], str)
                and _FIELD.fullmatch(category["field"])
                and category["field"] in fields
                and colors(category["values"])
            )
    else:
        valid = False
    if not valid:
        raise ShareError("The style is not supported by the web-map service")


class _LayerOptions(QtWidgets.QDialog):
    def __init__(self, layer, band_index=None, band_info=None, parent=None):
        super().__init__(parent)
        self.layer = layer
        self.band_index = band_index
        self.band_info = band_info
        self.setWindowTitle(self.tr("Web-map layer options"))
        self.resize(550, 500)
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.name = QtWidgets.QLineEdit(layer.name())
        self.name.setMaxLength(120)
        self.attribution = QtWidgets.QLineEdit(layer.attribution())
        self.attribution.setMaxLength(500)
        form.addRow(self.tr("Layer name"), self.name)
        form.addRow(self.tr("Attribution"), self.attribution)
        self.min_zoom = QtWidgets.QSpinBox()
        self.max_zoom = QtWidgets.QSpinBox()
        self.fields = QtWidgets.QListWidget()
        self.path, self.source_layer_name = _local_layer(layer)
        if isinstance(layer, QgsRasterLayer):
            if type(band_index) is not int or band_info is None:
                raise ShareError("Select a raster band from the dataset")
            self.default_style = _raster_style(self.path, band_index, band_info)
        else:
            self.min_zoom.setRange(0, 22)
            self.max_zoom.setRange(0, 22)
            self.min_zoom.setValue(6)
            self.max_zoom.setValue(10)
            form.addRow(self.tr("Minimum zoom"), self.min_zoom)
            form.addRow(self.tr("Maximum zoom"), self.max_zoom)
            self.default_style = _vector_style(layer)
        layout.addLayout(form)
        if isinstance(layer, QgsVectorLayer):
            note = QtWidgets.QLabel(
                self.tr(
                    "Select only attributes safe to make public. All selected attributes "
                    "and a generated feature identifier are embedded in the tiles."
                )
            )
            note.setWordWrap(True)
            layout.addWidget(note)
            for field in layer.fields():
                item = QtWidgets.QListWidgetItem(field.name())
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.Unchecked)
                self.fields.addItem(item)
                category = self.default_style.get("category")
                if category and field.name() == category["field"]:
                    item.setCheckState(QtCore.Qt.Checked)
            layout.addWidget(self.fields)
        note = QtWidgets.QLabel(
            self.tr(
                "The map uses the default Trends.Earth style for this output. "
                "Style editing is not available."
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.configuration = None

    def _accept(self):
        try:
            name = self.name.text().strip()
            if not name:
                raise ShareError("A layer name is required")
            fields = [
                self.fields.item(index).text()
                for index in range(self.fields.count())
                if self.fields.item(index).checkState() == QtCore.Qt.Checked
            ]
            if isinstance(self.layer, QgsVectorLayer):
                category = self.default_style.get("category")
                if category and (
                    not isinstance(category, dict)
                    or category.get("field") not in fields
                ):
                    raise ShareError(
                        "The vector category field must be selected for export"
                    )
                if self.min_zoom.value() > self.max_zoom.value():
                    raise ShareError("Minimum zoom must not exceed maximum zoom")
                kind = "vector"
            else:
                kind = "raster"
            _validate_style(self.default_style, kind, fields)
            self.configuration = {
                "name": name,
                "kind": kind,
                "path": self.path,
                "source_layer_name": self.source_layer_name,
                "band": self.band_index,
                "fields": fields,
                "min_zoom": self.min_zoom.value(),
                "max_zoom": self.max_zoom.value(),
                "style": self.default_style,
                "attribution": self.attribution.text(),
            }
        except ShareError as exc:
            QtWidgets.QMessageBox.warning(self, self.tr("Web-map layer"), str(exc))
            return
        self.accept()


class _PrepareTask(QgsTask):
    def __init__(self, configurations, directory, callback):
        super().__init__("Prepare web-map snapshots", QgsTask.CanCancel)
        self.configurations = configurations
        self.directory = directory
        self.callback = callback
        self.snapshots = []
        self.error = None

    def run(self):
        try:
            for index, config in enumerate(self.configurations):
                path = Path(self.directory) / f"layer-{index}"
                if config["kind"] == "raster":
                    path = path.with_suffix(".tif")
                    digest = export_raster(
                        config["path"], path, config["band"], self.isCanceled
                    )
                    declaration = {"kind": "raster", "band": 1}
                else:
                    path = path.with_suffix(".pmtiles")
                    digest = export_vector(
                        config["path"],
                        config["source_layer_name"],
                        path,
                        config["fields"],
                        config["min_zoom"],
                        config["max_zoom"],
                        self.isCanceled,
                    )
                    declaration = {"kind": "vector", "source_layer": "analysis"}
                declaration.update(
                    name=config["name"],
                    style=config["style"],
                    attribution=config["attribution"],
                    **digest,
                )
                self.snapshots.append({"path": path, "declaration": declaration})
                self.setProgress(100 * (index + 1) / len(self.configurations))
            return True
        except (ShareError, OSError, RuntimeError) as exc:
            self.error = str(exc)
            return False

    def finished(self, result):
        self.callback(result, self.snapshots, self.error)


class _PublishTask(QgsTask):
    def __init__(
        self,
        base_url,
        token,
        title,
        retention,
        snapshots,
        share_id,
        callback,
        update_existing=False,
    ):
        super().__init__("Upload and publish web map", QgsTask.CanCancel)
        self.base_url = base_url
        self.token = token
        self.title = title
        self.retention = retention
        self.snapshots = snapshots
        self.share_id = share_id
        self.update_existing = update_existing
        self.callback = callback
        self.error = None
        self.result = None
        self.published = False
        self.updated = False

    def _check_cancelled(self):
        if self.isCanceled():
            raise ShareCancelled("Upload cancelled")

    def run(self):
        client = None
        try:
            self._check_cancelled()
            client = ShareClient(self.base_url, self.token, timeout=TIMEOUT)
            resuming = bool(self.share_id)
            if self.update_existing:
                share = client.status(self.share_id)
                pending = [
                    layer for layer in share["layers"] if not layer.get("published")
                ]
                if share.get("update_state") == "idle":
                    share = client.add_layers(
                        self.share_id,
                        [snapshot["declaration"] for snapshot in self.snapshots],
                    )
                    pending = [
                        layer for layer in share["layers"] if not layer.get("published")
                    ]
                expected_names = {
                    item["declaration"]["name"] for item in self.snapshots
                }
                if {layer["name"] for layer in pending} != expected_names:
                    raise ShareError(
                        "The pending share update does not match the prepared layers"
                    )
                if share.get("update_state") not in (
                    "uploading",
                    "failed",
                    "validating",
                ):
                    raise ShareError("The published map cannot accept this update")
                layers = {layer["name"]: layer for layer in pending}
                if share["update_state"] == "validating":
                    share = client.complete(
                        self.share_id,
                        [{"layer_id": layer["id"], "parts": []} for layer in pending],
                    )
                else:
                    share = self._upload_pending(client, layers, share)
                while share.get("update_state") == "validating":
                    for _ in range(5):
                        self._check_cancelled()
                        time.sleep(1)
                    share = client.status(self.share_id)
                if share.get("update_state") == "failed":
                    details = "; ".join(
                        error["error"] for error in share.get("validation_errors", [])
                    )
                    raise ShareError(
                        "Server validation failed: "
                        + (details or "The new layers could not be validated")
                    )
                if share.get("update_state") != "idle":
                    raise ShareError("The layer update did not complete")
                self.result = {"share": share}
                self.updated = True
                self.published = True
                self.setProgress(100)
                return True
            if self.share_id:
                share = client.status(self.share_id)
            else:
                share = client.create(
                    self.title,
                    self.retention,
                    [snapshot["declaration"] for snapshot in self.snapshots],
                )
                self.share_id = share["id"]
            layers = {layer["name"]: layer for layer in share["layers"]}
            if set(layers) != {item["declaration"]["name"] for item in self.snapshots}:
                raise ShareError("The draft layers do not match the prepared snapshots")
            if share["state"] in ("draft", "uploading"):
                share = self._upload_pending(client, layers, share)
            elif share["state"] == "validating" and resuming:
                # Completion is idempotent and can recover a lost validation enqueue.
                share = client.complete(
                    self.share_id,
                    [
                        {"layer_id": layer["id"], "parts": []}
                        for layer in layers.values()
                    ],
                )
            while share["state"] == "validating":
                for _ in range(5):
                    self._check_cancelled()
                    time.sleep(1)
                share = client.status(self.share_id)
            if share["state"] == "failed":
                details = "; ".join(
                    error["error"] for error in share.get("validation_errors", [])
                )
                raise ShareError("Server validation failed: " + details)
            if share.get("ready_at"):
                raise ShareError(
                    "This share is already published; rotate its link in Manage web-map shares"
                )
            if share["state"] != "ready":
                raise ShareError("The draft cannot be published in its current state")
            self._check_cancelled()
            for attempt in range(13):
                try:
                    self.result = client.publish(self.share_id)
                    break
                except ShareError as exc:
                    if exc.status_code != 503 or attempt == 12:
                        raise
                    for _ in range(5):
                        self._check_cancelled()
                        time.sleep(1)
            if not isinstance(self.result.get("link"), str) or not self.result.get(
                "share", {}
            ).get("expires_at"):
                raise ShareError("The server returned an invalid publication response")
            self.setProgress(100)
            self.published = True
            return True
        except (
            ShareError,
            OSError,
            RuntimeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            self.error = str(exc)
            return False
        finally:
            self.token = None
            if client:
                client.close()

    def _upload_pending(self, client, layers, share):
        errors = {error["layer_id"] for error in share.get("validation_errors", [])}
        manifest = []
        total = sum(item["declaration"]["size_bytes"] for item in self.snapshots)
        uploaded = 0
        for item in self.snapshots:
            self._check_cancelled()
            layer = layers[item["declaration"]["name"]]
            size = item["declaration"]["size_bytes"]
            if layer["upload_completed"] and layer["id"] not in errors:
                manifest.append({"layer_id": layer["id"], "parts": []})
            else:
                manifest.append(
                    client.upload(
                        self.share_id,
                        layer["id"],
                        item["path"],
                        cancelled=self.isCanceled,
                        progress=lambda count, offset=uploaded: self.setProgress(
                            90 * (offset + count) / total
                        ),
                    )
                )
            uploaded += size
        self._check_cancelled()
        return client.complete(self.share_id, manifest)

    def finished(self, result):
        self.callback(self.published or result, self.result, self.share_id, self.error)


class CreateWebmapDialog(QtWidgets.QDialog):
    def __init__(
        self, parent=None, on_published=None, job=None, existing_share_id=None
    ):
        super().__init__(parent)
        self.existing_share_id = existing_share_id
        self.setWindowTitle(
            self.tr("Add layers to shared map")
            if existing_share_id
            else self.tr("Share web map")
        )
        self.resize(650, 620)
        self.on_published = on_published
        self.api_client = api.APIClient(get_api_url(), TIMEOUT)
        self.directory = tempfile.TemporaryDirectory(prefix="te-webmap-")
        self.configurations = []
        self.snapshots = []
        self.task = None
        self.share_id = None
        layout = QtWidgets.QVBoxLayout(self)
        warning_text = (
            "The existing public link remains active while these layers are uploaded "
            "and validated. Recipients can forward the link or save content."
            if existing_share_id
            else "An unlisted link gives anyone who has it access to the map. "
            "Recipients can forward the link or save content. Review attribution, "
            "rights, sensitive locations and public vector attributes before sharing. "
            "The entire layer is shared, not just selected features."
        )
        warning = QtWidgets.QLabel(self.tr(warning_text))
        warning.setWordWrap(True)
        layout.addWidget(warning)
        form = QtWidgets.QFormLayout()
        self.title = QtWidgets.QLineEdit()
        self.title.setMaxLength(120)
        self.retention = QtWidgets.QComboBox()
        for days in (7, 30, 90):
            self.retention.addItem(self.tr("{days} days").format(days=days), days)
        form.addRow(self.tr("Map title"), self.title)
        form.addRow(self.tr("Retention after publication"), self.retention)
        layout.addLayout(form)
        if existing_share_id:
            self.title.hide()
            self.retention.hide()
            form.labelForField(self.title).hide()
            form.labelForField(self.retention).hide()

        self.job_choice = QtWidgets.QComboBox()
        self.output_choice = QtWidgets.QComboBox()
        self.band_choice = QtWidgets.QComboBox()
        self.job_choice_label = QtWidgets.QLabel(self.tr("Dataset"))
        self.output_choice_label = QtWidgets.QLabel(self.tr("Output"))
        self.band_choice_label = QtWidgets.QLabel(self.tr("Band"))
        selectors = QtWidgets.QFormLayout()
        selectors.addRow(self.job_choice_label, self.job_choice)
        selectors.addRow(self.output_choice_label, self.output_choice)
        selectors.addRow(self.band_choice_label, self.band_choice)
        layout.addLayout(selectors)
        add = QtWidgets.QPushButton(self.tr("Add selected output"))
        add.clicked.connect(self._add_layer)
        layout.addWidget(add)
        self.layers = QtWidgets.QListWidget()
        layout.addWidget(self.layers)
        remove = QtWidgets.QPushButton(self.tr("Remove selected layer"))
        remove.clicked.connect(self._remove_layer)
        layout.addWidget(remove)
        self.confirm = QtWidgets.QCheckBox(
            self.tr(
                "I have the rights to share these layers and have checked them for sensitive information."
            )
        )
        layout.addWidget(self.confirm)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        status_area = QtWidgets.QScrollArea()
        status_area.setWidgetResizable(True)
        status_area.setWidget(self.status)
        status_area.setMinimumHeight(100)
        layout.addWidget(status_area)
        self.progress = QtWidgets.QProgressBar()
        layout.addWidget(self.progress)
        buttons = QtWidgets.QHBoxLayout()
        self.prepare_button = QtWidgets.QPushButton(self.tr("Prepare and review"))
        self.upload_button = QtWidgets.QPushButton(
            self.tr("Upload and add layers")
            if existing_share_id
            else self.tr("Upload and publish")
        )
        self.cancel_button = QtWidgets.QPushButton(self.tr("Cancel task"))
        self.close_button = QtWidgets.QPushButton(self.tr("Close"))
        for button in (
            self.prepare_button,
            self.upload_button,
            self.cancel_button,
            self.close_button,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.prepare_button.clicked.connect(self._prepare)
        self.upload_button.clicked.connect(self._upload)
        self.cancel_button.clicked.connect(self._cancel)
        self.close_button.clicked.connect(self.close)
        self.upload_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.job_choice.currentIndexChanged.connect(self._populate_outputs)
        self.output_choice.currentIndexChanged.connect(self._populate_bands)
        local_jobs = [
            item
            for item in job_manager.relevant_jobs
            if item.status in (JobStatus.DOWNLOADED, JobStatus.GENERATED_LOCALLY)
            and (item.is_raster() or item.is_vector())
            and not item.is_timeseries()
        ]
        if job is not None:
            local_jobs = [job]
            self.job_choice_label.hide()
            self.job_choice.hide()
        for item in local_jobs:
            label = item.visible_name or item.task_name or str(item.id)
            self.job_choice.addItem(label, item)
        self._populate_outputs()
        self._editing_widgets = [
            self.title,
            self.retention,
            self.job_choice,
            self.output_choice,
            self.band_choice,
            add,
            remove,
            self.prepare_button,
        ]

    def _populate_outputs(self):
        self.output_choice.clear()
        self.band_choice.clear()
        job = self.job_choice.currentData()
        if job is None or not job_manager.ensure_results_loaded(job):
            return
        for result in job._get_results_list():
            if not isinstance(result, (RasterResults, VectorResults)) or not result.uri:
                continue
            path = Path(str(result.uri.uri))
            if not path.is_file():
                continue
            if isinstance(result, RasterResults) and result.get_bands():
                self.output_choice.addItem(
                    self.tr("{name} (raster)").format(name=result.name), result
                )
            elif isinstance(result, VectorResults):
                self.output_choice.addItem(
                    self.tr("{name} (vector)").format(name=result.name), result
                )
        self._populate_bands()

    def _populate_bands(self):
        result = self.output_choice.currentData()
        raster = isinstance(result, RasterResults)
        self.band_choice_label.setVisible(raster)
        self.band_choice.setVisible(raster)
        self.band_choice.clear()
        if raster:
            for index, band in enumerate(result.get_bands(), start=1):
                self.band_choice.addItem(
                    self.tr("{name} (band {index})").format(
                        name=band.name, index=index
                    ),
                    index,
                )

    def _add_layer(self):
        result = self.output_choice.currentData()
        if result is None:
            return
        try:
            path = str(result.uri.uri)
            band_index = None
            band_info = None
            if isinstance(result, RasterResults):
                band_index = self.band_choice.currentData()
                if type(band_index) is not int:
                    raise ShareError("Select an output band")
                band = result.get_bands()[band_index - 1]
                band_info = JobBand.Schema().dump(band)
                layer = QgsRasterLayer(path, band.name, "gdal")
            else:
                source = (
                    f"{path}|layername={result.name}"
                    if Path(path).suffix.lower() in (".gpkg", ".sqlite")
                    else path
                )
                layer = QgsVectorLayer(source, result.name, "ogr")
            if not layer.isValid():
                raise ShareError("The selected dataset output could not be opened")
            _local_layer(layer)
        except ShareError as exc:
            QtWidgets.QMessageBox.warning(self, self.tr("Share web map"), str(exc))
            return
        try:
            dialog = _LayerOptions(layer, band_index, band_info, self)
        except ShareError as exc:
            QtWidgets.QMessageBox.warning(self, self.tr("Share web map"), str(exc))
            return
        if dialog.exec():
            config = dialog.configuration
            if len(self.configurations) >= 10 or any(
                item["name"] == config["name"] for item in self.configurations
            ):
                QtWidgets.QMessageBox.warning(
                    self,
                    self.tr("Share web map"),
                    self.tr("Choose unique names and at most 10 layers."),
                )
                return
            self.configurations.append(config)
            self.layers.addItem(
                self.tr("{name} ({kind})").format(
                    name=config["name"], kind=config["kind"]
                )
            )
            self.upload_button.setEnabled(False)

    def _remove_layer(self):
        row = self.layers.currentRow()
        if row >= 0:
            self.layers.takeItem(row)
            self.configurations.pop(row)
            self.upload_button.setEnabled(False)

    def _busy(self, busy):
        for widget in self._editing_widgets:
            widget.setEnabled(
                not busy
                and (self.share_id is None or self.existing_share_id is not None)
            )
        self.upload_button.setEnabled(not busy and bool(self.snapshots))
        self.cancel_button.setEnabled(busy)
        self.close_button.setEnabled(not busy)

    def _prepare(self):
        if (
            not self.existing_share_id and not self.title.text().strip()
        ) or not self.configurations:
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("Share web map"),
                self.tr("Enter a title and select at least one output."),
            )
            return
        self.directory.cleanup()
        self.directory = tempfile.TemporaryDirectory(prefix="te-webmap-")
        self.snapshots = []
        self.confirm.setChecked(False)
        self.status.setText(self.tr("Preparing and checking snapshots..."))
        self.task = _PrepareTask(
            self.configurations, self.directory.name, self._prepared
        )
        self.task.progressChanged.connect(
            lambda value: self.progress.setValue(int(value))
        )
        self._busy(True)
        QgsApplication.taskManager().addTask(self.task)

    def _prepared(self, succeeded, snapshots, error):
        self.task = None
        self.snapshots = snapshots if succeeded else []
        self._busy(False)
        if not succeeded:
            self.status.setText(
                self.tr("Snapshot preparation failed: {error}").format(
                    error=error or self.tr("Cancelled")
                )
            )
            return
        total = sum(item["declaration"]["size_bytes"] for item in snapshots)
        details = "\n".join(
            f"{item['declaration']['name']}: {item['declaration']['size_bytes']} bytes; "
            f"attribution: {item['declaration']['attribution']}; "
            f"style: {json.dumps(item['declaration']['style'])}; "
            + (
                f"public fields: {', '.join(config['fields'])}; "
                f"zooms: {config['min_zoom']}-{config['max_zoom']}"
                if config["kind"] == "vector"
                else f"source band: {config['band']}"
            )
            for item, config in zip(snapshots, self.configurations)
        )
        self.status.setText(
            self.tr("Prepared {bytes} bytes. Review before upload:\n{details}").format(
                bytes=total, details=details
            )
        )

    def _upload(self):
        if not self.confirm.isChecked():
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("Share web map"),
                self.tr(
                    "Confirm the sharing rights and sensitive-information check first."
                ),
            )
            return
        base_url = get_api_url()
        self.api_client.url = base_url
        token = self.api_client.login()
        if not token:
            QtWidgets.QMessageBox.warning(
                self, self.tr("Share web map"), self.tr("Authentication is required.")
            )
            return
        self.status.setText(
            self.tr(
                "Uploading and validating the new layers. This may take several minutes."
                if self.existing_share_id
                else "Uploading, validating and publishing. This may take several minutes."
            )
        )
        self.task = _PublishTask(
            base_url,
            token,
            self.title.text().strip(),
            self.retention.currentData(),
            self.snapshots,
            self.existing_share_id or self.share_id,
            self._published,
            update_existing=bool(self.existing_share_id),
        )
        self.task.progressChanged.connect(
            lambda value: self.progress.setValue(int(value))
        )
        self._busy(True)
        QgsApplication.taskManager().addTask(self.task)

    def _published(self, succeeded, result, share_id, error):
        self.task = None
        self.share_id = share_id
        self._busy(False)
        if not succeeded:
            if error and error.startswith("Server validation failed:"):
                self.upload_button.setEnabled(bool(self.existing_share_id))
                self.status.setText(
                    self.tr(
                        "{error}. Existing published layers remain available. "
                        "Correct the source or try again."
                    ).format(error=error)
                )
                return
            self.status.setText(
                self.tr(
                    "Sharing failed: {error}. Draft ID: {id}. Retry or revoke it in Manage web-map shares."
                ).format(
                    error=error or self.tr("Cancelled"),
                    id=share_id or self.tr("not created"),
                )
            )
            return
        self.upload_button.setEnabled(False)
        if self.existing_share_id:
            self.status.setText(
                self.tr("The new layers are available in the existing shared map.")
            )
        elif self.on_published:
            self.on_published(result)
        self.directory.cleanup()
        self.accept()

    def _cancel(self):
        if self.task:
            self.task.cancel()

    def closeEvent(self, event):
        if self.task:
            event.ignore()
            return
        self.directory.cleanup()
        super().closeEvent(event)

    def reject(self):
        if self.task is None:
            self.directory.cleanup()
            super().reject()
