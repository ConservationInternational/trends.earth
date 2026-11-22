"""Private owner API and multipart transfers for public web-map shares.

Capability links and signed upload URLs are deliberately kept in memory only.
This module does not log requests, responses, or transport exceptions.
"""

import base64
import http.client
import os
import ssl
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import requests
import socks


class ShareError(Exception):
    """An owner API or upload operation failed."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class ShareCancelled(ShareError):
    """The owner cancelled an upload."""


def _https_url(url):
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and (parsed.port is None or 1 <= parsed.port <= 65535)
            and not parsed.username
            and not parsed.password
            and not parsed.fragment
            and not any(ord(char) <= 32 or ord(char) == 127 for char in url)
        )
    except ValueError:
        return False


class _PartReader:
    def __init__(self, source, size, cancelled, progress, offset):
        self.source = source
        self.remaining = size
        self.size = size
        self.cancelled = cancelled
        self.progress = progress
        self.offset = offset

    def __len__(self):
        return self.size

    def read(self, size=-1):
        if self.cancelled():
            raise ShareCancelled("Upload cancelled")
        if self.remaining == 0 or size == 0:
            return b""
        size = min(self.remaining, 65536 if size < 0 else size)
        chunk = self.source.read(size)
        if not chunk:
            raise ShareError("Snapshot changed or ended during upload")
        self.remaining -= len(chunk)
        self.progress(self.offset + self.size - self.remaining)
        return chunk


def _proxy_for_url(url):
    """Resolve QGIS and environment proxies without exposing signed queries."""
    from qgis.core import QgsNetworkAccessManager
    from qgis.PyQt.QtCore import QUrl
    from qgis.PyQt.QtNetwork import QNetworkProxy, QNetworkProxyQuery

    parsed = urlsplit(url)
    safe_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    manager = QgsNetworkAccessManager.instance()
    proxies = manager.proxyFactory().queryProxy(QNetworkProxyQuery(QUrl(safe_url)))
    if not proxies:
        raise ShareError("Could not resolve the network proxy")
    proxy = proxies[0]
    proxy_type = proxy.type()
    types = QNetworkProxy.ProxyType
    if proxy_type == types.NoProxy:
        return None
    if proxy_type == types.DefaultProxy:
        environment = requests.utils.get_environ_proxies(safe_url)
        proxy_url = environment.get("https") or environment.get("all")
        if not proxy_url:
            return None
    elif proxy_type in (types.HttpProxy, types.Socks5Proxy):
        host = proxy.hostName()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        auth = ""
        if proxy.user() or proxy.password():
            auth = f"{quote(proxy.user(), safe='')}:{quote(proxy.password(), safe='')}@"
        scheme = "http" if proxy_type == types.HttpProxy else "socks5h"
        proxy_url = f"{scheme}://{auth}{host}:{proxy.port()}"
    else:
        raise ShareError("The configured network proxy type is not supported")
    try:
        parsed_proxy = urlsplit(proxy_url)
        if (
            parsed_proxy.scheme not in ("http", "socks5", "socks5h")
            or not parsed_proxy.hostname
            or (parsed_proxy.port is not None and not 1 <= parsed_proxy.port <= 65535)
            or parsed_proxy.path not in ("", "/")
            or parsed_proxy.query
            or parsed_proxy.fragment
        ):
            raise ValueError
    except ValueError:
        raise ShareError(
            "The network proxy must be a valid HTTP or SOCKS5 proxy URL"
        ) from None
    return proxy_url


class _UploadSession:
    """Send signed URLs without passing their query strings to HTTP loggers."""

    def put(self, url, data, headers, timeout, allow_redirects):
        parsed = urlsplit(url)
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        proxy_url = _proxy_for_url(url)
        proxy = urlsplit(proxy_url) if proxy_url else None
        ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get(
            "CURL_CA_BUNDLE"
        )
        context = ssl.create_default_context(cafile=ca_bundle or None)
        if proxy and proxy.scheme == "http":
            connection = http.client.HTTPSConnection(
                proxy.hostname, proxy.port or 80, timeout=timeout, context=context
            )
            tunnel_headers = {}
            if proxy.username is not None:
                credentials = (
                    f"{unquote(proxy.username)}:{unquote(proxy.password or '')}"
                )
                token = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
                tunnel_headers["Proxy-Authorization"] = f"Basic {token}"
            connection.set_tunnel(
                parsed.hostname, parsed.port or 443, headers=tunnel_headers
            )
        else:
            connection = http.client.HTTPSConnection(
                parsed.hostname, parsed.port, timeout=timeout, context=context
            )
            if proxy:

                def connect(address, timeout=None, source_address=None):
                    return socks.create_connection(
                        address,
                        timeout=timeout,
                        source_address=source_address,
                        proxy_type=socks.SOCKS5,
                        proxy_addr=proxy.hostname,
                        proxy_port=proxy.port or 1080,
                        proxy_rdns=proxy.scheme == "socks5h",
                        proxy_username=unquote(proxy.username)
                        if proxy.username
                        else None,
                        proxy_password=unquote(proxy.password)
                        if proxy.password
                        else None,
                    )

                connection._create_connection = connect
        connection.set_debuglevel(0)
        try:
            connection.putrequest("PUT", target, skip_accept_encoding=True)
            connection.putheader("Content-Length", headers["Content-Length"])
            connection.endheaders()
            while chunk := data.read(65536):
                connection.send(chunk)
            reply = connection.getresponse()
            return _UploadResponse(reply.status, reply.getheader("ETag"))
        finally:
            connection.close()

    def close(self):
        pass


class _UploadResponse:
    def __init__(self, status, etag):
        self.status_code = status
        self.headers = {"ETag": etag}


class ShareClient:
    """Use a short-lived owner token supplied by the plugin's login flow."""

    def __init__(self, base_url, access_token, timeout=30):
        if not _https_url(base_url) or urlsplit(base_url).query:
            raise ShareError("The sharing API must use an HTTPS URL")
        if not access_token:
            raise ShareError("Authentication is required for web-map sharing")
        self.base_url = base_url.rstrip("/")
        self._token = access_token
        self.timeout = timeout
        self._api_session = requests.Session()
        # Do not let netrc or requests override the explicitly resolved proxy.
        self._api_session.auth = lambda request: request
        self._api_session.trust_env = False
        self._upload_session = _UploadSession()

    def close(self):
        self._api_session.close()
        self._upload_session.close()
        self._token = None

    def _request(self, method, path, payload=None):
        url = self.base_url + "/api/v1/shares" + path
        proxy = _proxy_for_url(url)
        try:
            response = self._api_session.request(
                method,
                url,
                headers={"Authorization": f"Bearer {self._token}"},
                json=payload,
                timeout=self.timeout,
                allow_redirects=False,
                proxies={"https": proxy} if proxy else {},
                verify=os.environ.get("REQUESTS_CA_BUNDLE")
                or os.environ.get("CURL_CA_BUNDLE")
                or True,
            )
        except requests.RequestException:
            raise ShareError("Could not contact the sharing API") from None
        if response.status_code not in (200, 201, 202):
            # Do not include an untrusted body that could contain a signed URL.
            descriptions = {
                400: "The share declaration or snapshot size is invalid",
                401: "Authentication expired; sign in again",
                403: "Sharing is not permitted for this account",
                409: "The share is not ready for this operation",
                429: "Storage quota, share limit or request rate exceeded",
                503: "Sharing service is unavailable or not ready; try again",
            }
            detail = descriptions.get(response.status_code, "Sharing request failed")
            raise ShareError(
                f"{detail} (HTTP {response.status_code})", response.status_code
            )
        try:
            result = response.json()
            return result["data"]
        except (ValueError, KeyError, TypeError):
            raise ShareError("Invalid response from the sharing API") from None

    def create(self, title, retention_days, layers):
        return self._request(
            "POST",
            "",
            {"title": title, "retention_days": retention_days, "layers": layers},
        )

    def list(self):
        return self._request("GET", "")

    def storage(self):
        return self._request("GET", "/storage")

    def status(self, share_id):
        return self._request("GET", "/" + _share_id(share_id))

    def publish(self, share_id):
        return self._request("POST", "/" + _share_id(share_id) + "/publish")

    def rotate(self, share_id):
        return self._request("POST", "/" + _share_id(share_id) + "/rotate")

    def revoke(self, share_id):
        return self._request("DELETE", "/" + _share_id(share_id))

    def complete(self, share_id, layers):
        return self._request(
            "POST", "/" + _share_id(share_id) + "/complete", {"layers": layers}
        )

    def _parts(self, share_id, layer_id, file_size):
        result = self._request(
            "POST",
            "/" + _share_id(share_id) + "/uploads",
            {"layer_id": _share_id(layer_id)},
        )
        if not isinstance(result, dict) or result.get("layer_id") != layer_id:
            raise ShareError("Invalid upload response from the sharing API")
        parts = result.get("parts")
        if not isinstance(parts, list) or not 1 <= len(parts) <= 10000:
            raise ShareError("Invalid multipart upload description")
        total = 0
        for number, part in enumerate(parts, 1):
            if (
                not isinstance(part, dict)
                or type(part.get("part_number")) is not int
                or part["part_number"] != number
                or type(part.get("size_bytes")) is not int
                or part["size_bytes"] <= 0
                or not isinstance(part.get("url"), str)
                or not _https_url(part["url"])
            ):
                raise ShareError("Invalid multipart upload description")
            total += part["size_bytes"]
        if total != file_size:
            raise ShareError("Upload size does not match the snapshot")
        return parts

    def upload(
        self, share_id, layer_id, path, cancelled=lambda: False, progress=lambda _: None
    ):
        """Upload a snapshot and return its API completion-manifest entry.

        A 403 refreshes expired URLs once for the current part. A later retry
        can call this method again; uploading a part number replaces that part.
        """
        try:
            with open(path, "rb") as source:
                source.seek(0, 2)
                file_size = source.tell()
                source.seek(0)
                parts = self._parts(share_id, layer_id, file_size)
                completed = []
                offset = 0
                for index in range(len(parts)):
                    size = parts[index]["size_bytes"]
                    for attempt in range(2):
                        if cancelled():
                            raise ShareCancelled("Upload cancelled")
                        source.seek(offset)
                        reader = _PartReader(source, size, cancelled, progress, offset)
                        try:
                            response = self._upload_session.put(
                                parts[index]["url"],
                                data=reader,
                                headers={"Content-Length": str(size)},
                                timeout=self.timeout,
                                allow_redirects=False,
                            )
                        except (OSError, http.client.HTTPException):
                            raise ShareError("Could not upload the snapshot") from None
                        if response.status_code == 403 and attempt == 0:
                            refreshed = self._parts(share_id, layer_id, file_size)
                            if [p["size_bytes"] for p in refreshed] != [
                                p["size_bytes"] for p in parts
                            ]:
                                raise ShareError("Multipart upload layout changed")
                            parts = refreshed
                            continue
                        if response.status_code != 200:
                            raise ShareError(
                                f"Snapshot upload returned HTTP {response.status_code}"
                            )
                        etag = response.headers.get("ETag")
                        if reader.remaining or not etag or len(etag) > 256:
                            raise ShareError("Invalid multipart upload response")
                        completed.append({"part_number": index + 1, "etag": etag})
                        offset += size
                        break
                return {"layer_id": layer_id, "parts": completed}
        except OSError:
            raise ShareError("Could not read the snapshot file") from None


def _share_id(value):
    from uuid import UUID

    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ShareError("Invalid share or layer ID") from None
