"""Report data XLSX template of a country."""

import json
from copy import copy
from dataclasses import dataclass
from pathlib import Path

import openpyxl
from openpyxl.worksheet.cell_range import MultiCellRange

from ..report import DATA_TEMPLATE_PATH, INDICATORS
from ..spatial import EXAMPLE_GEF_CP_ID

CHILD_PROJECTS_PATH = Path(__file__).parent.parent / "child_projects.json"

# Columns of the report data template: GEF_CP_ID, Country, indicator,
# sub_indicator, target and reported_progress
COLUMN_COUNT = 6

# Default ISO3 of the template.
DEFAULT_COUNTRY = "XXX"


@dataclass
class ChildProject:
    gef_cp_id: str
    # ISO3 of the country, e.g. AGO
    country: str
    country_name: str
    title: str


def read_child_projects() -> list[ChildProject]:
    """Child projects of child_projects.json, sorted by country name."""
    data = json.loads(CHILD_PROJECTS_PATH.read_text(encoding="utf-8"))
    return [ChildProject(**child_project) for child_project in data]


def countries(child_projects: list[ChildProject]) -> dict[str, str]:
    """Country names by ISO3 of the child projects, sorted by name."""
    names = {project.country: project.country_name for project in child_projects}
    return dict(sorted(names.items(), key=lambda item: item[1]))


def write_data_template(path: Path, country: str):
    """Write data to the template."""
    child_projects = [
        project for project in read_child_projects() if project.country == country
    ] or [ChildProject(EXAMPLE_GEF_CP_ID, country, "", "")]

    workbook = openpyxl.load_workbook(DATA_TEMPLATE_PATH)
    sheet = workbook.worksheets[0]

    # Styles of the cells of the first data row, for every row
    styles = [
        copy(sheet.cell(2, column)._style) for column in range(1, COLUMN_COUNT + 1)
    ]
    sheet.delete_rows(2, sheet.max_row)

    row = 1
    for project in child_projects:
        for indicator in INDICATORS.values():
            for sub_indicator in indicator["sub_indicators"]:
                row += 1
                values = (
                    project.gef_cp_id,
                    project.country,
                    indicator["label"],
                    sub_indicator,
                    None,
                    None,
                )
                for column, (value, style) in enumerate(zip(values, styles), 1):
                    cell = sheet.cell(row, column, value)
                    cell._style = copy(style)

    # Dropdowns of the indicator and sub-indicator columns, on all the rows
    for validation in sheet.data_validations.dataValidation:
        column = str(validation.sqref).split(":")[0].rstrip("0123456789")
        validation.sqref = MultiCellRange(f"{column}2:{column}{row}")
    workbook.save(path)
