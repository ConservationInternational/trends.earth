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

import unittest
import sys

from qgis.core import *
from PyQt4.QtCore import *
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication

from LDMP.settings import DlgSettingsLogin

from LDMP.test import regular_keys, admin_keys


class DialogSettingsLoginTests(unittest.TestCase):
    def testLogin(self):
        # Test valid login
        d = DlgSettingsLogin()
        d.email.setText(regular_keys['email'])
        d.password.setText(regular_keys['password'])
        self.assertEquals(regular_keys['email'], d.email.text())
        self.assertEquals(regular_keys['password'], d.password.text())
        okWidget = d.buttonBox.button(d.buttonBox.Ok)
        QTest.mouseClick(okWidget, Qt.LeftButton)
        self.assertTrue(d.ok)

        # Test login without email
        d = DlgSettingsLogin()
        d.email.setText('')
        d.password.setText(regular_keys['password'])
        okWidget = d.buttonBox.button(d.buttonBox.Ok)
        QTest.mouseClick(okWidget, Qt.LeftButton)
        self.assertFalse(d.ok)

        # Test login without password
        d = DlgSettingsLogin()
        d.email.setText(regular_keys['email'])
        d.password.setText('')
        okWidget = d.buttonBox.button(d.buttonBox.Ok)
        QTest.mouseClick(okWidget, Qt.LeftButton)
        self.assertFalse(d.ok)

        # Test login without email and without password
        d = DlgSettingsLogin()
        d.email.setText('')
        d.password.setText('')
        okWidget = d.buttonBox.button(d.buttonBox.Ok)
        QTest.mouseClick(okWidget, Qt.LeftButton)
        self.assertFalse(d.ok)

def SettingsSuite():
    suite = unittest.TestSuite()
    suite.addTests(unittest.makeSuite(DialogSettingsLoginTests, 'test'))
    return suite
