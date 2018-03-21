# -*- coding: utf-8 -*-
#
# (c) 2016 Boundless, http://boundlessgeo.com
# This code is licensed under the GPL 2.0 license.
#
import unittest
import sys
import os
from qgis.core import *
from PyQt4.QtCore import *
from PyQt4.QtTest import QTest
from LDMP import DlgSettings()


class DialogTestsAPI(unittest.TestCase):
    def testAPILogin(self):
        dialog = DefineCatalogDialog(self.explorer.catalogs())
        dialog.nameBox.setText("trends-earth-automated-tests@trends.earth")
        dialog.urlBox.setText("http://" + geoserverLocation() + "/geoserver")
        dialog.passwordBox.setText("password")
        dialog.usernameBox.setText("username")
        okWidget = dialog.buttonBox.button(dialog.buttonBox.Ok)
        QTest.mouseClick(okWidget, Qt.LeftButton)
        self.assertTrue(dialog.ok)
        self.assertEquals("username", dialog.username)
        self.assertEquals("password", dialog.password)
        self.assertEquals("name", dialog.name)
        self.assertEquals("http://" + geoserverLocation() + "/geoserver/rest", dialog.url)
        settings = QSettings()
        settings.endGroup()
        settings.beginGroup("/GeoServer/Catalogs/name")
        settings.remove("")
        settings.endGroup()

        QTest.mouseClick(okWidget, Qt.LeftButton)
        self.assertTrue(dialog.ok)
        self.assertEquals("catalogname", dialog.name)
        self.assertEquals("http://localhost:8081/geoserver/rest", dialog.url)
        dialog = DefineCatalogDialog(self.explorer.catalogs())
        self.assertEquals("catalogname", dialog.nameBox.text())
        self.assertEquals("localhost:8081/geoserver", dialog.urlBox.text())
        okWidget = dialog.buttonBox.button(dialog.buttonBox.Ok)
        QTest.mouseClick(okWidget, Qt.LeftButton)

def suite():
    suite = unittest.TestSuite()
    suite.addTests(unittest.makeSuite(GSNameDialogTest, 'test'))
    return suite

def run_all():
    unittest.TextTestRunner(verbosity=3, stream=sys.stdout).run(suite())
