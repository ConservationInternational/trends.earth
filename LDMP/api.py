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

    def _call_api(self, endpoint, method='get', payload={}, use_token=False):
        # Flag to retry if token is needed
        if use_token:
            TOKEN_TRIES = 0
            while TOKEN_TRIES <= 1:
                token = self.settings.value("LDMP/token", None)
                try:
                    if method == 'get':
                        resp = requests.get(API_URL + endpoint, json=payload, headers={'Authorization': 'Bearer %s'%token})
                    elif method == 'post':
                        resp = requests.post(API_URL + endpoint, json=payload, headers={'Authorization': 'Bearer %s'%token})
                    elif method == 'update':
                        resp = requests.update(API_URL + endpoint, json=payload, headers={'Authorization': 'Bearer %s'%token})
                    elif method == 'delete':
                        resp = requests.delete(API_URL + endpoint, json=payload, headers={'Authorization': 'Bearer %s'%token})
                    elif method == 'patch':
                        resp = requests.patch(API_URL + endpoint, json=payload, headers={'Authorization': 'Bearer %s'%token})
                    else:
                        raise ValueError("Unrecognized method: {}".format(method))
                except requests.ConnectionError:
                    raise APIError('Error connecting to LDMP server. Check your internet connection.')
                if resp.status_code == 401:
                    self.login()
                TOKEN_TRIES += 1
        else:
            try:
                if method == 'get':
                    resp = requests.get(API_URL + endpoint, json=payload)
                elif method == 'post':
                    resp = requests.post(API_URL + endpoint, json=payload)
                elif method == 'update':
                    resp = requests.update(API_URL + endpoint, json=payload)
                elif method == 'delete':
                    resp = requests.delete(API_URL + endpoint, json=payload)
                elif method == 'patch':
                    resp = requests.patch(API_URL + endpoint, json=payload)
                else:
                    raise ValueError("Unrecognized method: {}".format(method))
            except requests.ConnectionError:
                raise APIError('Error connecting to LDMP server. Check your internet connection.')
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
            self.settings.setValue("LDMP/user_id", self.get_user(email)['id'])
        elif resp.status_code == 401:
            raise APIInvalidCredentials('Invalid username or password.')
        else:
            raise APIError('Error connecting to LDMP server. Check your internet connection.')

    def recover_pwd(self, email):
        resp = self._call_api('/api/v1/user/{}/recover-password'.format(email), 'post')
        if resp.status_code == 200:
            return
        elif resp.status_code == 404:
            raise APIUserNotFound('Invalid username.')

    def get_user(self, email):
        resp = self._call_api('/api/v1/user/{}'.format(quote_plus(email)), 'get', use_token=True)
        if resp.status_code == 200:
            return resp.json()['data']
        elif resp.status_code == 401:
            raise APIError('Invalid token.')
        elif resp.status_code == 404:
            raise APIUserNotFound('Invalid username.')
        else:
            raise APIError('Error connecting to LDMP server. Check your internet connection.')

    def register(self, email, name, organization, country):
        payload = {"email" : email,
                   "name" : name,
                   "institution": organization,
                   "country": country}
        resp = self._call_api('/auth', 'post', payload)
        if resp.status_code == 200:
            self.settings.setValue("LDMP/email", email)
        if resp.status_code == 400:
            raise APIUserAlreadyExists('User already exists')

    def calculate(self, script, params={}):
        resp = self._call_api('/api/v1/script/{}/run'.format(quote_plus(script)),
                'post', params, use_token=True)
        if resp.status_code == 200:
            return
        elif resp.status_code == 400:
            raise APIScriptStateNotValid
        elif resp.status_code == 404:
            raise APIScriptNotFound
        else:
            raise APIError('Error connecting to LDMP server. Check your internet connection.')

    def update_user(self, email, name, organization, country):
        payload = {"email" : email,
                   "name" : name,
                   "institution": organization,
                   "country": country}
        resp = self._call_api('/api/v1/user/{}'.format(quote_plus(email)), 'patch', payload, use_token=True)
        if resp.status_code == 200:
            return
        elif resp.status_code == 400:
            raise APIScriptStateNotValid
        elif resp.status_code == 404:
            raise APIScriptNotFound
        else:
            raise APIError('Error connecting to LDMP server. Check your internet connection.')

    def get_execution(self, id=None, user=None):
        if id:
            resp = self._call_api('/api/v1/execution/{}'.format(quote_plus(id)), 'get', use_token=True)
        else:
            resp = self._call_api('/api/v1/execution', 'get', use_token=True)
        if resp.status_code == 200:
            if user:
                return [x for x in resp.json()['data'] if x['user_id'] == user]
            else:
                return resp.json()['data']
        elif resp.status_code == 400:
            raise APIScriptStateNotValid
        elif resp.status_code == 404:
            raise APIScriptNotFound
        else:
            raise APIError('Error connecting to LDMP server. Check your internet connection.')
