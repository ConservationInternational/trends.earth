import enum
import math

from qgis.core import QgsFeature
from qgis.core import QgsGeometry
from qgis.core import QgsUnitTypes
from qgis.core import QgsVectorLayerUtils
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
        self.line_edit.setText(self.tr("0.00 km²"))
        self.line_edit.setSizePolicy(
            QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.Preferred
        )
        self.layout.addWidget(self.line_edit)

    def set_area(self, area):
        self.line_edit.setText(self.tr("{:.6g} km²".format(area)))


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
            self.spin_radius.setSuffix(self.tr(" km²"))
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


class PolygonMapTool(QgsMapToolDigitizeFeature):
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

        super().cadCanvasReleaseEvent(e)

    def cadCanvasMoveEvent(self, e: QgsMapMouseEvent):
        super().cadCanvasMoveEvent(e)

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

        layer.beginEditCommand(self.tr("add feature"))
        g = f.geometry()
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
