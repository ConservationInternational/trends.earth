"""Progress chart of the ecosystem restoration progress report, exported with
the plugin's BarChart (plotly, with the QtChartRenderer fallback)."""

from pathlib import Path
from typing import List

from ...chart_type.bar_chart import BarChart, BarSeries
from ...chart_type.line_chart import LineChart, LineSeries
from ..model import RestorationDataModel
from ..styles import (
    AXIS_COLOR,
    FONT_FAMILY,
    GRID_COLOR,
    REPORTED_COLOR,
    SPATIAL_COLOR,
    TARGET_COLOR,
    TEXT_COLOR,
    tr_ecosystem_restoration,
)


def write_progress_to_bar_chart(
    title: str, data: List[RestorationDataModel], output_dir: Path, chart_name: str
) -> tuple[bool, list]:
    """Export the progress chart as chart-<chart_name>.png in output_dir.
    Returns the status and the messages of BarChart.export().
    """
    tr = tr_ecosystem_restoration.tr
    targets = [float(d.target or 0) for d in data]
    reported = [float(d.reported_progress or 0) for d in data]
    spatial = [float(d.spatially_supported or 0) for d in data]

    # Spatially supported area with its share of the target, e.g. 2,000 (80%)
    spatial_texts = [
        f"{value:,.0f} ({value / target:.0%})" if target > 0 else f"{value:,.0f}"
        for value, target in zip(spatial, targets)
    ]

    chart = BarChart(
        root_output_dir=str(output_dir),
        size=(1000, 510),
        categories=[tr(d.label) for d in data],
        series=[
            BarSeries(tr("Country target"), targets, TARGET_COLOR),
            BarSeries(tr("Country-reported progress"), reported, REPORTED_COLOR),
            BarSeries(
                tr("Spatially supported area"), spatial, SPATIAL_COLOR, spatial_texts
            ),
        ],
        font_family=FONT_FAMILY,
        text_color=TEXT_COLOR,
        axis_color=AXIS_COLOR,
        grid_color=GRID_COLOR,
    )
    chart.base_chart_name = chart_name
    chart.plot_title = tr(title)
    chart.value_axis_label = tr("Area (ha)")

    return chart.export()


def write_current_progress_indicator_chart(
    data: RestorationDataModel, output_dir: Path, chart_name: str
) -> tuple[bool, list]:
    """Save the current progress chart of one indicator."""
    tr = tr_ecosystem_restoration.tr
    values = [
        float(data.target or 0),
        float(data.reported_progress or 0),
        float(data.spatially_supported or 0),
    ]

    chart = BarChart(
        root_output_dir=str(output_dir),
        size=(760, 460),
        show_legend=False,
        categories=[tr("Target"), tr("Reported"), tr("Spatially supported")],
        series=[
            BarSeries(
                tr("Area"),
                values,
                [TARGET_COLOR, REPORTED_COLOR, SPATIAL_COLOR],
                [f"<b>{value:,.0f}</b>" for value in values],
            ),
        ],
        font_family=FONT_FAMILY,
        text_color=TEXT_COLOR,
        axis_color=AXIS_COLOR,
        grid_color=GRID_COLOR,
        font_size_labels=13,
    )
    chart.base_chart_name = chart_name
    chart.plot_title = tr("Current progress")
    chart.value_axis_label = tr("Area (ha)")

    return chart.export()


def write_progress_over_time_chart(
    data: RestorationDataModel, output_dir: Path, chart_name: str
) -> tuple[bool, list]:
    """Save the progress over time chart of the data as line chart."""
    tr = tr_ecosystem_restoration.tr
    points = sorted(data.spatially_supported_overtime or [], key=lambda p: p.year)
    if not points:
        return False, ["No spatially supported area over time."]

    years = [point.year for point in points]
    target = float(data.target or 0)

    chart = LineChart(
        root_output_dir=str(output_dir),
        size=(760, 460),
        series=[
            LineSeries(
                tr("Spatially supported area"),
                years,
                [float(point.value or 0) for point in points],
                REPORTED_COLOR,
                fill=True,
            ),
            LineSeries(
                tr("Target"),
                years,
                [target] * len(years),
                TARGET_COLOR,
                dash="dash",
                width=2.5,
                markers=False,
            ),
        ],
        font_family=FONT_FAMILY,
        text_color=TEXT_COLOR,
        axis_color=AXIS_COLOR,
        grid_color=GRID_COLOR,
    )
    chart.base_chart_name = chart_name
    chart.plot_title = tr("Progress over time")
    chart.value_axis_label = tr("Area (ha)")
    return chart.export()
