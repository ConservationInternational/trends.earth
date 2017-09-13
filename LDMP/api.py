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
        email                : GEF-LDMP@conservation.org
 ***************************************************************************/
"""

import datetime
from dateutil import tz
import requests
import json
import threading

from urllib import quote_plus

from PyQt4.QtCore import QSettings

from qgis.utils import iface
mb = iface.messageBar()

from . import log

API_URL = 'http://api.resilienceatlas.org'

def get_user_email():
    email = QSettings().value("LDMP/email", None)
    if email is None:
        QtGui.QMessageBox.critical(None, self.tr("Error"),
                self.tr("Please register with the Land Degradation Monitoring Toolbox before using this function."))
        return False
    else:
        return email

def clean_api_response(resp):
    try:
        # JSON conversion will fail if the server didn't return a json 
        # response
        response = resp.json().copy()
        if response.has_key('password'):
            response['password'] = '**REMOVED**'
        if response.has_key('access_token'):
            response['access_token'] = '**REMOVED**'
        response = json.dumps(response, indent=4, sort_keys=True)
    except ValueError:
        response = resp.text
    return response

def get_error_status(resp):
    status = resp.get('status', None)
    if not status:
        status = resp.get('status_code', 'None')
    desc = resp.get('detail', None)
    if not desc:
        desc = resp.get('description', 'Generic error')
    return (desc, status)

def login(email=None, password=None):
    if (email == None):
        email = get_user_email()
    if (password == None):
        password = QSettings().value("LDMP/password", None)
    if not email or not password:
        mb.pushMessage("Error", "Unable to login to LDMP server. Check your username and password.", level=1, duration=5)
        return False

    log('API trying login for user {}'.format(email))
    resp = requests.post(API_URL + '/auth', json={"email" : email, "password" : password})
    log('API response to login for user {}: {}'.format(email, clean_api_response(resp)))

    if resp.status_code == 200:
        QSettings().setValue("LDMP/email", email)
        QSettings().setValue("LDMP/password", password)
        return resp
    else:
        resp = resp.json()
        desc, status = get_error_status(resp)
        mb.pushMessage("Error: {} (status {}).".format(desc, status),
                level=1, duration=5)
        return False

class API_Call(threading.Thread):
    """Run earth engine task against the ldmp API"""
    def __init__(self, endpoint, method='get', payload={}, use_token=False, start_now=True):
        threading.Thread.__init__(self)

        self.settings = QSettings()

        self.endpoint = endpoint
        self.method = method
        self.payload = payload
        self.use_token = use_token

        if start_now: self.start()

    def run(self):
        if self.use_token:
            resp = login()
            if resp:
                headers = {'Authorization': 'Bearer %s'%resp.json()['access_token']}
                log("API _call_api loaded token.")
            else: 
                return False
        else:
            headers = {}

        # Strip password out of payload for printing to QGIS logs
        clean_payload = self.payload.copy()
        if clean_payload.has_key('password'):
            clean_payload['password'] = '**REMOVED**'

        log('API _call_api calling {} with method "{}" and payload: {}'.format(self.endpoint, self.method, clean_payload))

        try:
            if self.method == 'get':
                resp = requests.get(API_URL + self.endpoint, json=self.payload, headers=headers)
            elif self.method == 'post':
                resp = requests.post(API_URL + self.endpoint, json=self.payload, headers=headers)
            elif self.method == 'update':
                resp = requests.update(API_URL + self.endpoint, json=self.payload, headers=headers)
            elif self.method == 'delete':
                resp = requests.delete(API_URL + self.endpoint, json=self.payload, headers=headers)
            elif self.method == 'patch':
                resp = requests.patch(API_URL + self.endpoint, json=self.payload, headers=headers)
            else:
                raise ValueError("Unrecognized method: {}".format(self.method))
        except requests.ConnectionError:
            mb.pushMessage("Error", "Unable to connect to LDMP server.", level=1, duration=5)
            return False

        log('API _call_api response from "{}" request: {}'.format(self.method, clean_api_response(resp)))

        if resp.status_code != 200:
            resp = resp.json()
            desc, status = get_error_status(resp)
            mb.pushMessage("Error: {} (status {}).".format(desc, status),
                    level=1, duration=5)
            self.resp = None
        else:
            self.resp = resp.json()

    def get_resp(self):
        self.join()
        return self.resp

class API:
    def __init__(self):
        self.settings = QSettings()

    def recover_pwd(self, email):
        call = API_Call('/api/v1/user/{}/recover-password'.format(quote_plus(email)), 'post')
        return call.get_resp()

    def get_user(self, email):
        call = API_Call('/api/v1/user/{}'.format(quote_plus(email)), use_token=True)
        return call.get_resp()['data']

    def register(self, email, name, organization, country):
        payload = {"email" : email,
                   "name" : name,
                   "institution": organization,
                   "country": country}
        call = API_Call('/api/v1/user', method='post', payload=payload)
        return call.get_resp()

    def calculate(self, script, params={}):
        call = API_Call('/api/v1/script/{}/run'.format(quote_plus(script)), 
                'post', params, use_token=True)
        return call.get_resp()

    def update_user(self, email, name, organization, country):
        payload = {"email" : email,
                   "name" : name,
                   "institution": organization,
                   "country": country}
        call = API_Call('/api/v1/user/{}'.format(quote_plus(email)), 'patch', payload, use_token=True)
        return call.get_resp()

    def get_execution(self, id=None, user=None):
        if id:
            call = API_Call('/api/v1/execution/{}'.format(quote_plus(id)), 'get', use_token=True)
        else:
            call = API_Call('/api/v1/execution', 'get', use_token=True)
        resp = call.get_resp()
        if not resp:
            return None
        else:
            data = resp['data']
            # Sort responses in descending order using start time by default
            data = sorted(data, key=lambda job: job['start_date'], reverse=True)
            # Convert start/end dates into datatime objects in local time zone
            for job in data:
                start_date = datetime.datetime.strptime(job['start_date'], '%Y-%m-%dT%H:%M:%S.%f')
                start_date = start_date.replace(tzinfo=tz.tzutc())
                start_date = start_date.astimezone(tz.tzlocal())
                job['start_date'] = start_date
                end_date = datetime.datetime.strptime(job['end_date'], '%Y-%m-%dT%H:%M:%S.%f')
                end_date = end_date.replace(tzinfo=tz.tzutc())
                end_date = end_date.astimezone(tz.tzlocal())
                job['end_date'] = end_date
            if user:
                log('Username is {}'.format(user))
                user_id = self.get_user(user)['id']
                return [x for x in data if x['user_id'] == user_id]
            else:
                return []

    def get_script(self, id=None):
        if id:
            call = API_Call('/api/v1/script/{}'.format(quote_plus(id)), 'get', use_token=True)
        else:
            call = API_Call('/api/v1/script', 'get', use_token=True)
        return call.get_resp()['data']
