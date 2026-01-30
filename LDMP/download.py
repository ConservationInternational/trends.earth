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

import dataclasses
import gzip
import hashlib
import json
import os
import typing
import zipfile
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from qgis.core import (
    Qgis,
    QgsFileDownloader,
    QgsNetworkAccessManager,
    QgsNetworkReplyContent,
)
from qgis.PyQt import QtCore, QtNetwork, QtWidgets
from qgis.utils import iface

from .api import APIClient
from .constants import TIMEOUT, get_api_url
from .logger import log
from .worker import AbstractWorker, start_worker

if TYPE_CHECKING:
    from te_schemas import results as te_schemas_results


@dataclasses.dataclass()
class City:
    wof_id: str
    name: str
    geojson: typing.Dict
    name_de: str
    name_en: str
    name_es: str
    name_fr: str
    name_pt: str
    name_ru: str
    name_zh: str

    @classmethod
    def deserialize(cls, wof_id: str, raw_city: typing.Dict):
        return cls(
            wof_id=wof_id,
            name=raw_city["ADM1NAME"],
            geojson=raw_city["geojson"],
            name_de=raw_city["name_de"],
            name_en=raw_city["name_en"],
            name_es=raw_city["name_es"],
            name_fr=raw_city["name_fr"],
            name_pt=raw_city["name_pt"],
            name_ru=raw_city["name_ru"],
            name_zh=raw_city["name_zh"],
        )


@dataclasses.dataclass()
class Country:
    name: str
    code: str
    crs: str
    wrap: bool
    level1_regions: typing.Dict[str, str]

    @classmethod
    def deserialize(cls, name: str, raw_country: typing.Dict):
        regions = {}
        admin1_data = raw_country.get("admin1", {})
        if admin1_data:
            for admin_level1_name, details in admin1_data.items():
                regions[admin_level1_name] = details["code"]

        return cls(
            name=name,
            code=raw_country["code"],
            crs=raw_country["crs"],
            wrap=raw_country["wrap"],
            level1_regions=regions,
        )


class tr_download:
    @staticmethod
    def tr(message: str) -> str:
        return QtCore.QCoreApplication.translate("tr_download", message)


class BoundaryTimestampManager:
    """
    Manages server timestamp fetching for boundary operations.

    Caches the timestamp for a single session to avoid redundant API calls
    when multiple boundary operations occur in quick succession.
    """

    def __init__(self):
        self._cached_timestamp: typing.Optional[str] = None
        self._release_type: typing.Optional[str] = None

    def get_server_timestamp(
        self, release_type: str = "gbOpen", force_refresh: bool = False
    ) -> typing.Optional[str]:
        """
        Get cached server timestamp or fetch if needed.

        Args:
            release_type: geoBoundaries release type
            force_refresh: Force fetch even if cached

        Returns:
            Server timestamp string or None
        """
        # Return cached timestamp if same release type and not forcing refresh
        if (
            not force_refresh
            and self._cached_timestamp is not None
            and self._release_type == release_type
        ):
            log(
                f"Using cached server timestamp: {self._cached_timestamp} (release: {release_type})"
            )
            return self._cached_timestamp

        # Fetch fresh timestamp from API
        try:
            from . import api

            server_info = api.default_api_client.get_boundaries_last_updated(
                release_type
            )
            if server_info:
                timestamp = server_info.get("last_updated")
                if timestamp:
                    self._cached_timestamp = timestamp
                    self._release_type = release_type
                    log(
                        f"Fetched server timestamp: {timestamp} (release: {release_type})"
                    )
                    return timestamp
            else:
                log("Could not get server last updated timestamp")
                return None
        except Exception as e:
            log(f"Error fetching server timestamp: {e}")
            return None

    def clear_cache(self):
        """Clear cached timestamp to force fresh fetch on next call."""
        self._cached_timestamp = None
        self._release_type = None


# Global timestamp manager instance
_timestamp_manager = None


@contextmanager
def _boundary_download_feedback(
    message: str,
) -> typing.Iterator[typing.Optional[QtWidgets.QProgressBar]]:
    """Show progress feedback while downloading large boundary files."""

    app = QtWidgets.QApplication.instance()
    message_widget = None
    message_bar = None
    progress: typing.Optional[QtWidgets.QProgressBar] = None

    if iface:
        message_bar = iface.messageBar()
        if message_bar:
            message_widget = message_bar.createMessage(
                tr_download.tr("Downloading boundaries"), message
            )
            progress = QtWidgets.QProgressBar()
            if progress is not None:
                progress.setMaximum(0)
                progress.setMinimum(0)
                progress.setTextVisible(False)
                progress.setFormat("%p%")
                message_widget.layout().addWidget(progress)
            message_bar.pushWidget(message_widget, Qgis.Info)

    try:
        if app:
            app.setOverrideCursor(QtCore.Qt.WaitCursor)
            app.processEvents()
        yield progress
    finally:
        if app:
            app.restoreOverrideCursor()
            app.processEvents()
        if message_bar and message_widget:
            message_bar.popWidget(message_widget)


def get_timestamp_manager() -> BoundaryTimestampManager:
    """Get the global timestamp manager instance."""
    global _timestamp_manager
    if _timestamp_manager is None:
        _timestamp_manager = BoundaryTimestampManager()
    return _timestamp_manager


def local_check_hash_against_etag(path: Path, expected: str) -> bool:
    try:
        path_hash = hashlib.md5(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        result = False
    else:
        result = path_hash == expected
        if result:
            log(f"File hash verified for {path}")
        else:
            log(
                f"Failed verification of file hash for {path}. Expected {expected}, "
                f"but got {path_hash}"
            )
    return result


def verify_file_against_etag(
    path: typing.Union[str, Path], etag: "te_schemas_results.Etag"
) -> bool:
    """
    Verify a downloaded file against an etag, handling different cloud storage types.

    Supports:
    - AWS_MD5: Standard MD5 hex hash
    - AWS_MULTIPART: Multipart upload etag (cannot verify client-side, logs warning)
    - GCS_MD5: Base64-encoded MD5 hash
    - GCS_CRC32C: CRC32C checksum (not currently supported, logs warning)

    Args:
        path: Path to the file to verify
        etag: Etag object containing hash and type

    Returns:
        True if verification passed or was skipped, False if verification failed
    """
    import base64
    import binascii

    from te_schemas.results import EtagType

    path = Path(path)

    if not path.exists():
        log(f"Cannot verify etag for missing file: {path}")
        return False

    etag_type = etag.type
    expected_hash = etag.hash

    # Handle AWS multipart - cannot verify client-side without part info
    if etag_type == EtagType.AWS_MULTIPART:
        log(
            f"Skipping verification for {path} - AWS multipart etag cannot be "
            "verified client-side"
        )
        return True

    # Handle GCS CRC32C - would need crcmod library which may not be available
    if etag_type == EtagType.GCS_CRC32C:
        log(
            f"Skipping verification for {path} - GCS CRC32C verification not "
            "currently supported"
        )
        return True

    # Calculate file MD5
    try:
        file_md5 = hashlib.md5(path.read_bytes())
    except IOError as e:
        log(f"Error reading file for verification: {e}")
        return False

    # Handle AWS MD5 - hex encoded
    if etag_type == EtagType.AWS_MD5:
        file_hash = file_md5.hexdigest()
        if file_hash == expected_hash:
            log(f"File hash verified (AWS MD5) for {path}")
            return True
        else:
            log(
                f"Failed verification of file hash for {path}. "
                f"Expected {expected_hash}, but got {file_hash}"
            )
            return False

    # Handle GCS MD5 - base64 encoded
    if etag_type == EtagType.GCS_MD5:
        # Convert our hex hash to base64 for comparison
        file_hash_b64 = base64.b64encode(file_md5.digest()).decode("ascii")
        if file_hash_b64 == expected_hash:
            log(f"File hash verified (GCS MD5) for {path}")
            return True
        else:
            # Also try comparing as hex in case hash was already decoded
            file_hash_hex = file_md5.hexdigest()
            try:
                expected_hex = binascii.hexlify(base64.b64decode(expected_hash)).decode(
                    "ascii"
                )
                if file_hash_hex == expected_hex:
                    log(f"File hash verified (GCS MD5 decoded) for {path}")
                    return True
            except (ValueError, binascii.Error):
                pass

            log(
                f"Failed verification of file hash for {path}. "
                f"Expected {expected_hash}, but got {file_hash_b64}"
            )
            return False

    log(f"Unknown etag type {etag_type} for {path}, skipping verification")
    return True


def check_hash_against_etag(url, filename, expected=None):
    if not expected:
        h = APIClient(get_api_url(), TIMEOUT).get_header(url)
        if not h:
            log("Failed to fetch expected hash for {}".format(filename))
            return False
        else:
            if type(h) is QtNetwork.QNetworkReply:
                expected = h.header(QtNetwork.QNetworkRequest.ETagHeader).strip('"')
            elif type(h) is QgsNetworkReplyContent:
                expected = h.rawheader("ETag").strip('"')
            else:
                raise NotImplementedError

    with open(filename, "rb") as f:
        md5hash = hashlib.md5(f.read()).hexdigest()

    if md5hash == expected:
        log("File hash verified for {}".format(filename))
        return True
    else:
        log(
            "Failed verification of file hash for {}. Expected {}, but got {}".format(
                filename, expected, md5hash
            )
        )
        return False


def extract_zipfile(f, verify=True):
    filename = os.path.join(os.path.dirname(__file__), "data", f)
    url = "https://s3.amazonaws.com/trends.earth/sharing/{}".format(f)

    if os.path.exists(filename) and verify:
        if not check_hash_against_etag(url, filename):
            os.remove(filename)

    if not os.path.exists(filename):
        log("Downloading {}".format(f))
        # TODO: Dialog box with two options:
        #   1) Download
        #   2) Load from local folder
        worker = Download(url, filename)
        try:
            worker.start()
        except PermissionError:
            QtWidgets.QMessageBox.critical(
                None,
                tr_download.tr("Error"),
                tr_download.tr("Unable to write to {}.".format(filename)),
            )
            return False
        resp = worker.get_resp()
        if not resp:
            return False
        if not check_hash_against_etag(url, filename):
            return False

    try:
        with zipfile.ZipFile(filename, "r") as fin:
            fin.extractall(os.path.join(os.path.dirname(__file__), "data"))
        return True
    except zipfile.BadZipfile:
        os.remove(filename)
        return False


def read_json(f, verify=True):
    filename = os.path.join(os.path.dirname(__file__), "data", f)
    url = "https://s3.amazonaws.com/trends.earth/sharing/{}".format(f)

    if os.path.exists(filename) and verify:
        if not check_hash_against_etag(url, filename):
            os.remove(filename)

    if not os.path.exists(filename):
        log("Downloading {}".format(f))
        # TODO: Dialog box with two options:
        #   1) Download
        #   2) Load from local folder
        worker = Download(url, filename)
        try:
            worker.start()
        except PermissionError:
            QtWidgets.QMessageBox.critical(
                None,
                tr_download.tr("Error"),
                tr_download.tr(
                    "Unable to write to {}. Do you need administrator permissions?".format(
                        filename
                    )
                ),
            )
            return None
        resp = worker.get_resp()
        if not resp:
            return None
        if not check_hash_against_etag(url, filename):
            return None

    with gzip.GzipFile(filename, "r") as fin:
        json_bytes = fin.read()
        json_str = json_bytes.decode("utf-8")

    return json.loads(json_str)


def download_files(urls, out_folder):
    if out_folder == "":
        QtWidgets.QMessageBox.critical(
            None,
            tr_download.tr("Folder does not exist"),
            tr_download.tr("Folder {} does not exist.".format(out_folder)),
        )
        return None

    if not os.access(out_folder, os.W_OK):
        QtWidgets.QMessageBox.critical(
            None,
            tr_download.tr("Error"),
            tr_download.tr("Unable to write to {}.".format(out_folder)),
        )
        return None

    downloads = []
    for url in urls:
        out_path = os.path.join(out_folder, os.path.basename(url))
        if not os.path.exists(out_path) or not check_hash_against_etag(url, out_path):
            log("Downloading {} to {}".format(url, out_path))

            worker = Download(url, out_path)
            try:
                worker.start()
            except PermissionError:
                log("Unable to write to {}.".format(out_folder))
                QtWidgets.QMessageBox.critical(
                    None,
                    tr_download.tr("Error"),
                    tr_download.tr("Unable to write to {}.".format(out_folder)),
                )
                return None

            resp = worker.get_resp()
            if not resp:
                log("Error accessing {}.".format(url))
                QtWidgets.QMessageBox.critical(
                    None,
                    tr_download.tr("Error"),
                    tr_download.tr("Error accessing {}.".format(url)),
                )
                return None
            if not check_hash_against_etag(url, out_path):
                log("File verification failed for {}.".format(out_path))
                QtWidgets.QMessageBox.critical(
                    None,
                    tr_download.tr("Error"),
                    tr_download.tr("File verification failed for {}.".format(out_path)),
                )
                return None

            downloads.extend(out_path)

    return downloads


def get_admin_bounds() -> typing.Dict[str, Country]:
    """
    Get administrative boundaries from API or fallback to cached file.

    Returns:
        Dictionary mapping country names to Country objects
    """
    try:
        # Load boundaries from API using intelligent caching

        api_boundaries = _get_boundaries_from_api()
        if api_boundaries:
            log("Loaded administrative boundaries from Trends.Earth API")
            return api_boundaries

        log("Falling back to cached administrative boundaries bundle")
        cached_boundaries = _get_boundaries_from_local_cache()
        if cached_boundaries:
            return cached_boundaries

        log("No administrative boundaries available from API or cache", Qgis.Critical)
        return {}
    except Exception as e:
        log(f"Error loading boundaries from API: {e}")
        cached_boundaries = _get_boundaries_from_local_cache()
        if cached_boundaries:
            return cached_boundaries
        return {}


def _get_boundaries_from_api() -> typing.Optional[typing.Dict[str, Country]]:
    """
    Download and cache administrative boundaries from Trends.Earth API using intelligent caching.

    Uses server-side timestamps to determine cache validity. Only checks server for
    updates monthly to minimize API overhead.

    Returns:
        Dictionary mapping country names to Country objects, or None on error
    """
    from . import api
    from .boundaries_cache import get_boundaries_cache

    cache = get_boundaries_cache()
    release_type = "gbOpen"  # Default release type

    # Check if we should query server for updates (monthly check)
    should_check_server = cache.should_check_server_for_updates(release_type)
    server_last_updated = None

    if should_check_server:
        # Use shared timestamp manager to avoid redundant API calls
        timestamp_mgr = get_timestamp_manager()
        server_last_updated = timestamp_mgr.get_server_timestamp(release_type)

        if server_last_updated:
            # Mark that we've checked the server
            cache.mark_server_checked(release_type)

    # Try to load from cache with server timestamp validation
    cached_data = cache.load_boundaries_list(release_type, server_last_updated)
    if cached_data:
        log("Using valid cached boundaries list from API")
        return _convert_api_boundaries_to_countries(cached_data)

    # Fetch fresh data from API
    try:
        log("Fetching fresh boundaries list from API")
        api_response = api.default_api_client.get_boundaries_list(release_type)
        if not api_response:
            log("No boundaries data received from API")
            return None

        boundaries_list = api_response.get("boundaries") or api_response.get("data", [])
        server_timestamp = api_response.get("last_updated")

        if not boundaries_list:
            log("Empty boundaries list received from API")
            return None

        # Cache the boundaries list with server timestamp
        cache.save_boundaries_list(boundaries_list, release_type, server_timestamp)

        log(
            f"Retrieved and cached {len(boundaries_list)} countries from API with timestamp {server_timestamp}"
        )
        return _convert_api_boundaries_to_countries(boundaries_list)

    except Exception as e:
        log(f"Error fetching boundaries from API: {e}")
        return None


def _get_boundaries_from_local_cache() -> typing.Optional[typing.Dict[str, Country]]:
    """Load administrative boundaries from the packaged cache file."""

    from .boundaries_cache import get_boundaries_cache

    try:
        cache = get_boundaries_cache()
        cache_file = cache.get_boundaries_list_cache_file("gbOpen")

        if not cache_file.exists():
            log(f"Boundaries cache file not found: {cache_file}")
            return None

        with cache_file.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        if isinstance(data, dict):
            boundaries_list = data.get("data") or data.get("boundaries")
        else:
            boundaries_list = data

        if not boundaries_list:
            log("Packaged boundaries cache is empty or malformed", Qgis.Warning)
            return None

        log("Loaded administrative boundaries from packaged cache")
        return _convert_api_boundaries_to_countries(boundaries_list)
    except Exception as exc:
        log(f"Error loading boundaries from packaged cache: {exc}", Qgis.Warning)
        return None


def _convert_api_boundaries_to_countries(
    boundaries_list: typing.List[typing.Dict],
) -> typing.Dict[str, Country]:
    """
    Convert API boundaries list to Country objects dictionary.

    Args:
        boundaries_list: List of boundary data from API

    Returns:
        Dictionary mapping country names to Country objects
    """
    countries_regions = {}

    for boundary in boundaries_list:
        country_name = boundary.get("boundaryName")
        country_iso = boundary.get("boundaryISO")

        if not country_name or not country_iso:
            continue

        # Build admin1 regions dictionary
        admin1_regions = {}
        admin1_units = boundary.get("admin1_units", [])
        for unit in admin1_units:
            shape_name = unit.get("shapeName")
            shape_id = unit.get("shapeID")
            if shape_name and shape_id:
                admin1_regions[shape_name] = shape_id

        # Create Country object with API data
        country = Country(
            name=country_name,
            code=country_iso,
            crs="EPSG:4326",  # GeoBoundaries uses WGS84
            wrap=False,  # Default for most countries
            level1_regions=admin1_regions,
        )

        countries_regions[country_name] = country

    return countries_regions


def _extract_admin_unit_from_geojson(
    full_geojson: typing.Dict, target_shape_id: str
) -> typing.Optional[typing.Dict]:
    """
    Extract a specific admin unit from a full country-level GeoJSON by shape ID.

    Args:
        full_geojson: Complete GeoJSON containing all admin units for a country
        target_shape_id: The shape ID of the specific admin unit to extract

    Returns:
        GeoJSON containing only the requested admin unit, or None if not found
    """
    if not full_geojson or "features" not in full_geojson:
        return None

    # Find the feature with the matching shape ID
    matching_features = []
    normalized_target = str(target_shape_id).strip().lower()

    for feature in full_geojson.get("features", []):
        properties = feature.get("properties", {})
        shape_id = properties.get("shapeID") or properties.get("shapeName")

        if shape_id is None:
            continue

        if str(shape_id).strip().lower() == normalized_target:
            matching_features.append(feature)

    if not matching_features:
        available_ids = [
            str((f.get("properties") or {}).get("shapeID"))
            for f in full_geojson.get("features", [])
            if (f.get("properties") or {}).get("shapeID")
        ]
        sample_ids = ", ".join(available_ids[:5])
        log(
            "Admin unit with shape ID '{}' not found in GeoJSON. Sample IDs: {}".format(
                target_shape_id,
                sample_ids or "<none>",
            )
        )
        return None

    # Create new GeoJSON with only the matching feature(s)
    extracted_geojson = {"type": "FeatureCollection", "features": matching_features}

    # Copy any other top-level properties from the original
    for key, value in full_geojson.items():
        if key not in ["type", "features"]:
            extracted_geojson[key] = value

    log(f"Extracted admin unit '{target_shape_id}' from cached country-level GeoJSON")
    return extracted_geojson


def download_boundary_geojson(
    country_code: str, admin_level: int = 0, shape_id: typing.Optional[str] = None
) -> typing.Optional[typing.Dict]:
    """
    Download boundary GeoJSON from API for a specific country and admin level using intelligent caching.

    For admin level 1, downloads all admin1 units for the country in a single GeoJSON
    and extracts the specific unit by shape_id if requested. This is more efficient
    since GeoBoundaries provides all admin1 units in one response.

    Args:
        country_code: ISO 3-letter country code (e.g., 'USA', 'BRA')
        admin_level: Administrative level (0 for country, 1 for states/provinces)
        shape_id: Specific shape ID for admin1 units (optional, extracts from full dataset)

    Returns:
        GeoJSON dictionary or None on error
    """
    from . import api
    from .boundaries_cache import get_boundaries_cache

    cache = get_boundaries_cache()
    release_type = "gbOpen"  # Default release type

    # For admin1, always use country-level cache key (without shape_id)
    # since GeoBoundaries returns all admin1 units for the country
    cache_key = f"{country_code}_adm{admin_level}"

    # Check if we should query server for updates (monthly check)
    should_check_server = cache.should_check_server_for_updates(release_type)
    server_last_updated = None

    if should_check_server:
        # Use shared timestamp manager to avoid redundant API calls
        timestamp_mgr = get_timestamp_manager()
        server_last_updated = timestamp_mgr.get_server_timestamp(release_type)

        if server_last_updated:
            # Mark that we've checked the server
            cache.mark_server_checked(release_type)

    # Try to load from cache with server timestamp validation
    # For admin1, always load the full country-level GeoJSON (no shape_id in cache key)
    cached_geojson = cache.load_boundary_geojson(
        country_code, admin_level, None, server_last_updated
    )
    if cached_geojson:
        log(f"Using valid cached boundary data for {cache_key}")

        # If requesting a specific admin1 unit, extract it from the full GeoJSON
        if admin_level == 1 and shape_id:
            return _extract_admin_unit_from_geojson(cached_geojson, shape_id)

        return cached_geojson

    # Get boundaries list to find download URL
    # Try API first, then fall back to cached boundaries list
    try:
        log(f"Fetching fresh boundary data for {cache_key}")
        api_response = api.default_api_client.get_boundaries_list(release_type)
        if api_response:
            boundaries_list = api_response.get("boundaries") or api_response.get(
                "data", []
            )
            server_timestamp = api_response.get("last_updated")
        else:
            log("API unavailable, using cached boundaries list for download URLs")
            boundaries_list = None
            server_timestamp = None

        # If API failed, try to load boundaries list from cache
        if not boundaries_list:
            cache_file = cache.get_boundaries_list_cache_file(release_type)
            if cache_file.exists():
                try:
                    with cache_file.open("r", encoding="utf-8") as handle:
                        cached_data = json.load(handle)
                    if isinstance(cached_data, dict):
                        boundaries_list = cached_data.get("data") or cached_data.get(
                            "boundaries"
                        )
                    else:
                        boundaries_list = cached_data
                    log("Loaded boundaries list from cache for download URLs")
                except Exception as cache_err:
                    log(f"Error loading cached boundaries list: {cache_err}")
                    boundaries_list = None

        if not boundaries_list:
            log("Could not get boundaries list from API or cache")
            return None

        # Find the country
        country_boundary = None
        for boundary in boundaries_list:
            if boundary.get("boundaryISO") == country_code:
                country_boundary = boundary
                break

        if not country_boundary:
            log(f"Country {country_code} not found in boundaries list")
            return None

        # Get the appropriate download URL
        if admin_level == 0:
            download_url = country_boundary.get(
                "adm0_geojson_url"
            ) or country_boundary.get("gjDownloadURL")
        else:
            download_url = country_boundary.get(
                "adm1_geojson_url"
            ) or country_boundary.get("gjDownloadURL")

        if not download_url:
            log(f"No GeoJSON download URL found for {country_code} ADM{admin_level}")
            return None

        download_message = (
            f"{country_code} ADM{admin_level}"
            if admin_level == 0
            else f"{country_code} {shape_id}"
        )

        manager = QgsNetworkAccessManager.instance()
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(download_url))
        request.setRawHeader(b"User-Agent", b"trends.earth/1.0")
        request.setRawHeader(b"Accept-Encoding", b"gzip, deflate")

        reply = manager.get(request)
        loop = QtCore.QEventLoop()

        geojson_data: typing.Optional[typing.Dict] = None

        with _boundary_download_feedback(
            tr_download.tr("Downloading boundaries for {}...").format(download_message)
        ) as progress_bar:

            def _update_progress(bytes_received: int, bytes_total: int) -> None:
                if not progress_bar:
                    return
                if bytes_total > 0:
                    if progress_bar.maximum() != bytes_total:
                        progress_bar.setMaximum(int(bytes_total))
                        progress_bar.setTextVisible(True)
                    progress_bar.setValue(int(bytes_received))
                    received_mb = bytes_received / (1024 * 1024)
                    total_mb = bytes_total / (1024 * 1024)
                    progress_bar.setFormat(f"{received_mb:.1f}/{total_mb:.1f} MB")
                else:
                    progress_bar.setMaximum(0)
                    progress_bar.setValue(0)
                    progress_bar.setTextVisible(False)

            reply.downloadProgress.connect(_update_progress)

            def _on_finished() -> None:
                loop.quit()

            reply.finished.connect(_on_finished)

            if reply.isFinished():
                _on_finished()
            else:
                loop.exec_()

            try:
                reply.downloadProgress.disconnect(_update_progress)
            except TypeError:
                pass
            try:
                reply.finished.disconnect(_on_finished)
            except TypeError:
                pass

        if reply.error() != QtNetwork.QNetworkReply.NoError:
            log(f"Network reply error: {reply.errorString()}")
            reply.deleteLater()
            return None

        raw_bytes = bytes(reply.readAll())

        try:
            encoding = bytes(reply.rawHeader(b"Content-Encoding")).decode("utf-8")
        except Exception:
            encoding = ""

        try:
            if "gzip" in encoding.lower():
                raw_bytes = gzip.decompress(raw_bytes)
            geojson_text = raw_bytes.decode("utf-8")
            geojson_data = json.loads(geojson_text)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            log(f"Error parsing GeoJSON response: {e}")
            reply.deleteLater()
            return None
        finally:
            reply.deleteLater()

        if geojson_data is None:
            return None

        # Cache the full GeoJSON (without shape_id filtering)
        cache.save_boundary_geojson(
            geojson_data, country_code, admin_level, None, server_timestamp
        )

        log(
            f"Downloaded and cached boundary data for {cache_key} with timestamp {server_timestamp}"
        )

        if admin_level == 1 and shape_id:
            return _extract_admin_unit_from_geojson(geojson_data, shape_id)

        return geojson_data

    except Exception as e:
        log(f"Error downloading boundary GeoJSON: {e}")
        return None


def get_cities() -> typing.Dict[str, typing.Dict[str, City]]:
    cities_key = read_json("cities.json.gz", verify=False)
    countries_cities = {}
    if cities_key:
        for country_code, city_details in cities_key.items():
            country_cities = {}
            for wof_id, further_details in city_details.items():
                country_cities[wof_id] = City.deserialize(wof_id, further_details)
            countries_cities[country_code] = country_cities
    return countries_cities


class DownloadError(Exception):
    def __init__(self, message):
        self.message = message


class DownloadWorker(AbstractWorker):
    """worker, implement the work method here and raise exceptions if needed"""

    def __init__(self, url, outfile):
        AbstractWorker.__init__(self)
        self.url = url
        self.outfile = outfile

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        self.download_file(self.url, self.outfile)

        return True

    def download_file(self, url, outfile):
        try:
            loop = QtCore.QEventLoop()

            download_exit = partial(self.download_exit, loop)

            downloader = QgsFileDownloader(QtCore.QUrl(url), outfile)
            downloader.downloadCompleted.connect(self.download_finished)
            downloader.downloadExited.connect(download_exit)
            downloader.downloadCanceled.connect(download_exit)
            downloader.downloadError.connect(self.download_error)
            downloader.downloadProgress.connect(self.update_progress)

            downloader.startDownload()

            if self.killed:
                downloader.downloadProgress.connect(downloader.cancelDownload)

            loop.exec_()

        except Exception as e:
            log(tr_download.tr("Error in downloading file, {}").format(str(e)))

    def update_progress(self, value, total):
        if total > 0:
            self.progress.emit(value * 100 / total)

    def download_error(self, error):
        log(tr_download.tr(f"Error while downloading file to {self.outfile}, {error}"))
        raise DownloadError(
            "Unable to start download of {}, {}".format(self.url, error)
        )

    def download_finished(self):
        log(tr_download.tr(f"Finished downloading file to {self.outfile}"))

    def download_exit(self, loop):
        log(tr_download.tr(f"Download exited {self.outfile}"))
        loop.exit()


class Download:
    def __init__(self, url, outfile):
        self.resp = None
        self.exception = None
        self.url = url
        self.outfile = outfile

    def start(self):
        try:
            worker = DownloadWorker(self.url, self.outfile)
            pause = QtCore.QEventLoop()
            worker.finished.connect(pause.quit)
            worker.successfully_finished.connect(self.save_resp)
            worker.error.connect(self.save_exception)
            start_worker(
                worker, iface, tr_download.tr("Downloading {}").format(self.outfile)
            )
            pause.exec_()
            if self.get_exception():
                raise self.get_exception()

        except DownloadError:
            log("Download failed.")
            QtWidgets.QMessageBox.critical(
                None,
                tr_download.tr("Error"),
                tr_download.tr("Download failed. Check your internet connection."),
            )
        except Exception:
            QtWidgets.QMessageBox.critical(
                None,
                tr_download.tr("Error"),
                tr_download.tr("Problem running task for downloading file"),
            )
            log(tr_download.tr("An error occured when running task for"))
            return False
        return True

    def save_resp(self, resp):
        self.resp = resp

    def get_resp(self):
        return self.resp

    def save_exception(self, exception):
        self.exception = exception

    def get_exception(self):
        return self.exception
