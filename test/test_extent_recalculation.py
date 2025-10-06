"""Tests for extent recalculation functionality"""

import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from te_schemas.jobs import Job, JobStatus
from te_schemas.results import (
    URI,
    Band,
    DataType,
    Raster,
    RasterFileType,
    RasterResults,
    RasterType,
    TiledRaster,
    VectorFalsePositive,
    VectorResults,
    VectorType,
)
from utilities_for_testing import get_qgis_app

QGIS_APP = get_qgis_app()


class TestExtentRecalculation(unittest.TestCase):
    """Test suite for extent recalculation features"""

    def setUp(self):
        """Set up test fixtures"""
        # Import here to ensure QGIS is initialized
        from LDMP.jobs.manager import (
            _get_extent_tuple_raster,
            _get_extent_tuple_vector,
            _set_results_extents_raster,
            _set_results_extents_vector,
            set_results_extents,
        )

        self.set_results_extents = set_results_extents
        self._set_results_extents_raster = _set_results_extents_raster
        self._set_results_extents_vector = _set_results_extents_vector
        self._get_extent_tuple_raster = _get_extent_tuple_raster
        self._get_extent_tuple_vector = _get_extent_tuple_vector

    def create_mock_job_with_raster_results(
        self, extent=None, raster_type=RasterType.ONE_FILE_RASTER
    ):
        """Create a mock job with raster results for testing"""
        job = Mock(spec=Job)
        job.id = "test-job-id"
        job.status = JobStatus.DOWNLOADED

        # Create raster with specific extent
        if raster_type == RasterType.ONE_FILE_RASTER:
            raster = Raster(
                uri=URI(uri=Path("/fake/path/raster.tif")),
                bands=[Band(name="test", metadata={})],
                datatype=DataType.INT16,
                filetype=RasterFileType.GEOTIFF,
                extent=extent,
            )
        else:  # TILED_RASTER
            raster = TiledRaster(
                tile_uris=[
                    URI(uri=Path("/fake/path/tile1.tif")),
                    URI(uri=Path("/fake/path/tile2.tif")),
                ],
                bands=[Band(name="test", metadata={})],
                datatype=DataType.INT16,
                filetype=RasterFileType.GEOTIFF,
                extents=[extent] if extent else None,
            )

        # Create raster results
        job.results = RasterResults(
            name="test_results", rasters={"test_raster": raster}
        )

        return job

    def create_mock_job_with_vector_results(self, extent=None):
        """Create a mock job with vector results for testing"""
        job = Mock(spec=Job)
        job.id = "test-vector-job-id"
        job.status = JobStatus.DOWNLOADED

        # Create vector results
        job.results = VectorResults(
            name="test_vector_results",
            vector=VectorFalsePositive(
                uri=URI(uri=Path("/fake/path/vector.geojson")),
                type=VectorType.ERROR_RECODE,
            ),
            extent=extent,
        )

        return job

    def test_set_results_extents_when_extent_is_none(self):
        """Test that set_results_extents calculates extent when it's None"""
        job = self.create_mock_job_with_raster_results(extent=None)

        with patch("LDMP.jobs.manager._get_extent_tuple_raster") as mock_get_extent:
            mock_get_extent.return_value = (0.0, 0.0, 10.0, 10.0)

            self._set_results_extents_raster(job)

            # Verify extent was calculated
            mock_get_extent.assert_called_once()
            self.assertEqual(
                job.results.rasters["test_raster"].extent, (0.0, 0.0, 10.0, 10.0)
            )

    def test_set_results_extents_preserves_existing_extent(self):
        """Test that set_results_extents preserves existing extent when force=False"""
        existing_extent = (1.0, 1.0, 5.0, 5.0)
        job = self.create_mock_job_with_raster_results(extent=existing_extent)

        with patch("LDMP.jobs.manager._get_extent_tuple_raster") as mock_get_extent:
            mock_get_extent.return_value = (0.0, 0.0, 10.0, 10.0)

            self._set_results_extents_raster(job, force=False)

            # Verify extent was NOT recalculated
            mock_get_extent.assert_not_called()
            self.assertEqual(job.results.rasters["test_raster"].extent, existing_extent)

    def test_set_results_extents_force_recalculates_extent(self):
        """Test that force=True recalculates extent even when it exists"""
        existing_extent = (1.0, 1.0, 5.0, 5.0)
        job = self.create_mock_job_with_raster_results(extent=existing_extent)

        with patch("LDMP.jobs.manager._get_extent_tuple_raster") as mock_get_extent:
            new_extent = (0.0, 0.0, 10.0, 10.0)
            mock_get_extent.return_value = new_extent

            self._set_results_extents_raster(job, force=True)

            # Verify extent was recalculated
            mock_get_extent.assert_called_once()
            self.assertEqual(job.results.rasters["test_raster"].extent, new_extent)

    def test_set_results_extents_tiled_raster(self):
        """Test extent calculation for tiled rasters"""
        job = self.create_mock_job_with_raster_results(
            extent=None, raster_type=RasterType.TILED_RASTER
        )

        with patch("LDMP.jobs.manager._get_extent_tuple_raster") as mock_get_extent:
            # Return different extents for each tile
            mock_get_extent.side_effect = [(0.0, 0.0, 5.0, 5.0), (5.0, 0.0, 10.0, 5.0)]

            self._set_results_extents_raster(job)

            # Verify extent was calculated for both tiles
            self.assertEqual(mock_get_extent.call_count, 2)
            self.assertEqual(len(job.results.rasters["test_raster"].extents), 2)
            self.assertIn(
                (0.0, 0.0, 5.0, 5.0), job.results.rasters["test_raster"].extents
            )
            self.assertIn(
                (5.0, 0.0, 10.0, 5.0), job.results.rasters["test_raster"].extents
            )

    def test_set_results_extents_vector(self):
        """Test extent calculation for vector results"""
        job = self.create_mock_job_with_vector_results(extent=None)

        with patch("LDMP.jobs.manager._get_extent_tuple_vector") as mock_get_extent:
            mock_get_extent.return_value = (-5.0, -5.0, 5.0, 5.0)

            self._set_results_extents_vector(job)

            # Verify extent was calculated
            mock_get_extent.assert_called_once()
            self.assertEqual(job.results.extent, (-5.0, -5.0, 5.0, 5.0))

    def test_set_results_extents_main_function_raster(self):
        """Test the main set_results_extents function with raster results"""
        job = self.create_mock_job_with_raster_results(extent=None)

        with patch("LDMP.jobs.manager._set_results_extents_raster") as mock_set:
            self.set_results_extents(job)
            mock_set.assert_called_once_with(job, force=False)

    def test_set_results_extents_main_function_vector(self):
        """Test the main set_results_extents function with vector results"""
        job = self.create_mock_job_with_vector_results(extent=None)

        with patch("LDMP.jobs.manager._set_results_extents_vector") as mock_set:
            self.set_results_extents(job)
            mock_set.assert_called_once_with(job, force=False)

    def test_set_results_extents_with_force_parameter(self):
        """Test that force parameter is passed through correctly"""
        job = self.create_mock_job_with_raster_results(extent=(1.0, 1.0, 5.0, 5.0))

        with patch("LDMP.jobs.manager._set_results_extents_raster") as mock_set:
            self.set_results_extents(job, force=True)
            mock_set.assert_called_once_with(job, force=True)

    def test_set_results_extents_skips_when_no_results(self):
        """Test that function handles jobs with no results gracefully"""
        job = Mock(spec=Job)
        job.results = None

        # Should not raise an exception
        self.set_results_extents(job)

    def test_set_results_extents_skips_wrong_status(self):
        """Test that function only processes downloaded/locally generated jobs"""
        job = self.create_mock_job_with_raster_results(extent=None)
        job.status = JobStatus.PENDING

        with patch("LDMP.jobs.manager._get_extent_tuple_raster") as mock_get_extent:
            self.set_results_extents(job)

            # Should not calculate extent for pending jobs
            mock_get_extent.assert_not_called()


class TestExtentAsGeom(unittest.TestCase):
    """Test suite for _extent_as_geom validation"""

    def setUp(self):
        """Set up test fixtures"""
        from LDMP.data_io import _extent_as_geom

        self._extent_as_geom = _extent_as_geom

    def test_extent_as_geom_with_valid_extent(self):
        """Test that valid extent creates geometry correctly"""
        extent = (0.0, 0.0, 10.0, 10.0)
        geom = self._extent_as_geom(extent)
        self.assertIsNotNone(geom)
        if geom is not None:
            self.assertTrue(geom.isGeosValid())

    def test_extent_as_geom_with_none(self):
        """Test that None extent returns None"""
        geom = self._extent_as_geom(None)
        self.assertIsNone(geom)

    def test_extent_as_geom_with_none_values(self):
        """Test that extent with None values returns None"""
        extent = (0.0, None, 10.0, 10.0)
        geom = self._extent_as_geom(extent)
        self.assertIsNone(geom)

    def test_extent_as_geom_with_nan_values(self):
        """Test that extent with NaN values returns None"""
        extent = (0.0, 0.0, float("nan"), 10.0)
        geom = self._extent_as_geom(extent)
        self.assertIsNone(geom)

    def test_extent_as_geom_with_inf_values(self):
        """Test that extent with Inf values returns None"""
        extent = (0.0, 0.0, float("inf"), 10.0)
        geom = self._extent_as_geom(extent)
        self.assertIsNone(geom)

    def test_extent_as_geom_with_wrong_length(self):
        """Test that extent with wrong number of values returns None"""
        extent = (0.0, 0.0, 10.0)  # Only 3 values instead of 4
        geom = self._extent_as_geom(extent)
        self.assertIsNone(geom)

    def test_extent_as_geom_with_empty_tuple(self):
        """Test that empty extent returns None"""
        extent = ()
        geom = self._extent_as_geom(extent)
        self.assertIsNone(geom)


class TestAutoExtentRecalculation(unittest.TestCase):
    """Test suite for automatic extent recalculation on job import"""

    def setUp(self):
        """Set up test fixtures"""
        # Import will be done in tests to avoid issues if module isn't available
        pass

    def create_mock_job_with_raster_results(
        self, extent=None, raster_type=RasterType.ONE_FILE_RASTER
    ):
        """Create a mock job with raster results for testing"""
        job = Mock(spec=Job)
        job.id = "test-job-id"
        job.status = JobStatus.DOWNLOADED

        # Create raster with specific extent
        if raster_type == RasterType.ONE_FILE_RASTER:
            raster = Raster(
                uri=URI(uri=Path("/fake/path/raster.tif")),
                bands=[Band(name="test", metadata={})],
                datatype=DataType.INT16,
                filetype=RasterFileType.GEOTIFF,
                extent=extent,
            )
        else:  # TILED_RASTER
            raster = TiledRaster(
                tile_uris=[
                    URI(uri=Path("/fake/path/tile1.tif")),
                    URI(uri=Path("/fake/path/tile2.tif")),
                ],
                bands=[Band(name="test", metadata={})],
                datatype=DataType.INT16,
                filetype=RasterFileType.GEOTIFF,
                extents=[extent] if extent else None,
            )

        # Create raster results
        job.results = RasterResults(
            name="test_results", rasters={"test_raster": raster}
        )

        return job

    def test_parse_chosen_path_detects_missing_extent(self):
        """Test that parse_chosen_path detects and recalculates missing extents"""
        # Import here to handle potential import errors
        try:
            import json
            import tempfile

            from LDMP.data_io import DlgDataIOLoadTE
        except ImportError:
            self.skipTest("LDMP.data_io module not available")

        # Create a mock job with None extent
        mock_job = self.create_mock_job_with_raster_results(extent=None)

        # Create a temporary JSON file (content doesn't matter, we'll mock the load)
        job_data = {"id": "test-job"}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(job_data, f)
            temp_file = f.name

        try:
            dialog = DlgDataIOLoadTE()

            with patch("LDMP.data_io.Job.Schema") as mock_job_schema:
                # Mock the Job.Schema().load() to return our mock job
                mock_schema_instance = Mock()
                mock_schema_instance.load.return_value = mock_job
                mock_job_schema.return_value = mock_schema_instance

                with patch("LDMP.data_io.set_results_extents") as mock_set_extents:
                    with patch("LDMP.data_io.update_uris_if_needed"):
                        job, error = dialog.parse_chosen_path(temp_file)

                        # Verify that set_results_extents was called with force=True
                        # because missing extent was detected
                        self.assertTrue(mock_set_extents.called)
                        call_args = mock_set_extents.call_args

                        # Check if force=True was used
                        called_with_force = False
                        if len(call_args) > 1:  # Has both args and kwargs
                            if len(call_args[0]) > 1:  # positional force arg
                                called_with_force = call_args[0][1]
                            elif call_args[1]:  # kwargs
                                called_with_force = call_args[1].get("force", False)

                        self.assertTrue(
                            called_with_force,
                            "set_results_extents should be called with force=True for missing extents",
                        )

        finally:
            os.unlink(temp_file)

    def test_parse_chosen_path_skips_recalc_for_valid_extents(self):
        """Test that parse_chosen_path doesn't recalculate when extents are valid"""
        try:
            import json
            import tempfile

            from LDMP.data_io import DlgDataIOLoadTE
        except ImportError:
            self.skipTest("LDMP.data_io module not available")

        # Create a mock job with valid extent
        valid_extent = (0.0, 0.0, 10.0, 10.0)
        mock_job = self.create_mock_job_with_raster_results(extent=valid_extent)

        # Create a temporary JSON file (content doesn't matter, we'll mock the load)
        job_data = {"id": "test-job"}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(job_data, f)
            temp_file = f.name

        try:
            dialog = DlgDataIOLoadTE()

            with patch("LDMP.data_io.Job.Schema") as mock_job_schema:
                # Mock the Job.Schema().load() to return our mock job
                mock_schema_instance = Mock()
                mock_schema_instance.load.return_value = mock_job
                mock_job_schema.return_value = mock_schema_instance

                with patch("LDMP.data_io.set_results_extents") as mock_set_extents:
                    with patch("LDMP.data_io.update_uris_if_needed"):
                        job, error = dialog.parse_chosen_path(temp_file)

                        # Verify that set_results_extents was called but NOT with force=True
                        self.assertTrue(mock_set_extents.called)
                        call_args = mock_set_extents.call_args

                        # Check if force=False (default) was used
                        called_with_force = False
                        if len(call_args) > 1:  # Has both args and kwargs
                            if len(call_args[0]) > 1:  # positional force arg
                                called_with_force = call_args[0][1]
                            elif call_args[1]:  # kwargs
                                called_with_force = call_args[1].get("force", False)

                        self.assertFalse(
                            called_with_force,
                            "set_results_extents should NOT be called with force=True for valid extents",
                        )

        finally:
            os.unlink(temp_file)


class TestCheckDatasetOverlapRaster(unittest.TestCase):
    """Test suite for _check_dataset_overlap_raster warning messages"""

    def setUp(self):
        """Set up test fixtures"""
        from LDMP.data_io import _check_dataset_overlap_raster

        self._check_dataset_overlap_raster = _check_dataset_overlap_raster

    def test_check_dataset_overlap_logs_warning_for_no_extents(self):
        """Test that warning is logged when no valid extents are found"""
        # Create a mock AOI
        mock_aoi = Mock()

        # Create mock raster results with no extents
        mock_raster_results = Mock()
        mock_raster_results.get_extents.return_value = []

        with patch("LDMP.data_io.log") as mock_log:
            result = self._check_dataset_overlap_raster(mock_aoi, mock_raster_results)

            # Verify warning was logged
            self.assertFalse(result)
            mock_log.assert_called_once()
            log_message = mock_log.call_args[0][0]
            self.assertIn("No valid extents found", log_message)
            self.assertIn("set_results_extents(job, force=True)", log_message)

    def test_check_dataset_overlap_works_with_valid_extents(self):
        """Test that function works normally with valid extents"""
        # Create a mock AOI
        mock_aoi = Mock()
        mock_aoi.calc_frac_overlap.return_value = 1.0

        # Create mock raster results with valid extents
        mock_raster_results = Mock()
        mock_raster_results.get_extents.return_value = [(0.0, 0.0, 10.0, 10.0)]

        with patch("LDMP.data_io.log") as mock_log:
            with patch("LDMP.data_io._extent_as_geom") as mock_extent_as_geom:
                # Mock the geometry creation
                mock_geom = Mock()
                mock_extent_as_geom.return_value = mock_geom

                result = self._check_dataset_overlap_raster(
                    mock_aoi, mock_raster_results
                )

                # Should return True (full overlap)
                self.assertTrue(result)

                # Warning should NOT be logged for valid extents
                if mock_log.called:
                    log_message = mock_log.call_args[0][0]
                    self.assertNotIn("No valid extents found", str(log_message))


if __name__ == "__main__":
    unittest.main()
