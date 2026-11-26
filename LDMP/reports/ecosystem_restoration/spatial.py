"""Spatially supported area of the restoration sites, from their polygons."""

import datetime as dt
import glob
import json
import re
import shutil
from pathlib import Path
from xml.sax.saxutils import (
    escape,  # nosec B406 - only escapes text written to QML, no XML is parsed
)

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
    QgsDistanceArea,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QDate, QDateTime, QMetaType

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

# Date of a site in a text field, YYYY_MM_DD, e.g. 2026_05_26
SITE_DATE_FORMAT = "YYYY_MM_DD"
SITE_DATE_REGEX = re.compile(r"^(\d{4})_(\d{2})_(\d{2})$")

# Accepted files of the spatial input: GeoJSON, KML, KMZ (zipped KML) and
# Shapefile
SPATIAL_FILE_EXTENSIONS = (".geojson", ".kml", ".kmz", ".shp")
SPATIAL_FILE_FILTER = (
    "Vector files (*.geojson *.kml *.kmz *.shp);;"
    "GeoJSON (*.geojson);;"
    "KML (*.kml *.kmz);;"
    "Shapefile (*.shp)"
)

# Files of a layer with several files, e.g. a Shapefile and its .dbf, .shx,
# .prj, etc., with the same name
MULTI_FILE_EXTENSIONS = (".shp",)

# Empty Shapefile of the restoration sites, with its QGIS form in the .qml
SPATIAL_TEMPLATE_DIR = Path(__file__).parent / "spatial_template"

# Formats of the spatial template, with the extension of the saved file, the
# Shapefile template is its .shp and the files next to it
TEMPLATE_FORMATS = {
    "Shapefile": ".shp",
    "GeoJSON": ".geojson",
    "KML": ".kml",
    "KMZ": ".kmz",
}

# Field of the name of a KML placemark, written as its <name>
KML_NAME_FIELD = "Name"

# Custom property of a layer joined with its attributes XLSX, its spatial
# input file
SPATIAL_FILE_PROPERTY = "ecosystem_restoration/spatial_file"

# Child project of the example site of the GeoJSON and KML templates
EXAMPLE_GEF_CP_ID = "99999"
EXAMPLE_INDICATOR = "3. Under restoration"
EXAMPLE_SUB_INDICATOR = "3.2 Forest and forest land"
EXAMPLE_AREA_TYPE = "Example site, delete it"


def layer_date(name: str) -> dt.date | None:
    """Get the layer date from the name."""
    match = LAYER_NAME_REGEX.match(name or "")
    if not match:
        return None
    try:
        return dt.datetime.strptime(match.group(2), "%Y%m%d").date()
    except ValueError:
        return None


def validate_spatial_layer_name(names: list[str]) -> list[str]:
    """Validate spatial layer name."""
    errors = []
    countries = set()
    for name in names:
        if layer_date(name) is None:
            errors.append(f"Layer {name} is not named {LAYER_NAME_FORMAT}.")
            continue
        countries.add(LAYER_NAME_REGEX.match(name).group(1))

    if len(countries) > 1:
        errors.append(
            f"The layers are of more than one country: {', '.join(sorted(countries))}. "
            "A report is for one country."
        )

    return errors


def site_date(value) -> dt.date | None:
    """Date of a site, from its Date attribute: a value of a Date field, or a
    text YYYY_MM_DD, e.g. 2026_05_26."""
    if isinstance(value, QDateTime):
        value = value.date()
    if isinstance(value, QDate):
        return value.toPyDate() if value.isValid() else None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    match = SITE_DATE_REGEX.match(str(value or "").strip())
    if not match:
        return None
    try:
        return dt.date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


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


def write_spatial_template(
    path: Path,
    country: str,
    date: dt.date,
    template_format: str = "Shapefile",
    separate_attributes: bool = False,
):
    """Write the spatial template of the country and the date.

    With separate_attributes, the polygons have only a Name, their Site_ID,
    and their attributes are in an XLSX of the same name.
    """
    if not separate_attributes:
        if template_format == "Shapefile":
            _write_shapefile_template(path, country, date)
        else:
            _write_vector_template(path, country, date, template_format)
        return

    # Imported here, attribute imports spatial
    from .attribute import ATTRIBUTES_FILE_EXTENSION, write_attributes_template

    _write_vector_template(path, country, date, template_format, True)
    write_attributes_template(
        path.with_suffix(ATTRIBUTES_FILE_EXTENSION), country, date
    )


def _write_shapefile_template(path: Path, country: str, date: dt.date):
    """Write the files of SPATIAL_TEMPLATE_DIR next to the .shp path, named as
    the path, e.g. IND_V20261231.shp, .dbf, .shx, .prj, .cpg and .qml."""
    for file in sorted(SPATIAL_TEMPLATE_DIR.iterdir()):
        if not file.is_file():
            continue
        target = path.with_suffix(file.suffix)
        # Update qml with default country and site id
        if file.suffix.lower() == ".qml":
            qml = file.read_text(encoding="utf-8")
            qml = _set_default(qml, COUNTRY_FIELD, country)
            qml = _set_default(qml, SITE_ID_FIELD, f"{country}_")
            target.write_text(qml, encoding="utf-8")
        else:
            shutil.copyfile(file, target)


def _write_vector_template(
    path: Path,
    country: str,
    date: dt.date,
    template_format: str,
    name_only: bool = False,
):
    """Write a GeoJSON, KML or KMZ template, with the fields of the Shapefile
    template, with one example site.

    With name_only, the template has only the Name field, the Site_ID of the
    polygons, its attributes are in an attributes XLSX. It can be a Shapefile
    too.
    """
    is_kml = template_format in ("KML", "KMZ")
    fields = QgsFields()
    if not name_only:
        template = QgsVectorLayer(
            str(next(SPATIAL_TEMPLATE_DIR.glob("*.shp"))), "template", "ogr"
        )
        for field in template.fields():
            if is_kml and field.type() == QMetaType.Type.QDate:
                field = QgsField(field.name(), QMetaType.Type.QString, "String", 10)
            fields.append(field)
    if is_kml or name_only:
        # Name of the placemark, the label of the site in Google Earth
        fields.append(QgsField(KML_NAME_FIELD, QMetaType.Type.QString, "String", 254))

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = {
        "KML": "LIBKML",
        "KMZ": "LIBKML",
        "Shapefile": "ESRI Shapefile",
    }.get(template_format, "GeoJSON")
    options.layerName = layer_name(country, date)
    options.fileEncoding = "UTF-8"
    writer = QgsVectorFileWriter.create(
        str(path),
        fields,
        QgsWkbTypes.Polygon,
        QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsCoordinateTransformContext(),
        options,
    )
    if writer.hasError() != QgsVectorFileWriter.NoError:
        raise OSError(writer.errorMessage())

    # Example site
    feature = QgsFeature(fields)
    if is_kml or name_only:
        feature[KML_NAME_FIELD] = f"{country}_0001"
    if not name_only:
        feature[GEF_CP_ID_FIELD] = EXAMPLE_GEF_CP_ID
        feature[COUNTRY_FIELD] = country
        feature[SITE_ID_FIELD] = f"{country}_0001"
        feature[DATE_FIELD] = (
            date.strftime("%Y_%m_%d")
            if is_kml
            else QDate(date.year, date.month, date.day)
        )
        feature[INDICATOR_FIELD] = EXAMPLE_INDICATOR
        feature[SUB_INDICATOR_FIELD] = EXAMPLE_SUB_INDICATOR
        feature[AREA_TYPE_FIELD] = EXAMPLE_AREA_TYPE
    feature.setGeometry(
        QgsGeometry.fromWkt("POLYGON((0 0,0.01 0,0.01 0.01,0 0.01,0 0))")
    )
    writer.addFeature(feature)
    del writer


def open_spatial_file(path: str) -> QgsVectorLayer:
    """Open a spatial input file."""
    name = Path(path).stem
    layer = QgsVectorLayer(path, name, "ogr")
    if not layer.isValid():
        raise ValueError(f"Spatial input file {path} cannot be opened.")
    layers = layer.dataProvider().subLayers()
    if len(layers) > 1:
        raise ValueError(
            f"Spatial input file {path} has more than one layer, "
            f"it has {len(layers)} layers."
        )

    # Imported here, attribute imports spatial
    from .attribute import attributes_file, join_attributes

    xlsx = attributes_file(path)
    if xlsx is None:
        return layer
    return join_attributes(layer, path, xlsx)


def spatial_file(layer: QgsVectorLayer) -> Path:
    """Spatial input file of a layer opened by open_spatial_file."""
    return layer_file(layer.customProperty(SPATIAL_FILE_PROPERTY) or layer.source())


def layer_file(source: str) -> Path:
    """File of a layer source, without its options."""
    return Path(str(source or "").split("|")[0])


def layer_files(source: str) -> list[Path]:
    """Files of a layer source, a Shapefile has its .dbf, .shx, .prj, etc. too,
    and the attributes XLSX of the same name too."""
    # Imported here, attribute imports spatial
    from .attribute import ATTRIBUTES_FILE_EXTENSION, attributes_file

    path = layer_file(source)
    files = [path]
    if path.suffix.lower() in MULTI_FILE_EXTENSIONS:
        files = sorted(
            file
            for file in path.parent.glob(f"{glob.escape(path.stem)}.*")
            if file.is_file() and file.suffix.lower() != ATTRIBUTES_FILE_EXTENSION
        )
    xlsx = attributes_file(str(path))
    return files + [xlsx] if xlsx else files


def _distance_area() -> QgsDistanceArea:
    """Area of EPSG:4326 geometries on the WGS84 ellipsoid."""
    distance_area = QgsDistanceArea()
    distance_area.setSourceCrs(
        QgsCoordinateReferenceSystem("EPSG:4326"), QgsCoordinateTransformContext()
    )
    distance_area.setEllipsoid("WGS84")
    return distance_area


def read_sites_yearly(
    layers: list[QgsVectorLayer],
    aoi: QgsGeometry | None = None,
) -> dict[tuple[str, int], list[dict]]:
    """Restoration sites of the validated layers, by Indicator and year of
    their Date, with their area in hectares.

    With an AOI, in EPSG:4326, only the sites that intersect the AOI, with
    the area of their part in the AOI. Their geometry is not changed, a site
    touching the AOI only on its boundary is not in the AOI.
    """
    distance_area = _distance_area()
    if aoi is not None:
        aoi_engine = QgsGeometry.createGeometryEngine(aoi.constGet())
        aoi_engine.prepareGeometry()
        aoi_bbox = aoi.boundingBox()

    site_found: set[tuple[str, int]] = set()

    sites: dict[tuple[str, int], list[dict]] = {}
    for layer in sorted(layers, key=lambda layer: layer.name(), reverse=True):
        for feature in layer.getFeatures():
            site_id = str(feature[SITE_ID_FIELD] or "").strip()
            date = site_date(feature[DATE_FIELD])
            if not site_id or date is None or (site_id, date.year) in site_found:
                continue
            site_found.add((site_id, date.year))

            # The latest record of the site in the year, also when it is not
            # in the AOI
            geometry = feature.geometry()
            if aoi is None:
                area = distance_area.measureArea(geometry) / 10000
            elif aoi_bbox.intersects(geometry.boundingBox()) and aoi_engine.intersects(
                geometry.constGet()
            ):
                # Area of the part of the site in the AOI
                part = QgsGeometry(aoi_engine.intersection(geometry.constGet()))
                area = distance_area.measureArea(part) / 10000
            else:
                continue
            if area <= 0:
                continue

            indicator = str(feature[INDICATOR_FIELD] or "").strip()
            sites.setdefault((indicator, date.year), []).append(
                {
                    "site_id": site_id,
                    "layer": layer.name(),
                    "date": date,
                    "gef_cp_id": str(feature[GEF_CP_ID_FIELD] or "").strip(),
                    "sub_indicator": str(feature[SUB_INDICATOR_FIELD] or "").strip(),
                    "geometry": geometry,
                    "area": area,
                }
            )
    return sites


def latest_file(paths: list[str]) -> str | None:
    """Spatial input file of the latest date of its name."""
    dated = [(date, path) for path in paths if (date := layer_date(Path(path).stem))]
    return max(dated)[1] if dated else None


def read_site_ids(
    layers: list[QgsVectorLayer],
    gef_cp_id: str | None = None,
    country: str | None = None,
) -> dict[str, list[str]]:
    """Read site ids from layers."""
    names = [GEF_CP_ID_FIELD, SITE_ID_FIELD, INDICATOR_FIELD]
    site_ids: dict[str, set[str]] = {}
    for layer in layers:
        match = LAYER_NAME_REGEX.match(layer.name() or "")
        if country and (not match or match.group(1) != country):
            continue
        if any(layer.fields().lookupField(name) < 0 for name in names):
            continue
        request = QgsFeatureRequest()
        request.setFlags(Qgis.FeatureRequestFlag.NoGeometry)
        request.setSubsetOfAttributes(names, layer.fields())
        for feature in layer.getFeatures(request):
            site_id = str(feature[SITE_ID_FIELD] or "").strip()
            if not site_id:
                continue
            if gef_cp_id and str(feature[GEF_CP_ID_FIELD] or "").strip() != gef_cp_id:
                continue
            indicator = str(feature[INDICATOR_FIELD] or "").strip()
            site_ids.setdefault(indicator, set()).add(site_id)
    return {indicator: sorted(ids) for indicator, ids in site_ids.items()}


def site_country(site: dict) -> str:
    """Country of a site of read_sites_yearly."""
    return LAYER_NAME_REGEX.match(site["layer"]).group(1)


def in_scope(site: dict, gef_cp_id: str | None, country: str | None) -> bool:
    """The condition of filtering site."""
    return (not gef_cp_id or site["gef_cp_id"] == gef_cp_id) and (
        not country or site_country(site) == country
    )


def write_validated_sites(
    sites: dict[tuple[str, int], list[dict]],
    output_dir: Path,
    reporting_period: tuple[int, int],
    gef_cp_id: str | None = None,
    country: str | None = None,
) -> list[Path]:
    """Write the sites used by the report, one GeoJSON per year, e.g.
    2025.geojson, returns the paths of the GeoJSON."""
    features_by_year: dict[int, list[dict]] = {}
    for (indicator, year), group in sorted(sites.items(), key=lambda item: item[0]):
        if not reporting_period[0] <= year <= reporting_period[1]:
            continue
        for site in group:
            if not in_scope(site, gef_cp_id, country):
                continue
            features_by_year.setdefault(year, []).append(
                {
                    "type": "Feature",
                    "properties": {
                        GEF_CP_ID_FIELD: site["gef_cp_id"],
                        COUNTRY_FIELD: site_country(site),
                        SITE_ID_FIELD: site["site_id"],
                        INDICATOR_FIELD: indicator,
                        SUB_INDICATOR_FIELD: site["sub_indicator"],
                        DATE_FIELD: site["date"].isoformat(),
                        "Area_ha": site["area"],
                        "Layer": site["layer"],
                    },
                    "geometry": json.loads(site["geometry"].asJson()),
                }
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for year, features in sorted(features_by_year.items()):
        path = output_dir / f"{year}.geojson"
        features.sort(key=lambda feature: feature["properties"][SITE_ID_FIELD])
        collection = {
            "type": "FeatureCollection",
            "name": str(year),
            "crs": {
                "type": "name",
                "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
            },
            "features": features,
        }
        path.write_text(json.dumps(collection))
        paths.append(path)
    return paths


def calculate_spatially_supported(
    sites: dict[tuple[str, int], list[dict]],
    gef_cp_id: str | None = None,
    country: str | None = None,
) -> list[dict]:
    """Calculate spatially supported area of the restoration sites by
    sub-indicator and year, the year of the Date of the sites.

    Only the sites of the child project gef_cp_id and of the country, any
    child project or country when it is None.
    """
    areas: dict[tuple[str, str, int], float] = {}
    for (indicator, year), group in sites.items():
        for site in group:
            if not in_scope(site, gef_cp_id, country):
                continue
            key = (indicator, site["sub_indicator"], year)
            areas[key] = areas.get(key, 0) + site["area"]

    return [
        {
            "indicator": indicator,
            "sub_indicator": sub_indicator,
            "year": year,
            "area": area,
        }
        for (indicator, sub_indicator, year), area in sorted(areas.items())
    ]
