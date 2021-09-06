# -*- coding: utf-8 -*-
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

from future import standard_library
standard_library.install_aliases()

from datetime import datetime
from dateutil import tz
import requests
import json
from urllib.parse import quote_plus

from PyQt5 import (
    QtCore,
    QtWidgets
)

from qgis.utils import iface
from qgis.core import (
    QgsAuthMethodConfig,
    QgsApplication,
    QgsTask,
)


from . import (
    conf,
    auth
)
from .logger import log
from .worker import (
    AbstractWorker,
    start_worker,
)

API_URL = 'https://api.trends.earth'
TIMEOUT = 20

def tr(message):
    return QtCore.QCoreApplication.translate("tr_api", message)


###############################################################################
# Threading functions for calls to requests

class RequestTask(QgsTask):
    def __init__(self, description, url, method, payload, headers):
        super().__init__(description, QgsTask.CanCancel)
        self.description = description
        self.url = url
        self.method = method
        self.payload = payload
        self.headers = headers
        self.exception = None
        self.resp = None

    def run(self):
        if self.method == 'get':
            self.resp = requests.get(self.url, json=self.payload, headers=self.headers, timeout=TIMEOUT)
        elif self.method == 'post':
            self.resp = requests.post(self.url, json=self.payload, headers=self.headers, timeout=TIMEOUT)
        elif self.method == 'update':
            self.resp = requests.update(self.url, json=self.payload, headers=self.headers, timeout=TIMEOUT)
        elif self.method == 'delete':
            self.resp = requests.delete(self.url, json=self.payload, headers=self.headers, timeout=TIMEOUT)
        elif self.method == 'patch':
            self.resp = requests.patch(self.url, json=self.payload, headers=self.headers, timeout=TIMEOUT)
        elif self.method == 'head':
            self.resp = requests.head(self.url, json=self.payload, headers=self.headers, timeout=TIMEOUT)
        else:
            self.exception = ValueError("Unrecognized method: {}".format(self.method))
            return False

        return True

    def finished(self, result):
        if result:
            log('Task completed')
        else:
            if self.exception is None:
                log(f'API {self.method} not successful - probably cancelled')

            elif self.exception is requests.exceptions.ConnectionError:
                log('API unable to access server - check internet connection')
                self.error_message = tr(
                    "Unable to login to Trends.Earth server. Check your "
                    "internet connection."
                )

            elif self.exception is requests.exceptions.Timeout:
                log('API unable to login - general error')
                self.error_message = tr(f"Unable to connect to Trends.Earth  server.")

            else:
                log(f'API {self.method} not successful - exception: {self.exception}')
                raise self.exception

        if self.resp is not None:
            log(f'API response from "{self.method}" request: {self.resp.status_code}')
        else:
            log(f'API response from "{self.method}" request was None')

        if conf.settings_manager.get_value(conf.Setting.DEBUG):
            log(f'API response from "{self.method}" request (data): '
                '{clean_api_response(self.resp))}')

###############################################################################
# Other helper functions for api calls


def clean_api_response(resp):
    if resp == None:
        # Return 'None' unmodified
        response = resp
    else:
        try:
            # JSON conversion will fail if the server didn't return a json
            # response
            response = resp.json().copy()

            if 'password' in response:
                response['password'] = '**REMOVED**'

            if 'access_token' in response:
                response['access_token'] = '**REMOVED**'
            response = json.dumps(response, indent=4, sort_keys=True)
        except ValueError:
            response = resp.text

    return response


def get_error_status(resp):
    try:
        # JSON conversion will fail if the server didn't return a json
        # response
        resp = resp.json()
    except ValueError:
        return ('Unknown error', None)
    status = resp.get('status', None)

    if not status:
        status = resp.get('status_code', 'None')
    desc = resp.get('detail', None)

    if not desc:
        desc = resp.get('description', 'Generic error')

    return (desc, status)


def login(authConfigId=None):
    authConfig = auth.get_auth_config(
        auth.TE_API_AUTH_SETUP,
        authConfigId=authConfigId
    )

    if (not authConfig or
            not authConfig.config('username') or
            not authConfig.config('password')):
        log('API unable to login - setup auth configuration before using')

        return None

    resp = call_api(
        '/auth',
        method='post',
        payload={
            "email": authConfig.config('username'),
            "password": authConfig.config('password')
        }
    )

    error_message = ''
    if resp:
        try:
            token = resp.get('access_token', None)

            if token is None:
                log('Unable to read Trends.Earth token in API response')
                error_message = tr("Unable to read token for Trends.Earth "
                                   "server. Check username and password.")
                ret = None
        except KeyError:
            log('API unable to login - check username and password')
            error_message = tr("Unable to login to Trends.Earth. "
                               "Check username and password.")
            ret = None
        else:
            ret = token
    else:
        log('Unable to access Trends.Earth server')
        error_message = tr("Unable to access Trends.Earth server. Check your "
                           "internet connection")
        ret = None

    if error_message:
        QtWidgets.QMessageBox.critical(None, tr("Error"), tr(error_message))

    return ret


def login_test(email, password):
    resp = call_api(
        '/auth',
        method='post',
        payload={
            "email": email,
            "password": password
        }
    )

    if resp:
        return True
    else:
        if not email or not password:
            log("API unable to login during login test - check "
                "username/password")
            QtWidgets.QMessageBox.critical(
                None,
                tr("Error"),
                tr(
                    "Unable to login to Trends.Earth. Check that "
                    "username and password are correct."
                )
            )

        return False


def _make_request(description, **kwargs):
    api_task = RequestTask(description, **kwargs)
    QgsApplication.taskManager().addTask(api_task)
    api_task.waitForFinished((TIMEOUT + 1) * 1000)
    return api_task.resp


def call_api(endpoint, method='get', payload=None, use_token=False):
    if use_token:
        token = login()

        if token:
            log("API loaded token.")
            headers = {'Authorization': f'Bearer {token}'}
        else:
            return
    else:
        log("API no token required.")
        headers = {}

    # Only continue if don't need token or if token load was successful

    if (not use_token) or token:
        # Strip password out of payload for printing to QGIS logs

        if payload:
            clean_payload = payload.copy()

            if 'password' in clean_payload:
                clean_payload['password'] = '**REMOVED**'
        else:
            clean_payload = payload
        log(u'API calling {} with method "{}"'.format(endpoint, method))

        if conf.settings_manager.get_value(conf.Setting.DEBUG):
            log(u'API call payload: {}'.format(clean_payload))
        resp = _make_request(
            'Trends.Earth API call',
            url=API_URL + endpoint,
            method=method,
            payload=payload,
            headers=headers
        )

    else:
        resp = None

    if resp != None:
        if resp.status_code == 200:
            ret = resp.json()
        else:
            desc, status = get_error_status(resp)
            QtWidgets.QMessageBox.critical(
                None, "Error", u"Error: {} (status {}).".format(desc, status))
            ret = None
    else:
        ret = None

    return ret


def get_header(url):
    resp = _make_request(
        'Get head',
        url=url,
        method='head',
        payload=None,
        headers=None
    )

    if resp != None:
        log(u'Response from "{}" header request: {}'.format(url, resp.status_code))

        if resp.status_code == 200:
            ret = resp.headers
        else:
            desc, status = get_error_status(resp)
            QtWidgets.QMessageBox.critical(
                None, "Error", u"Error: {} (status {}).".format(desc, status))
            ret = None
    else:
        log('Header request failed')
        ret = None

    return ret

################################################################################
# Functions supporting access to individual api endpoints


def recover_pwd(email):
    return call_api(u'/api/v1/user/{}/recover-password'.format(quote_plus(email)), 'post')


def get_user(email='me'):
    resp = call_api(u'/api/v1/user/{}'.format(quote_plus(email)), use_token=True)

    if resp:
        return resp['data']
    else:
        return None


def delete_user(email='me'):
    resp = call_api('/api/v1/user/me', 'delete', use_token=True)

    if resp:
        return True
    else:
        return None


def register(email, name, organization, country):
    payload = {"email": email,
               "name": name,
               "institution": organization,
               "country": country}

    return call_api('/api/v1/user', method='post', payload=payload)


def update_user(email, name, organization, country):
    payload = {"email": email,
               "name": name,
               "institution": organization,
               "country": country}

    return call_api('/api/v1/user/me', 'patch', payload, use_token=True)


def update_password(password, repeatPassword):
    payload = {"email": email,
               "name": name,
               "institution": organization,
               "country": country}

    return call_api(u'/api/v1/user/{}'.format(quote_plus(email)), 'patch', payload, use_token=True)


def get_execution(id=None, date=None):
    log('Fetching executions')
    query = ['include=script']

    if id:
        query.append(u'user_id={}'.format(quote_plus(id)))

    if date:
        query.append(u'updated_at={}'.format(date))
    query = "?" + "&".join(query)

    resp = call_api(u'/api/v1/execution{}'.format(query), method='get', use_token=True)

    if not resp:
        return None
    else:
        # do import here to avoid circular import
        from LDMP.jobs import Job, JobSchema

        data = resp['data']
        # Sort responses in descending order using start time by default
        data = sorted(data, key=lambda job_dict: round(datetime.strptime(job_dict['start_date'], '%Y-%m-%dT%H:%M:%S.%f').timestamp()), reverse=True)
        # Convert start/end dates into datatime objects in local time zone

        for job_dict in data:
            start_date = datetime.strptime(job_dict['start_date'], '%Y-%m-%dT%H:%M:%S.%f')
            start_date = start_date.replace(tzinfo=tz.tzutc())
            start_date = start_date.astimezone(tz.tzlocal())
            job_dict['start_date'] = start_date
            end_date = datetime.strptime(job_dict['end_date'], '%Y-%m-%dT%H:%M:%S.%f')
            end_date = end_date.replace(tzinfo=tz.tzutc())
            end_date = end_date.astimezone(tz.tzlocal())
            job_dict['end_date'] = end_date

        return data


def get_script(id=None):
    if id:
        resp = call_api(u'/api/v1/script/{}'.format(quote_plus(id)), 'get', use_token=True)
    else:
        resp = call_api(u'/api/v1/script', 'get', use_token=True)

    if resp:
        return resp['data']
    else:
        return None
