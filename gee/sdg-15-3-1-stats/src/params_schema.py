"""
Marshmallow parameter schema for the sdg-15-3-1-stats GEE script.

Purpose: Calculates statistics for SDG 15.3.1 indicators from pre-computed
    raster data stored in S3.  Supports crosstab analysis between periods
    (baseline, report_1, report_2).

Usage::

    from params_schema import SDG1531StatsParameters

    # Validate and deserialize incoming params dict
    params_obj = SDG1531StatsParameters.Schema().load(raw_params)

    # Serialize back to a dict for API transport
    params_dict = SDG1531StatsParameters.Schema().dump(params_obj)

Note:
    This script already had an inline ``SDGStatsParametersSchema`` in its
    ``main.py``.  This file provides the canonical dataclass-based version
    for cross-project consistency.  The inline schema in ``main.py`` can be
    replaced with an import of ``SDG1531StatsParameters`` from here.
"""

from dataclasses import field
from typing import List, Optional, Tuple

from marshmallow import validate, validates_schema
from marshmallow.exceptions import ValidationError
from marshmallow_dataclass import dataclass
from te_schemas.error_recode import ErrorRecodePolygons
from te_schemas.productivity import ProductivityMode

_VALID_PERIODS = ["baseline", "report_1", "report_2"]


@dataclass
class SDG1531StatsParameters:
    """Parameters for the SDG 15.3.1 statistics calculation.

    Attributes:
        polygons: Error-recode polygons (ErrorRecodePolygons) used for the
            statistics calculation.
        iso: ISO 3166-1 alpha-3 country code (exactly 3 characters).
        periods: List of period names to include.
        crosstabs: List of period pairs for crosstab analysis.  Each tuple
            must contain two *different* period names.
        boundary_dataset: Boundary dataset to use — ``"UN"`` or
            ``"NaturalEarth"``.
        productivity_dataset: Productivity mode value from
            ``ProductivityMode``.
        substr_regexs: Additional regex patterns for S3 job matching.
        ENV: Execution environment.
        EXECUTION_ID: Unique execution identifier.
    """

    polygons: ErrorRecodePolygons = field(metadata={"required": True})
    iso: str = field(metadata={"required": True, "validate": validate.Length(equal=3)})
    periods: List[str] = field(
        default_factory=lambda: ["baseline"],
        metadata={
            "validate": lambda items: all(item in _VALID_PERIODS for item in items)
        },
    )
    crosstabs: List[Tuple[str, str]] = field(
        default_factory=list,
    )
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

    class Meta:
        """Marshmallow Meta options."""

        @staticmethod
        @validates_schema
        def validate_crosstabs(data, **kwargs):
            """Ensure each crosstab pair contains different periods."""
            for pair in data.get("crosstabs", []):
                if pair[0] == pair[1]:
                    raise ValidationError(
                        "Crosstab pairs must contain two different periods, "
                        f"got ({pair[0]!r}, {pair[1]!r})."
                    )
