"""Offline tests for e2e remote-submission recovery (no API access needed)."""

import unittest
from unittest import mock

from . import harness


class FakeClient:
    def __init__(self, records):
        self._records = list(records)
        self.last_response = None

    def advance(self):
        self.last_response = self._records.pop(0)

    def describe_last_response(self):
        r = self.last_response
        return f"{r['method']} {r['endpoint']} -> HTTP {r['status']}"


def _record(status, retry_after=None):
    return {
        "method": "POST",
        "endpoint": "/api/v1/script/x/run",
        "status": status,
        "body": "",
        "retry_after": retry_after,
    }


class SubmitWithRecoveryTest(unittest.TestCase):
    def setUp(self):
        patches = [
            mock.patch.object(harness, "say"),
            mock.patch.object(harness, "process_events_for"),
        ]
        for p in patches:
            self.addCleanup(p.stop)
        self.say = patches[0].start()
        self.sleep = patches[1].start()

    def _run(self, records, submit_results, found=None):
        client = FakeClient(records)
        results = list(submit_results)

        def submit(params, script_id):
            job = results.pop(0)
            if job is None:
                client.advance()
            return job

        with (
            mock.patch.object(
                harness,
                "_last_api_response",
                side_effect=lambda: (
                    client.last_response,
                    client.describe_last_response(),
                ),
            ),
            mock.patch.object(
                harness, "find_submitted_execution", return_value=found
            ) as find,
            mock.patch.object(harness.job_manager, "write_job_metadata_file"),
            mock.patch.object(
                harness.job_manager, "_update_known_jobs_with_newly_submitted_job"
            ),
        ):
            out = harness.submit_with_recovery(submit, {"task_name": "t"}, "sid")
        return out, find

    def test_success_first_try(self):
        (job, failure), find = self._run([], ["JOB"])
        self.assertEqual(job, "JOB")
        self.assertIsNone(failure)
        find.assert_not_called()

    def test_accepted_by_server_despite_client_failure(self):
        found = mock.Mock(id="abc")
        (job, failure), _ = self._run([_record(200)], [None], found=found)
        self.assertIs(job, found)
        self.assertIsNone(failure)
        self.sleep.assert_not_called()

    def test_rate_limited_then_retried(self):
        (job, failure), _ = self._run([_record(429, retry_after=5)], [None, "JOB"])
        self.assertEqual(job, "JOB")
        self.assertIsNone(failure)
        self.sleep.assert_called_once_with(5)

    def test_real_rejection_reports_status(self):
        (job, failure), _ = self._run([_record(400)], [None])
        self.assertIsNone(job)
        self.assertIn("HTTP 400", failure)
        self.sleep.assert_not_called()

    def test_gives_up_after_max_attempts(self):
        with mock.patch.dict("os.environ", {"TE_E2E_SUBMIT_ATTEMPTS": "2"}):
            (job, failure), _ = self._run(
                [_record(503, retry_after=1), _record(503, retry_after=1)],
                [None, None],
            )
        self.assertIsNone(job)
        self.assertIn("HTTP 503", failure)
        self.assertEqual(self.sleep.call_count, 1)

    def test_excessive_retry_after_is_not_waited(self):
        (job, failure), _ = self._run([_record(429, retry_after=86400)], [None])
        self.assertIsNone(job)
        self.assertIn("exceeds the retry limit", failure)
        self.sleep.assert_not_called()


class RemoteStatusTest(unittest.TestCase):
    """API lifecycle: PENDING (incl. queued) -> READY -> RUNNING -> terminal."""

    IN_PROGRESS = ("PENDING", "READY", "RUNNING", "CANCELLING")

    def test_in_progress_statuses_are_not_terminal(self):
        for name in self.IN_PROGRESS:
            status = harness.JobStatus[name]
            self.assertNotIn(status, harness.REMOTE_TERMINAL_STATUSES)
            self.assertNotIn(status, harness.REMOTE_SUCCESS_STATUSES)

    def test_server_terminal_statuses(self):
        for name in ("FINISHED", "FAILED", "CANCELLED"):
            self.assertIn(harness.JobStatus[name], harness.REMOTE_TERMINAL_STATUSES)

    def test_in_progress_at_timeout_is_not_reported_as_failed(self):
        for name in self.IN_PROGRESS:
            text = harness.describe_remote_outcome(harness.JobStatus[name], 240)
            self.assertIn(f"still {name.lower()}", text)
            self.assertIn("not failed", text)
        self.assertEqual(
            harness.describe_remote_outcome(harness.JobStatus.FAILED, 240),
            "ended as failed",
        )


if __name__ == "__main__":
    unittest.main()
