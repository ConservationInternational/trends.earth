"""Ecosystem restoration progress report."""

import datetime as dt
from pathlib import Path

from ...logger import log
from ..models import slugify
from .model import IndicatorDataModel, RestorationDataModel, SpatialSupportedOvertime
from .writer.pdf import write_pdf
from .writer.chart import (
    write_current_progress_indicator_chart,
    write_progress_over_time_chart,
    write_progress_to_bar_chart,
)


# QGIS print layout template of the report
TEMPLATE_PATH = Path(__file__).parent / "template.qpt"
INDICATOR_NAMES = ("indicator_1", "indicator_3", "indicator_4")


def _log_export(chart_name: str, result: tuple[bool, list]) -> bool:
    status, messages = result
    if not status:
        log(f"Chart {chart_name} was not exported: {'; '.join(messages)}")
    return status


def _chart_path(output_dir: Path, chart_name: str) -> Path:
    """Path of the image saved by BaseChart.export() for the chart name."""
    return output_dir / f"{slugify(f'chart-{chart_name}')}.png"


def _mock_spatially_data() -> dict[str, list]:
    """Mock the spatial data until the report inputs are available."""

    mock_spatial_data = {
        "1.1 Protected areas newly created": [
            SpatialSupportedOvertime(2024, 0),
            SpatialSupportedOvertime(2025, 200),
            SpatialSupportedOvertime(2026, 400),
        ],
        "1.2 Improved management effectiveness": [
            SpatialSupportedOvertime(2024, 0),
            SpatialSupportedOvertime(2025, 800),
            SpatialSupportedOvertime(2026, 1600),
        ],
        "3.1 Degraded agricultural lands": [
            SpatialSupportedOvertime(2024, 0),
            SpatialSupportedOvertime(2025, 300),
            SpatialSupportedOvertime(2026, 700),
        ],
        "3.2 Forest and forest land": [
            SpatialSupportedOvertime(2024, 0),
            SpatialSupportedOvertime(2025, 600),
            SpatialSupportedOvertime(2026, 1200),
        ],
        "3.3 Natural grasslands and woodlands": [
            SpatialSupportedOvertime(2024, 0),
            SpatialSupportedOvertime(2025, 200),
            SpatialSupportedOvertime(2026, 400),
        ],
        "3.4 Wetlands, estuaries and mangroves": [
            SpatialSupportedOvertime(2024, 0),
            SpatialSupportedOvertime(2025, 150),
            SpatialSupportedOvertime(2026, 300),
        ],
        "4.1 Management benefiting biodiversity": [
            SpatialSupportedOvertime(2024, 0),
            SpatialSupportedOvertime(2025, 400),
            SpatialSupportedOvertime(2026, 800),
        ],
        "4.2 Third-party certification": [
            SpatialSupportedOvertime(2024, 0),
            SpatialSupportedOvertime(2025, 200),
            SpatialSupportedOvertime(2026, 400),
        ],
        "4.3 Sustainable production systems": [
            SpatialSupportedOvertime(2024, 0),
            SpatialSupportedOvertime(2025, 300),
            SpatialSupportedOvertime(2026, 600),
        ],
        "4.4 HCV forest loss avoided": [
            SpatialSupportedOvertime(2024, 0),
            SpatialSupportedOvertime(2025, 150),
            SpatialSupportedOvertime(2026, 300),
        ],
    }
    return mock_spatial_data


def _number(value: str) -> float | None:
    """Number of a CSV cell, None when it is empty."""
    value = (value or "").strip().replace(",", "")
    return float(value) if value else None


def _sub_indicator_code(label: str) -> str:
    """Code at the start of a sub-indicator label, e.g. 1.1."""
    return (label or "").strip().split(" ", 1)[0]


def _format_data(data: list[dict]) -> IndicatorDataModel:
    """Format the report data, one dict per sub-indicator, as an
    IndicatorDataModel."""
    rows_by_indicator = {}
    for row in data:
        rows_by_indicator.setdefault(row["indicator"].strip(), []).append(row)

    # Mock spatial data by the code of the sub-indicator, e.g. 1.1
    spatial_data = {
        _sub_indicator_code(label): overtime
        for label, overtime in _mock_spatially_data().items()
    }

    indicator_models = []
    for indicator, rows in rows_by_indicator.items():
        sub_indicators = []
        for row in rows:
            label = row["sub_indicator"].strip()
            # Sort spatially supported overtime
            overtime = sorted(
                spatial_data.get(_sub_indicator_code(label), []),
                key=lambda point: point.year,
            )
            sub_indicators.append(
                RestorationDataModel(
                    label=label,
                    target=_number(row["target"]),
                    reported_progress=_number(row["reported_progress"]),
                    spatially_supported=overtime[-1].value if overtime else None,
                    spatially_supported_overtime=overtime or None,
                )
            )
        indicator_models.append(IndicatorDataModel(indicator, sub_indicators))

    return IndicatorDataModel("Progress against reporting targets", indicator_models)


def _progress_variables(prefix: str, data: RestorationDataModel) -> dict[str, str]:
    """Convert RestorationDataModel as context for report."""
    target = data.target or 0
    reported_progress = data.reported_progress or 0
    spatially_supported = data.spatially_supported or 0
    return {
        f"{prefix}_reporting_target": f"{target:,.0f}",
        f"{prefix}_reported_progress": f"{reported_progress:,.0f}",
        f"{prefix}_spatially_supported": f"{spatially_supported:,.0f}",
        f"{prefix}_target_achieved": (
            f"{spatially_supported / target * 100:.0f}" if target > 0 else "-"
        ),
    }


def _report_variables(global_data: IndicatorDataModel) -> dict[str, str]:
    """Values of the [% @te_restoration_... %] expressions in the template labels."""
    variables = {
        "te_restoration_reporting_scope": "Project 1",
        "te_restoration_country": "Indonesia",
        "te_restoration_gef_child_project": "ABC12345",
        "te_restoration_analysis_area": "Indonesia",
        "te_restoration_reporting_period": "2024 to 2026",
        "te_restoration_report_generated": dt.date.today().strftime("%d %B %Y"),
        "te_restoration_spatial_data_version": "0.0.1",
    }

    # All indicators, e.g. te_restoration_global_reporting_target
    variables.update(_progress_variables("te_restoration_global", global_data))

    for indicator_name, indicator in zip(
        INDICATOR_NAMES, global_data.sub_indicator_data
    ):
        # Indicator
        prefix = f"te_restoration_{indicator_name}"
        variables.update(_progress_variables(prefix, indicator))

        # Sub-indicators data
        for number, sub_indicator in enumerate(indicator.sub_indicator_data, start=1):
            variables.update(_progress_variables(f"{prefix}_{number}", sub_indicator))

    return variables


def generate_report(output_dir: Path, data: list[dict]) -> Path | None:
    """Generate the PDF report of Ecosystem Restoration Progress.

    Returns the path of the PDF, or None when it could not be exported.
    """
    global_data = _format_data(data)
    indicators = global_data.sub_indicator_data
    # Image of each picture item of the template, by item id
    pictures = {}

    # All indicators
    if _log_export(
        "summary",
        write_progress_to_bar_chart(
            global_data.label, indicators, output_dir, "summary"
        ),
    ):
        pictures["Global.SummaryChart"] = _chart_path(output_dir, "summary")

    # Generate each indicator
    for indicator_name, indicator in zip(INDICATOR_NAMES, indicators):
        # Prefix of the indicator items in the template, e.g. Indicator_1
        item_prefix = indicator_name.capitalize()
        chart_name = f"{indicator_name}_current_progress"
        if _log_export(
            chart_name,
            write_current_progress_indicator_chart(indicator, output_dir, chart_name),
        ):
            pictures[f"{item_prefix}.CurrentProgressChart"] = _chart_path(
                output_dir, chart_name
            )

        chart_name = f"{indicator_name}_progress_over_time"
        if _log_export(
            chart_name,
            write_progress_over_time_chart(indicator, output_dir, chart_name),
        ):
            pictures[f"{item_prefix}.ProgressOverTimeChart"] = _chart_path(
                output_dir, chart_name
            )

        chart_name = f"summary_{indicator_name}"
        if _log_export(
            chart_name,
            write_progress_to_bar_chart(
                indicator.label,
                indicator.sub_indicator_data,
                output_dir,
                chart_name,
            ),
        ):
            pictures[f"{item_prefix}.SubIndicatorChart"] = _chart_path(
                output_dir, chart_name
            )

    return write_pdf(
        TEMPLATE_PATH,
        _report_variables(global_data),
        pictures,
        output_dir / "ecosystem_restoration_report.pdf",
    )
