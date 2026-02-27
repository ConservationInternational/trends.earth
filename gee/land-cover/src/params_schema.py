"""
Marshmallow parameter schema for the land-cover GEE script.

Purpose: Calculates the land-cover change indicator between two years using
    ESA CCI land-cover data with custom legend nesting and transition
    degradation matrices.

Usage::

    from params_schema import LandCoverParameters

    # Validate and deserialize incoming params dict
    params_obj = LandCoverParameters.Schema().load(raw_params)

    # Serialize back to a dict for API transport
    params_dict = LandCoverParameters.Schema().dump(params_obj)

Note:
    The ``trans_matrix``, ``legend_nesting_esa_to_custom``, and
    ``legend_nesting_custom_to_ipcc`` fields are deserialized using their
    own te_schemas marshmallow schemas (``LCTransitionDefinitionDeg`` and
    ``LCLegendNesting``).
"""

from dataclasses import field
from typing import Optional

from marshmallow import validate
from marshmallow_dataclass import dataclass
from te_schemas.land_cover import LCLegendNesting, LCTransitionDefinitionDeg


@dataclass
class LandCoverParameters:
    """Parameters for the land-cover change indicator calculation.

    Attributes:
        year_initial: Baseline year for land-cover comparison.
        year_final: Target year for land-cover comparison.
        geojsons: JSON-encoded string of area-of-interest geometries.
        crs: Coordinate reference system as WKT string.
        trans_matrix: Land-cover transition degradation definition, validated
            via ``LCTransitionDefinitionDeg.Schema()``.
        legend_nesting_esa_to_custom: Nesting definition mapping ESA CCI
            classes to the user's custom legend.
        legend_nesting_custom_to_ipcc: Nesting definition mapping the user's
            custom legend classes to IPCC classes.
        ENV: Execution environment.
        EXECUTION_ID: Unique execution identifier.
    """

    year_initial: int = field(metadata={"required": True})
    year_final: int = field(metadata={"required": True})
    geojsons: str = field(metadata={"required": True})
    crs: str = field(metadata={"required": True})
    trans_matrix: LCTransitionDefinitionDeg = field(metadata={"required": True})
    legend_nesting_esa_to_custom: LCLegendNesting = field(metadata={"required": True})
    legend_nesting_custom_to_ipcc: LCLegendNesting = field(metadata={"required": True})
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
