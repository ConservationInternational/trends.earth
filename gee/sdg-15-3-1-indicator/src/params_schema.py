"""
Marshmallow parameter schema for the sdg-15-3-1-indicator GEE script.

Purpose: Calculates the final SDG 15.3.1 indicator (land degradation
    neutrality) by combining productivity (5-class LPD), land-cover
    degradation, and soil organic carbon sub-indicators.  Supports a
    baseline period and multiple status/reporting periods.  Optionally
    includes extra productivity bands (trajectory, performance, state).

Usage::

    from params_schema import SDG1531IndicatorParameters

    # Validate and deserialize incoming params dict
    params_obj = SDG1531IndicatorParameters.Schema().load(raw_params)

    # Serialize back to a dict for API transport
    params_dict = SDG1531IndicatorParameters.Schema().dump(params_obj)
"""

from dataclasses import field
from typing import List, Optional, Union

from marshmallow import validate
from marshmallow_dataclass import dataclass
from te_schemas.land_cover import LCLegendNesting, LCTransitionDefinitionDeg
from te_schemas.productivity import ProductivityMode

# ---------------------------------------------------------------------------
# Nested sub-parameter schemas
# ---------------------------------------------------------------------------


@dataclass
class TEProductivityParams:
    """Trends.Earth productivity sub-indicator parameters.

    Used when ``mode`` is ``"TRENDS_EARTH_5_CLASS_LPD"``.

    Attributes:
        mode: Must be ``"TRENDS_EARTH_5_CLASS_LPD"``.
        asset_productivity: GEE asset path for the NDVI productivity dataset.
        asset_climate: GEE asset path for the climate dataset (may be *None*
            when no climate adjustment is needed).
        traj_year_initial: Trajectory period start year.
        traj_year_final: Trajectory period end year.
        traj_method: Trajectory calculation method name.
        perf_year_initial: Performance period start year.
        perf_year_final: Performance period end year.
        state_year_bl_start: State baseline period start year.
        state_year_bl_end: State baseline period end year.
        state_year_tg_start: State target period start year.
        state_year_tg_end: State target period end year.
    """

    mode: str = field(
        metadata={
            "required": True,
            "validate": validate.Equal(ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value),
        }
    )
    asset_productivity: str = field(metadata={"required": True})
    traj_method: str = field(metadata={"required": True})
    traj_year_initial: int = field(metadata={"required": True})
    traj_year_final: int = field(metadata={"required": True})
    perf_year_initial: int = field(metadata={"required": True})
    perf_year_final: int = field(metadata={"required": True})
    state_year_bl_start: int = field(metadata={"required": True})
    state_year_bl_end: int = field(metadata={"required": True})
    state_year_tg_start: int = field(metadata={"required": True})
    state_year_tg_end: int = field(metadata={"required": True})
    asset_climate: Optional[str] = field(
        default=None,
    )


@dataclass
class JRCProductivityParams:
    """JRC pre-calculated productivity sub-indicator parameters.

    Used when ``mode`` is ``"JRC_5_CLASS_LPD"``.

    Attributes:
        mode: Must be ``"JRC_5_CLASS_LPD"``.
        asset: GEE asset path for the pre-calculated JRC LPD data.
        year_initial: Start year.
        year_final: End year.
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
    data_source: Optional[str] = field(
        default="Joint Research Commission (JRC)",
    )


@dataclass
class FAOWOCATProductivityParams:
    """FAO-WOCAT productivity sub-indicator parameters.

    Used when ``mode`` is ``"FAO_WOCAT_5_CLASS_LPD"``.

    Attributes:
        mode: Must be ``"FAO_WOCAT_5_CLASS_LPD"``.
        ndvi_gee_dataset: GEE asset path for NDVI data.
        year_initial: Start year.
        year_final: End year.
        low_biomass: Low biomass threshold.
        high_biomass: High biomass threshold.
        years_interval: Interval in years for the analysis window.
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
    low_biomass: float = field(
        default=0.4,
    )
    high_biomass: float = field(
        default=0.7,
    )
    years_interval: int = field(
        default=3,
    )
    modis_mode: str = field(
        default="MannKendal + MTID",
    )


@dataclass
class LandCoverSubParams:
    """Land-cover sub-indicator parameters for a single period.

    Attributes:
        year_initial: Baseline year for land-cover comparison.
        year_final: Target year for land-cover comparison.
        trans_matrix: Transition degradation definition.
        legend_nesting_esa_to_custom: ESA-to-custom legend nesting.
        legend_nesting_custom_to_ipcc: Custom-to-IPCC legend nesting.
        fake_data: Allow fallback for missing years.
    """

    year_initial: int = field(metadata={"required": True})
    year_final: int = field(metadata={"required": True})
    trans_matrix: LCTransitionDefinitionDeg = field(metadata={"required": True})
    legend_nesting_esa_to_custom: LCLegendNesting = field(metadata={"required": True})
    legend_nesting_custom_to_ipcc: LCLegendNesting = field(metadata={"required": True})
    fake_data: bool = field(
        default=False,
    )


@dataclass
class SOCSubParams:
    """Soil organic carbon sub-indicator parameters for a single period.

    Attributes:
        year_initial: Baseline year.
        year_final: Target year.
        fl: IPCC stock change factor.
        legend_nesting_esa_to_custom: ESA-to-custom legend nesting.
        legend_nesting_custom_to_ipcc: Custom-to-IPCC legend nesting.
        fake_data: Allow fallback for missing years.
    """

    year_initial: int = field(metadata={"required": True})
    year_final: int = field(metadata={"required": True})
    fl: Union[float, str] = field(metadata={"required": True})
    legend_nesting_esa_to_custom: LCLegendNesting = field(metadata={"required": True})
    legend_nesting_custom_to_ipcc: LCLegendNesting = field(metadata={"required": True})
    fake_data: bool = field(
        default=False,
    )


@dataclass
class PeriodDefinition:
    """Year range for a reporting period.

    Attributes:
        year_initial: Period start year.
        year_final: Period end year.
    """

    year_initial: int = field(metadata={"required": True})
    year_final: int = field(metadata={"required": True})


@dataclass
class SDGPeriodParams:
    """Complete parameter set for a single SDG 15.3.1 reporting period.

    Contains the period year range and the three sub-indicator parameter
    blocks.

    Attributes:
        period: Year range definition.
        productivity: Productivity sub-indicator parameters (one of the
            three mode-specific dataclasses).
        land_cover: Land-cover sub-indicator parameters.
        soil_organic_carbon: Soil organic carbon sub-indicator parameters.
    """

    period: PeriodDefinition = field(metadata={"required": True})
    productivity: dict = field(metadata={"required": True})
    land_cover: LandCoverSubParams = field(metadata={"required": True})
    soil_organic_carbon: SOCSubParams = field(metadata={"required": True})


# ---------------------------------------------------------------------------
# Top-level schema
# ---------------------------------------------------------------------------


@dataclass
class SDG1531IndicatorParameters:
    """Parameters for the SDG 15.3.1 combined indicator calculation.

    Attributes:
        geojsons: Area-of-interest geometries (already-parsed list).
        crs: Coordinate reference system as WKT string.
        baseline_period: Complete parameter set for the baseline period.
        status_periods: List of parameter sets for status/reporting periods.
        filetype: Output raster file type.
        include_productivity_bands: Include extra productivity bands
            (trajectory, performance, state) in the output.
        ENV: Execution environment.
        EXECUTION_ID: Unique execution identifier.
    """

    geojsons: list = field(metadata={"required": True})
    crs: str = field(metadata={"required": True})
    baseline_period: SDGPeriodParams = field(metadata={"required": True})
    status_periods: List[SDGPeriodParams] = field(metadata={"required": True})
    filetype: str = field(
        default="COG",
        metadata={"validate": validate.OneOf(["COG", "GeoTiff"])},
    )
    include_productivity_bands: bool = field(
        default=False,
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
