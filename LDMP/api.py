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

import sys
import time
import datetime
from dateutil import tz
import requests
import json
from urllib import quote_plus

from PyQt4 import QtGui, QtCore

from qgis.utils import iface

from LDMP.worker import AbstractWorker, start_worker

from LDMP import log

API_URL = 'http://api.resilienceatlas.org'
TIMEOUT=20

def get_user_email(warn=True):
    email = QtCore.QSettings().value("LDMP/email", None)
    if warn and email is None:
        QtGui.QMessageBox.critical(None, "Error", "Please register with the Land Degradation Monitoring Toolbox before using this function.")
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
        else:
            raise ValueError("Unrecognized method: {}".format(method))
            resp = None
        return resp

class Request(object):
    def __init__(self, url, method='get', payload=None, headers={}):
        self.resp = None
        self.exception = None

        self.url = url
        self.method = method
        self.payload = payload
        self.headers = headers

    def start(self):
        try:
            worker = RequestWorker(self.url, self.method, self.payload, self.headers)
            pause = QtCore.QEventLoop()
            worker.finished.connect(pause.quit)
            worker.successfully_finished.connect(self.save_resp)
            worker.error.connect(self.save_exception)
            start_worker(worker, iface, 'Contacting LDMP server...')
            pause.exec_()
            if self.get_exception():
                raise self.get_exception()
        except requests.exceptions.ConnectionError:
            log('API unable to access server - check internet connection')
            QtGui.QMessageBox.critical(None, "Error", "Unable to login to LDMP server. Check your internet connection.")
            resp = None
        except requests.exceptions.Timeout:
            log('API unable to login - general error')
            QtGui.QMessageBox.critical(None, "Error", "Unable to connect to LDMP server.")
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
            if response.has_key('password'):
                response['password'] = '**REMOVED**'
            if response.has_key('access_token'):
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

def login(email=None, password=None):
    if (email == None):
        email = get_user_email()
    if (password == None):
        password = QtCore.QSettings().value("LDMP/password", None)
    if not email or not password:
        log('API unable to login - check username/password')
        QtGui.QMessageBox.critical(None, "Error", "Unable to login to LDMP server. Check your username and password.")
        resp = None

    resp = call_api('/auth', method='post', payload={"email" : email, "password" : password})

    if resp != None:
        QtCore.QSettings().setValue("LDMP/email", email)
        QtCore.QSettings().setValue("LDMP/password", password)

    return resp

def call_api(endpoint, method='get', payload=None, use_token=False):
    if use_token:
        login_resp = login()
        log("API loaded token.")
        headers = {'Authorization': 'Bearer {}'.format(login_resp['access_token'])}
    else:
        log("API no token required.")
        headers = {}

    # Only continue if don't need token or if token load was successful
    if (not use_token) or (login_resp):
        # Strip password out of payload for printing to QGIS logs
        if payload:
            clean_payload = payload.copy()
            if clean_payload.has_key('password'):
                clean_payload['password'] = '**REMOVED**'
        else:
            clean_payload = payload
        log('API calling {} with method "{}" and payload: {}'.format(endpoint, method, clean_payload))
        worker = Request(API_URL + endpoint, method, payload, headers)
        worker.start()
        resp = worker.get_resp()
        log('API response from "{}" request: {}'.format(method, clean_api_response(resp)))
    else:
        resp = None

    if resp != None:
        if resp.status_code == 200:
            ret = resp.json()
        else:
            desc, status = get_error_status(resp)
            QtGui.QMessageBox.critical(None, "Error", "Error: {} (status {}).".format(desc, status))
            ret = None
    else:
        ret = None

    return ret

################################################################################
# Functions supporting access to individual api endpoints
def recover_pwd(email):
    return call_api('/api/v1/user/{}/recover-password'.format(quote_plus(email)), 'post')

def get_user(email='me'):
    resp = call_api('/api/v1/user/{}'.format(quote_plus(email)), use_token=True)
    if resp:
        return resp['data']
    else:
        return None

def delete_user(email='me'):
    resp = call_api('/api/v1/user/{}'.format(quote_plus(email)), 'delete', use_token=True)
    if resp:
        return resp['data']
    else:
        return None

def register(email, name, organization, country):
    payload = {"email" : email,
               "name" : name,
               "institution": organization,
               "country": country}
    return call_api('/api/v1/user', method='post', payload=payload)

def run_script(script, params={}):
    # TODO: check before submission whether this payload and script ID has 
    # been sent recently - or even whether there are results already 
    # available for it. Notify the user if this is the case to prevent, or 
    # at least reduce, repeated identical submissions.
    return call_api('/api/v1/script/{}/run'.format(quote_plus(script)), 'post', params, use_token=True)

def update_user(email, name, organization, country):
    payload = {"email" : email,
               "name" : name,
               "institution": organization,
               "country": country}
    return call_api('/api/v1/user/{}'.format(quote_plus(email)), 'patch', payload, use_token=True)

def get_execution(id=None):
    log('Fetching executions')
    if id:
        resp = call_api('/api/v1/execution/{}'.format(quote_plus(id)), method='get', use_token=True)
    else:
        resp = call_api('/api/v1/execution', method='get', use_token=True)
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
        return data

def get_script(id=None):
    if id:
        resp = call_api('/api/v1/script/{}'.format(quote_plus(id)), 'get', use_token=True)
    else:
        resp = call_api('/api/v1/script', 'get', use_token=True)
    if resp:
        return resp['data']
    else:
        return None
