def download_stac(
    collection_id,
    assets,
    geojsons,
    crs,
    task_name,
):
    print("collection_id:", collection_id)
    print("assets:")
    for key, href in assets.items():
        print(f"  {key}: {href}")
    print("geojsons:", geojsons)
    print("crs:", crs)
    print("task_name:", task_name)
