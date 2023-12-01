import enum
import math

from qgis.core import Qgis
from qgis.core import QgsAbstractGeometry
from qgis.core import QgsFeature
from qgis.core import QgsGeometry
from qgis.core import QgsPointXY
from qgis.core import QgsProject
from qgis.core import QgsRasterLayer
from qgis.core import QgsRectangle
from qgis.core import QgsUnitTypes
from qgis.core import QgsVectorLayerUtils
from qgis.core import QgsWkbTypes
from qgis.gui import QgsDoubleSpinBox
from qgis.gui import QgsMapCanvas
from qgis.gui import QgsMapMouseEvent
from qgis.gui import QgsMapToolAdvancedDigitizing
from qgis.gui import QgsMapToolCapture
from qgis.gui import QgsMapToolDigitizeFeature
from qgis.gui import QgsVertexMarker
from qgis.PyQt import QtCore
from qgis.PyQt import QtGui
from qgis.PyQt import QtWidgets
from qgis.utils import iface

from .areaofinterest import prepare_area_of_interest
from .jobs.manager import job_manager


class BufferMode(enum.IntEnum):
    AREA = 1
    RADIUS = 2


class AreaWidget(QtWidgets.QWidget):
    layout: QtWidgets.QHBoxLayout
    label: QtWidgets.QLabel
    line_edit: QtWidgets.QLineEdit

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QtWidgets.QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.label = QtWidgets.QLabel(self.tr("Area"))
        self.layout.addWidget(self.label)

        self.line_edit = QtWidgets.QLineEdit(self)
        self.line_edit.setReadOnly(True)
        self.line_edit.setText(self.tr("0.00 km\u00B2"))
        self.line_edit.setSizePolicy(
            QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.Preferred
        )
        self.layout.addWidget(self.line_edit)

    def set_area(self, area):
        self.line_edit.setText(self.tr("{:.6g} km\u00B2".format(area)))


class BufferWidget(QtWidgets.QWidget):
    layout: QtWidgets.QHBoxLayout
    spin_radius: QgsDoubleSpinBox
    combo_mode: QtWidgets.QComboBox
    radius_editing_canceled: QtCore.pyqtSignal = QtCore.pyqtSignal()
    radius_editing_finished: QtCore.pyqtSignal = QtCore.pyqtSignal(float)
    radius_changed: QtCore.pyqtSignal = QtCore.pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QtWidgets.QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.spin_radius = QgsDoubleSpinBox(self)
        self.spin_radius.setMinimum(0)
        self.spin_radius.setSuffix(self.tr(" km"))
        self.spin_radius.setSingleStep(1)
        self.spin_radius.setValue(0)
        self.spin_radius.setClearValue(0)
        self.spin_radius.setSizePolicy(
            QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.Preferred
        )
        self.layout.addWidget(self.spin_radius)

        self.combo_mode = QtWidgets.QComboBox()
        self.combo_mode.addItem(self.tr("Radius"), BufferMode.RADIUS)
        self.combo_mode.addItem(self.tr("Area"), BufferMode.AREA)
        self.layout.addWidget(self.combo_mode)

        self.combo_mode.currentIndexChanged.connect(self.change_mode)
        self.spin_radius.installEventFilter(self)
        self.spin_radius.valueChanged.connect(self.radius_updated)

        self.setFocusProxy(self.spin_radius)

    def editor(self):
        return self.spin_radius

    def change_mode(self, index):
        if index == BufferMode.AREA:
            self.spin_radius.setSuffix(self.tr(" km\u00B2"))
        elif index == BufferMode.RADIUS:
            self.spin_radius.setSuffix(self.tr(" km"))

        self.setFocus(QtCore.Qt.TabFocusReason)
        self.spin_radius.selectAll()
        self.radius_updated(self.spin_radius.value())

    def set_radius(self, radius):
        if self.combo_mode.currentData() == BufferMode.RADIUS:
            self.spin_radius.setValue(radius)
        else:
            self.spin_radius.setValue(math.pi * radius * radius)

    def radius(self):
        if self.combo_mode.currentData() == BufferMode.RADIUS:
            return self.spin_radius.value()
        else:
            return math.sqrt(self.spin_radius.value() / math.pi)

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent):
        if obj == self.spin_radius and event.type() == QtCore.QEvent.KeyPress:
            if event.key() == QtCore.Qt.Key_Escape:
                self.radius_editing_canceled.emit()
                return True
            if (
                event.key() == QtCore.Qt.Key_Enter
                or event.key() == QtCore.Qt.Key_Return
            ):
                self.radius_editing_finished.emit(self.radius())
                return True
        return False

    def radius_updated(self, value: float):
        if self.combo_mode.currentData() == BufferMode.RADIUS:
            self.radius_changed.emit(value)
        else:
            self.radius_changed.emit(math.sqrt(value / math.pi))


class GeomOpResult(enum.Enum):
    """
    Success result from a geometry operation.
    """

    TRUE = 0
    FALSE = 1
    UNKNOWN = -1


class TEMapToolMixin:
    """
    Provides base functionality for preventing polygon overlaps and
    raises warnings when digitization occurs outside the extents of
    the base raster layer.
    """

    def __init__(self, *args, **kwargs):
        self._intersection_mode = None
        self._geom_engine = None

    def _prepare_base_reference_extent(self):
        """
        Create geometry engine for the extent of the base layer for
        subsequent operations for checking if digitized polygons
        intersect with the base layer.
        """
        if self._geom_engine is None:
            geom = prepare_area_of_interest().get_unary_geometry()
            if geom is None or not geom.isGeosValid():
                return

            self._geom_engine = QgsGeometry.createGeometryEngine(geom.constGet())
            self._geom_engine.prepareGeometry()

    def intersects_with_base_extents(self, geom: QgsGeometry) -> GeomOpResult:
        """
        Assert if 'geom' is fully within the base layer extents. If the
        base layer extent could not be determined due to different reasons
        then this function will always return 'UNKNOWN'.
        """
        if self._geom_engine is None:
            return GeomOpResult.UNKNOWN

        if self._geom_engine.intersects(geom.constGet()):
            return GeomOpResult.TRUE

        return GeomOpResult.FALSE

    def intersection_with_base_extents(self, geom: QgsGeometry) -> QgsAbstractGeometry:
        """
        Returns intersection of geom and base extent. If the base layer extent
        could not be determined then this will return the unmodified geom.
        """
        if self._geom_engine is None:
            return geom.get()
        else:
            # Disable below until crash is resolved
            # g = QgsGeometry(self._geom_engine.intersection(geom.constGet()))
            # g.convertGeometryCollectionToSubclass(QgsWkbTypes.PolygonGeometry)
            g = self._geom_engine.intersection(geom.constGet())
            if g.geometryType() == "Polygon":
                return g
            elif g.geometryType() == "GeometryCollection":
                # When a new polygon partially overlaps the boundary of the
                # region and also an existing polygon the user has drawn, then
                # the intersection can include Linestrings - these need to be
                # removed before the geometry is saved
                n = 0
                while n < g.childCount():
                    child = g.childGeometry(n)
                    if child.geometryType() not in ["Polygon", "MultiPolygon"]:
                        g.removeGeometry(n)
                        # Continue loop with same value of n as removal of this
                        # geometry means another geometry has taken its place
                        # in the same index position
                        continue
                    n += 1
                return g
            else:
                return QgsGeometry().get()

    def _set_intersection_mode(self, avoid_overlaps: bool):
        # Activate/de-activate intersection mode
        project = QgsProject.instance()
        if self._intersection_mode is None:
            self._intersection_mode = project.avoidIntersectionsMode()

        if avoid_overlaps:
            project.setAvoidIntersectionsMode(
                Qgis.AvoidIntersectionsMode.AvoidIntersectionsLayers
            )
            project.setAvoidIntersectionsLayers([self.currentVectorLayer()])
        else:
            # Restore original mode
            if self._intersection_mode is not None:
                project.setAvoidIntersectionsMode(self._intersection_mode)

    def job_from_current_layer(self) -> "Job":
        """
        Returns the 'Job' object corresponding to the current vector layer
        being digitized.
        """
        layer = self.currentVectorLayer()
        if layer is None:
            return None

        job_id = layer.customProperty("job_id", None)
        if job_id is None:
            return None

        return job_manager.get_vector_result_job_by_id(job_id)

    def notify_outside_extent(self):
        """
        Send a warning message that the digitizing is outside the base
        layer extent.
        """
        msg_bar = iface.messageBar()
        msg_bar.pushMessage(
            self.tr("Warning"),
            self.tr(
                "Current cursor position is outside the extent of the base "
                "source dataset."
            ),
            Qgis.MessageLevel.Warning,
            2,
        )

    def base_layer_extents(self) -> QgsRectangle:
        """
        Returns the extents for the base raster layer defined in
        the job's 'params' attribute.
        """
        job = self.job_from_current_layer()
        if job is None:
            return None

        if len(job.params) == 0:
            return None

        related_job = list(job.params.values())[0]
        path = related_job.get("path", None)
        if path is None:
            return None

        base_layer = QgsRasterLayer(path)
        if not base_layer.isValid():
            return None

        return base_layer.extent()

    def warn_if_extents_outside(self, p: QgsPointXY):
        """
        Check if the point is within the extent of base layer and
        warn accordingly.
        """
        iface.messageBar().clearWidgets()
        p_geom = QgsGeometry.fromPointXY(p)
        intersects = self.intersects_with_base_extents(p_geom)
        if intersects == GeomOpResult.UNKNOWN:
            return
        elif intersects == GeomOpResult.FALSE:
            self.notify_outside_extent()


class PolygonMapTool(QgsMapToolDigitizeFeature, TEMapToolMixin):
    def __init__(self, canvas: QgsMapCanvas):
        super().__init__(
            canvas, iface.cadDockWidget(), QgsMapToolCapture.CapturePolygon
        )

        self.canvas = canvas
        self.widget = None
        self.active = False

        self.digitizingCompleted.connect(self.digitized)

    def create_widget(self):
        if self.canvas is None:
            return
        self.delete_widget()

        # self.widget = AreaWidget()
        # iface.addUserInputWidget(self.widget)

    def delete_widget(self):
        if self.widget:
            self.widget.deleteLater()

        self.widget = None

    def deactivate(self):
        self.delete_widget()
        self._set_intersection_mode(False)
        self._geom_engine = None
        super().deactivate()

    def cadCanvasReleaseEvent(self, e: QgsMapMouseEvent):
        if self.canvas is None:
            return

        layer = self.currentVectorLayer()
        if layer is None:
            self.delete_widget()
            self.notifyNotVectorLayer()
            self.cadDockWidget().clear()
            return

        if not self.active:
            self.create_widget()
            self.active = True
            self._set_intersection_mode(True)
            self._prepare_base_reference_extent()
            if e.button() == QtCore.Qt.LeftButton:
                self.warn_if_extents_outside(e.mapPoint())

        elif self.active and e.button() == QtCore.Qt.RightButton:
            self.active = False

        super().cadCanvasReleaseEvent(e)

    def cadCanvasMoveEvent(self, e: QgsMapMouseEvent):
        super().cadCanvasMoveEvent(e)

        # Check if the cursor is within the extents of the base raster layer
        if self.active:
            self.warn_if_extents_outside(e.mapPoint())

        # Disable until crash is resolved
        # if self.active:
        #     curve = self.captureCurve().clone()
        #     curve.addVertex(QgsPoint(e.mapPoint()))
        #     curve.close()
        #     ring = curve.curveToLine()
        #     poly = QgsPolygon()
        #     poly.setExteriorRing(ring)
        #     g = QgsGeometry(poly)
        #     crs = self.currentVectorLayer().crs()
        #     f = QgsUnitTypes.fromUnitToUnitFactor(QgsUnitTypes.distanceToAreaUnit(crs.mapUnits()), QgsUnitTypes.AreaSquareKilometers)
        #     self.widget.set_area(g.area() * f)

    def digitized(self, f: QgsFeature):
        self.active = False

        layer = self.currentVectorLayer()
        if layer is None:
            self.delete_rubberband()
            self.notifyNotVectorLayer()
            self.cadDockWidget().clear()
            return

        g = f.geometry()

        g.set(self.intersection_with_base_extents(g))
        if g.isEmpty() or g.area() == 0:
            msg_bar = iface.messageBar()
            msg_bar.pushMessage(
                self.tr("Error"),
                self.tr(
                    "Empty geometry. Did you draw a feature outside of "
                    "the currently selected region, or overlapping existing "
                    "features?"
                ),
                Qgis.MessageLevel.Critical,
                5,
            )
            return

        layer.beginEditCommand(self.tr("add feature"))
        fields = layer.fields()
        attrs = {fields.lookupField("source"): "manual digitizing"}
        f = QgsVectorLayerUtils.createFeature(
            layer, g, attrs, layer.createExpressionContext()
        )

        if iface.openFeatureForm(layer, f):
            layer.addFeature(f)

        self.delete_widget()
        self.cadDockWidget().clear()

        layer.endEditCommand()
        layer.triggerRepaint()


class BufferMapTool(QgsMapToolAdvancedDigitizing):
    def __init__(self, canvas: QgsMapCanvas):
        super().__init__(canvas, iface.cadDockWidget())

        self.canvas = canvas
        self.center_point = None
        self.start_point = None
        self.widget = None
        self.rubberband = None

        self.active = False
        self.radius = 0

    def create_widget(self):
        if self.canvas is None:
            return
        self.delete_widget()

        self.widget = BufferWidget()
        iface.addUserInputWidget(self.widget)
        self.widget.setFocus(QtCore.Qt.TabFocusReason)

        self.widget.radius_changed.connect(self.update_rubberband)
        self.widget.radius_editing_finished.connect(self.apply_buffer_w)
        self.widget.radius_editing_canceled.connect(self.cancel)

    def delete_widget(self):
        if self.widget:
            self.widget.radius_changed.disconnect(self.update_rubberband)
            self.widget.radius_editing_finished.disconnect(self.apply_buffer_w)
            self.widget.radius_editing_canceled.disconnect(self.cancel)

            self.widget.releaseKeyboard()
            self.widget.deleteLater()

        self.widget = None

    def delete_rubberband(self):
        del self.rubberband
        self.rubberband = None

    def activate(self):
        layer = self.currentVectorLayer()
        if layer is None:
            return

        if not layer.isEditable():
            return

        super().activate()

    def deactivate(self):
        self.delete_widget()
        self.active = False
        if self.center_point is not None:
            self.canvas.scene().removeItem(self.center_point)
            self.center_point = None
        self.delete_rubberband()
        super().deactivate()

    def cancel(self):
        self.delete_widget()
        self.delete_rubberband()
        if self.center_point is not None:
            self.canvas.scene().removeItem(self.center_point)
            self.center_point = None
        self.active = False
        self.cadDockWidget().clear()

    def update_rubberband(self, radius):
        layer = self.currentVectorLayer()
        f = QgsUnitTypes.fromUnitToUnitFactor(
            QgsUnitTypes.DistanceKilometers, layer.crs().mapUnits()
        )
        if self.active:
            self.radius = radius * f
            if self.rubberband:
                g = QgsGeometry.fromPointXY(self.start_point).buffer(self.radius, 10)
                self.rubberband.setToGeometry(g, layer)
                self.rubberband.update()

    def keyReleaseEvent(self, e: QtGui.QKeyEvent):
        if self.active and e.key() == QtCore.Qt.Key_Escape:
            self.cancel()
            return
        super().keyReleaseEvent(e)

    def cadCanvasMoveEvent(self, e: QgsMapMouseEvent):
        if self.active:
            p = e.mapPoint()
            layer = self.currentVectorLayer()
            f = QgsUnitTypes.fromUnitToUnitFactor(
                layer.crs().mapUnits(), QgsUnitTypes.DistanceKilometers
            )
            radius = self.distance(self.start_point, p) * f

            if self.widget is not None:
                self.widget.radius_changed.disconnect(self.update_rubberband)
                self.widget.set_radius(radius)
                self.widget.setFocus(QtCore.Qt.TabFocusReason)
                self.widget.editor().selectAll()
                self.widget.radius_changed.connect(self.update_rubberband)

            self.update_rubberband(radius)

    def cadCanvasReleaseEvent(self, e: QgsMapMouseEvent):
        if self.canvas is None:
            return

        layer = self.currentVectorLayer()
        if layer is None:
            self.delete_widget()
            self.delete_rubberband()
            self.notifyNotVectorLayer()
            self.cadDockWidget().clear()
            return

        if e.button() == QtCore.Qt.RightButton:
            self.cancel()
            return

        if e.modifiers() & QtCore.Qt.ControlModifier:
            if self.center_point is None:
                self.center_point = QgsVertexMarker(self.canvas)
                self.center_point.setIconType(QgsVertexMarker.ICON_CROSS)

            self.center_point.setCenter(e.mapPoint())
            self.start_point = e.mapPoint()
            self.cadDockWidget().clear()
            return

        self.delete_widget()

        if not self.active:
            self.radius = 0
            self.delete_rubberband()

            pos = e.mapPoint()
            if not layer.isEditable():
                self.notifyNotEditableLayer()
                return

            if self.center_point is None:
                self.center_point = QgsVertexMarker(self.canvas)
                self.center_point.setIconType(QgsVertexMarker.ICON_CROSS)
                self.center_point.setCenter(e.mapPoint())
                self.start_point = e.mapPoint()

            self.rubberband = self.createRubberBand(layer.geometryType())
            self.radius = self.distance(self.start_point, pos)
            g = QgsGeometry.fromPointXY(self.start_point).buffer(self.radius, 10)
            self.rubberband.setToGeometry(g, layer)
            self.rubberband.show()

            self.create_widget()
            self.active = True
            return

        self.apply_buffer(self.radius)

    def apply_buffer_w(self, radius):
        self.apply_buffer(radius, True)

    def apply_buffer(self, radius, convert=False):
        self.radius = radius
        self.active = False

        layer = self.currentVectorLayer()
        if layer is None:
            self.delete_rubberband()
            self.notifyNotVectorLayer()
            self.cadDockWidget().clear()
            return

        layer.beginEditCommand(self.tr("add feature"))
        g = None
        if convert:
            f = QgsUnitTypes.fromUnitToUnitFactor(
                QgsUnitTypes.DistanceKilometers, layer.crs().mapUnits()
            )
            g = QgsGeometry.fromPointXY(self.start_point).buffer(self.radius * f, 10)
        else:
            g = QgsGeometry.fromPointXY(self.start_point).buffer(self.radius, 10)
        fields = layer.fields()
        attrs = {fields.lookupField("source"): "buffer tool"}
        f = QgsVectorLayerUtils.createFeature(
            layer, g, attrs, layer.createExpressionContext()
        )
        if iface.openFeatureForm(layer, f):
            layer.addFeature(f)

        self.delete_widget()
        self.delete_rubberband()
        self.cadDockWidget().clear()

        if self.center_point is not None:
            self.canvas.scene().removeItem(self.center_point)
            self.center_point = None

        layer.endEditCommand()
        layer.triggerRepaint()

    def distance(self, p1, p2):
        return math.sqrt(
            (p1.x() - p2.x()) * (p1.x() - p2.x())
            + (p1.y() - p2.y()) * (p1.y() - p2.y())
        )
