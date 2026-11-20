import datetime as dt
import unittest
import uuid
from types import SimpleNamespace

from LDMP.calculate_ldn import group_subnational_runs

UNITS = [
    {"id": "u-amazonia", "name": "Amazonia", "geometry_hash": "a1"},
    {"id": "u-cerrado", "name": "Cerrado", "geometry_hash": "c1"},
    {"id": "u-pantanal", "name": "Pantanal", "geometry_hash": "p1"},
]
T0 = dt.datetime(2026, 10, 20, 16, 43, tzinfo=dt.UTC)


def _job(unit, period="baseline", start=T0, run_id=None, geometry_hash=None):
    tag = {
        "id": unit["id"],
        "name": unit["name"],
        "geometry_hash": geometry_hash or unit["geometry_hash"],
    }
    if run_id:
        tag["run_id"] = run_id
    return SimpleNamespace(
        id=uuid.uuid4(),
        task_name=f"{unit['name']} - {period}",
        start_date=start,
        params={"subnational_unit": tag, "period": {"name": period}},
    )


def _run_jobs(run_id, start=T0, units=UNITS, period="baseline", **kwargs):
    return [
        _job(u, period, start + dt.timedelta(seconds=i), run_id, **kwargs)
        for i, u in enumerate(units)
    ]


class GroupSubnationalRunsTests(unittest.TestCase):
    def test_one_submission_is_one_complete_run(self):
        runs = group_subnational_runs(_run_jobs("r1"), UNITS)

        self.assertEqual(len(runs), 1)
        self.assertTrue(runs[0].complete)
        self.assertEqual(set(runs[0].jobs_by_unit), {u["id"] for u in UNITS})
        self.assertEqual(runs[0].period_key, "baseline")
        self.assertEqual(runs[0].run_id, "r1")

    def test_runs_with_different_ids_stay_separate_most_recent_first(self):
        later = T0 + dt.timedelta(days=1)
        jobs = _run_jobs("r1") + _run_jobs("r2", start=later)

        runs = group_subnational_runs(jobs, UNITS)

        self.assertEqual([r.run_id for r in runs], ["r2", "r1"])
        self.assertTrue(all(r.complete for r in runs))

    def test_missing_unit_makes_run_incomplete(self):
        runs = group_subnational_runs(_run_jobs("r1", units=UNITS[:2]), UNITS)

        self.assertEqual(len(runs), 1)
        self.assertFalse(runs[0].complete)
        self.assertEqual(runs[0].missing_units, ["Pantanal"])
        self.assertEqual(set(runs[0].jobs_by_unit), {"u-amazonia", "u-cerrado"})

    def test_periods_are_separate_runs(self):
        jobs = _run_jobs("r1") + _run_jobs("r1", period="reporting_1")

        runs = group_subnational_runs(jobs, UNITS)

        self.assertEqual({r.period_key for r in runs}, {"baseline", "reporting_1"})
        self.assertEqual(len(runs), 2)

    def test_report_and_reporting_period_names_are_one_period(self):
        jobs = _run_jobs("r1", period="reporting_1")
        jobs[0].params["period"]["name"] = "report_1"

        runs = group_subnational_runs(jobs, UNITS)

        self.assertEqual(len(runs), 1)
        self.assertTrue(runs[0].complete)

    def test_unit_with_changed_boundary_is_stale(self):
        jobs = _run_jobs("r1", units=UNITS[:2]) + [
            _job(UNITS[2], run_id="r1", geometry_hash="old-boundary")
        ]

        runs = group_subnational_runs(jobs, UNITS)

        self.assertEqual(len(runs), 1)
        self.assertFalse(runs[0].complete)
        self.assertEqual(runs[0].stale_units, ["Pantanal"])
        self.assertEqual(runs[0].missing_units, [])

    def test_run_where_everything_is_stale_is_dropped(self):
        jobs = _run_jobs("r1", geometry_hash="old-boundary")

        self.assertEqual(group_subnational_runs(jobs, UNITS), [])

    def test_latest_result_of_a_unit_wins_within_a_run(self):
        first = _job(UNITS[0], run_id="r1", start=T0)
        second = _job(UNITS[0], run_id="r1", start=T0 + dt.timedelta(seconds=30))
        jobs = [first, second] + _run_jobs("r1", units=UNITS[1:])

        runs = group_subnational_runs(jobs, UNITS)

        self.assertIs(runs[0].jobs_by_unit["u-amazonia"], second)

    def test_old_jobs_without_run_id_are_grouped_by_start_time(self):
        jobs = _run_jobs(None) + _run_jobs(None, start=T0 + dt.timedelta(hours=3))

        runs = group_subnational_runs(jobs, UNITS)

        self.assertEqual(len(runs), 2)
        self.assertTrue(all(r.complete and r.run_id is None for r in runs))

    def test_old_jobs_started_seconds_apart_are_one_run(self):
        runs = group_subnational_runs(_run_jobs(None), UNITS)

        self.assertEqual(len(runs), 1)
        self.assertTrue(runs[0].complete)

    def test_jobs_of_other_units_are_ignored(self):
        stranger = {"id": "u-other", "name": "Other", "geometry_hash": "x"}
        jobs = _run_jobs("r1") + [_job(stranger, run_id="r1")]

        runs = group_subnational_runs(jobs, UNITS)

        self.assertEqual(len(runs), 1)
        self.assertEqual(set(runs[0].jobs_by_unit), {u["id"] for u in UNITS})

    def test_no_jobs_no_runs(self):
        self.assertEqual(group_subnational_runs([], UNITS), [])


if __name__ == "__main__":
    unittest.main()
