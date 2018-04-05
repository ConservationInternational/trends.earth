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
from PyQt4.QtGui import QMessageBox, QApplication
from PyQt4.QtCore import *
from PyQt4.QtTest import QTest

from LDMP.settings import DlgSettingsLogin

from LDMP.test import regular_keys, admin_keys


# Ensure any message boxes that open are closed within 5 seconds
def close_msg_boxes():
    for w in QApplication.topLevelWidgets():
        if isinstance(w, QMessageBox):
            print('Closing message box')
            QTest.keyClick(w, Qt.Key_Enter)
timer = QTimer()
timer.timeout.connect(close_msg_boxes)
timer.start(5000)

class DialogSettingsLoginTests(unittest.TestCase):
    def testLogin(self):
        dialog = DlgSettingsLogin()
        dialog.email.setText(regular_keys['email'])
        dialog.password.setText(regular_keys['password'])
        self.assertEquals(regular_keys['email'], dialog.email.text())
        self.assertEquals(regular_keys['password'], dialog.password.text())
        print('Testing valid login')
        okWidget = dialog.buttonBox.button(dialog.buttonBox.Ok)
        QTest.mouseClick(okWidget, Qt.LeftButton)
        self.assertTrue(dialog.ok)

        ret = dialog.login()
        self.assertTrue(ret)
        close_msg_boxes()

        # Test login without email
        print('Testing login without email')
        dialog.email.setText('')
        dialog.password.setText(regular_keys['password'])
        ret = dialog.login()
        self.assertFalse(ret)
        close_msg_boxes()

        # Test login without password
        print('Testing login without password')
        dialog.email.setText(regular_keys['email'])
        dialog.password.setText('')
        ret = dialog.login()
        self.assertFalse(ret)
        close_msg_boxes()

        # Test login without email and without password
        print('Testing login without email and without password')
        dialog.email.setText('')
        dialog.password.setText('')
        ret = dialog.login()
        self.assertFalse(ret)
        close_msg_boxes()

def suite():
    suite = unittest.TestSuite()
    suite.addTests(unittest.makeSuite(DialogSettingsLoginTests, 'test'))
    return suite

def run_all():
    unittest.TextTestRunner(verbosity=3, stream=sys.stdout).run(suite())
