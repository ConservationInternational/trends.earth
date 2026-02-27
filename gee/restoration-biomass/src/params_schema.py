"""
Marshmallow parameter schema for the restoration-biomass GEE script.

Purpose: Calculates potential carbon gains from ecosystem restoration.
    Estimates CO2 sequestration for different restoration interventions
    (natural regeneration, agroforestry, various plantations for terrestrial;
    mangrove shrub/tree for coastal) using Winrock carbon sequestration
    coefficients.

Usage::

    from params_schema import RestorationBiomassParameters

    # Validate and deserialize incoming params dict
    params_obj = RestorationBiomassParameters.Schema().load(raw_params)

    # Serialize back to a dict for API transport
    params_dict = RestorationBiomassParameters.Schema().dump(params_obj)
"""

from dataclasses import field
from typing import Optional

from marshmallow import validate
from marshmallow_dataclass import dataclass


@dataclass
class RestorationBiomassParameters:
    """Parameters for the restoration biomass calculation.

    Attributes:
        rest_type: Restoration type — ``"terrestrial"`` or ``"coastal"``.
        length_yr: Number of years for the restoration projection.
        geojsons: JSON-encoded string of area-of-interest geometries.
        crs: Coordinate reference system as WKT string.
        ENV: Execution environment.
        EXECUTION_ID: Unique execution identifier.
    """

    rest_type: str = field(
        metadata={
            "required": True,
            "validate": validate.OneOf(["terrestrial", "coastal"]),
        }
    )
    length_yr: int = field(
        metadata={"required": True, "validate": validate.Range(min=1)}
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
