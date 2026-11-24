"""Regression tests for deleting job datasets."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from LDMP.jobs import manager


class TestDeleteJobDatasets(unittest.TestCase):
    def test_deletes_dataset_only_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset_dir = Path(tmp) / "dataset"
            dataset_dir.mkdir()
            (dataset_dir / "result.tif").touch()
            job = SimpleNamespace(results=object())

            with (
                patch.object(manager.job_manager, "get_job_file_path") as get_path,
                patch.object(
                    manager.shutil, "rmtree", wraps=manager.shutil.rmtree
                ) as rm,
                patch("time.sleep") as sleep,
            ):
                get_path.return_value = dataset_dir / "job.json"
                manager._delete_job_datasets(job)

            self.assertFalse(dataset_dir.exists())
            rm.assert_called_once_with(str(dataset_dir))
            sleep.assert_not_called()

    def test_no_results_does_not_retry(self):
        job = SimpleNamespace(results=None)
        with (
            patch.object(manager, "log") as log,
            patch.object(manager.shutil, "rmtree") as rm,
            patch("time.sleep") as sleep,
        ):
            manager._delete_job_datasets(job)

        rm.assert_not_called()
        sleep.assert_not_called()
        log.assert_called_once_with(
            "This job has no results to be deleted, skipping..."
        )

    def test_reports_removal_failure_once(self):
        job = SimpleNamespace(results=object())
        with tempfile.TemporaryDirectory() as tmp:
            dataset_dir = Path(tmp) / "dataset"
            with (
                patch.object(
                    manager.job_manager,
                    "get_job_file_path",
                    return_value=dataset_dir / "job.json",
                ),
                patch.object(
                    manager.shutil, "rmtree", side_effect=OSError("cannot remove")
                ) as rm,
                patch.object(manager, "log") as log,
                patch("time.sleep") as sleep,
            ):
                manager._delete_job_datasets(job)

            rm.assert_called_once_with(str(dataset_dir))
            sleep.assert_not_called()
            log.assert_called_once_with(
                f"Could not remove directory {str(dataset_dir)!r}, skipping deletion..."
            )
