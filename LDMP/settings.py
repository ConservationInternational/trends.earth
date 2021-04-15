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
import subprocess
from pathlib import Path

from qgis.PyQt.QtCore import QSettings, pyqtSignal, Qt
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtGui import QIcon, QPixmap, QDoubleValidator

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsSettings,
    QgsVectorLayer
)
from qgis.gui import QgsMapToolEmitPoint, QgsMapToolPan

from qgis.utils import iface

from qgis.core import QgsApplication

from LDMP.gui.DlgSettings import Ui_DlgSettings
from LDMP.gui.DlgSettingsEdit import Ui_DlgSettingsEdit
from LDMP.gui.DlgSettingsEditForgotPassword import Ui_DlgSettingsEditForgotPassword
from LDMP.gui.DlgSettingsEditUpdate import Ui_DlgSettingsEditUpdate
from LDMP.gui.DlgSettingsLogin import Ui_DlgSettingsLogin
from LDMP.gui.DlgSettingsRegister import Ui_DlgSettingsRegister

from LDMP.gui.WidgetSettingsAdvanced import Ui_WidgetSettingsAdvanced
from LDMP.gui.DlgSettingsAdvanced import Ui_DlgSettingsAdvanced
from LDMP.gui.WidgetSelectArea import Ui_WidgetSelectArea

from LDMP import binaries_available, __version__, openFolder
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

from LDMP import log
from LDMP.download import download_files, get_admin_bounds, read_json, get_cities
from LDMP.message_bar import MessageBar

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

        # add subcomponent widgets
        self.widgetSettingsAdvanced = WidgetSettingsAdvanced()
        self.verticalLayout_advanced.layout().insertWidget(0, self.widgetSettingsAdvanced)

        # set Dialog UIs
        self.dlg_settings_register = DlgSettingsRegister()
        self.dlg_settings_login = DlgSettingsLogin()

        self.dlg_settings_register.authConfigInitialised.connect(self.selectDefaultAuthConfiguration)

        self.pushButton_register.clicked.connect(self.register)
        self.pushButton_login.clicked.connect(self.login)

        self.pushButton_update_profile.clicked.connect(self.update_profile)
        self.pushButton_delete_user.clicked.connect(self.delete)
        self.pushButton_forgot_pwd.clicked.connect(self.forgot_pwd)

        self.buttonBox.accepted.connect(self.close)
        self.settings = QgsSettings()

        self.area_widget = AreaWidget()
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.area_widget)

        self.region_of_interest.setLayout(layout)

        # load gui default value from settings
        self.reloadAuthConfigurations()

    def showEvent(self, event):
        super(DlgSettings, self).showEvent(event)
        # add message bar for all dialog communication
        MessageBar().init()
        self.layout().insertWidget(0, MessageBar().get())

    def close(self):
        super(DlgSettings, self).close()
        MessageBar().reset()

    def reloadAuthConfigurations(self):
        self.authConfigSelect_authentication.populateConfigSelector()
        self.authConfigSelect_authentication.clearMessage()

        authConfigId = settings.value("trends_earth/authId", None)
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
        if not authConfigId:
            MessageBar().get().pushCritical('Trends.Earth', self.tr('Please select a authentication profile'))
            return

        # try to login with current credentials
        resp = login(authConfigId)
        if resp:
            username = get_user_email()
            QtWidgets.QMessageBox.information(None,
                                              self.tr("Success"),
                                              self.tr(u"""Logged in to the Trends.Earth server as {}.<html><p>Welcome to Trends.Earth!<p/><p>
                    <a href= 'https://groups.google.com/forum/#!forum/trends_earth_users/join'>Join the Trends.Earth Users google groups<a/></p><p> Make sure to join the google groups for the Trends.Earth users to keep up with updates and Q&A about the tool, methods, and datasets in support of Sustainable Development Goals monitoring.</p>""").format(
                                                  username))
            settings.setValue("LDMP/jobs_cache", None)
            self.ok = True

    def forgot_pwd(self):
        dlg_settings_edit_forgot_password = DlgSettingsEditForgotPassword()
        dlg_settings_edit_forgot_password.exec_()

    def update_profile(self):
        user = get_user()
        if not user:
            return
        dlg_settings_edit_update = DlgSettingsEditUpdate(user)
        dlg_settings_edit_update.exec_()

    def delete(self):
        email = get_user_email()
        if not email:
            return

        reply = QtWidgets.QMessageBox.question(
            None,
            self.tr("Delete user?"),
            self.tr(
                u"Are you sure you want to delete the user {}? All of your tasks will "
                u"be lost and you will no longer be able to process data online "
                u"using Trends.Earth.".format(email)
            ),
            QtWidgets.QMessageBox.Yes,
            QtWidgets.QMessageBox.No
        )
        if reply == QtWidgets.QMessageBox.Yes:
            resp = delete_user(email)
            if resp:
                QtWidgets.QMessageBox.information(
                    None,
                    self.tr("Success"),
                    QtWidgets.QApplication.translate(
                        'LDMP', u"User {} deleted.".format(email))
                )
                # remove current used config (as set in QSettings) and trigger GUI
                remove_current_auth_config()
                self.reloadAuthConfigurations()
                # self.authConfigUpdated.emit()

    def accept(self):
        self.area_widget.save_settings()
        super().accept()


class AreaWidget(QtWidgets.QWidget, Ui_WidgetSelectArea):
    def __init__(self, parent=None):
        super(AreaWidget, self).__init__(parent)

        self.setupUi(self)

        self.canvas = iface.mapCanvas()
        self.settings = QgsSettings()
        self.vector_file = None
        self.current_cities_key = None

        self.admin_bounds_key = get_admin_bounds()
        if not self.admin_bounds_key:
            raise ValueError('Admin boundaries not available')

        self.cities = get_cities()
        if not self.cities:
            raise ValueError('Cities list not available')

        # Populate
        self.area_admin_0.addItems(sorted(self.admin_bounds_key.keys()))
        self.populate_admin_1()
        self.populate_cities()
        self.area_admin_0.currentIndexChanged.connect(self.populate_admin_1)
        self.area_admin_0.currentIndexChanged.connect(self.populate_cities)
        self.area_admin_0.currentIndexChanged.connect(self.generate_name_setting)

        self.secondLevel_area_admin_1.currentIndexChanged.connect(self.generate_name_setting)
        self.secondLevel_city.currentIndexChanged.connect(self.generate_name_setting)
        self.area_frompoint_point_x.textChanged.connect(self.generate_name_setting)
        self.area_frompoint_point_y.textChanged.connect(self.generate_name_setting)
        self.area_fromfile_file.textChanged.connect(self.generate_name_setting)
        self.buffer_size_km.valueChanged.connect(self.generate_name_setting)
        self.checkbox_buffer.toggled.connect(self.generate_name_setting)

        self.area_fromfile_browse.clicked.connect(self.open_vector_browse)
        self.area_fromadmin.clicked.connect(self.area_type_toggle)
        self.area_fromfile.clicked.connect(self.area_type_toggle)

        self.radioButton_secondLevel_region.clicked.connect(self.radioButton_secondLevel_toggle)
        self.radioButton_secondLevel_city.clicked.connect(self.radioButton_secondLevel_toggle)

        icon = QIcon(QPixmap(':/plugins/LDMP/icons/map-marker.svg'))
        self.area_frompoint_choose_point.setIcon(icon)
        self.area_frompoint_choose_point.clicked.connect(self.point_chooser)
        # TODO: Set range to only accept valid coordinates for current map coordinate system
        self.area_frompoint_point_x.setValidator(QDoubleValidator())
        # TODO: Set range to only accept valid coordinates for current map coordinate system
        self.area_frompoint_point_y.setValidator(QDoubleValidator())
        self.area_frompoint.clicked.connect(self.area_type_toggle)

        # Setup point chooser
        self.choose_point_tool = QgsMapToolEmitPoint(self.canvas)
        self.choose_point_tool.canvasClicked.connect(self.set_point_coords)

        self.load_settings()
        self.generate_name_setting()

    def load_settings(self):

        buffer_checked = self.settings.value("trends_earth/region_of_interest/buffer_checked", False, type=bool)
        area_from_option = self.settings.value("trends_earth/region_of_interest/chosen_method", None)

        if area_from_option == 'country_region' or \
                area_from_option == 'country_city':
            self.area_fromadmin.setChecked(True)
        elif area_from_option == 'point':
            self.area_frompoint.setChecked(True)
        elif area_from_option == 'vector_layer':
            self.area_fromfile.setChecked(True)
        self.area_frompoint_point_x.setText(self.settings.value("trends_earth/region_of_interest/point/x", None))
        self.area_frompoint_point_y.setText(self.settings.value("trends_earth/region_of_interest/point/y", None))
        self.area_fromfile_file.setText(self.settings.value("trends_earth/region_of_interest/vector_file", None))
        self.area_type_toggle()

        admin_0 = self.settings.value("trends_earth/region_of_interest/country/country_name", None)
        if admin_0:
            self.area_admin_0.setCurrentIndex(self.area_admin_0.findText(admin_0))
            self.populate_admin_1()

        area_from_option_secondLevel = self.settings.value("trends_earth/region_of_interest/chosen_method", None)
        if area_from_option_secondLevel == 'country_region':
            self.radioButton_secondLevel_region.setChecked(True)
        elif area_from_option_secondLevel == 'country_city':
            self.radioButton_secondLevel_city.setChecked(True)
        self.radioButton_secondLevel_toggle()

        secondLevel_area_admin_1 = self.settings.value("trends_earth/region_of_interest/country/region_name", None)
        if secondLevel_area_admin_1:
            self.secondLevel_area_admin_1.setCurrentIndex(
                self.secondLevel_area_admin_1.findText(secondLevel_area_admin_1))
        secondLevel_city = self.settings.value("trends_earth/region_of_interest/country/city_name", None)

        if secondLevel_city:
            self.populate_cities()
            self.secondLevel_city.setCurrentIndex(self.secondLevel_city.findText(secondLevel_city))

        buffer_size = self.settings.value("trends_earth/region_of_interest/buffer_size", None)
        if buffer_size:
            self.buffer_size_km.setValue(float(buffer_size))
        self.checkbox_buffer.setChecked(buffer_checked)

        self.area_settings_name.setText(
            self.settings.value("trends_earth/region_of_interest/area_settings_name", '')
        )

    def populate_cities(self):
        self.secondLevel_city.clear()
        adm0_a3 = self.admin_bounds_key[self.area_admin_0.currentText()]['code']
        self.current_cities_key = {value['name_en']: key for key, value in self.cities[adm0_a3].items()}
        self.secondLevel_city.addItems(sorted(self.current_cities_key.keys()))

    def populate_admin_1(self):
        self.secondLevel_area_admin_1.clear()
        self.secondLevel_area_admin_1.addItems(['All regions'])
        self.secondLevel_area_admin_1.addItems(
            sorted(self.admin_bounds_key[self.area_admin_0.currentText()]['admin1'].keys()))

    def area_type_toggle(self):
        # if self.area_frompoint.isChecked():
        #     self.area_fromfile.setChecked(not self.area_frompoint.isChecked())
        #     self.area_fromadmin.setChecked(not self.area_frompoint.isChecked())

        self.area_frompoint_point_x.setEnabled(self.area_frompoint.isChecked())
        self.area_frompoint_point_y.setEnabled(self.area_frompoint.isChecked())
        self.area_frompoint_choose_point.setEnabled(self.area_frompoint.isChecked())

        self.area_admin_0.setEnabled(self.area_fromadmin.isChecked())
        self.first_level_label.setEnabled(self.area_fromadmin.isChecked())
        self.second_level.setEnabled(self.area_fromadmin.isChecked())
        self.label_disclaimer.setEnabled(self.area_fromadmin.isChecked())

        self.area_fromfile_file.setEnabled(self.area_fromfile.isChecked())
        self.area_fromfile_browse.setEnabled(self.area_fromfile.isChecked())
        self.generate_name_setting()

    def radioButton_secondLevel_toggle(self):
        self.secondLevel_area_admin_1.setEnabled(self.radioButton_secondLevel_region.isChecked())
        self.secondLevel_city.setEnabled(not self.radioButton_secondLevel_region.isChecked())
        self.generate_name_setting()

    def point_chooser(self):
        log("Choosing point from canvas...")
        self.canvas.setMapTool(self.choose_point_tool)
        self.window().hide()
        QtWidgets.QMessageBox.critical(None, self.tr("Point chooser"), self.tr("Click the map to choose a point."))

    def generate_name_setting(self):
        if self.area_fromadmin.isChecked():
            if self.radioButton_secondLevel_region.isChecked():
                name = "{}-{}".format(
                    self.area_admin_0.currentText().lower().replace(' ', '-'),
                    self.secondLevel_area_admin_1.currentText().lower().replace(' ', '-')
                )
            else:
                name = "{}-{}".format(
                    self.area_admin_0.currentText().lower().replace(' ', '-'),
                    self.secondLevel_city.currentText().lower().replace(' ', '-')
                )
        elif self.area_frompoint.isChecked():
            if self.area_frompoint_point_x.text() is not '' and \
                    self.area_frompoint_point_y.text() is not '':
                name = "pt-lon{:.3f}lat{:.3f}".format(
                    float(self.area_frompoint_point_x.text()),
                    float(self.area_frompoint_point_y.text())
                )
            else:
                return
        elif self.area_fromfile.isChecked():
            if self.area_fromfile_file.text() is not '':
                layer = QgsVectorLayer(
                    self.area_fromfile_file.text(),
                    "area",
                    "ogr")
                if layer.isValid():
                    centroid = layer.extent().center()
                    # Store point in EPSG:4326 crs
                    coord_transform = QgsCoordinateTransform(
                        layer.sourceCrs(),
                        QgsCoordinateReferenceSystem(4326),
                        QgsProject.instance())
                    point = coord_transform.transform(centroid)
                    name = "shape-lon{:.3f}lat{:.3f}".format(
                        point.x(),
                        point.y()
                    )
                else:
                    return
            else:
                return
        if self.checkbox_buffer.isChecked():
            name = "{}-buffer-{:.3f}".format(
                name,
                self.buffer_size_km.value()
            )
        self.area_settings_name.setText(name)

    def set_point_coords(self, point, button):
        log("Set point coords")
        # TODO: Show a messagebar while tool is active, and then remove the bar when a point is chosen.
        self.point = point
        # Disable the choose point tool
        self.canvas.setMapTool(QgsMapToolPan(self.canvas))
        # Don't reset_tab_on_show as it would lead to return to first tab after
        # using the point chooser
        self.window().reset_tab_on_showEvent = False
        self.window().show()
        self.window().reset_tab_on_showEvent = True
        self.point = self.canvas.getCoordinateTransform().toMapCoordinates(self.canvas.mouseLastXY())

        # Store point in EPSG:4326 crs
        transform_instance = QgsCoordinateTransform(
            QgsProject.instance().crs(),
            QgsCoordinateReferenceSystem(4326),
            QgsProject.instance())
        transformed_point = transform_instance.transform(self.point)

        log("Chose point: {}, {}.".format(transformed_point.x(), transformed_point.y()))
        self.area_frompoint_point_x.setText("{:.8f}".format(transformed_point.x()))
        self.area_frompoint_point_y.setText("{:.8f}".format(transformed_point.y()))

    def open_vector_browse(self):
        initial_path = self.settings.value("trends_earth/input_shapefile", None)
        if not initial_path:
            initial_path = self.settings.value("trends_earth/input_shapefile_dir", None)
        if not initial_path:
            initial_path = str(Path.home())

        vector_file, _ = QtWidgets.QFileDialog.getOpenFileName(self,
                                                               self.tr('Select a file defining the area of interest'),
                                                               initial_path,
                                                               self.tr('Vector file (*.shp *.kml *.kmz *.geojson)'))
        if vector_file:
            if os.access(vector_file, os.R_OK):
                self.vector_file = vector_file
                self.area_fromfile_file.setText(vector_file)
                return True
            else:
                QtWidgets.QMessageBox.critical(None,
                                               self.tr("Error"),
                                               self.tr(u"Cannot read {}. Choose a different file.".format(vector_file)))
                return False
        else:
            return False

    def save_settings(self):

        if self.area_fromadmin.isChecked():
            self.settings.setValue(
                "trends_earth/region_of_interest/country/country_name",
                self.area_admin_0.currentText())
        else:
            self.settings.setValue(
                "trends_earth/region_of_interest/country/country_name",
                None)
        if self.radioButton_secondLevel_region.isChecked():
            self.settings.setValue("trends_earth/region_of_interest/country/region_name",
                                   self.secondLevel_area_admin_1.currentText())
        else:
            self.settings.setValue("trends_earth/region_of_interest/country/region_name",
                                   None)
        if self.radioButton_secondLevel_city.isChecked():
            self.settings.setValue(
                "trends_earth/region_of_interest/country/city_name",
                self.secondLevel_city.currentText())
        else:
            self.settings.setValue(
                "trends_earth/region_of_interest/country/city_name",
                None)
        if self.area_frompoint.isChecked():
            self.settings.setValue(
                "trends_earth/region_of_interest/point/x",
                self.area_frompoint_point_x.text())
            self.settings.setValue(
                "trends_earth/region_of_interest/point/y",
                self.area_frompoint_point_y.text())
        else:
            self.settings.setValue("trends_earth/region_of_interest/point/x", None)
            self.settings.setValue("trends_earth/region_of_interest/point/y", None)
        if self.area_fromfile.isChecked():
            self.settings.setValue(
                "trends_earth/region_of_interest/vector_layer",
                self.area_fromfile_file.text())
        else:
            self.settings.setValue(
                "trends_earth/region_of_interest/vector_layer",
                None)

        self.settings.setValue(
            "trends_earth/region_of_interest/buffer_checked",
            self.checkbox_buffer.isChecked())
        self.settings.setValue(
            "trends_earth/region_of_interest/buffer_size",
            self.buffer_size_km.value())

        area_value = None
        if self.area_frompoint.isChecked():
            area_value = 'point'
        elif self.area_fromadmin.isChecked():
            if self.radioButton_secondLevel_city.isChecked():
                area_value = 'country_city'
            else:
                area_value = 'country_region'
        elif self.area_fromfile.isChecked():
            area_value = 'vector_layer'

        if area_value is not None:
            self.settings.setValue("trends_earth/region_of_interest/chosen_method", area_value)

        if self.vector_file is not None:
            self.settings.setValue("trends_earth/input_shapefile", self.vector_file)
            self.settings.setValue("trends_earth/input_shapefile_dir", os.path.dirname(self.vector_file))

        if self.current_cities_key is not None:
            self.settings.setValue("trends_earth/region_of_interest/current_cities_key", self.current_cities_key)

        self.settings.setValue("trends_earth/region_of_interest/area_settings_name",
                               self.area_settings_name.text())


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
                                              self.tr(
                                                  u"User registered. Your password has been emailed to {}. Then set it in {} configuration".format(
                                                      self.email.text(), AUTH_CONFIG_NAME)))

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
                    <a href= 'https://groups.google.com/forum/#!forum/trends_earth_users/join'>Join the Trends.Earth Users google groups<a/></p><p> Make sure to join the google groups for the Trends.Earth users to keep up with updates and Q&A about the tool, methods, and datasets in support of Sustainable Development Goals monitoring.</p>""").format(
                                                  self.email.text()))
            settings.setValue("LDMP/jobs_cache", None)
            self.done(QtWidgets.QDialog.Accepted)
            self.ok = True


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
                                               self.tr(
                                                   u"Are you sure you want to reset the password for {}? Your new password will be emailed to you.".format(
                                                       self.email.text())),
                                               QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No)

        if reply == QtWidgets.QMessageBox.Yes:
            resp = recover_pwd(self.email.text())
            if resp:
                self.close()
                QtWidgets.QMessageBox.information(None,
                                                  self.tr("Success"),
                                                  self.tr(
                                                      u"The password has been reset for {}. Check your email for the new password, and then return to Trends.Earth to enter it.").format(
                                                      self.email.text()))
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


class WidgetSettingsAdvanced(QtWidgets.QWidget, Ui_WidgetSettingsAdvanced):
    def __init__(self, parent=None):
        super(WidgetSettingsAdvanced, self).__init__(parent)

        self.setupUi(self)

        self.binaries_browse_button.clicked.connect(self.binary_folder_browse)
        self.binaries_download_button.clicked.connect(self.binaries_download)
        self.debug_checkbox.clicked.connect(self.debug_toggle)
        self.binaries_checkbox.clicked.connect(self.binaries_toggle)
        self.qgsFileWidget_base_directory.fileChanged.connect(self.base_directory_changed)
        self.pushButton_open_base_directory.clicked.connect(self.open_base_directory)

        # Flag that can be used to indicate if binary state has changed (i.e.
        # if new binaries have been downloaded)
        self.binary_state_changed = False

    def closeEvent(self, event):
        super(WidgetSettingsAdvanced, self).closeEvent(event)
        if self.binaries_checkbox.isChecked() != self.binaries_checkbox_initial or self.binary_state_changed:
            QtWidgets.QMessageBox.warning(None,
                                          self.tr("Warning"),
                                          self.tr("You must restart QGIS for these changes to take effect."))

    def showEvent(self, event):
        super(WidgetSettingsAdvanced, self).showEvent(event)

        self.debug_checkbox.setChecked(QSettings().value("trends_earth/advanced/debug", False, type=bool))

        binaries_checked = QSettings().value("trends_earth/advanced/binaries_enabled", False, type=bool)
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

        binaries_folder = QSettings().value("trends_earth/advanced/binaries_folder", None)
        if binaries_folder is not None:
            self.binaries_folder.setText(binaries_folder)

        self.binaries_checkbox_initial = binaries_checked
        self.binaries_checkbox.setChecked(binaries_checked)
        self.binaries_toggle()

        base_data_directory = QSettings().value(
            "trends_earth/advanced/base_data_directory",
            str(Path.home() / "trends_earth_data")
        )
        self.qgsFileWidget_base_directory.setFilePath(base_data_directory)

    def base_directory_changed(self, new_base_directory):
        if not new_base_directory:
            # TODO: change to MessageBar().get()
            iface.messageBar().pushWarning('Trends.Earth', self.tr('No base data directory set'))
            return

        try:
            if not os.path.exists(new_base_directory):
                os.makedirs(new_base_directory)
        except PermissionError:
            # TODO: change to MessageBar().get()
            iface.messageBar().pushCritical('Trends.Earth',
                                            self.tr("Unable to write to {}. Try a different folder.".format(
                                                new_base_directory)))
            return

        QSettings().setValue("trends_earth/advanced/base_data_directory", str(new_base_directory))

    def open_base_directory(self):
        base_data_directory = QSettings().value("trends_earth/advanced/base_data_directory", None)
        openFolder(base_data_directory)

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
                                           self.tr(
                                               "Unable to write to {}. Choose a different folder.".format(out_folder)))
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

        if not downloads:
            return None

        try:
            with zipfile.ZipFile(os.path.join(out_folder, zip_filename), 'r') as zf:
                zf.extractall(out_folder)
        except PermissionError:
            QtWidgets.QMessageBox.critical(None,
                                           self.tr("Error"),
                                           self.tr(
                                               "Unable to write to {}. Check that you have permissions to write to this folder, and that you are not trying to overwrite the binaries that you currently have loaded in QGIS.".format(
                                                   out_folder)))
            return None
        except FileNotFoundError:
            QtWidgets.QMessageBox.critical(None,
                                       self.tr("Error"),
                                       self.tr("Unable to read binaries from {}. Check that binaries were downloaded successfully.".format(out_folder)))
            return None
        
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
        QSettings().setValue("trends_earth/advanced/binaries_enabled", str(state))
        self.binaries_folder.setEnabled(state)
        self.binaries_browse_button.setEnabled(state)
        self.binaries_download_button.setEnabled(state)
        self.binaries_label.setEnabled(state)

    def debug_toggle(self):
        QSettings().setValue("trends_earth/advanced/debug", str(self.debug_checkbox.isChecked()))

    def binary_folder_browse(self):
        initial_path = QSettings().value("trends_earth/advanced/binaries_folder", None)
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
                                               self.tr(
                                                   u"Choose a different folder - cannot install binaries within the Trends.Earth QGIS plugin installation folder.".format(
                                                       plugin_folder)))
                return False
            if os.access(folder, os.W_OK):
                QSettings().setValue("trends_earth/advanced/binaries_folder", folder)
                self.binaries_folder.setText(folder)
                self.binary_state_changed = True
                return True
            else:
                QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                               self.tr(u"Cannot read {}. Choose a different folder.".format(folder)))
                return False
        else:
            return False
