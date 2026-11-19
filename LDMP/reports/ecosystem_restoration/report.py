"""Ecosystem restoration progress report."""

import datetime as dt
import re
from pathlib import Path

import openpyxl

from ...logger import log
from ..models import slugify
from .model import IndicatorDataModel, RestorationDataModel, SpatialSupportedOvertime
from .spatial import GEF_CP_ID_REGEX
from .writer.pdf import write_pdf
from .writer.chart import (
    write_current_progress_indicator_chart,
    write_progress_over_time_chart,
    write_progress_to_bar_chart,
)


# QGIS print layout template of the report
TEMPLATE_PATH = Path(__file__).parent / "template.qpt"

# Folder of the charts of the report, in the output folder
CHARTS_DIR_NAME = "charts"

GEF_CP_ID = "GEF_CP_ID"
# ISO3 of the country of the child project of a row of the report data
COUNTRY = "Country"
COUNTRY_REGEX = re.compile(r"^[A-Z]{3}$")

# Template of the report data XLSX
DATA_TEMPLATE_PATH = (
    Path(__file__).parent
    / "data_progress_template"
    / "restoration_progress_report_data.xlsx"
)
# Name of the report data XLSX
DATA_XLSX_NAME = DATA_TEMPLATE_PATH.name

# Every report data XLSX has
REQUIRED_DATA_COLUMNS = (
    GEF_CP_ID,
    COUNTRY,
    "indicator",
    "sub_indicator",
    "target",
    "reported_progress",
)

# Reporting scopes, of the report label by their parameter value
REPORTING_SCOPE_PROJECT = "project"
REPORTING_SCOPE_COUNTRY = "country"
REPORTING_SCOPE_CUSTOM_AOI = "custom_aoi"
REPORTING_SCOPES = {
    REPORTING_SCOPE_PROJECT: "Project",
    REPORTING_SCOPE_COUNTRY: "Country",
    REPORTING_SCOPE_CUSTOM_AOI: "Custom AOI",
}
# Analysis area of the report of each reporting scope
ANALYSIS_AREAS = {
    REPORTING_SCOPE_PROJECT: "Project intervention area",
    REPORTING_SCOPE_COUNTRY: "National boundary",
    REPORTING_SCOPE_CUSTOM_AOI: "Custom AOI",
}

# Reporting period, from the baseline year to the reporting year,
# by default from 2 years before this year
MIN_REPORTING_YEAR = 2000
DEFAULT_BASELINE_YEARS_BEFORE = 2

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


def _cell_text(value) -> str:
    """Text of an XLSX cell."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def read_data(path: str | Path) -> tuple[list[str], list[dict]]:
    """Columns and rows of the first sheet of the report data XLSX.

    The first row is the columns, every other row is a dict of the text of its
    cells by column. Empty rows are skipped.
    """
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = workbook.worksheets[0].iter_rows(values_only=True)
        columns = [_cell_text(value) for value in next(rows, ())]
        data = []
        for row in rows:
            values = [_cell_text(value) for value in row]
            if any(values):
                values += [""] * (len(columns) - len(values))
                data.append(dict(zip(columns, values)))
        return columns, data
    finally:
        workbook.close()


def _log_export(chart_name: str, result: tuple[bool, list]) -> bool:
    status, messages = result
    if not status:
        log(f"Chart {chart_name} was not exported: {'; '.join(messages)}")
    return status


def _chart_path(output_dir: Path, chart_name: str) -> Path:
    """Path of the image saved by BaseChart.export() for the chart name."""
    return output_dir / f"{slugify(f'chart-{chart_name}')}.png"


def _number(value: str) -> float | None:
    """Number of a report data cell, None when it is empty."""
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
    """Report data rows by sub-indicator label, checked against INDICATORS.

    Raises ValueError When a sub-indicator is in more than one row.
    """
    found_rows = []
    rows = {}
    # Row 1 of the XLSX is the header
    for number, row in enumerate(data, start=2):
        source = f"Report data row {number}"
        gef_cp_id = (row[GEF_CP_ID] or "").strip()
        if not gef_cp_id:
            raise ValueError(f"{source}: '{gef_cp_id}' is empty")
        if not GEF_CP_ID_REGEX.match(gef_cp_id):
            raise ValueError(f"{source}: {GEF_CP_ID} {gef_cp_id} is not five numbers.")
        country = (row[COUNTRY] or "").strip()
        if not COUNTRY_REGEX.match(country):
            raise ValueError(
                f"{source}: {COUNTRY} '{country}' is not an ISO3 code, e.g. IND."
            )

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


def validate_data(columns: list[str], data: list[dict]) -> list[str]:
    """Errors of the report data, empty when it is valid.

    The report data has REQUIRED_DATA_COLUMNS, and its rows are checked by
    _rows_by_sub_indicator.
    """
    missing = [column for column in REQUIRED_DATA_COLUMNS if column not in columns]
    if missing:
        return [f"Report data has no column: {', '.join(missing)}"]
    try:
        _rows_by_sub_indicator(data)
    except ValueError as error:
        return [str(error)]
    return []


def validate_reported_progress(
    data: list[dict], sites: dict[tuple[str, int], list[dict]], reporting_year: int
) -> list[str]:
    """Validate reported progress, empty when it is valid.

    A target needs no sites, but a reported progress greater than zero needs one site at least
    in the reporting year, of the GEF_CP_ID and the sub-indicator of the row.
    """
    site_keys = {
        (site["gef_cp_id"], site["sub_indicator"])
        for (_, year), group in sites.items()
        if year == reporting_year
        for site in group
    }
    errors = []

    # Row 1 of the XLSX is the header
    for number, row in enumerate(data, start=2):
        gef_cp_id = (row[GEF_CP_ID] or "").strip()
        sub_indicator = (row["sub_indicator"] or "").strip()
        reported_progress = _number(row["reported_progress"]) or 0
        if reported_progress > 0 and (gef_cp_id, sub_indicator) not in site_keys:
            errors.append(
                f"Report data row {number}: reported progress of sub-indicator "
                f"'{sub_indicator}' for child project {gef_cp_id} has no site."
            )
    return errors


def validate_reporting_period(baseline_year, reporting_year) -> list[str]:
    """Validate reporting periods."""
    years = {"Baseline year": baseline_year, "Monitoring year": reporting_year}
    errors = [
        f"{name} is not a year: {year}"
        for name, year in years.items()
        if not isinstance(year, int) or isinstance(year, bool)
    ]
    if errors:
        return errors

    this_year = dt.date.today().year
    for name, year in years.items():
        if year < MIN_REPORTING_YEAR:
            errors.append(f"{name} {year} is before {MIN_REPORTING_YEAR}.")
    if reporting_year > this_year:
        errors.append(
            f"Monitoring year {reporting_year} is after this year {this_year}."
        )
    if baseline_year > reporting_year:
        errors.append(
            f"Baseline year {baseline_year} is after monitoring year {reporting_year}."
        )
    return errors


def _format_data(
    data: list[dict],
    spatial_data: list[dict],
    reporting_period: tuple[int, int],
) -> IndicatorDataModel:
    """Format the report data, one dict per sub-indicator, as an IndicatorDataModel."""
    years = list(range(reporting_period[0], reporting_period[1] + 1))

    # Spatially supported area by sub-indicator label and year
    # Calculated from spatial_data
    areas: dict[str, dict[int, float]] = {}
    for row in spatial_data:
        sub_indicator = _check_indicator(f"Spatial input, year {row['year']}", row)
        # The areas of a sub-indicator in a year are summed
        area_by_year = areas.setdefault(sub_indicator, {})
        area_by_year[row["year"]] = area_by_year.get(row["year"], 0) + row["area"]

    # Formatting the data
    rows = _rows_by_sub_indicator(data)
    indicator_models = []
    for indicator in INDICATORS.values():
        sub_indicators = []
        for label in indicator["sub_indicators"]:
            row = rows.get(label, {})

            # Spatially supported area of every year of the reporting period
            area_by_year = areas.get(label, {})
            overtime = [
                SpatialSupportedOvertime(year=year, value=area_by_year.get(year, 0))
                for year in years
            ]

            # Append RestorationDataModel to sub_indicators data
            sub_indicators.append(
                RestorationDataModel(
                    label=label,
                    target=row.get("target"),
                    reported_progress=row.get("reported_progress"),
                    spatially_supported=overtime[-1].value,
                    spatially_supported_overtime=overtime,
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


def _report_variables(
    report_title: str,
    reporting_scope: str,
    global_data: IndicatorDataModel,
    countries: list[str],
    reporting_period: tuple[int, int],
    spatial_data_version: str,
    gef_child_project: str,
) -> dict[str, str]:
    """Values for the reports."""
    variables = {
        "te_restoration_title": report_title,
        "te_restoration_reporting_scope": REPORTING_SCOPES[reporting_scope],
        "te_restoration_country": " • ".join(countries),
        "te_restoration_gef_child_project": gef_child_project,
        "te_restoration_analysis_area": ANALYSIS_AREAS[reporting_scope],
        # Baseline year to reporting year
        "te_restoration_reporting_period": (
            f"{reporting_period[0]} to {reporting_period[1]}"
        ),
        "te_restoration_report_generated": dt.date.today().strftime("%Y-%m-%d"),
        # Name of the spatial input layer, e.g. IND_V20251231
        "te_restoration_spatial_data_version": spatial_data_version,
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
    report_title: str,
    reporting_scope: str,
    data: list[dict],
    spatial_data: list[dict],
    countries: list[str],
    reporting_period: tuple[int, int],
    spatial_data_version: str,
    gef_child_project: str,
) -> Path | None:
    """Generate the PDF report of Ecosystem Restoration Progress.

    The reporting period is the baseline year and the reporting year.
    Returns the path of the PDF, or None when it could not be exported.
    """
    global_data = _format_data(data, spatial_data, reporting_period)
    indicators = global_data.sub_indicator_data
    # Charts of the report, in the charts folder
    charts_dir = output_dir / CHARTS_DIR_NAME
    charts_dir.mkdir(parents=True, exist_ok=True)
    # Image of each picture item of the template, by item id
    pictures = {}

    # All indicators
    if _log_export(
        "summary",
        write_progress_to_bar_chart(
            global_data.label, indicators, charts_dir, "summary"
        ),
    ):
        pictures["Global.SummaryChart"] = _chart_path(charts_dir, "summary")

    # Generate each indicator
    for indicator_name, indicator in zip(INDICATORS, indicators):
        # Prefix of the indicator items in the template, e.g. Indicator_1
        item_prefix = indicator_name.capitalize()
        chart_name = f"{indicator_name}_current_progress"
        if _log_export(
            chart_name,
            write_current_progress_indicator_chart(indicator, charts_dir, chart_name),
        ):
            pictures[f"{item_prefix}.CurrentProgressChart"] = _chart_path(
                charts_dir, chart_name
            )

        chart_name = f"{indicator_name}_progress_over_time"
        if _log_export(
            chart_name,
            write_progress_over_time_chart(indicator, charts_dir, chart_name),
        ):
            pictures[f"{item_prefix}.ProgressOverTimeChart"] = _chart_path(
                charts_dir, chart_name
            )

        chart_name = f"summary_{indicator_name}"
        if _log_export(
            chart_name,
            write_progress_to_bar_chart(
                indicator.label,
                indicator.sub_indicator_data,
                charts_dir,
                chart_name,
            ),
        ):
            pictures[f"{item_prefix}.SubIndicatorChart"] = _chart_path(
                charts_dir, chart_name
            )

    return write_pdf(
        TEMPLATE_PATH,
        _report_variables(
            report_title,
            reporting_scope,
            global_data,
            countries,
            reporting_period,
            spatial_data_version,
            gef_child_project,
        ),
        pictures,
        output_dir / "Restoration_Progress_Report.pdf",
    )
