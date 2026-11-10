"""
Per-unit settings for the indicator dialogs when subnational units are defined.

The indicator dialogs keep a single set of input widgets. A ``SubnationalUnitBar``
sits above them with one tab per unit: the widgets always show the tab that is
selected, and the values of the other units are remembered. On submit, each
unit's values are applied to the widgets in turn to build that unit's payload.
"""

import contextlib
import json
import typing

from qgis.PyQt import QtCore, QtWidgets

from . import areaofinterest, conf
from .logger import log


def get_subnational_units() -> list[dict]:
    """Return the saved subnational units, or [] when the mode is off."""
    if not conf.settings_manager.get_value(conf.Setting.SUBNATIONAL_ENABLED):
        return []
    try:
        return json.loads(
            conf.settings_manager.get_value(conf.Setting.SUBNATIONAL_UNITS) or "[]"
        )
    except (TypeError, ValueError):
        return []


def capture_widget_state(widget: QtWidgets.QWidget):
    """Return the user-editable value of an input widget."""
    if isinstance(widget, QtWidgets.QComboBox):
        return widget.currentText()
    if isinstance(widget, QtWidgets.QAbstractButton):
        return widget.isChecked()
    if isinstance(widget, QtWidgets.QGroupBox):
        return widget.isChecked() if widget.isCheckable() else None
    if isinstance(widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
        return widget.value()
    if isinstance(widget, QtWidgets.QDateTimeEdit):
        return widget.date().toString(QtCore.Qt.ISODate)
    if isinstance(widget, QtWidgets.QLineEdit):
        return widget.text()
    return None


def apply_widget_state(widget: QtWidgets.QWidget, state) -> None:
    """Set an input widget to a value returned by ``capture_widget_state``."""
    if state is None:
        return
    if isinstance(widget, QtWidgets.QComboBox):
        index = widget.findText(state)
        if index >= 0 and index != widget.currentIndex():
            widget.setCurrentIndex(index)
    elif isinstance(widget, QtWidgets.QAbstractButton):
        widget.setChecked(state)
    elif isinstance(widget, QtWidgets.QGroupBox):
        if widget.isCheckable():
            widget.setChecked(state)
    elif isinstance(widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
        widget.setValue(state)
    elif isinstance(widget, QtWidgets.QDateTimeEdit):
        widget.setDate(QtCore.QDate.fromString(state, QtCore.Qt.ISODate))
    elif isinstance(widget, QtWidgets.QLineEdit):
        widget.setText(state)


class SubnationalUnitBar(QtWidgets.QWidget):
    """
    One tab per subnational unit, plus a button to copy the current unit's
    settings to all of the others.
    """

    unit_changed = QtCore.pyqtSignal(str)
    copied = QtCore.pyqtSignal(str)

    def __init__(
        self,
        widgets: typing.Sequence[QtWidgets.QWidget],
        parent=None,
        on_unit_shown: typing.Callable[[dict], None] | None = None,
    ):
        super().__init__(parent)
        self._widgets = list(widgets)
        self._on_unit_shown = on_unit_shown
        self._units: list[dict] = []
        self._states: dict[str, list] = {}
        self._current_id: str | None = None
        self._loading = False

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._label = QtWidgets.QLabel(
            self.tr("Settings below apply to the selected subnational unit:")
        )
        layout.addWidget(self._label)

        row = QtWidgets.QHBoxLayout()
        self._tabs = QtWidgets.QTabBar()
        self._tabs.setExpanding(False)
        self._tabs.setUsesScrollButtons(True)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        row.addWidget(self._tabs, 1)

        self._copy_btn = QtWidgets.QPushButton(self.tr("Copy to all units"))
        self._copy_btn.setToolTip(
            self.tr("Apply the settings of the selected unit to every other unit")
        )
        self._copy_btn.clicked.connect(self.copy_to_all)
        row.addWidget(self._copy_btn)
        layout.addLayout(row)

        self.setVisible(False)

    @property
    def units(self) -> list[dict]:
        return list(self._units)

    @property
    def current_unit_id(self) -> str | None:
        return self._current_id

    def _capture(self) -> list:
        return [capture_widget_state(w) for w in self._widgets]

    def _apply(self, state: list) -> None:
        for widget, value in zip(self._widgets, state):
            apply_widget_state(widget, value)

    def _show_unit(self, unit_id: str) -> None:
        """Put ``unit_id``'s saved values into the widgets."""
        if self._on_unit_shown is not None:
            unit = next((u for u in self._units if u.get("id") == unit_id), None)
            if unit is not None:
                self._on_unit_shown(unit)
        self._apply(self._states[unit_id])

    def set_units(self, units: list[dict]) -> None:
        """
        Show tabs for ``units``. Units already known keep their settings; new
        ones start from what the widgets currently show.
        """
        if self._current_id is not None:
            self._states[self._current_id] = self._capture()

        ids = [u.get("id") for u in units]
        if ids == [u.get("id") for u in self._units] and [
            u.get("name") for u in units
        ] == [u.get("name") for u in self._units]:
            # Same units: just refresh what depends on the shown unit
            if self._current_id is not None:
                self._show_unit(self._current_id)
            return

        defaults = self._capture()
        self._states = {
            unit_id: state for unit_id, state in self._states.items() if unit_id in ids
        }
        for unit_id in ids:
            self._states.setdefault(unit_id, list(defaults))
        self._units = list(units)

        self._loading = True
        try:
            while self._tabs.count():
                self._tabs.removeTab(0)
            for unit in units:
                self._tabs.addTab(unit.get("name") or self.tr("Unit"))
            keep = self._current_id if self._current_id in ids else None
            self._current_id = keep or (ids[0] if ids else None)
            if self._current_id is not None:
                self._tabs.setCurrentIndex(ids.index(self._current_id))
                self._show_unit(self._current_id)
        finally:
            self._loading = False

        self.setVisible(bool(units))
        if self._current_id is not None:
            self.unit_changed.emit(self._current_id)

    def _on_tab_changed(self, index: int) -> None:
        if self._loading or index < 0 or index >= len(self._units):
            return
        if self._current_id is not None:
            self._states[self._current_id] = self._capture()
        self._current_id = self._units[index].get("id")
        self._show_unit(self._current_id)
        self.unit_changed.emit(self._current_id)

    def copy_to_all(self) -> None:
        if self._current_id is None:
            return
        state = self._capture()
        self._states = {unit_id: list(state) for unit_id in self._states}
        self.copied.emit(self._current_id)

    @contextlib.contextmanager
    def unit_applied(self, unit_id: str):
        """Show ``unit_id``'s settings in the widgets while the block runs."""
        if self._current_id is not None:
            self._states[self._current_id] = self._capture()
        previous = self._current_id
        self._show_unit(unit_id)
        try:
            yield
        finally:
            if previous is not None:
                self._show_unit(previous)


def unit_tag(unit: dict, run_id: str) -> dict:
    """The ``subnational_unit`` job parameter that ties a result to its unit."""
    return {
        "id": unit.get("id"),
        "name": unit.get("name", "unit"),
        "geometry_hash": unit.get("geometry_hash"),
        "run_id": run_id,
    }


def unit_task_name(unit: dict, base_name: str) -> str:
    unit_name = unit.get("name", "unit")
    if not base_name:
        return unit_name
    # The name may already say which unit it is for (e.g. typed per unit)
    if unit_name.lower() in base_name.lower():
        return base_name
    return f"{unit_name} - {base_name}"


def set_unit_geometry(payload: dict, unit_aoi: "areaofinterest.AOI") -> dict | None:
    """
    Return ``payload`` retargeted at the unit's bounding box and CRS, or None
    if the bounding box cannot be calculated.
    """
    try:
        ret = unit_aoi.bounding_box_gee_geojson()
    except RuntimeError as e:
        log(f"Unable to calculate unit bounding box: {e}")
        return None
    if not ret:
        return None

    crosses_180th, geojsons = ret
    unit_payload = dict(payload)
    unit_payload["geojsons"] = json.dumps(geojsons)
    unit_payload["crs"] = unit_aoi.get_crs_dst_wkt()
    unit_payload["crosses_180th"] = crosses_180th
    return unit_payload
