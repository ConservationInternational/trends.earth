import unittest
import sys

from LDMP.test.test_dialog_settings import SettingSuite

def unitTests():
    _tests = []
    _tests.extend(SettingSuite())
    return _tests

def run_all():
    unittest.TextTestRunner(verbosity=3, stream=sys.stdout).run(SettingSuite())
