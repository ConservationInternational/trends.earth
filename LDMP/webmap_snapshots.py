"""Prepare local raster snapshots for expiring web-map shares."""

import hashlib
import os
import re
import tempfile
from pathlib import Path

from osgeo import gdal, ogr

from .dataset_export import _read_vrt, _resolve_source, _source_elements
from .webmap_sharing import ShareCancelled, ShareError

_VECTOR_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,119}$")
_FEATURE_ID = "te_snapshot_id"


def _check_local_dependencies(source_path):
    pending = [Path(source_path)]
    seen = set()
    while pending:
        path = pending.pop()
        if not path.is_file():
            raise ShareError("A raster dependency is missing or is not local")
        path = path.resolve()
        if path in seen:
            continue
        seen.add(path)
        if path.suffix.lower() != ".vrt":
            continue
        tree = _read_vrt(path)
        if tree is None:
            raise ShareError("Could not read the raster VRT")
        for element in _source_elements(tree):
            dependency = _resolve_source(path, element)
            if dependency is None:
                raise ShareError("VRT sources must be local files")
            pending.append(dependency)


def export_raster(source_path, destination, band, cancelled=lambda: False):
    """Create a self-contained, single-band COG and return its size and digest."""
    destination = Path(destination)
    if Path(source_path).resolve() == destination.resolve():
        raise ShareError("The snapshot must not overwrite the source raster")
    if destination.exists() or destination.is_symlink():
        raise ShareError("The snapshot destination already exists")
    try:
        return _export_raster(source_path, destination, band, cancelled)
    except (ShareError, OSError, RuntimeError):
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            raise ShareError(
                "Could not remove the incomplete raster snapshot"
            ) from None
        raise


def _export_raster(source_path, destination, band, cancelled):
    if not os.path.isfile(source_path):
        raise ShareError("The raster source is not a local file")
    if type(band) is not int or band < 1:
        raise ShareError("The selected raster band is invalid")
    if gdal.GetDriverByName("COG") is None:
        raise ShareError("This GDAL installation does not support COG export")
    _check_local_dependencies(source_path)

    messages = []

    def error_handler(error_class, error_number, message):
        if error_class >= gdal.CE_Warning:
            messages.append(message)

    def progress(_complete, _message, _data):
        return 0 if cancelled() else 1

    gdal.PushErrorHandler(error_handler)
    try:
        source = gdal.OpenEx(source_path, gdal.OF_RASTER | gdal.OF_READONLY)
        if source is None or band > source.RasterCount:
            raise ShareError("Could not open the selected raster band")
        for dependency in source.GetFileList() or []:
            if not os.path.isfile(dependency):
                raise ShareError("A raster dependency is missing or is not local")
        if not source.GetProjection():
            raise ShareError("The raster must have a coordinate reference system")
        if cancelled():
            raise ShareCancelled("Snapshot creation cancelled")
        options = gdal.TranslateOptions(
            format="COG",
            bandList=[band],
            creationOptions=["COMPRESS=DEFLATE", "OVERVIEW_RESAMPLING=NEAREST"],
            callback=progress,
        )
        try:
            result = gdal.Translate(str(destination), source, options=options)
        except RuntimeError:
            if cancelled():
                raise ShareCancelled("Snapshot creation cancelled") from None
            raise ShareError("Raster conversion failed") from None
        source = None
        if cancelled():
            raise ShareCancelled("Snapshot creation cancelled")
        if result is None or messages:
            raise ShareError("Raster conversion failed or reported a GDAL warning")
        result = None
    finally:
        gdal.PopErrorHandler()

    digest = hashlib.sha256()
    size = 0
    try:
        with open(destination, "rb") as snapshot:
            while True:
                if cancelled():
                    raise ShareCancelled("Snapshot creation cancelled")
                chunk = snapshot.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
    except OSError:
        raise ShareError("Could not read the raster snapshot") from None
    if not size:
        raise ShareError("The raster snapshot is empty")
    return {"size_bytes": size, "sha256": digest.hexdigest()}


def export_vector(
    source_path,
    layer_name,
    destination,
    fields,
    min_zoom,
    max_zoom,
    cancelled=lambda: False,
):
    """Create one PMTiles MVT layer and detect missing features at every zoom."""
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ShareError("The snapshot destination already exists")
    if not os.path.isfile(source_path):
        raise ShareError("The vector source is not a local file")
    if gdal.GetDriverByName("PMTiles") is None:
        raise ShareError("This GDAL installation does not support PMTiles export")
    if not 0 <= min_zoom <= max_zoom <= 22:
        raise ShareError("The vector zoom range is invalid")
    if (
        len(fields) > 255
        or len({field.lower() for field in fields}) != len(fields)
        or any(
            not _VECTOR_IDENTIFIER.fullmatch(field) or field.lower() == _FEATURE_ID
            for field in fields
        )
    ):
        raise ShareError("Select at most 255 uniquely named ASCII identifier fields")

    messages = []

    def errors(level, _number, message):
        if level >= gdal.CE_Warning:
            messages.append(message)

    def progress(_complete, _message, _data):
        return 0 if cancelled() else 1

    try:
        with tempfile.TemporaryDirectory(prefix="te-webmap-") as directory:
            gdal.PushErrorHandler(errors)
            try:
                source = gdal.OpenEx(source_path, gdal.OF_VECTOR | gdal.OF_READONLY)
                if source is None:
                    raise ShareError("Could not open the vector source")
                layer = (
                    source.GetLayerByName(layer_name)
                    if layer_name
                    else source.GetLayer(0)
                )
                if layer is None or layer.GetSpatialRef() is None:
                    raise ShareError("The vector layer or its CRS is unavailable")
                definition = layer.GetLayerDefn()
                indices = [definition.GetFieldIndex(field) for field in fields]
                if any(index < 0 for index in indices):
                    raise ShareError("A selected vector field no longer exists")
                supported = {
                    ogr.OFTInteger,
                    ogr.OFTInteger64,
                    ogr.OFTReal,
                    ogr.OFTString,
                }
                if any(
                    definition.GetFieldDefn(index).GetType() not in supported
                    for index in indices
                ):
                    raise ShareError("A selected vector field has an unsupported type")
                driver = ogr.GetDriverByName("GPKG")
                if driver is None:
                    raise ShareError(
                        "This GDAL installation does not support GeoPackage staging"
                    )
                staging = driver.CreateDataSource(str(Path(directory) / "staging.gpkg"))
                if staging is None:
                    raise ShareError("Could not create the vector staging file")
                target = staging.CreateLayer(
                    "analysis", layer.GetSpatialRef(), layer.GetGeomType()
                )
                if target is None:
                    raise ShareError("Could not create the vector staging layer")
                for index in indices:
                    if target.CreateField(definition.GetFieldDefn(index)) != 0:
                        raise ShareError("Could not copy a selected vector field")
                if (
                    target.CreateField(ogr.FieldDefn(_FEATURE_ID, ogr.OFTInteger64))
                    != 0
                ):
                    raise ShareError("Could not create the vector verification field")
                expected = {}
                for number, feature in enumerate(layer, 1):
                    if cancelled():
                        raise ShareCancelled("Snapshot creation cancelled")
                    if number > 500000:
                        raise ShareError(
                            "Vector layers exceeding 500000 features cannot be verified"
                        )
                    geometry = feature.GetGeometryRef()
                    if geometry is None or geometry.IsEmpty():
                        raise ShareError("The vector contains an empty geometry")
                    copy = ogr.Feature(target.GetLayerDefn())
                    if copy.SetGeometry(geometry) != 0:
                        raise ShareError("Could not copy a vector geometry")
                    attributes = {}
                    for field in fields:
                        if feature.IsFieldSetAndNotNull(field):
                            value = feature.GetField(field)
                            copy.SetField(field, value)
                            attributes[field] = value
                    copy.SetField(_FEATURE_ID, number)
                    if target.CreateFeature(copy) != 0:
                        raise ShareError("Could not copy a vector feature")
                    expected[number] = attributes
                if not expected:
                    raise ShareError("The vector layer has no features")
                target = None
                staging = None
                source = None
                if messages:
                    raise ShareError("Vector staging reported a GDAL warning")
                options = gdal.VectorTranslateOptions(
                    format="PMTiles",
                    datasetCreationOptions=[
                        f"MINZOOM={min_zoom}",
                        f"MAXZOOM={max_zoom}",
                        "SIMPLIFICATION=0",
                        "SIMPLIFICATION_MAX_ZOOM=0",
                    ],
                    callback=progress,
                )
                result = gdal.VectorTranslate(
                    str(destination),
                    str(Path(directory) / "staging.gpkg"),
                    options=options,
                )
                if cancelled():
                    raise ShareCancelled("Snapshot creation cancelled")
                if result is None or messages:
                    raise ShareError(
                        "Vector conversion failed or reported a GDAL warning"
                    )
                result = None
                for zoom in range(min_zoom, max_zoom + 1):
                    try:
                        tiles = gdal.OpenEx(
                            str(destination),
                            gdal.OF_VECTOR | gdal.OF_READONLY,
                            open_options=[f"ZOOM_LEVEL={zoom}"],
                        )
                    except RuntimeError:
                        raise ShareError(
                            f"Could not inspect vector tiles at zoom {zoom}; "
                            "features may have been omitted"
                        ) from None
                    if tiles is None or tiles.GetLayerCount() != 1:
                        raise ShareError(
                            f"Could not inspect vector tiles at zoom {zoom}; "
                            "features may have been omitted"
                        )
                    rendered = set()
                    for count, feature in enumerate(tiles.GetLayer(0), 1):
                        if cancelled():
                            raise ShareCancelled("Snapshot verification cancelled")
                        if count > 2000000:
                            raise ShareError(
                                f"Vector verification exceeds its work limit at zoom {zoom}"
                            )
                        if feature.IsFieldSetAndNotNull(_FEATURE_ID):
                            feature_id = feature.GetField(_FEATURE_ID)
                            if feature_id not in expected:
                                raise ShareError(
                                    "Vector tiles contain an unexpected feature"
                                )
                            for field, value in expected[feature_id].items():
                                if (
                                    not feature.IsFieldSetAndNotNull(field)
                                    or feature.GetField(field) != value
                                ):
                                    raise ShareError(
                                        f"Vector tiling altered an attribute at zoom {zoom}"
                                    )
                            rendered.add(feature_id)
                    tiles = None
                    missing = expected.keys() - rendered
                    if missing:
                        raise ShareError(
                            f"Vector tiling omitted {len(missing)} features at zoom {zoom}; "
                            "choose a higher minimum zoom or a different dataset"
                        )
                if messages:
                    raise ShareError("Vector verification reported a GDAL warning")
            finally:
                gdal.PopErrorHandler()
        return _file_digest(destination, cancelled)
    except (ShareError, OSError, RuntimeError):
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            raise ShareError(
                "Could not remove the incomplete vector snapshot"
            ) from None
        raise


def _file_digest(path, cancelled):
    digest = hashlib.sha256()
    size = 0
    try:
        with open(path, "rb") as snapshot:
            while True:
                if cancelled():
                    raise ShareCancelled("Snapshot creation cancelled")
                chunk = snapshot.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
    except OSError:
        raise ShareError("Could not read the snapshot") from None
    if not size:
        raise ShareError("The snapshot is empty")
    return {"size_bytes": size, "sha256": digest.hexdigest()}
