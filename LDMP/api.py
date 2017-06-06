import requests

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

class APIUserNotFound(APIError):
    pass

API_URL = 'http://api.resilienceatlas.org'

class API:
    def __init__(self):
        self.settings = QSettings()

        self.token = None

        email = self.settings.value("LDMP/email", None) 
        password = self.settings.value("LDMP/password", None)

        if email and password:
            try:
                self.login(email, password)
            except APIInvalidCredentials:
                # Silently ignore failed logins when first loading the class 
                # (in case bad username and password are stored in QSettings)
                pass

    def login(self, email=None, password=None):
        creds = {"email" : email, "password" : password}
        resp = requests.post(API_URL + '/auth', json=creds)
        if resp.status_code == 200:
            self.user = resp.json()
            self.token = resp.json()['access_token']
            self.settings.setValue("LDMP/email", email)
            self.settings.setValue("LDMP/password", password)
        elif resp.status_code == 401:
            raise APIInvalidCredentials('Invalid username or password.')
        else:
            raise APIError('Error connecting to LDMP server.')

    def recover_pwd(self, email):
        resp = requests.post(API_URL + '/api/v1/user/{}/recover-password'.format(email))
        if resp.status_code == 200:
            return
        elif resp.status_code == 404:
            raise APIUserNotFound('Invalid username.')
        else:
            raise APIError('Error connecting to LDMP server.')

    def password_update(self, email, password):
        creds = {"email" : email, "password" : password}
        resp = requests.get(API_URL + '/api/v1/user', json=creds)
        resp.json(self, )
