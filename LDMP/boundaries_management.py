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

import typing

from . import download
from .boundaries_cache import get_boundaries_cache
from .logger import log


def clear_boundaries_cache(older_than_days=None):
    """
    Clear cached boundary files.

    Args:
        older_than_days: Only clear files older than this many days.
                        If None, clear all cache files.

    Returns:
        Number of files cleared
    """
    try:
        cache = get_boundaries_cache()
        cleared_count = cache.clear_cache(older_than_days)

        if cleared_count > 0:
            log(f"Cleared {cleared_count} boundary cache files")
            # Cache clearing will automatically force refresh on next access
        else:
            log("No boundary cache files to clear")

        return cleared_count

    except Exception as e:
        log(f"Error clearing boundary cache: {e}")
        return 0


def refresh_boundaries_from_api(release_type="gbOpen"):
    """
    Force refresh of boundaries data from API using intelligent caching.

    Args:
        release_type: geoBoundaries release type to refresh

    Returns:
        Dictionary with refresh results and statistics
    """
    from . import api

    result = {
        "success": False,
        "boundaries_count": 0,
        "server_last_updated": None,
        "error": None,
    }

    try:
        cache = get_boundaries_cache()

        # Clear existing cache for this release type
        cache_file = cache.get_boundaries_list_cache_file(release_type)
        if cache_file.exists():
            cache_file.unlink()

        # Also clear any server check timestamps to force fresh check
        server_check_file = cache._get_server_check_cache_file(release_type)
        if server_check_file.exists():
            server_check_file.unlink()

        # Fetch fresh data with server timestamp
        api_response = api.default_api_client.get_boundaries_list(release_type)
        if api_response:
            boundaries_list = api_response.get("boundaries", [])
            server_timestamp = api_response.get("last_updated")

            if boundaries_list:
                # Save to cache with server timestamp
                cache.save_boundaries_list(
                    boundaries_list, release_type, server_timestamp
                )

                # Update server check timestamp
                cache.mark_server_checked(release_type)

                result.update(
                    {
                        "success": True,
                        "boundaries_count": len(boundaries_list),
                        "server_last_updated": server_timestamp,
                    }
                )
                log(
                    f"Successfully refreshed {len(boundaries_list)} boundaries from API with timestamp {server_timestamp}"
                )
            else:
                result["error"] = "Empty boundaries list received from API"
        else:
            result["error"] = "No boundaries data received from API"

        # Force reload admin bounds cache
        admin_bounds = download.get_admin_bounds()
        if admin_bounds and result["success"]:
            log(f"Successfully refreshed admin bounds: {len(admin_bounds)} countries")

    except Exception as e:
        error_msg = f"Error refreshing boundaries from API: {e}"
        log(error_msg)
        result["error"] = str(e)

    return result


def get_cache_statistics():
    """
    Get statistics about cached boundary files and server check status.

    Returns:
        Dictionary with cache statistics
    """
    try:
        cache = get_boundaries_cache()

        # Count cache files
        boundaries_list_files = list(cache.cache_dir.glob("boundaries_*.json"))
        boundary_geojson_files = list(cache.cache_dir.glob("boundary_*.json"))
        server_check_files = list(cache.cache_dir.glob("server_check_*.json"))

        total_size = 0
        all_files = boundaries_list_files + boundary_geojson_files + server_check_files
        for cache_file in all_files:
            try:
                total_size += cache_file.stat().st_size
            except OSError:
                pass

        # Check server check status for default release type (monthly interval)
        release_type = "gbOpen"
        should_check = cache.should_check_server_for_updates(release_type)

        # Get server check file info if it exists
        server_check_file = cache._get_server_check_cache_file(release_type)
        last_server_check = None
        if server_check_file.exists():
            try:
                import time

                last_check_timestamp = server_check_file.stat().st_mtime
                last_server_check = time.ctime(last_check_timestamp)
            except OSError:
                pass

        return {
            "boundaries_list_files": len(boundaries_list_files),
            "boundary_geojson_files": len(boundary_geojson_files),
            "server_check_files": len(server_check_files),
            "total_files": len(all_files),
            "total_size_mb": total_size / (1024 * 1024),
            "cache_dir": str(cache.cache_dir),
            "should_check_server": should_check,
            "last_server_check": last_server_check,
            "release_type": release_type,
        }

    except Exception as e:
        log(f"Error getting cache statistics: {e}")
        return {
            "boundaries_list_files": 0,
            "boundary_geojson_files": 0,
            "server_check_files": 0,
            "total_files": 0,
            "total_size_mb": 0,
            "cache_dir": "Unknown",
            "should_check_server": True,
            "last_server_check": None,
            "error": str(e),
        }


def check_server_for_updates(release_type="gbOpen") -> typing.Dict[str, typing.Any]:
    """
    Check server for boundary updates and get current status.

    Args:
        release_type: geoBoundaries release type to check

    Returns:
        Dictionary with server check results
    """
    from . import api

    result = {
        "server_available": False,
        "server_last_updated": None,
        "cache_up_to_date": False,
        "should_update": False,
        "error": None,
    }

    try:
        cache = get_boundaries_cache()

        # Get server's last updated timestamp
        server_info = api.default_api_client.get_boundaries_last_updated(release_type)
        if server_info:
            server_timestamp = server_info.get("last_updated")
            result.update(
                {"server_available": True, "server_last_updated": server_timestamp}
            )

            # Check if local cache is up to date
            cache_valid = cache.is_boundaries_list_cache_valid(
                release_type, server_timestamp
            )
            result["cache_up_to_date"] = cache_valid
            result["should_update"] = not cache_valid

            # Update server check timestamp
            cache.mark_server_checked(release_type)

            log(
                f"Server check complete - last updated: {server_timestamp}, cache valid: {cache_valid}"
            )
        else:
            result["error"] = "Could not get server timestamp"
            log("Could not get server last updated timestamp")

    except Exception as e:
        error_msg = f"Error checking server for updates: {e}"
        log(error_msg)
        result["error"] = str(e)

    return result


def force_server_update_check(release_type="gbOpen") -> typing.Dict[str, typing.Any]:
    """
    Force an immediate server update check, bypassing monthly check interval.

    Args:
        release_type: geoBoundaries release type to check

    Returns:
        Dictionary with server check results and update actions
    """
    try:
        cache = get_boundaries_cache()

        # Clear server check timestamp to force check
        server_check_file = cache._get_server_check_cache_file(release_type)
        if server_check_file.exists():
            server_check_file.unlink()

        # Perform server check
        result = check_server_for_updates(release_type)

        # If update is needed, refresh the cache
        if result.get("should_update"):
            refresh_result = refresh_boundaries_from_api(release_type)
            result["refresh_performed"] = True
            result["refresh_success"] = refresh_result.get("success", False)
            result["refresh_error"] = refresh_result.get("error")
        else:
            result["refresh_performed"] = False

        return result

    except Exception as e:
        log(f"Error forcing server update check: {e}")
        return {"server_available": False, "error": str(e), "refresh_performed": False}


def validate_and_migrate_boundary_settings() -> bool:
    """
    Clear old boundary settings and start fresh.

    Users will  need to reselect their area of interest.
    Returns:
        bool: True if cleanup completed successfully
    """
    try:
        from LDMP import conf

        settings_manager = conf.settings_manager

        # Check if we have old name-based settings
        has_old_settings = (
            settings_manager.get_value(conf.Setting.COUNTRY_NAME)
            or settings_manager.get_value(conf.Setting.REGION_NAME)
            or settings_manager.get_value(conf.Setting.CITY_NAME)
            or settings_manager.get_value(conf.Setting.CITY_KEY)
        )

        if has_old_settings:
            log(
                "Clearing old boundary settings - users will need to reselect their area"
            )
            _clear_all_boundary_settings(settings_manager)

        # Also clean up legacy cache files
        clear_legacy_boundary_cache()

        return True

    except Exception as e:
        log(f"Error during QSettings cleanup: {e}")
        return False


def _clear_all_boundary_settings(settings_manager) -> None:
    """Clear all boundary-related settings."""
    from LDMP import conf

    # Clear new ID-based settings
    settings_manager.write_value(conf.Setting.COUNTRY_ID, "")
    settings_manager.write_value(conf.Setting.REGION_ID, "")
    settings_manager.write_value(conf.Setting.CITY_ID, "")

    # Clear legacy name-based settings
    settings_manager.write_value(conf.Setting.COUNTRY_NAME, "")
    settings_manager.write_value(conf.Setting.REGION_NAME, "")
    settings_manager.write_value(conf.Setting.CITY_NAME, "")
    settings_manager.write_value(conf.Setting.CITY_KEY, None)


def clear_legacy_boundary_cache() -> None:
    """
    Clear legacy boundary cache files.
    """
    try:
        from pathlib import Path

        from LDMP import conf

        base_dir = Path(conf.settings_manager.get_value(conf.Setting.BASE_DIR))
        cache_dir = base_dir / "cache"

        # List of legacy files to remove
        legacy_files = [
            "admin_bounds_key.json.gz",
            "admin_bounds_key.json",
            "countries_regions.json",
            "countries_regions.json.gz",
        ]

        for filename in legacy_files:
            file_path = cache_dir / filename
            if file_path.exists():
                log(f"Removing legacy boundary file: {file_path}")
                file_path.unlink()

        log("Legacy boundary cache cleanup completed")

    except Exception as e:
        log(f"Error during legacy cache cleanup: {e}")
