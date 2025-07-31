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

import base64
import io
import json
import time
from urllib.parse import quote_plus

import backoff
import requests
from qgis.core import (
    QgsApplication,
    QgsNetworkAccessManager,
    QgsNetworkReplyContent,
    QgsSettings,
    QgsTask,
)
from qgis.PyQt import QtCore, QtNetwork

from . import auth, conf
from .constants import API_URL, TIMEOUT
from .logger import log


class tr_api:
    @staticmethod
    def tr(message):
        return QtCore.QCoreApplication.translate("tr_api", message)


###############################################################################
# Threading functions for calls to requests


class RequestTask(QgsTask):
    def __init__(
        self,
        description,
        url,
        method,
        payload,
        headers,
        timeout=30,
        skip_auth_manager=False,
    ):
        super().__init__(description, QgsTask.CanCancel)

        self.description = description
        self.url = url
        self.method = method
        self.payload = payload

        self.timeout = timeout
        self.headers = headers or {}
        self.skip_auth_manager = skip_auth_manager
        self.exception = None
        self.resp = None

    def run(self):
        try:
            settings = QgsSettings()
            auth_id = settings.value("trendsearth/auth")

            qurl = QtCore.QUrl(self.url)

            network_manager = QgsNetworkAccessManager().instance()
            network_manager.setTimeout(600000)

            network_request = QtNetwork.QNetworkRequest(qurl)

            # Only use auth manager if not explicitly skipped (e.g., for initial login)
            if not self.skip_auth_manager:
                auth_manager = QgsApplication.authManager()
                auth_manager.updateNetworkRequest(network_request, auth_id)

            network_request.setHeader(
                QtNetwork.QNetworkRequest.ContentTypeHeader, "application/json"
            )

            if len(self.headers) > 0:
                for header_name, header_value in self.headers.items():
                    network_request.setRawHeader(
                        QtCore.QByteArray(header_name.encode()),
                        QtCore.QByteArray(header_value.encode()),
                    )

            if self.method == "get":
                self.resp = network_manager.blockingGet(network_request)

            elif self.method == "post":
                request_data = None
                doc = QtCore.QJsonDocument({})

                if self.payload is not None:
                    # Work around to handle QJsonDocument failing to deal with
                    # dictionaries that contain nested values of OrderedDict.
                    try:
                        doc = QtCore.QJsonDocument(self.payload)
                    except TypeError:
                        request_data = bytes(json.dumps(self.payload), encoding="utf-8")

                request_data = (
                    doc.toJson(QtCore.QJsonDocument.Compact)
                    if request_data is None
                    else request_data
                )

                self.resp = network_manager.blockingPost(network_request, request_data)

            elif self.method == "update":
                doc = QtCore.QJsonDocument(self.payload)
                request_data = doc.toJson(QtCore.QJsonDocument.Compact)

                self.resp = network_manager.sendCustomRequest(
                    network_request, b"UPDATE", request_data
                )

                loop = QtCore.QEventLoop()
                self.resp.finished.connect(loop.quit)
                loop.exec_()

            elif self.method == "delete":
                empty_payload = {}
                doc = QtCore.QJsonDocument(empty_payload)
                request_data = doc.toJson(QtCore.QJsonDocument.Compact)

                self.resp = network_manager.sendCustomRequest(
                    network_request, b"DELETE", request_data
                )

                loop = QtCore.QEventLoop()
                self.resp.finished.connect(loop.quit)
                loop.exec_()

            elif self.method == "patch":
                doc = QtCore.QJsonDocument(self.payload)
                request_data = doc.toJson(QtCore.QJsonDocument.Compact)

                self.resp = network_manager.sendCustomRequest(
                    network_request, b"PATCH", request_data
                )

                loop = QtCore.QEventLoop()
                self.resp.finished.connect(loop.quit)
                loop.exec_()

            elif self.method == "head":
                self.resp = network_manager.head(network_request)

                loop = QtCore.QEventLoop()
                self.resp.finished.connect(loop.quit)
                loop.exec_()

            else:
                self.exception = ValueError(
                    "Unrecognized method: {}".format(self.method)
                )
                return False
        except Exception as exc:
            self.exception = exc
            return False

        return True

    def finished(self, result):
        if result:
            # Task completed successfully
            pass
        else:
            if self.exception is None:
                log(f"API {self.method} not successful - probably cancelled")
            else:
                try:
                    log(
                        f"API {self.method} not successful - exception: {self.exception}"
                    )
                    raise self.exception
                except requests.exceptions.ConnectionError:
                    self.error_message = tr_api.tr(
                        "Unable to login to Trends.Earth server. Check your "
                        "internet connection."
                    )
                except requests.exceptions.Timeout:
                    self.error_message = tr_api.tr(
                        "Unable to connect to Trends.Earth server."
                    )

        if self.resp is not None:
            log(f'API response from "{self.method}" request: {self.resp.error()}')
        else:
            log(f'API response from "{self.method}" request was None')


###############################################################################
# Other helper functions for api calls


def backoff_hdlr(details):
    log(
        "Backing off {wait:0.1f} seconds after {tries} tries "
        "calling function {target}".format(**details)
    )


class APIClient(QtCore.QObject):
    url: str

    def __init__(self, url, timeout=30):
        self.url = url
        self.timeout = timeout

    def _decode_jwt_payload(self, token):
        """Decode JWT payload to extract expiration time"""
        try:
            # JWT tokens have 3 parts separated by dots: header.payload.signature
            parts = token.split(".")
            if len(parts) != 3:
                log("Invalid JWT token format")
                return None

            # Decode the payload (second part)
            payload = parts[1]
            # Add padding if needed (JWT base64 encoding may not have padding)
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += "=" * padding

            decoded_bytes = base64.urlsafe_b64decode(payload)
            payload_data = json.loads(decoded_bytes.decode("utf-8"))

            return payload_data
        except Exception as e:
            log(f"Error decoding JWT payload: {e}")
            return None

    def _is_token_expired(self, token, buffer_seconds=300):
        """Check if JWT token is expired or will expire within buffer_seconds"""
        payload = self._decode_jwt_payload(token)
        if not payload:
            return True

        exp = payload.get("exp")
        if not exp:
            log("JWT token missing expiration claim")
            return True

        # Check if token expires within the buffer time (default 5 minutes)
        current_time = time.time()
        return current_time >= (exp - buffer_seconds)

    def _store_tokens(self, access_token, refresh_token=None):
        """Store access and refresh tokens securely"""
        settings = QgsSettings()

        if access_token:
            settings.setValue("trendsearth/access_token", access_token)
            log("Access token stored")

        if refresh_token:
            settings.setValue("trendsearth/refresh_token", refresh_token)
            log("Refresh token stored")

    def _get_stored_tokens(self):
        """Retrieve stored access and refresh tokens"""
        settings = QgsSettings()
        access_token = settings.value("trendsearth/access_token", None)
        refresh_token = settings.value("trendsearth/refresh_token", None)

        return access_token, refresh_token

    def _clear_stored_tokens(self):
        """Clear stored tokens"""
        settings = QgsSettings()
        settings.setValue("trendsearth/access_token", None)
        settings.setValue("trendsearth/refresh_token", None)
        log("Stored tokens cleared")

    def _refresh_access_token(self, refresh_token):
        """Use refresh token to get new access token"""
        if not refresh_token:
            log("No refresh token available")
            return None

        log("Attempting to refresh access token")

        resp = self.call_api(
            "/auth/refresh",
            method="post",
            payload={"refresh_token": refresh_token},
            use_token=False,  # Don't use token for refresh endpoint
        )

        if resp:
            access_token = resp.get("access_token")
            new_refresh_token = resp.get("refresh_token")  # May get new refresh token

            if access_token:
                # Store the new tokens
                self._store_tokens(access_token, new_refresh_token or refresh_token)
                log("Access token refreshed successfully")
                return access_token
            else:
                log("No access token in refresh response")
        else:
            log("Failed to refresh access token")

        return None

    def clean_api_response(self, resp):
        if resp is None:
            # Return 'None' unmodified
            response = resp
        else:
            try:
                # JSON conversion will fail if the server didn't return a json
                # response
                response = resp.json().copy()

                if "password" in response:
                    response["password"] = "**REMOVED**"

                if "access_token" in response:
                    response["access_token"] = "**REMOVED**"

                if "refresh_token" in response:
                    response["refresh_token"] = "**REMOVED**"

                response = json.dumps(response, indent=4, sort_keys=True)
            except ValueError:
                response = resp.text

        return response

    def login(self, authConfigId=None):
        # First check if we have valid stored tokens
        stored_access_token, stored_refresh_token = self._get_stored_tokens()

        # If we have an access token and it's not expired, use it
        if stored_access_token and not self._is_token_expired(stored_access_token):
            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                log("Using valid stored access token")
            return stored_access_token

        # If access token is expired but we have a refresh token, try to refresh
        if (
            stored_access_token
            and stored_refresh_token
            and self._is_token_expired(stored_access_token)
        ):
            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                log("Access token expired, attempting refresh")

            refreshed_token = self._refresh_access_token(stored_refresh_token)
            if refreshed_token:
                return refreshed_token
            else:
                log("Token refresh failed, clearing stored tokens and logging in fresh")
                self._clear_stored_tokens()

        # Fall back to fresh login
        authConfig = auth.get_auth_config(
            auth.TE_API_AUTH_SETUP, authConfigId=authConfigId
        )

        if (
            not authConfig
            or not authConfig.config("username")
            or not authConfig.config("password")
        ):
            log("API unable to login - setup auth configuration before using")
            return None

        resp = self.call_api(
            "/auth",
            method="post",
            payload={
                "email": authConfig.config("username"),
                "password": authConfig.config("password"),
            },
            use_token=False,  # Don't use token for initial auth
        )

        error_message = ""
        if resp:
            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                log(f"Login response received: {resp}")
            try:
                access_token = resp.get("access_token", None)
                refresh_token = resp.get("refresh_token", None)

                if access_token is None:
                    log("Unable to read Trends.Earth token in API response")
                    log(
                        f"Response keys: {list(resp.keys()) if resp else 'No response'}"
                    )

                    # Check if this is a 204 response (successful but no content)
                    if not resp or len(resp) == 0:
                        error_message = tr_api.tr(
                            "Authentication succeeded but no tokens returned. "
                            "The API authentication method may have changed."
                        )
                    else:
                        error_message = tr_api.tr(
                            "Unable to read token for Trends.Earth "
                            "server. Check username and password."
                        )
                    ret = None
                else:
                    # Store both tokens
                    self._store_tokens(access_token, refresh_token)
                    ret = access_token

                    if conf.settings_manager.get_value(conf.Setting.DEBUG):
                        log("Successfully logged in and stored tokens")
                        if refresh_token:
                            log("Refresh token also stored")
                        else:
                            log("No refresh token provided by server")

            except KeyError:
                log("API unable to login - check username and password")
                error_message = tr_api.tr(
                    "Unable to login to Trends.Earth. Check username and password."
                )
                ret = None
        else:
            log("Unable to access Trends.Earth server")
            error_message = tr_api.tr(
                "Unable to access Trends.Earth server. Check your internet connection"
            )
            ret = None

        if error_message:
            log(error_message)
            # iface.messageBar().pushCritical("Trends.Earth", error_message)

        return ret

    def logout(self):
        """Logout user and revoke tokens"""
        access_token, refresh_token = self._get_stored_tokens()

        # Try to revoke tokens on server if we have them
        if access_token:
            try:
                # Call logout endpoint to revoke the token on server side
                resp = self.call_api("/auth/logout", method="post", use_token=True)
                if resp:
                    log("Server-side logout successful")
                else:
                    log("Server-side logout failed, but clearing local tokens anyway")
            except Exception as e:
                log(f"Error during server-side logout: {e}")

        # Always clear local tokens and cached user ID
        self._clear_stored_tokens()

        # Clear cached user ID from settings
        try:
            conf.settings_manager.write_value(conf.Setting.USER_ID, None)
            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                log("Cleared cached user ID")
        except Exception as e:
            log(f"Warning: Could not clear cached user ID: {e}")

        log("User logged out and tokens cleared")

        return True

    def login_test(self, email, password):
        resp = self.call_api(
            "/auth", method="post", payload={"email": email, "password": password}
        )

        if resp:
            return True
        else:
            if not email or not password:
                log("API unable to login during login test - check username/password")
            return False

    @backoff.on_predicate(
        backoff.expo, lambda x: x is None, max_tries=3, on_backoff=backoff_hdlr
    )
    def _make_request(self, description, skip_auth_manager=False, **kwargs):
        api_task = RequestTask(
            description, skip_auth_manager=skip_auth_manager, **kwargs
        )
        QgsApplication.taskManager().addTask(api_task)
        result = api_task.waitForFinished((self.timeout + 1) * 1000)

        if not result:
            log("Request timed out")

        return api_task.resp

    def _clean_payload(self, payload):
        clean_payload = payload.copy()

        if "password" in clean_payload:
            clean_payload["password"] = "**REMOVED**"

        if "refresh_token" in clean_payload:
            clean_payload["refresh_token"] = "**REMOVED**"

        return clean_payload

    def call_api(self, endpoint, method="get", payload=None, use_token=False):
        token = None
        if use_token:
            token = self.login()

            if token:
                if conf.settings_manager.get_value(conf.Setting.DEBUG):
                    log("API loaded token.")
                headers = {"Authorization": f"Bearer {token}"}
            else:
                return None
        else:
            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                log("API no token required.")
            headers = {}

        # Only continue if don't need token or if token load was successful

        if (not use_token) or token:
            # Strip password out of payload for printing to QGIS logs

            if payload:
                clean_payload = self._clean_payload(payload)
            else:
                clean_payload = payload
            log('API calling {} with method "{}"'.format(endpoint, method))

            if conf.settings_manager.get_value(conf.Setting.DEBUG):
                log("API call payload: {}".format(clean_payload))
            resp = self._make_request(
                "Trends.Earth API call",
                url=self.url + endpoint,
                method=method,
                payload=payload,
                headers=headers,
                timeout=self.timeout,
                skip_auth_manager=(not use_token),  # Skip auth manager for login calls
            )
        else:
            resp = None

        if resp is not None:
            status_code = resp.attribute(
                QtNetwork.QNetworkRequest.HttpStatusCodeAttribute
            )

            if status_code in [200, 201, 204]:  # Accept success status codes
                if status_code == 204:
                    # 204 No Content - successful but no response body
                    log(
                        'API response from "{}" request: {}'.format(method, status_code)
                    )
                    ret = {}  # Return empty dict for 204 responses
                elif type(resp) is QtNetwork.QNetworkReply:
                    ret = resp.readAll()
                    ret = json.load(io.BytesIO(ret))
                elif type(resp) is QgsNetworkReplyContent:
                    ret = resp.content()
                    ret = json.load(io.BytesIO(ret))
                else:
                    err_msg = "Unknown object type: {}.".format(str(resp))
                    log(err_msg)
                    ret = None
            else:
                desc, status = resp.error(), resp.errorString()
                err_msg = "Error: {} (status {}).".format(desc, status)
                log(err_msg)

                # If we get a 401 (Unauthorized) error and we're using a token,
                # it might mean our token is invalid. Clear stored tokens to force fresh login.
                if status_code == 401 and use_token:
                    log("Received 401 error, clearing stored tokens for fresh login")
                    self._clear_stored_tokens()

                """
                iface.messageBar().pushCritical(
                    "Trends.Earth", "Error: {} (status {}).".format(desc, status)
                )
                """
                ret = None
        else:
            ret = None

        return ret

    def get_header(self, url):
        resp = self._make_request(
            "Get head",
            url=url,
            method="head",
            payload=None,
            headers=None,
            timeout=self.timeout,
        )

        if resp is not None:
            status_code = resp.attribute(
                QtNetwork.QNetworkRequest.HttpStatusCodeAttribute
            )
            if status_code == 200:
                ret = resp
            else:
                desc, status = resp.error(), resp.errorString()
                err_msg = "Error: {} (status {}).".format(desc, status)
                log(err_msg)
                """
                iface.messageBar().pushCritical(
                    "Trends.Earth", "Error: {} (status {}).".format(desc, status)
                )
                """
                ret = None

            return ret

    ################################################################################
    # Functions supporting access to individual api endpoints

    def recover_pwd(self, email):
        return self.call_api(
            "/api/v1/user/{}/recover-password".format(quote_plus(email)), "post"
        )

    def get_user(self, email="me"):
        resp = self.call_api(
            "/api/v1/user/{}".format(quote_plus(email)), use_token=True
        )

        if resp:
            return resp["data"]
        else:
            return None

    def delete_user(self, email="me"):
        resp = self.call_api("/api/v1/user/me", "delete", use_token=True)

        if resp:
            return True
        else:
            return None

    def register(self, email, name, organization, country):
        payload = {
            "email": email,
            "name": name,
            "institution": organization,
            "country": country,
        }

        return self.call_api("/api/v1/user", method="post", payload=payload)

    def update_user(self, email, name, organization, country):
        payload = {
            "email": email,
            "name": name,
            "institution": organization,
            "country": country,
        }

        return self.call_api("/api/v1/user/me", "patch", payload, use_token=True)

    # def update_password(self, password, repeatPassword):
    #     payload = {
    #         "email": email,
    #         "name": name,
    #         "institution": organization,
    #         "country": country,
    #     }
    #
    #     return self.call_api(
    #         "/api/v1/user/{}".format(quote_plus(email)),
    #         "patch",
    #         payload,
    #         use_token=True,
    #     )

    def get_execution(self, id=None, date=None):
        log("Fetching executions")
        query = ["include=script"]

        if id:
            query.append("user_id={}".format(quote_plus(id)))

        if date:
            query.append("updated_at={}".format(date))
        query = "?" + "&".join(query)

        resp = self.call_api(
            "/api/v1/execution{}".format(query), method="get", use_token=True
        )

        if not resp:
            return None
        else:
            return resp["data"]

    def get_script(self, id=None):
        if id:
            resp = self.call_api(
                "/api/v1/script/{}".format(quote_plus(id)), "get", use_token=True
            )
        else:
            resp = self.call_api("/api/v1/script", "get", use_token=True)

        if resp:
            return resp["data"]
        else:
            return None


default_api_client = APIClient(API_URL, TIMEOUT)
