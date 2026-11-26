"""Maps of the restoration sites in the report, the polygons of the sites
drawn in the map items of the print layout template."""

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFillSymbol,
    QgsGeometry,
    QgsLayoutItemMap,
    QgsProject,
    QgsRectangle,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
)

from ..styles import SPATIAL_COLOR

# CRS of the sites, and of the map items
SITES_CRS = "EPSG:4326"
MAP_CRS = "EPSG:3857"

# Margin around the sites in a map, a share of their extent
MAP_MARGIN = 0.1

# Smallest extent of a map in degrees
MIN_EXTENT = 0.001


def sites_extent(geometries: list[QgsGeometry]) -> QgsRectangle | None:
    """Extent of the geometries."""
    extent = None
    for geometry in geometries:
        if geometry is None or geometry.isEmpty():
            continue
        if extent is None:
            extent = QgsRectangle(geometry.boundingBox())
        else:
            extent.combineExtentWith(geometry.boundingBox())
    if extent is None:
        return None

    width = max(extent.width(), MIN_EXTENT)
    height = max(extent.height(), MIN_EXTENT)
    margin_x = width * MAP_MARGIN
    margin_y = height * MAP_MARGIN
    center = extent.center()
    return QgsRectangle(
        center.x() - (width / 2) - margin_x,
        center.y() - (height / 2) - margin_y,
        center.x() + (width / 2) + margin_x,
        center.y() + (height / 2) + margin_y,
    )


def _sites_layer(name: str, geometries: list[QgsGeometry]) -> QgsVectorLayer:
    """Memory layer of the polygons of the sites."""
    layer = QgsVectorLayer(f"MultiPolygon?crs={SITES_CRS}", name, "memory")
    features = []
    for geometry in geometries:
        feature = QgsFeature()
        feature.setGeometry(QgsGeometry(geometry))
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    layer.updateExtents()

    # Spatially supported color, half transparent fill
    color = SPATIAL_COLOR.lstrip("#")
    red, green, blue = (int(color[index : index + 2], 16) for index in (0, 2, 4))
    symbol = QgsFillSymbol.createSimple(
        {
            "color": f"{red},{green},{blue},110",
            "outline_color": f"{red},{green},{blue},255",
            "outline_width": "0.4",
        }
    )
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    return layer


def set_site_map(
    project: QgsProject,
    item: QgsLayoutItemMap,
    geometries: list[QgsGeometry],
    extent: QgsRectangle | None,
):
    """Draw the polygons of the sites in the map item."""
    layer = _sites_layer(item.id(), geometries)
    project.addMapLayer(layer, False)
    item.setKeepLayerSet(True)
    item.setLayers([layer])

    map_crs = QgsCoordinateReferenceSystem(MAP_CRS)
    item.setCrs(map_crs)
    if extent is None:
        return
    transform = QgsCoordinateTransform(
        QgsCoordinateReferenceSystem(SITES_CRS), map_crs, project
    )
    item.zoomToExtent(transform.transformBoundingBox(extent))
