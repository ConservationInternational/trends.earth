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
        email                : GEF-LDMP@conservation.org
 ***************************************************************************/
"""

import os

from PyQt4.QtCore import QCoreApplication
from PyQt4 import QtGui, uic

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'DlgSettings.ui'))

class DlgSettings (QtGui.QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgSettings, self).__init__(parent)
        # Set up the user interface from Designer.
        # After setupUI you can access any designer object by doing
        # self.<objectname>, and you can use autoconnect slots - see
        # http://qt-project.org/doc/qt-4.8/designer-using-a-ui-file.html
        # #widgets-and-dialogs-with-auto-connect
        self.setupUi(self)

        self.login.clicked.connect(self.btn_login)
        self.forgot_pwd.clicked.connect(self.btn_forgot_pwd)
        self.register_user.clicked.connect(self.btn_register)
        self.cancel.clicked.connect(self.btn_cancel)

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('LDMP', message)

    def btn_register(self):
        if not self.email.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter an email address to register.").format(self.email), None)
        elif not self.name.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your name before registering.").format(self.email), None)
        elif not self.organization.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your organization before registering.").format(self.email), None)
        elif not self.country.currentText():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your country before registering.").format(self.email), None)
        elif self.password.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("If you are registering for the first time, do not enter a password. Your password will be send to you via email after registration.").format(self.email), None)
        else:
            #TODO: setup so this message can be translated    
            QtGui.QMessageBox.information(None, self.tr("Registered"), self.tr("Registered {} as new user.").format(self.email.text()), None)
            self.close()

    def btn_cancel(self):
        self.close()

    def btn_forgot_pwd(self):
        # Verify there is input for email
        self.close()

    def btn_login(self):
        # Verify there are inputs for email and password
        self.close()
