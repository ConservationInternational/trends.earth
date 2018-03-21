# -*- coding: utf-8 -*-
#
# (c) 2016 Boundless, http://boundlessgeo.com
# This code is licensed under the GPL 2.0 license.
#
import unittest
import sys
import os
from qgis.core import *
from PyQt4.QtGui import QMessageBox
from PyQt4.QtCore import *
from PyQt4.QtTest import QTest
from LDMP.settings import DlgSettingsLogin


def close_msg_boxes():
    topWidgets = QApplication.topLevelWidgets();
    for w in topWidgets:
        if isinstance(w, QMessageBox):
            QTest.keyClick(w, Qt.Key_Enter)

class DialogTestsAPI(unittest.TestCase):
    with open(os.path.join(os.path.dirname(__file__), 'aws_credentials.json'), 'r') as fin:
        keys = json.load(fin)

    def testAPILogin(self):
        dialog = DlgSettingsLogin()
        dialog.email.setText(keys['email'])
        dialog.password.setText(keys['password'])
        self.assertEquals(keys['email'], dialog.username)
        self.assertEquals(keys['password'], dialog.password)
        okWidget = dialog.buttonBox.button(dialog.buttonBox.Ok)
        QTest.mouseClick(okWidget, Qt.LeftButton)
        self.assertTrue(dialog.ok)

        ret = dialog.login()
        self.assertTrue(ret)
        close_msg_boxes()

        dialog.email.setText('')
        dialog.password.setText(keys['password'])
        ret = dialog.login()
        self.assertFalse(ret)
        close_msg_boxes()

        dialog.email.setText(keys['email'])
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
    suite.addTests(unittest.makeSuite(DialogTestsAPI, 'test'))
    return suite

def run_all():
    unittest.TextTestRunner(verbosity=3, stream=sys.stdout).run(suite())
