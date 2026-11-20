"""Vertical bar chart."""

import typing
from dataclasses import dataclass

from ..charts import (
    _PLOTLY_IMAGE_EXPORT_MSG,
    _PLOTLY_MISSING_MSG,
    BaseChart,
    go,
)
from ..models import slugify


@dataclass
class BarSeries:
    """One series of values per category."""

    name: str
    values: list[float]
    # One color for the whole series, or one color per bar
    color: typing.Union[str, list[str]]

    # Optional text shown on each bar, defaults to the formatted value
    texts: typing.Optional[list[str]] = None


class BarChart(BaseChart):
    """Vertical bar chart of one or more series over the same categories, with
    the bars of each series side by side.

    Use StackedBarChart for stacked bars.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.categories: list[str] = kwargs.pop("categories", [])
        self.series: list[BarSeries] = kwargs.pop("series", [])
        self.size: typing.Optional[tuple[int, int]] = kwargs.pop("size", None)
        self.show_legend: bool = kwargs.pop("show_legend", True)

        # Optional styles, plotly defaults are used when None
        self.font_family: typing.Optional[str] = kwargs.pop("font_family", None)
        self.text_color: typing.Optional[str] = kwargs.pop("text_color", None)
        self.axis_color: typing.Optional[str] = kwargs.pop("axis_color", None)
        self.grid_color: typing.Optional[str] = kwargs.pop("grid_color", None)

        self.font_size_title: int = kwargs.pop("font_size_title", 36)
        self.font_size_body: int = kwargs.pop("font_size_body", 26)
        self.font_size_legend: int = kwargs.pop("font_size_legend", 26)
        self.font_size_labels: int = kwargs.pop("font_size_labels", 22)

    @property
    def preferred_size(self) -> tuple[int, int]:
        if self.size is not None:
            return self.size
        return super().preferred_size

    def export(self) -> tuple[bool, list]:
        if not self.is_plotly_available():
            return False, [_PLOTLY_MISSING_MSG]

        # Create chart
        if not self.root_output_dir:
            return False, ["Output directory not defined"]

        if len(self.categories) == 0 or len(self.series) == 0:
            return False, ["No data items defined."]

        file_name = slugify(f"chart-{self.base_chart_name}")
        output_file_path = f"{self.root_output_dir}/{file_name}.png"

        # Preferred chart size
        pw, ph = self.preferred_size

        # Create and export grouped bar graph
        fig = go.Figure()
        for series in self.series:
            texts = series.texts or [f"{value:,.0f}" for value in series.values]
            fig.add_trace(
                go.Bar(
                    x=self.categories,
                    y=series.values,
                    name=series.name,
                    text=texts,
                    textposition="outside",
                    marker_color=series.color,
                    textfont={"size": self.font_size_labels},
                )
            )

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
                "showline": self.axis_color is not None,
                "linecolor": self.axis_color,
            },
            yaxis={
                "title": self.value_axis_label,
                "tickfont_size": self.font_size_body,
                "tickformat": ",.4r",
                "showline": self.axis_color is not None,
                "linecolor": self.axis_color,
                "gridcolor": self.grid_color,
            },
            legend={"font": {"size": self.font_size_legend}},
            uniformtext={"minsize": 7, "mode": "hide"},
            barmode="group",
            showlegend=self.show_legend,
            width=pw,
            height=ph,
        )

        # Save image
        if not self.save_image(fig, output_file_path):
            return False, [_PLOTLY_IMAGE_EXPORT_MSG]
        self._paths.append(output_file_path)

        return True, []
