"""Attributes XLSX of a spatial input file, joined with its polygons."""

import datetime as dt
from pathlib import Path

import openpyxl
from osgeo import gdal
from qgis.core import QgsFeature, QgsField, QgsFields, QgsVectorLayer, QgsWkbTypes
from qgis.PyQt.QtCore import QMetaType

from .spatial import (
    AREA_TYPE_FIELD,
    COUNTRY_FIELD,
    DATE_FIELD,
    EXAMPLE_AREA_TYPE,
    EXAMPLE_INDICATOR,
    EXAMPLE_SUB_INDICATOR,
    GEF_CP_ID_FIELD,
    INDICATOR_FIELD,
    KML_NAME_FIELD,
    REQUIRED_SPATIAL_FIELDS,
    SITE_ID_FIELD,
    SPATIAL_FIELDS,
    SPATIAL_FILE_PROPERTY,
    SUB_INDICATOR_FIELD,
    example_sites,
    layer_file,
)

# Attributes XLSX of a spatial input file, of the same name in the same
# folder, its sites are joined by the Name of the polygons and their Site_ID
ATTRIBUTES_FILE_EXTENSION = ".xlsx"
# Most errors listed when the polygons and the attributes XLSX do not match
MAX_ATTRIBUTE_ERRORS = 10


def attributes_file(path: str) -> Path | None:
    """Attribute file, which is same with the layer path."""
    xlsx = layer_file(path).with_suffix(ATTRIBUTES_FILE_EXTENSION)
    return xlsx if xlsx.is_file() else None


def write_attributes_template(path: Path, country: str, date: dt.date):
    """Write the attributes XLSX template, the columns of SPATIAL_FIELDS and
    the example sites of example_sites, of the polygons named by their
    Site_ID, e.g. {country}_0001."""
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Attributes"
    sheet.append(list(SPATIAL_FIELDS))
    for site_id, gef_cp_id, _ in example_sites(country):
        example = {
            GEF_CP_ID_FIELD: gef_cp_id,
            COUNTRY_FIELD: country,
            SITE_ID_FIELD: site_id,
            DATE_FIELD: date,
            INDICATOR_FIELD: EXAMPLE_INDICATOR,
            SUB_INDICATOR_FIELD: EXAMPLE_SUB_INDICATOR,
            AREA_TYPE_FIELD: EXAMPLE_AREA_TYPE,
        }
        sheet.append([example.get(name) for name in SPATIAL_FIELDS])

    for index, name in enumerate(SPATIAL_FIELDS, start=1):
        column = sheet.cell(1, index).column_letter
        sheet.column_dimensions[column].width = (
            max(len(name), len(str(example.get(name) or "")), 12) + 2
        )
        # Columns of texts, GEF_CP_ID keeps its leading zeros, and of dates
        number_format = "yyyy-mm-dd" if name == DATE_FIELD else "@"
        for row in range(2, 1001):
            sheet.cell(row, index).number_format = number_format
    sheet.freeze_panes = "A2"
    workbook.save(path)


def _attribute_text(value) -> str:
    """Text of a cell of the attributes XLSX, a date as YYYY_MM_DD."""
    if value is None:
        return ""
    if isinstance(value, (dt.date, dt.datetime)):
        return value.strftime("%Y_%m_%d")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _read_attributes(xlsx: Path) -> tuple[dict[str, dict], list[str]]:
    """Read attributes from xlsx, by Site_ID, and the errors of its rows.

    Raises ValueError when the XLSX has not the REQUIRED_SPATIAL_FIELDS columns.
    """
    workbook = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    try:
        rows = workbook.worksheets[0].iter_rows(values_only=True)
        columns = [_attribute_text(value) for value in next(rows, ())]
        missing = [name for name in REQUIRED_SPATIAL_FIELDS if name not in columns]
        if missing:
            raise ValueError(f"{xlsx.name} has no column: {', '.join(missing)}")

        attributes, errors = {}, []
        # Row 1 of the XLSX is the header
        for number, row in enumerate(rows, start=2):
            values = dict(zip(columns, [_attribute_text(value) for value in row]))
            if not any(values.values()):
                continue
            site_id = values.get(SITE_ID_FIELD, "")
            if not site_id:
                errors.append(f"{xlsx.name} row {number}: no {SITE_ID_FIELD}.")
            elif site_id in attributes:
                errors.append(
                    f"{xlsx.name} row {number}: {SITE_ID_FIELD} {site_id} is not unique."
                )
            else:
                attributes[site_id] = values
        return attributes, errors
    finally:
        workbook.close()


def join_attributes(layer: QgsVectorLayer, path: str, xlsx: Path) -> QgsVectorLayer:
    """Join attributes to the layer."""
    errors = []
    name_index = layer.fields().lookupField(KML_NAME_FIELD)
    if name_index < 0:
        errors.append(
            f"Layer {layer.name()} has no field {KML_NAME_FIELD}, the "
            f"{SITE_ID_FIELD} of the polygons in {xlsx.name}."
        )
    try:
        attributes, row_errors = _read_attributes(xlsx)
    except ValueError as error:
        errors.append(str(error))
    if errors:
        raise ValueError("\n".join(errors))

    # Errors of the rows of the XLSX, then of the polygons
    errors = row_errors

    # Polygons read as in LayerValidation, a ring not closed is no boundary
    option = "OGR_GEOMETRY_ACCEPT_UNCLOSED_RING"
    previous = gdal.GetThreadLocalConfigOption(option, None)
    gdal.SetThreadLocalConfigOption(option, "NO")
    try:
        source_layer = QgsVectorLayer(layer.source(), layer.name(), "ogr")
        source_features = list(source_layer.getFeatures())
    finally:
        gdal.SetThreadLocalConfigOption(option, previous)

    fields = QgsFields()
    for field_name in (KML_NAME_FIELD, *SPATIAL_FIELDS):
        fields.append(QgsField(field_name, QMetaType.Type.QString, "String"))

    features, names = [], set()
    for source_feature in source_features:
        name = str(source_feature[name_index] or "").strip()
        polygon = f"Polygon {name}" if name else f"Feature {source_feature.id()}"
        if not name:
            errors.append(f"{polygon}: no {KML_NAME_FIELD}.")
        elif name in names:
            errors.append(f"{polygon}: {KML_NAME_FIELD} is not unique.")
        elif name not in attributes:
            errors.append(f"{polygon}: no {SITE_ID_FIELD} {name} in {xlsx.name}.")
        else:
            names.add(name)
            feature = QgsFeature(fields)
            feature[KML_NAME_FIELD] = name
            for field_name in SPATIAL_FIELDS:
                feature[field_name] = attributes[name].get(field_name) or None
            feature.setGeometry(source_feature.geometry())
            features.append(feature)
    errors += [
        f"Site {site_id} of {xlsx.name}: no polygon of {KML_NAME_FIELD} {site_id}."
        for site_id in attributes
        if site_id not in names
    ]
    if errors:
        if len(errors) > MAX_ATTRIBUTE_ERRORS:
            errors = errors[:MAX_ATTRIBUTE_ERRORS] + ["..."]
        raise ValueError(
            f"Spatial input file {path} and its attributes {xlsx.name} do not "
            "match:\n" + "\n".join(errors)
        )

    geometry_type = QgsWkbTypes.displayString(source_layer.wkbType())
    joined = QgsVectorLayer(
        f"{geometry_type}?crs={source_layer.crs().authid()}", layer.name(), "memory"
    )
    joined.setCrs(source_layer.crs())
    joined.dataProvider().addAttributes(fields.toList())
    joined.updateFields()
    joined.dataProvider().addFeatures(features)
    joined.updateExtents()
    joined.setCustomProperty(SPATIAL_FILE_PROPERTY, str(layer_file(path)))
    return joined
