from qgis.testing import unittest

import sys
from queue import Queue
from time import sleep

from LDMP.test.unit.test_dialog_settings import SettingsUnitSuite
from LDMP.test.unit.test_calculate_ldn import CalculateLDNUnitSuite
from LDMP.test.integration.test_calculate_ldn import CalculateLDNIntegrationSuite
from LDMP.test.integration.test_calculate_urban import CalculateUrbanIntegrationSuite


def unitTests():
    suite = unittest.TestSuite()
    suite.addTest(SettingsUnitSuite())
    suite.addTest(CalculateLDNUnitSuite())
    return suite


def integrationTests():
    suite = unittest.TestSuite()
    suite.addTest(CalculateLDNIntegrationSuite())
    suite.addTest(CalculateUrbanIntegrationSuite())
    return suite


def run_all():
    unittest.TextTestRunner(verbosity=3, stream=sys.stdout).run(unitTests())
    unittest.TextTestRunner(verbosity=3, stream=sys.stdout).run(integrationTests())
    # while True:
    #     if not gee_task_queue.empty():
    #         # update status of all items in the queue
    #         # process the next available task if it is ready
    #         gee_task_queue.update_status()
    #         task = gee_task_queue.get()
    #         while task:
    #             if task:
    #                 unittest.TextTestRunner(verbosity=3, stream=sys.stdout).run(unittest.makeSuite(gee_task_queue.get()[1]))
    #     else:
    #         break
    #     print('Waiting for completion of GEE tasks')
    #     sleep(10)
