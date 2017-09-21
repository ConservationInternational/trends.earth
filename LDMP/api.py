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
mb = iface.messageBar()

from . import log

API_URL = 'http://api.resilienceatlas.org'
TIMEOUT=20

def get_user_email(warn=True):
    email = QtCore.QSettings().value("LDMP/email", None)
    if warn and email is None:
        QtGui.QMessageBox.critical(None, "Error", "Please register with the Land Degradation Monitoring Toolbox before using this function.")
        return None
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
	# TODO: this creates a problem when it is called from within a thread
        mb.pushMessage("Error", "Unable to login to LDMP server. Check your username and password.", level=1, duration=5)
        return False

    log('API trying login for user {}'.format(email))
    try:
        resp = requests.post(API_URL + '/auth', json={"email" : email, "password" : password}, timeout=TIMEOUT)
        log('API response to login for user {}: {}'.format(email, clean_api_response(resp)))
    except requests.ConnectionError:
        mb.pushMessage("Error", "Unable to login to LDMP server. Check your internet connection.", level=1, duration=5)
        return False

    if resp.status_code == 200:
        QtCore.QSettings().setValue("LDMP/email", email)
        QtCore.QSettings().setValue("LDMP/password", password)
        return resp
    else:
        desc, status = get_error_status(resp)
        mb.pushMessage("Error: {} (status {}).".format(desc, status),
                level=1, duration=5)
        return False

class API_Call_Worker(QtCore.QObject):
    """Run earth engine task against the ldmp API"""
    def __init__(self, endpoint, method='get', payload={}, use_token=False):
        QtCore.QObject.__init__(self)
        self.endpoint = endpoint
        self.method = method
        self.payload = payload
        self.use_token = use_token

    def run(self):
        if self.use_token:
            try:
                resp = login()
                headers = {'Authorization': 'Bearer %s'%resp.json()['access_token']}
                log("API loaded token.")
            except:
                resp = None
        else:
            headers = {}

        # Only continue if don't need token or if token load was successful
        if (not self.use_token) or (resp):
            # Strip password out of payload for printing to QGIS logs
            clean_payload = self.payload.copy()
            if clean_payload.has_key('password'):
                clean_payload['password'] = '**REMOVED**'
            log('API calling {} with method "{}" and payload: {}'.format(self.endpoint, self.method, clean_payload))
            try:
                if self.method == 'get':
                    resp = requests.get(API_URL + self.endpoint, json=self.payload, headers=headers, timeout=TIMEOUT)
                elif self.method == 'post':
                    resp = requests.post(API_URL + self.endpoint, json=self.payload, headers=headers, timeout=TIMEOUT)
                elif self.method == 'update':
                    resp = requests.update(API_URL + self.endpoint, json=self.payload, headers=headers, timeout=TIMEOUT)
                elif self.method == 'delete':
                    resp = requests.delete(API_URL + self.endpoint, json=self.payload, headers=headers, timeout=TIMEOUT)
                elif self.method == 'patch':
                    resp = requests.patch(API_URL + self.endpoint, json=self.payload, headers=headers, timeout=TIMEOUT)
                else:
                    raise ValueError("Unrecognized method: {}".format(self.method))
                log('API response from "{}" request: {}'.format(self.method, clean_api_response(resp)))
            except Exception, e:
                resp = None
                log('API error: {}'.format(e))
                # forward the exception upstream
                self.error.emit(e, sys.exc_info())
        self.finished.emit(resp)

    finished = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(Exception, basestring)
    progress = QtCore.pyqtSignal(float)

class API_Call(QtCore.QObject):
    def __init__(self, endpoint, method, payload, use_token):
        QtCore.QObject.__init__(self)
        self.settings = QtCore.QSettings()

        self.endpoint = endpoint
        self.method = method
        self.payload = payload
        self.use_token = use_token

    def startWorker(self):
        worker = API_Call_Worker(self.endpoint, self.method, self.payload, self.use_token)
	messageBar = iface.messageBar().createMessage('Contacting LDMP server...')
	progressBar = QtGui.QProgressBar()
	progressBar.setAlignment(QtCore.Qt.AlignLeft|QtCore.Qt.AlignVCenter)
	messageBar.layout().addWidget(progressBar)
	iface.messageBar().pushWidget(messageBar, iface.messageBar().INFO)
	self.messageBar = messageBar

        # start the worker in a new thread
        thread = QtCore.QThread(self)
        worker.moveToThread(thread)
        worker.finished.connect(self.workerFinished)
        worker.error.connect(self.workerError)
        worker.progress.connect(progressBar.setValue)
        thread.started.connect(worker.run)
        thread.start()
        self.thread = thread
        self.worker = worker
        self.worker_finished = False

    def workerFinished(self, ret):
	# clean up the worker and thread
	self.worker.deleteLater()
	self.thread.quit()
	self.thread.wait()
	self.thread.deleteLater()
	# remove widget from message bar
	iface.messageBar().popWidget(self.messageBar)
        self.worker_finished = True
        if ret == None:
            self.resp = None
        elif ret.status_code == 200:
            self.resp = ret.json()
        else:
            desc, status = get_error_status(ret)
            mb.pushMessage("Error: {} (status {}).".format(desc, status), 
                    level=1, duration=5)
            self.resp = None
        self.finished.emit()

    def workerError(self, e, exception_string):
        if e == requests.ConnectionError:
            mb.pushMessage("Error", "Unable to connect to LDMP server.", level=1, duration=5)
        elif e == requests.exceptions.Timeout:
            mb.pushMessage("Error", "Timed out attempting to connect to LDMP server.", level=1, duration=5)
        else:
            log('Worker thread raised an exception:\n'.format(exception_string), level=2)

    finished = QtCore.pyqtSignal()

################################################################################
# Main function that makes an api call, first instantiating an API_Call 
# instance and then starting it.
def call_api(endpoint, method='get', payload={}, use_token=False):
    api_call = API_Call(endpoint, method, payload, use_token)
    pause = QtCore.QEventLoop()
    api_call.finished.connect(pause.quit)
    api_call.startWorker()
    pause.exec_()
    return api_call

################################################################################
# Functions supporting access to individual api endpoints
def recover_pwd(email):
    api_call = call_api('/api/v1/user/{}/recover-password'.format(quote_plus(email)), 'post')
    return api_call.resp

def get_user(email):
    api_call = call_api('/api/v1/user/{}'.format(quote_plus(email)), use_token=True)
    return api_call.resp['data']

def register(email, name, organization, country):
    payload = {"email" : email,
               "name" : name,
               "institution": organization,
               "country": country}
    api_call = call_api('/api/v1/user', method='post', payload=payload)
    return api_call.resp

def calculate(script, params={}):
    # TODO: check before submission whether this payload and script ID has 
    # been sent recently - or even whether there are results already 
    # available for it. Notify the user if this is the case to prevent, or 
    # at least reduce, repeated identical submissions.
    api_call = call_api('/api/v1/script/{}/run'.format(quote_plus(script)), 'post', params, use_token=True)
    return api_call.resp

def update_user(email, name, organization, country):
    payload = {"email" : email,
               "name" : name,
               "institution": organization,
               "country": country}
    api_call = call_api('/api/v1/user/{}'.format(quote_plus(email)), 'patch', payload, use_token=True)
    return api_call.resp

def get_execution(id=None, user=None):
    if id:
        api_call = call_api('/api/v1/execution/{}'.format(quote_plus(id)), 'get', use_token=True)
    else:
        api_call = call_api('/api/v1/execution', 'get', use_token=True)
    resp = api_call.resp
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

def get_script(id=None):
    if id:
        api_call = call_api('/api/v1/script/{}'.format(quote_plus(id)), 'get', use_token=True)
    else:
        api_call = call_api('/api/v1/script', 'get', use_token=True)
    return api_call.resp['data']
