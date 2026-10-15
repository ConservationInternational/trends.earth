import unittest
from types import SimpleNamespace

from LDMP.calculate_ldn import (
    job_is_stale_for_subnational_unit,
    job_matches_subnational_unit,
    subnational_period_key,
)

NORTH = {"id": "unit-north", "name": "North"}
NORTH_EAST = {"id": "unit-north-east", "name": "North East"}


def _job(task_name="", params=None):
    return SimpleNamespace(task_name=task_name, params=params or {})


def _tagged_job(unit, period_name):
    return _job(
        task_name=f"{unit['name']} - {period_name}",
        params={
            "subnational_unit": {
                "id": unit["id"],
                "name": unit["name"],
                "geometry_hash": unit.get("geometry_hash"),
            },
            "period": {"name": period_name},
        },
    )


class SubnationalPeriodKeyTests(unittest.TestCase):
    def test_baseline_unchanged(self):
        self.assertEqual(subnational_period_key("baseline"), "baseline")

    def test_report_and_reporting_are_equivalent(self):
        self.assertEqual(
            subnational_period_key("report_2"), subnational_period_key("reporting_2")
        )

    def test_different_numbers_do_not_match(self):
        self.assertNotEqual(
            subnational_period_key("report_1"), subnational_period_key("reporting_11")
        )


class SubnationalJobMatchingTests(unittest.TestCase):
    def test_tagged_job_matches_own_unit_and_period(self):
        job = _tagged_job(NORTH, "reporting_1")

        self.assertTrue(job_matches_subnational_unit(job, NORTH, "report_1"))

    def test_tagged_job_does_not_match_unit_with_overlapping_name(self):
        job = _tagged_job(NORTH_EAST, "baseline")

        self.assertFalse(job_matches_subnational_unit(job, NORTH, "baseline"))
        self.assertTrue(job_matches_subnational_unit(job, NORTH_EAST, "baseline"))

    def test_tagged_job_matches_by_id_after_unit_rename(self):
        job = _tagged_job(NORTH, "baseline")
        renamed = {"id": NORTH["id"], "name": "Northern Woodland"}

        self.assertTrue(job_matches_subnational_unit(job, renamed, "baseline"))

    def test_tagged_job_does_not_match_other_period(self):
        job = _tagged_job(NORTH, "reporting_1")

        self.assertFalse(job_matches_subnational_unit(job, NORTH, "baseline"))
        self.assertFalse(job_matches_subnational_unit(job, NORTH, "report_11"))

    def test_any_period_when_period_not_given(self):
        job = _tagged_job(NORTH, "reporting_3")

        self.assertTrue(job_matches_subnational_unit(job, NORTH))
        self.assertFalse(job_matches_subnational_unit(job, NORTH_EAST))

    def test_untagged_job_falls_back_to_exact_task_name(self):
        job = _job(task_name="North East - baseline")

        self.assertFalse(job_matches_subnational_unit(job, NORTH, "baseline"))
        self.assertTrue(job_matches_subnational_unit(job, NORTH_EAST, "baseline"))

    def test_untagged_job_with_unrelated_task_name_does_not_match(self):
        job = _job(task_name="North baseline run")

        self.assertFalse(job_matches_subnational_unit(job, NORTH, "baseline"))
        self.assertFalse(job_matches_subnational_unit(job, NORTH))


if __name__ == "__main__":
    unittest.main()


class SubnationalStaleGeometryTests(unittest.TestCase):
    def test_job_for_unchanged_geometry_matches(self):
        unit = {**NORTH, "geometry_hash": "aaa"}
        job = _tagged_job(unit, "baseline")

        self.assertFalse(job_is_stale_for_subnational_unit(job, unit))
        self.assertTrue(job_matches_subnational_unit(job, unit, "baseline"))

    def test_job_for_edited_geometry_is_stale_and_does_not_match(self):
        job = _tagged_job({**NORTH, "geometry_hash": "aaa"}, "baseline")
        edited = {**NORTH, "geometry_hash": "bbb"}

        self.assertTrue(job_is_stale_for_subnational_unit(job, edited))
        self.assertFalse(job_matches_subnational_unit(job, edited, "baseline"))

    def test_stale_job_matches_when_stale_included(self):
        job = _tagged_job({**NORTH, "geometry_hash": "aaa"}, "baseline")
        edited = {**NORTH, "geometry_hash": "bbb"}

        self.assertTrue(
            job_matches_subnational_unit(job, edited, "baseline", include_stale=True)
        )

    def test_job_without_hash_is_never_stale(self):
        job = _tagged_job(NORTH, "baseline")
        edited = {**NORTH, "geometry_hash": "bbb"}

        self.assertFalse(job_is_stale_for_subnational_unit(job, edited))
        self.assertTrue(job_matches_subnational_unit(job, edited, "baseline"))

    def test_unit_without_hash_is_never_stale(self):
        job = _tagged_job({**NORTH, "geometry_hash": "aaa"}, "baseline")

        self.assertFalse(job_is_stale_for_subnational_unit(job, NORTH))


def _box(min_x, min_y, max_x, max_y):
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [min_x, min_y],
                [max_x, min_y],
                [max_x, max_y],
                [min_x, max_y],
                [min_x, min_y],
            ]
        ],
    }


class SubnationalLegacyBoundingBoxTests(unittest.TestCase):
    """Jobs submitted before geometry hashes existed are compared by bbox."""

    def _legacy_job(self, bbox):
        job = _tagged_job(NORTH, "baseline")
        job.params["subnational_unit"].pop("geometry_hash")
        job.params["geojsons"] = [bbox]
        return job

    def test_same_bbox_is_not_stale(self):
        job = self._legacy_job(_box(0, 0, 1, 1))
        unit = {**NORTH, "geometry_hash": "bbb"}

        self.assertFalse(
            job_is_stale_for_subnational_unit(job, unit, [_box(0, 0, 1, 1)])
        )

    def test_different_bbox_is_stale(self):
        job = self._legacy_job(_box(0, 0, 1, 1))
        unit = {**NORTH, "geometry_hash": "bbb"}

        self.assertTrue(
            job_is_stale_for_subnational_unit(job, unit, [_box(5, 5, 6, 6)])
        )
        self.assertFalse(
            job_matches_subnational_unit(
                job, unit, "baseline", unit_bbox=[_box(5, 5, 6, 6)]
            )
        )

    def test_geojsons_as_json_string(self):
        import json

        job = self._legacy_job(_box(0, 0, 1, 1))
        job.params["geojsons"] = json.dumps([_box(0, 0, 1, 1)])

        self.assertFalse(
            job_is_stale_for_subnational_unit(job, NORTH, [_box(0, 0, 1, 1)])
        )

    def test_without_unit_bbox_legacy_job_is_not_stale(self):
        job = self._legacy_job(_box(0, 0, 1, 1))

        self.assertFalse(job_is_stale_for_subnational_unit(job, NORTH))

    def test_untagged_name_matched_job_with_other_bbox_is_stale(self):
        job = _job(
            task_name="North - baseline", params={"geojsons": [_box(0, 0, 1, 1)]}
        )

        self.assertTrue(job_matches_subnational_unit(job, NORTH, "baseline"))
        self.assertFalse(
            job_matches_subnational_unit(
                job, NORTH, "baseline", unit_bbox=[_box(5, 5, 6, 6)]
            )
        )
        self.assertTrue(
            job_matches_subnational_unit(
                job, NORTH, "baseline", include_stale=True, unit_bbox=[_box(5, 5, 6, 6)]
            )
        )

    def test_untagged_name_matched_job_with_same_bbox_matches(self):
        job = _job(
            task_name="North - baseline", params={"geojsons": [_box(0, 0, 1, 1)]}
        )

        self.assertTrue(
            job_matches_subnational_unit(
                job, NORTH, "baseline", unit_bbox=[_box(0, 0, 1, 1)]
            )
        )
