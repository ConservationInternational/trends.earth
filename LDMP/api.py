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

import requests

from urllib import quote_plus

from PyQt4.QtCore import QSettings

class APIError(Exception):
     def __init__(self, message):
        self.message = message

class APIInvalidCredentials(APIError):
    pass

class APIUserAlreadyExists(APIError):
    pass

class APICredentialsUndefined(APIError):
    pass

class APIUserNotFound(APIError):
    pass

API_URL = 'http://api.resilienceatlas.org'

class API:
    def __init__(self):
        self.settings = QSettings()

    def _call_api(self, endpoint, action='get', payload={}):
        # Flag to retry if token is needed
        TOKEN_TRIES = 0
        while TOKEN_TRIES <= 1:
            try:
                if action == 'get':
                    resp = requests.get(API_URL + endpoint, payload)
                elif action == 'post':
                    resp = requests.post(API_URL + endpoint, payload)
                elif action == 'update':
                    resp = requests.update(API_URL + endpoint, payload)
                elif action == 'delete':
                    resp = requests.delete(API_URL + endpoint, payload)
                else:
                    raise ValueError("Unrecognized action: {}".format(action))
            except requests.ConnectionError:
                raise APIError('Error connecting to LDMP server. Check your internet connection.')
                break
            except:
                # If there was a failure and there is a token necessary for 
                # this call, try to refresh the token once.
                if TOKEN_TRIES < 1 & payload.has_key('token'):
                    self.login()
                    payload['token'] = self.settings.value("LDMP/token", None)
            TOKEN_TRIES += 1
        if resp.status_code == 500:
            raise APIError('Error connecting to LDMP server.')

        return resp

    def login(self, email=None, password=None):
        if (email == None): email = self.settings.value("LDMP/email", None)
        if (password == None): password = self.settings.value("LDMP/password", None)
        if not email or not password:
            raise APICredentialsUndefined('Enter a valid username and password for the LDMP server.')
        try:
            resp = requests.post(API_URL + '/auth',
                    json={"email" : email, "password" : password})
        except requests.ConnectionError:
            raise APIError('Error connecting to LDMP server. Check your internet connection.')
        if resp.status_code == 200:
            self.settings.setValue("LDMP/email", email)
            self.settings.setValue("LDMP/password", password)
            self.settings.setValue("LDMP/token", resp.json()['access_token'])
        elif resp.status_code == 401:
            raise APIInvalidCredentials('Invalid username or password.')

    def recover_pwd(self, email):
        resp = self._call_api('/api/v1/user/{}/recover-password'.format(email), 'post')
        if resp.status_code == 200:
            return
        elif resp.status_code == 404:
            raise APIUserNotFound('Invalid username.')

    def get_user(self, email):
        resp = self._call_api('/api/v1/user/{}'.format(quote_plus(email)), 'get', {'token': self.settings.value("LDMP/token", None)})
        
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 401:
            raise APIError('Invalid token.')
        elif resp.status_code == 404:
            raise APIUserNotFound('Invalid username.')

    def register(self, email, name, organization, country):
        payload = {"email" : email, "name" : name, "institution": institution, "country": country}
        resp = self._call_api('/auth', 'post', payload)
        if resp.status_code == 200:
            self.settings.setValue("LDMP/email", email)
        if resp.status_code == 400:
            raise APIUserAlreadyExists('User already exists')

    def calculate(self, script, params):
        resp = self._call_api('/api/v1/script/{}/run'.format(script), 'get', params)
        if resp.status_code == 200:
            return(resp.json()['data']['id'])
        if resp.status_code == 400:
            raise APIScriptStateNotValid
        if resp.status_code == 404:
            raise APIScriptNotFound
