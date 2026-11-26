"""Region selection and geometry preparation for web-map display masks."""

import json

from qgis.core import QgsWkbTypes
from qgis.PyQt import QtCore, QtWidgets

from . import areaofinterest, conf
from .webmap_sharing import ShareError


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
        notice = QtWidgets.QLabel(
            self.tr(
                "The polygon is visible to link holders. Masking only changes "
                "the display; it does not restrict access to the layer data."
            )
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
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
            mask = json.loads(geometry.asJson())
            size = len(json.dumps(mask, separators=(",", ":")).encode())
            if size > 512 * 1024 or sum(1 for _ in geometry.vertices()) > 30000:
                raise ShareError(
                    self.tr(
                        "The mask is too detailed to share (maximum 512 KB and "
                        "30,000 coordinates). Choose a simpler polygon."
                    )
                )
            return mask
        except (RuntimeError, ValueError, TypeError) as exc:
            raise ShareError(
                self.tr("Could not prepare the mask: {error}").format(error=str(exc))
            ) from exc
