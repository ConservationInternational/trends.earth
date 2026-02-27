"""
Marshmallow parameter schema for the time-series GEE script.

Purpose: Calculates zonal statistics for vegetation productivity (NDVI) time
    series over a region, returning mean/min/max/mode/stddev by year.
    Returns JSON time-series tables (not rasters).

Usage::

    from params_schema import TimeSeriesParameters

    # Validate and deserialize incoming params dict
    params_obj = TimeSeriesParameters.Schema().load(raw_params)

    # Serialize back to a dict for API transport
    params_dict = TimeSeriesParameters.Schema().dump(params_obj)

Note:
    Only the *first* geometry in ``geojsons`` is used for the calculation.
"""

from dataclasses import field
from typing import Optional

from marshmallow import validate
from marshmallow_dataclass import dataclass


@dataclass
class TimeSeriesParameters:
    """Parameters for the NDVI time-series zonal statistics calculation.

    Attributes:
        year_initial: Start year.
        year_final: End year.
        geojsons: JSON-encoded string of area-of-interest geometries.
            Only the first geometry is used.
        ndvi_gee_dataset: GEE asset path for NDVI data.
        climate_gee_dataset: GEE asset path for climate data used in
            climate-adjusted trajectory methods.
        trajectory_method: Name of the trajectory calculation method
            (e.g. ``"ndvi_trend"``).
        ENV: Execution environment.
        EXECUTION_ID: Unique execution identifier.
    """

    year_initial: int = field(metadata={"required": True})
    year_final: int = field(metadata={"required": True})
    geojsons: str = field(metadata={"required": True})
    ndvi_gee_dataset: str = field(metadata={"required": True})
    climate_gee_dataset: str = field(metadata={"required": True})
    trajectory_method: str = field(metadata={"required": True})
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
