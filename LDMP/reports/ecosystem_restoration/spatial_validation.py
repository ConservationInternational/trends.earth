"""Validation of a spatial input layer of restoration sites."""

import datetime as dt
import re

from osgeo import gdal
from qgis.core import Qgis, QgsFeature, QgsVectorLayer, QgsWkbTypes
from qgis.PyQt.QtCore import QDate, QDateTime

from .spatial import (
    COUNTRY_FIELD,
    DATE_FIELD,
    GEF_CP_ID_FIELD,
    GEF_CP_ID_REGEX,
    LAYER_NAME_REGEX,
    REQUIRED_SPATIAL_FIELDS,
    SITE_ID_FIELD,
    SPATIAL_FIELDS,
    layer_file,
)

LAYER_FILE_EXTENSIONS = (".geojson", ".kml", ".shp")
LAYER_CRS = "EPSG:4326"

# Regex for identifier of a restoration site, [ISO3 Code]_[SiteNumber], e.g. HTI_0023
SITE_ID_FORMAT = "[ISO3 Code]_[SiteNumber]"
SITE_ID_REGEX = re.compile(r"^([A-Z]{3})_\d{4}$")

# Most errors listed by LayerValidation.run
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


class LayerValidation:
    """Validation of a spatial input layer of restoration sites."""

    def __init__(self, layer: QgsVectorLayer):
        self.layer = layer

    def _validate_file(self) -> list[str]:
        """Errors of the file of the layer: not a file,
        not a GeoJSON, KML or Shapefile, or not in EPSG:4326."""
        errors = []
        path = layer_file(self.layer.source())
        if not path.is_file():
            errors.append(f"Layer {self.layer.name()} is not a file.")
        elif path.suffix.lower() not in LAYER_FILE_EXTENSIONS:
            errors.append(
                f"Layer {self.layer.name()} is not a GeoJSON, KML or Shapefile: "
                f"{path.name}"
            )
        if self.layer.crs().authid() != LAYER_CRS:
            errors.append(
                f"Layer {self.layer.name()} is not in {LAYER_CRS}: "
                f"{self.layer.crs().authid() or 'no CRS'}"
            )
        return errors

    def _missing_fields(self) -> list[str]:
        """SPATIAL_FIELDS that the layer has not, field names are not case-sensitive."""
        return [
            name for name in SPATIAL_FIELDS if self.layer.fields().lookupField(name) < 0
        ]

    def _validate_closed_polygon(self) -> dict[int, list[str]]:
        """Errors of the boundary of each site of the layer, by feature id.

        A boundary is closed polygons: the rings of the polygons are closed,
        with 4 points at least, and the polygons are valid, no
        self-intersection or dangling vertex. A site with a valid boundary has
        no errors.
        """
        layer = self.layer
        is_file = layer.providerType() == "ogr" and layer_file(layer.source()).is_file()
        option = "OGR_GEOMETRY_ACCEPT_UNCLOSED_RING"
        previous = gdal.GetThreadLocalConfigOption(option, None)
        if is_file:
            gdal.SetThreadLocalConfigOption(option, "NO")
        try:
            if is_file:
                layer = QgsVectorLayer(layer.source(), layer.name(), "ogr")

            errors = {}
            for feature in layer.getFeatures():
                geometry = feature.geometry()
                if geometry.isNull() or geometry.isEmpty():
                    errors[feature.id()] = [
                        "no boundary, or the boundary is not closed."
                    ]
                    continue
                if geometry.type() != QgsWkbTypes.PolygonGeometry:
                    geometry_type = QgsWkbTypes.geometryDisplayString(geometry.type())
                    errors[feature.id()] = [
                        f"boundary is a {geometry_type}, not a closed polygon."
                    ]
                    continue

                rings = [
                    ring
                    for part in geometry.constParts()
                    for ring in [part.exteriorRing()]
                    + [
                        part.interiorRing(index)
                        for index in range(part.numInteriorRings())
                    ]
                ]
                if any(
                    ring is None or not ring.isClosed() or ring.numPoints() < 4
                    for ring in rings
                ):
                    errors[feature.id()] = ["boundary is not closed."]
                    continue

                invalid = geometry.validateGeometry(Qgis.GeometryValidationEngine.Geos)
                if invalid:
                    errors[feature.id()] = [
                        f"boundary is not valid: {error.what()}" for error in invalid
                    ]
            return errors
        finally:
            if is_file:
                gdal.SetThreadLocalConfigOption(option, previous)

    def _validate_attributes(
        self, feature: QgsFeature, layer_country: str | None
    ) -> list[str]:
        """Errors of the attributes of a site, empty when they are valid.

        The site has a value for REQUIRED_SPATIAL_FIELDS, a date, a GEF_CP_ID
        of five numbers, the country of the layer name and a Site_ID of its
        Country, e.g. HTI_0023.
        """
        empty = [
            name
            for name in REQUIRED_SPATIAL_FIELDS
            if not str(feature[name] or "").strip()
        ]
        if empty:
            return [f"no value for {', '.join(empty)}."]

        errors = []
        if _year(feature[DATE_FIELD]) is None:
            errors.append(f"{DATE_FIELD} is not a date.")
        gef_cp_id = str(feature[GEF_CP_ID_FIELD]).strip()
        if not GEF_CP_ID_REGEX.match(gef_cp_id):
            errors.append(f"{GEF_CP_ID_FIELD} {gef_cp_id} is not five numbers.")

        country = str(feature[COUNTRY_FIELD]).strip()
        if layer_country and country != layer_country:
            errors.append(
                f"{COUNTRY_FIELD} {country} is not {layer_country}, "
                f"the country of layer {self.layer.name()}."
            )
        site_id_match = SITE_ID_REGEX.match(str(feature[SITE_ID_FIELD]).strip())
        if not site_id_match:
            errors.append(f"{SITE_ID_FIELD} is not {SITE_ID_FORMAT}, e.g. HTI_0023.")
        elif site_id_match.group(1) != country:
            errors.append(
                f"{SITE_ID_FIELD} does not start with {COUNTRY_FIELD} {country}."
            )
        return errors

    def run(self) -> list[str]:
        """Run all the validations, returns their errors and empty when the layer is valid."""
        # Check the file of the layer: a GeoJSON, KML or Shapefile in EPSG:4326.
        errors = self._validate_file()
        if errors:
            return errors

        # Check the layer has all SPATIAL_FIELDS.
        missing = self._missing_fields()
        if missing:
            return [f"Layer {self.layer.name()} has no field: {', '.join(missing)}"]

        # Validate closed polygon
        boundary_errors = self._validate_closed_polygon()

        # Validate features
        match = LAYER_NAME_REGEX.match(self.layer.name() or "")
        layer_country = match.group(1) if match else None
        site_ids = set()
        for feature in self.layer.getFeatures():
            site_id = str(feature[SITE_ID_FIELD] or "").strip()
            site = f"Site {site_id}" if site_id else f"Feature {feature.id()}"

            site_errors = self._validate_attributes(feature, layer_country)
            site_errors += boundary_errors.get(feature.id(), [])
            if site_id in site_ids:
                site_errors.append(f"{SITE_ID_FIELD} is not unique.")
            elif site_id:
                site_ids.add(site_id)
            errors.extend(f"{site}: {error}" for error in site_errors)

            if len(errors) >= MAX_SITE_ERRORS:
                errors.append("...")
                break
        return errors
