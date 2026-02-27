"""
Marshmallow parameter schema for the urban-area GEE script.

Purpose: Calculates urban area expansion and classification using Impervious
    Surface Index (ISI), VIIRS nighttime lights, and JRC surface water.
    Classifies urban zones (urban core, suburban, fringe open space, captured
    open space, rural open/built-up, water) for years 2000-2015.  Includes
    population density from GPW v4.

Usage::

    from params_schema import UrbanAreaParameters

    # Validate and deserialize incoming params dict
    params_obj = UrbanAreaParameters.Schema().load(raw_params)

    # Serialize back to a dict for API transport
    params_dict = UrbanAreaParameters.Schema().dump(params_obj)

Note:
    The total area of all geometries in ``geojsons`` must be <= 35,000 km².
"""

from dataclasses import field
from typing import Optional

from marshmallow import validate
from marshmallow_dataclass import dataclass


@dataclass
class UrbanAreaParameters:
    """Parameters for the urban area classification.

    Attributes:
        isi_thr: Impervious Surface Index threshold for urban detection.
        ntl_thr: VIIRS nighttime light threshold for urban detection.
        wat_thr: JRC surface water occurrence threshold.
        cap_ope: Captured open-space area threshold in hectares.
        pct_suburban: Fraction threshold for suburban classification
            (0.0–1.0, plugin divides the UI percentage by 100).
        pct_urban: Fraction threshold for urban classification (0.0–1.0).
        un_adju: Use UN-adjusted population density when *True*.
        geojsons: JSON-encoded string of area-of-interest geometries
            (total area must be <= 35,000 km²).
        crs: Coordinate reference system as WKT string.
        ENV: Execution environment.
        EXECUTION_ID: Unique execution identifier.
    """

    isi_thr: float = field(metadata={"required": True})
    ntl_thr: float = field(metadata={"required": True})
    wat_thr: float = field(metadata={"required": True})
    cap_ope: float = field(metadata={"required": True})
    pct_suburban: float = field(
        metadata={"required": True, "validate": validate.Range(min=0.0, max=1.0)}
    )
    pct_urban: float = field(
        metadata={"required": True, "validate": validate.Range(min=0.0, max=1.0)}
    )
    un_adju: bool = field(metadata={"required": True})
    geojsons: str = field(metadata={"required": True})
    crs: str = field(metadata={"required": True})
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
