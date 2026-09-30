import unittest
from types import SimpleNamespace

from LDMP.calculate_ldn import job_matches_subnational_unit, subnational_period_key

NORTH = {"id": "unit-north", "name": "North"}
NORTH_EAST = {"id": "unit-north-east", "name": "North East"}


def _job(task_name="", params=None):
    return SimpleNamespace(task_name=task_name, params=params or {})


def _tagged_job(unit, period_name):
    return _job(
        task_name=f"{unit['name']} - {period_name}",
        params={
            "subnational_unit": {"id": unit["id"], "name": unit["name"]},
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
