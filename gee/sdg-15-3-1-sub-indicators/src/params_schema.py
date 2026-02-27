"""
Marshmallow parameter schema for the sdg-15-3-1-sub-indicators GEE script.

Purpose: Calculates all three SDG 15.3.1 sub-indicators (productivity,
    land cover, SOC) individually with full detail, plus population data.
    Unlike the ``sdg-15-3-1-indicator`` script, this outputs the raw
    sub-indicator layers for detailed analysis.

Usage::

    from params_schema import SDG1531SubIndicatorsParameters

    # Validate and deserialize incoming params dict
    params_obj = SDG1531SubIndicatorsParameters.Schema().load(raw_params)

    # Serialize back to a dict for API transport
    params_dict = SDG1531SubIndicatorsParameters.Schema().dump(params_obj)
"""

from dataclasses import field
from typing import Optional, Union

from marshmallow import validate
from marshmallow_dataclass import dataclass
from te_schemas.land_cover import LCLegendNesting, LCTransitionDefinitionDeg
from te_schemas.productivity import ProductivityMode

# ---------------------------------------------------------------------------
# Nested sub-parameter schemas
# ---------------------------------------------------------------------------


@dataclass
class PeriodInfo:
    """Metadata about the analysis period.

    Attributes:
        name: Period name (e.g. ``"baseline"``, ``"reporting_1"``).
        year_initial: Period start year.
        year_final: Period end year.
    """

    name: str = field(metadata={"required": True})
    year_initial: int = field(metadata={"required": True})
    year_final: int = field(metadata={"required": True})


@dataclass
class ScriptInfo:
    """Minimal script metadata passed with the request.

    Attributes:
        name: Script name as registered in the platform.
    """

    name: str = field(metadata={"required": True})


@dataclass
class TEProductivityParams:
    """Trends.Earth productivity sub-indicator parameters.

    Attributes:
        mode: Must be ``"TrendsEarth-LPD-5"``.
        ndvi_gee_dataset: GEE asset for NDVI data.
        climate_gee_dataset: GEE asset for climate data (optional).
        trajectory_method: Trajectory calculation method name.
        traj_year_initial: Trajectory start year.
        traj_year_final: Trajectory end year.
        perf_year_initial: Performance start year.
        perf_year_final: Performance end year.
        state_year_bl_start: State baseline start year.
        state_year_bl_end: State baseline end year.
        state_year_tg_start: State target start year.
        state_year_tg_end: State target end year.
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
    trajectory_method: str = field(metadata={"required": True})
    traj_year_initial: int = field(metadata={"required": True})
    traj_year_final: int = field(metadata={"required": True})
    perf_year_initial: int = field(metadata={"required": True})
    perf_year_final: int = field(metadata={"required": True})
    state_year_bl_start: int = field(metadata={"required": True})
    state_year_bl_end: int = field(metadata={"required": True})
    state_year_tg_start: int = field(metadata={"required": True})
    state_year_tg_end: int = field(metadata={"required": True})
    climate_gee_dataset: Optional[str] = field(
        default=None,
    )
    calc_traj: bool = field(default=True)
    calc_perf: bool = field(default=True)
    calc_state: bool = field(default=True)


@dataclass
class JRCProductivityParams:
    """JRC pre-calculated productivity sub-indicator parameters.

    Attributes:
        mode: Must be ``"JRC-LPD-5"``.
        asset: JRC LPD GEE asset path.
        year_initial: Start year.
        year_final: End year.
        data_source: Source label.
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

    Attributes:
        mode: Must be ``"FAO-WOCAT-LPD-5"``.
        ndvi_gee_dataset: GEE asset for NDVI data.
        year_initial: Start year.
        year_final: End year.
        low_biomass: Low biomass threshold.
        high_biomass: High biomass threshold.
        years_interval: Analysis window interval in years.
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
    low_biomass: Optional[float] = field(
        default=None,
    )
    high_biomass: Optional[float] = field(
        default=None,
    )
    years_interval: Optional[int] = field(
        default=None,
    )
    modis_mode: Optional[str] = field(
        default=None,
    )


@dataclass
class LandCoverSubParams:
    """Land-cover sub-indicator parameters for a single period.

    Attributes:
        year_initial: Baseline year.
        year_final: Target year.
        trans_matrix: Transition degradation matrix.
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
        fl: IPCC stock change factor (float or ``"per pixel"``).
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
class PopulationSubParams:
    """Population data parameters.

    Attributes:
        year: Population reference year.
        asset: GEE asset path for WorldPop data.
        source: Human-readable data source name.
        fake_data: Allow fallback to nearest year.
    """

    year: int = field(metadata={"required": True})
    asset: str = field(metadata={"required": True})
    source: str = field(metadata={"required": True})
    fake_data: bool = field(
        default=False,
    )


# ---------------------------------------------------------------------------
# Top-level schema
# ---------------------------------------------------------------------------


@dataclass
class SDG1531SubIndicatorsParameters:
    """Parameters for the SDG 15.3.1 sub-indicators calculation.

    Attributes:
        geojsons: Area-of-interest geometries (already-parsed list).
        crs: Coordinate reference system as WKT string.
        period: Period metadata (name and year range).
        script: Script metadata.
        productivity: Productivity parameters (dict whose ``"mode"`` key
            determines the expected structure — see
            ``TEProductivityParams``, ``JRCProductivityParams``,
            ``FAOWOCATProductivityParams``).
        land_cover: Land-cover sub-indicator parameters.
        soil_organic_carbon: SOC sub-indicator parameters.
        population: Population data parameters.
        annual_lc: Include annual land-cover layers.
        filetype: Output raster file type.
        ENV: Execution environment.
        EXECUTION_ID: Unique execution identifier.
    """

    geojsons: list = field(metadata={"required": True})
    crs: str = field(metadata={"required": True})
    period: PeriodInfo = field(metadata={"required": True})
    script: ScriptInfo = field(metadata={"required": True})
    productivity: dict = field(metadata={"required": True})
    land_cover: LandCoverSubParams = field(metadata={"required": True})
    soil_organic_carbon: SOCSubParams = field(metadata={"required": True})
    population: PopulationSubParams = field(metadata={"required": True})
    annual_lc: Optional[bool] = field(
        default=None,
    )
    filetype: str = field(
        default="COG",
        metadata={"validate": validate.OneOf(["COG", "GeoTiff"])},
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
