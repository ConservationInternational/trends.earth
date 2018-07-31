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

import os
import json

from qgis.PyQt.QtCore import QCoreApplication, QSettings
from qgis.PyQt import QtGui

from qgis.utils import iface
mb = iface.messageBar()

from LDMP.gui.DlgSettings import Ui_DlgSettings
from LDMP.gui.DlgSettingsEdit import Ui_DlgSettingsEdit
from LDMP.gui.DlgSettingsEditForgotPassword import Ui_DlgSettingsEditForgotPassword
from LDMP.gui.DlgSettingsEditUpdate import Ui_DlgSettingsEditUpdate
from LDMP.gui.DlgSettingsLogin import Ui_DlgSettingsLogin
from LDMP.gui.DlgSettingsRegister import Ui_DlgSettingsRegister

from LDMP.api import get_user_email, get_user, delete_user, login, register, \
    update_user, recover_pwd
from LDMP.download import get_admin_bounds

settings = QSettings()


class DlgSettings(QtGui.QDialog, Ui_DlgSettings):
    def __init__(self, parent=None):
        super(DlgSettings, self).__init__(parent)

        self.setupUi(self)

        self.dlg_settings_register = DlgSettingsRegister()
        self.dlg_settings_login = DlgSettingsLogin()
        self.dlg_settings_edit = DlgSettingsEdit()

        self.pushButton_register.clicked.connect(self.register)
        self.pushButton_login.clicked.connect(self.login)
        self.pushButton_edit.clicked.connect(self.edit)
        self.pushButton_forgot_pwd.clicked.connect(self.forgot_pwd)

        self.buttonBox.rejected.connect(self.close)

    def register(self):
        result = self.dlg_settings_register.exec_()

    def login(self):
        result = self.dlg_settings_login.exec_()
        if result and self.dlg_settings_login.ok:
            self.close()

    def edit(self):
        if not get_user_email():
            # Note that the get_user_email will display a message box warning 
            # the user to register.
            return

        self.dlg_settings_edit.exec_()

    def forgot_pwd(self):
        dlg_settings_edit_forgot_password = DlgSettingsEditForgotPassword()
        ret = dlg_settings_edit_forgot_password.exec_()
        if ret and dlg_settings_edit_forgot_password.ok:
            self.done(QtGui.QDialog.Accepted)


class DlgSettingsRegister(QtGui.QDialog, Ui_DlgSettingsRegister):
    def __init__(self, parent=None):
        super(DlgSettingsRegister, self).__init__(parent)

        self.setupUi(self)

        self.admin_bounds_key = get_admin_bounds()
        self.country.addItems(sorted(self.admin_bounds_key.keys()))

        self.buttonBox.accepted.connect(self.register)
        self.buttonBox.rejected.connect(self.close)

    def register(self):
        if not self.email.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your email address."), None)
            return
        elif not self.name.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your name."), None)
            return
        elif not self.organization.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your organization."), None)
            return
        elif not self.country.currentText():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your country."), None)
            return

        resp = register(self.email.text(), self.name.text(), self.organization.text(), self.country.currentText())
        if resp:
            self.close()
            QtGui.QMessageBox.information(None,
                    self.tr("Success"),
                    self.tr(u"User registered. Your password has been emailed to {}.".format(self.email.text())))
            settings.setValue("LDMP/email", self.email.text())
            settings.setValue("LDMP/password", None)
            return True


class DlgSettingsLogin(QtGui.QDialog, Ui_DlgSettingsLogin):
    def __init__(self, parent=None):
        super(DlgSettingsLogin, self).__init__(parent)

        self.setupUi(self)

        self.buttonBox.accepted.connect(self.login)
        self.buttonBox.rejected.connect(self.close)

        self.ok = False

    def showEvent(self, event):
        super(DlgSettingsLogin, self).showEvent(event)

        email = get_user_email(warn=False)
        if email:
            self.email.setText(email)
        password = settings.value("LDMP/password", None)
        if password:
            self.password.setText(password)

    def login(self):
        if not self.email.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Enter your email address."), None)
            return
        elif not self.password.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Enter your password."), None)
            return

        resp = login(self.email.text(), self.password.text())
        if resp:
            QtGui.QMessageBox.information(None,
                    self.tr("Success"),
                    self.tr(u"Logged in to the Trends.Earth server as {}.").format(self.email.text()))
            settings.setValue("LDMP/jobs_cache", None)
            self.done(QtGui.QDialog.Accepted)
            self.ok = True


class DlgSettingsEdit(QtGui.QDialog, Ui_DlgSettingsEdit):
    def __init__(self, parent=None):
        super(DlgSettingsEdit, self).__init__(parent)

        self.setupUi(self)

        self.pushButton_change_user.clicked.connect(self.change_user)
        self.pushButton_update_profile.clicked.connect(self.update_profile)
        self.pushButton_delete_user.clicked.connect(self.delete)

        self.buttonBox.rejected.connect(self.close)

        self.ok = False

    def change_user(self):
        dlg_settings_change_user = DlgSettingsLogin()
        ret = dlg_settings_change_user.exec_()
        if ret and dlg_settings_change_user.ok:
            self.close()

    def update_profile(self):
        user = get_user()
        if not user:
            return
        dlg_settings_edit_update = DlgSettingsEditUpdate(user)
        ret = dlg_settings_edit_update.exec_()
        if ret and dlg_settings_edit_update.ok:
            self.close()

    def delete(self):
        email = get_user_email()
        if not email:
            return

        reply = QtGui.QMessageBox.question(None, self.tr("Delete user?"),
                                           self.tr(u"Are you sure you want to delete the user {}? All of your tasks will be lost and you will no longer be able to process data online using Trends.Earth.".format(email)),
                                           QtGui.QMessageBox.Yes, QtGui.QMessageBox.No)
        if reply == QtGui.QMessageBox.Yes:
            resp = delete_user(email)
            if resp:
                QtGui.QMessageBox.information(None,
                        self.tr("Success"),
                        QtGui.QApplication.translate('LDMPPlugin', u"User {} deleted.".format(email)))
                settings.setValue("LDMP/password", None)
                settings.setValue("LDMP/email", None)
                self.close()
                self.ok = True


class DlgSettingsEditForgotPassword(QtGui.QDialog, Ui_DlgSettingsEditForgotPassword):
    def __init__(self, parent=None):
        super(DlgSettingsEditForgotPassword, self).__init__(parent)

        self.setupUi(self)

        self.buttonBox.accepted.connect(self.reset_password)
        self.buttonBox.rejected.connect(self.close)

        self.ok = False

    def showEvent(self, event):
        super(DlgSettingsEditForgotPassword, self).showEvent(event)

        email = get_user_email(warn=False)
        if email:
            self.email.setText(email)

    def reset_password(self):
        if not self.email.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Enter your email address to reset your password."), None)
            return

        reply = QtGui.QMessageBox.question(None, self.tr("Reset password?"),
                                           self.tr(u"Are you sure you want to reset the password for {}? Your new password will be emailed to you.".format(self.email.text())),
                                           QtGui.QMessageBox.Yes, QtGui.QMessageBox.No)

        if reply == QtGui.QMessageBox.Yes:
            resp = recover_pwd(self.email.text())
            if resp:
                self.close()
                QtGui.QMessageBox.information(None,
                        self.tr("Success"),
                        self.tr(u"The password has been reset for {}. Check your email for the new password, and then return to Trends.Earth to enter it.").format(self.email.text()))
                settings.setValue("LDMP/password", None)
                self.ok = True


class DlgSettingsEditUpdate(QtGui.QDialog, Ui_DlgSettingsEditUpdate):
    def __init__(self, user, parent=None):
        """Constructor."""
        super(DlgSettingsEditUpdate, self).__init__(parent)

        self.setupUi(self)

        self.user = user

        self.admin_bounds_key = get_admin_bounds()

        self.email.setText(user['email'])
        self.name.setText(user['name'])
        self.organization.setText(user['institution'])

        # Add countries, and set index to currently chosen country
        self.country.addItems(sorted(self.admin_bounds_key.keys()))
        index = self.country.findText(user['country'])
        if index != -1:
            self.country.setCurrentIndex(index)

        self.buttonBox.accepted.connect(self.update_profile)
        self.buttonBox.rejected.connect(self.close)

        self.ok = False

    def update_profile(self):
        if not self.email.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your email address."), None)
            return
        elif not self.name.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your name."), None)
            return
        elif not self.organization.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your organization."), None)
            return
        elif not self.country.currentText():
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your country."), None)
            return

        resp = update_user(self.email.text(), self.name.text(),
                           self.organization.text(), self.country.currentText())

        if resp:
            QtGui.QMessageBox.information(None, self.tr("Saved"),
                                          self.tr(u"Updated information for {}.").format(self.email.text()), None)
            self.close()
            self.ok = True
