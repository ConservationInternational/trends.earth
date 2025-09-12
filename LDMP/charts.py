import json

from osgeo import ogr
from qgis.utils import qgsfunction
from te_algorithms.gdal.land_deg.land_deg_stats import get_stats_for_geom

from .logger import log


@qgsfunction(args="auto", group="Trends.Earth", usesgeometry=True)
def calculate_error_recode_stats(band_datas, feature, parent, context):
    log("calculating error recode stats")
    band_datas = json.loads(band_datas)
    ogr_geom = ogr.CreateGeometryFromWkt(feature.geometry().asWkt())

    stats = {}
    for band in band_datas:
        band_info = [{"name": band["name"], "index": band["index"]}]
        band_stats = get_stats_for_geom(
            band["path"], band_info, ogr_geom, nodata_value=-32768
        )

        # Extract the single band's stats (since we only passed one band)
        stats[band["out_name"]] = band_stats[band["name"]]

    return json.dumps(stats)
