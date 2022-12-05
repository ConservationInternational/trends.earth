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

from qgis.core import QgsApplication, QgsAuthManager, QgsAuthMethodConfig

from qgis.PyQt import QtCore

from LDMP.auth import get_auth_config, TE_API_AUTH_SETUP


class CalculateLDNOneStep(unittest.TestCase):

    def setUp(self):
        self.app_server = MockApiServer()

        self.server = Process(target=self.app_server.run)
        self.server.start()

        self.api_client = APIClient(self.app_server.url, 30)
        self.response = None
        self.error = None

    def set_auth_db(self):
        AUTHDB_MASTERPWD = 'password'

        print("Init script: %s" % __file__)

        # Check if authdb master password is set
        am = QgsApplication.authManager()
        if not am.masterPasswordHashInDatabase():
            # Set it!
            am.setMasterPassword(AUTHDB_MASTERPWD, True)
            # Create config
            am.authenticationDatabasePath()
            print("IF Master Password is set")
            masset = am.masterPasswordIsSet()
            print(masset)

        auth_setup = AuthSetup(name="Trends.Earth")

        cfg = QgsAuthMethodConfig()
        cfg.setName(auth_setup.name)
        cfg.setMethod('Basic')
        cfg.setConfig('username', 'test')
        cfg.setConfig('password', 'test')
        am.storeAuthenticationConfig(cfg)

        QtCore.QSettings().setValue(
            f"trends_earth/{auth_setup.key}", cfg.id()
        )

        return cfg.id()

    def test_job_submission(self):
        ldn_one_step_script_id = '47b99c3d-f5b5-4df3-81e7-324a17a6e147'

        self.auth_id = self.set_auth_db()

        job_manager.api_client = self.api_client
        job_dict = {
            'task_notes': 'Test'
        }

        response = job_manager.submit_remote_job(job_dict, ldn_one_step_script_id)

        self.assertIsNotNone(response)
        self.assertIsNotNone(response['data'])

    def tearDown(self):
        self.server.terminate()
        self.server.join()


if __name__ == "__main__":
    unittest.main()
