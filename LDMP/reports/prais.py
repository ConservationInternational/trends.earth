import collections
import copy
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from te_schemas.jobs import Job
from te_schemas.land_cover import LCClass, LCTransitionMatrixBase


def classify_process(initial: LCClass, final: LCClass) -> str:
    """Return a human-readable degradation process label for an LC transition."""
    if final["name_short"] == "Artificial":
        return "Urban Expansion"

    if initial["name_short"] == "Tree-covered" and final["name_short"] in {
        "Grassland",
        "Cropland",
        "Bare land",
    }:
        return "Deforestation"

    if final["name_short"] == "Bare land":
        return "Vegetation Loss"

    if final["name_short"] == "Water":
        return "Inundation"

    if initial["name_short"] == "Grassland" and final["name_short"] == "Tree-covered":
        return "Woody Encroachment"

    if initial["name_short"] == "Wetland" and final["name_short"] != "Wetland":
        return "Wetland Drainage"

    return "Other"


def simplify_transition_matrix(transitions: collections.Iterable[Dict]) -> list[Any]:
    """
    Simplifies a list of transition matrices by extracting and restructuring key information
    into a concise representation.
    """
    result = []
    for transition in transitions:
        result.append(
            {
                "initial": transition["initial"]["name_short"],
                "final": transition["final"]["name_short"],
                "meaning": transition["meaning"],
            }
        )
    return result


def _lc_name_short(lc: Union[LCClass, Dict]) -> str:
    """Return the short name regardless of whether *lc* is an LCClass or a raw dict."""
    return lc["name_short"] if hasattr(lc, "name_short") else lc.get("name_short", "")


def _build_land_cover_estimates(
    lc_areas_by_year: Dict[str, Dict[str, float]],
) -> List[Dict]:
    """Create the SO1‑1.T4 annual land‑cover estimates table."""
    estimates: List[Dict] = []

    for year_str, year_data in lc_areas_by_year.items():
        row = {
            "year": int(year_str),
            "tree_covered_km2": 0.0,
            "grasslands_km2": 0.0,
            "croplands_km2": 0.0,
            "wetlands_km2": 0.0,
            "artificial_surfaces_km2": 0.0,
            "other_lands_km2": 0.0,
            "water_bodies_km2": 0.0,
        }

        for lc_class, area in year_data.items():
            lc_lower = lc_class.lower()
            if "tree" in lc_lower:
                row["tree_covered_km2"] += area
            elif "grass" in lc_lower:
                row["grasslands_km2"] += area
            elif "crop" in lc_lower:
                row["croplands_km2"] += area
            elif "wet" in lc_lower:
                row["wetlands_km2"] += area
            elif "artificial" in lc_lower or "built" in lc_lower:
                row["artificial_surfaces_km2"] += area
            elif "water" in lc_lower:
                row["water_bodies_km2"] += area
            else:
                row["other_lands_km2"] += area

        estimates.append(row)

    estimates.sort(key=lambda r: r["year"])
    return estimates


def generate_prais_json(result: Job, job: Job, job_output_path: Path) -> None:
    """Generate a PRAIS‑compatible JSON summary"""
    if not hasattr(result, "data"):
        return

    result_data = result.data

    data = copy.deepcopy(result_data)

    report_data = data.get("report", {})
    land_condition = report_data.get("land_condition", {})
    metadata = report_data.get("metadata", {})

    prais_data: Dict[str, Union[str, Dict, List]] = {
        "key_degradation_processes": [],
        "land_cover_legend": None,
        "land_cover_transition_matrix": None,
        "land_cover_estimates": [],
        "land_cover_change_for_baseline": [],
        "land_cover_change_for_progress": [],
        "land_cover_degradation_in_baseline_and_progress": [],
    }
    baseline = land_condition.get("baseline", {})
    progress = land_condition.get("progress", {})
    aoi = metadata.get("area_of_interest", {}).get("geojson", {})

    land_cover_section: Dict = baseline.get("land_cover", {})
    land_cover_section_progress: Dict = progress.get("land_cover", {})

    baseline_sdg: Dict = baseline.get("sdg", {})
    progress_sdg: Dict = progress.get("sdg", {})

    lc_areas_by_year: Dict[str, Dict[str, float]] = {
        **land_cover_section.get("land_cover_areas_by_year", {}).get("values", {}),
        **land_cover_section_progress.get("land_cover_areas_by_year", {}).get(
            "values", {}
        ),
    }
    if lc_areas_by_year:
        prais_data["land_cover_estimates"] = _build_land_cover_estimates(
            lc_areas_by_year
        )

    lc_areas_by_year: Dict[str, Dict[str, float]] = land_cover_section.get(
        "land_cover_areas_by_year", {}
    ).get("values", {})

    periods = job.params.get("periods", [])
    baseline_period_params = next(
        (p.get("params", {}) for p in periods if p.get("name") == "baseline"),
        {},
    )

    if "period" in baseline_period_params:
        year_initial = baseline_period_params["period"].get("year_initial")
        year_final = baseline_period_params["period"].get("year_final")

        if isinstance(year_initial, int) and isinstance(year_final, int):
            for year in range(year_initial, year_final + 1):
                year_str = str(year)
                year_data = lc_areas_by_year.get(year_str)
                if not year_data:
                    continue

                water_bodies_area = sum(
                    v for k, v in year_data.items() if "water" in k.lower()
                )
                total_land_area = sum(
                    v for k, v in year_data.items() if "water" not in k.lower()
                )

                # prais_data["country_profile"]["land_area"].append(
                #     {
                #         "year": year,
                #         "total_land_area_km2": total_land_area,
                #         "water_bodies_km2": water_bodies_area,
                #         "total_country_area_km2": total_land_area + water_bodies_area,
                #     }
                # )

    transition_matrix_raw: Optional[Dict] = land_cover_section.get("transition_matrix")
    if transition_matrix_raw:
        matrix_dict: Dict = transition_matrix_raw.get(
            "definitions", transition_matrix_raw
        )

        prais_data["land_cover_legend"] = transition_matrix_raw.get("legend")
        prais_data["land_cover_transition_matrix"] = simplify_transition_matrix(
            matrix_dict.get("transitions", [])
        )

        matrix: LCTransitionMatrixBase = LCTransitionMatrixBase.Schema().load(
            matrix_dict
        )

        degradation_transitions_data = [
            t for t in matrix.transitions if t["meaning"] == "degradation"
        ]

        degradation_transitions = [
            {
                "initial": {
                    "name_short": t["initial"]["name_short"],
                    "code": t["initial"]["code"],
                },
                "final": {
                    "name_short": t["final"]["name_short"],
                    "code": t["final"]["code"],
                },
            }
            for t in degradation_transitions_data
        ]

        prais_data["key_degradation_processes"] = [
            {
                "degradation_process": classify_process(t["initial"], t["final"]),
                "starting_land_cover": _lc_name_short(t["initial"]),
                "ending_land_cover": _lc_name_short(t["final"]),
            }
            for t in degradation_transitions
        ]

    prais_data["land_cover_change_for_baseline"] = land_cover_section.get(
        "crosstabs_by_land_cover_class", []
    )
    prais_data["land_cover_change_for_progress"] = land_cover_section_progress.get(
        "crosstabs_by_land_cover_class", []
    )

    baseline_areas = baseline_sdg.get("summary", {}).get("areas", [])
    progress_areas = progress_sdg.get("summary", {}).get("areas", [])

    if baseline_areas:
        total_baseline_area = sum(a["area"] for a in baseline_areas)
        [
            a.update({"percentage": a["area"] / total_baseline_area * 100})
            for a in baseline_areas
        ]

    if progress_areas:
        total_progress_area = sum(a["area"] for a in progress_areas)
        [
            a.update({"percentage": a["area"] / total_progress_area * 100})
            for a in progress_areas
        ]

    prais_data["land_cover_degradation_in_baseline_and_progress"] = {
        "baseline": baseline_areas,
        "progress": progress_areas,
    }

    prais_json_folder = os.path.join(job_output_path.parent, "prais")
    os.mkdir(prais_json_folder)
    prais_json_path = os.path.join(prais_json_folder, "so_1_1.json")
    aoi_path = os.path.join(prais_json_folder, "aoi.json")
    with open(prais_json_path, "w", encoding="utf-8") as f:
        json.dump(prais_data, f, indent=2)

    with open(aoi_path, "w", encoding="utf-8") as f:
        json.dump(aoi, f, indent=2)
