"""
Marshmallow parameter schema for the productivity GEE script.

Purpose: Calculates vegetation productivity indicators.  Supports three
    modes: Trends.Earth 5-class LPD (trajectory + performance + state),
    JRC 5-class LPD (pre-calculated), and FAO-WOCAT 5-class LPD.

Each mode has its own parameter class (``TEProductivityParams``,
``JRCProductivityParams``, ``FAOWOCATProductivityParams``) which is passed
as a nested dict under the ``productivity`` key.  The ``mode`` field inside
that dict determines which parameter class applies.

Usage::

    from params_schema import ProductivityParameters

    # Validate and deserialize incoming params dict
    params_obj = ProductivityParameters.Schema().load(raw_params)

    # Serialize back to a dict for API transport
    params_dict = ProductivityParameters.Schema().dump(params_obj)

The three mode classes are also importable on their own for reuse by other
scripts (e.g.  ``sdg-15-3-1-sub-indicators``).
"""

from dataclasses import field
from typing import Optional

from marshmallow import validate
from marshmallow_dataclass import dataclass
from te_schemas.productivity import ProductivityMode

# ---------------------------------------------------------------------------
# Mode-specific parameter classes
# ---------------------------------------------------------------------------


@dataclass
class TEProductivityParams:
    """Trends.Earth 5-class LPD productivity parameters.

    Used when ``mode`` is ``"TrendsEarth-LPD-5"``.

    Attributes:
        mode: Must equal ``ProductivityMode.TRENDS_EARTH_5_CLASS_LPD``.
        ndvi_gee_dataset: GEE asset path for NDVI data.
        trajectory_method: Trajectory calculation method name
            (``"ndvi_trend"``, ``"p_restrend"``, ``"ue"``).
        traj_year_initial: Trajectory period start year.
        traj_year_final: Trajectory period end year.
        perf_year_initial: Performance period start year.
        perf_year_final: Performance period end year.
        state_year_bl_start: State baseline start year.
        state_year_bl_end: State baseline end year.
        state_year_tg_start: State target start year.
        state_year_tg_end: State target end year.
        climate_gee_dataset: GEE asset path for climate data (optional,
            required for ``"p_restrend"`` and ``"ue"``).
        calc_traj: Whether to calculate trajectory (default ``True``).
        calc_perf: Whether to calculate performance (default ``True``).
        calc_state: Whether to calculate state (default ``True``).
    """

    mode: str = field(
        metadata={
            "required": True,
            "validate": validate.Equal(ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value),
        }
    )
    ndvi_gee_dataset: str = field(metadata={"required": True})
    traj_year_initial: int = field(metadata={"required": True})
    traj_year_final: int = field(metadata={"required": True})
    perf_year_initial: int = field(metadata={"required": True})
    perf_year_final: int = field(metadata={"required": True})
    state_year_bl_start: int = field(metadata={"required": True})
    state_year_bl_end: int = field(metadata={"required": True})
    state_year_tg_start: int = field(metadata={"required": True})
    state_year_tg_end: int = field(metadata={"required": True})
    trajectory_method: str = field(
        default="ndvi_trend",
        metadata={
            "validate": validate.OneOf(["ndvi_trend", "p_restrend", "ue"]),
        },
    )
    climate_gee_dataset: Optional[str] = field(default=None)
    calc_traj: bool = field(default=True)
    calc_perf: bool = field(default=True)
    calc_state: bool = field(default=True)


@dataclass
class JRCProductivityParams:
    """JRC pre-calculated 5-class LPD productivity parameters.

    Used when ``mode`` is ``"JRC-LPD-5"``.

    Attributes:
        mode: Must equal ``ProductivityMode.JRC_5_CLASS_LPD``.
        asset: GEE asset path for the JRC LPD layer.
        year_initial: Analysis start year.
        year_final: Analysis end year.
        data_source: Human-readable source label.
    """

    mode: str = field(
        metadata={
            "required": True,
            "validate": validate.Equal(ProductivityMode.JRC_5_CLASS_LPD.value),
        }
    )
    asset: str = field(metadata={"required": True})
    year_initial: int = field(metadata={"required": True})
    year_final: int = field(metadata={"required": True})
    data_source: str = field(
        default="Joint Research Commission (JRC)",
    )


@dataclass
class FAOWOCATProductivityParams:
    """FAO-WOCAT 5-class LPD productivity parameters.

    Used when ``mode`` is ``"FAO-WOCAT-LPD-5"``.

    Attributes:
        mode: Must equal ``ProductivityMode.FAO_WOCAT_5_CLASS_LPD``.
        ndvi_gee_dataset: GEE asset path for NDVI data.
        year_initial: Analysis start year.
        year_final: Analysis end year.
        low_biomass: Low biomass threshold (0–1).
        high_biomass: High biomass threshold (0–1).
        years_interval: Interval in years for analysis window.
        modis_mode: MODIS analysis mode string.
    """

    mode: str = field(
        metadata={
            "required": True,
            "validate": validate.Equal(ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value),
        }
    )
    ndvi_gee_dataset: str = field(metadata={"required": True})
    year_initial: int = field(metadata={"required": True})
    year_final: int = field(metadata={"required": True})
    low_biomass: float = field(metadata={"required": True})
    high_biomass: float = field(metadata={"required": True})
    years_interval: int = field(metadata={"required": True})
    modis_mode: str = field(metadata={"required": True})


# ---------------------------------------------------------------------------
# Top-level schema
# ---------------------------------------------------------------------------


@dataclass
class ProductivityParameters:
    """Top-level parameters for the productivity calculation.

    The ``productivity`` field is a dict whose ``mode`` key determines
    which parameter set applies:

    * ``"TrendsEarth-LPD-5"`` → :class:`TEProductivityParams`
    * ``"JRC-LPD-5"`` → :class:`JRCProductivityParams`
    * ``"FAO-WOCAT-LPD-5"`` → :class:`FAOWOCATProductivityParams`

    Attributes:
        geojsons: JSON-encoded string of area-of-interest geometries.
        crs: Coordinate reference system as WKT string.
        productivity: Mode-specific parameters (see above).
        ENV: Execution environment.
        EXECUTION_ID: Unique execution identifier.
    """

    geojsons: str = field(metadata={"required": True})
    crs: str = field(metadata={"required": True})
    productivity: dict = field(metadata={"required": True})

    ENV: Optional[str] = field(
        default=None,
        metadata={
            "validate": validate.OneOf(["dev", "staging", "prod"]),
            "allow_none": True,
        },
    )
    EXECUTION_ID: Optional[str] = field(default=None)
