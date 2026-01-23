"""
Utility functions for working with SDG 15.3.1 GeoJSON files.

This module provides functions to load polygon GeoJSON files and create
parameter dictionaries for submitting both error recode and statistics
calculation jobs to the trends.earth API.
"""

import json
from pathlib import Path


def load_error_polygons_from_geojson(geojson_path):
    """
    Load error polygons from a GeoJSON file.

    Parameters:
    -----------
    geojson_path : str or Path
        Path to the GeoJSON file containing error polygons

    Returns:
    --------
    dict : Error polygons data structure suitable for the API

    Raises:
    -------
    FileNotFoundError : If the GeoJSON file doesn't exist
    ValueError : If the GeoJSON structure is invalid
    """
    geojson_path = Path(geojson_path)

    if not geojson_path.exists():
        raise FileNotFoundError(f"GeoJSON file not found: {geojson_path}")

    with open(geojson_path, "r", encoding="utf-8") as f:
        error_polygons = json.load(f)

    # Validate basic structure
    if error_polygons.get("type") != "FeatureCollection":
        raise ValueError("GeoJSON must be a FeatureCollection")

    if not error_polygons.get("features"):
        raise ValueError("GeoJSON must contain features")

    return error_polygons


def create_error_recode_params(
    iso_code,
    geojson_path,
    boundary_dataset="UN",
    write_tifs=True,
    include_polygon_geojson=False,
):
    """
    Create parameters dictionary for SDG 15.3.1 error recode job.

    Parameters:
    -----------
    iso_code : str
        ISO 3166-1 alpha-3 country code (e.g., "ATG", "KEN", "TKM", "COL")
    geojson_path : str or Path
        Path to the GeoJSON file containing error polygons
    boundary_dataset : str, optional
        Administrative boundary dataset to use (default: "UN")
    write_tifs : bool, optional
        Whether to write output as GeoTIFF files (default: True)
    include_polygon_geojson : bool, optional
        Whether to include the original error polygons GeoJSON as a
        VectorResults in the output (default: False). When True, the
        algorithm returns both RasterResults and VectorResults.

    Returns:
    --------
    dict : Parameters dictionary ready for API submission

    Raises:
    -------
    FileNotFoundError : If the GeoJSON file doesn't exist
    ValueError : If the GeoJSON structure is invalid
    """
    # Load error polygons from GeoJSON file
    error_polygons = load_error_polygons_from_geojson(geojson_path)

    # Create parameters dictionary
    params = {
        "iso": iso_code.upper(),
        "boundary_dataset": boundary_dataset,
        "write_tifs": write_tifs,
        "include_polygon_geojson": include_polygon_geojson,
        "error_polygons": error_polygons,
    }

    return params


def create_sdg_stats_params(
    iso_code,
    geojson_path,
    boundary_dataset="UN",
    periods=["baseline", "report_1", "report_2"],
    crosstabs=[["baseline", "report_2"]],
):
    """
    Create parameters dictionary for SDG 15.3.1 statistics calculation job.

    Parameters:
    -----------
    iso_code : str
        ISO 3166-1 alpha-3 country code (e.g., "ATG", "KEN", "TKM", "COL")
    geojson_path : str or Path
        Path to the GeoJSON file containing polygons for statistics calculation
    boundary_dataset : str, optional
        Administrative boundary dataset to use (default: "UN")
    periods : list, optional
        List of periods to calculate statistics for
        (default: ["baseline", "report_1", "report_2"])
    crosstabs : list, optional
        List of period pairs for crosstab analysis
        (default: [["baseline", "report_2"]])

    Returns:
    --------
    dict : Parameters dictionary ready for API submission

    Raises:
    -------
    FileNotFoundError : If the GeoJSON file doesn't exist
    ValueError : If the GeoJSON structure is invalid
    """

    # Load polygons from GeoJSON file (reuse existing function)
    polygons_data = load_error_polygons_from_geojson(geojson_path)

    # Create parameters dictionary for stats job
    params = {
        "iso": iso_code.upper(),
        "periods": periods,
        "crosstabs": crosstabs,
        "boundary_dataset": boundary_dataset,
        "polygons": polygons_data,
    }

    return params
