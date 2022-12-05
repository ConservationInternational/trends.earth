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

import unittest

from multiprocessing import Process

from mock.mock_http_server import MockApiServer

from LDMP.api import APIClient
from LDMP.jobs.manager import job_manager
from LDMP.auth import init_auth_config, AuthSetup

from qgis.core import QgsApplication, QgsAuthMethodConfig

from qgis.PyQt import QtCore

from functools import partial


class CalculateLDNOneStep(unittest.TestCase):

    def setUp(self):
        self.app_server = MockApiServer()

        self.server = Process(target=self.app_server.run)
        self.server.start()

        self.api_client = APIClient(self.app_server.url, 30)
        self.response = None
        self.error = None

        print("Start of setting up auth method")

        auth_setup = AuthSetup(name="Trends.Earth")
        # self.auth_id = init_auth_config(auth_setup, 'test', 'test')
        currentAuthConfig = QgsAuthMethodConfig()
        currentAuthConfig.setName(auth_setup.name)

        print("Setting up auth method")

        # reset it's config values to set later new password when received

        currentAuthConfig.setMethod("Basic")
        currentAuthConfig.setConfig("username", 'test')
        currentAuthConfig.setConfig("password", 'testpass')

        res = QgsApplication.authManager().storeAuthenticationConfig(
            currentAuthConfig
        )
        # if res:
        #     print("Successfully added auth config")
        #
        # QtCore.QSettings().setValue(
        #     f"trends_earth/{auth_setup.key}", currentAuthConfig.id()
        # )

        self.auth_id = currentAuthConfig.id()

    def test_job_submission(self):
        ldn_one_step_id = 'bdad3786-bc36-46aa-8e3d-d6cede915cef'
        ldn_one_step_script_id = '47b99c3d-f5b5-4df3-81e7-324a17a6e147'

        job_manager.api_client = self.api_client
        job_dict = {
            'task_notes': 'Test'
        }
        print(self.api_client.url)
        print(f"/api/v1/script/{ldn_one_step_script_id}/run")

        response = job_manager.submit_remote_job(job_dict, ldn_one_step_script_id)

        self.assertIsNotNone(response)
        self.assertIsNotNone(response['data'])

    def tearDown(self):
        self.server.terminate()
        self.server.join()


if __name__ == "__main__":
    unittest.main()
