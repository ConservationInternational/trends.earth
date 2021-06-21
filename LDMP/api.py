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
    QgsApplication
)


from . import conf
from .logger import log
from .worker import (
    AbstractWorker,
    start_worker,
)

API_URL = 'https://api.trends.earth'
TIMEOUT = 20
AUTH_CONFIG_NAME = 'Trends.Earth'


class tr_api(object):
    def tr(message):
        return QtCore.QCoreApplication.translate("tr_api", message)


def init_auth_config(email=None):
    currentAuthConfig = None

    # check if an auth method with name AUTH_CONFIG_NAME was already set
    configs = QgsApplication.authManager().availableAuthMethodConfigs()
    previousAuthExist = False
    for config in configs.values():
        if config.name() == AUTH_CONFIG_NAME:
            currentAuthConfig = config
            previousAuthExist = True
            break

    if not previousAuthExist:
        # not found => craete a new one
        currentAuthConfig = QgsAuthMethodConfig()
        currentAuthConfig.setName(AUTH_CONFIG_NAME)

    # reset it's config values to set later new password when received
    currentAuthConfig.setMethod('Basic')
    currentAuthConfig.setUri(API_URL + '/auth')
    currentAuthConfig.setConfig('username', email)
    currentAuthConfig.setConfig('password', None)
    currentAuthConfig.setConfig('realm', None)

    if not previousAuthExist:
        # store a new auth config
        if not QgsApplication.authManager().storeAuthenticationConfig(currentAuthConfig):
            iface.messageBar().pushCritical(
                'Trends.Earth', tr_api.tr('Cannot init auth configuration'))
            return None
    else:
        # update existing
         if not QgsApplication.authManager().updateAuthenticationConfig(currentAuthConfig):
            iface.messageBar().pushCritical(
                'Trends.Earth', tr_api.tr('Cannot update auth configuration'))
            return None

    QtCore.QSettings().setValue("trends_earth/authId", currentAuthConfig.id())
    return currentAuthConfig.id()

def remove_current_auth_config():
    authConfigId = QtCore.QSettings().value("trends_earth/authId", None)
    if not authConfigId:
        iface.messageBar().pushCritical('Trends.Earth', tr_api.tr('No authentication set. Do it in Trends.Earth settings'))
        return None
    log('remove_current_auth_config with authId {}'.format(authConfigId))

    if not QgsApplication.authManager().removeAuthenticationConfig( authConfigId ):
        iface.messageBar().pushCritical('Trends.Earth', tr_api.tr('Cannot remove auth configuration with id: {}').format(authConfigId))
        return False

    QtCore.QSettings().setValue("trends_earth/authId", None)
    return True

def get_auth_config(authConfigId=None, warn=True):
    if not authConfigId:
        # not set? then retrieve from config if set
        authConfigId = QtCore.QSettings().value("trends_earth/authId", None)
        if not authConfigId:
            if warn:
                iface.messageBar().pushCritical('Trends.Earth', tr_api.tr('No authentication set. Do it in Trends.Earth settings'))
            return None
    log('get_auth_config with authId {}'.format(authConfigId))

    configs = QgsApplication.authManager().availableAuthMethodConfigs()
    message_bar = iface.messageBar()
    if not authConfigId in configs.keys():
        if warn:
            message_bar.pushCritical(
                'Trends.Earth',
                tr_api.tr(
                    f'Cannot retrieve credentials with authId: {authConfigId} setup '
                    f'correct credentials before'
                )
            )

        return None

    authConfig = QgsAuthMethodConfig()
    ok = QgsApplication.authManager().loadAuthenticationConfig(authConfigId, authConfig, True)
    if not ok:
        if warn:
            message_bar.pushCritical(
                'Trends.Earth',
                tr_api.tr(
                    f'Cannot retrieve credentials with authId: {authConfigId} setup '
                    f'correct credentials before'
                )
            )
        return None
    
    if not authConfig.isValid():
        if warn:
            message_bar.pushCritical(
                'Trends.Earth',
                tr_api.tr(f'Not valid auth configuration with authId: {authConfigId}')
            )
        return None

    # check if auth method is the only supported for no
    if authConfig.method() != 'Basic':
        if warn:
            message_bar.pushCritical(
                'Trends.Earth',
                tr_api.tr(
                    f'Auth method with authId: {authConfigId} is '
                    f'{authConfig.method()}. Only basic auth is supported '
                    f'by Trend.Earth'
                )
            )
        return None
    
    return authConfig

def get_user_email(warn=True):
    # get mail from authConfig
    authConfig = get_auth_config(warn=warn)
    if not authConfig:
        return None

    email = authConfig.config('username')
    if warn and email is None:
        QtWidgets.QMessageBox.critical(
            None,
            tr_api.tr("Error"),
            tr_api.tr("Please register with Trends.Earth before using this function.")
        )
        return None
    else:
        return email

###############################################################################
# Threading functions for calls to requests


class RequestWorker(AbstractWorker):
    """worker, implement the work method here and raise exceptions if needed"""

    def __init__(self, url, method, payload, headers):
        AbstractWorker.__init__(self)
        self.url = url
        self.method = method
        self.payload = payload
        self.headers = headers

    def work(self):
        self.toggle_show_progress.emit(False)
        self.toggle_show_cancel.emit(False)
        if self.method == 'get':
            resp = requests.get(self.url, json=self.payload, headers=self.headers, timeout=TIMEOUT)
        elif self.method == 'post':
            resp = requests.post(self.url, json=self.payload, headers=self.headers, timeout=TIMEOUT)
        elif self.method == 'update':
            resp = requests.update(self.url, json=self.payload, headers=self.headers, timeout=TIMEOUT)
        elif self.method == 'delete':
            resp = requests.delete(self.url, json=self.payload, headers=self.headers, timeout=TIMEOUT)
        elif self.method == 'patch':
            resp = requests.patch(self.url, json=self.payload, headers=self.headers, timeout=TIMEOUT)
        elif self.method == 'head':
            resp = requests.head(self.url, json=self.payload, headers=self.headers, timeout=TIMEOUT)
        else:
            raise ValueError("Unrecognized method: {}".format(method))
            resp = None
        return resp


class Request(object):
    def __init__(self, url, method='get', payload=None, headers={}, server_name='Trends.Earth'):
        self.resp = None
        self.exception = None

        self.url = url
        self.method = method
        self.payload = payload
        self.headers = headers
        self.server_name = server_name

    def start(self):
        try:
            worker = RequestWorker(self.url, self.method, self.payload, self.headers)
            pause = QtCore.QEventLoop()
            worker.finished.connect(pause.quit)
            worker.successfully_finished.connect(self.save_resp)
            worker.error.connect(self.save_exception)
            start_worker(worker, iface, tr_api.tr(u'Contacting {} server...'.format(self.server_name)))
            pause.exec_()
            if self.get_exception():
                raise self.get_exception()
        except requests.exceptions.ConnectionError:
            log('API unable to access server - check internet connection')
            QtWidgets.QMessageBox.critical(
                None,
                tr_api.tr("Error"),
                tr_api.tr(
                    f"Unable to login to {self.server_name} server. Check your "
                    f"internet connection."
                )
            )
            resp = None
        except requests.exceptions.Timeout:
            log('API unable to login - general error')
            QtWidgets.QMessageBox.critical(
                None,
                tr_api.tr("Error"),
                tr_api.tr(u"Unable to connect to {} server.".format(self.server_name))
            )
            resp = None

    def save_resp(self, resp):
        self.resp = resp

    def get_resp(self):
        return self.resp

    def save_exception(self, exception):
        self.exception = exception

    def get_exception(self):
        return self.exception

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
    authConfig = get_auth_config(authConfigId=authConfigId)
    if not authConfig :
        log('API unable to login - setup auth configuration before')
        QtWidgets.QMessageBox.critical(
            None,
            tr_api.tr("Error"),
            tr_api.tr(
                "Unable to login to Trends.Earth. Setup auth configuration before.")
        )
        return None

    email = authConfig.config('username')
    password = authConfig.config('password')

    if not email or not password:
        log('API unable to login - set username/password in auth config with id: {}'.format(authConfig.id()))
        QtWidgets.QMessageBox.critical(
            None,
            tr_api.tr("Error"),
            tr_api.tr(
                f"Unable to login to Trends.Earth. Set your username and password in auth config: {authConfig.name()!r}"
            )
        )
        return None

    resp = call_api('/auth', method='post', payload={"email": email, "password": password})

    if resp != None:
        QtCore.QSettings().setValue("trends_earth/authId", authConfig.id())

    return resp


def call_api(endpoint, method='get', payload=None, use_token=False):
    if use_token:
        login_resp = login()
        if login_resp:
            log("API loaded token.")
            headers = {'Authorization': 'Bearer {}'.format(login_resp['access_token'])}
        else:
            return
    else:
        log("API no token required.")
        headers = {}

    # Only continue if don't need token or if token load was successful
    if (not use_token) or (login_resp):
        # Strip password out of payload for printing to QGIS logs
        if payload:
            clean_payload = payload.copy()
            if 'password' in clean_payload:
                clean_payload['password'] = '**REMOVED**'
        else:
            clean_payload = payload
        log(u'API calling {} with method "{}" and payload: {}'.format(endpoint, method, clean_payload))
        worker = Request(API_URL + endpoint, method, payload, headers)
        worker.start()
        resp = worker.get_resp()
        if resp is not None:
            log(u'API response from "{}" request (code): {}'.format(method, resp.status_code))
        else:
            log(u'API response from "{}" request was None'.format(method))
        if conf.settings_manager.get_value(conf.Setting.DEBUG):
            log(u'API response from "{}" request (data): {}'.format(method, clean_api_response(resp)))
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
    worker = Request(url, 'head')
    worker.start()
    resp = worker.get_resp()

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
