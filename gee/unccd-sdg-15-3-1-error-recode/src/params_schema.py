"""
Marshmallow parameter schema for the unccd-sdg-15-3-1-error-recode GEE script.

Purpose: Performs error recoding for UNCCD SDG 15.3.1 submissions.  Takes
    pre-computed SDG indicator rasters from S3 and applies polygon-based
    corrections (reclassifying degradation/stable/improved) across baseline
    and reporting periods.  Computes crosstab statistics between baseline
    and recoded reporting periods.

Usage::

    from params_schema import UNCCDErrorRecodeParameters

    # Validate and deserialize incoming params dict
    params_obj = UNCCDErrorRecodeParameters.Schema().load(raw_params)

    # Serialize back to a dict for API transport
    params_dict = UNCCDErrorRecodeParameters.Schema().dump(params_obj)

Note:
    This script has elevated resource requirements (2-4 GB memory,
    0.5-1 CPU) reflecting the computational cost of raster reclassification.
"""

from dataclasses import field
from typing import List, Optional

from marshmallow import validate
from marshmallow_dataclass import dataclass
from te_schemas.error_recode import ErrorRecodePolygons
from te_schemas.productivity import ProductivityMode


@dataclass
class UNCCDErrorRecodeParameters:
    """Parameters for the UNCCD SDG 15.3.1 error recode.

    Attributes:
        error_polygons: Error-recode polygon collection.  Each feature's
            properties must include ``periods_affected`` (list of period
            names), and optionally ``recode_deg_to``, ``recode_stable_to``,
            ``recode_imp_to``.
        iso: ISO 3166-1 alpha-3 country code (exactly 3 characters).
        boundary_dataset: Boundary dataset — ``"UN"`` or ``"NaturalEarth"``.
        productivity_dataset: Productivity mode value from
            ``ProductivityMode``.
        write_tifs: Write output GeoTIFFs to S3.
        include_polygon_geojson: Include the error polygon GeoJSON in the
            result payload.
        substr_regexs: Additional regex patterns for S3 job matching.
        ENV: Execution environment.
        EXECUTION_ID: Unique execution identifier.
    """

    error_polygons: ErrorRecodePolygons = field(metadata={"required": True})
    iso: str = field(metadata={"required": True, "validate": validate.Length(equal=3)})
    boundary_dataset: str = field(
        default="UN",
        metadata={"validate": validate.OneOf(["UN", "NaturalEarth"])},
    )
    productivity_dataset: str = field(
        default=ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value,
        metadata={
            "validate": validate.OneOf([mode.value for mode in ProductivityMode])
        },
    )
    write_tifs: bool = field(
        default=False,
    )
    include_polygon_geojson: bool = field(
        default=False,
    )
    substr_regexs: List[str] = field(
        default_factory=list,
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
