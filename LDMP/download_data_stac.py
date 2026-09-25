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


def _stac_dataset_item(category, collection_id, stac):
    collection = stac["collection"]
    features = stac["items"]["features"]
    min_x = min(f["bbox"][0] for f in features)
    min_y = min(f["bbox"][1] for f in features)
    max_x = max(f["bbox"][2] for f in features)
    max_y = max(f["bbox"][3] for f in features)
    interval = collection["extent"]["temporal"]["interval"][0]
    start_year = "NA"
    end_year = "NA"
    if interval[0][:4]:
        start_year = interval[0][:4]
    if interval[1][:4]:
        end_year = interval[1][:4]

    if start_year == end_year:
        start_year = "NA"
        end_year = "NA"

    gsd = collection.get("summaries", {}).get("gsd", [])
    assets = {
        key: asset
        for feature in features
        for key, asset in feature["assets"].items()
        if "data" in asset.get("roles", [])
    }
    return {
        "category": category,
        "title": collection.get("title", collection_id),
        "Units": "",
        "Spatial Resolution": f"{gsd[0]} m" if gsd else "",
        "Start year": start_year,
        "End year": end_year,
        "extent_lat": f"{min_y:.3f} - {max_y:.3f}",
        "extent_lon": f"{min_x:.3f} - {max_x:.3f}",
        "Data source": ", ".join(p["name"] for p in collection.get("providers", [])),
        "Source": collection_id,
        "Citation": collection.get("sci:citation", ""),
        "stac_collection": collection_id,
        "assets": {key: asset["href"] for key, asset in assets.items()},
        "layers": {
            layer: {
                key: assets[key].get("title", key) for key in layer_config["assets"]
            }
            for layer, layer_config in stac["layers"].items()
        },
        "styles": {
            key: layer_config["style"]
            for layer_config in stac["layers"].values()
            for key in layer_config["assets"]
        },
    }
