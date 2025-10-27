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
from functools import partial
from pathlib import Path

from qgis.core import (
    QgsBlockingNetworkRequest,
    QgsFileDownloader,
    QgsNetworkReplyContent,
)
from qgis.PyQt import QtCore, QtNetwork, QtWidgets
from qgis.utils import iface

from .api import APIClient
from .constants import API_URL, TIMEOUT
from .logger import log
from .worker import AbstractWorker, start_worker


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
    def tr(message):
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


def check_hash_against_etag(url, filename, expected=None):
    if not expected:
        h = APIClient(API_URL, TIMEOUT).get_header(url)
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
        else:
            log("Failed to load boundaries from API")
            return {}
    except Exception as e:
        log(f"Error loading boundaries from API: {e}")
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

        boundaries_list = api_response.get("boundaries", [])
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
    for feature in full_geojson.get("features", []):
        properties = feature.get("properties", {})
        shape_id = properties.get("shapeID") or properties.get("shapeName")

        if shape_id == target_shape_id:
            matching_features.append(feature)

    if not matching_features:
        log(f"Admin unit with shape ID '{target_shape_id}' not found in GeoJSON")
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
    try:
        log(f"Fetching fresh boundary data for {cache_key}")
        api_response = api.default_api_client.get_boundaries_list(release_type)
        if not api_response:
            log("Could not get boundaries list from API")
            return None

        boundaries_list = api_response.get("boundaries", [])
        server_timestamp = api_response.get("last_updated")

        if not boundaries_list:
            log("Empty boundaries list received from API")
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
            download_url = country_boundary.get("adm0_geojson_url")
        else:
            download_url = country_boundary.get("adm1_geojson_url")

        if not download_url:
            log(f"No GeoJSON download URL found for {country_code} ADM{admin_level}")
            return None

        # Download the GeoJSON
        log(f"Downloading boundary GeoJSON from {download_url}")

        # Use QgsBlockingNetworkRequest for synchronous download

        request = QgsBlockingNetworkRequest()

        # Set custom headers
        url = QtCore.QUrl(download_url)
        network_request = QtNetwork.QNetworkRequest(url)
        network_request.setRawHeader(b"User-Agent", b"trends.earth/1.0")
        network_request.setRawHeader(b"Accept-Encoding", b"gzip, deflate, br")

        # Perform the request with timeout (in milliseconds)
        error_code = request.get(network_request, timeout=60000)

        if error_code != QgsBlockingNetworkRequest.NoError:
            log(f"Network error downloading boundary: {request.errorMessage()}")
            return None

        # Get the response content
        reply = request.reply()
        if reply.error() != QtNetwork.QNetworkReply.NoError:
            log(f"Network reply error: {reply.errorString()}")
            return None

        # Parse JSON response
        content = reply.content()
        try:
            geojson_data = json.loads(content.data().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            log(f"Error parsing GeoJSON response: {e}")
            return None

        # Cache the full GeoJSON (without shape_id filtering)
        # For admin1, this contains ALL admin1 units for the country
        cache.save_boundary_geojson(
            geojson_data, country_code, admin_level, None, server_timestamp
        )

        log(
            f"Downloaded and cached boundary data for {cache_key} with timestamp {server_timestamp}"
        )

        # If requesting a specific admin1 unit, extract it from the full GeoJSON
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
