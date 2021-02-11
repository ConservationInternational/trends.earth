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
import re
import zipfile
from pathlib import Path

from qgis.PyQt.QtCore import QSettings, pyqtSignal
from qgis.PyQt import QtWidgets

from qgis.utils import iface
from qgis.core import QgsApplication
mb = iface.messageBar()

from LDMP.gui.DlgSettings import Ui_DlgSettings
from LDMP.gui.DlgSettingsEdit import Ui_DlgSettingsEdit
from LDMP.gui.DlgSettingsEditForgotPassword import Ui_DlgSettingsEditForgotPassword
from LDMP.gui.DlgSettingsEditUpdate import Ui_DlgSettingsEditUpdate
from LDMP.gui.DlgSettingsLogin import Ui_DlgSettingsLogin
from LDMP.gui.DlgSettingsRegister import Ui_DlgSettingsRegister
from LDMP.gui.DlgSettingsAdvanced import Ui_DlgSettingsAdvanced

from LDMP import binaries_available, __version__
from LDMP.api import (
    get_user_email,
    get_user,
    delete_user,
    login,
    register,
    update_user,
    recover_pwd,
    init_auth_config,
    remove_current_auth_config,
    AUTH_CONFIG_NAME
)
from LDMP.download import download_files, get_admin_bounds

settings = QSettings()


# Function to indicate if child is a folder within parent
def is_subdir(child, parent):
    parent = os.path.normpath(os.path.realpath(parent))
    child = os.path.normpath(os.path.realpath(child))
    if not os.path.isdir(parent) or not os.path.isdir(child):
        return False
    elif child == parent:
        return True
    head, tail = os.path.split(child)
    if head == parent:
        return True
    elif tail == '':
        return False
    else:
        return is_subdir(head, parent)


class DlgSettings(QtWidgets.QDialog, Ui_DlgSettings):
    def __init__(self, parent=None):
        super(DlgSettings, self).__init__(parent)

        self.setupUi(self)

        self.dlg_settings_register = DlgSettingsRegister()
        self.dlg_settings_login = DlgSettingsLogin()
        self.dlg_settings_edit = DlgSettingsEdit()
        self.dlg_settings_advanced = DlgSettingsAdvanced()

        # update authConfig list if triggered by sub GUIs that can add modify or update auth configs
        self.dlg_settings_edit.authConfigUpdated.connect(self.reloadAuthConfigurations)
        self.dlg_settings_register.authConfigInitialised.connect(self.selectDefaultAuthConfiguration)

        self.pushButton_register.clicked.connect(self.register)
        self.pushButton_test_connection.clicked.connect(self.login)
        self.pushButton_edit.clicked.connect(self.edit)
        self.pushButton_advanced.clicked.connect(self.advanced)

        self.buttonBox.accepted.connect(self.close)

        # load gui default value from settings
        self.reloadAuthConfigurations()

    def reloadAuthConfigurations(self):
        self.authConfigSelect_authentication.populateConfigSelector()
        self.authConfigSelect_authentication.clearMessage()

        authConfigId = settings.value("trend_earth/authId", None)
        configs = QgsApplication.authManager().availableAuthMethodConfigs()
        if authConfigId in configs.keys():
            self.authConfigSelect_authentication.setConfigId(authConfigId)
    
    def selectDefaultAuthConfiguration(self, authConfigId):
        self.reloadAuthConfigurations()
        if authConfigId:
            self.authConfigSelect_authentication.setConfigId(authConfigId)

    def register(self):
        result = self.dlg_settings_register.exec_()

    def login(self):
        # retrieve basic auth from QGIS authManager
        authConfigId = self.authConfigSelect_authentication.configId()
        
        # try to login with current credentials
        resp = login(authConfigId)
        if resp:
            username = get_user_email()
            QtWidgets.QMessageBox.information(None,
                    self.tr("Success"),
                    self.tr(u"""Logged in to the Trends.Earth server as {}.<html><p>Welcome to Trends.Earth!<p/><p>
                    <a href= 'https://groups.google.com/forum/#!forum/trends_earth_users/join'>Join the Trends.Earth Users google groups<a/></p><p> Make sure to join the google groups for the Trends.Earth users to keep up with updates and Q&A about the tool, methods, and datasets in support of Sustainable Development Goals monitoring.</p>""").format(username))
            settings.setValue("LDMP/jobs_cache", None)
            self.ok = True

    def edit(self):
        if not get_user_email():
            # Note that the get_user_email will display a message box warning 
            # the user to register.
            return

        self.dlg_settings_edit.exec_()

    def advanced(self):
        result = self.dlg_settings_advanced.exec_()


class DlgSettingsRegister(QtWidgets.QDialog, Ui_DlgSettingsRegister):

    authConfigInitialised = pyqtSignal(str)

    def __init__(self, parent=None):
        super(DlgSettingsRegister, self).__init__(parent)

        self.setupUi(self)

        self.admin_bounds_key = get_admin_bounds()
        self.country.addItems(sorted(self.admin_bounds_key.keys()))

        self.buttonBox.accepted.connect(self.register)
        self.buttonBox.rejected.connect(self.close)

    def register(self):
        if not self.email.text():
            QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your email address."))
            return
        elif not self.name.text():
            QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your name."))
            return
        elif not self.organization.text():
            QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your organization."))
            return
        elif not self.country.currentText():
            QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your country."))
            return

        resp = register(self.email.text(), self.name.text(), self.organization.text(), self.country.currentText())
        if resp:
            self.close()
            QtWidgets.QMessageBox.information(None,
                    self.tr("Success"),
                    self.tr(u"User registered. Your password has been emailed to {}. Then set it in {} configuration".format(self.email.text(), AUTH_CONFIG_NAME)))
            
            # add a new auth conf that have to be completed with pwd
            authConfidId = init_auth_config(email=self.email.text())
            if authConfidId:
                self.authConfigInitialised.emit(authConfidId)

            return True


class DlgSettingsLogin(QtWidgets.QDialog, Ui_DlgSettingsLogin):
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
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Enter your email address."))
            return
        elif not self.password.text():
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Enter your password."))
            return

        resp = login(self.email.text(), self.password.text())
        if resp:
            QtWidgets.QMessageBox.information(None,
                    self.tr("Success"),
                    self.tr(u"""Logged in to the Trends.Earth server as {}.<html><p>Welcome to Trends.Earth!<p/><p>
                    <a href= 'https://groups.google.com/forum/#!forum/trends_earth_users/join'>Join the Trends.Earth Users google groups<a/></p><p> Make sure to join the google groups for the Trends.Earth users to keep up with updates and Q&A about the tool, methods, and datasets in support of Sustainable Development Goals monitoring.</p>""").format(self.email.text()))
            settings.setValue("LDMP/jobs_cache", None)
            self.done(QtWidgets.QDialog.Accepted)
            self.ok = True


class DlgSettingsEdit(QtWidgets.QDialog, Ui_DlgSettingsEdit):

    authConfigUpdated = pyqtSignal()

    def __init__(self, parent=None):
        super(DlgSettingsEdit, self).__init__(parent)

        self.setupUi(self)

        self.pushButton_forgot_pwd.clicked.connect(self.forgot_pwd)
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

        reply = QtWidgets.QMessageBox.question(None, self.tr("Delete user?"),
                                           self.tr(u"Are you sure you want to delete the user {}? All of your tasks will be lost and you will no longer be able to process data online using Trends.Earth.".format(email)),
                                           QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No)
        if reply == QtWidgets.QMessageBox.Yes:
            resp = delete_user(email)
            if resp:
                QtWidgets.QMessageBox.information(None,
                        self.tr("Success"),
                        QtWidgets.QApplication.translate('LDMP', u"User {} deleted.".format(email)))
                
                # remove current used config (as set in QSettings) and trigger GUI
                remove_current_auth_config()
                self.authConfigUpdated.emit()

                self.close()
                self.ok = True

    def forgot_pwd(self):
        dlg_settings_edit_forgot_password = DlgSettingsEditForgotPassword()
        ret = dlg_settings_edit_forgot_password.exec_()
        if ret and dlg_settings_edit_forgot_password.ok:
            self.done(QtWidgets.QDialog.Accepted)


class DlgSettingsEditForgotPassword(QtWidgets.QDialog, Ui_DlgSettingsEditForgotPassword):
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
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Enter your email address to reset your password."))
            return

        reply = QtWidgets.QMessageBox.question(None, self.tr("Reset password?"),
                                           self.tr(u"Are you sure you want to reset the password for {}? Your new password will be emailed to you.".format(self.email.text())),
                                           QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No)

        if reply == QtWidgets.QMessageBox.Yes:
            resp = recover_pwd(self.email.text())
            if resp:
                self.close()
                QtWidgets.QMessageBox.information(None,
                        self.tr("Success"),
                        self.tr(u"The password has been reset for {}. Check your email for the new password, and then return to Trends.Earth to enter it.").format(self.email.text()))
                self.ok = True


class DlgSettingsEditUpdate(QtWidgets.QDialog, Ui_DlgSettingsEditUpdate):
    def __init__(self, user, parent=None):
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
            QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your email address."))
            return
        elif not self.name.text():
            QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your name."))
            return
        elif not self.organization.text():
            QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your organization."))
            return
        elif not self.country.currentText():
            QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr("Enter your country."))
            return

        resp = update_user(self.email.text(), self.name.text(),
                           self.organization.text(), self.country.currentText())

        if resp:
            QtWidgets.QMessageBox.information(None, self.tr("Saved"),
                                          self.tr(u"Updated information for {}.").format(self.email.text()))
            self.close()
            self.ok = True


class DlgSettingsAdvanced(QtWidgets.QDialog, Ui_DlgSettingsAdvanced):
    def __init__(self, parent=None):
        super(DlgSettingsAdvanced, self).__init__(parent)

        self.setupUi(self)

        self.buttonBox.accepted.connect(self.close)
        self.binaries_browse_button.clicked.connect(self.binary_folder_browse)
        self.binaries_download_button.clicked.connect(self.binaries_download)
        self.debug_checkbox.clicked.connect(self.debug_toggle)
        self.binaries_checkbox.clicked.connect(self.binaries_toggle)

        # Flag that can be used to indicate if binary state has changed (i.e. 
        # if new binaries have been downloaded)
        self.binary_state_changed = False

    def close(self):
        super(DlgSettingsAdvanced, self).close()
        if self.binaries_checkbox.isChecked() != self.binaries_checkbox_initial or self.binary_state_changed:
            QtWidgets.QMessageBox.warning(None,
                                          self.tr("Warning"),
                                          self.tr("You must restart QGIS for these changes to take effect."))

    def showEvent(self, event):
        super(DlgSettingsAdvanced, self).showEvent(event)

        self.debug_checkbox.setChecked(QSettings().value("LDMP/debug", False) == 'True')

        binaries_checked = QSettings().value("LDMP/binaries_enabled", False) == 'True'
        # TODO: Have this actually check if they are enabled in summary_numba 
        # and calculate_numba. Right now this doesn't really check if they are 
        # enabled, just that they are available. Which should be the same 
        # thing, but might not always be...
        if binaries_available() and binaries_checked:
            self.binaries_label.setText(self.tr('Binaries <b>are</b> loaded.'))
        else:
            self.binaries_label.setText(self.tr('Binaries <b>are not</b> loaded.'))
        # Set a flag that will be used to indicate whether the status of using 
        # binaries or not has changed (needed to allow displaying a message to 
        # the user that they need to restart when this setting is changed)

        binaries_folder = QSettings().value("LDMP/binaries_folder", None)
        if binaries_folder is not None:
            self.binaries_folder.setText(binaries_folder)

        self.binaries_checkbox_initial = binaries_checked
        self.binaries_checkbox.setChecked(binaries_checked)
        self.binaries_toggle()

    def binaries_download(self):
        out_folder = os.path.join(self.binaries_folder.text())
        if out_folder == '':
            QtWidgets.QMessageBox.information(None,
                                       self.tr("Choose a folder"),
                                       self.tr("Choose a folder before downloading binaries."))
            return

        if not os.access(out_folder, os.W_OK):
            QtWidgets.QMessageBox.critical(None,
                                       self.tr("Error"),
                                       self.tr("Unable to write to {}. Choose a different folder.".format(out_folder)))
            return

        try:
            if not os.path.exists(out_folder):
                os.makedirs(out_folder)
        except PermissionError:
            QtWidgets.QMessageBox.critical(None,
                                       self.tr("Error"),
                                       self.tr("Unable to write to {}. Try a different folder.".format(filename)))
            return None

        zip_filename = 'trends_earth_binaries_{}.zip'.format(__version__.replace('.', '_'))
        zip_url = 'https://s3.amazonaws.com/trends.earth/plugin_binaries/' + zip_filename
        downloads = download_files([zip_url], out_folder)

        try:
            with zipfile.ZipFile(os.path.join(out_folder, zip_filename), 'r') as zf:
                zf.extractall(out_folder)
        except PermissionError:
            QtWidgets.QMessageBox.critical(None,
                                       self.tr("Error"),
                                       self.tr("Unable to write to {}. Check that you have permissions to write to this folder, and that you are not trying to overwrite the binaries that you currently have loaded in QGIS.".format(out_folder)))
            return None
        finally:
            os.remove(os.path.join(out_folder, zip_filename))

        if downloads is None:
            QtWidgets.QMessageBox.critical(None,
                                       self.tr("Error"),
                                       self.tr("Error downloading binaries."))
        else:
            if len(downloads) > 0:
                self.binary_state_changed = True
                QtWidgets.QMessageBox.information(None,
                                           self.tr("Success"),
                                           self.tr("Downloaded binaries."))
            else:
                QtWidgets.QMessageBox.critical(None,
                                           self.tr("Success"),
                                           self.tr("All binaries up to date.".format(out_folder)))


    def binaries_toggle(self):
        state = self.binaries_checkbox.isChecked()
        QSettings().setValue("LDMP/binaries_enabled", str(state))
        self.binaries_folder.setEnabled(state)
        self.binaries_browse_button.setEnabled(state)
        self.binaries_download_button.setEnabled(state)
        self.binaries_label.setEnabled(state)

    def debug_toggle(self):
        QSettings().setValue("LDMP/debug", str(self.debug_checkbox.isChecked()))

    def binary_folder_browse(self):
        initial_path = QSettings().value("LDMP/binaries_folder", None)
        if not initial_path:
            initial_path = str(Path.home())

        folder = QtWidgets.QFileDialog.getExistingDirectory(self,
                                                            self.tr('Select folder containing Trends.Earth binaries'),
                                                            initial_path)
        if folder:
            plugin_folder = os.path.normpath(os.path.realpath(os.path.dirname(__file__)))
            if is_subdir(folder, plugin_folder):
                QtWidgets.QMessageBox.critical(None,
                                               self.tr("Error"),
                                               self.tr(u"Choose a different folder - cannot install binaries within the Trends.Earth QGIS plugin installation folder.".format(plugin_folder)))
                return False
            if os.access(folder, os.W_OK):
                QSettings().setValue("LDMP/binaries_folder", folder)
                self.binaries_folder.setText(folder)
                self.binary_state_changed = True
                return True
            else:
                QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr(u"Cannot read {}. Choose a different folder.".format(folder)))
                return False
        else:
            return False
                

