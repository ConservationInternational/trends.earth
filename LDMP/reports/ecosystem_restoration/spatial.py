"""Spatially supported area of the restoration sites, from their polygons."""

import datetime as dt
import glob
import re
import zipfile
from pathlib import Path

from qgis.core import (
    QgsCoordinateTransformContext,
    QgsDistanceArea,
    QgsGeometry,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QDate, QDateTime


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

# Most errors listed by validate_sites
MAX_SITE_ERRORS = 10

LAYER_NAME_FORMAT = "[ISO COUNTRY]_V[YYYYMMDD]"
LAYER_NAME_REGEX = re.compile(r"^([A-Z]{3})_V(\d{8})$")
LAYER_FILE_EXTENSIONS = (".geojson", ".kml", ".shp")
LAYER_CRS = "EPSG:4326"

# Empty Shapefile of the restoration sites, with its QGIS form in the .qml
SPATIAL_TEMPLATE_DIR = Path(__file__).parent / "spatial_template"
# Name of the files of the template, and of its ZIP file
SPATIAL_TEMPLATE_NAME = "XXX_VYYYYMMDD"


def _year(value) -> int | None:
    """Year of a date attribute, None when it is empty or not a date."""
    if isinstance(value, QDateTime):
        value = value.date()
    if isinstance(value, QDate):
        return value.year() if value.isValid() else None
    if isinstance(value, (dt.date, dt.datetime)):
        return value.year
    text = str(value or "").strip()
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None


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


def write_spatial_template(path: Path):
    """Write the files of SPATIAL_TEMPLATE_DIR in a ZIP file."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file in sorted(SPATIAL_TEMPLATE_DIR.iterdir()):
            if file.is_file():
                zip_file.write(file, file.name)


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


def check_layer_file(layer: QgsVectorLayer) -> list[str]:
    """Check layer based on extensions, not a file or not using EPSG:4326."""
    errors = []
    path = layer_file(layer.source())
    if not path.is_file():
        errors.append(f"Layer {layer.name()} is not a file.")
    elif path.suffix.lower() not in LAYER_FILE_EXTENSIONS:
        errors.append(
            f"Layer {layer.name()} is not a GeoJSON, KML or Shapefile: {path.name}"
        )
    if layer.crs().authid() != LAYER_CRS:
        errors.append(
            f"Layer {layer.name()} is not in {LAYER_CRS}: "
            f"{layer.crs().authid() or 'no CRS'}"
        )
    return errors


def missing_fields(layer: QgsVectorLayer) -> list[str]:
    """SPATIAL_FIELDS that the layer has not, field names are not case-sensitive."""
    return [name for name in SPATIAL_FIELDS if layer.fields().lookupField(name) < 0]


def validate_sites(layer: QgsVectorLayer) -> list[str]:
    """Errors of the restoration sites, empty when they are valid.

    Every site has a value for REQUIRED_SPATIAL_FIELDS, a date and a unique
    Site_ID. The layer has all SPATIAL_FIELDS, checked with missing_fields.
    """
    errors = []
    site_ids = set()
    for feature in layer.getFeatures():
        site_id = str(feature[SITE_ID_FIELD] or "").strip()
        site = f"Site {site_id}" if site_id else f"Feature {feature.id()}"

        empty = [
            name
            for name in REQUIRED_SPATIAL_FIELDS
            if not str(feature[name] or "").strip()
        ]
        if empty:
            errors.append(f"{site}: no value for {', '.join(empty)}.")
        elif _year(feature[DATE_FIELD]) is None:
            errors.append(f"{site}: {DATE_FIELD} is not a date.")

        if site_id in site_ids:
            errors.append(f"{site}: {SITE_ID_FIELD} is not unique.")
        elif site_id:
            site_ids.add(site_id)

        if len(errors) >= MAX_SITE_ERRORS:
            errors.append("...")
            break
    return errors


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
