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
import os

from qgis.core import *
from PyQt4.QtGui import QMessageBox
from PyQt4.QtCore import *
from PyQt4.QtTest import QTest

from LDMP.settings import DlgSettingsLogin

from LDMP.test import regular_keys, admin_keys


def close_msg_boxes():
    topWidgets = QApplication.topLevelWidgets();
    for w in topWidgets:
        if isinstance(w, QMessageBox):
            QTest.keyClick(w, Qt.Key_Enter)

class DialogSettingsLoginTests(unittest.TestCase):
    def testLogin(self):
        dialog = DlgSettingsLogin()
        dialog.email.setText(regular_keys['email'])
        dialog.password.setText(regular_keys['password'])
        self.assertEquals(regular_keys['email'], dialog.username)
        self.assertEquals(regular_keys['password'], dialog.password)
        okWidget = dialog.buttonBox.button(dialog.buttonBox.Ok)
        QTest.mouseClick(okWidget, Qt.LeftButton)
        self.assertTrue(dialog.ok)

        ret = dialog.login()
        self.assertTrue(ret)
        close_msg_boxes()

        dialog.email.setText('')
        dialog.password.setText(regular_keys['password'])
        ret = dialog.login()
        self.assertFalse(ret)
        close_msg_boxes()

        dialog.email.setText(regular_keys['email'])
        dialog.password.setText('')
        ret = dialog.login()
        self.assertFalse(ret)
        close_msg_boxes()

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
