"""
Marshmallow parameter schema for the download-data GEE script.

Purpose: Downloads a GEE dataset (any asset) for a given area and time range.

Usage::

    from params_schema import DownloadDataParameters

    # Validate and deserialize incoming params dict
    params_obj = DownloadDataParameters.Schema().load(raw_params)

    # Serialize back to a dict for API transport
    params_dict = DownloadDataParameters.Schema().dump(params_obj)
"""

from dataclasses import field
from typing import Any, Dict, Optional

from marshmallow import validate
from marshmallow_dataclass import dataclass


@dataclass
class DownloadDataParameters:
    """Parameters for downloading a GEE dataset.

    Attributes:
        asset: GEE asset path to download (e.g.
            ``"users/geflanddegradation/toolbox_datasets/ndvi_modis_2001_2019"``).
        name: Human-readable name of the dataset.
        geojsons: JSON-encoded string of area-of-interest geometries.  Parsed
            with ``json.loads()`` in the script's ``run()`` function.
        crs: Coordinate reference system as WKT string.
        year_initial: Start year for temporal filtering (optional for
            non-temporal datasets).
        year_final: End year for temporal filtering.
        temporal_resolution: Temporal resolution of the dataset (e.g.
            ``"annual"``, ``"monthly"``).
        ENV: Execution environment.  One of ``"dev"``, ``"staging"``,
            ``"prod"``, or *None*.
        EXECUTION_ID: Unique execution identifier assigned by the platform.
    """

    asset: str = field(metadata={"required": True})
    name: str = field(metadata={"required": True})
    geojsons: str = field(metadata={"required": True})
    crs: str = field(metadata={"required": True})
    year_initial: Optional[int] = field(
        default=None,
    )
    year_final: Optional[int] = field(
        default=None,
    )
    temporal_resolution: Optional[str] = field(
        default=None,
    )
    band_number: Optional[int] = field(
        default=None,
        metadata={
            "validate": validate.Range(min=1),
            "allow_none": True,
        },
    )
    band_name: Optional[str] = field(
        default=None,
    )
    band_metadata: Optional[Dict[str, Any]] = field(
        default=None,
    )
    band_add_to_map: Optional[bool] = field(
        default=None,
    )
    ENV: Optional[str] = field(
        default=None,
        metadata={
            "validate": validate.OneOf(["dev", "staging", "prod"]),
            "allow_none": True,
        },
    )
    EXECUTION_ID: Optional[str] = field(
        default=None,
    )
