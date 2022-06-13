import numpy
from osgeo import gdal
from osgeo import ogr
from processing.tools import raster
from qgis.core import QgsGeometry
from qgis.core import QgsRectangle
from qgis.utils import qgsfunction

from .logger import log
from te_algorithms.gdal.land_deg.land_deg_stats import get_stats_for_geom

def recode_deg_soc(soc):
    out = soc.copy()
    out[(soc >= -101) & (soc <= -10)] = -1
    out[(soc > -10) & (soc < 10)] = 0
    out[soc >= 10] = 1
    return out


@qgsfunction(args='auto', group='Trends.Earth', usesgeometry=True)
def calculate_charts(raster_path, band_name, band, change_type, feature, parent, context):
    ogr_geom = ogr.CreateGeometryFromWkt(feature.geometry().asWkt())
    stats = get_stats_for_geom(raster_path, band_name, band, ogr_geom, change_type)
    return (stats[change_type] / stats['area_ha']) * 100
