"""Region selection and geometry preparation for web-map display masks."""

import json

from qgis.core import QgsGeometry, QgsWkbTypes
from qgis.PyQt import QtCore, QtWidgets

from . import areaofinterest, conf
from .webmap_sharing import ShareError

MAX_MASK_BYTES = 512 * 1024
MAX_MASK_COORDINATES = 30000
# Simplified masks stay below the API limits because the server may add
# vertices when it splits polygons at the antimeridian.
_SIMPLIFIED_LIMIT_FACTOR = 0.95


def _mask_size(geometry, precision=17):
    mask = json.loads(geometry.asJson(precision))
    return mask, len(json.dumps(mask, separators=(",", ":")).encode())


def _within_limits(geometry, precision=17, factor=1):
    mask, size = _mask_size(geometry, precision)
    vertices = sum(1 for _ in geometry.vertices())
    fits = size <= MAX_MASK_BYTES * factor and vertices <= MAX_MASK_COORDINATES * factor
    return mask if fits else None


def _polygonal(geometry):
    if geometry.isNull() or geometry.isEmpty():
        return None
    if not geometry.isGeosValid():
        geometry = geometry.makeValid()
    if QgsWkbTypes.geometryType(geometry.wkbType()) != QgsWkbTypes.PolygonGeometry:
        parts = [
            part
            for part in geometry.asGeometryCollection()
            if QgsWkbTypes.geometryType(part.wkbType()) == QgsWkbTypes.PolygonGeometry
        ]
        if not parts:
            return None
        geometry = QgsGeometry.unaryUnion(parts)
    if geometry.isEmpty() or not geometry.isGeosValid() or geometry.area() <= 0:
        return None
    return geometry


def simplify_mask(geometry):
    """Return the least simplified GeoJSON polygon that fits the sharing limits.

    Coordinates are first rounded to about 10 cm, then the tolerance is doubled
    until both the size and coordinate limits are met.
    """
    box = geometry.boundingBox()
    tolerance = max(box.width(), box.height()) * 1e-6
    candidate = _polygonal(geometry.snappedToGrid(1e-6, 1e-6))
    for _ in range(40):
        if candidate is not None:
            mask = _within_limits(candidate, 6, _SIMPLIFIED_LIMIT_FACTOR)
            if mask is not None:
                return mask
        candidate = _polygonal(geometry.simplify(tolerance).snappedToGrid(1e-6, 1e-6))
        tolerance *= 2
    return None


class MaskSelector(QtWidgets.QGroupBox):
    changed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle(self.tr("Mask shared layers to a region"))
        self.setCheckable(True)
        self.setChecked(False)
        layout = QtWidgets.QVBoxLayout(self)
        region = QtWidgets.QHBoxLayout()
        self.label = QtWidgets.QLabel()
        self.label.setWordWrap(True)
        self.button = QtWidgets.QPushButton(self.tr("Change region"))
        self.button.clicked.connect(self._change_region)
        region.addWidget(self.label, 1)
        region.addWidget(self.button)
        layout.addLayout(region)
        self.simplify = QtWidgets.QCheckBox(
            self.tr("Simplify the polygon automatically if it is too detailed")
        )
        self.simplify.setChecked(True)
        self.simplify.toggled.connect(self.changed)
        layout.addWidget(self.simplify)
        self.toggled.connect(self.changed)
        self._refresh()

    def _refresh(self):
        name = conf.settings_manager.get_value(conf.Setting.AREA_NAME)
        self.label.setText(
            self.tr("Current region: {name}").format(
                name=name or self.tr("Not selected")
            )
        )

    def _change_region(self):
        areaofinterest.open_settings()
        self._refresh()
        self.changed.emit()

    def geometry(self):
        if not self.isChecked():
            return None
        method = conf.settings_manager.get_value(conf.Setting.AREA_FROM_OPTION)
        if method not in (
            conf.AreaSetting.COUNTRY_REGION.value,
            conf.AreaSetting.VECTOR_LAYER.value,
        ):
            raise ShareError(
                self.tr(
                    "Select an administrative region or polygon in region settings."
                )
            )
        try:
            aoi = areaofinterest.prepare_area_of_interest(show_errors=False)
            if aoi is None or aoi.datatype != "polygon":
                raise ShareError(self.tr("The selected region is not a valid polygon."))
            geometry = aoi.get_unary_geometry()
            if (
                geometry is None
                or geometry.isEmpty()
                or not geometry.isGeosValid()
                or QgsWkbTypes.geometryType(geometry.wkbType())
                != QgsWkbTypes.PolygonGeometry
            ):
                raise ShareError(self.tr("The selected region is not a valid polygon."))
            geometry.get().dropZValue()
            geometry.get().dropMValue()
            mask = _within_limits(geometry)
            if mask is not None:
                return mask
            if self.simplify.isChecked():
                mask = simplify_mask(geometry)
                if mask is not None:
                    return mask
                raise ShareError(
                    self.tr(
                        "The mask could not be simplified to fit the sharing limits "
                        "(512 KB and 30,000 coordinates). Choose a simpler polygon."
                    )
                )
            raise ShareError(
                self.tr(
                    "The mask is too detailed to share (maximum 512 KB and "
                    "30,000 coordinates). Enable automatic simplification or "
                    "choose a simpler polygon."
                )
            )
        except (RuntimeError, ValueError, TypeError) as exc:
            raise ShareError(
                self.tr("Could not prepare the mask: {error}").format(error=str(exc))
            ) from exc
