"""Sanity checks for SDG 15.3.1 and drought summary JSON files.

These run on the ``*_summary.json`` written by the summary tools, before the
UNCCD/PRAIS package is built. They are pure Python (no QGIS imports) so they
can be unit tested offline.

Problems that indicate a broken summary are reported as errors and fail the
stage. Results that are possible but unusual are reported as warnings.
"""

import dataclasses
import itertools
import math
import os

NO_DATA = "No data"
DEG_CLASSES = ("Improved", "Stable", "Degraded")
DROUGHT_CLASSES = (
    "Mild drought",
    "Moderate drought",
    "Severe drought",
    "Extreme drought",
)
NON_DROUGHT = "Non-drought"
POP_TYPES = ("Total population", "Male population", "Female population")
SUMMARY_KEYS = ("all_cover_types", "non_water")

# Plausible national population densities (people per sq km), from sparsely
# populated countries (e.g. Greenland, Mongolia) to city states (e.g. Monaco,
# Macao), with margin. Values outside indicate a wrong AOI or mis-scaled data.
MIN_POP_DENSITY = 0.01
MAX_POP_DENSITY = 50_000


def _env_float(name, default):
    value = os.environ.get(name, "").strip()
    try:
        return float(value) if value else default
    except ValueError:
        return default


@dataclasses.dataclass(frozen=True)
class Thresholds:
    # Summary total area vs. the AOI polygon area (pixel edge effects)
    area_tol: float = 0.05
    # Tabulations of the same pixels (indicators, periods, crosstabs)
    identity_tol: float = 0.01
    # Fraction of the area (or population) in "No data"
    max_nodata_frac: float = 0.30
    warn_nodata_frac: float = 0.10
    # Fraction of valid area in a single class (Stable or Degraded) before warning
    warn_single_class_frac: float = 0.95

    @classmethod
    def from_env(cls):
        default = cls()
        return cls(
            area_tol=_env_float("TE_E2E_CHECK_AREA_TOL", default.area_tol),
            max_nodata_frac=_env_float(
                "TE_E2E_CHECK_MAX_NODATA_FRAC", default.max_nodata_frac
            ),
            warn_nodata_frac=_env_float(
                "TE_E2E_CHECK_WARN_NODATA_FRAC", default.warn_nodata_frac
            ),
        )


@dataclasses.dataclass
class CheckReport:
    kind: str
    errors: list = dataclasses.field(default_factory=list)
    warnings: list = dataclasses.field(default_factory=list)
    metrics: dict = dataclasses.field(default_factory=dict)

    @property
    def ok(self):
        return not self.errors

    def error(self, message):
        self.errors.append(message)

    def warn(self, message):
        self.warnings.append(message)

    def as_dict(self):
        return dataclasses.asdict(self)


def _rel_diff(a, b):
    scale = max(abs(a), abs(b))
    return 0.0 if scale == 0 else abs(a - b) / scale


def _is_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _named_values(report, label, items, name_key, value_key):
    """Return ``{name: value}``, reporting invalid or negative values."""
    values = {}
    for item in items or []:
        name = item.get(name_key)
        value = item.get(value_key)
        if not _is_number(value):
            report.error(f"{label}: {name!r} has invalid value {value!r}")
            continue
        if value < 0:
            report.error(f"{label}: {name!r} is negative ({value})")
        values[name] = float(value)
    return values


def _areas(report, label, area_list):
    if not isinstance(area_list, dict):
        report.error(f"{label}: missing")
        return None
    return _named_values(report, label, area_list.get("areas"), "name", "area")


def _check_total(report, label, total, expected, tol):
    if expected is not None and _rel_diff(total, expected) > tol:
        report.error(
            f"{label}: total {total:,.1f} differs from expected {expected:,.1f} "
            f"by {_rel_diff(total, expected):.1%}"
        )


def _check_nodata(report, label, nodata, total, thresholds, what="area"):
    if total <= 0:
        return None
    frac = nodata / total
    if frac > thresholds.max_nodata_frac:
        report.error(f"{label}: {frac:.1%} of {what} is No data")
    elif frac > thresholds.warn_nodata_frac:
        report.warn(f"{label}: {frac:.1%} of {what} is No data")
    return frac


def _check_deg_areas(report, label, area_list, expected_total, thresholds):
    """Check an Improved/Stable/Degraded/No data area list."""
    areas = _areas(report, label, area_list)
    if areas is None:
        return None
    missing = [c for c in (*DEG_CLASSES, NO_DATA) if c not in areas]
    if missing:
        report.error(f"{label}: missing classes {missing}")
        return None
    total = sum(areas.values())
    if total <= 0:
        report.error(f"{label}: total area is zero")
        return None
    _check_total(report, label, total, expected_total, thresholds.identity_tol)
    nodata_frac = _check_nodata(report, label, areas[NO_DATA], total, thresholds)
    valid = sum(areas[c] for c in DEG_CLASSES)
    if valid <= 0:
        report.error(f"{label}: no area is Improved, Stable or Degraded")
        return None
    if areas["Stable"] <= 0:
        report.error(f"{label}: Stable area is zero")
    for cls in ("Improved", "Degraded"):
        if areas[cls] <= 0:
            report.warn(f"{label}: {cls} area is zero")
    for cls in ("Stable", "Degraded"):
        frac = areas[cls] / valid
        if frac >= thresholds.warn_single_class_frac:
            report.warn(f"{label}: {frac:.1%} of valid area is {cls}")
    return {
        "total_km2": total,
        "nodata_frac": nodata_frac,
        "degraded_frac": areas["Degraded"] / valid,
        "stable_frac": areas["Stable"] / valid,
        "improved_frac": areas["Improved"] / valid,
    }


def _check_summaries_by_cover(report, label, summaries, total, thresholds):
    """Check productivity or SOC summaries keyed by all_cover_types/non_water."""
    if not isinstance(summaries, dict):
        report.error(f"{label}: missing")
        return {}
    metrics = {}
    for key in SUMMARY_KEYS:
        if key not in summaries:
            report.error(f"{label}: missing {key!r} summary")
    if "all_cover_types" in summaries:
        metrics["all_cover_types"] = _check_deg_areas(
            report,
            f"{label} (all cover types)",
            summaries["all_cover_types"],
            total,
            thresholds,
        )
    if "non_water" in summaries:
        non_water = _check_deg_areas(
            report, f"{label} (non-water)", summaries["non_water"], None, thresholds
        )
        metrics["non_water"] = non_water
        if non_water and non_water["total_km2"] > total * (1 + thresholds.identity_tol):
            report.error(
                f"{label}: non-water area {non_water['total_km2']:,.1f} exceeds "
                f"total area {total:,.1f}"
            )
    return metrics


def _crosstab_sum(report, label, crosstab):
    if not isinstance(crosstab, dict):
        report.error(f"{label}: missing")
        return None
    values = [entry.get("value") for entry in crosstab.get("values") or []]
    bad = [v for v in values if not _is_number(v) or v < 0]
    if bad:
        report.error(f"{label}: invalid or negative values {bad[:5]}")
        return None
    return sum(values)


def _check_by_year(report, label, by_year, expected_total, thresholds, max_change):
    """Check a {year: {class: value}} table.

    ``expected_total`` compares each year's total with the summary area.
    ``max_change`` warns when the total changes more than that between years.
    """
    values = (by_year or {}).get("values") if isinstance(by_year, dict) else None
    if not values:
        report.error(f"{label}: no values")
        return {}
    totals = {}
    for year in sorted(values, key=lambda y: int(y)):
        by_class = values[year] or {}
        bad = [v for v in by_class.values() if not _is_number(v) or v < 0]
        if bad:
            report.error(f"{label} {year}: invalid or negative values {bad[:5]}")
            continue
        total = sum(by_class.values())
        if total <= 0:
            report.error(f"{label} {year}: total is zero")
            continue
        nonzero = [k for k, v in by_class.items() if v > 0 and k != NO_DATA]
        if len(nonzero) < 2:
            report.error(f"{label} {year}: only {len(nonzero)} class(es) have values")
        _check_total(
            report, f"{label} {year}", total, expected_total, thresholds.identity_tol
        )
        totals[int(year)] = total
    years = sorted(totals)
    for previous, year in itertools.pairwise(years):
        change = _rel_diff(totals[previous], totals[year])
        if change > max_change:
            report.warn(
                f"{label}: total changes {change:.1%} between {previous} and {year}"
            )
    return totals


def _check_population(report, label, summary, thresholds):
    """Check a {pop type: PopulationList} mapping and return the total."""
    if not isinstance(summary, dict) or "Total population" not in summary:
        report.error(f"{label}: no Total population")
        return None
    totals = {}
    for pop_type, pop_list in summary.items():
        values = _named_values(
            report,
            f"{label} {pop_type}",
            (pop_list or {}).get("values"),
            "name",
            "population",
        )
        total = sum(values.values())
        totals[pop_type] = total
        if total <= 0:
            report.error(f"{label} {pop_type}: population is zero")
            continue
        _check_nodata(
            report,
            f"{label} {pop_type}",
            values.get(NO_DATA, 0.0),
            total,
            thresholds,
            what="population",
        )
    male = totals.get("Male population")
    female = totals.get("Female population")
    if (male is None) != (female is None):
        report.error(f"{label}: only one of male/female population is present")
    elif male is not None:
        combined = male + female
        if _rel_diff(combined, totals["Total population"]) > thresholds.identity_tol:
            report.error(
                f"{label}: male + female ({combined:,.0f}) does not match total "
                f"({totals['Total population']:,.0f})"
            )
    return totals["Total population"]


def _check_population_density(report, area_km2, population):
    if not population or not area_km2:
        return
    density = population / area_km2
    report.metrics["population_density"] = density
    if not MIN_POP_DENSITY <= density <= MAX_POP_DENSITY:
        report.error(
            f"population density {density:,.2f} per sq km "
            f"({population:,.0f} people over {area_km2:,.1f} sq km) is implausible"
        )


def _check_aoi_area(report, total, aoi_area_km2, thresholds):
    if aoi_area_km2 and _rel_diff(total, aoi_area_km2) > thresholds.area_tol:
        report.error(
            f"total area {total:,.1f} sq km differs from the AOI area "
            f"{aoi_area_km2:,.1f} sq km by {_rel_diff(total, aoi_area_km2):.1%}"
        )


def _period_sort_key(name):
    if name == "baseline":
        return (0, 0)
    try:
        return (1, int(name.rsplit("_", 1)[-1]))
    except ValueError:
        return (2, name)


# ---------------------------------------------------------------------------
# SDG 15.3.1
# ---------------------------------------------------------------------------


def _check_status(report, label, status, total, thresholds):
    if not isinstance(status, dict):
        report.error(f"{label}: missing status assessment")
        return
    _check_deg_areas(report, f"{label} SDG", status.get("sdg"), total, thresholds)
    _check_deg_areas(
        report, f"{label} land cover", status.get("land_cover"), total, thresholds
    )
    for key, name in (
        ("productivity", "productivity"),
        ("soil_organic_carbon", "soil organic carbon"),
    ):
        _check_summaries_by_cover(
            report, f"{label} {name}", status.get(key), total, thresholds
        )


def _check_change(report, label, change, total, thresholds):
    if not isinstance(change, dict):
        report.error(f"{label}: missing change assessment")
        return
    for key in ("sdg", "productivity", "land_cover", "soil_organic_carbon"):
        value = _crosstab_sum(report, f"{label} {key}", change.get(key))
        if value is not None:
            _check_total(
                report, f"{label} {key}", value, total, thresholds.identity_tol
            )


def _check_crosstab_list(report, label, crosstabs, total, thresholds, partition):
    """Check a list of crosstabs against the total area.

    With ``partition`` the crosstabs split the area between them (e.g. one per
    productivity class), so their combined sum is checked. Otherwise each
    crosstab covers the whole area on its own (e.g. one land cover transition
    crosstab per distinct period), so each is checked separately.
    """
    if not crosstabs:
        report.warn(f"{label}: no crosstabs")
        return
    sums = []
    for crosstab in crosstabs:
        value = _crosstab_sum(report, label, crosstab)
        if value is None:
            return
        sums.append(value)
    if partition:
        sums = [sum(sums)]
    for index, value in enumerate(sums):
        name = label if len(sums) == 1 else f"{label} [{index}]"
        if value <= 0:
            report.error(f"{name}: all values are zero")
        elif value > total * (1 + thresholds.identity_tol):
            report.error(f"{name}: sum {value:,.1f} exceeds total area {total:,.1f}")


def check_sdg_summary(data, aoi_area_km2=None, thresholds=None):
    """Check a ``TrendsEarthLandConditionSummary`` JSON dictionary."""
    thresholds = thresholds or Thresholds()
    report = CheckReport("sdg")
    land_condition = data.get("land_condition") or {}
    affected = data.get("affected_population") or {}
    if "baseline" not in land_condition:
        report.error("no baseline period in land_condition")
        return report
    periods = sorted(land_condition, key=_period_sort_key)
    if len(periods) < 2:
        report.warn("no reporting periods, only the baseline")
    report.metrics["periods"] = periods

    totals = {}
    populations = {}
    for period in periods:
        lcr = land_condition[period] or {}
        pa = lcr.get("period_assessment") or {}
        sdg = _check_deg_areas(
            report,
            f"{period} SDG 15.3.1",
            (pa.get("sdg") or {}).get("summary"),
            None,
            thresholds,
        )
        if sdg is None:
            continue
        total = sdg["total_km2"]
        totals[period] = total
        metrics = report.metrics.setdefault(period, {})
        metrics["sdg"] = sdg

        land_cover = pa.get("land_cover") or {}
        metrics["land_cover"] = _check_deg_areas(
            report,
            f"{period} land cover",
            land_cover.get("summary"),
            total,
            thresholds,
        )
        metrics["productivity"] = _check_summaries_by_cover(
            report,
            f"{period} productivity",
            (pa.get("productivity") or {}).get("summaries"),
            total,
            thresholds,
        )
        soc = pa.get("soil_organic_carbon") or {}
        metrics["soil_organic_carbon"] = _check_summaries_by_cover(
            report,
            f"{period} soil organic carbon",
            soc.get("summaries"),
            total,
            thresholds,
        )

        _check_by_year(
            report,
            f"{period} land cover area by year",
            land_cover.get("land_cover_areas_by_year"),
            total,
            thresholds,
            max_change=thresholds.identity_tol,
        )
        _check_by_year(
            report,
            f"{period} SOC stock by year",
            soc.get("soc_stock_by_year"),
            None,
            thresholds,
            max_change=0.2,
        )
        _check_crosstab_list(
            report,
            f"{period} land cover transitions",
            land_cover.get("crosstabs_by_land_cover_class"),
            total,
            thresholds,
            partition=False,
        )
        _check_crosstab_list(
            report,
            f"{period} productivity by land cover transition",
            (pa.get("productivity") or {}).get("crosstabs_by_productivity_class"),
            total,
            thresholds,
            partition=True,
        )

        if period != "baseline":
            _check_status(
                report,
                f"{period} status",
                lcr.get("status_assessment"),
                total,
                thresholds,
            )
            _check_change(
                report,
                f"{period} change",
                lcr.get("change_assessment"),
                total,
                thresholds,
            )

        pop_summary = (affected.get(period) or {}).get("summary")
        population = _check_population(
            report, f"{period} population", pop_summary, thresholds
        )
        if population is not None:
            populations[period] = population
            metrics["population"] = population

    if not totals:
        return report
    baseline_total = totals.get("baseline") or next(iter(totals.values()))
    for period, total in totals.items():
        _check_total(
            report,
            f"{period} total area vs baseline",
            total,
            baseline_total,
            thresholds.identity_tol,
        )
    pop_periods = sorted(populations, key=_period_sort_key)
    for previous, period in itertools.pairwise(pop_periods):
        change = _rel_diff(populations[previous], populations[period])
        if change > 0.5:
            report.warn(f"population changes {change:.1%} from {previous} to {period}")

    report.metrics["total_area_km2"] = baseline_total
    report.metrics["aoi_area_km2"] = aoi_area_km2
    _check_aoi_area(report, baseline_total, aoi_area_km2, thresholds)
    _check_population_density(
        report,
        baseline_total,
        populations.get(pop_periods[-1]) if pop_periods else None,
    )
    return report


# ---------------------------------------------------------------------------
# Drought
# ---------------------------------------------------------------------------


def check_drought_summary(data, aoi_area_km2=None, thresholds=None):
    """Check a ``TrendsEarthDroughtSummary`` JSON dictionary."""
    thresholds = thresholds or Thresholds()
    report = CheckReport("drought")
    drought = data.get("drought") or {}
    tier_one = drought.get("tier_one") or {}
    tier_two = drought.get("tier_two") or {}
    if not tier_one:
        report.error("no tier one (area by drought class) results")
        return report

    years = sorted(int(y) for y in tier_one)
    report.metrics["years"] = [years[0], years[-1]]
    if years != list(range(years[0], years[-1] + 1)):
        report.error(f"tier one years are not contiguous: {years}")
    missing_pop_years = sorted(set(years) - {int(y) for y in tier_two})
    if missing_pop_years:
        report.error(f"tier two has no population for years {missing_pop_years}")

    totals = {}
    drought_area = {}
    non_drought_area = {}
    nodata_fracs = {}
    populations = {}
    by_year = {int(k): v for k, v in tier_one.items()}
    pop_by_year = {int(k): v for k, v in tier_two.items()}
    for year in years:
        label = f"{year} drought area"
        areas = _areas(report, label, by_year[year])
        if areas is None:
            continue
        missing = [
            c for c in (*DROUGHT_CLASSES, NON_DROUGHT, NO_DATA) if c not in areas
        ]
        if missing:
            report.error(f"{label}: missing classes {missing}")
            continue
        total = sum(areas.values())
        if total <= 0:
            report.error(f"{label}: total area is zero")
            continue
        totals[year] = total
        nodata_fracs[year] = _check_nodata(
            report, label, areas[NO_DATA], total, thresholds
        )
        drought_area[year] = sum(areas[c] for c in DROUGHT_CLASSES)
        non_drought_area[year] = areas[NON_DROUGHT]
        if drought_area[year] + non_drought_area[year] <= 0:
            report.error(f"{label}: all area is No data")

        if year in pop_by_year:
            population = _check_population(
                report, f"{year} drought population", pop_by_year[year], thresholds
            )
            if population is not None:
                populations[year] = population

    if not totals:
        return report

    first_total = totals[min(totals)]
    for year, total in totals.items():
        _check_total(
            report,
            f"{year} drought total area vs {min(totals)}",
            total,
            first_total,
            thresholds.identity_tol,
        )
    if not any(v > 0 for v in drought_area.values()):
        report.error("no area is in any drought class in any year")
    if not any(v > 0 for v in non_drought_area.values()):
        report.error("no area is Non-drought in any year")
    always_drought = [y for y, v in non_drought_area.items() if v <= 0]
    if always_drought and len(always_drought) < len(non_drought_area):
        report.warn(f"no Non-drought area in years {always_drought}")
    pop_years = sorted(populations)
    for previous, year in itertools.pairwise(pop_years):
        change = _rel_diff(populations[previous], populations[year])
        if change > 0.25:
            report.warn(f"population changes {change:.1%} from {previous} to {year}")

    dvi_values = list((drought.get("tier_three") or {}).values())
    if not dvi_values:
        report.error("no tier three (drought vulnerability) results")
    for entry in dvi_values:
        value = (entry or {}).get("value")
        if not _is_number(value):
            report.error(f"drought vulnerability index is {value!r}")
        elif not 0 <= value <= 1:
            report.error(f"drought vulnerability index {value} is outside 0-1")
        else:
            report.metrics["dvi"] = value

    report.metrics["total_area_km2"] = first_total
    report.metrics["aoi_area_km2"] = aoi_area_km2
    report.metrics["max_nodata_frac"] = max(
        (v for v in nodata_fracs.values() if v is not None), default=None
    )
    report.metrics["mean_drought_frac"] = sum(
        drought_area[y] / totals[y] for y in totals
    ) / len(totals)
    if pop_years:
        report.metrics["population"] = populations[pop_years[-1]]
    _check_aoi_area(report, first_total, aoi_area_km2, thresholds)
    _check_population_density(
        report, first_total, populations[pop_years[-1]] if pop_years else None
    )
    return report
