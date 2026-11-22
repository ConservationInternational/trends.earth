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
    QgsColorRampShader,
    QgsProject,
    QgsProviderRegistry,
    QgsRasterLayer,
    QgsTask,
    QgsVectorLayer,
)
from qgis.PyQt import QtCore, QtWidgets

from . import api
from .constants import TIMEOUT, get_api_url
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


def _raster_style(layer):
    renderer = layer.renderer()
    if renderer is None:
        return None
    if renderer.type() == "paletted":
        classes = renderer.classes()
        values = {}
        for item in classes:
            if not float(item.value).is_integer() or item.color.alpha() != 255:
                return None
            values[str(int(item.value))] = item.color.name()
        if 1 <= len(values) <= 256:
            return {"kind": "categorical", "values": values}
    if renderer.type() == "singlebandpseudocolor":
        raster_shader = renderer.shader()
        if raster_shader is None:
            return None
        shader = raster_shader.rasterShaderFunction()
        if (
            isinstance(shader, QgsColorRampShader)
            and shader.colorRampType() == QgsColorRampShader.Exact
        ):
            values = {}
            for item in shader.colorRampItemList():
                if (
                    not math.isfinite(item.value)
                    or not float(item.value).is_integer()
                    or item.color.alpha() != 255
                ):
                    return None
                values[str(int(item.value))] = item.color.name()
            if 1 <= len(values) <= 256:
                return {"kind": "categorical", "values": values}
    return None


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
        return style
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
                return style
            raw_value = category.value()
            if raw_value is None:
                return style
            if isinstance(raw_value, bool):
                value = str(raw_value).lower()
            elif isinstance(raw_value, float):
                if not math.isfinite(raw_value) or not raw_value.is_integer():
                    return style
                value = str(int(raw_value))
            else:
                value = str(raw_value)
            if not value or len(value) > 120 or value in values:
                return style
            values[value] = category.symbol().color().name()
        if field and 1 <= len(values) <= 256:
            style["category"] = {"field": field, "values": values}
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
            set(style) == {"kind", "min", "max", "palette"}
            and number(style.get("min"), -float("inf"), float("inf"))
            and number(style.get("max"), -float("inf"), float("inf"))
            and style["min"] < style["max"]
            and style["palette"]
            in {"viridis", "plasma", "magma", "inferno", "cividis", "turbo"}
        )
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
    def __init__(self, layer, parent=None):
        super().__init__(parent)
        self.layer = layer
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
        self.band = QtWidgets.QSpinBox()
        self.min_zoom = QtWidgets.QSpinBox()
        self.max_zoom = QtWidgets.QSpinBox()
        self.fields = QtWidgets.QListWidget()
        if isinstance(layer, QgsRasterLayer):
            self.band.setRange(1, max(1, layer.bandCount()))
            renderer = layer.renderer()
            if renderer and hasattr(renderer, "band"):
                self.band.setValue(renderer.band())
            form.addRow(self.tr("Raster band"), self.band)
            default_style = _raster_style(layer)
        else:
            self.min_zoom.setRange(0, 22)
            self.max_zoom.setRange(0, 22)
            self.min_zoom.setValue(6)
            self.max_zoom.setValue(10)
            form.addRow(self.tr("Minimum zoom"), self.min_zoom)
            form.addRow(self.tr("Maximum zoom"), self.max_zoom)
            default_style = _vector_style(layer)
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
            layout.addWidget(self.fields)
        note = QtWidgets.QLabel(
            self.tr(
                "Review or edit the API style JSON. Styles are limited to categorical "
                "or supported continuous raster palettes, and uniform or categorical "
                "vector styles. Extracted colors and symbol sizes can be approximate; "
                "unsupported symbology cannot be reproduced automatically."
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.style = QtWidgets.QPlainTextEdit()
        if default_style:
            self.style.setPlainText(json.dumps(default_style, indent=2))
        else:
            self.style.setPlaceholderText(
                '{"kind":"continuous","min":0,"max":1,"palette":"viridis"}'
            )
        layout.addWidget(self.style)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.configuration = None

    def _accept(self):
        try:
            style = json.loads(self.style.toPlainText())
            if not isinstance(style, dict):
                raise TypeError
            path, source_layer = _local_layer(self.layer)
            name = self.name.text().strip()
            if not name:
                raise ShareError("A layer name is required")
            fields = [
                self.fields.item(index).text()
                for index in range(self.fields.count())
                if self.fields.item(index).checkState() == QtCore.Qt.Checked
            ]
            if isinstance(self.layer, QgsVectorLayer):
                if style.get("kind") != "vector":
                    raise ShareError("A vector style is required")
                category = style.get("category")
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
                if style.get("kind") not in ("categorical", "continuous"):
                    raise ShareError("A supported raster style is required")
                kind = "raster"
            _validate_style(style, kind, fields)
            self.configuration = {
                "name": name,
                "kind": kind,
                "path": path,
                "source_layer_name": source_layer,
                "band": self.band.value(),
                "fields": fields,
                "min_zoom": self.min_zoom.value(),
                "max_zoom": self.max_zoom.value(),
                "style": style,
                "attribution": self.attribution.text(),
            }
        except (ValueError, TypeError):
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("Web-map layer"),
                self.tr("Enter a valid JSON style object."),
            )
            return
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
        self, base_url, token, title, retention, snapshots, share_id, callback
    ):
        super().__init__("Upload and publish web map", QgsTask.CanCancel)
        self.base_url = base_url
        self.token = token
        self.title = title
        self.retention = retention
        self.snapshots = snapshots
        self.share_id = share_id
        self.callback = callback
        self.error = None
        self.result = None
        self.published = False

    def _check_cancelled(self):
        if self.isCanceled():
            raise ShareCancelled("Upload cancelled")

    def run(self):
        client = None
        try:
            self._check_cancelled()
            client = ShareClient(self.base_url, self.token, timeout=TIMEOUT)
            resuming = bool(self.share_id)
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
                errors = {
                    error["layer_id"] for error in share.get("validation_errors", [])
                }
                manifest = []
                total = sum(
                    item["declaration"]["size_bytes"] for item in self.snapshots
                )
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
                                progress=lambda count, offset=uploaded: (
                                    self.setProgress(90 * (offset + count) / total)
                                ),
                            )
                        )
                    uploaded += size
                self._check_cancelled()
                share = client.complete(self.share_id, manifest)
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

    def finished(self, result):
        self.callback(self.published or result, self.result, self.share_id, self.error)


class CreateWebmapDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, on_published=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Share web map"))
        self.resize(650, 500)
        self.on_published = on_published
        self.api_client = api.APIClient(get_api_url(), TIMEOUT)
        self.directory = tempfile.TemporaryDirectory(prefix="te-webmap-")
        self.configurations = []
        self.snapshots = []
        self.task = None
        self.share_id = None
        layout = QtWidgets.QVBoxLayout(self)
        warning = QtWidgets.QLabel(
            self.tr(
                "An unlisted link gives anyone who has it access to the map. "
                "Recipients can forward the link or save content. Review attribution, "
                "rights, sensitive locations and public vector attributes before sharing. "
                "The entire layer is shared, not just selected features."
            )
        )
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
        self.layer_choice = QtWidgets.QComboBox()
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, (QgsRasterLayer, QgsVectorLayer)):
                self.layer_choice.addItem(layer.name(), layer.id())
        add = QtWidgets.QPushButton(self.tr("Add and configure layer"))
        add.clicked.connect(self._add_layer)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.layer_choice)
        row.addWidget(add)
        layout.addLayout(row)
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
        self.upload_button = QtWidgets.QPushButton(self.tr("Upload and publish"))
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
        self._editing_widgets = [
            self.title,
            self.retention,
            self.layer_choice,
            add,
            remove,
            self.prepare_button,
        ]

    def _add_layer(self):
        layer = QgsProject.instance().mapLayer(self.layer_choice.currentData())
        if layer is None:
            return
        try:
            _local_layer(layer)
        except ShareError as exc:
            QtWidgets.QMessageBox.warning(self, self.tr("Share web map"), str(exc))
            return
        dialog = _LayerOptions(layer, self)
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
            self.layers.addItem(f"{config['name']} ({config['kind']})")
            self.upload_button.setEnabled(False)

    def _remove_layer(self):
        row = self.layers.currentRow()
        if row >= 0:
            self.layers.takeItem(row)
            self.configurations.pop(row)
            self.upload_button.setEnabled(False)

    def _busy(self, busy):
        for widget in self._editing_widgets:
            widget.setEnabled(not busy and self.share_id is None)
        self.upload_button.setEnabled(not busy and bool(self.snapshots))
        self.cancel_button.setEnabled(busy)
        self.close_button.setEnabled(not busy)

    def _prepare(self):
        if not self.title.text().strip() or not self.configurations:
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("Share web map"),
                self.tr("Enter a title and select at least one layer."),
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
        token = self.api_client.login()
        if not token:
            QtWidgets.QMessageBox.warning(
                self, self.tr("Share web map"), self.tr("Authentication is required.")
            )
            return
        self.status.setText(
            self.tr(
                "Uploading, validating and publishing. This may take several minutes."
            )
        )
        self.task = _PublishTask(
            self.api_client.url,
            token,
            self.title.text().strip(),
            self.retention.currentData(),
            self.snapshots,
            self.share_id,
            self._published,
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
                self.upload_button.setEnabled(False)
                self.status.setText(
                    self.tr(
                        "{error}. Revoke the draft in Manage web-map shares, "
                        "then create a new share with corrected data."
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
        if self.on_published:
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
