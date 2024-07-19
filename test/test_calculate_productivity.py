import unittest
from multiprocessing import Process

from mock.mock_http_server import MockApiServer
from qgis.core import QgsApplication
from qgis.core import QgsAuthMethodConfig
from qgis.PyQt import QtCore

from LDMP.api import APIClient
from LDMP.auth import AuthSetup
from LDMP.conf import KNOWN_SCRIPTS
from LDMP.jobs.manager import job_manager
from LDMP.jobs.models import Job


class CalculateProductivity(unittest.TestCase):
    def setUp(self):
        self.app_server = MockApiServer()

        self.server = Process(target=self.app_server.run)
        self.server.start()

        self.api_client = APIClient(self.app_server.url, 30)
        self.response = None
        self.error = None

    def set_auth_db(self):
        AUTHDB_MASTERPWD = "password"
        print("Init script: %s" % __file__)

        auth_manager = QgsApplication.authManager()
        if not auth_manager.masterPasswordHashInDatabase():
            auth_manager.setMasterPassword(AUTHDB_MASTERPWD, True)
            # Create config
            auth_manager.authenticationDatabasePath()
            auth_manager.masterPasswordIsSet()

        auth_setup = AuthSetup(name="Trends.Earth")

        cfg = QgsAuthMethodConfig()
        cfg.setName(auth_setup.name)
        cfg.setMethod("Basic")
        cfg.setConfig("username", "test")
        cfg.setConfig("password", "test")
        auth_manager.storeAuthenticationConfig(cfg)

        QtCore.QSettings().setValue(f"trends_earth/{auth_setup.key}", cfg.id())

        return cfg.id()

    def test_job_submission(self):
        productivity_script_name = "productivity"

        script = [
            s for s in KNOWN_SCRIPTS.values() if s.name == productivity_script_name
        ][0]

        self.auth_id = self.set_auth_db()

        job_manager.api_client = self.api_client
        job_dict = {"task_notes": "Test"}

        response = job_manager.submit_remote_job(job_dict, script.id)

        self.assertIsNotNone(response)
        if isinstance(response, Job):
            self.assertIsNotNone(response.get_display_name())
        else:
            self.assertIsNotNone(response["data"])

    def tearDown(self):
        self.server.terminate()
        self.server.join()


if __name__ == "__main__":
    unittest.main()
