"""Spatially supported area of the restoration sites, from their polygons."""

import datetime as dt

from qgis.core import (
    QgsCoordinateTransformContext,
    QgsDistanceArea,
    QgsGeometry,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QDate, QDateTime


INDICATOR_FIELD = "Indicator"
SUB_INDICATOR_FIELD = "Sub_Indicator"
DATE_FIELD = "Date"
REQUIRED_SPATIAL_FIELDS = (INDICATOR_FIELD, SUB_INDICATOR_FIELD, DATE_FIELD)


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
