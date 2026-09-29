"""
/***************************************************************************
 LDMP - A QGIS plugin
 This plugin supports monitoring and reporting of land degradation to the UNCCD
 and in support of the SDG Land Degradation Neutrality (LDN) target.
                              -------------------
        begin                : 2017-05-23
        git sha              : $Format:%H$
        copyright            : (C) 2017 by Conservation International
        email                : trends.earth@conservation.org
 ***************************************************************************/
"""

import os

from .conf import _load_jsonc

stac_datasets_file = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), "data", "stac_datasets.jsonc"
)
stac_datasets_dir = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), "data", "stac_datasets"
)
STAC_DATASETS = {
    category: {
        collection_id: {
            "collection": _load_jsonc(
                os.path.join(stac_datasets_dir, files["collection"])
            ),
            "items": _load_jsonc(os.path.join(stac_datasets_dir, files["items"])),
            "layers": _load_jsonc(os.path.join(stac_datasets_dir, files["layers"])),
        }
        for collection_id, files in collections.items()
    }
    for category, collections in _load_jsonc(stac_datasets_file).items()
}
