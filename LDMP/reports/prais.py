import copy
import json
from pathlib import Path
from typing import Dict, List, Optional, Union

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


def _lc_name_short(lc: Union[LCClass, Dict]) -> str:
    """Return the short name regardless of whether *lc* is an LCClass or a raw dict."""
    return lc["name_short"] if hasattr(lc, "name_short") else lc.get("name_short", "")


def generate_prais_json(result: Job, job: Job, job_output_path: Path) -> None:
    """Generate a PRAIS‑compatible JSON summary"""
    if not hasattr(result, "data"):
        return

    result_data = result.data

    data = copy.deepcopy(result_data)

    prais_data: Dict[str, Union[str, Dict, List]] = {
        "id": str(job.id),
        "task_name": job.task_name,
        "task_notes": job.task_notes,
        "country_profile": {"land_area": []},
        "land_cover_legend": None,
        "land_cover_transition_matrix": None,
        "key_degradation_processes": [],
    }
    baseline = data.get("report", {}).get("land_condition", {}).get("baseline", {})
    land_cover_section: Dict = baseline.get("land_cover", {})

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

                prais_data["country_profile"]["land_area"].append(
                    {
                        "year": year,
                        "total_land_area_km2": total_land_area,
                        "water_bodies_km2": water_bodies_area,
                        "total_country_area_km2": total_land_area + water_bodies_area,
                    }
                )

    transition_matrix_raw: Optional[Dict] = land_cover_section.get("transition_matrix")
    if transition_matrix_raw:
        matrix_dict: Dict = transition_matrix_raw.get(
            "definitions", transition_matrix_raw
        )

        prais_data["land_cover_legend"] = transition_matrix_raw.get("legend")
        prais_data["land_cover_transition_matrix"] = matrix_dict

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

    prais_json_path = job_output_path.parent / "prais_summary.json"
    with open(prais_json_path, "w", encoding="utf-8") as f:
        json.dump(prais_data, f, indent=2)
