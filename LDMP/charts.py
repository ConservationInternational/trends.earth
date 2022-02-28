from osgeo import gdal
from qgis.core import QgsGeometry, QgsRectangle
from qgis.utils import qgsfunction
from processing.tools import raster

@qgsfunction(args='auto', group='Trends.Earth', usesgeometry=True)
def calculate_charts(file_path, band, value, feature, parent, context):
    rds = gdal.Open(file_path, gdal.GA_ReadOnly)
    rb = rds.GetRasterBand(band)
    rgt = rds.GetGeoTransform()

    geom = feature.geometry()
    bbox = geom.boundingBox()
    xmin = bbox.xMinimum()
    xmax = bbox.xMaximum()
    ymin = bbox.yMinimum()
    ymax = bbox.yMaximum()

    dx = abs(rgt[1])
    dy = abs(rgt[5])

    sc, sr = raster.mapToPixel(xmin, ymax, rgt)
    ec, er = raster.mapToPixel(xmax, ymin, rgt)
    w = ec - sc
    h = er - sr

    if w == 0: w += 1
    if h == 0: h += 1

    src_offset = (sc, sr, w, h)
    src_array = rb.ReadAsArray(*src_offset)
    new_gt = ((rgt[0] + (src_offset[0] * rgt[1])), rgt[1], 0.0,
              (rgt[3] + (src_offset[1] * rgt[5])), 0.0, rgt[5])

    eng = QgsGeometry.createGeometryEngine(geom.constGet())
    eng.prepareGeometry()

    area = 0
    cy = new_gt[3]
    for c in range(w):
        cx = new_gt[0]
        for r in range(h):
            v = src_array[c, r]
            g = QgsGeometry.fromRect(QgsRectangle(cx, cy - dy, cx + dx, cy))
            if not g.isNull() and eng.intersects(g.constGet()):
                ig = g.intersection(geom)
                a = ig.area()
                if v == value:
                    area += a
            cx += dx
        cy -= dy

    return area * 100.0 / geom.area()
