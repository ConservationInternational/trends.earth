"""Test for bug fix: AttributeError when job.start_date is None in filterAcceptsRow"""

import datetime
import unittest
import uuid
from unittest.mock import Mock

from qgis.PyQt import QtCore
from te_schemas.jobs import JobStatus
from utilities_for_testing import get_qgis_app

from LDMP.jobs.models import Job, SortField, TypeFilter

# Import the classes we need to test
from LDMP.jobs.mvc import JobsSortFilterProxyModel

QGIS_APP = get_qgis_app()


def create_mock_job(
    job_id=None, start_date=None, end_date=None, status=JobStatus.FINISHED
):
    """Create a mock Job object for testing"""
    if job_id is None:
        job_id = uuid.uuid4()

    job = Mock(spec=Job)
    job.id = job_id
    job.start_date = start_date
    job.end_date = end_date
    job.status = status
    job.task_name = "Test Task"
    job.script = None
    job.visible_name = "Test Job"

    # Mock the local_context attribute
    job.local_context = Mock()
    job.local_context.area_of_interest_name = "Test Area"

    # Mock methods that might be called
    job.is_raster = Mock(return_value=True)
    job.is_vector = Mock(return_value=False)

    return job


class SimpleJobsModel(QtCore.QAbstractItemModel):
    """Simple test model for testing the proxy filter"""

    def __init__(self, jobs, parent=None):
        super().__init__(parent)
        self.jobs = jobs

    def index(self, row, column, parent=QtCore.QModelIndex()):
        if not self.hasIndex(row, column, parent):
            return QtCore.QModelIndex()
        # Use internalPointer to store the job object, like the real JobsModel does
        job = self.jobs[row] if row < len(self.jobs) else None
        return self.createIndex(row, column, job)

    def parent(self, index):
        return QtCore.QModelIndex()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self.jobs) if not parent.isValid() else 0

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 1

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None

        # Get the job from internalPointer, like the real JobsModel does
        job = index.internalPointer()

        # Return job for DisplayRole, matching the real JobsModel behavior
        if role == QtCore.Qt.DisplayRole or role == QtCore.Qt.ItemDataRole:
            return job

        return None


class TestJobsFilterNoneDates(unittest.TestCase):
    """Test suite for jobs filtering with None dates"""

    def test_filter_accepts_row_with_none_start_date(self):
        """Test that filterAcceptsRow handles None start_date without crashing"""
        # Create a job with None start_date (this is the bug scenario)
        job_with_none_start = create_mock_job(
            start_date=None, end_date=datetime.datetime(2025, 10, 1, 12, 0, 0)
        )

        # Create a simple test model
        source_model = SimpleJobsModel([job_with_none_start])

        # Create proxy model
        proxy = JobsSortFilterProxyModel(SortField.DATE)
        proxy.setSourceModel(source_model)
        proxy.type_filter = TypeFilter.ALL
        proxy.setFilterRegExp(".*")

        # Set date filter
        start_filter = QtCore.QDateTime.fromString(
            "2025-01-01 00:00:00", "yyyy-MM-dd HH:mm:ss"
        )
        end_filter = QtCore.QDateTime.fromString(
            "2025-12-31 23:59:59", "yyyy-MM-dd HH:mm:ss"
        )
        proxy.start_date = start_filter
        proxy.end_date = end_filter

        # This should NOT raise an AttributeError
        try:
            result = proxy.filterAcceptsRow(0, QtCore.QModelIndex())
            # When dates are filtered and job has None date, it should not match
            self.assertIn(result, [True, False])  # Just ensure no crash
        except AttributeError as e:
            self.fail(
                f"filterAcceptsRow raised AttributeError with None start_date: {e}"
            )

    def test_filter_accepts_row_with_none_end_date(self):
        """Test that filterAcceptsRow handles None end_date without crashing"""
        # Create a job with None end_date
        job_with_none_end = create_mock_job(
            start_date=datetime.datetime(2025, 1, 1, 12, 0, 0), end_date=None
        )

        # Create a simple test model
        source_model = SimpleJobsModel([job_with_none_end])

        # Create proxy model
        proxy = JobsSortFilterProxyModel(SortField.DATE)
        proxy.setSourceModel(source_model)
        proxy.type_filter = TypeFilter.ALL
        proxy.setFilterRegExp(".*")

        # Set date filter
        start_filter = QtCore.QDateTime.fromString(
            "2025-01-01 00:00:00", "yyyy-MM-dd HH:mm:ss"
        )
        end_filter = QtCore.QDateTime.fromString(
            "2025-12-31 23:59:59", "yyyy-MM-dd HH:mm:ss"
        )
        proxy.start_date = start_filter
        proxy.end_date = end_filter

        # This should NOT raise an AttributeError
        try:
            result = proxy.filterAcceptsRow(0, QtCore.QModelIndex())
            self.assertIn(result, [True, False])  # Just ensure no crash
        except AttributeError as e:
            self.fail(f"filterAcceptsRow raised AttributeError with None end_date: {e}")

    def test_filter_accepts_row_with_both_dates_none(self):
        """Test that filterAcceptsRow handles both dates being None"""
        # Create a job with both dates None
        job_with_none_dates = create_mock_job(start_date=None, end_date=None)

        # Create a simple test model
        source_model = SimpleJobsModel([job_with_none_dates])

        # Create proxy model
        proxy = JobsSortFilterProxyModel(SortField.DATE)
        proxy.setSourceModel(source_model)
        proxy.type_filter = TypeFilter.ALL
        proxy.setFilterRegExp(".*")

        # Set date filter
        start_filter = QtCore.QDateTime.fromString(
            "2025-01-01 00:00:00", "yyyy-MM-dd HH:mm:ss"
        )
        end_filter = QtCore.QDateTime.fromString(
            "2025-12-31 23:59:59", "yyyy-MM-dd HH:mm:ss"
        )
        proxy.start_date = start_filter
        proxy.end_date = end_filter

        # This should NOT raise an AttributeError
        try:
            result = proxy.filterAcceptsRow(0, QtCore.QModelIndex())
            self.assertIn(result, [True, False])  # Just ensure no crash
        except AttributeError as e:
            self.fail(
                f"filterAcceptsRow raised AttributeError with both dates None: {e}"
            )

    def test_filter_accepts_row_with_valid_dates(self):
        """Test that filtering works correctly with valid dates"""
        # Create a job within the date range
        job_in_range = create_mock_job(
            start_date=datetime.datetime(2025, 1, 15, 12, 0, 0),
            end_date=datetime.datetime(2025, 1, 16, 12, 0, 0),
        )

        # Create a simple test model
        source_model = SimpleJobsModel([job_in_range])

        # Create proxy model
        proxy = JobsSortFilterProxyModel(SortField.DATE)
        proxy.setSourceModel(source_model)
        proxy.type_filter = TypeFilter.ALL
        proxy.setFilterRegExp(".*")

        # Set date filter for January 2025
        start_filter = QtCore.QDateTime.fromString(
            "2025-01-01 00:00:00", "yyyy-MM-dd HH:mm:ss"
        )
        end_filter = QtCore.QDateTime.fromString(
            "2025-01-31 23:59:59", "yyyy-MM-dd HH:mm:ss"
        )
        proxy.start_date = start_filter
        proxy.end_date = end_filter

        # This should accept the row (job is within date range)
        result = proxy.filterAcceptsRow(0, QtCore.QModelIndex())
        self.assertTrue(result)

    def test_filter_rejects_row_outside_date_range(self):
        """Test that filtering rejects jobs outside the date range"""
        # Create a job outside the date range (February)
        job_out_of_range = create_mock_job(
            start_date=datetime.datetime(2025, 2, 15, 12, 0, 0),
            end_date=datetime.datetime(2025, 2, 16, 12, 0, 0),
        )

        # Create a simple test model
        source_model = SimpleJobsModel([job_out_of_range])

        # Create proxy model
        proxy = JobsSortFilterProxyModel(SortField.DATE)
        proxy.setSourceModel(source_model)
        proxy.type_filter = TypeFilter.ALL
        proxy.setFilterRegExp(".*")

        # Set date filter for January 2025
        start_filter = QtCore.QDateTime.fromString(
            "2025-01-01 00:00:00", "yyyy-MM-dd HH:mm:ss"
        )
        end_filter = QtCore.QDateTime.fromString(
            "2025-01-31 23:59:59", "yyyy-MM-dd HH:mm:ss"
        )
        proxy.start_date = start_filter
        proxy.end_date = end_filter

        # This should reject the row (job is outside date range)
        result = proxy.filterAcceptsRow(0, QtCore.QModelIndex())
        self.assertFalse(result)
