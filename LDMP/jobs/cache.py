"""SQLite-based persistent cache for Job objects.

This module provides a JobCache class that persists parsed Job objects across
QGIS sessions, eliminating the need to re-parse large JSON files on every startup.

The cache stores Job objects in a split format:
- metadata_pickle: Job with params={} and results=None (small, fast to load)
- params_pickle: Just the params dict (can be large)
- results_pickle: Just the results (can be large)

For UI display, only the lightweight metadata_pickle is loaded. The large
params/results are loaded on-demand when actually needed.
"""

import copy
import json
import logging
import os
import pickle
import sqlite3
import threading
import typing
from pathlib import Path

from ..logger import log

logger = logging.getLogger(__name__)

# Cache schema version - increment when schema structure changes
# to invalidate old caches and force re-parsing
# v1: Initial schema with full job_pickle
# v2: Split storage (metadata_pickle, params_pickle, results_pickle)
# v3: Added indexed columns for rapid dropdown queries (script_id, script_name,
#     extent_*, job_status already existed)
# v4: Added has_loadable_result column for UI button state without loading results
# v5: Added result type flag columns (is_raster, is_vector, is_timeseries,
#     is_file) for UI state without loading results + thread safety with lock
# v6: Fixed cache_job() to handle None job (failed-parse sentinel),
#     fixed mtime comparison with epsilon tolerance,
#     added schema table integrity validation
# v7: Added cached_prod_mode, cached_band_names (JSON), cached_result_uri
#     columns to avoid unpickling params/results for dropdown filters
CACHE_SCHEMA_VERSION = 7

# Tolerance for floating-point mtime comparisons.
_MTIME_EPSILON = 1e-3


def _mtime_matches(a: float, b: float) -> bool:
    """Return True if two mtime values are close enough to be considered equal."""
    return abs(a - b) < _MTIME_EPSILON


def _normalize_cache_key(path: Path) -> str:
    """Normalize a path for use as a cache key.

    On Windows, paths are case-insensitive, so we lowercase the resolved path.
    """
    resolved = str(path.resolve())
    if os.name == "nt":  # Windows
        return resolved.lower()
    return resolved


def _set_cached_type_flags(
    job,
    has_loadable_result,
    is_raster,
    is_vector,
    is_timeseries,
    is_file,
    cache_path=None,
    extent_north=None,
    extent_south=None,
    extent_east=None,
    extent_west=None,
    cached_prod_mode=None,
    cached_band_names=None,
    cached_result_uri=None,
):
    """Set cached result type flags on a Job object.

    These flags allow the UI to determine job type and button state
    without needing the heavy results data to be loaded.
    ``cache_path`` is stored so results can be lazy-loaded on demand.
    If extent values are provided, ``_cached_extent`` is set as
    ``(west, south, east, north)`` — i.e. ``(minx, miny, maxx, maxy)``.
    """
    job._cached_has_loadable_result = bool(has_loadable_result)
    job._cached_is_raster = bool(is_raster)
    job._cached_is_vector = bool(is_vector)
    job._cached_is_timeseries = bool(is_timeseries)
    job._cached_is_file = bool(is_file)
    if cache_path is not None:
        job._cache_path = cache_path
    if (
        extent_north is not None
        and extent_south is not None
        and extent_east is not None
        and extent_west is not None
    ):
        job._cached_extent = (extent_west, extent_south, extent_east, extent_north)
    else:
        job._cached_extent = None
    job._cached_prod_mode = cached_prod_mode
    if cached_band_names is not None:
        try:
            job._cached_band_names = tuple(json.loads(cached_band_names))
        except (json.JSONDecodeError, TypeError):
            job._cached_band_names = None
    else:
        job._cached_band_names = None
    job._cached_result_uri = cached_result_uri


class JobCache:
    """SQLite-backed persistent cache for Job objects.

    Stores pickled Job objects alongside file paths and mtimes. When a file
    hasn't changed (same mtime), the Job can be restored from pickle much
    faster than re-parsing the JSON file with marshmallow.

    The cache automatically invalidates when:
    - A file's mtime changes
    - The cache schema version changes (e.g., Job class structure updated)
    - The cache database is corrupted or inaccessible

    Attributes:
        db_path: Path to the SQLite database file
    """

    # Sentinel to indicate base_dir should be resolved from settings
    _USE_SETTINGS_BASE_DIR = object()

    def __init__(self, base_dir: typing.Optional[Path] = None):
        """Initialize the job cache.

        Args:
            base_dir: Base directory for Trends.Earth data. If None, uses the
                     configured BASE_DIR setting. The cache database is stored
                     as `.job_cache.db` in this directory.
        """
        # Store sentinel or explicit base_dir - don't resolve from settings yet
        # to avoid circular import at module load time
        if base_dir is not None:
            self._base_dir_input = base_dir
        else:
            self._base_dir_input = self._USE_SETTINGS_BASE_DIR
        self._base_dir: typing.Optional[Path] = None
        self._base_dir_resolved = False
        self._conn: typing.Optional[sqlite3.Connection] = None
        self._initialized = False
        # Lock to serialize all database operations for thread safety.
        # SQLite connections are not thread-safe by default, and even with
        # check_same_thread=False, concurrent access can cause issues.
        self._lock = threading.Lock()

    def _resolve_base_dir(self) -> typing.Optional[Path]:
        """Resolve the base directory, importing conf lazily if needed."""
        if self._base_dir_resolved:
            return self._base_dir

        self._base_dir_resolved = True
        if self._base_dir_input is self._USE_SETTINGS_BASE_DIR:
            # Lazy import to avoid circular dependency
            from ..conf import Setting, settings_manager

            base_dir_str = settings_manager.get_value(Setting.BASE_DIR)
            if base_dir_str:
                self._base_dir = Path(base_dir_str)
        else:
            self._base_dir = self._base_dir_input

        return self._base_dir

    @property
    def db_path(self) -> typing.Optional[Path]:
        """Path to the SQLite database file, or None if no base dir configured."""
        base_dir = self._resolve_base_dir()
        if base_dir is None:
            return None
        return base_dir / ".job_cache.db"

    def _ensure_initialized(self) -> bool:
        """Ensure the database connection is open and schema is created.

        Returns:
            True if the cache is ready to use, False if unavailable.
        """
        if self._initialized and self._conn is not None:
            return True

        if self.db_path is None:
            return False

        try:
            # Ensure parent directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            # Open database with WAL mode for better concurrency
            # check_same_thread=False allows the connection to be used from
            # any thread. Thread safety is ensured by self._lock.
            self._conn = sqlite3.connect(
                str(self.db_path),
                timeout=5.0,
                isolation_level=None,  # autocommit mode
                check_same_thread=False,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")

            # Create schema if needed
            self._create_schema()
            self._initialized = True
            return True

        except (sqlite3.Error, OSError, IOError) as exc:
            log(f"Failed to initialize job cache: {type(exc).__name__}: {exc}")
            self._conn = None
            self._initialized = False
            return False

    def _create_schema(self):
        """Create the cache table and check schema version."""
        if self._conn is None:
            return

        # Create metadata table for schema versioning
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS cache_metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # Check schema version
        cursor = self._conn.execute(
            "SELECT value FROM cache_metadata WHERE key = 'schema_version'"
        )
        row = cursor.fetchone()
        current_version = int(row[0]) if row else 0

        need_recreate = current_version != CACHE_SCHEMA_VERSION

        if not need_recreate:
            # Validate that the existing table has the expected columns
            try:
                probe = self._conn.execute(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type='table' AND name='job_cache'"
                )
                table_row = probe.fetchone()
                if table_row is None:
                    need_recreate = True
                else:
                    table_sql = (table_row[0] or "").lower()
                    for col in (
                        "metadata_pickle",
                        "has_loadable_result",
                        "is_raster",
                        "cached_prod_mode",
                    ):
                        if col not in table_sql:
                            need_recreate = True
                            break
            except sqlite3.Error:
                need_recreate = True

        if need_recreate:
            # Schema version changed or table is missing/corrupt - recreate
            log(
                f"Job cache schema version changed ({current_version} -> "
                f"{CACHE_SCHEMA_VERSION}), clearing cache"
            )
            self._conn.execute("DROP TABLE IF EXISTS job_cache")
            self._conn.execute(
                "INSERT OR REPLACE INTO cache_metadata (key, value) VALUES (?, ?)",
                ("schema_version", str(CACHE_SCHEMA_VERSION)),
            )

        # Create main cache table with split storage:
        # - metadata_pickle: Job with params={} and results=None (small, fast)
        # - params_pickle: Just the params dict (can be large)
        # - results_pickle: Just the results (can be large)
        # Plus indexed columns for rapid dropdown queries without unpickling
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS job_cache (
                path TEXT PRIMARY KEY,
                mtime REAL NOT NULL,
                metadata_pickle BLOB NOT NULL,
                params_pickle BLOB,
                results_pickle BLOB,
                job_id TEXT NOT NULL,
                job_status TEXT NOT NULL,
                script_id TEXT,
                script_name TEXT,
                extent_north REAL,
                extent_south REAL,
                extent_east REAL,
                extent_west REAL,
                has_loadable_result INTEGER DEFAULT 0,
                is_raster INTEGER DEFAULT 0,
                is_vector INTEGER DEFAULT 0,
                is_timeseries INTEGER DEFAULT 0,
                is_file INTEGER DEFAULT 0,
                cached_prod_mode TEXT,
                cached_band_names TEXT,
                cached_result_uri TEXT
            )
        """)

        # Create indexes for efficient queries
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_job_status ON job_cache(job_status)"
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_job_id ON job_cache(job_id)")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_script_id ON job_cache(script_id)"
        )

    def get_cached_job(
        self,
        path: Path,
        current_mtime: float,
        load_params: bool = True,
        load_results: bool = True,
    ) -> typing.Optional[typing.Any]:
        """Get a cached Job if the file hasn't changed.

        Args:
            path: Path to the job JSON file
            current_mtime: Current modification time of the file
            load_params: If True, load and attach params (slower)
            load_results: If True, load and attach results (slower)

        Returns:
            The cached Job object if valid, or None if not cached or stale.
            If load_params=False, job.params will be {}
            If load_results=False, job.results will be None but
                cached result type flags will be set on the job.
        """
        with self._lock:
            if not self._ensure_initialized() or self._conn is None:
                return None

            cache_key = _normalize_cache_key(path)

            try:
                cursor = self._conn.execute(
                    "SELECT mtime, metadata_pickle, params_pickle, results_pickle, "
                    "has_loadable_result, is_raster, is_vector, is_timeseries, "
                    "is_file, extent_north, extent_south, extent_east, extent_west, "
                    "cached_prod_mode, cached_band_names, cached_result_uri "
                    "FROM job_cache WHERE path = ?",
                    (cache_key,),
                )
                row = cursor.fetchone()

                if row is None:
                    return None

                (
                    cached_mtime,
                    metadata_pickle,
                    params_pickle,
                    results_pickle,
                    has_loadable_result,
                    cached_is_raster,
                    cached_is_vector,
                    cached_is_timeseries,
                    cached_is_file,
                    cached_extent_north,
                    cached_extent_south,
                    cached_extent_east,
                    cached_extent_west,
                    cached_prod_mode,
                    cached_band_names,
                    cached_result_uri,
                ) = row

                # Check if file has changed
                if not _mtime_matches(cached_mtime, current_mtime):
                    return None

                # Restore Job from pickle
                try:
                    job = pickle.loads(metadata_pickle)

                    # Set cached result type flags for UI state
                    _set_cached_type_flags(
                        job,
                        has_loadable_result,
                        cached_is_raster,
                        cached_is_vector,
                        cached_is_timeseries,
                        cached_is_file,
                        cache_path=cache_key,
                        extent_north=cached_extent_north,
                        extent_south=cached_extent_south,
                        extent_east=cached_extent_east,
                        extent_west=cached_extent_west,
                        cached_prod_mode=cached_prod_mode,
                        cached_band_names=cached_band_names,
                        cached_result_uri=cached_result_uri,
                    )

                    # Optionally load heavy data
                    if load_params and params_pickle:
                        try:
                            job.params = pickle.loads(params_pickle)
                        except (
                            pickle.PickleError,
                            AttributeError,
                            ModuleNotFoundError,
                        ):
                            pass  # Keep empty params if unpickle fails

                    if load_results and results_pickle:
                        try:
                            job.results = pickle.loads(results_pickle)
                        except (
                            pickle.PickleError,
                            AttributeError,
                            ModuleNotFoundError,
                        ):
                            pass  # Keep None results if unpickle fails

                    return job
                except (pickle.PickleError, AttributeError, ModuleNotFoundError) as exc:
                    # Pickle failed (class structure changed?) - invalidate entry
                    # Lazy import to avoid circular dependency
                    from ..conf import Setting, settings_manager

                    if settings_manager.get_value(Setting.DEBUG):
                        log(f"Failed to unpickle cached job for {path}: {exc}")
                    self._conn.execute(
                        "DELETE FROM job_cache WHERE path = ?", (cache_key,)
                    )
                    return None

            except sqlite3.Error as exc:
                log(f"SQLite error reading cache for {path}: {exc}")
                return None

    def load_results_for_job(self, job) -> bool:
        """Load results from the cache into a Job that was loaded without them.

        Uses the ``_cache_path`` attribute set during lightweight loading.
        Returns True if results were successfully loaded, False otherwise.
        """
        cache_path = getattr(job, "_cache_path", None)
        if cache_path is None:
            return False

        with self._lock:
            if not self._ensure_initialized() or self._conn is None:
                return False

            try:
                cursor = self._conn.execute(
                    "SELECT results_pickle FROM job_cache WHERE path = ?",
                    (cache_path,),
                )
                row = cursor.fetchone()
                if row is None or row[0] is None:
                    return False

                job.results = pickle.loads(row[0])
                return True
            except (
                sqlite3.Error,
                pickle.PickleError,
                AttributeError,
                ModuleNotFoundError,
            ) as exc:
                log(f"Failed to lazy-load results for {cache_path}: {exc}")
                return False

    def load_params_for_job(self, job) -> bool:
        """Load params from the cache into a Job that was loaded without them.

        Uses the ``_cache_path`` attribute set during lightweight loading.
        Returns True if params were successfully loaded, False otherwise.
        """
        cache_path = getattr(job, "_cache_path", None)
        if cache_path is None:
            return False

        with self._lock:
            if not self._ensure_initialized() or self._conn is None:
                return False

            try:
                cursor = self._conn.execute(
                    "SELECT params_pickle FROM job_cache WHERE path = ?",
                    (cache_path,),
                )
                row = cursor.fetchone()
                if row is None or row[0] is None:
                    return False

                job.params = pickle.loads(row[0])
                return True
            except (
                sqlite3.Error,
                pickle.PickleError,
                AttributeError,
                ModuleNotFoundError,
            ) as exc:
                log(f"Failed to lazy-load params for {cache_path}: {exc}")
                return False

    def cache_job(
        self, path: Path, mtime: float, job: typing.Optional[typing.Any]
    ) -> bool:
        """Store a Job in the cache with split storage.

        If *job* is ``None``, a lightweight sentinel row is stored with
        ``job_status='FAILED_PARSE'`` so that subsequent scans can skip
        the file without re-parsing it.

        When *job* is a real Job object it is stored in three parts:
        - metadata_pickle: Job with params={} and results=None (small, fast to load)
        - params_pickle: Just the params dict (can be large)
        - results_pickle: Just the results (can be large)

        Additionally, indexed columns are extracted for rapid dropdown queries:
        - script_id, script_name: From job.script
        - extent_*: Combined bounding box from job.results

        Args:
            path: Path to the job JSON file
            mtime: Modification time of the file
            job: The Job object to cache, or None to mark as failed-parse

        Returns:
            True if successfully cached, False otherwise.
        """
        with self._lock:
            if not self._ensure_initialized() or self._conn is None:
                return False

            cache_key = _normalize_cache_key(path)

            # Store a FAILED_PARSE sentinel when job is None
            if job is None:
                try:
                    self._conn.execute(
                        """
                        INSERT OR REPLACE INTO job_cache
                        (path, mtime, metadata_pickle, params_pickle,
                         results_pickle, job_id, job_status, script_id,
                         script_name, extent_north, extent_south,
                         extent_east, extent_west, has_loadable_result,
                         is_raster, is_vector, is_timeseries, is_file,
                         cached_prod_mode, cached_band_names,
                         cached_result_uri)
                        VALUES (?, ?, ?, NULL, NULL, '', 'FAILED_PARSE',
                                NULL, NULL, NULL, NULL, NULL, NULL,
                                0, 0, 0, 0, 0, NULL, NULL, NULL)
                        """,
                        (cache_key, mtime, b""),
                    )
                    return True
                except sqlite3.Error as exc:
                    log(
                        f"Failed to cache failed-parse sentinel for "
                        f"{path}: {type(exc).__name__}: {exc}"
                    )
                    return False

            try:
                # Extract params and results before creating lightweight copy
                params = getattr(job, "params", {}) or {}
                results = getattr(job, "results", None)

                # Create lightweight copy for metadata_pickle
                job_lightweight = copy.copy(job)
                job_lightweight.params = {}
                job_lightweight.results = None

                metadata_pickle = pickle.dumps(
                    job_lightweight, protocol=pickle.HIGHEST_PROTOCOL
                )
                params_pickle = (
                    pickle.dumps(params, protocol=pickle.HIGHEST_PROTOCOL)
                    if params
                    else None
                )
                results_pickle = (
                    pickle.dumps(results, protocol=pickle.HIGHEST_PROTOCOL)
                    if results is not None
                    else None
                )

                job_id = str(job.id) if hasattr(job, "id") else ""
                job_status = job.status.value if hasattr(job, "status") else ""

                # Extract script info for dropdown queries
                script_id, script_name = self._extract_script_info(job)

                # Extract combined extent from results
                extent_north, extent_south, extent_east, extent_west = (
                    self._extract_combined_extent(results)
                )

                # Compute result type flags for UI state
                has_loadable = self._compute_has_loadable_result(results)
                type_flags = self._compute_result_type_flags(job)

                # Extract dropdown pre-filter columns
                cached_prod_mode = self._extract_prod_mode(params, results)
                cached_band_names = self._extract_band_names(results)
                cached_result_uri = self._extract_result_uri(results)

                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO job_cache
                    (path, mtime, metadata_pickle, params_pickle, results_pickle,
                     job_id, job_status, script_id, script_name,
                     extent_north, extent_south, extent_east, extent_west,
                     has_loadable_result,
                     is_raster, is_vector, is_timeseries, is_file,
                     cached_prod_mode, cached_band_names, cached_result_uri)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cache_key,
                        mtime,
                        metadata_pickle,
                        params_pickle,
                        results_pickle,
                        job_id,
                        job_status,
                        script_id,
                        script_name,
                        extent_north,
                        extent_south,
                        extent_east,
                        extent_west,
                        1 if has_loadable else 0,
                        1 if type_flags["is_raster"] else 0,
                        1 if type_flags["is_vector"] else 0,
                        1 if type_flags["is_timeseries"] else 0,
                        1 if type_flags["is_file"] else 0,
                        cached_prod_mode,
                        cached_band_names,
                        cached_result_uri,
                    ),
                )
                return True

            except (sqlite3.Error, pickle.PickleError) as exc:
                log(f"Failed to cache job for {path}: {type(exc).__name__}: {exc}")
                return False

    def _extract_script_info(
        self, job: typing.Any
    ) -> typing.Tuple[typing.Optional[str], typing.Optional[str]]:
        """Extract script ID and name from a Job object.

        Args:
            job: The Job object

        Returns:
            Tuple of (script_id, script_name), either may be None
        """
        script = getattr(job, "script", None)
        if script is None:
            return (None, None)

        script_id = None
        script_name = None

        # Get ID (could be UUID or string)
        if hasattr(script, "id") and script.id is not None:
            script_id = str(script.id)

        # Prefer name_readable, fall back to name
        if hasattr(script, "name_readable") and script.name_readable:
            script_name = script.name_readable
        elif hasattr(script, "name") and script.name:
            script_name = script.name

        return (script_id, script_name)

    def _extract_prod_mode(
        self,
        params: typing.Dict[str, typing.Any],
        results: typing.Any,
    ) -> typing.Optional[str]:
        """Extract productivity mode from job params (or infer from band names).

        Mirrors the runtime logic in data_io._get_usable_bands:
        1. Check params["prod_mode"]
        2. Check params["productivity"]["mode"]
        3. Infer from band names via PROD_MODE_FOR_BAND mapping

        Returns the raw string value, or None if not determinable.
        """
        # Try explicit params first
        if "prod_mode" in params:
            mode = params.get("prod_mode")
        elif "productivity" in params:
            mode = params.get("productivity", {}).get("mode")
        else:
            mode = None

        # Normalize enum to raw value
        if mode is not None:
            return mode.value if hasattr(mode, "value") else str(mode)

        # Infer from band names in results
        if results is not None:
            try:
                from te_schemas.results import RasterResults as _RasterResults

                results_list = results if isinstance(results, list) else [results]
                for result in results_list:
                    if isinstance(result, _RasterResults) and hasattr(
                        result, "get_bands"
                    ):
                        for band in result.get_bands():
                            name = getattr(band, "name", None)
                            if name is not None:
                                # Lazy import to avoid circular at module level
                                try:
                                    import te_algorithms.gdal.land_deg.config as ld_conf
                                    from te_schemas.productivity import ProductivityMode

                                    _PROD_MODE_FOR_BAND = {
                                        ld_conf.FAO_WOCAT_LPD_BAND_NAME: ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value,
                                        ld_conf.JRC_LPD_BAND_NAME: ProductivityMode.JRC_5_CLASS_LPD.value,
                                        ld_conf.TE_LPD_BAND_NAME: ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value,
                                        ld_conf.CUSTOM_LPD_BAND_NAME: ProductivityMode.CUSTOM_5_CLASS_LPD.value,
                                    }
                                    if name in _PROD_MODE_FOR_BAND:
                                        return _PROD_MODE_FOR_BAND[name]
                                except ImportError:
                                    pass
            except Exception:
                pass

        return None

    def _extract_band_names(self, results: typing.Any) -> typing.Optional[str]:
        """Extract band names from the first RasterResults as a JSON array.

        Returns a JSON-encoded list of band name strings, or None if no
        raster bands are found.
        """
        if results is None:
            return None

        try:
            from te_schemas.results import RasterResults as _RasterResults

            results_list = results if isinstance(results, list) else [results]
            for result in results_list:
                if isinstance(result, _RasterResults) and hasattr(result, "get_bands"):
                    bands = result.get_bands()
                    if bands:
                        names = [
                            getattr(b, "name", None)
                            for b in bands
                            if getattr(b, "name", None) is not None
                        ]
                        if names:
                            return json.dumps(names)
        except Exception:
            pass

        return None

    def _extract_result_uri(self, results: typing.Any) -> typing.Optional[str]:
        """Extract the primary result URI string from the first result with a URI.

        Checks RasterResults first (most common), then other result types.
        Returns the URI path as a string, or None.
        """
        if results is None:
            return None

        try:
            results_list = results if isinstance(results, list) else [results]
            for result in results_list:
                if result is None:
                    continue
                uri_obj = getattr(result, "uri", None)
                if uri_obj is not None:
                    uri_path = getattr(uri_obj, "uri", None)
                    if uri_path is not None:
                        return str(uri_path)
        except Exception:
            pass

        return None

    def _extract_combined_extent(
        self, results: typing.Any
    ) -> typing.Tuple[
        typing.Optional[float],
        typing.Optional[float],
        typing.Optional[float],
        typing.Optional[float],
    ]:
        """Extract combined bounding box from job results.

        Iterates through all results and computes the union of all extents.
        Extent format in results is (minx, miny, maxx, maxy) which maps to
        (west, south, east, north).

        Args:
            results: The results from a Job (single result or list)

        Returns:
            Tuple of (north, south, east, west), all may be None if no extents found
        """
        if results is None:
            return (None, None, None, None)

        all_extents: typing.List[typing.Tuple[float, float, float, float]] = []

        # Handle single result or list of results
        results_list = results if isinstance(results, list) else [results]

        for result in results_list:
            if result is None:
                continue

            # Try get_extents() method first (RasterResults)
            if hasattr(result, "get_extents") and callable(result.get_extents):
                try:
                    extents = result.get_extents()
                    if extents:
                        all_extents.extend(extents)
                except Exception:
                    pass

            # Try direct extent attribute (single extent)
            elif hasattr(result, "extent") and result.extent is not None:
                try:
                    ext = result.extent
                    if isinstance(ext, (tuple, list)) and len(ext) == 4:
                        all_extents.append(tuple(ext))
                except Exception:
                    pass

            # Try extents attribute (list of extents, e.g., TiledRaster)
            elif hasattr(result, "extents") and result.extents:
                try:
                    for ext in result.extents:
                        if isinstance(ext, (tuple, list)) and len(ext) == 4:
                            all_extents.append(tuple(ext))
                except Exception:
                    pass

            # Try rasters attribute (container with multiple rasters)
            elif hasattr(result, "rasters") and result.rasters:
                try:
                    for raster in result.rasters:
                        if hasattr(raster, "extent") and raster.extent is not None:
                            ext = raster.extent
                            if isinstance(ext, (tuple, list)) and len(ext) == 4:
                                all_extents.append(tuple(ext))
                        elif hasattr(raster, "extents") and raster.extents:
                            for ext in raster.extents:
                                if isinstance(ext, (tuple, list)) and len(ext) == 4:
                                    all_extents.append(tuple(ext))
                except Exception:
                    pass

        if not all_extents:
            return (None, None, None, None)

        # Compute union of all extents
        # Extent format: (minx, miny, maxx, maxy) = (west, south, east, north)
        try:
            west = min(ext[0] for ext in all_extents)
            south = min(ext[1] for ext in all_extents)
            east = max(ext[2] for ext in all_extents)
            north = max(ext[3] for ext in all_extents)
            return (north, south, east, west)
        except (TypeError, ValueError, IndexError):
            return (None, None, None, None)

    def _compute_has_loadable_result(self, results: typing.Any) -> bool:
        """Compute whether the job has loadable results for UI display.

        Checks if any result has a URI pointing to a loadable file:
        - VSI paths (e.g., /vsis3/) are always considered loadable
        - Local .vrt or .tif files that exist are loadable

        Args:
            results: The results from a Job (single result or list)

        Returns:
            True if at least one result has a loadable URI, False otherwise.
        """
        import re

        if results is None:
            return False

        # Handle single result or list of results
        results_list = results if isinstance(results, list) else [results]

        for result in results_list:
            if result is None:
                continue

            # Check for uri attribute
            if not hasattr(result, "uri") or result.uri is None:
                continue

            uri_obj = result.uri
            if not hasattr(uri_obj, "uri") or uri_obj.uri is None:
                continue

            uri_path = uri_obj.uri

            # Check for VSI path (GDAL virtual file system)
            path_str = str(uri_path)
            if re.match(r"[/\\]vsi(?:s3|gs)", path_str) is not None:
                return True

            # Check for local .vrt or .tif file that exists
            try:
                if hasattr(uri_path, "suffix"):
                    if uri_path.suffix in [".vrt", ".tif"]:
                        if hasattr(uri_path, "exists") and uri_path.exists():
                            return True
            except (AttributeError, OSError):
                pass

        return False

    def _compute_result_type_flags(self, job: typing.Any) -> typing.Dict[str, bool]:
        """Compute result type flags from a job's results.

        Uses the job's own is_*() methods which iterate _get_results_list()
        to check isinstance on each result. These flags are stored in
        SQLite so the UI can determine job type without unpickling results.

        Args:
            job: The Job object (must have results loaded)

        Returns:
            Dict with keys is_raster, is_vector, is_timeseries, is_file.
        """
        return {
            "is_raster": job.is_raster() if hasattr(job, "is_raster") else False,
            "is_vector": job.is_vector() if hasattr(job, "is_vector") else False,
            "is_timeseries": (
                job.is_timeseries() if hasattr(job, "is_timeseries") else False
            ),
            "is_file": job.is_file() if hasattr(job, "is_file") else False,
        }

    def is_failed_file(self, path: Path, current_mtime: float) -> bool:
        """Check if a file was previously marked as failed to parse.

        Args:
            path: Path to check
            current_mtime: Current modification time of the file

        Returns:
            True if the file is in the cache as a failed parse and mtime matches.
        """
        with self._lock:
            if not self._ensure_initialized() or self._conn is None:
                return False

            cache_key = _normalize_cache_key(path)

            try:
                cursor = self._conn.execute(
                    "SELECT mtime, job_status FROM job_cache WHERE path = ?",
                    (cache_key,),
                )
                row = cursor.fetchone()

                if row is None:
                    return False

                cached_mtime, job_status = row
                return (
                    _mtime_matches(cached_mtime, current_mtime)
                    and job_status == "FAILED_PARSE"
                )

            except sqlite3.Error:
                return False

    # -------------------------------------------------------------------------
    # Fast dropdown/query methods - use indexed columns, no unpickling needed
    # -------------------------------------------------------------------------

    def get_dropdown_metadata(
        self,
        status_filter: typing.Optional[typing.List[str]] = None,
    ) -> typing.List[typing.Dict[str, typing.Any]]:
        """Get lightweight metadata for all jobs, suitable for dropdown population.

        This method reads only from indexed columns - no unpickling is needed,
        making it extremely fast even with hundreds of jobs.

        Args:
            status_filter: Optional list of job_status values to include.
                          If None, excludes only FAILED_PARSE entries.

        Returns:
            List of dicts with keys: job_id, job_status, script_id, script_name,
            extent_north, extent_south, extent_east, extent_west, path
        """
        with self._lock:
            if not self._ensure_initialized() or self._conn is None:
                return []

            try:
                if status_filter:
                    placeholders = ",".join("?" for _ in status_filter)
                    query = f"""
                        SELECT job_id, job_status, script_id, script_name,
                               extent_north, extent_south, extent_east, extent_west, path
                        FROM job_cache
                        WHERE job_status IN ({placeholders})
                    """
                    cursor = self._conn.execute(query, status_filter)
                else:
                    query = """
                        SELECT job_id, job_status, script_id, script_name,
                               extent_north, extent_south, extent_east, extent_west, path
                        FROM job_cache
                        WHERE job_status != 'FAILED_PARSE'
                    """
                    cursor = self._conn.execute(query)

                results = []
                for row in cursor:
                    results.append(
                        {
                            "job_id": row[0],
                            "job_status": row[1],
                            "script_id": row[2],
                            "script_name": row[3],
                            "extent_north": row[4],
                            "extent_south": row[5],
                            "extent_east": row[6],
                            "extent_west": row[7],
                            "path": row[8],
                        }
                    )
                return results

            except sqlite3.Error as exc:
                log(f"SQLite error getting dropdown metadata: {exc}")
                return []

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None
                self._initialized = False

    def __del__(self):
        """Ensure connection is closed on deletion."""
        self.close()
