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

from urllib import quote_plus

from PyQt4.QtCore import QSettings

from qgis.utils import iface
mb = iface.messageBar()

from qgis.core import QgsMessageLog

API_URL = 'http://api.resilienceatlas.org'

class API:
    def __init__(self):
        self.settings = QSettings()

    def _call_api(self, endpoint, method='get', payload={}, use_token=False):
        if use_token:
            resp = self.login()
            if resp:
                headers = {'Authorization': 'Bearer %s'%resp.json()['access_token']}
            else: 
                return False
        else:
            headers = {}

        QgsMessageLog.logMessage("API _call_api loaded token.", tag="LDMP", level=QgsMessageLog.INFO)
        # Strip password out of payload
        clean_payload = payload.copy()
        if clean_payload.has_key('password'):
            clean_payload['password'] = '**REMOVED**'
        QgsMessageLog.logMessage("API _call_api calling {} with payload: {}".format(endpoint, clean_payload), tag="LDMP", level=QgsMessageLog.INFO)

        try:
            if method == 'get':
                resp = requests.get(API_URL + endpoint, json=payload, headers=headers)
            elif method == 'post':
                resp = requests.post(API_URL + endpoint, json=payload, headers=headers)
            elif method == 'update':
                resp = requests.update(API_URL + endpoint, json=payload, headers=headers)
            elif method == 'delete':
                resp = requests.delete(API_URL + endpoint, json=payload, headers=headers)
            elif method == 'patch':
                resp = requests.patch(API_URL + endpoint, json=payload, headers=headers)
            else:
                raise ValueError("Unrecognized method: {}".format(method))
        except requests.ConnectionError:
            mb.pushMessage("Error", "Unable to connect to LDMP server.", level=1, duration=5)
            return False

        QgsMessageLog.logMessage("API _call_api response: {}".format(resp.text), tag="LDMP", level=QgsMessageLog.INFO)

        if resp.status_code == 500:
            mb.pushMessage("Error", "Unable to connect to LDMP server.", level=1, duration=5)
            return False

        return resp

    def login(self, email=None, password=None):
        if (email == None): email = self.settings.value("LDMP/email", None)
        if (password == None): password = self.settings.value("LDMP/password", None)
        if not email or not password:
            mb.pushMessage("Error", "Unable to login to LDMP server. Check your username and password.", level=1, duration=5)
            return False
        resp = self._call_api('/auth', 'post', payload={"email" : email, "password" : password})
        if resp.status_code == 200:
            self.settings.setValue("LDMP/email", email)
            self.settings.setValue("LDMP/password", password)
            return resp
        elif resp.status_code == 401:
            mb.pushMessage("Error", "Unable to login to LDMP server. Check your username and password.", level=1, duration=5)
        else:
            mb.pushMessage("Error", "Unable to connect to LDMP server.", level=1, duration=5)
        return False

    def recover_pwd(self, email):
        resp = self._call_api('/api/v1/user/{}/recover-password'.format(email), 'post')
        if not resp:
            return False
        elif resp.status_code == 200:
            return resp
        elif resp.status_code == 404:
            mb.pushMessage("Error", "{} is not a registered user.".format(email), level=1, duration=5)
        else:
            mb.pushMessage("Error", "Unable to connect to LDMP server.", level=1, duration=5)
        return False

    def get_user(self, email):
        resp = self._call_api('/api/v1/user/{}'.format(quote_plus(email)), 'get', use_token=True)
        if not resp:
            return False
        elif resp.status_code == 200:
            return resp.json()['data']
        elif resp.status_code == 404:
            mb.pushMessage("Error", "Unable to login to LDMP server. Check your username and password.", level=1, duration=5)
        else:
            mb.pushMessage("Error", "Unable to connect to LDMP server.", level=1, duration=5)
        return False

    def register(self, email, name, organization, country):
        payload = {"email" : email,
                   "name" : name,
                   "institution": organization,
                   "country": country}
        resp = self._call_api('/auth', 'post', payload)
        if not resp:
            return False
        elif resp.status_code == 200:
            self.settings.setValue("LDMP/email", email)
            return resp
        elif resp.status_code == 400:
            mb.pushMessage("Error", "User {} is already registered.".format(email), level=1, duration=5)
        else:
            mb.pushMessage("Error", "Unable to connect to LDMP server.", level=1, duration=5)
        return False

    def calculate(self, script, params={}):
        resp = self._call_api('/api/v1/script/{}/run'.format(quote_plus(script)),
                'post', params, use_token=True)
        if not resp:
            return False
        elif resp.status_code == 200:
            return resp
        elif resp.status_code == 400:
            mb.pushMessage("Error", "LDMP server error (script state not valid).".format(email), level=1, duration=5)
        elif resp.status_code == 404:
            mb.pushMessage("Error", "LDMP server error (script not found).".format(email), level=1, duration=5)
        else:
            mb.pushMessage("Error", "Unable to connect to LDMP server.", level=1, duration=5)
        return False

    def update_user(self, email, name, organization, country):
        payload = {"email" : email,
                   "name" : name,
                   "institution": organization,
                   "country": country}
        resp = self._call_api('/api/v1/user/{}'.format(quote_plus(email)), 'patch', payload, use_token=True)
        if not resp:
            return False
        if resp.status_code == 200:
            return resp
        else:
            mb.pushMessage("Error", "Unable to connect to LDMP server.", level=1, duration=5)
        return False

    def get_execution(self, id=None, user=None):
        if id:
            resp = self._call_api('/api/v1/execution/{}'.format(quote_plus(id)), 'get', use_token=True)
        else:
            resp = self._call_api('/api/v1/execution', 'get', use_token=True)
        if not resp:
            return False
        elif resp.status_code == 200:
            resp = resp.json()['data']
            # Sort responses in descending order using start time by default
            resp = sorted(resp, key=lambda job: job['start_date'], reverse=True)
            # Convert start/end dates into datatime objects in local time zone
            for job in resp:
                start_date = datetime.datetime.strptime(job['start_date'], '%Y-%m-%dT%H:%M:%S.%f')
                start_date = start_date.replace(tzinfo=tz.tzutc())
                start_date = start_date.astimezone(tz.tzlocal())
                job['start_date'] = start_date
                end_date = datetime.datetime.strptime(job['end_date'], '%Y-%m-%dT%H:%M:%S.%f')
                end_date = end_date.replace(tzinfo=tz.tzutc())
                end_date = end_date.astimezone(tz.tzlocal())
                job['end_date'] = end_date
            if user:
                user = self.get_user(self.settings.value("LDMP/email"))['id']
                return [x for x in resp if x['user_id'] == user]
            else:
                return []
        else:
            mb.pushMessage("Error", "Unable to connect to LDMP server.", level=1, duration=5)
        return False

    def get_script(self, id=None, user=None):
        if id:
            resp = self._call_api('/api/v1/script/{}'.format(quote_plus(id)), 'get', use_token=True)
        else:
            resp = self._call_api('/api/v1/script', 'get', use_token=True)
        if not resp:
            return False
        return resp.json()['data']
