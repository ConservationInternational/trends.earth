"""Spatially supported area of the restoration sites, from their polygons."""

import datetime as dt

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
SUB_INDICATOR_FIELD = "Sub_Indicator"
AREA_TYPE_FIELD = "Area_Type"
ACTIVITY_FIELD = "Activity"
SOURCE_FIELD = "Source"

# Fields with a value for every restoration site
REQUIRED_SPATIAL_FIELDS = (
    GEF_CP_ID_FIELD,
    COUNTRY_FIELD,
    SITE_ID_FIELD,
    DATE_FIELD,
    INDICATOR_FIELD,
    SUB_INDICATOR_FIELD,
)

# Fields of every layer, their values are optional
OPTIONAL_VALUE_SPATIAL_FIELDS = (
    AREA_TYPE_FIELD,
    ACTIVITY_FIELD,
    SOURCE_FIELD,
)

SPATIAL_FIELDS = REQUIRED_SPATIAL_FIELDS + OPTIONAL_VALUE_SPATIAL_FIELDS

# Most errors listed by validate_sites
MAX_SITE_ERRORS = 10


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


def calculate_spatially_supported(layer: QgsVectorLayer) -> list[dict]:
    """Calculate spatially supported area of the restoration sites, from their polygons."""
    geometries: dict[tuple[str, str, int], list[QgsGeometry]] = {}

    # We try to find geometries per sub indicator and year
    for feature in layer.getFeatures():
        indicator = str(feature[INDICATOR_FIELD] or "").strip()
        sub_indicator = str(feature[SUB_INDICATOR_FIELD] or "").strip()
        year = _year(feature[DATE_FIELD])
        geometry = feature.geometry()
        if not sub_indicator or not year or geometry.isEmpty():
            continue
        geometries.setdefault((indicator, sub_indicator, year), []).append(geometry)

    # We union geometries by year and sub indicator
    distance_area = QgsDistanceArea()
    distance_area.setSourceCrs(layer.crs(), QgsCoordinateTransformContext())
    distance_area.setEllipsoid("WGS84")

    areas = []
    for (indicator, sub_indicator, year), polygons in sorted(geometries.items()):
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
