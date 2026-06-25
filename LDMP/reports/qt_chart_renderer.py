"""Native Qt fallback rendering for report charts."""

import html
import math
import re
import typing

from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QImage, QPainter, QPen


class QtChartRenderer:
    """Render the report chart subset directly with Qt."""

    # Fallback colors, ordered from light to dark.
    _palette = (
        "#e5f5e0",
        "#c7e9c0",
        "#a1d99b",
        "#74c476",
        "#41ab5d",
        "#238b45",
        "#006d2c",
        "#00441b",
    )

    _superscript_translation = str.maketrans(
        "0123456789+-=()",
        "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾",
    )

    def __init__(self, figure: typing.Any, width: int, height: int):
        self._figure = figure.to_dict()
        self._layout = self._figure.get("layout", {})
        self._traces = self._figure.get("data", [])
        self._width = width
        self._height = height

    @staticmethod
    def _qt_attr(name: str, scope: str):
        value = getattr(Qt, name, None)
        if value is not None:
            return value
        return getattr(getattr(Qt, scope), name)

    @staticmethod
    def _image_format():
        image_format = getattr(QImage, "Format_ARGB32", None)
        if image_format is not None:
            return image_format
        return QImage.Format.Format_ARGB32

    @classmethod
    def _plain_text(cls, value: typing.Any) -> str:
        def superscript(match) -> str:
            return match.group(1).translate(cls._superscript_translation)

        text = str(value or "")
        text = re.sub(r"<sup>(.*?)</sup>", superscript, text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\^([0-9+\-=()]+)", superscript, text)
        return html.unescape(text)

    @staticmethod
    def _number(value: typing.Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _format_number(value: float) -> str:
        if abs(value) >= 100:
            return f"{value:,.0f}"
        if abs(value) >= 1:
            return f"{value:,.2f}".rstrip("0").rstrip(".")
        return f"{value:,.3f}".rstrip("0").rstrip(".")

    @classmethod
    def _color(cls, trace: dict, index: int) -> QColor:
        marker = trace.get("marker", {})
        value = marker.get("color", marker.get("colors"))
        if isinstance(value, (list, tuple)):
            value = value[index] if index < len(value) else None
        if not value:
            value = cls._palette[index % len(cls._palette)]

        color = QColor(value)
        if not color.isValid():
            color = QColor(cls._palette[index % len(cls._palette)])
        return color

    @staticmethod
    def _label_color(background: QColor) -> QColor:
        def linearize(channel: float) -> float:
            if channel <= 0.04045:
                return channel / 12.92
            return ((channel + 0.055) / 1.055) ** 2.4

        luminance = (
            0.2126 * linearize(background.redF())
            + 0.7152 * linearize(background.greenF())
            + 0.0722 * linearize(background.blueF())
        )
        return QColor("white" if luminance < 0.179 else "black")

    @staticmethod
    def _font(pixel_size: int, bold: bool = False) -> QFont:
        font = QFont()
        font.setPixelSize(pixel_size)
        font.setBold(bold)
        return font

    def _title(self) -> str:
        title = self._layout.get("title", "")
        if isinstance(title, dict):
            title = title.get("text", "")
        return self._plain_text(title)

    def _draw_title(self, painter: QPainter):
        painter.setPen(QColor("#27313d"))
        painter.setFont(self._font(28, bold=True))
        painter.drawText(
            QRectF(30, 20, self._width - 60, 45),
            self._qt_attr("AlignCenter", "AlignmentFlag"),
            self._title(),
        )

    @classmethod
    def _draw_legend(
        cls,
        painter: QPainter,
        labels: typing.Iterable[str],
        colors: typing.Iterable[QColor],
        x: float,
        y: float,
        width: float,
    ):
        align_left = cls._qt_attr("AlignLeft", "AlignmentFlag")
        align_vcenter = cls._qt_attr("AlignVCenter", "AlignmentFlag")
        painter.setFont(cls._font(15))
        painter.setPen(QColor("#27313d"))
        for label, color in zip(labels, colors):
            painter.fillRect(QRectF(x, y + 3, 16, 16), color)
            painter.drawText(
                QRectF(x + 24, y, width - 24, 23),
                align_left | align_vcenter,
                label,
            )
            y += 27

    @staticmethod
    def _spread_pie_labels(labels, min_y: float, max_y: float):
        if not labels:
            return []

        labels = sorted(labels, key=lambda label: label[2])
        spacing = min(24, (max_y - min_y) / max(len(labels) - 1, 1))
        spread_labels = []
        next_y = min_y
        for value, angle, natural_y in labels:
            label_y = max(natural_y, next_y)
            spread_labels.append((value, angle, label_y))
            next_y = label_y + spacing

        overflow = spread_labels[-1][2] - max_y
        if overflow > 0:
            spread_labels = [
                (value, angle, label_y - overflow)
                for value, angle, label_y in spread_labels
            ]
        return spread_labels

    def _draw_pie(self, painter: QPainter, trace: dict) -> bool:
        labels = [self._plain_text(v) for v in trace.get("labels", [])]
        values = [max(0.0, self._number(v)) for v in trace.get("values", [])]
        total = sum(values)
        if not values or total <= 0:
            return False

        colors = [self._color(trace, i) for i in range(len(values))]
        diameter = min(self._height - 180, self._width - 500)
        pie_rect = QRectF(145, 100, diameter, diameter)
        start_angle = 90 * 16

        painter.setPen(QPen(QColor("white"), 2))
        painter.setFont(self._font(13, bold=True))
        value_labels = []
        for value, color in zip(values, colors):
            span_angle = round(-360 * 16 * value / total)
            painter.setBrush(color)
            painter.drawPie(pie_rect, start_angle, span_angle)

            middle_angle = math.radians((start_angle + span_angle / 2) / 16)
            if span_angle:
                value_labels.append((value, middle_angle))
            start_angle += span_angle

        # Draw outside labels last so narrow slices keep readable values.
        center = pie_rect.center()
        label_radius = diameter * 0.6
        edge_radius = diameter * 0.49
        label_min_y = pie_rect.top() + 12
        label_max_y = pie_rect.bottom() - 12
        align_left = self._qt_attr("AlignLeft", "AlignmentFlag")
        align_right = self._qt_attr("AlignRight", "AlignmentFlag")
        align_vcenter = self._qt_attr("AlignVCenter", "AlignmentFlag")
        label_width = 100
        for side in (-1, 1):
            side_labels = [
                (
                    value,
                    angle,
                    center.y() - math.sin(angle) * label_radius,
                )
                for value, angle in value_labels
                if math.cos(angle) * side >= 0
            ]
            for value, angle, label_y in self._spread_pie_labels(
                side_labels, label_min_y, label_max_y
            ):
                edge_x = center.x() + math.cos(angle) * edge_radius
                edge_y = center.y() - math.sin(angle) * edge_radius
                line_end_x = pie_rect.right() + 30 if side > 0 else pie_rect.left() - 30
                text_x = line_end_x + 5 if side > 0 else line_end_x - label_width - 5
                alignment = align_left if side > 0 else align_right

                painter.setPen(QPen(QColor("#637381"), 1))
                painter.drawLine(QPointF(edge_x, edge_y), QPointF(line_end_x, label_y))
                painter.setPen(QColor("#1f2933"))
                painter.drawText(
                    QRectF(text_x, label_y - 12, label_width, 24),
                    alignment | align_vcenter,
                    self._format_number(value),
                )

        legend_x = pie_rect.right() + 150
        self._draw_legend(
            painter,
            labels,
            colors,
            legend_x,
            125,
            self._width - legend_x - 15,
        )
        return True

    def _bar_bounds(self, traces: typing.List[dict], stacked: bool):
        value_lists = [
            [self._number(value) for value in trace.get("y", [])] for trace in traces
        ]
        category_count = max((len(values) for values in value_lists), default=0)
        if category_count == 0:
            return None

        if stacked:
            positive = [0.0] * category_count
            negative = [0.0] * category_count
            for values in value_lists:
                for index, value in enumerate(values):
                    if value >= 0:
                        positive[index] += value
                    else:
                        negative[index] += value
            low = min(negative + [0.0])
            high = max(positive + [0.0])
        else:
            values = [value for trace_values in value_lists for value in trace_values]
            low = min(values + [0.0])
            high = max(values + [0.0])

        span = high - low
        if span <= 0:
            span = 1.0
        padding = span * 0.1
        return low - padding, high + padding

    def _draw_axes(
        self,
        painter: QPainter,
        plot_rect: QRectF,
        low: float,
        high: float,
        labels: typing.List[str],
    ):
        align_right = self._qt_attr("AlignRight", "AlignmentFlag")
        align_vcenter = self._qt_attr("AlignVCenter", "AlignmentFlag")
        align_center = self._qt_attr("AlignCenter", "AlignmentFlag")

        painter.setFont(self._font(13))
        for step in range(6):
            value = low + (high - low) * step / 5
            y = plot_rect.bottom() - plot_rect.height() * step / 5
            painter.setPen(QPen(QColor("#d9e0e7"), 1))
            painter.drawLine(
                QPointF(plot_rect.left(), y), QPointF(plot_rect.right(), y)
            )
            painter.setPen(QColor("#3e4c59"))
            painter.drawText(
                QRectF(5, y - 12, plot_rect.left() - 15, 24),
                align_right | align_vcenter,
                self._format_number(value),
            )

        painter.setPen(QPen(QColor("#637381"), 2))
        zero_y = plot_rect.bottom() - (0 - low) * plot_rect.height() / (high - low)
        painter.drawLine(
            QPointF(plot_rect.left(), zero_y), QPointF(plot_rect.right(), zero_y)
        )
        painter.drawLine(
            QPointF(plot_rect.left(), plot_rect.top()),
            QPointF(plot_rect.left(), plot_rect.bottom()),
        )

        slot_width = plot_rect.width() / max(len(labels), 1)
        painter.setPen(QColor("#3e4c59"))
        painter.setFont(self._font(12))
        for index, label in enumerate(labels):
            text = label if len(label) <= 18 else f"{label[:15]}..."
            painter.drawText(
                QRectF(
                    plot_rect.left() + slot_width * index,
                    plot_rect.bottom() + 8,
                    slot_width,
                    45,
                ),
                align_center,
                text,
            )

        yaxis = self._layout.get("yaxis", {})
        axis_title = yaxis.get("title", "") if isinstance(yaxis, dict) else ""
        if isinstance(axis_title, dict):
            axis_title = axis_title.get("text", "")
        axis_title = self._plain_text(axis_title)
        if axis_title:
            painter.save()
            painter.translate(18, plot_rect.center().y())
            painter.rotate(-90)
            painter.setFont(self._font(15))
            painter.drawText(
                QRectF(-plot_rect.height() / 2, -15, plot_rect.height(), 30),
                align_center,
                axis_title,
            )
            painter.restore()

    def _draw_bars(self, painter: QPainter, traces: typing.List[dict]) -> bool:
        stacked = self._layout.get("barmode") == "relative"
        bounds = self._bar_bounds(traces, stacked)
        if bounds is None:
            return False
        low, high = bounds

        labels = [self._plain_text(v) for v in traces[0].get("x", [])]
        if not labels:
            return False

        show_legend = bool(self._layout.get("showlegend"))
        legend_width = 230 if show_legend else 20
        plot_rect = QRectF(
            95, 100, self._width - 115 - legend_width, self._height - 235
        )
        self._draw_axes(painter, plot_rect, low, high, labels)

        slot_width = plot_rect.width() / len(labels)
        bar_area_width = slot_width * 0.7
        baseline = plot_rect.bottom() - (0 - low) * plot_rect.height() / (high - low)
        positive_offsets = [0.0] * len(labels)
        negative_offsets = [0.0] * len(labels)

        painter.setFont(self._font(11))
        align_center = self._qt_attr("AlignCenter", "AlignmentFlag")
        for trace_index, trace in enumerate(traces):
            values = [self._number(value) for value in trace.get("y", [])]
            for category_index, value in enumerate(values):
                if category_index >= len(labels):
                    continue

                if stacked:
                    bottom_value = (
                        positive_offsets[category_index]
                        if value >= 0
                        else negative_offsets[category_index]
                    )
                    top_value = bottom_value + value
                    if value >= 0:
                        positive_offsets[category_index] = top_value
                    else:
                        negative_offsets[category_index] = top_value
                    x = (
                        plot_rect.left()
                        + slot_width * category_index
                        + (slot_width - bar_area_width) / 2
                    )
                    width = bar_area_width
                    y_bottom = plot_rect.bottom() - (
                        bottom_value - low
                    ) * plot_rect.height() / (high - low)
                else:
                    width = bar_area_width / len(traces)
                    x = (
                        plot_rect.left()
                        + slot_width * category_index
                        + (slot_width - bar_area_width) / 2
                        + width * trace_index
                    )
                    y_bottom = baseline

                y_top = plot_rect.bottom() - (
                    (top_value if stacked else value) - low
                ) * plot_rect.height() / (high - low)
                rect = QRectF(x, min(y_top, y_bottom), width, abs(y_bottom - y_top))
                color = self._color(trace, category_index)
                painter.fillRect(rect, color)
                painter.setPen(QPen(color.darker(125), 1))
                painter.drawRect(rect)

                if stacked and rect.height() >= 20:
                    painter.setPen(self._label_color(color))
                    painter.drawText(
                        rect,
                        align_center,
                        self._format_number(value),
                    )
                elif not stacked:
                    label_width = max(width, 60)
                    label_y = rect.top() - 22 if value >= 0 else rect.bottom() + 2
                    painter.setPen(QColor("#1f2933"))
                    painter.drawText(
                        QRectF(
                            rect.center().x() - label_width / 2,
                            label_y,
                            label_width,
                            20,
                        ),
                        align_center,
                        self._format_number(value),
                    )

        if show_legend:
            self._draw_legend(
                painter,
                [self._plain_text(trace.get("name", "")) for trace in traces],
                [self._color(trace, 0) for trace in traces],
                plot_rect.right() + 30,
                115,
                legend_width - 35,
            )
        return True

    def save(self, path: str) -> bool:
        image = QImage(self._width, self._height, self._image_format())
        image.fill(QColor("white"))
        painter = QPainter(image)

        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            self._draw_title(painter)
            if len(self._traces) == 1 and self._traces[0].get("type") == "pie":
                rendered = self._draw_pie(painter, self._traces[0])
            elif self._traces and all(
                trace.get("type") == "bar" for trace in self._traces
            ):
                rendered = self._draw_bars(painter, self._traces)
            else:
                rendered = False
        finally:
            painter.end()

        return rendered and image.save(path, "PNG")
