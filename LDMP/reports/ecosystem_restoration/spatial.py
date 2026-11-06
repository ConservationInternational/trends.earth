"""Spatially supported area of the restoration sites, from their polygons."""

import datetime as dt
import glob
import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from qgis.core import (
    QgsCoordinateTransformContext,
    QgsDistanceArea,
    QgsGeometry,
    QgsVectorLayer,
)

GEF_CP_ID_FIELD = "GEF_CP_ID"
COUNTRY_FIELD = "Country"
SITE_ID_FIELD = "Site_ID"
DATE_FIELD = "Date"
INDICATOR_FIELD = "Indicator"
SUB_INDICATOR_FIELD = "Sub_Indic"
AREA_TYPE_FIELD = "Area_Type"
ACTIVITY_FIELD = "Activity"
SOURCE_FIELD = "Source"

# Required attributes for spatial data
REQUIRED_SPATIAL_FIELDS = (
    GEF_CP_ID_FIELD,
    COUNTRY_FIELD,
    SITE_ID_FIELD,
    DATE_FIELD,
    INDICATOR_FIELD,
    SUB_INDICATOR_FIELD,
)

# Optional attributes for spatial data
OPTIONAL_VALUE_SPATIAL_FIELDS = (
    AREA_TYPE_FIELD,
    ACTIVITY_FIELD,
    SOURCE_FIELD,
)

SPATIAL_FIELDS = REQUIRED_SPATIAL_FIELDS + OPTIONAL_VALUE_SPATIAL_FIELDS

# Regex for GEF identification of a child project [GEF8 Code], five numbers, e.g. 11130
GEF_CP_ID_REGEX = re.compile(r"^\d{5}$")

LAYER_NAME_FORMAT = "[ISO COUNTRY]_V[YYYYMMDD]"
LAYER_NAME_REGEX = re.compile(r"^([A-Z]{3})_V(\d{8})$")

# Empty Shapefile of the restoration sites, with its QGIS form in the .qml
SPATIAL_TEMPLATE_DIR = Path(__file__).parent / "spatial_template"


def layer_date(name: str) -> dt.date | None:
    """Get the layer date from the name."""
    match = LAYER_NAME_REGEX.match(name or "")
    if not match:
        return None
    try:
        return dt.datetime.strptime(match.group(2), "%Y%m%d").date()
    except ValueError:
        return None


def layer_dates(names: list[str]) -> tuple[dict[str, dt.date], list[str]]:
    """Return dates of layer by the names, and return errors found.

    A country (ISO3 of the name) has only one layer per year.
    """
    dates = {}
    errors = []
    names_by_country_year: dict[tuple[str, int], list[str]] = {}
    for name in names:
        date = layer_date(name)
        if date is None:
            errors.append(f"Layer {name} is not named {LAYER_NAME_FORMAT}.")
            continue
        dates[name] = date
        country = LAYER_NAME_REGEX.match(name).group(1)
        names_by_country_year.setdefault((country, date.year), []).append(name)

    for (country, year), year_names in sorted(names_by_country_year.items()):
        if len(year_names) > 1:
            errors.append(
                f"{country} has more than one layer in {year}: {', '.join(year_names)}."
            )

    return dict(sorted(dates.items(), key=lambda item: item[1])), errors


def layer_name(country: str, date: dt.date) -> str:
    """Layer name of the country and the date, e.g. IND_V20261231."""
    return f"{country}_V{date:%Y%m%d}"


def _set_default(qml: str, field: str, value: str) -> str:
    """QML with the default value of the field, a text."""
    expression = escape("'{}'".format(value.replace("'", "''")), {'"': "&quot;"})
    return re.sub(
        rf'<default\b[^>]*\bfield="{field}"[^>]*/>',
        lambda match: re.sub(
            r'\bexpression="[^"]*"', f'expression="{expression}"', match.group(0)
        ),
        qml,
    )


def write_spatial_template(path: Path, country: str, date: dt.date):
    """Write the files of SPATIAL_TEMPLATE_DIR in a ZIP file."""
    name = layer_name(country, date)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file in sorted(SPATIAL_TEMPLATE_DIR.iterdir()):
            if not file.is_file():
                continue
            # Update qml with default country and site id
            if file.suffix.lower() == ".qml":
                qml = file.read_text(encoding="utf-8")
                qml = _set_default(qml, COUNTRY_FIELD, country)
                qml = _set_default(qml, SITE_ID_FIELD, f"{country}_")
                zip_file.writestr(f"{name}{file.suffix}", qml)
            else:
                zip_file.write(file, f"{name}{file.suffix}")


def layer_file(source: str) -> Path:
    """File of a layer source, without its options."""
    return Path(str(source or "").split("|")[0])


def layer_files(source: str) -> list[Path]:
    """Files of a layer source, a Shapefile has its .dbf, .shx, .prj, etc. too."""
    path = layer_file(source)
    if path.suffix.lower() != ".shp":
        return [path]
    return sorted(
        file
        for file in path.parent.glob(f"{glob.escape(path.stem)}.*")
        if file.is_file()
    )


def calculate_spatially_supported(layer: QgsVectorLayer, year: int) -> list[dict]:
    """Calculate spatially supported area of the restoration sites, from their polygons by year"""
    geometries: dict[tuple[str, str], list[QgsGeometry]] = {}

    # We try to find geometries per sub indicator
    for feature in layer.getFeatures():
        indicator = str(feature[INDICATOR_FIELD] or "").strip()
        sub_indicator = str(feature[SUB_INDICATOR_FIELD] or "").strip()
        geometry = feature.geometry()
        if not sub_indicator or geometry.isEmpty():
            continue
        geometries.setdefault((indicator, sub_indicator), []).append(geometry)

    # We union geometries by sub indicator
    distance_area = QgsDistanceArea()
    distance_area.setSourceCrs(layer.crs(), QgsCoordinateTransformContext())
    distance_area.setEllipsoid("WGS84")

    areas = []
    for (indicator, sub_indicator), polygons in sorted(geometries.items()):
        union = QgsGeometry.unaryUnion(polygons)
        areas.append(
            {
                "indicator": indicator,
                "sub_indicator": sub_indicator,
                "year": year,
                "area": distance_area.measureArea(union) / 10000,
            }
        )
    return areas


def read_countries(layer: QgsVectorLayer) -> list[str]:
    """Countries of the restoration sites, sorted, without empty values."""
    countries = {
        str(feature[COUNTRY_FIELD] or "").strip() for feature in layer.getFeatures()
    }
    countries.discard("")
    return sorted(countries)
