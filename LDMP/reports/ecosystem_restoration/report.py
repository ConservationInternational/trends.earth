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


def _mock_data() -> IndicatorDataModel:
    """Mock the data until the report inputs are available."""
    return IndicatorDataModel(
        "Progress against reporting targets",
        [
            IndicatorDataModel(
                "Indicator 1: Under improved management",
                sub_indicator_data=[
                    RestorationDataModel(
                        label="1.1 Protected areas newly created",
                        target=500,
                        reported_progress=450,
                        spatially_supported=400,
                        spatially_supported_overtime=[
                            SpatialSupportedOvertime(2024, 0),
                            SpatialSupportedOvertime(2025, 200),
                            SpatialSupportedOvertime(2026, 400),
                        ],
                    ),
                    RestorationDataModel(
                        label="1.2 Improved management effectiveness",
                        target=2000,
                        reported_progress=1750,
                        spatially_supported=1600,
                        spatially_supported_overtime=[
                            SpatialSupportedOvertime(2024, 0),
                            SpatialSupportedOvertime(2025, 800),
                            SpatialSupportedOvertime(2026, 1600),
                        ],
                    ),
                ],
            ),
            IndicatorDataModel(
                "Indicator 3: Under restoration",
                sub_indicator_data=[
                    RestorationDataModel(
                        label="3.1 Degraded agricultural lands",
                        target=900,
                        reported_progress=800,
                        spatially_supported=700,
                        spatially_supported_overtime=[
                            SpatialSupportedOvertime(2024, 0),
                            SpatialSupportedOvertime(2025, 300),
                            SpatialSupportedOvertime(2026, 700),
                        ],
                    ),
                    RestorationDataModel(
                        label="3.2 Forest and forest land",
                        target=1700,
                        reported_progress=1350,
                        spatially_supported=1200,
                        spatially_supported_overtime=[
                            SpatialSupportedOvertime(2024, 0),
                            SpatialSupportedOvertime(2025, 600),
                            SpatialSupportedOvertime(2026, 1200),
                        ],
                    ),
                    RestorationDataModel(
                        label="3.3 Natural grasslands and woodlands",
                        target=700,
                        reported_progress=500,
                        spatially_supported=400,
                        spatially_supported_overtime=[
                            SpatialSupportedOvertime(2024, 0),
                            SpatialSupportedOvertime(2025, 200),
                            SpatialSupportedOvertime(2026, 400),
                        ],
                    ),
                    RestorationDataModel(
                        label="3.4 Wetlands, estuaries and mangroves",
                        target=500,
                        reported_progress=350,
                        spatially_supported=300,
                        spatially_supported_overtime=[
                            SpatialSupportedOvertime(2024, 0),
                            SpatialSupportedOvertime(2025, 150),
                            SpatialSupportedOvertime(2026, 300),
                        ],
                    ),
                ],
            ),
            IndicatorDataModel(
                "Indicator 4: Under improved practices",
                sub_indicator_data=[
                    RestorationDataModel(
                        label="4.1 Management benefiting biodiversity",
                        target=900,
                        reported_progress=850,
                        spatially_supported=800,
                        spatially_supported_overtime=[
                            SpatialSupportedOvertime(2024, 0),
                            SpatialSupportedOvertime(2025, 400),
                            SpatialSupportedOvertime(2026, 800),
                        ],
                    ),
                    RestorationDataModel(
                        label="4.2 Third-party certification",
                        target=500,
                        reported_progress=430,
                        spatially_supported=400,
                        spatially_supported_overtime=[
                            SpatialSupportedOvertime(2024, 0),
                            SpatialSupportedOvertime(2025, 200),
                            SpatialSupportedOvertime(2026, 400),
                        ],
                    ),
                    RestorationDataModel(
                        label="4.3 Sustainable production systems",
                        target=650,
                        reported_progress=620,
                        spatially_supported=600,
                        spatially_supported_overtime=[
                            SpatialSupportedOvertime(2024, 0),
                            SpatialSupportedOvertime(2025, 300),
                            SpatialSupportedOvertime(2026, 600),
                        ],
                    ),
                    RestorationDataModel(
                        label="4.4 HCV forest loss avoided",
                        target=350,
                        reported_progress=300,
                        spatially_supported=300,
                        spatially_supported_overtime=[
                            SpatialSupportedOvertime(2024, 0),
                            SpatialSupportedOvertime(2025, 150),
                            SpatialSupportedOvertime(2026, 300),
                        ],
                    ),
                ],
            ),
        ],
    )


def _progress_variables(prefix: str, data: RestorationDataModel) -> dict[str, str]:
    """
    Target, reported progress, spatially supported area and target achieved
    of the data, as the variables <prefix>_reporting_target, etc. Shown with
    the unit in the template, e.g. "8,700 ha" and "77 %".
    """
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


def generate_report(output_dir: Path) -> Path | None:
    """Generate the report charts in output_dir and the PDF of the report.
    Returns the path of the PDF, or None when it could not be exported."""
    global_data = _mock_data()
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
