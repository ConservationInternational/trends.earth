"""
Marshmallow parameter schema for the landpks GEE script.

Purpose: Generates PNG imagery for the LandPKS mobile app at a single point
    location.  Produces four outputs: land trend plot (NDVI + precipitation +
    land cover time series), base image (Landsat 8 RGB), greenness (NDVI mean),
    and greenness trend (NDVI trend).  Results are uploaded to Google Cloud
    Storage.

Usage::

    from params_schema import LandPKSParameters

    # Validate and deserialize incoming params dict
    params_obj = LandPKSParameters.Schema().load(raw_params)

    # Serialize back to a dict for API transport
    params_dict = LandPKSParameters.Schema().dump(params_obj)

Note:
    Unlike most other GEE scripts this one expects a *singular* ``geojson``
    field (a single Point geometry) instead of the plural ``geojsons``.
"""

from dataclasses import field
from typing import Optional

from marshmallow import validate
from marshmallow_dataclass import dataclass


@dataclass
class LandPKSParameters:
    """Parameters for generating LandPKS imagery.

    Attributes:
        year_start: Start year for the analysis.  Must be >= 2001.
        year_end: End year for the analysis.  Must be <= 2022.
        lang: Language code for labels and text output.
        geojson: JSON-encoded string of a *single* GeoJSON Point geometry.
        ENV: Execution environment.
        EXECUTION_ID: Unique execution identifier.
    """

    year_start: int = field(
        metadata={"required": True, "validate": validate.Range(min=2001)}
    )
    year_end: int = field(
        metadata={"required": True, "validate": validate.Range(max=2022)}
    )
    lang: str = field(
        metadata={"required": True, "validate": validate.OneOf(["EN", "ES", "PT"])}
    )
    geojson: str = field(metadata={"required": True})
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
