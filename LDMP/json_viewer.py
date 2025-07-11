"""Collapsible JSON viewer widget for Trends.Earth QGIS plugin."""

import json
from typing import Any, Dict, List, Union

from qgis.PyQt import QtCore, QtGui, QtWidgets


class JsonViewerWidget(QtWidgets.QTreeWidget):
    """A collapsible tree widget for displaying JSON data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setAlternatingRowColors(True)
        self.setFont(
            QtGui.QFont("Courier", 9)
        )  # Monospace font for better JSON display

        # Set minimum size to match the original QTextBrowser
        self.setMinimumSize(400, 0)

        # Enable context menu
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, position):
        """Show context menu with JSON viewer options."""
        menu = QtWidgets.QMenu(self)

        expand_all_action = menu.addAction("Expand All")
        expand_all_action.triggered.connect(self.expandAll)

        collapse_all_action = menu.addAction("Collapse All")
        collapse_all_action.triggered.connect(self.collapseAll)

        menu.addSeparator()

        copy_json_action = menu.addAction("Copy as JSON Text")
        copy_json_action.triggered.connect(self._copy_json_text)

        if hasattr(self, "_original_data"):
            copy_json_action.setEnabled(True)
        else:
            copy_json_action.setEnabled(False)

        menu.exec_(self.mapToGlobal(position))

    def _copy_json_text(self):
        """Copy the JSON data as formatted text to clipboard."""
        json_text = self.get_expanded_json_text()
        if json_text:
            clipboard = QtWidgets.QApplication.clipboard()
            clipboard.setText(json_text)

    def set_json_data(self, json_data: Union[str, Dict, List], collapse_level: int = 1):
        """
        Set JSON data to display in the tree widget.

        Args:
            json_data: JSON data as string, dict, or list
            collapse_level: Level at which to collapse items (0 = all expanded, 1 = first level collapsed, etc.)
        """
        self.clear()

        if isinstance(json_data, str):
            try:
                data = json.loads(json_data)
            except json.JSONDecodeError:
                # If it's not valid JSON, just display as text
                item = QtWidgets.QTreeWidgetItem(self)
                item.setText(0, json_data)
                return
        else:
            data = json_data

        if data is None:
            item = QtWidgets.QTreeWidgetItem(self)
            item.setText(0, "null")
            return

        # Store original data for potential future use
        self._original_data = data

        self._add_json_item(data, self, collapse_level, 0)

        # Expand only the first level by default
        self.expandToDepth(0)

    def _add_json_item(
        self,
        data: Any,
        parent: QtWidgets.QTreeWidgetItem,
        collapse_level: int,
        current_level: int,
    ):
        """Recursively add JSON items to the tree."""

        try:
            if isinstance(data, dict):
                for key, value in data.items():
                    item = QtWidgets.QTreeWidgetItem(parent)

                    if isinstance(value, (dict, list)) and value:
                        # Container types with content
                        type_info = (
                            f"({len(value)} items)"
                            if isinstance(value, list)
                            else f"({len(value)} keys)"
                        )
                        item.setText(0, f"{key}: {type_info}")
                        item.setIcon(0, self._get_icon_for_type(value))
                        self._add_json_item(
                            value, item, collapse_level, current_level + 1
                        )

                        # Collapse items beyond the specified level
                        if current_level >= collapse_level:
                            item.setExpanded(False)
                    else:
                        # Leaf nodes or empty containers
                        value_str = self._format_value(value)
                        item.setText(0, f"{key}: {value_str}")
                        item.setIcon(0, self._get_icon_for_type(value))

            elif isinstance(data, list):
                for i, value in enumerate(data):
                    item = QtWidgets.QTreeWidgetItem(parent)

                    if isinstance(value, (dict, list)) and value:
                        # Container types with content
                        type_info = (
                            f"({len(value)} items)"
                            if isinstance(value, list)
                            else f"({len(value)} keys)"
                        )
                        item.setText(0, f"[{i}]: {type_info}")
                        item.setIcon(0, self._get_icon_for_type(value))
                        self._add_json_item(
                            value, item, collapse_level, current_level + 1
                        )

                        # Collapse items beyond the specified level
                        if current_level >= collapse_level:
                            item.setExpanded(False)
                    else:
                        # Leaf nodes or empty containers
                        value_str = self._format_value(value)
                        item.setText(0, f"[{i}]: {value_str}")
                        item.setIcon(0, self._get_icon_for_type(value))
            else:
                # Handle primitive values at root level
                item = QtWidgets.QTreeWidgetItem(parent)
                value_str = self._format_value(data)
                item.setText(0, value_str)
                item.setIcon(0, self._get_icon_for_type(data))

        except (AttributeError, TypeError) as e:
            # Handle any unexpected data types gracefully
            item = QtWidgets.QTreeWidgetItem(parent)
            item.setText(0, f"Error displaying data: {str(e)}")
            item.setIcon(0, self._create_colored_icon(QtCore.Qt.red))

    def _format_value(self, value: Any) -> str:
        """Format a value for display."""
        if isinstance(value, str):
            # Truncate long strings and show quotes
            if len(value) > 50:
                return f'"{value[:47]}..."'
            else:
                return f'"{value}"'
        elif value is None:
            return "null"
        elif isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, (dict, list)) and not value:
            return "{}" if isinstance(value, dict) else "[]"
        elif isinstance(value, float):
            # Format floats with reasonable precision
            return f"{value:.6g}"
        else:
            return str(value)

    def _get_icon_for_type(self, value: Any) -> QtGui.QIcon:
        """Get an appropriate icon for the value type."""
        # Create simple colored icons for different types
        if isinstance(value, dict):
            return self._create_colored_icon(QtCore.Qt.blue)
        elif isinstance(value, list):
            return self._create_colored_icon(QtCore.Qt.darkGreen)
        elif isinstance(value, str):
            return self._create_colored_icon(QtCore.Qt.darkRed)
        elif isinstance(value, (int, float)):
            return self._create_colored_icon(QtCore.Qt.darkMagenta)
        elif isinstance(value, bool):
            return self._create_colored_icon(QtCore.Qt.darkCyan)
        else:
            return self._create_colored_icon(QtCore.Qt.gray)

    def _create_colored_icon(self, color: QtGui.QColor) -> QtGui.QIcon:
        """Create a simple colored square icon."""
        pixmap = QtGui.QPixmap(12, 12)
        pixmap.fill(color)
        return QtGui.QIcon(pixmap)

    def get_expanded_json_text(self) -> str:
        """Get the full JSON as formatted text (for copying/export)."""
        if hasattr(self, "_original_data"):
            return json.dumps(self._original_data, indent=4, sort_keys=True)
        return ""
