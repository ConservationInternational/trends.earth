"""Create unlisted web maps or add dataset outputs to existing ones."""

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
from te_schemas.results import Band as JobBand
from te_schemas.results import RasterResults, VectorResults

from . import api
from .constants import TIMEOUT, get_api_url
from .jobs.manager import job_manager
from .layers import (
    _create_color_ramp,
    _get_band_scale,
    get_band_title,
    open_vector_layer,
)
from .layers import styles as default_raster_styles
from .webmap_dialog import (
    WebmapSharesDialog,
    _OwnerTask,
    can_add_layers,
    confirm_public_sharing,
    show_link,
)
from .webmap_mask import MaskSelector
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
    shader = style_config["ramp"].get("shader", "exact")
    is_categorical = ramp_type.startswith("categorical") and (
        ramp_type != "categorical with dynamic ramp" and shader != "interpolated"
    )
    # Generated ramps use scaled units; fixed style items already use raw values.
    unscale = band_scale not in (0, 1) and (
        ramp_type.endswith("stretch") or ramp_type == "categorical with dynamic ramp"
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
        if unscale:
            value /= band_scale
        label = str(item.label or "").strip()[:_MAX_LABEL]
        colors.append((value, item.color.name().lower(), label))

    if is_categorical:
        values = {}
        labels = {}
        for value, color, label in colors:
            if not value.is_integer():
                raise ShareError(
                    f"The default categories for {band_info['name']} are not integers"
                )
            values[str(int(value))] = color
            if label:
                labels[str(int(value))] = label
        if not values or len(values) > 256:
            raise ShareError(
                f"The default categories for {band_info['name']} are unsupported"
            )
        style = {"kind": "categorical", "values": values}
        if labels:
            style["labels"] = labels
        if shader == "discrete":
            style["classification"] = "discrete"
        return style

    colors.sort(key=lambda item: item[0])
    stops = []
    for value, color, label in colors:
        if stops and value == stops[-1]["value"]:
            stops[-1] = {"value": value, "color": color}
        else:
            stops.append({"value": value, "color": color})
        if label:
            stops[-1]["label"] = label
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
        labels = {}
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
            label = str(category.label() or "").strip()[:_MAX_LABEL]
            if label and label != value:
                labels[value] = label
        if field and 1 <= len(values) <= 256:
            style["category"] = {
                "field": field,
                "values": values,
                # Legend text is supplied by the plugin so it can be translated.
                "other_label": QtCore.QCoreApplication.translate(
                    "webmap", "Other or missing values"
                )[:_MAX_LABEL],
            }
            if labels:
                style["category"]["labels"] = labels
        else:
            raise ShareError(
                "This categorized vector output has no supported category field"
            )
    else:
        raise ShareError("This vector output has an unsupported default style")
    return style


_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_MAX_LABEL = 200
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

    def labels(values, container):
        return "labels" not in container or (
            isinstance(container["labels"], dict)
            and container["labels"].keys() <= values.keys()
            and all(
                isinstance(label, str) and 1 <= len(label) <= _MAX_LABEL
                for label in container["labels"].values()
            )
        )

    if kind == "raster" and style.get("kind") == "categorical":
        valid = (
            {"kind", "values"}
            <= style.keys()
            <= {"kind", "values", "labels", "classification"}
            and colors(style.get("values"), True)
            and labels(style["values"], style)
            and style.get("classification", "exact") in ("exact", "discrete")
        )
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
                    and {"value", "color"} <= stop.keys() <= {"value", "color", "label"}
                    and (
                        "label" not in stop
                        or (
                            isinstance(stop["label"], str)
                            and 1 <= len(stop["label"]) <= _MAX_LABEL
                        )
                    )
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
                and {"field", "values"}
                <= category.keys()
                <= {"field", "values", "labels", "other_label"}
                and (
                    "other_label" not in category
                    or (
                        isinstance(category["other_label"], str)
                        and 1 <= len(category["other_label"]) <= _MAX_LABEL
                    )
                )
                and isinstance(category["field"], str)
                and _FIELD.fullmatch(category["field"])
                and category["field"] in fields
                and colors(category["values"])
                and labels(category["values"], category)
            )
    else:
        valid = False
    if not valid:
        raise ShareError("The style is not supported by the web-map service")


def _layer_configuration(
    layer,
    style,
    band_index=None,
    name=None,
    attribution=None,
    fields=(),
    min_zoom=0,
    max_zoom=0,
):
    path, source_layer_name = _local_layer(layer)
    name = (layer.name() if name is None else name).strip()
    if not name:
        raise ShareError("A layer name is required")
    fields = list(fields)
    if isinstance(layer, QgsVectorLayer):
        category = style.get("category")
        if category and (
            not isinstance(category, dict) or category.get("field") not in fields
        ):
            raise ShareError("The vector category field must be selected for export")
        if min_zoom > max_zoom:
            raise ShareError("Minimum zoom must not exceed maximum zoom")
        kind = "vector"
    else:
        kind = "raster"
    _validate_style(style, kind, fields)
    return {
        "name": name,
        "kind": kind,
        "path": path,
        "source_layer_name": source_layer_name,
        "band": band_index,
        "fields": fields,
        "min_zoom": min_zoom,
        "max_zoom": max_zoom,
        "style": style,
        "attribution": layer.attribution() if attribution is None else attribution,
    }


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
            self.configuration = _layer_configuration(
                self.layer,
                self.default_style,
                self.band_index,
                self.name.text(),
                self.attribution.text(),
                [
                    self.fields.item(index).text()
                    for index in range(self.fields.count())
                    if self.fields.item(index).checkState() == QtCore.Qt.Checked
                ],
                self.min_zoom.value(),
                self.max_zoom.value(),
            )
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
        mask=None,
    ):
        super().__init__("Upload and publish web map", QgsTask.CanCancel)
        self.base_url = base_url
        self.token = token
        self.title = title
        self.retention = retention
        self.snapshots = snapshots
        self.share_id = share_id
        self.update_existing = update_existing
        self.mask = mask
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
                try:
                    link = client.link(self.share_id).get("link")
                except (ShareError, AttributeError):
                    link = None
                self.result = {
                    "share": share,
                    "link": link
                    if isinstance(link, str) and link.startswith("https://")
                    else None,
                }
                self.updated = True
                self.published = True
                self.setProgress(100)
                return True
            if self.share_id:
                share = client.status(self.share_id)
            else:
                args = (
                    self.title,
                    self.retention,
                    [snapshot["declaration"] for snapshot in self.snapshots],
                )
                share = client.create(*args, mask=self.mask) if self.mask else client.create(*args)
                self.share_id = share["id"]
                if self.mask and not share.get("has_mask"):
                    raise ShareError("The sharing API did not accept the requested mask")
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
                    "This map is already published; find its link in Shared web maps"
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


_OUTPUT_ROLE = QtCore.Qt.UserRole


class CreateWebmapDialog(QtWidgets.QDialog):
    """Create an empty web map, or add a dataset's outputs to an existing one.

    Passing ``job`` or ``existing_share_id`` only allows adding layers to an
    already published map. New maps are created without layers; their layers
    are added from each dataset's Share button.
    """

    def __init__(
        self,
        parent=None,
        on_published=None,
        job=None,
        existing_share_id=None,
        shares=None,
    ):
        super().__init__(parent)
        self.adding = job is not None or existing_share_id is not None
        self.existing_share_id = existing_share_id
        self.setWindowTitle(
            self.tr("Add to shared web map") if self.adding else self.tr("New web map")
        )
        self.resize(640, 560 if self.adding else 0)
        self.on_published = on_published
        self.api_client = api.APIClient(get_api_url(), TIMEOUT)
        self.directory = tempfile.TemporaryDirectory(prefix="te-webmap-")
        self.entries = []
        self.snapshots = []
        self.mask_geometry = None
        self.task = None
        self.share_id = None
        self._updating = False
        self._confirmed = False
        layout = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()
        self.title = QtWidgets.QLineEdit()
        self.title.setMaxLength(120)
        self.title.setPlaceholderText(self.tr("Shown at the top of the shared map"))
        self.retention = QtWidgets.QComboBox()
        for days in (7, 30, 90):
            self.retention.addItem(self.tr("{days} days").format(days=days), days)
        self.target = QtWidgets.QComboBox()
        if self.adding:
            form.addRow(self.tr("Shared map"), self.target)
        else:
            form.addRow(self.tr("Map title"), self.title)
            form.addRow(self.tr("Keep online for"), self.retention)
        layout.addLayout(form)
        self.mask_selector = MaskSelector()
        self.mask_selector.setVisible(not self.adding)
        self.mask_selector.setToolTip(
            self.tr("The polygon is shared with link holders. This is a display mask, not a data restriction.")
        )
        self.mask_selector.changed.connect(self._invalidate)
        layout.addWidget(self.mask_selector)

        self.no_maps = QtWidgets.QWidget()
        no_maps_layout = QtWidgets.QHBoxLayout(self.no_maps)
        no_maps_layout.setContentsMargins(0, 0, 0, 0)
        no_maps_label = QtWidgets.QLabel(
            self.tr(
                "You don't have a published web map yet. Create one in Shared web "
                "maps, then add outputs to it here."
            )
        )
        no_maps_label.setWordWrap(True)
        open_manager = QtWidgets.QPushButton(self.tr("Open Shared web maps"))
        open_manager.clicked.connect(self._open_manager)
        no_maps_layout.addWidget(no_maps_label, 1)
        no_maps_layout.addWidget(open_manager)
        self.no_maps.hide()
        layout.addWidget(self.no_maps)

        hint = QtWidgets.QLabel(
            self.tr(
                "Check the outputs to include. Double-click a layer name to rename it."
            )
            if self.adding
            else self.tr(
                "The map is created without layers. To add layers, use the Share "
                "button on each dataset in the Datasets tab."
            )
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(1)
        self.tree.setHeaderLabels([self.tr("Layer name")])
        self.tree.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tree.header().setStretchLastSection(True)
        self.tree.setVisible(self.adding)
        layout.addWidget(self.tree, 1)
        if not self.adding:
            layout.addStretch(1)

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(self.status)
        self.progress = QtWidgets.QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        self.share_button = QtWidgets.QPushButton(
            self.tr("Add to map") if self.adding else self.tr("Create map")
        )
        self.share_button.setDefault(True)
        self.cancel_button = QtWidgets.QPushButton(self.tr("Cancel"))
        buttons.addWidget(self.share_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)
        self.share_button.clicked.connect(self._share)
        self.cancel_button.clicked.connect(self._cancel)

        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemDoubleClicked.connect(self._edit_name)
        self.target.currentIndexChanged.connect(self._invalidate)
        self.title.textChanged.connect(self._invalidate)
        self.retention.currentIndexChanged.connect(self._invalidate)
        if job is not None:
            self._add_outputs(self.tree.invisibleRootItem(), job)
        if self.adding:
            if shares is None:
                self.target.addItem(self.tr("Loading shared maps..."))
                self.target.setEnabled(False)
                QtCore.QTimer.singleShot(0, self._load_targets)
            else:
                self._targets_loaded("list", True, shares, None)
        self._update_buttons()

    def _add_outputs(self, parent, job):
        self._updating = True
        try:
            if not job_manager.ensure_results_loaded(job):
                return
            for result in job._get_results_list():
                if (
                    not isinstance(result, (RasterResults, VectorResults))
                    or not result.uri
                    or not Path(str(result.uri.uri)).is_file()
                ):
                    continue
                if isinstance(result, RasterResults):
                    for index, band in enumerate(result.get_bands(), start=1):
                        title = get_band_title(JobBand.Schema().dump(band))
                        self._add_output(parent, title, (result, index))
                else:
                    self._add_output(parent, result.name, (result, None))
        finally:
            self._updating = False

    def _add_output(self, parent, title, output):
        item = QtWidgets.QTreeWidgetItem([title])
        item.setData(0, _OUTPUT_ROLE, output)
        item.setFlags(
            QtCore.Qt.ItemIsEnabled
            | QtCore.Qt.ItemIsUserCheckable
            | QtCore.Qt.ItemIsEditable
            | QtCore.Qt.ItemIsSelectable
        )
        item.setCheckState(0, QtCore.Qt.Unchecked)
        parent.addChild(item)

    def _edit_name(self, item, column):
        if column == 0 and item.data(0, _OUTPUT_ROLE) is not None and not self.task:
            self.tree.editItem(item, 0)

    def _entry(self, item):
        return next((entry for entry in self.entries if entry[0] is item), None)

    def _set_checked(self, item, checked):
        self._updating = True
        item.setCheckState(0, QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked)
        self._updating = False

    def _item_changed(self, item, column):
        if self._updating or item.data(0, _OUTPUT_ROLE) is None:
            return
        self._invalidate()
        if column != 0:
            return
        entry = self._entry(item)
        if item.checkState(0) == QtCore.Qt.Checked and entry is None:
            configuration = self._configure(item)
            if configuration is None:
                self._set_checked(item, False)
                return
            self.entries.append([item, configuration])
            self._updating = True
            item.setText(0, configuration["name"])
            self._updating = False
        elif item.checkState(0) != QtCore.Qt.Checked and entry is not None:
            self.entries.remove(entry)
        self._update_buttons()

    def _configure(self, item):
        result, band_index = item.data(0, _OUTPUT_ROLE)
        names = {entry[0].text(0).strip() for entry in self.entries}
        name = item.text(0).strip()
        if name in names:
            dataset = item.parent().text(0) if item.parent() else ""
            name = f"{name} ({dataset})" if dataset else name
            suffix = 2
            base = name
            while name in names:
                name = f"{base} {suffix}"
                suffix += 1
        try:
            path = str(result.uri.uri)
            if isinstance(result, RasterResults):
                band = result.get_bands()[band_index - 1]
                band_info = JobBand.Schema().dump(band)
                layer = QgsRasterLayer(path, name, "gdal")
            else:
                # Use the same loader as the map so the default style matches.
                layer = open_vector_layer(path, name)
            if layer is None or not layer.isValid():
                raise ShareError("The selected dataset output could not be opened")
            if isinstance(layer, QgsRasterLayer):
                style = _raster_style(path, band_index, band_info)
                return _layer_configuration(layer, style, band_index, name)
            # Vector attributes are embedded in public tiles, so they must be
            # chosen explicitly.
            dialog = _LayerOptions(layer, parent=self)
            return dialog.configuration if dialog.exec() else None
        except ShareError as exc:
            QtWidgets.QMessageBox.warning(self, self.windowTitle(), str(exc))
            return None

    def _invalidate(self, *_args):
        if not self._locked():
            self.snapshots = []
            self.mask_geometry = None
            self._confirmed = False

    def _locked(self):
        # A created draft must be resumed with the same layers.
        return not self.adding and self.share_id is not None

    def _update_buttons(self):
        busy = self.task is not None
        has_target = not self.adding or self.target.currentData() is not None
        self.share_button.setEnabled(
            not busy and (bool(self.entries) or not self.adding) and has_target
        )
        editable = not busy and not self._locked()
        for widget in (self.tree, self.title, self.retention, self.mask_selector):
            widget.setEnabled(editable)
        self.target.setEnabled(
            not busy and self.adding and self.target.currentData() is not None
        )
        self.cancel_button.setText(
            self.tr("Stop")
            if busy
            else self.tr("Close")
            if self.share_id
            else self.tr("Cancel")
        )

    def _load_targets(self):
        base_url = get_api_url()
        self.api_client.url = base_url
        token = self.api_client.login()
        if not token:
            self._targets_loaded(
                "list", False, None, self.tr("Authentication is required.")
            )
            return
        self.task = _OwnerTask(base_url, token, "list", None, self._targets_loaded)
        self._update_buttons()
        QgsApplication.taskManager().addTask(self.task)

    def _targets_loaded(self, _operation, succeeded, shares, error):
        self.task = None
        self.target.clear()
        if not succeeded:
            self.status.setText(
                self.tr("Could not load your shared maps: {error}").format(error=error)
            )
            self._update_buttons()
            return
        for share in shares:
            if can_add_layers(share):
                expires = str(share.get("expires_at") or "")[:10]
                self.target.addItem(
                    self.tr("{title} (expires {date})").format(
                        title=share.get("title", ""), date=expires
                    )
                    if expires
                    else share.get("title", ""),
                    share["id"],
                )
        index = self.target.findData(self.existing_share_id)
        if index >= 0:
            self.target.setCurrentIndex(index)
        self.no_maps.setVisible(self.target.count() == 0)
        self._update_buttons()

    def _open_manager(self):
        parent = self.parentWidget()
        self.reject()
        WebmapSharesDialog(parent).exec()

    def _selected_configurations(self):
        if not self.adding:
            if not self.title.text().strip():
                raise ShareError(self.tr("Enter a map title."))
            return []
        configurations = []
        for item, configuration in self.entries:
            configuration["name"] = item.text(0).strip()
            configurations.append(configuration)
        names = [configuration["name"] for configuration in configurations]
        if not names:
            raise ShareError(self.tr("Check at least one output to share."))
        if len(names) > 10:
            raise ShareError(self.tr("A web map can include at most 10 layers."))
        if any(not name or len(name) > 120 for name in names) or len(set(names)) != len(
            names
        ):
            raise ShareError(
                self.tr("Each layer needs a unique name of up to 120 characters.")
            )
        if self.target.currentData() is None:
            raise ShareError(self.tr("Choose a shared map."))
        return configurations

    def _share(self):
        if self.task:
            return
        try:
            configurations = self._selected_configurations()
            if not self.adding and not self._locked() and not self.snapshots:
                self.mask_geometry = self.mask_selector.geometry()
        except ShareError as exc:
            QtWidgets.QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        if not (self.snapshots and self._confirmed):
            if not confirm_public_sharing(
                self,
                [configuration["name"] for configuration in configurations],
                self.target.currentText() if self.adding else None,
            ):
                return
            self._confirmed = True
        if self.snapshots or not self.adding:
            self._publish()
            return
        self.directory.cleanup()
        self.directory = tempfile.TemporaryDirectory(prefix="te-webmap-")
        self.status.setText(self.tr("Preparing layers..."))
        self.task = _PrepareTask(configurations, self.directory.name, self._prepared)
        self.task.progressChanged.connect(
            lambda value: self.progress.setValue(int(value))
        )
        self.progress.setValue(0)
        self.progress.show()
        self._update_buttons()
        QgsApplication.taskManager().addTask(self.task)

    def _prepared(self, succeeded, snapshots, error):
        self.task = None
        self.snapshots = snapshots if succeeded else []
        self._update_buttons()
        if not succeeded:
            self.progress.hide()
            self.status.setText(
                self.tr("Could not prepare the layers: {error}").format(
                    error=error or self.tr("Cancelled")
                )
            )
            return
        self._publish()

    def _publish(self):
        base_url = get_api_url()
        self.api_client.url = base_url
        token = self.api_client.login()
        if not token:
            self.progress.hide()
            self.status.setText(self.tr("Authentication is required."))
            return
        self.status.setText(
            self.tr("Uploading and checking layers. This may take several minutes.")
            if self.adding
            else self.tr("Creating the web map...")
        )
        target = self.target.currentData() if self.adding else self.share_id
        self.task = _PublishTask(
            base_url,
            token,
            self.title.text().strip(),
            self.retention.currentData(),
            self.snapshots,
            target,
            self._published,
            update_existing=self.adding,
            mask=self.mask_geometry,
        )
        self.task.progressChanged.connect(
            lambda value: self.progress.setValue(int(value))
        )
        self.progress.show()
        self._update_buttons()
        QgsApplication.taskManager().addTask(self.task)

    def _published(self, succeeded, result, share_id, error):
        self.task = None
        if not self.adding:
            self.share_id = share_id
        self.progress.hide()
        self._update_buttons()
        if not succeeded:
            retry = self.tr("Select {button} to try again.").format(
                button=self.share_button.text()
            )
            if error and error.startswith("Server validation failed:"):
                self.status.setText(
                    self.tr("{error}. Published layers are unchanged. {retry}").format(
                        error=error, retry=retry
                    )
                )
                return
            self.status.setText(
                self.tr("Sharing failed: {error}. {retry}").format(
                    error=error or self.tr("Cancelled"), retry=retry
                )
            )
            return
        self.directory.cleanup()
        self.accept()
        parent = self.parentWidget()
        if self.adding:
            count = len(self.snapshots)
            message = self.tr(
                "Added {count} layer(s) to “{title}”. Anyone with the link will see "
                "them the next time they open the map."
            ).format(count=count, title=result["share"].get("title", ""))
            if result.get("link") and result["share"].get("expires_at"):
                show_link(parent, result, message)
            else:
                QtWidgets.QMessageBox.information(
                    parent, self.tr("Shared web map"), message
                )
        elif self.on_published:
            self.on_published(result)
        else:
            show_link(parent, result)

    def _cancel(self):
        if self.task:
            self.task.cancel()
        else:
            self.reject()

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
