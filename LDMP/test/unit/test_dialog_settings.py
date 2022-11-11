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
import sys

from qgis.core import *
from qgis.PyQt.QtCore import *
from qgis.PyQt.QtTest import QTest
from qgis.testing import unittest

from LDMP.settings import DlgSettingsLogin
from LDMP.test import regular_keys


class DialogSettingsLoginTests(unittest.TestCase):
    def testLoginValid(self):
        # TODO: pass if there is no internet
        # Test valid login
        d = DlgSettingsLogin()
        d.email.setText(regular_keys["email"])
        d.password.setText(regular_keys["password"])
        self.assertEqual(regular_keys["email"], d.email.text())
        self.assertEqual(regular_keys["password"], d.password.text())
        okWidget = d.buttonBox.button(d.buttonBox.Ok)
        QTest.mouseClick(okWidget, Qt.LeftButton)
        self.assertTrue(d.ok)

    def testLoginNoEmail(self):
        # Test login without email
        d = DlgSettingsLogin()
        d.email.setText("")
        d.password.setText(regular_keys["password"])
        okWidget = d.buttonBox.button(d.buttonBox.Ok)
        QTest.mouseClick(okWidget, Qt.LeftButton)
        self.assertFalse(d.ok)

    def testLoginNoPassword(self):
        # Test login without password
        d = DlgSettingsLogin()
        d.email.setText(regular_keys["email"])
        d.password.setText("")
        okWidget = d.buttonBox.button(d.buttonBox.Ok)
        QTest.mouseClick(okWidget, Qt.LeftButton)
        self.assertFalse(d.ok)

    def testLoginNoPasswordNoEmail(self):
        # Test login without email and without password
        d = DlgSettingsLogin()
        d.email.setText("")
        d.password.setText("")
        okWidget = d.buttonBox.button(d.buttonBox.Ok)
        QTest.mouseClick(okWidget, Qt.LeftButton)
        self.assertFalse(d.ok)


def SettingsUnitSuite():
    suite = unittest.TestSuite()
    suite.addTests(
        unittest.defaultTestLoader.loadTestsFromTestCase(
            DialogSettingsLoginTests, "test"
        )
    )
    return suite


def run_all():
    _suite = unittest.TestSuite()
    _suite.addTest(SettingsUnitSuite())
    unittest.TextTestRunner(verbosity=3, stream=sys.stdout).run(_suite)
