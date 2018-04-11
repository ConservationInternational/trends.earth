import unittest
import sys

from LDMP.test.test_dialog_settings import SettingsSuite

def unitTests():
    _tests = []
    _tests.extend(SettingsSuite())
    return _tests

def run_all():
    unittest.TextTestRunner(verbosity=3, stream=sys.stdout).run(SettingsSuite())
