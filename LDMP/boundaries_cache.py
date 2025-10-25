"""
/***************************************************************************
 LDMP - A QGIS plugin
 This plugin supports monitoring and reporting of land degradation to the UNCCD
 and in support of the SDG Land Degradation Neutrality (LDN) target.
                              -------------------
        begin                : 2017-05-23
        git sha              : $Format:%H$
        copyright            : (C) 2017 by Conservation International
        email                : trends.earth@conservation.org
 ***************************************************************************/
"""

import json
import os
import time
import typing
from datetime import datetime, timezone
from pathlib import Path

from .logger import log


class BoundariesCache:
    """
    Manages intelligent caching of administrative boundaries downloaded from the API.

    Uses server-side last updated timestamps for cache validation instead of arbitrary
    TTL expiration. Server timestamps are checked weekly to minimize API overhead.
    """

    def __init__(self, cache_dir: typing.Optional[str] = None):
        """
        Initialize the boundaries cache.

        Args:
            cache_dir: Directory to store cache files. Defaults to plugin data directory.
        """
        if cache_dir is None:
            cache_dir = os.path.join(os.path.dirname(__file__), "data")

        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

        # Check server for updates only monthly (30 days)
        self.server_check_ttl = 30 * 24 * 3600  # 30 days

    def get_boundaries_list_cache_file(self, release_type: str = "gbOpen") -> Path:
        """Get cache file path for boundaries list."""
        return self.cache_dir / f"boundaries_list_{release_type}.json"

    def get_boundary_geojson_cache_file(
        self, country_code: str, admin_level: int, shape_id: typing.Optional[str] = None
    ) -> Path:
        """Get cache file path for boundary GeoJSON."""
        cache_key = f"{country_code}_adm{admin_level}"
        # Note: shape_id is no longer used in cache key for admin1 since we cache
        # the full country-level GeoJSON containing all admin1 units
        return self.cache_dir / f"boundary_{cache_key}.json"

    def _get_server_check_cache_file(self, release_type: str = "gbOpen") -> Path:
        """Get cache file for server update check timestamp."""
        return self.cache_dir / f"server_check_{release_type}.json"

    def _should_check_server(self, release_type: str = "gbOpen") -> bool:
        """Check if it's time to check server for updates (monthly check)."""
        check_file = self._get_server_check_cache_file(release_type)

        if not check_file.exists():
            return True

        try:
            check_age = time.time() - check_file.stat().st_mtime
            return check_age >= self.server_check_ttl
        except (OSError, ValueError):
            return True

    def _update_server_check_timestamp(self, release_type: str = "gbOpen") -> None:
        """Update the server check timestamp to current time."""
        check_file = self._get_server_check_cache_file(release_type)
        try:
            check_file.touch()
            log(f"Updated server check timestamp: {check_file}")
        except OSError as e:
            log(f"Error updating server check timestamp: {e}")

    def _parse_server_timestamp(self, timestamp_str: str) -> typing.Optional[datetime]:
        """Parse server timestamp string to datetime object."""
        if not timestamp_str:
            return None

        try:
            # Handle ISO format with or without 'Z' suffix
            clean_timestamp = timestamp_str.replace("Z", "+00:00")
            return datetime.fromisoformat(clean_timestamp)
        except (ValueError, AttributeError):
            log(f"Error parsing server timestamp: {timestamp_str}")
            return None

    def _get_cache_metadata(self, cache_file: Path) -> typing.Optional[typing.Dict]:
        """Get metadata from cache file including server timestamp."""
        if not cache_file.exists():
            return None

        try:
            with cache_file.open("r", encoding="utf-8") as f:
                data = json.load(f)

            # Extract metadata - could be at root level or nested
            if isinstance(data, dict):
                if "_cache_metadata" in data:
                    return data["_cache_metadata"]
                elif "server_last_updated" in data:
                    # Legacy format
                    return {
                        "server_last_updated": data.get("server_last_updated"),
                        "cached_at": data.get("cached_at"),
                    }
            return None
        except (json.JSONDecodeError, OSError) as e:
            log(f"Error reading cache metadata from {cache_file}: {e}")
            return None

    def _save_with_metadata(
        self,
        cache_file: Path,
        data: typing.Any,
        server_timestamp: typing.Optional[str] = None,
    ) -> bool:
        """Save data to cache file with metadata."""
        try:
            cache_data = {
                "_cache_metadata": {
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                    "server_last_updated": server_timestamp,
                },
                "data": data,
            }

            with cache_file.open("w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)
            return True
        except (OSError, TypeError) as e:
            log(f"Error saving cache with metadata to {cache_file}: {e}")
            return False

    def _extract_data_from_cache(self, cache_file: Path) -> typing.Optional[typing.Any]:
        """Extract the actual data from a cache file, handling metadata."""
        try:
            with cache_file.open("r", encoding="utf-8") as f:
                cache_data = json.load(f)

            # Handle new format with metadata
            if isinstance(cache_data, dict) and "_cache_metadata" in cache_data:
                return cache_data.get("data")
            # Handle legacy format or direct data
            else:
                return cache_data
        except (json.JSONDecodeError, OSError) as e:
            log(f"Error extracting data from cache {cache_file}: {e}")
            return None

    def load_boundaries_list(
        self,
        release_type: str = "gbOpen",
        server_last_updated: typing.Optional[str] = None,
    ) -> typing.Optional[typing.List[typing.Dict]]:
        """
        Load boundaries list from cache if valid based on server timestamps.

        Args:
            release_type: geoBoundaries release type
            server_last_updated: Server's last updated timestamp (if known)

        Returns:
            Cached boundaries list or None if cache is invalid/missing
        """
        cache_file = self.get_boundaries_list_cache_file(release_type)

        if not cache_file.exists():
            return None

        # Get cache metadata
        cache_metadata = self._get_cache_metadata(cache_file)

        if server_last_updated and cache_metadata:
            # Compare with server timestamp if available
            cached_server_timestamp = cache_metadata.get("server_last_updated")
            if cached_server_timestamp:
                cached_time = self._parse_server_timestamp(cached_server_timestamp)
                server_time = self._parse_server_timestamp(server_last_updated)

                if cached_time and server_time:
                    if server_time > cached_time:
                        log(
                            f"Cache outdated - server has newer data: {server_last_updated} > {cached_server_timestamp}"
                        )
                        return None
                    else:
                        log(
                            f"Cache up to date based on server timestamp: {cached_server_timestamp}"
                        )

        # Load cached data
        data = self._extract_data_from_cache(cache_file)
        if data:
            log(f"Loaded boundaries list from cache: {cache_file}")
            return data
        else:
            log(f"Error reading boundaries list cache: {cache_file}")
            return None

    def save_boundaries_list(
        self,
        boundaries_list: typing.List[typing.Dict],
        release_type: str = "gbOpen",
        server_last_updated: typing.Optional[str] = None,
    ) -> bool:
        """
        Save boundaries list to cache with metadata.

        Args:
            boundaries_list: List of boundary data from API
            release_type: geoBoundaries release type
            server_last_updated: Server's last updated timestamp

        Returns:
            True if saved successfully, False otherwise
        """
        cache_file = self.get_boundaries_list_cache_file(release_type)

        if self._save_with_metadata(cache_file, boundaries_list, server_last_updated):
            log(
                f"Saved boundaries list to cache with server timestamp {server_last_updated}: {cache_file}"
            )
            return True
        else:
            log(f"Error saving boundaries list cache: {cache_file}")
            return False

    def load_boundary_geojson(
        self,
        country_code: str,
        admin_level: int,
        shape_id: typing.Optional[str] = None,
        server_last_updated: typing.Optional[str] = None,
    ) -> typing.Optional[typing.Dict]:
        """
        Load boundary GeoJSON from cache if valid based on server timestamps.

        For admin level 1, loads the complete country-level GeoJSON containing
        all admin1 units. The shape_id parameter is ignored for caching but
        kept for API compatibility.

        Args:
            country_code: ISO 3-letter country code
            admin_level: Administrative level (0 or 1)
            shape_id: Ignored for caching (kept for compatibility)
            server_last_updated: Server's last updated timestamp (if known)

        Returns:
            Cached GeoJSON data or None if cache is invalid/missing
        """
        cache_file = self.get_boundary_geojson_cache_file(
            country_code, admin_level, shape_id
        )

        if not cache_file.exists():
            return None

        # Get cache metadata
        cache_metadata = self._get_cache_metadata(cache_file)

        if server_last_updated and cache_metadata:
            # Compare with server timestamp if available
            cached_server_timestamp = cache_metadata.get("server_last_updated")
            if cached_server_timestamp:
                cached_time = self._parse_server_timestamp(cached_server_timestamp)
                server_time = self._parse_server_timestamp(server_last_updated)

                if cached_time and server_time:
                    if server_time > cached_time:
                        log(
                            f"GeoJSON cache outdated - server has newer data: {server_last_updated} > {cached_server_timestamp}"
                        )
                        return None
                    else:
                        log(
                            f"GeoJSON cache up to date based on server timestamp: {cached_server_timestamp}"
                        )

        # Load cached data
        data = self._extract_data_from_cache(cache_file)
        if data:
            log(f"Loaded boundary GeoJSON from cache: {cache_file}")
            return data
        else:
            log(f"Error reading boundary GeoJSON cache: {cache_file}")
            return None

    def save_boundary_geojson(
        self,
        geojson_data: typing.Dict,
        country_code: str,
        admin_level: int,
        shape_id: typing.Optional[str] = None,
        server_last_updated: typing.Optional[str] = None,
    ) -> bool:
        """
        Save boundary GeoJSON to cache with metadata.

        For admin level 1, saves the complete country-level GeoJSON containing
        all admin1 units. The shape_id parameter is ignored for caching but
        kept for API compatibility.

        Args:
            geojson_data: GeoJSON data to cache
            country_code: ISO 3-letter country code
            admin_level: Administrative level (0 or 1)
            shape_id: Ignored for caching (kept for compatibility)
            server_last_updated: Server's last updated timestamp

        Returns:
            True if saved successfully, False otherwise
        """
        cache_file = self.get_boundary_geojson_cache_file(
            country_code, admin_level, shape_id
        )

        if self._save_with_metadata(cache_file, geojson_data, server_last_updated):
            log(
                f"Saved boundary GeoJSON to cache with server timestamp {server_last_updated}: {cache_file}"
            )
            return True
        else:
            log(f"Error saving boundary GeoJSON cache: {cache_file}")
            return False

    def should_check_server_for_updates(self, release_type: str = "gbOpen") -> bool:
        """
        Check if it's time to query the server for updates (monthly check).

        Args:
            release_type: geoBoundaries release type

        Returns:
            True if server should be checked for updates, False otherwise
        """
        return self._should_check_server(release_type)

    def mark_server_checked(self, release_type: str = "gbOpen") -> None:
        """
        Mark that we've checked the server for updates.

        Args:
            release_type: geoBoundaries release type
        """
        self._update_server_check_timestamp(release_type)

    def is_boundaries_list_cache_valid(
        self,
        release_type: str = "gbOpen",
        server_last_updated: typing.Optional[str] = None,
    ) -> bool:
        """
        Check if boundaries list cache is valid based on server timestamp.

        Args:
            release_type: geoBoundaries release type
            server_last_updated: Server's last updated timestamp

        Returns:
            True if cache is valid, False otherwise
        """
        cache_file = self.get_boundaries_list_cache_file(release_type)

        if not cache_file.exists():
            return False

        if not server_last_updated:
            # No server timestamp to compare - assume cache is valid if file exists
            return True

        cache_metadata = self._get_cache_metadata(cache_file)
        if not cache_metadata:
            return False

        cached_server_timestamp = cache_metadata.get("server_last_updated")
        if not cached_server_timestamp:
            # No server timestamp in cache - assume invalid
            return False

        cached_time = self._parse_server_timestamp(cached_server_timestamp)
        server_time = self._parse_server_timestamp(server_last_updated)

        if cached_time and server_time:
            return server_time <= cached_time

        return False

    def is_boundary_geojson_cache_valid(
        self,
        country_code: str,
        admin_level: int,
        shape_id: typing.Optional[str] = None,
        server_last_updated: typing.Optional[str] = None,
    ) -> bool:
        """
        Check if boundary GeoJSON cache is valid based on server timestamp.

        Args:
            country_code: ISO 3-letter country code
            admin_level: Administrative level (0 or 1)
            shape_id: Specific shape ID for admin1 units
            server_last_updated: Server's last updated timestamp

        Returns:
            True if cache is valid, False otherwise
        """
        cache_file = self.get_boundary_geojson_cache_file(
            country_code, admin_level, shape_id
        )

        if not cache_file.exists():
            return False

        if not server_last_updated:
            # No server timestamp to compare - assume cache is valid if file exists
            return True

        cache_metadata = self._get_cache_metadata(cache_file)
        if not cache_metadata:
            return False

        cached_server_timestamp = cache_metadata.get("server_last_updated")
        if not cached_server_timestamp:
            # No server timestamp in cache - assume invalid
            return False

        cached_time = self._parse_server_timestamp(cached_server_timestamp)
        server_time = self._parse_server_timestamp(server_last_updated)

        if cached_time and server_time:
            return server_time <= cached_time

        return False

    def clear_cache(self, older_than_days: typing.Optional[int] = None) -> int:
        """
        Clear cached files.

        Args:
            older_than_days: Only clear files older than this many days.
                           If None, clear all cache files.

        Returns:
            Number of files cleared
        """
        cleared_count = 0

        try:
            for cache_file in self.cache_dir.glob("boundaries_*.json"):
                should_delete = True

                if older_than_days is not None:
                    try:
                        file_age_days = (time.time() - cache_file.stat().st_mtime) / (
                            24 * 3600
                        )
                        should_delete = file_age_days > older_than_days
                    except OSError:
                        pass  # Delete if we can't check age

                if should_delete:
                    try:
                        cache_file.unlink()
                        cleared_count += 1
                        log(f"Cleared cache file: {cache_file}")
                    except OSError as e:
                        log(f"Error deleting cache file {cache_file}: {e}")

            for cache_file in self.cache_dir.glob("boundary_*.json"):
                should_delete = True

                if older_than_days is not None:
                    try:
                        file_age_days = (time.time() - cache_file.stat().st_mtime) / (
                            24 * 3600
                        )
                        should_delete = file_age_days > older_than_days
                    except OSError:
                        pass

                if should_delete:
                    try:
                        cache_file.unlink()
                        cleared_count += 1
                        log(f"Cleared cache file: {cache_file}")
                    except OSError as e:
                        log(f"Error deleting cache file {cache_file}: {e}")

        except Exception as e:
            log(f"Error during cache cleanup: {e}")

        if cleared_count > 0:
            log(f"Cleared {cleared_count} cache files")

        return cleared_count


# Global cache instance
_boundaries_cache = None


def get_boundaries_cache() -> BoundariesCache:
    """Get the global boundaries cache instance."""
    global _boundaries_cache
    if _boundaries_cache is None:
        _boundaries_cache = BoundariesCache()
    return _boundaries_cache
