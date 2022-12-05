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


class CalculateLDNOneStep(unittest.TestCase):

    def setup(self):
        self.app_server = MockApiServer()

        self.server = Process(target=self.app_server.run)
        self.server.start()

        self.api_client = APIClient(self.app_server.url, 30)
        self.response = None
        self.error = None

    def submit_job(self):
        ldn_one_step_id = 'bdad3786-bc36-46aa-8e3d-d6cede915cef'
        ldn_one_step_script_id = '47b99c3d-f5b5-4df3-81e7-324a17a6e147'

        job_manager.api_client = self.api_client

        response = job_manager.submit_remote_job({}, ldn_one_step_script_id)

        assert response['data']

    def tearDown(self):
        self.server.terminate()
        self.server.join()


if __name__ == "__main__":
    unittest.main()
