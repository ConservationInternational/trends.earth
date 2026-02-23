"""Marshmallow compatibility regression tests for the trends.earth QGIS plugin.

These tests verify that te_schemas and te_algorithms marshmallow-based
schemas used by the plugin continue to serialize and deserialize correctly.
They serve as a safety net for marshmallow version upgrades.

The tests exercise both:
- te_schemas types consumed by LDMP (Job, Results, ExecutionScript, etc.)
- The plugin-specific Job subclass (LDMP.jobs.models.Job) with its @pre_load hook
"""

import unittest
import uuid

from te_schemas.algorithms import AlgorithmRunMode, ExecutionScript
from te_schemas.jobs import Job as JobBase
from te_schemas.jobs import JobStatus, RemoteScript, ScriptStatus
from te_schemas.results import (
    URI,
    Band,
    DataType,
    Raster,
    RasterFileType,
    RasterResults,
    ResultType,
    Vector,
    VectorResults,
    VectorType,
)
from utilities_for_testing import get_qgis_app

# QGIS must be initialised before importing anything from LDMP because
# LDMP.jobs.models imports qgis.PyQt at module level.
QGIS_APP = get_qgis_app()

from LDMP.jobs.models import Job  # noqa: E402

# ===================================================================
# Helpers
# ===================================================================


def _make_band(name="b1"):
    return Band(name=name, metadata={"units": "none"})


def _make_uri(uri="https://example.com/data.tif"):
    return URI(uri=uri, etag=None)


def _make_raster():
    return Raster(
        uri=_make_uri(),
        bands=[_make_band()],
        datatype=DataType.INT16,
        filetype=RasterFileType.GEOTIFF,
    )


def _make_raster_results():
    return RasterResults(
        name="test-raster",
        rasters={"INT16": _make_raster()},
    )


def _make_vector_results():
    return VectorResults(
        name="test-vector",
        vector=Vector(
            uri=_make_uri("https://example.com/v.geojson"),
            type=VectorType.GENERIC,
        ),
    )


def _make_execution_script(name="Test Script", version="1.0"):
    return ExecutionScript(
        id=str(uuid.uuid4()),
        name=name,
        version=version,
        run_mode=AlgorithmRunMode.LOCAL,
    )


def _make_base_job_dict(**overrides):
    """Return a raw dict that can be loaded by the plugin Job schema."""
    script = _make_execution_script()
    data = {
        "id": str(uuid.uuid4()),
        "params": {},
        "progress": 100,
        "start_date": "2025-01-01T00:00:00",
        "status": "FINISHED",
        "task_name": "regression-test",
        "script": ExecutionScript.Schema().dump(script),
    }
    data.update(overrides)
    return data


# ===================================================================
# 1. Plugin Job subclass round-trip via te_schemas base
# ===================================================================


class TestPluginJobSchema(unittest.TestCase):
    """Test the LDMP Job subclass schema (marshmallow_dataclass + @pre_load)."""

    def test_load_basic_job(self):
        """A well-formed dict should load into a Job instance."""
        data = _make_base_job_dict()
        job = Job.Schema().load(data)
        self.assertIsInstance(job, Job)
        self.assertEqual(job.task_name, "regression-test")
        self.assertEqual(job.status, JobStatus.FINISHED)

    def test_dump_load_roundtrip(self):
        """dump → load should produce the same logical object."""
        data = _make_base_job_dict()
        job = Job.Schema().load(data)
        dumped = Job.Schema().dump(job)
        reloaded = Job.Schema().load(dumped)
        self.assertEqual(str(job.id), str(reloaded.id))
        self.assertEqual(job.task_name, reloaded.task_name)
        self.assertEqual(job.status, reloaded.status)

    def test_pre_load_script_name_version_parsing(self):
        """@pre_load should split 'Name 1_2_3' into name='Name' version='1.2.3'."""
        data = _make_base_job_dict()
        data["script"] = {
            "id": str(uuid.uuid4()),
            "name": "Land Cover 1_0_7",
            "run_mode": "local",
        }
        job = Job.Schema().load(data)
        self.assertEqual(job.script.name, "Land Cover")
        self.assertEqual(job.script.version, "1.0.7")

    def test_pre_load_fallback_to_unknown(self):
        """When script info is absent, @pre_load should create an Unknown script."""
        data = _make_base_job_dict()
        data.pop("script", None)
        # Don't put script_id in params either
        job = Job.Schema().load(data)
        self.assertIsNotNone(job.script)

    def test_results_with_raster(self):
        """A job with raster results should load and dump correctly."""
        rr = _make_raster_results()
        data = _make_base_job_dict(
            results=RasterResults.Schema().dump(rr),
        )
        job = Job.Schema().load(data)
        dumped = Job.Schema().dump(job)
        self.assertIn("results", dumped)

    def test_results_with_vector(self):
        """A job with vector results should load and dump correctly."""
        vr = _make_vector_results()
        data = _make_base_job_dict(
            results=VectorResults.Schema().dump(vr),
        )
        job = Job.Schema().load(data)
        dumped = Job.Schema().dump(job)
        self.assertIn("results", dumped)

    def test_results_with_list(self):
        """A job with a list of results should round-trip."""
        rr = _make_raster_results()
        vr = _make_vector_results()
        data = _make_base_job_dict(
            results=[
                RasterResults.Schema().dump(rr),
                VectorResults.Schema().dump(vr),
            ],
        )
        job = Job.Schema().load(data)
        dumped = Job.Schema().dump(job)
        self.assertIn("results", dumped)

    def test_results_null(self):
        """A job with no results should load fine."""
        data = _make_base_job_dict()
        data["results"] = None
        job = Job.Schema().load(data)
        self.assertIsNone(job.results)

    def test_get_basename(self):
        """Job.get_basename should return a slug string."""
        data = _make_base_job_dict()
        job = Job.Schema().load(data)
        basename = job.get_basename()
        self.assertIsInstance(basename, str)
        self.assertTrue(len(basename) > 0)

    def test_get_display_name(self):
        """Job.get_display_name should return something meaningful."""
        data = _make_base_job_dict()
        job = Job.Schema().load(data)
        name = job.get_display_name()
        self.assertIsInstance(name, str)


# ===================================================================
# 2. te_schemas types used by the plugin (without LDMP-specific logic)
# ===================================================================


class TestTeSchemasDependencies(unittest.TestCase):
    """Regression tests for te_schemas types consumed by the plugin."""

    def test_band_roundtrip(self):
        b = _make_band()
        data = Band.Schema().dump(b)
        loaded = Band.Schema().load(data)
        self.assertEqual(loaded.name, "b1")

    def test_uri_roundtrip(self):
        u = _make_uri()
        data = URI.Schema().dump(u)
        loaded = URI.Schema().load(data)
        self.assertEqual(loaded.uri, "https://example.com/data.tif")

    def test_raster_roundtrip(self):
        r = _make_raster()
        data = Raster.Schema().dump(r)
        loaded = Raster.Schema().load(data)
        self.assertEqual(loaded.datatype, DataType.INT16)
        self.assertEqual(loaded.filetype, RasterFileType.GEOTIFF)

    def test_raster_results_roundtrip(self):
        rr = _make_raster_results()
        data = RasterResults.Schema().dump(rr)
        loaded = RasterResults.Schema().load(data)
        self.assertEqual(loaded.name, "test-raster")
        self.assertIn("INT16", loaded.rasters)

    def test_vector_results_roundtrip(self):
        vr = _make_vector_results()
        data = VectorResults.Schema().dump(vr)
        loaded = VectorResults.Schema().load(data)
        self.assertEqual(loaded.vector.type, VectorType.GENERIC)

    def test_execution_script_roundtrip(self):
        es = _make_execution_script()
        data = ExecutionScript.Schema().dump(es)
        loaded = ExecutionScript.Schema().load(data)
        self.assertEqual(loaded.name, "Test Script")
        self.assertEqual(loaded.run_mode, AlgorithmRunMode.LOCAL)

    def test_remote_script_roundtrip(self):
        rs_data = {
            "id": str(uuid.uuid4()),
            "name": "Remote Script",
            "slug": "remote-script",
            "description": "A test remote script",
            "status": "SUCCESS",
            "created_at": "2025-01-01T00:00:00",
            "updated_at": "2025-01-01T00:00:00",
            "user_id": str(uuid.uuid4()),
            "public": True,
        }
        loaded = RemoteScript.Schema().load(rs_data)
        self.assertEqual(loaded.name, "Remote Script")
        dumped = RemoteScript.Schema().dump(loaded)
        reloaded = RemoteScript.Schema().load(dumped)
        self.assertEqual(reloaded.slug, "remote-script")


# ===================================================================
# 3. Enum serialization (enums used in plugin imports)
# ===================================================================


class TestEnumSerialization(unittest.TestCase):
    """Ensures enums serialize as values, not names."""

    def test_job_status_by_value(self):
        self.assertEqual(JobStatus("FINISHED"), JobStatus.FINISHED)
        self.assertEqual(JobStatus("PENDING"), JobStatus.PENDING)
        self.assertEqual(JobStatus("RUNNING"), JobStatus.RUNNING)

    def test_data_type_by_value(self):
        self.assertEqual(DataType("Int16"), DataType.INT16)
        self.assertEqual(DataType("Float32"), DataType.FLOAT32)

    def test_raster_file_type_by_value(self):
        self.assertEqual(RasterFileType("GeoTiff"), RasterFileType.GEOTIFF)

    def test_result_type_by_value(self):
        self.assertEqual(ResultType("RasterResults"), ResultType.RASTER_RESULTS)
        self.assertEqual(ResultType("VectorResults"), ResultType.VECTOR_RESULTS)

    def test_vector_type_by_value(self):
        self.assertEqual(VectorType("Generic"), VectorType.GENERIC)
        self.assertEqual(VectorType("False positive/negative"), VectorType.ERROR_RECODE)

    def test_algorithm_run_mode_by_value(self):
        self.assertEqual(AlgorithmRunMode("local"), AlgorithmRunMode.LOCAL)
        self.assertEqual(AlgorithmRunMode(0), AlgorithmRunMode.NOT_APPLICABLE)

    def test_script_status_by_value(self):
        self.assertEqual(ScriptStatus("SUCCESS"), ScriptStatus.SUCCESS)
        self.assertEqual(ScriptStatus("FAIL"), ScriptStatus.FAIL)
        self.assertEqual(ScriptStatus("BUILDING"), ScriptStatus.BUILDING)


# ===================================================================
# 4. Validation error handling (marshmallow.exceptions.ValidationError)
# ===================================================================


class TestValidationErrors(unittest.TestCase):
    """Plugin uses marshmallow.exceptions.ValidationError in LDMP.jobs.manager."""

    def test_import_validation_error(self):
        from marshmallow.exceptions import ValidationError

        self.assertTrue(issubclass(ValidationError, Exception))

    def test_schema_raises_validation_error(self):
        from marshmallow.exceptions import ValidationError

        # Band requires "name"
        with self.assertRaises(ValidationError):
            Band.Schema().load({})

    def test_job_base_validation(self):
        from marshmallow.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            # Missing required fields (params must be present for @pre_load)
            JobBase.Schema().load({"status": "INVALID", "params": {}})


# ===================================================================
# 5. SchemaBase interface used via te_schemas
# ===================================================================


class TestSchemaBaseInterface(unittest.TestCase):
    """Tests SchemaBase methods that algorithm/plugin code relies on.

    ExecutionScript inherits from SchemaBase, so we use it to verify
    the dump/dumps/schema/validate instance methods.
    """

    def test_schema_method(self):
        es = _make_execution_script()
        schema = es.schema()
        self.assertIsNotNone(schema)
        self.assertTrue(hasattr(schema, "load"))

    def test_dump_method(self):
        es = _make_execution_script()
        data = es.dump()
        self.assertIsInstance(data, dict)
        self.assertEqual(data["name"], "Test Script")

    def test_validate_method(self):
        es = _make_execution_script()
        es.validate()  # Should not raise

    def test_dumps_method(self):
        es = _make_execution_script()
        json_str = es.dumps()
        self.assertIsInstance(json_str, str)
        self.assertIn("Test Script", json_str)


# ===================================================================
# 6. Backward-compatible field defaults
# ===================================================================


class TestFieldDefaults(unittest.TestCase):
    """Verify dump_default / load_default work as expected."""

    def test_job_requires_progress(self):
        """Job loaded without explicit progress should raise ValidationError."""
        from marshmallow.exceptions import ValidationError

        data = _make_base_job_dict()
        data.pop("progress", None)
        with self.assertRaises(ValidationError):
            Job.Schema().load(data)

    def test_band_requires_metadata(self):
        """Band without metadata should raise ValidationError (metadata is required)."""
        from marshmallow.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            Band.Schema().load({"name": "b1"})

    def test_band_with_metadata(self):
        """Band with name and metadata should load correctly."""
        data = {"name": "b1", "metadata": {"units": "none"}}
        b = Band.Schema().load(data)
        self.assertEqual(b.name, "b1")
        self.assertEqual(b.metadata, {"units": "none"})

    def test_execution_script_defaults(self):
        """ExecutionScript with minimal data should apply defaults for optional fields."""
        data = {
            "id": str(uuid.uuid4()),
            "name": "test",
            "run_mode": "local",
        }
        es = ExecutionScript.Schema().load(data)
        self.assertIsNotNone(es)
        self.assertEqual(es.run_mode, AlgorithmRunMode.LOCAL)


# ===================================================================
# 7. Unknown-field handling (EXCLUDE)
# ===================================================================


class TestUnknownFieldHandling(unittest.TestCase):
    """te_schemas schemas use Meta.unknown = EXCLUDE.
    This verifies extra fields don't cause errors."""

    def test_execution_script_ignores_unknown(self):
        data = {
            "id": str(uuid.uuid4()),
            "name": "test",
            "run_mode": "local",
            "unknown_extra_field": True,
        }
        es = ExecutionScript.Schema().load(data)
        self.assertEqual(es.name, "test")

    def test_uri_ignores_unknown(self):
        data = {
            "uri": "https://example.com/r.tif",
            "etag": None,
            "extra": 42,
        }
        u = URI.Schema().load(data)
        self.assertEqual(u.uri, "https://example.com/r.tif")


if __name__ == "__main__":
    unittest.main()
