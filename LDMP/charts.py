import numpy
from osgeo import gdal, ogr
from qgis.utils import qgsfunction
from processing.tools import raster

@qgsfunction(args='auto', group='Trends.Earth', usesgeometry=True)
def calculate_charts(file_path, band, value, feature, parent):
    rds = gdal.Open(file_path, gdal.GA_ReadOnly)
    rb = rds.GetRasterBand(band)
    rgt = rds.GetGeoTransform()
    nd = rb.GetNoDataValue()

    mem_drv = ogr.GetDriverByName('Memory')
    driver = gdal.GetDriverByName('MEM')

    geom = feature.geometry()
    bbox = geom.boundingBox()
    xmin = bbox.xMinimum()
    xmax = bbox.xMaximum()
    ymin = bbox.yMinimum()
    ymax = bbox.yMaximum()

    pa = abs(rgt[1] * rgt[5])
    sc, sr = raster.mapToPixel(xmin, ymax, rgt)
    ec, er = raster.mapToPixel(xmax, ymin, rgt)
    w = ec - sc
    h = er - sr

    src_offset = (sc, sr, w, h)
    src_array = rb.ReadAsArray(*src_offset)

    new_gt = ((rgt[0] + (src_offset[0] * rgt[1])), rgt[1], 0.0,
              (rgt[3] + (src_offset[1] * rgt[5])), 0.0, rgt[5])

    mem_ds = mem_drv.CreateDataSource('out')
    mem_layer = mem_ds.CreateLayer('poly', None, ogr.wkbPolygon)
    ft = ogr.Feature(mem_layer.GetLayerDefn())
    ogr_g = ogr.CreateGeometryFromWkt(geom.asWkt())
    ft.SetGeometry(ogr_g)
    mem_layer.CreateFeature(ft)
    ft.Destroy()

    rvds = driver.Create('', src_offset[2], src_offset[3], 1, gdal.GDT_Byte)
    rvds.SetGeoTransform(new_gt)
    gdal.RasterizeLayer(rvds, [1], mem_layer, burn_values=[1])
    rv_array = rvds.ReadAsArray()

    src_array = numpy.nan_to_num(src_array)
    masked = numpy.ma.MaskedArray(src_array,
                                  mask=numpy.logical_or(src_array == nd,
                                                        numpy.logical_not(rv_array)))
    return (numpy.count_nonzero(masked == value) * pa * 100.0) / geom.area()

