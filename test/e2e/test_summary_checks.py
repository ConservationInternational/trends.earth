"""Offline tests for the e2e summary JSON sanity checks."""

import copy
import unittest

from .summary_checks import Thresholds, check_drought_summary, check_sdg_summary

TOTAL = 1000.0
DEG = {"Improved": 150.0, "Stable": 700.0, "Degraded": 100.0, "No data": 50.0}
DEG_NON_WATER = {"Improved": 140.0, "Stable": 650.0, "Degraded": 90.0, "No data": 20.0}
LC_YEAR = {
    "Tree-covered": 600.0,
    "Grassland": 200.0,
    "Cropland": 150.0,
    "Water body": 40.0,
    "No data": 10.0,
}


def area_list(values, name="Area"):
    return {
        "name": name,
        "unit": "sq km",
        "areas": [{"name": k, "area": v} for k, v in values.items()],
    }


def crosstab(cells):
    return {
        "name": "Crosstab",
        "unit": "sq km",
        "initial_year": 2000,
        "final_year": 2015,
        "values": [
            {"initial_label": a, "final_label": b, "value": v}
            for (a, b), v in cells.items()
        ],
    }


def change_crosstab():
    return crosstab(
        {
            ("Stable", "Stable"): 650.0,
            ("Improved", "Improved"): 150.0,
            ("Degraded", "Degraded"): 100.0,
            ("No data", "No data"): 50.0,
            ("Stable", "Degraded"): 50.0,
        }
    )


def by_cover():
    return {
        "all_cover_types": area_list(DEG),
        "non_water": area_list(DEG_NON_WATER),
    }


def population(total=600_000):
    def pop_list(scale):
        shares = {"Improved": 0.2, "Stable": 0.6, "Degraded": 0.15, "No data": 0.05}
        return {
            "name": "Population",
            "values": [
                {"name": k, "population": int(total * scale * s), "type": "Total"}
                for k, s in shares.items()
            ],
        }

    return {
        "Total population": pop_list(1.0),
        "Male population": pop_list(0.5),
        "Female population": pop_list(0.5),
    }


def land_condition_report(reporting=False):
    report = {
        "period_assessment": {
            "sdg": {"summary": area_list(DEG)},
            "productivity": {
                "summaries": by_cover(),
                "crosstabs_by_productivity_class": [
                    crosstab({("Tree-covered", "Tree-covered"): 500.0})
                ],
            },
            "land_cover": {
                "summary": area_list(DEG),
                "crosstabs_by_land_cover_class": [
                    crosstab({("Tree-covered", "Tree-covered"): 950.0})
                ],
                "land_cover_areas_by_year": {
                    "values": {"2000": dict(LC_YEAR), "2015": dict(LC_YEAR)}
                },
            },
            "soil_organic_carbon": {
                "summaries": by_cover(),
                "soc_stock_by_year": {
                    "values": {
                        "2000": {"Tree-covered": 5e6, "Grassland": 1e6},
                        "2015": {"Tree-covered": 4.9e6, "Grassland": 1e6},
                    }
                },
            },
        }
    }
    if reporting:
        report["status_assessment"] = {
            "sdg": area_list(DEG),
            "land_cover": area_list(DEG),
            "productivity": by_cover(),
            "soil_organic_carbon": by_cover(),
        }
        report["change_assessment"] = {
            key: change_crosstab()
            for key in ("sdg", "productivity", "land_cover", "soil_organic_carbon")
        }
    return report


def sdg_summary():
    return {
        "land_condition": {
            "baseline": land_condition_report(),
            "report_1": land_condition_report(reporting=True),
        },
        "affected_population": {
            "baseline": {"summary": population()},
            "report_1": {"summary": population()},
        },
    }


def drought_summary():
    def year_areas(year):
        drought = 100.0 if year % 3 == 0 else 0.0
        return area_list(
            {
                "Mild drought": drought,
                "Moderate drought": drought / 2,
                "Severe drought": 0.0,
                "Extreme drought": 0.0,
                "Non-drought": TOTAL - 20.0 - 1.5 * drought,
                "No data": 20.0,
            }
        )

    years = range(2000, 2020)
    return {
        "drought": {
            "tier_one": {str(y): year_areas(y) for y in years},
            "tier_two": {str(y): population() for y in years},
            "tier_three": {"2018": {"name": "Mean value", "value": 0.42}},
        }
    }


def set_area(area_list_data, name, value):
    for entry in area_list_data["areas"]:
        if entry["name"] == name:
            entry["area"] = value
            return
    raise KeyError(name)


class SdgSummaryChecksTest(unittest.TestCase):
    def check(self, data, **kwargs):
        kwargs.setdefault("aoi_area_km2", TOTAL)
        return check_sdg_summary(data, **kwargs)

    def assert_error(self, report, fragment):
        self.assertFalse(report.ok)
        self.assertTrue(
            any(fragment in e for e in report.errors),
            f"no error containing {fragment!r}: {report.errors}",
        )

    def test_valid_summary_passes(self):
        report = self.check(sdg_summary())
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])
        self.assertAlmostEqual(report.metrics["total_area_km2"], TOTAL)

    def test_mismatched_indicator_total_fails(self):
        data = sdg_summary()
        pa = data["land_condition"]["baseline"]["period_assessment"]
        set_area(pa["land_cover"]["summary"], "Stable", 900.0)
        self.assert_error(self.check(data), "baseline land cover")

    def test_non_water_larger_than_total_fails(self):
        data = sdg_summary()
        pa = data["land_condition"]["baseline"]["period_assessment"]
        set_area(pa["productivity"]["summaries"]["non_water"], "Stable", 2000.0)
        self.assert_error(self.check(data), "non-water area")

    def test_change_crosstab_not_summing_to_total_fails(self):
        data = sdg_summary()
        change = data["land_condition"]["report_1"]["change_assessment"]
        change["soil_organic_carbon"]["values"].pop()
        self.assert_error(self.check(data), "report_1 change soil_organic_carbon")

    def test_status_not_summing_to_total_fails(self):
        data = sdg_summary()
        status = data["land_condition"]["report_1"]["status_assessment"]
        set_area(status["sdg"], "Degraded", 0.0)
        self.assert_error(self.check(data), "report_1 status SDG")

    def test_high_nodata_fails_and_moderate_nodata_warns(self):
        data = sdg_summary()
        sdg = data["land_condition"]["baseline"]["period_assessment"]["sdg"]
        set_area(sdg["summary"], "Stable", 300.0)
        set_area(sdg["summary"], "No data", 450.0)
        report = self.check(data, aoi_area_km2=None)
        self.assert_error(report, "No data")

        report = self.check(sdg_summary(), thresholds=Thresholds(warn_nodata_frac=0.01))
        self.assertEqual(report.errors, [])
        self.assertTrue(any("No data" in w for w in report.warnings))

    def test_zero_stable_fails(self):
        data = sdg_summary()
        pa = data["land_condition"]["report_1"]["period_assessment"]
        set_area(pa["sdg"]["summary"], "Stable", 0.0)
        set_area(pa["sdg"]["summary"], "No data", 750.0)
        report = self.check(data, thresholds=Thresholds(max_nodata_frac=1.0))
        self.assert_error(report, "Stable area is zero")

    def test_missing_class_fails(self):
        data = sdg_summary()
        sdg = data["land_condition"]["baseline"]["period_assessment"]["sdg"]
        sdg["summary"]["areas"] = sdg["summary"]["areas"][:-1]
        self.assert_error(self.check(data), "missing classes")

    def test_invalid_values_fail(self):
        data = sdg_summary()
        sdg = data["land_condition"]["baseline"]["period_assessment"]["sdg"]
        set_area(sdg["summary"], "Improved", None)
        self.assert_error(self.check(data), "invalid value")
        data = sdg_summary()
        sdg = data["land_condition"]["baseline"]["period_assessment"]["sdg"]
        set_area(sdg["summary"], "Improved", -5.0)
        self.assert_error(self.check(data), "negative")

    def test_aoi_area_mismatch_fails(self):
        self.assert_error(self.check(sdg_summary(), aoi_area_km2=2000.0), "AOI area")

    def test_land_cover_transitions_checked_per_period(self):
        # One full-area crosstab per distinct transition period (e.g. when the
        # productivity period differs from the land cover period).
        data = sdg_summary()
        lc = data["land_condition"]["baseline"]["period_assessment"]["land_cover"]
        lc["crosstabs_by_land_cover_class"].append(
            crosstab({("Tree-covered", "Tree-covered"): 950.0})
        )
        self.assertEqual(self.check(data).errors, [])

        lc["crosstabs_by_land_cover_class"][1]["values"][0]["value"] = 1500.0
        self.assert_error(self.check(data), "baseline land cover transitions [1]")

    def test_productivity_crosstabs_summed_across_classes(self):
        data = sdg_summary()
        prod = data["land_condition"]["baseline"]["period_assessment"]["productivity"]
        prod["crosstabs_by_productivity_class"].append(
            crosstab({("Tree-covered", "Tree-covered"): 600.0})
        )
        self.assert_error(self.check(data), "productivity by land cover transition")

    def test_implausible_population_density_fails(self):
        data = sdg_summary()
        for period in ("baseline", "report_1"):
            data["affected_population"][period]["summary"] = population(1e8)
        self.assert_error(self.check(data), "population density")

    def test_land_cover_by_year_total_mismatch_fails(self):
        data = sdg_summary()
        lc = data["land_condition"]["baseline"]["period_assessment"]["land_cover"]
        lc["land_cover_areas_by_year"]["values"]["2015"]["Cropland"] = 500.0
        self.assert_error(self.check(data), "land cover area by year 2015")

    def test_single_land_cover_class_fails(self):
        data = sdg_summary()
        lc = data["land_condition"]["baseline"]["period_assessment"]["land_cover"]
        lc["land_cover_areas_by_year"]["values"]["2000"] = {
            "Tree-covered": 990.0,
            "No data": 10.0,
        }
        self.assert_error(self.check(data), "class(es) have values")

    def test_population_sex_mismatch_fails(self):
        data = sdg_summary()
        pop = data["affected_population"]["baseline"]["summary"]
        pop["Male population"]["values"][1]["population"] *= 3
        self.assert_error(self.check(data), "male + female")

    def test_missing_population_fails(self):
        data = sdg_summary()
        del data["affected_population"]["report_1"]
        self.assert_error(self.check(data), "report_1 population")

    def test_period_totals_must_match(self):
        data = sdg_summary()
        report_1 = copy.deepcopy(data["land_condition"]["report_1"])
        sdg = report_1["period_assessment"]["sdg"]["summary"]
        set_area(sdg, "Stable", 1700.0)
        data["land_condition"]["report_1"] = report_1
        self.assert_error(self.check(data), "report_1 total area vs baseline")

    def test_nearly_all_stable_or_degraded_warns(self):
        for cls, other in (("Stable", "Degraded"), ("Degraded", "Stable")):
            data = sdg_summary()
            sdg = data["land_condition"]["baseline"]["period_assessment"]["sdg"]
            set_area(sdg["summary"], cls, 920.0)
            set_area(sdg["summary"], other, 10.0)
            set_area(sdg["summary"], "Improved", 20.0)
            report = check_sdg_summary(data)
            self.assertTrue(
                any(f"of valid area is {cls}" in w for w in report.warnings),
                report.warnings,
            )

    def test_zero_degraded_and_baseline_only_warn(self):
        data = sdg_summary()
        del data["land_condition"]["report_1"]
        del data["affected_population"]["report_1"]
        sdg = data["land_condition"]["baseline"]["period_assessment"]["sdg"]
        set_area(sdg["summary"], "Degraded", 0.0)
        set_area(sdg["summary"], "Stable", 800.0)
        report = self.check(data)
        self.assertEqual(report.errors, [])
        self.assertTrue(any("Degraded area is zero" in w for w in report.warnings))
        self.assertTrue(any("reporting periods" in w for w in report.warnings))


class DroughtSummaryChecksTest(unittest.TestCase):
    def check(self, data, **kwargs):
        kwargs.setdefault("aoi_area_km2", TOTAL)
        return check_drought_summary(data, **kwargs)

    def assert_error(self, report, fragment):
        self.assertFalse(report.ok)
        self.assertTrue(
            any(fragment in e for e in report.errors),
            f"no error containing {fragment!r}: {report.errors}",
        )

    def test_valid_summary_passes(self):
        report = self.check(drought_summary())
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])
        self.assertEqual(report.metrics["years"], [2000, 2019])
        self.assertEqual(report.metrics["dvi"], 0.42)

    def test_missing_dvi_fails(self):
        data = drought_summary()
        data["drought"]["tier_three"]["2018"]["value"] = None
        self.assert_error(self.check(data), "vulnerability index is None")

    def test_dvi_out_of_range_fails(self):
        data = drought_summary()
        data["drought"]["tier_three"]["2018"]["value"] = 1.5
        self.assert_error(self.check(data), "outside 0-1")

    def test_inconsistent_year_total_fails(self):
        data = drought_summary()
        set_area(data["drought"]["tier_one"]["2010"], "Non-drought", 3000.0)
        self.assert_error(self.check(data), "2010 drought total area")

    def test_gap_in_years_fails(self):
        data = drought_summary()
        del data["drought"]["tier_one"]["2005"]
        self.assert_error(self.check(data), "not contiguous")

    def test_no_drought_in_any_year_fails(self):
        data = drought_summary()
        for areas in data["drought"]["tier_one"].values():
            for cls in ("Mild drought", "Moderate drought"):
                set_area(areas, cls, 0.0)
            set_area(areas, "Non-drought", TOTAL - 20.0)
        self.assert_error(self.check(data), "no area is in any drought class")

    def test_high_nodata_fails(self):
        data = drought_summary()
        areas = data["drought"]["tier_one"]["2001"]
        set_area(areas, "Non-drought", 400.0)
        set_area(areas, "No data", 600.0)
        self.assert_error(self.check(data), "2001 drought area")

    def test_missing_population_year_fails(self):
        data = drought_summary()
        del data["drought"]["tier_two"]["2019"]
        self.assert_error(self.check(data), "no population for years [2019]")

    def test_zero_population_fails(self):
        data = drought_summary()
        data["drought"]["tier_two"]["2003"] = population(total=0)
        self.assert_error(self.check(data), "population is zero")

    def test_aoi_mismatch_and_density_fail(self):
        self.assert_error(self.check(drought_summary(), aoi_area_km2=500.0), "AOI")
        data = drought_summary()
        for year in data["drought"]["tier_two"]:
            data["drought"]["tier_two"][year] = population(5)
        self.assert_error(self.check(data), "population density")


class ThresholdsTest(unittest.TestCase):
    def test_from_env(self):
        from unittest import mock

        env = {
            "TE_E2E_CHECK_AREA_TOL": "0.2",
            "TE_E2E_CHECK_MAX_NODATA_FRAC": "0.5",
            "TE_E2E_CHECK_WARN_NODATA_FRAC": "bad",
        }
        with mock.patch.dict("os.environ", env):
            thresholds = Thresholds.from_env()
        self.assertEqual(thresholds.area_tol, 0.2)
        self.assertEqual(thresholds.max_nodata_frac, 0.5)
        self.assertEqual(thresholds.warn_nodata_frac, Thresholds().warn_nodata_frac)


if __name__ == "__main__":
    unittest.main()
