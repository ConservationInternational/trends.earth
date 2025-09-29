import hashlib
import json

from osgeo import ogr
from qgis.utils import qgsfunction
from te_algorithms.gdal.land_deg.land_deg_stats import get_stats_for_geom

from .logger import log


def _hash_band(band):
    """Generate a unique hash for a band based on its properties."""
    return hashlib.md5(
        f"{band['name']}_{band['index']}_"
        f"{json.dumps(band.get('metadata', {}), sort_keys=True)}".encode()
    ).hexdigest()


@qgsfunction(args="auto", group="Trends.Earth", usesgeometry=True)
def calculate_error_recode_stats(band_datas, feature, parent, context):
    log("calculating error recode stats")
    band_datas = json.loads(band_datas)
    ogr_geom = ogr.CreateGeometryFromWkt(feature.geometry().asWkt())

    stats = {}
    for band in band_datas:
        # Create bands dictionary with hash key for the new interface
        band_hash = _hash_band(band)
        bands = {
            band_hash: {
                "name": band["name"],
                "index": band["index"],
                "metadata": band.get("metadata", {}),
            }
        }

        band_stats = get_stats_for_geom(
            band["path"], bands, ogr_geom, nodata_value=-32768
        )

        # Extract the single band's stats using the hash key
        stats[band["out_name"]] = band_stats[band_hash]

    return json.dumps(stats)
