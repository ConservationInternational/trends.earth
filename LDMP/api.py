import requests

from jwt import InvalidTokenError

from PyQt4.QtCore import QSettings

# DEBUG ONLY:
from PyQt4 import QtGui

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

        self.email = self.settings.value("LDMP/email", None) 
        self.password = self.settings.value("LDMP/password", None)
        self.token = self.settings.value("LDMP/token", None)

        if self.email and self.password:
            try:
                self.login(self.email, self.password)
            except APIInvalidCredentials:
                # Silently ignore failed logins when first loading the class 
                # (in case bad username and password are stored in QSettings)
                pass

    def _call_api(self, endpoint, action='get', payload={}):
        
        # Flag to retry if token is needed
        TOKEN_TRIES = 0
        while TOKEN_TRIES <= 1:
            try:
                if action == 'get':
                    resp = requests.get(API_URL + endpoint, json=payload)
                elif action == 'post':
                    resp = requests.post(API_URL + endpoint, json=payload)
                elif action == 'update':
                    resp = requests.update(API_URL + endpoint, json=payload)
                elif action == 'delete':
                    resp = requests.delete(API_URL + endpoint, json=payload)
                else:
                    raise ValueError("Unrecognized action: {}".format(action))
            except requests.ConnectionError:
                raise APIError('Error connecting to LDMP server.')
            except InvalidTokenError:
                self.login()
                TOKEN_TRIES += 1

        if resp.status_code == 500:
            raise APIError('Error connecting to LDMP server. Check your internet connection.')

        return resp

    def login(self, email=None, password=None):
        if (email == None): email = self.email
        if (password == None): password = self.password

        if not self.email or not self.password:
            raise APICredentialsUndefined('Enter a valid username and password for the LDMP server.')

        creds = {"email" : email, "password" : password}
        resp = self._call_api('/auth', 'post', creds)
        if resp.status_code == 200:
            self.email = email
            self.password = password
            self.token = resp.json()['access_token']
            self.settings.setValue("LDMP/email", email)
            self.settings.setValue("LDMP/password", password)
            self.settings.setValue("LDMP/token", self.token)
        elif resp.status_code == 401:
            raise APIInvalidCredentials('Invalid username or password.')

    def recover_pwd(self, email):
        resp = self._call_api('/api/v1/user/{}/recover-password'.format(email), 'post')
        if resp.status_code == 200:
            return
        elif resp.status_code == 404:
            raise APIUserNotFound('Invalid username.')

    def get_user(self, email):
        resp = self._call_api('/api/v1/user/{}'.format(email), 'get', {'token': self.token})
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 401:
            #TODO if this is raised then need to login again to refresh the token
            raise APIError('Invalid token.')
        elif resp.status_code == 404:
            raise APIUserNotFound('Invalid username.')

    def register(self, email, name, organization, country):
        payload = {"email" : email, "name" : name, "institution": institution, "country": country}
        resp = self._call_api('/auth', 'post', payload)
        if resp.status_code == 200:
            self.email = email
            self.settings.setValue("LDMP/email", email)
        if resp.status_code == 400:
            raise APIUserAlreadyExists('User already exists')
