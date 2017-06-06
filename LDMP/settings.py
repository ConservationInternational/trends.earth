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

from PyQt4.QtCore import QCoreApplication, QSettings
from PyQt4 import QtGui, uic

DlgSettings_FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'DlgSettings.ui'))

from DlgSettingsRegister import Ui_DlgSettingsRegister
from DlgSettingsUpdate import Ui_DlgSettingsUpdate

from api import API
from api import APIError
from api import APIInvalidCredentials
from api import APIUserAlreadyExists

class DlgSettings (QtGui.QDialog, DlgSettings_FORM_CLASS):
    def __init__(self, parent=None):
        super(DlgSettings, self).__init__(parent)

        self.api = API()

        self.setupUi(self)
        
        self.dlg_settingsregister = DlgSettingsRegister()
        self.dlg_settingsupdate = DlgSettingsUpdate()

        self.register_user.clicked.connect(self.btn_register)
        self.login.clicked.connect(self.btn_login)
        self.update_profile.clicked.connect(self.btn_update_profile)
        self.forgot_pwd.clicked.connect(self.btn_forgot_pwd)
        self.cancel.clicked.connect(self.btn_cancel)

        settings = QSettings()
        email = settings.value("LDMP/email", None) 
        if email:
            self.email.setText(email)
        password = settings.value("LDMP/password", None)
        if password:
            self.password.setText(password)


    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('LDMP', message)

    def btn_update_profile(self):
        if not self.email.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("Enter an email address to update."), None)
        elif not self.password.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("Enter your password to update your user details."), None)
        else:
            result = self.dlg_settingsupdate.exec_()
            # See if OK was pressed
            if result:
                pass

    def btn_register(self):
        result = self.dlg_settingsregister.exec_()
        # See if OK was pressed
        if result:
            pass

    def btn_cancel(self):
        self.close()

    def btn_forgot_pwd(self):
        # Verify there is input for email
        if not self.email.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("Enter your email address to reset your password."), None)
        try:
            self.api.recover_pwd(self.email.text())
            QtGui.QMessageBox.information(None, self.tr("Recover password"),
                    self.tr("The password has been reset for {}. Check your email for the new password.").format(self.email.text()), None)
            self.close()
        except APIUserNotFound:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr('{} is not yet registered. Click "Register" to register this email.'), None)
        except APIError:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("Error connecting to the LDMP server."), None)

    def btn_login(self):
        if not self.email.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("Enter your email address."), None)
            self.close()
        elif not self.email.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("Enter your password."), None)
            self.close()
        try:
            self.api.login(self.email.text(), self.password.text())
            QtGui.QMessageBox.critical(None, self.tr("Login successful"), 
                    self.tr("Logged in to the LDMP server as {}.".format(self.email.text())), None)
            self.close()
        except APIInvalidCredentials:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("Invalid username or password."), None)
        except APIError:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("Error connecting to the LDMP server."), None)

class DlgSettingsRegister(QtGui.QDialog, Ui_DlgSettingsRegister):
    def __init__(self, parent=None):
        super(DlgSettingsRegister, self).__init__(parent)
        self.setupUi(self)

        self.save.clicked.connect(self.btn_save)
        self.cancel.clicked.connect(self.btn_cancel)

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('LDMP', message)

    def btn_save(self):
        if not self.email.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter an email address to register."), None)
        elif not self.name.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your name before registering."), None)
        elif not self.organization.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your organization before registering."), None)
        elif not self.country.currentText():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your country before registering."), None)
        else:
            #TODO: setup so this message can be translated    
            QtGui.QMessageBox.information(None, self.tr("Registered"), self.tr("Registered {} as new user. Your password has been emailed to you.").format(self.email.text()), None)
            self.close()

    def btn_cancel(self):
        self.close()

class DlgSettingsUpdate(QtGui.QDialog, Ui_DlgSettingsUpdate):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgSettingsUpdate, self).__init__(parent)
        self.setupUi(self)

        # Login first to get token, then retrieve current values of email, 
        # pass, name, organization, and country
        settings = QSettings()
        email = settings.value("LDMP/email", None) 
        if email:
            self.email.setText(email)
        password = settings.value("LDMP/password", None)
        if password:

        self.save.clicked.connect(self.btn_save)
        self.cancel.clicked.connect(self.btn_cancel)

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('LDMP', message)

    def btn_save(self):
        if not self.email.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter an email address to register."), None)
        elif not self.name.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your name before registering."), None)
        elif not self.organization.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your organization before registering."), None)
        elif not self.country.currentText():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your country before registering."), None)
        else:
            #TODO: setup so this message can be translated    
            QtGui.QMessageBox.information(None, self.tr("Registered"), self.tr("Registered {} as new user. Your password has been emailed to you.").format(self.email.text()), None)
            self.close()

    def btn_cancel(self):
        self.close()
