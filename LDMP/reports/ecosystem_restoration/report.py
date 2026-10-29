"""Ecosystem restoration progress report."""

from pathlib import Path

from ...logger import log
from ..models import slugify
from .model import IndicatorDataModel, RestorationDataModel, SpatialSupportedOvertime
from .writer.pdf import write_pdf
from .writer.chart import (
    write_current_progress_indicator_chart,
    write_progress_to_bar_chart,
)


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


def generate_report(output_dir: Path) -> Path:
    """Generate the report charts in output_dir and a PDF with all of them.
    Returns the path of the PDF."""
    global_data = _mock_data()
    indicators = global_data.sub_indicator_data
    # Exported charts, in the order they are added to the PDF
    chart_names = []

    # All indicators
    if _log_export(
        "summary",
        write_progress_to_bar_chart(
            global_data.label, indicators, output_dir, "summary"
        ),
    ):
        chart_names.append("summary")

    # Generate each indicator
    for indicator_name, indicator in zip(
        ("indicator_1", "indicator_3", "indicator_4"), indicators
    ):
        chart_name = f"{indicator_name}_current_progress"
        if _log_export(
            chart_name,
            write_current_progress_indicator_chart(indicator, output_dir, chart_name),
        ):
            chart_names.append(chart_name)

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
            chart_names.append(chart_name)

    return write_pdf(
        [_chart_path(output_dir, name) for name in chart_names],
        output_dir / "ecosystem_restoration_report.pdf",
    )
