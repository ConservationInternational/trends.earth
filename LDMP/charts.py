import json

import numpy
from osgeo import gdal
from osgeo import ogr
from processing.tools import raster
from qgis.core import QgsGeometry
from qgis.core import QgsRectangle
from qgis.utils import qgsfunction
from te_algorithms.gdal.land_deg.land_deg_stats import get_stats_for_geom

from .logger import log


@qgsfunction(args="auto", group="Trends.Earth", usesgeometry=True)
def calculate_error_recode_stats(band_datas, feature, parent, context):
    log("calculating error recode stats")
    band_datas = json.loads(band_datas)
    ogr_geom = ogr.CreateGeometryFromWkt(feature.geometry().asWkt())

    stats = {
        band["out_name"]: get_stats_for_geom(
            band["path"], band["name"], band["index"], ogr_geom, -32768
        )
        for band in band_datas
    }

    return json.dumps(stats)
