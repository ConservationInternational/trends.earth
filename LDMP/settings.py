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
from PyQt4 import QtGui

from qgis.utils import iface
mb = iface.messageBar()

from LDMP.gui.DlgSettings import Ui_DlgSettings as UiDialog

from LDMP.gui.DlgSettingsRegister import Ui_DlgSettingsRegister
from LDMP.gui.DlgSettingsUpdate import Ui_DlgSettingsUpdate

from LDMP.api import get_user_email, get_user, delete_user, login, register, update_user, recover_pwd

class DlgSettings (QtGui.QDialog, UiDialog):
    def __init__(self, parent=None):
        super(DlgSettings, self).__init__(parent)
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

        email = get_user_email(warn=False)
        if email: self.email.setText(email)
        password = self.settings.value("LDMP/password", None)
        if password: self.password.setText(password)

    def btn_update_profile(self):
        if not self.email.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("Enter an email address to update."), None)
        elif not self.password.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("Enter your password to update your user details."), None)
        else:
            # Validate the email/password by logging in first
            resp = login(self.email.text(), self.password.text())
            if not resp:
                return
            user = get_user()
            if not user:
                return

            self.dlg_settingsupdate.email.setText(user['email'])
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
        admin_0 = json.loads(QSettings().value('LDMP/admin_0', None))
        self.dlg_settingsregister.country.addItems(sorted(admin_0.keys()))
        result = self.dlg_settingsregister.exec_()
        # See if OK was pressed
        if result:
            self.close()

    def btn_delete(self):
        if not self.email.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("Enter your email."), None)
            return
        if not self.password.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("Enter your password."), None)
            return
        reply = QtGui.QMessageBox.question(None, self.tr("Delete user?"),
                    self.tr("Are you sure you want to delete your user? All of your tasks will be lost and you will no longer be able to process data online using the toolbox."),
                    QtGui.QMessageBox.Yes, QtGui.QMessageBox.No)
        if reply == QtGui.QMessageBox.Yes:
            resp = delete_user(self.email.text)
            if resp:
                mb.pushMessage(QtGui.QApplication.translate('LDMPPlugin', "Success"),
                        QtGui.QApplication.translate('LDMPPlugin', "User {} deleted.").format(self.email.text()), level=0)
                self.settings.setValue("LDMP/password", None)
                self.settings.setValue("LDMP/email", None)
                self.email.setText(None)
                self.password.setText(None)
                self.close()
                return True
            else:
                return False

    def btn_cancel(self):
        self.close()

    def btn_forgot_pwd(self):
        # Verify there is input for email
        if not self.email.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("Enter your email address to reset your password."), None)
            return
        resp = recover_pwd(self.email.text())
        if resp != None:
            mb.pushMessage(self.tr("Success"),
                    self.tr("The password has been reset for {}. Check your email for the new password.").format(self.email.text()), level=0)
            self.close()

    def btn_login(self):
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
            mb.pushMessage(self.tr("Success"),
                    self.tr("Logged in to the LDMP server as {}.").format(self.email.text()), level=0)
            self.settings.setValue("LDMP/jobs_cache", None)
            self.close()

class DlgSettingsRegister(QtGui.QDialog, Ui_DlgSettingsRegister):
    def __init__(self, parent=None):
        super(DlgSettingsRegister, self).__init__(parent)
        self.setupUi(self)

        self.save.clicked.connect(self.btn_save)
        self.cancel.clicked.connect(self.btn_cancel)

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
            resp = register(self.email.text(), self.name.text(), self.organization.text(), self.country.currentText())
            if resp:
                mb.pushMessage("Success", "User {} registered. Your password has been emailed to you.".format(self.email.text()), level=0)
                self.close()
                return True
            else:
                return False

    def btn_cancel(self):
        self.close()

class DlgSettingsUpdate(QtGui.QDialog, Ui_DlgSettingsUpdate):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgSettingsUpdate, self).__init__(parent)
        self.setupUi(self)

        self.save.clicked.connect(self.btn_save)
        self.cancel.clicked.connect(self.btn_cancel)

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
            resp = update_user(self.email.text(), self.name.text(), 
                    self.organization.text(), self.country.currentText())
            if resp != None:
                QtGui.QMessageBox.information(None, self.tr("Saved"),
                        self.tr("Updated information for {}.").format(self.email.text()), None)
                self.close()

    def btn_cancel(self):
        self.close()
