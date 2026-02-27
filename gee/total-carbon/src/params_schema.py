"""
Marshmallow parameter schema for the total-carbon GEE script.

Purpose: Calculates total carbon stocks (above + below ground biomass)
    for a region.

Usage::

    from params_schema import TotalCarbonParameters

    # Validate and deserialize incoming params dict
    params_obj = TotalCarbonParameters.Schema().load(raw_params)

    # Serialize back to a dict for API transport
    params_dict = TotalCarbonParameters.Schema().dump(params_obj)
"""

from dataclasses import field
from typing import Optional

from marshmallow import validate
from marshmallow_dataclass import dataclass


@dataclass
class TotalCarbonParameters:
    """Parameters for the total carbon stocks calculation.

    Attributes:
        fc_threshold: Forest-cover threshold percentage (0–100).
        year_initial: Start year.
        year_final: End year.
        method: Calculation method — ``"ipcc"`` or ``"mokany"``.
        biomass_data: Biomass data source — ``"woodshole"``,
            ``"geocarbon"``, or ``"custom"``.
        geojsons: JSON-encoded string of area-of-interest geometries.
        crs: Coordinate reference system as WKT string.
        ENV: Execution environment.
        EXECUTION_ID: Unique execution identifier.
    """

    fc_threshold: int = field(
        metadata={"required": True, "validate": validate.Range(min=0, max=100)}
    )
    year_initial: int = field(metadata={"required": True})
    year_final: int = field(metadata={"required": True})
    method: str = field(
        metadata={"required": True, "validate": validate.OneOf(["ipcc", "mokany"])}
    )
    biomass_data: str = field(
        metadata={
            "required": True,
            "validate": validate.OneOf(["woodshole", "geocarbon", "custom"]),
        }
    )
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
