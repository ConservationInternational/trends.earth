"""API client that authenticates with an OAuth2 service credential.

The plugin's ``APIClient`` only supports email/password login. The e2e tests
authenticate as a dedicated test user through a service credential (OAuth2
client-credentials grant), so this subclass replaces the login flow while
reusing every other API call unchanged. Tokens are held in memory only and are
never written to the QGIS auth database.
"""

import threading
import time

from qgis.PyQt import QtNetwork

from LDMP.api import APIClient
from LDMP.logger import log

TOKEN_ENDPOINT = "/api/v1/oauth/token"
# Re-mint the token this many seconds before the server-reported expiry.
EXPIRY_BUFFER_SECONDS = 300


class ServiceCredentialAPIClient(APIClient):
    def __init__(self, url, client_id, client_secret, timeout=60, parent=None):
        super().__init__(url, timeout=timeout, parent=parent)
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_expires_at = 0.0
        self._spy_lock = threading.Lock()
        self.password_login_calls = 0
        self.token_mints = 0
        self.last_response = None

    def __repr__(self):
        return f"ServiceCredentialAPIClient(url={self.url!r})"

    def redact(self, text):
        """Remove the client secret and current access token from ``text``."""
        text = str(text)
        for secret in (self._client_secret, self._cached_access_token):
            if secret:
                text = text.replace(secret, "***")
        return text

    def pre_cache_credentials(self):
        pass

    def _store_tokens(self, access_token, refresh_token=None):
        self._cached_access_token = access_token
        self._cached_refresh_token = None

    def _get_stored_tokens(self):
        return self._cached_access_token, None

    def _clear_stored_tokens(self):
        self._cached_access_token = None
        self._cached_refresh_token = None
        self._token_expires_at = 0.0

    def _refresh_access_token(self, refresh_token):
        return None

    def _login_impl(self, authConfigId=None):
        if self._cached_access_token and time.time() < self._token_expires_at:
            return self._cached_access_token

        self._clear_stored_tokens()
        resp = self.call_api(
            TOKEN_ENDPOINT,
            method="post",
            payload={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            use_token=False,
        )
        access_token = resp.get("access_token") if isinstance(resp, dict) else None
        if not access_token:
            message = (
                "Unable to obtain an access token with the e2e service credential. "
                "Check TE_E2E_CLIENT_ID/TE_E2E_CLIENT_SECRET and that the credential "
                "has not expired or been revoked."
            )
            log(message)
            self.authentication_failed.emit(message)
            return None

        try:
            expires_in = float(resp.get("expires_in") or 1800)
        except (TypeError, ValueError):
            expires_in = 1800.0
        self._store_tokens(access_token)
        self._token_expires_at = time.time() + max(
            expires_in - EXPIRY_BUFFER_SECONDS, 60
        )
        with self._spy_lock:
            self.token_mints += 1
        log("Obtained access token via service credential")
        return access_token

    def logout(self):
        self._clear_stored_tokens()
        return True

    def _make_request(self, description, **kwargs):
        url = str(kwargs.get("url", ""))
        if url.rstrip("/").endswith("/auth"):
            with self._spy_lock:
                self.password_login_calls += 1
        resp = super()._make_request(description, **kwargs)
        self._record_response(kwargs.get("method", "get"), url, resp)
        return resp

    def _record_response(self, method, url, resp):
        """Remember the outcome of the latest request for failure diagnostics.

        The plugin only logs API errors, so without this a rejected call is
        indistinguishable from a timeout or a rate limit.
        """
        record = {
            "method": str(method).upper(),
            "endpoint": url.removeprefix(self.url),
            "status": None,
            "body": "",
            "retry_after": None,
        }
        if resp is None:
            record["body"] = "no response (timed out or connection failed)"
        else:
            try:
                record["status"] = resp.attribute(
                    QtNetwork.QNetworkRequest.HttpStatusCodeAttribute
                )
                if hasattr(resp, "peek"):
                    # peek() leaves the body unread for the plugin's parser.
                    body = bytes(resp.peek(2000))
                else:
                    body = bytes(resp.content())[:2000]
                record["body"] = body.decode("utf-8", errors="replace")
                retry_after = bytes(resp.rawHeader(b"Retry-After")).decode()
                record["retry_after"] = float(retry_after) if retry_after else None
            except Exception as exc:  # noqa: BLE001 - diagnostics only
                record["body"] = f"could not read response: {exc}"
        self.last_response = record

    def describe_last_response(self):
        record = getattr(self, "last_response", None)
        if not record:
            return "no API response recorded"
        status = record["status"] if record["status"] is not None else "none"
        body = " ".join(record["body"].split())[:300]
        return self.redact(
            f"{record['method']} {record['endpoint']} -> HTTP {status}: {body}"
        )
