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

# Separator of the columns of the report data CSV
# We are using ; as the indicator has comma
CSV_DELIMITER = ";"

GEF_CP_ID = "GEF_CP_ID"

# Every report data CSV has
REQUIRED_DATA_COLUMNS = (
    GEF_CP_ID,
    "indicator",
    "sub_indicator",
    "target",
    "reported_progress",
)

# Indicators
INDICATORS = {
    "indicator_1": {
        "label": "1. Under improved management",
        "sub_indicators": [
            "1.1 Protected areas newly created",
            "1.2 Improved management effectiveness",
        ],
    },
    "indicator_3": {
        "label": "3. Under restoration",
        "sub_indicators": [
            "3.1 Degraded agricultural lands",
            "3.2 Forest and forest land",
            "3.3 Natural grasslands and woodlands",
            "3.4 Wetlands, estuaries and mangroves",
        ],
    },
    "indicator_4": {
        "label": "4. Under improved practices",
        "sub_indicators": [
            "4.1 Management benefiting biodiversity",
            "4.2 Third-party certification",
            "4.3 Sustainable production systems",
            "4.4 HCV forest loss avoided",
        ],
    },
}


# Indicator label of each sub-indicator label in INDICATORS
INDICATOR_BY_SUB_INDICATOR = {
    sub_indicator: indicator["label"]
    for indicator in INDICATORS.values()
    for sub_indicator in indicator["sub_indicators"]
}


def _log_export(chart_name: str, result: tuple[bool, list]) -> bool:
    status, messages = result
    if not status:
        log(f"Chart {chart_name} was not exported: {'; '.join(messages)}")
    return status


def _chart_path(output_dir: Path, chart_name: str) -> Path:
    """Path of the image saved by BaseChart.export() for the chart name."""
    return output_dir / f"{slugify(f'chart-{chart_name}')}.png"


def _number(value: str) -> float | None:
    """Number of a CSV cell, None when it is empty."""
    value = (value or "").strip().replace(",", "")
    return float(value) if value else None


def _check_indicator(source: str, row: dict) -> str:
    """Sub-indicator of the row, checked against the label of indicator.

    Raises ValueError when the sub-indicator is not in any indicator, or the
    indicator is not the one of the sub-indicator.
    """
    indicator = (row["indicator"] or "").strip()
    sub_indicator = (row["sub_indicator"] or "").strip()
    if sub_indicator not in INDICATOR_BY_SUB_INDICATOR:
        raise ValueError(f"{source}: unknown sub-indicator '{sub_indicator}'.")
    if indicator != INDICATOR_BY_SUB_INDICATOR[sub_indicator]:
        raise ValueError(
            f"{source}: sub-indicator '{sub_indicator}' is not under "
            f"indicator '{indicator}', it is under "
            f"'{INDICATOR_BY_SUB_INDICATOR[sub_indicator]}'."
        )
    return sub_indicator


def _rows_by_sub_indicator(data: list[dict]) -> dict[str, dict]:
    """CSV rows by sub-indicator label, checked against INDICATORS.

    Raises ValueError When a sub-indicator is in more than one row.
    """
    found_rows = []
    rows = {}
    # Row 1 of the CSV is the header
    for number, row in enumerate(data, start=2):
        source = f"Report data row {number}"
        gef_cp_id = (row[GEF_CP_ID] or "").strip()
        if not gef_cp_id:
            raise ValueError(f"{source}: '{gef_cp_id}' is empty")

        sub_indicator = _check_indicator(source, row)
        identifier = f"{gef_cp_id}:{sub_indicator}"
        if identifier in found_rows:
            raise ValueError(
                f"{source}: sub-indicator '{sub_indicator}' for child project {gef_cp_id} "
                "is in more than one row."
            )
        found_rows.append(identifier)

        total = rows.setdefault(sub_indicator, {"target": 0, "reported_progress": 0})
        for key in total:
            value = _number(row[key])
            if value is not None:
                total[key] = (total[key] or 0) + value
    return rows


def _format_data(data: list[dict], spatial_data: list[dict]) -> IndicatorDataModel:
    """Format the report data, one dict per sub-indicator, as an IndicatorDataModel."""

    # Spatially supported area over time by sub-indicator label
    # Calculated from spatial_data
    spatial_by_sub_indicator: dict[str, list[SpatialSupportedOvertime]] = {}
    for row in spatial_data:
        sub_indicator = _check_indicator(f"Spatial input, year {row['year']}", row)
        spatial_by_sub_indicator.setdefault(sub_indicator, []).append(
            SpatialSupportedOvertime(year=row["year"], value=row["area"])
        )

    # Formatting the data
    rows = _rows_by_sub_indicator(data)
    indicator_models = []
    for indicator in INDICATORS.values():
        sub_indicators = []
        for label in indicator["sub_indicators"]:
            row = rows.get(label, {})

            # Sort spatially supported overtime by year
            overtime = sorted(
                spatial_by_sub_indicator.get(label, []),
                key=lambda point: point.year,
            )

            # Append RestorationDataModel to sub_indicators data
            sub_indicators.append(
                RestorationDataModel(
                    label=label,
                    target=row.get("target"),
                    reported_progress=row.get("reported_progress"),
                    spatially_supported=overtime[-1].value if overtime else 0,
                    spatially_supported_overtime=overtime or None,
                )
            )
        indicator_models.append(IndicatorDataModel(indicator["label"], sub_indicators))

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

    # Models of _format_data are in the order of INDICATORS
    indicators = dict(zip(INDICATORS, global_data.sub_indicator_data))
    for indicator_name, indicator_config in INDICATORS.items():
        # Indicator, e.g. te_restoration_indicator_1_reporting_target
        indicator = indicators[indicator_name]
        prefix = f"te_restoration_{indicator_name}"
        variables[f"{prefix}_label"] = indicator_config["label"]
        variables.update(_progress_variables(prefix, indicator))

        # Sub-indicators, e.g. te_restoration_indicator_1_1_reporting_target
        for number, (label, sub_indicator) in enumerate(
            zip(indicator_config["sub_indicators"], indicator.sub_indicator_data),
            start=1,
        ):
            variables[f"{prefix}_{number}_label"] = label
            variables.update(_progress_variables(f"{prefix}_{number}", sub_indicator))

    return variables


def generate_report(
    output_dir: Path,
    data: list[dict],
    spatial_data: list[dict],
) -> Path | None:
    """Generate the PDF report of Ecosystem Restoration Progress.

    Returns the path of the PDF, or None when it could not be exported.
    """
    global_data = _format_data(data, spatial_data)
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
    for indicator_name, indicator in zip(INDICATORS, indicators):
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
        output_dir / "Restoration_Progress_Report.pdf",
    )
