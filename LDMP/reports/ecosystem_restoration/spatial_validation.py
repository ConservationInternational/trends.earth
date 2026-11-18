"""Validation of the spatial input layers of restoration sites."""

import datetime as dt
import re

from osgeo import gdal
from qgis.core import (
    Qgis,
    QgsFeature,
    QgsGeometry,
    QgsSpatialIndex,
    QgsVectorLayer,
    QgsWkbTypes,
)

from .spatial import (
    COUNTRY_FIELD,
    DATE_FIELD,
    GEF_CP_ID_FIELD,
    GEF_CP_ID_REGEX,
    INDICATOR_FIELD,
    LAYER_NAME_REGEX,
    REQUIRED_SPATIAL_FIELDS,
    SITE_DATE_FORMAT,
    SITE_ID_FIELD,
    SPATIAL_FIELDS,
    layer_date,
    layer_file,
    site_date,
)

LAYER_CRS = "EPSG:4326"

# Regex for identifier of a restoration site, [ISO3 Code]_[SiteNumber], e.g. HTI_0023
SITE_ID_FORMAT = "[ISO3 Code]_[SiteNumber]"
SITE_ID_REGEX = re.compile(r"^([A-Z]{3})_\d{4}$")

# Most errors listed by LayerValidation.run and validate_spatial_data
MAX_SITE_ERRORS = 10


class LayerValidation:
    """Validation of a spatial input layer of restoration sites."""

    def __init__(self, layer: QgsVectorLayer):
        self.layer = layer

    def _validate_file(self) -> list[str]:
        """Errors of the file of the layer: not a file, or not in EPSG:4326.
        The file can be of any vector format."""
        errors = []
        path = layer_file(self.layer.source())
        if not path.is_file():
            errors.append(f"Layer {self.layer.name()} is not a file.")
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
        self,
        feature: QgsFeature,
        layer_country: str | None,
        layer_version_date: dt.date | None,
    ) -> list[str]:
        """Errors of the attributes of a site, empty when they are valid.

        The site has a value for REQUIRED_SPATIAL_FIELDS, a date not after the
        date of the layer name, a GEF_CP_ID of five numbers, the country of
        the layer name and a Site_ID of its Country, e.g. HTI_0023.
        """
        empty = [
            name
            for name in REQUIRED_SPATIAL_FIELDS
            if not str(feature[name] or "").strip()
        ]
        if empty:
            return [f"no value for {', '.join(empty)}."]

        errors = []
        date = site_date(feature[DATE_FIELD])
        if date is None:
            errors.append(
                f"{DATE_FIELD} is not a date, or a text {SITE_DATE_FORMAT}, "
                "e.g. 2026_05_26."
            )
        elif layer_version_date and date > layer_version_date:
            errors.append(
                f"{DATE_FIELD} {date} is after {layer_version_date}, "
                f"the date of layer {self.layer.name()}."
            )
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
        # Check the file of the layer: a file in EPSG:4326.
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
        layer_version_date = layer_date(self.layer.name())
        site_ids = set()
        for feature in self.layer.getFeatures():
            site_id = str(feature[SITE_ID_FIELD] or "").strip()
            site = f"Site {site_id}" if site_id else f"Feature {feature.id()}"

            site_errors = self._validate_attributes(
                feature, layer_country, layer_version_date
            )
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


def validate_spatial_data(sites: dict[tuple[str, int], list[dict]]) -> list[str]:
    """Validate spatial data, returns the errors and empty when it is valid.

    The sites are from read_sites_yearly, of the layers validated by
    LayerValidation, one record of a site in a year, from any layer.

    Validation conditions:
    - Sites of the same Indicator in the same year do not overlap, also when
      they are from different layers or of different sub-indicators.
    - Sites of different indicators can overlap.
    - Sites of different years can overlap.
    - Two sites overlap when their interiors intersect, a site nested in
      another too.
    - Sites touching only on their boundaries, on an edge or a corner, do not
      overlap.
    """
    errors = []
    for (indicator, year), group in sites.items():
        # Sites of the indicator in the year, with a spatial index
        bbox_index = QgsSpatialIndex()
        for idx, site in enumerate(group):
            # Bounding box of the site, to find the earlier sites in the index
            geometry = site["geometry"]
            bbox = geometry.boundingBox()

            # Prepare engine
            engine = QgsGeometry.createGeometryEngine(geometry.constGet())
            engine.prepareGeometry()

            # Earlier sites with an intersecting bounding box, they overlap when
            # their interiors intersect, not only touch
            for intersect_idx in sorted(bbox_index.intersects(bbox)):
                other_site = group[intersect_idx]
                other = other_site["geometry"].constGet()
                if not engine.intersects(other) or engine.touches(other):
                    continue
                errors.append(
                    f"Site {site['site_id']} ({site['layer']}): boundary overlaps "
                    f"Site {other_site['site_id']} ({other_site['layer']}) of the same "
                    f"{INDICATOR_FIELD} {indicator} in {year}."
                )
                if len(errors) >= MAX_SITE_ERRORS:
                    errors.append("...")
                    return errors

            # Add the site after checking it, so the index has only
            bbox_index.addFeature(idx, bbox)
    return errors
