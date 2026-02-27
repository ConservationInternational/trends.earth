"""
Marshmallow parameter schema for the soil-organic-carbon GEE script.

Purpose: Calculates the soil organic carbon (SOC) indicator, showing change
    in SOC stocks between two years based on land-cover transitions and IPCC
    stock change factors.

Usage::

    from params_schema import SoilOrganicCarbonParameters

    # Validate and deserialize incoming params dict
    params_obj = SoilOrganicCarbonParameters.Schema().load(raw_params)

    # Serialize back to a dict for API transport
    params_dict = SoilOrganicCarbonParameters.Schema().dump(params_obj)
"""

from dataclasses import field
from typing import Optional, Union

from marshmallow import validate
from marshmallow_dataclass import dataclass
from te_schemas.land_cover import LCLegendNesting


@dataclass
class SoilOrganicCarbonParameters:
    """Parameters for the soil organic carbon calculation.

    Attributes:
        year_initial: Baseline year.
        year_final: Target year.
        fl: IPCC stock change factor (fl).  Can be a float value or the
            string ``"per pixel"`` for spatially-explicit factors.
        geojsons: JSON-encoded string of area-of-interest geometries.
        crs: Coordinate reference system as WKT string.
        legend_nesting_esa_to_custom: Nesting definition mapping ESA CCI
            classes to the user's custom legend.
        legend_nesting_custom_to_ipcc: Nesting definition mapping the
            user's custom legend to IPCC classes.
        download_annual_lc: Include annual land-cover layers in output.
        download_annual_soc: Include annual SOC layers in output.
        ENV: Execution environment.
        EXECUTION_ID: Unique execution identifier.
    """

    year_initial: int = field(metadata={"required": True})
    year_final: int = field(metadata={"required": True})
    fl: Union[float, str] = field(metadata={"required": True})
    geojsons: str = field(metadata={"required": True})
    crs: str = field(metadata={"required": True})
    legend_nesting_esa_to_custom: LCLegendNesting = field(metadata={"required": True})
    legend_nesting_custom_to_ipcc: LCLegendNesting = field(metadata={"required": True})
    download_annual_lc: Optional[bool] = field(
        default=None,
    )
    download_annual_soc: Optional[bool] = field(
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
