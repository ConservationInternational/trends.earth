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

import os
import sys
import json
import requests
import time
import pprint
from getpass import getpass


import numpy as np

import unittest

api_url = "https://api.trends.earth"

class api_Tests(unittest.TestCase):

    mail = None
    password = None
    token = None

    @classmethod
    def setUpClass(cls):
        # login and get bearer token
        # email, password = input('Email: '), getpass('Password: ')

        cls.email = "luipir@gmail.com"
        cls.password = 'XE70I2'
        creds = { "email" : cls.email, "password" : cls.password }
        auth_url = api_url + "/auth"

        auth_resp = requests.post(auth_url, json=creds)
        if auth_resp.status_code == 200:
            print("Logged in as {}.".format(cls.email))
            cls.token = auth_resp.json()['access_token']
        else:
            print("Error logging in. Sever returned {}.".format(auth_resp.status_code))

        return super().setUpClass()

    def setUp(self):
        pass

    def tearDown(self):
        pass

    @unittest.skip("demonstrating skipping")
    def testGetUserMe(self):
        start_time = time.time()
        # params = {'user': 'azvoleff@gmail.com',
        #         'lang': 'en',
        #         "year_start": 2001,
        #         "year_end": 2019,
        #         "geojson": "{\"coordinates\": [36.43006246, -0.71011347], \"type\": \"Point\"}",
        #         }
        resp_run = requests.get(api_url + '/api/v1/user/me',
                                json=None,
                                headers={'Authorization' : 'Bearer {}'.format(self.token)})
        print('Submission took {} seconds'.format(time.time() - start_time))
        self.assertEqual(resp_run.status_code, 200)
        data = resp_run.json()
        # print(data)
        self.assertEqual(data['data']['email'], self.email)

    def testExecutions(self):
        start_time = time.time()
        # params = {'user': 'azvoleff@gmail.com',
        #         'lang': 'en',
        #         "year_start": 2001,
        #         "year_end": 2019,
        #         "geojson": "{\"coordinates\": [36.43006246, -0.71011347], \"type\": \"Point\"}",
        #         }
        resp_run = requests.get(api_url + '/api/v1/execution',
                                json=None,
                                headers={'Authorization' : 'Bearer {}'.format(self.token)})
        print('Submission took {} seconds'.format(time.time() - start_time))
        self.assertEqual(resp_run.status_code, 200)
        data = resp_run.json()
        print(json.dumps(data, indent=4))
        # self.assertEqual(data['data']['email'], self.email)

def apitTestsSuite():
    print('runallaaa')
    suite = unittest.TestSuite()
    suite.addTests(unittest.makeSuite(api_Tests, 'test'))
    return suite


def run_all():
    _suite = unittest.TestSuite()
    _suite.addTest(apitTestsSuite())
    unittest.TextTestRunner(verbosity=3, stream=sys.stdout).run(_suite)

if __name__ == '__main__':
    run_all()
