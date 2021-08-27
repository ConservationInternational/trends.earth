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
import zipfile
import typing
from pathlib import Path

from PyQt5 import (
    QtCore,
    QtGui,
    QtWidgets,
)
import qgis.core
import qgis.gui
from qgis.utils import iface

from . import (
    __version__,
    api,
    auth,
    binaries_available,
    openFolder,
    download,
)
from .conf import (
    Setting,
    settings_manager,
)
from .jobs.manager import job_manager
from .gui.DlgSettings import Ui_DlgSettings
from .gui.DlgSettingsEditForgotPassword import Ui_DlgSettingsEditForgotPassword
from .gui.DlgSettingsEditUpdate import Ui_DlgSettingsEditUpdate
from .gui.DlgSettingsLogin import Ui_DlgSettingsLogin
from .gui.DlgSettingsRegister import Ui_DlgSettingsRegister
from .gui.WidgetSelectArea import Ui_WidgetSelectArea
from .gui.WidgetSettingsAdvanced import Ui_WidgetSettingsAdvanced
from .logger import log

settings = QtCore.QSettings()


def tr(message):
    return QtCore.QCoreApplication.translate("tr_settings", message)

        
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


def _get_user_email(auth_setup, warn=True):
    '''get user email for a particular service from authConfig'''
    authConfig = auth.get_auth_config(
        auth_setup,
        warn=warn
    )
    if not authConfig:
        return None

    email = authConfig.config('username')
    if warn and email is None:
        QtWidgets.QMessageBox.critical(
            None,
            tr("Error"),
            tr("Please setup access to {auth_setup.name} before "
               "using this function.")
        )
        return None
    else:
        return email


class DlgSettings(QtWidgets.QDialog, Ui_DlgSettings):
    message_bar: qgis.gui.QgsMessageBar

    def __init__(self, parent=None):
        super(DlgSettings, self).__init__(parent)

        self.setupUi(self)
        self.message_bar = qgis.gui.QgsMessageBar(self)
        self.layout().insertWidget(0, self.message_bar)

        # add subcomponent widgets
        self.widgetSettingsAdvanced = WidgetSettingsAdvanced(
            message_bar=self.message_bar)
        self.verticalLayout_advanced.layout().insertWidget(
            0, self.widgetSettingsAdvanced)

        # set Dialog UIs
        self.dlg_settings_register = DlgSettingsRegister()
        self.dlg_settings_login = DlgSettingsLogin()

        self.dlg_settings_register.authConfigInitialised.connect(
            self.selectDefaultAuthConfiguration)

        self.pushButton_register.clicked.connect(self.register)
        self.pushButton_login.clicked.connect(self.login)

        self.pushButton_update_profile.clicked.connect(self.update_profile)
        self.pushButton_delete_user.clicked.connect(self.delete)
        self.pushButton_forgot_pwd.clicked.connect(self.forgot_pwd)

        self.buttonBox.accepted.connect(self.close)
        self.settings = qgis.core.QgsSettings()

        self.area_widget = AreaWidget()
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.area_widget)

        self.region_of_interest.setLayout(layout)

        # load gui default value from settings
        self.reloadAuthConfigurations()

    def closeEvent(self, event):
        self.widgetSettingsAdvanced.closeEvent(event)
        self.area_widget.closeEvent(event)
        super().closeEvent(event)

    def reloadAuthConfigurations(self):
        authConfigId = settings.value(
            f"trends_earth/{auth.TE_API_AUTH_SETUP.key}",
            None
        )
        if not authConfigId:
            self.message_bar.pushCritical(
                'Trends.Earth',
                self.tr('Please register in order to use Trends.Earth')
            )
            return
        configs = qgis.core.QgsApplication.authManager().availableAuthMethodConfigs()
        if authConfigId not in configs.keys():
            QtCore.QSettings().setValue(
                f"trends_earth/{auth.TE_API_AUTH_SETUP.key}",
                None
            )

    def selectDefaultAuthConfiguration(self, authConfigId):
        self.reloadAuthConfigurations()

    def register(self):
        self.dlg_settings_register.exec_()
        #
        # if not authConfigId:
        #     self.message_bar.pushCritical(
        #         'Trends.Earth',
        #         self.tr('Please register in order to use Trends.Earth')
        #     )
        #
        #     return
        #
    def login(self):
        self.dlg_settings_login.exec_()

    def forgot_pwd(self):
        dlg_settings_edit_forgot_password = DlgSettingsEditForgotPassword()
        dlg_settings_edit_forgot_password.exec_()

    def update_profile(self):
        user = api.get_user()

        if not user:
            return
        dlg_settings_edit_update = DlgSettingsEditUpdate(user)
        dlg_settings_edit_update.exec_()

    def delete(self):
        email = _get_user_email(auth.TE_API_AUTH_SETUP)

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
            resp = api.delete_user(email)

            if resp:
                QtWidgets.QMessageBox.information(
                    None,
                    self.tr("Success"),
                    tr(f'Trends.Earth user {email} deleted.')
                )
                # remove currently used config (as set in QSettings) and 
                # trigger GUI
                auth.remove_current_auth_config(auth.TE_API_AUTH_SETUP)
                self.reloadAuthConfigurations()
                # self.authConfigUpdated.emit()

    def accept(self):
        self.area_widget.save_settings()
        self.widgetSettingsAdvanced.update_settings()
        super().accept()


class AreaWidget(QtWidgets.QWidget, Ui_WidgetSelectArea):
    admin_bounds_key: typing.Dict[str, download.Country]
    cities: typing.Dict[str, typing.Dict[str, download.City]]

    def __init__(self, parent=None):
        super(AreaWidget, self).__init__(parent)

        self.setupUi(self)

        self.canvas = iface.mapCanvas()
        self.vector_file = None
        self.current_cities_key = None

        self.admin_bounds_key = download.get_admin_bounds()

        if not self.admin_bounds_key:
            raise ValueError('Admin boundaries not available')

        self.cities = download.get_cities()

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

        icon = QtGui.QIcon(QtGui.QPixmap(':/plugins/LDMP/icons/map-marker.svg'))
        self.area_frompoint_choose_point.setIcon(icon)
        self.area_frompoint_choose_point.clicked.connect(self.point_chooser)
        # TODO: Set range to only accept valid coordinates for current map coordinate system
        self.area_frompoint_point_x.setValidator(QtGui.QDoubleValidator())
        # TODO: Set range to only accept valid coordinates for current map coordinate system
        self.area_frompoint_point_y.setValidator(QtGui.QDoubleValidator())
        self.area_frompoint.clicked.connect(self.area_type_toggle)

        # Setup point chooser
        self.choose_point_tool = qgis.gui.QgsMapToolEmitPoint(self.canvas)
        self.choose_point_tool.canvasClicked.connect(self.set_point_coords)

        self.load_settings()
        self.generate_name_setting()

    def load_settings(self):
        area_from_option = settings_manager.get_value(Setting.AREA_FROM_OPTION)

        if area_from_option == 'country_region' or area_from_option == 'country_city':
            self.area_fromadmin.setChecked(True)
        elif area_from_option == 'point':
            self.area_frompoint.setChecked(True)
        elif area_from_option == 'vector_layer':
            self.area_fromfile.setChecked(True)
        self.area_frompoint_point_x.setText(
            str(settings_manager.get_value(Setting.POINT_X)))
        self.area_frompoint_point_y.setText(
            str(settings_manager.get_value(Setting.POINT_Y)))
        self.area_fromfile_file.setText(
            settings_manager.get_value(Setting.VECTOR_FILE_PATH))
        self.area_type_toggle()
        admin_0 = settings_manager.get_value(Setting.COUNTRY_NAME)

        if admin_0:
            self.area_admin_0.setCurrentIndex(self.area_admin_0.findText(admin_0))
            self.populate_admin_1()

        if area_from_option == 'country_region':
            self.radioButton_secondLevel_region.setChecked(True)
        elif area_from_option == 'country_city':
            self.radioButton_secondLevel_city.setChecked(True)
        self.radioButton_secondLevel_toggle()

        secondLevel_area_admin_1 = settings_manager.get_value(Setting.REGION_NAME)

        if secondLevel_area_admin_1:
            self.secondLevel_area_admin_1.setCurrentIndex(
                self.secondLevel_area_admin_1.findText(secondLevel_area_admin_1))
        secondLevel_city = settings_manager.get_value(Setting.CITY_NAME)

        if secondLevel_city:
            self.populate_cities()
            self.secondLevel_city.setCurrentIndex(self.secondLevel_city.findText(secondLevel_city))
        buffer_size = settings_manager.get_value(Setting.BUFFER_SIZE)

        if buffer_size:
            self.buffer_size_km.setValue(float(buffer_size))
        buffer_checked = settings_manager.get_value(Setting.BUFFER_CHECKED)
        self.checkbox_buffer.setChecked(buffer_checked)
        self.area_settings_name.setText(settings_manager.get_value(Setting.AREA_NAME))

    def populate_cities(self):
        self.secondLevel_city.clear()
        country_code = self.admin_bounds_key[self.area_admin_0.currentText()].code
        self.current_cities_key = {}

        for wof_id, city in self.cities[country_code].items():
            self.current_cities_key[city.name_en] = wof_id
        self.secondLevel_city.addItems(sorted(self.current_cities_key.keys()))

    def populate_admin_1(self):
        self.secondLevel_area_admin_1.clear()
        self.secondLevel_area_admin_1.addItems(['All regions'])
        self.secondLevel_area_admin_1.addItems(
            sorted(
                self.admin_bounds_key[
                    self.area_admin_0.currentText()].level1_regions.keys()
            )
        )

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
                layer = qgis.core.QgsVectorLayer(
                    self.area_fromfile_file.text(),
                    "area",
                    "ogr")

                if layer.isValid():
                    centroid = layer.extent().center()
                    # Store point in EPSG:4326 crs
                    coord_transform = qgis.core.QgsCoordinateTransform(
                        layer.sourceCrs(),
                        qgis.core.QgsCoordinateReferenceSystem(4326),
                        qgis.core.QgsProject.instance())
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
        self.canvas.setMapTool(qgis.gui.QgsMapToolPan(self.canvas))
        # Don't reset_tab_on_show as it would lead to return to first tab after
        # using the point chooser
        self.window().reset_tab_on_showEvent = False
        self.window().show()
        self.window().reset_tab_on_showEvent = True
        self.point = self.canvas.getCoordinateTransform().toMapCoordinates(self.canvas.mouseLastXY())

        # Store point in EPSG:4326 crs
        transform_instance = qgis.core.QgsCoordinateTransform(
            qgis.core.QgsProject.instance().crs(),
            qgis.core.QgsCoordinateReferenceSystem(4326),
            qgis.core.QgsProject.instance())
        transformed_point = transform_instance.transform(self.point)

        log("Chose point: {}, {}.".format(transformed_point.x(), transformed_point.y()))
        self.area_frompoint_point_x.setText("{:.8f}".format(transformed_point.x()))
        self.area_frompoint_point_y.setText("{:.8f}".format(transformed_point.y()))

    def open_vector_browse(self):
        initial_path = settings_manager.get_value(Setting.VECTOR_FILE_PATH)

        if not initial_path:
            initial_path = settings_manager.get_value(Setting.VECTOR_FILE_DIR)

        if not initial_path:
            initial_path = str(Path.home())

        vector_file, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr('Select a file defining the area of interest'),
            initial_path,
            self.tr('Vector file (*.shp *.kml *.kmz *.geojson)')
        )

        if vector_file:
            if os.access(vector_file, os.R_OK):
                self.vector_file = vector_file
                self.area_fromfile_file.setText(vector_file)

                return True
            else:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(
                        u"Cannot read {}. Choose a different file.".format(vector_file))
                )

                return False
        else:
            return False

    def save_settings(self):
        country_name = ""
        region_name = ""
        city_name = ""
        point = (0, 0)
        vector_path = ""

        if self.area_fromadmin.isChecked():
            country_name = self.area_admin_0.currentText()

            if self.radioButton_secondLevel_region.isChecked():
                area_name = "country_region"
                region_name = self.secondLevel_area_admin_1.currentText()
            else:
                area_name = "country_city"
                city_name = self.secondLevel_city.currentText()
        elif self.area_frompoint.isChecked():
            area_name = "point"
            point = (
                self.area_frompoint_point_x.text(),
                self.area_frompoint_point_y.text(),
            )
        elif self.area_fromfile.isChecked():
            area_name = "vector_layer"
            vector_path = self.area_fromfile_file.text()
        else:
            raise RuntimeError("Invalid area type")
        settings_manager.write_value(Setting.AREA_FROM_OPTION, area_name)
        settings_manager.write_value(Setting.COUNTRY_NAME, country_name)
        settings_manager.write_value(Setting.REGION_NAME, region_name)
        settings_manager.write_value(Setting.CITY_NAME, city_name)
        settings_manager.write_value(Setting.POINT_X, point[0])
        settings_manager.write_value(Setting.POINT_Y, point[1])
        settings_manager.write_value(Setting.VECTOR_FILE_PATH, vector_path)
        settings_manager.write_value(
            Setting.VECTOR_FILE_DIR, str(Path(vector_path).parent))
        settings_manager.write_value(
            Setting.BUFFER_CHECKED, self.checkbox_buffer.isChecked())
        settings_manager.write_value(
            Setting.BUFFER_SIZE, self.buffer_size_km.value())
        settings_manager.write_value(
            Setting.AREA_NAME, self.area_settings_name.text())

        if self.current_cities_key is not None:
            settings_manager.write_value(Setting.CITY_KEY, self.current_cities_key)
        log("area settings have been saved")


class DlgSettingsRegister(QtWidgets.QDialog, Ui_DlgSettingsRegister):
    authConfigInitialised = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super(DlgSettingsRegister, self).__init__(parent)

        self.setupUi(self)

        self.admin_bounds_key = download.get_admin_bounds()
        self.country.addItems(sorted(self.admin_bounds_key.keys()))

        self.buttonBox.accepted.connect(self.register)
        self.buttonBox.rejected.connect(self.close)

    def register(self):
        if not self.email.text():
            QtWidgets.QMessageBox.critical(None,
                                           self.tr("Error"),
                                           self.tr("Enter your email address."))

            return
        elif not self.name.text():
            QtWidgets.QMessageBox.critical(None,
                                           self.tr("Error"),
                                           self.tr("Enter your name."))

            return
        elif not self.organization.text():
            QtWidgets.QMessageBox.critical(None,
                                           self.tr("Error"),
                                           self.tr("Enter your organization."))

            return
        elif not self.country.currentText():
            QtWidgets.QMessageBox.critical(None,
                                           self.tr("Error"),
                                           self.tr("Enter your country."))

            return

        resp = api.register(
            self.email.text(),
            self.name.text(),
            self.organization.text(),
            self.country.currentText()
        )

        if resp:
            self.close()
            QtWidgets.QMessageBox.information(
                None,
                self.tr("Success"),
                self.tr("User registered. Your password "
                        f"has been emailed to {self.email.text()}. "
                        "Enter that password in Trends.Earth settings "
                        "to finish setting up the plugin.")
            )

            # add a new auth conf that have to be completed with pwd
            authConfigId = auth.init_auth_config(
                auth.TE_API_AUTH_SETUP,
                email=self.email.text()
            )

            if authConfigId:
                self.authConfigInitialised.emit(authConfigId)
                return authConfigId
        else:
            return None


class DlgSettingsLogin(QtWidgets.QDialog, Ui_DlgSettingsLogin):
    def __init__(self, parent=None):
        super(DlgSettingsLogin, self).__init__(parent)

        self.setupUi(self)

        self.buttonBox.accepted.connect(self.login)
        self.buttonBox.rejected.connect(self.close)

        self.ok = False

    def showEvent(self, event):
        super(DlgSettingsLogin, self).showEvent(event)

        email = _get_user_email(auth.TE_API_AUTH_SETUP, warn=False)

        if email:
            self.email.setText(email)


    def login(self):
        if not self.email.text():
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Enter your email address.")
            )

            return
        elif not self.password.text():
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Enter your password.")
            )

            return

        if api.login_test(self.email.text(), self.password.text()):
            QtWidgets.QMessageBox.information(
                None,
                self.tr("Success"),
                self.tr(
                    'Logged in to the Trends.Earth server as '
                    f'{self.email.text()}.<html><p>Welcome to '
                    'Trends.Earth!<p/><p><a href= "'
                    'https://groups.google.com/forum/#!forum/trends_earth_users/join">Join '
                    'the Trends.Earth Users email group<a/></p><p> Make sure '
                    'to join the Trends.Earth users email group to keep up '
                    'with updates and Q&A about the tool, methods, and '
                    'datasets in support of Sustainable Development Goals '
                    'monitoring.')
            )
            auth.init_auth_config(
                auth.TE_API_AUTH_SETUP,
                self.email.text(),
                self.password.text()
            )
            self.ok = True
            self.close()


class DlgSettingsLoginLandPKS(QtWidgets.QDialog, Ui_DlgSettingsLogin):
    def __init__(self, parent=None):
        super(DlgSettingsLoginLandPKS, self).__init__(parent)

        self.setupUi(self)

        self.buttonBox.accepted.connect(self.login)
        self.buttonBox.rejected.connect(self.close)

        self.ok = False

    def showEvent(self, event):
        super(DlgSettingsLoginLandPKS, self).showEvent(event)

        email = _get_user_email(auth.LANDPKS_AUTH_SETUP, warn=False)

        if email:
            self.email.setText(email)


    def login(self):
        if not self.email.text():
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Enter your email address.")
            )

            return
        elif not self.password.text():
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Enter your password.")
            )

            return
        
        #######################################
        #######################################
        # TODO: Do something here to authorize
        # access to LandPKS...
        #######################################
        #######################################

        # IF the authorization works, run the below line - otherwise print an 
        # error message telling the user how to fix it and return None
        auth.init_auth_config(
            auth.LANDPKS_AUTH_SETUP,
            self.email.text(),
            self.password.text()
        )

        QtWidgets.QMessageBox.information(
            None,
            self.tr("Success"),
            self.tr(
                'Successfully setup login to the LandPKS server as '
                f'{self.email.text()}.'
            )
        )

        self.ok = True
        self.close()


class DlgSettingsEditForgotPassword(
    QtWidgets.QDialog,
    Ui_DlgSettingsEditForgotPassword
):
    def __init__(self, parent=None):
        super(DlgSettingsEditForgotPassword, self).__init__(parent)

        self.setupUi(self)

        self.buttonBox.accepted.connect(self.reset_password)
        self.buttonBox.rejected.connect(self.close)

        self.ok = False

    def showEvent(self, event):
        super(DlgSettingsEditForgotPassword, self).showEvent(event)

        email = _get_user_email(auth.TE_API_AUTH_SETUP, warn=False)

        if email:
            self.email.setText(email)

    def reset_password(self):
        if not self.email.text():
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Enter your email address to reset your password.")
            )

            return

        reply = QtWidgets.QMessageBox.question(
            None,
            self.tr("Reset password?"),
            self.tr(
                "Are you sure you want to reset the password for "
                f"{self.email.text()}? Your new password will be emailed "
                "to you."),
            QtWidgets.QMessageBox.Yes,
            QtWidgets.QMessageBox.No
        )

        if reply == QtWidgets.QMessageBox.Yes:
            resp = api.recover_pwd(self.email.text())

            if resp:
                self.close()
                QtWidgets.QMessageBox.information(
                    None,
                    self.tr("Success"),
                    self.tr(
                        f"The password has been reset for {self.email.text()}. "
                        "Check your email for the new password, and then "
                        "return to Trends.Earth to enter it."
                    )
                )
                self.ok = True


class DlgSettingsEditUpdate(QtWidgets.QDialog, Ui_DlgSettingsEditUpdate):
    def __init__(self, user, parent=None):
        super(DlgSettingsEditUpdate, self).__init__(parent)

        self.setupUi(self)

        self.user = user

        self.admin_bounds_key = download.get_admin_bounds()

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

        resp = api.update_user(
            self.email.text(),
            self.name.text(),
            self.organization.text(),
            self.country.currentText()
        )

        if resp:
            QtWidgets.QMessageBox.information(None, self.tr("Saved"),
                                              self.tr(u"Updated information for {}.").format(self.email.text()))
            self.close()
            self.ok = True


class WidgetSettingsAdvanced(QtWidgets.QWidget, Ui_WidgetSettingsAdvanced):
    _settings_base_path: str = "trends_earth/advanced"
    _qgis_settings = qgis.core.QgsSettings()

    binaries_gb = QtWidgets.QGroupBox
    binaries_dir_le = QtWidgets.QLineEdit
    debug_checkbox: QtWidgets.QCheckBox
    polling_frequency_gb: QtWidgets.QGroupBox
    polling_frequency_sb: QtWidgets.QSpinBox
    download_remote_datasets_chb: QtWidgets.QCheckBox
    qgsFileWidget_base_directory: qgis.gui.QgsFileWidget

    message_bar: qgis.gui.QgsMessageBar

    def __init__(self, message_bar: qgis.gui.QgsMessageBar, parent=None):
        super(WidgetSettingsAdvanced, self).__init__(parent)
        self.setupUi(self)

        self.message_bar = message_bar

        self.dlg_settings_login_landpks = DlgSettingsLoginLandPKS()

        self.pushButton_login_landpks.clicked.connect(self.login_landpks)
        self.binaries_browse_button.clicked.connect(self.binary_folder_browse)
        self.binaries_gb.toggled.connect(self.binaries_toggle)
        self.binaries_download_button.clicked.connect(self.binaries_download)
        self.qgsFileWidget_base_directory.fileChanged.connect(
            self.base_directory_changed)
        self.pushButton_open_base_directory.clicked.connect(self.open_base_directory)

        # Flag that can be used to indicate if binary state has changed (i.e.
        # if new binaries have been downloaded)
        self.binary_state_changed = False

    def closeEvent(self, event):
        super(WidgetSettingsAdvanced, self).closeEvent(event)

        if self.binaries_gb.isChecked() != self.binaries_checkbox_initial or self.binary_state_changed:
            QtWidgets.QMessageBox.warning(
                None,
                self.tr("Warning"),
                self.tr("You must restart QGIS for these changes to take effect.")
            )

    def update_settings(self):
        """Store the current value of each setting in QgsSettings"""
        log(f"poll remote: {self.polling_frequency_gb.isChecked()}")
        settings_manager.write_value(
            Setting.POLL_REMOTE, self.polling_frequency_gb.isChecked())
        settings_manager.write_value(
            Setting.REMOTE_POLLING_FREQUENCY, self.polling_frequency_sb.value())
        settings_manager.write_value(
            Setting.DOWNLOAD_RESULTS, self.download_remote_datasets_chb.isChecked())
        # TODO: save the current region of interest
        settings_manager.write_value(
            Setting.DEBUG, self.debug_checkbox.isChecked())
        settings_manager.write_value(
            Setting.BINARIES_ENABLED, self.binaries_gb.isChecked())
        settings_manager.write_value(
            Setting.BINARIES_DIR, self.binaries_dir_le.text())

        old_base_dir = settings_manager.get_value(Setting.BASE_DIR)
        new_base_dir = self.qgsFileWidget_base_directory.filePath()
        settings_manager.write_value(Setting.BASE_DIR, new_base_dir)

        if old_base_dir != new_base_dir:
            job_manager.clear_known_jobs()

    def login_landpks(self):
        self.dlg_settings_login_landpks.exec_()

    def show_settings(self):
        self.debug_checkbox.setChecked(settings_manager.get_value(Setting.DEBUG))
        self.binaries_dir_le.setText(
            settings_manager.get_value(Setting.BINARIES_DIR) or "")
        self.qgsFileWidget_base_directory.setFilePath(
            settings_manager.get_value(Setting.BASE_DIR) or "")
        self.polling_frequency_gb.setChecked(
            settings_manager.get_value(Setting.POLL_REMOTE))
        self.polling_frequency_sb.setValue(
            settings_manager.get_value(Setting.REMOTE_POLLING_FREQUENCY))
        self.download_remote_datasets_chb.setChecked(
            settings_manager.get_value(Setting.DOWNLOAD_RESULTS))

    def showEvent(self, event):
        super(WidgetSettingsAdvanced, self).showEvent(event)
        self.show_settings()
        binaries_checked = settings_manager.get_value(Setting.BINARIES_ENABLED)
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
        self.binaries_checkbox_initial = binaries_checked
        self.binaries_gb.setChecked(binaries_checked)
        self.binaries_toggle()

    def base_directory_changed(self, new_base_directory):
        if not new_base_directory:
            self.message_bar.pushWarning(
                'Trends.Earth', self.tr('No base data directory set'))

            return

        try:
            if not os.path.exists(new_base_directory):
                os.makedirs(new_base_directory)
        except PermissionError:
            self.message_bar.pushCritical(
                'Trends.Earth',
                self.tr("Unable to write to {}. Try a different folder.".format(
                    new_base_directory))
            )

            return

        settings_manager.write_value(Setting.BASE_DIR, str(new_base_directory))

    def open_base_directory(self):
        openFolder(self.qgsFileWidget_base_directory.filePath())

    def binaries_download(self):
        out_folder = os.path.join(self.binaries_dir_le.text())

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
        downloads = download.download_files([zip_url], out_folder)

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
        state = self.binaries_gb.isChecked()
        settings_manager.write_value(Setting.BINARIES_ENABLED, state)
        self.binaries_dir_le.setEnabled(state)
        self.binaries_browse_button.setEnabled(state)
        self.binaries_download_button.setEnabled(state)
        self.binaries_label.setEnabled(state)

    def binary_folder_browse(self):
        initial_path = self.binaries_dir_le.text()

        if not initial_path:
            initial_path = str(Path.home())

        folder_path = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            self.tr('Select folder containing Trends.Earth binaries'),
            initial_path
        )

        if folder_path:
            plugin_folder = os.path.normpath(
                os.path.realpath(os.path.dirname(__file__)))

            if is_subdir(folder_path, plugin_folder):
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(
                        "Choose a different folder - cannot install binaries within "
                        "the Trends.Earth QGIS plugin installation folder.")
                )

                return False

            if os.access(folder_path, os.W_OK):
                settings_manager.write_value(Setting.BINARIES_DIR, folder_path)
                self.binaries_dir_le.setText(folder_path)
                self.binary_state_changed = True

                return True
            else:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(f"Cannot read {folder_path!r}. Choose a different folder.")
                )

                return False
        else:
            return False
