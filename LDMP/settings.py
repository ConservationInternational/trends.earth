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
import json

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

        self.settings = QSettings()

        self.setupUi(self)
        
        self.dlg_settingsregister = DlgSettingsRegister()
        self.dlg_settingsupdate = DlgSettingsUpdate()

        self.register_user.clicked.connect(self.btn_register)
        self.delete_user.clicked.connect(self.btn_delete)
        self.login.clicked.connect(self.btn_login)
        self.update_profile.clicked.connect(self.btn_update_profile)
        self.forgot_pwd.clicked.connect(self.btn_forgot_pwd)
        self.cancel.clicked.connect(self.btn_cancel)

        email = self.settings.value("LDMP/email", None)
        if email: self.email.setText(email)
        password = self.settings.value("LDMP/password", None)
        if password: self.password.setText(password)

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
            user = self.api.get_user(self.email.text())

            self.dlg_settingsupdate.email.setText(user['email'])
            self.dlg_settingsupdate.password.setText(self.settings.value("LDMP/password"))
            self.dlg_settingsupdate.name.setText(user['name'])
            self.dlg_settingsupdate.organization.setText(user['institution'])

            # Add countries, and set index to currently chosen country
            admin_0 = json.loads(QSettings().value('LDMP/admin_0', None))
            self.dlg_settingsupdate.country.addItems(sorted(admin_0.keys()))
            index = self.dlg_settingsupdate.country.findText(user['country'])
            if index != -1: self.dlg_settingsupdate.country.setCurrentIndex(index)

            result = self.dlg_settingsupdate.exec_()

            if result:
                self.close()

    def btn_register(self):
        #TODO: Handle country once I have the data list ready.
        admin_0 = json.loads(QSettings().value('LDMP/admin_0', None))
        self.dlg_settingsregister.country.addItems(sorted(admin_0.keys()))
        result = self.dlg_settingsregister.exec_()
        # See if OK was pressed
        if result:
            pass

    def btn_delete(self):
        QtGui.QMessageBox.critical(None, self.tr("Error"),
                self.tr("Delete user functionality coming soon!"), None)
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
            QtGui.QMessageBox.information(None, self.tr("Login successful"), 
                    self.tr("Logged in to the LDMP server as {}.".format(self.email.text())), None)
            self.close()
        except APIInvalidCredentials as error:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("Invalid username or password."), None)
        except APIError:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("Error connecting to the LDMP server."), None)

class DlgSettingsRegister(QtGui.QDialog, Ui_DlgSettingsRegister):
    def __init__(self, parent=None):
        super(DlgSettingsRegister, self).__init__(parent)
        self.setupUi(self)

        self.api = API()

        self.save.clicked.connect(self.btn_save)
        self.cancel.clicked.connect(self.btn_cancel)

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('LDMP', message)

    def btn_save(self):
        if not self.email.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your email address."), None)
        elif not self.name.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your name."), None)
        elif not self.organization.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your organization."), None)
        elif not self.country.currentText():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your country."), None)
        else:
            try:
                self.api.register(self.email.text(), self.name.text(), self.organization.text(), self.country.currentText())
                QtGui.QMessageBox.information(None, self.tr("Registered"), self.tr("Registered {}. Your password has been emailed to you.").format(self.email.text()), None)
                self.close()
            except APIUserAlreadyExists as error:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                        self.tr("User already exists."), None)
            except APIError:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                        self.tr("Error connecting to the LDMP server."), None)

    def btn_cancel(self):
        self.close()

class DlgSettingsUpdate(QtGui.QDialog, Ui_DlgSettingsUpdate):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgSettingsUpdate, self).__init__(parent)
        self.setupUi(self)

        self.api = API()

        self.save.clicked.connect(self.btn_save)
        self.cancel.clicked.connect(self.btn_cancel)

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('LDMP', message)

    def btn_save(self):
        if not self.email.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your email address."), None)
        elif not self.name.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your name."), None)
        elif not self.organization.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your organization."), None)
        elif not self.country.currentText():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your country."), None)
        else:
            self.api.update_user(self.email.text(), self.name.text(), 
                    self.organization.text(), self.country.currentText())
            
            QtGui.QMessageBox.information(None, self.tr("Saved"),
                    self.tr("Updated information for {}.").format(self.email.text()), None)
            self.close()

    def btn_cancel(self):
        self.close()
