"""Line chart."""

import typing
from dataclasses import dataclass

from qgis.PyQt.QtGui import QColor

from ..charts import (
    _PLOTLY_IMAGE_EXPORT_MSG,
    _PLOTLY_MISSING_MSG,
    BaseChart,
    go,
)
from ..models import slugify


@dataclass
class LineSeries:
    """One line of y values over x values."""

    name: str
    x: list
    y: list[float]
    color: str

    dash: typing.Optional[str] = None
    width: float = 3
    markers: bool = True
    fill: bool = False


class LineChart(BaseChart):
    """Line chart of one or more series."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.series: list[LineSeries] = kwargs.pop("series", [])

        self.x_ticks: typing.Optional[list] = kwargs.pop("x_ticks", None)
        self.size: typing.Optional[tuple[int, int]] = kwargs.pop("size", None)
        self.show_legend: bool = kwargs.pop("show_legend", True)

        # Optional styles, plotly defaults are used when None
        self.font_family: typing.Optional[str] = kwargs.pop("font_family", None)
        self.text_color: typing.Optional[str] = kwargs.pop("text_color", None)
        self.axis_color: typing.Optional[str] = kwargs.pop("axis_color", None)
        self.grid_color: typing.Optional[str] = kwargs.pop("grid_color", None)

        self.font_size_title: int = kwargs.pop("font_size_title", 18)
        self.font_size_body: int = kwargs.pop("font_size_body", 13)
        self.font_size_legend: int = kwargs.pop("font_size_legend", 13)
        self.marker_size: int = kwargs.pop("marker_size", 10)
        # Opacity of the area filled below a line
        self.fill_opacity: float = kwargs.pop("fill_opacity", 0.12)

    @property
    def preferred_size(self) -> tuple[int, int]:
        if self.size is not None:
            return self.size
        return super().preferred_size

    def _fill_color(self, color: str) -> str:
        qcolor = QColor(color)
        return (
            f"rgba({qcolor.red()}, {qcolor.green()}, {qcolor.blue()}, "
            f"{self.fill_opacity})"
        )

    def export(self) -> tuple[bool, list]:
        if not self.is_plotly_available():
            return False, [_PLOTLY_MISSING_MSG]

        # Create chart
        if not self.root_output_dir:
            return False, ["Output directory not defined"]

        if len(self.series) == 0:
            return False, ["No data items defined."]

        file_name = slugify(f"chart-{self.base_chart_name}")
        output_file_path = f"{self.root_output_dir}/{file_name}.png"

        # Preferred chart size
        pw, ph = self.preferred_size

        # Create and export line graph
        fig = go.Figure()
        for series in self.series:
            fig.add_trace(
                go.Scatter(
                    x=series.x,
                    y=series.y,
                    name=series.name,
                    mode="lines+markers" if series.markers else "lines",
                    line={
                        "color": series.color,
                        "width": series.width,
                        "dash": series.dash,
                    },
                    marker={"color": series.color, "size": self.marker_size},
                    fill="tozeroy" if series.fill else None,
                    fillcolor=self._fill_color(series.color) if series.fill else None,
                )
            )

        x_ticks = self.x_ticks
        if x_ticks is None:
            x_ticks = sorted({x for series in self.series for x in series.x})

        fig.update_layout(
            title={
                "text": self.plot_title,
                "y": 0.95,
                "x": 0.5,
                "xanchor": "center",
                "yanchor": "top",
                "font": {"size": self.font_size_title},
            },
            font={"family": self.font_family, "color": self.text_color},
            xaxis={
                "tickfont_size": self.font_size_body,
                "tickmode": "array",
                "tickvals": x_ticks,
                "showline": self.axis_color is not None,
                "linecolor": self.axis_color,
                "gridcolor": self.grid_color,
            },
            yaxis={
                "title": self.value_axis_label,
                "tickfont_size": self.font_size_body,
                "tickformat": ",.4r",
                "rangemode": "tozero",
                "showline": self.axis_color is not None,
                "linecolor": self.axis_color,
                "gridcolor": self.grid_color,
            },
            legend={"font": {"size": self.font_size_legend}},
            showlegend=self.show_legend,
            width=pw,
            height=ph,
        )

        # Save image
        if not self.save_image(fig, output_file_path):
            return False, [_PLOTLY_IMAGE_EXPORT_MSG]
        self._paths.append(output_file_path)

        return True, []
