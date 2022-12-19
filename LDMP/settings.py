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
import typing
import zipfile
from enum import auto
from enum import Flag
from pathlib import Path

import qgis.core
import qgis.gui
from qgis.gui import QgsOptionsPageWidget
from qgis.gui import QgsOptionsWidgetFactory
from qgis.PyQt import QtCore
from qgis.PyQt import QtGui
from qgis.PyQt import QtWidgets
from qgis.PyQt import uic
from qgis.PyQt.QtGui import QIcon
from qgis.utils import iface
from te_schemas.land_cover import LCClass

from . import __version__
from . import api
from . import auth
from . import binaries_available
from . import binaries_name
from . import conf
from . import download
from . import openFolder
from .conf import DOCK_TITLE
from .conf import DOCK_TITLE_OFFLINE
from .conf import OPTIONS_ICON
from .conf import OPTIONS_TITLE
from .conf import Setting
from .conf import settings_manager
from .conf import TR_ALL_REGIONS
from .jobs.manager import job_manager
from .lc_setup import get_default_esa_nesting
from .lc_setup import LccInfoUtils
from .lc_setup import LCClassInfo


Ui_DlgLandCoverRestore, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgLandCoverRestore.ui")
)
Ui_DlgSettings, _ = uic.loadUiType(str(Path(__file__).parent / "gui/DlgSettings.ui"))
Ui_DlgSettingsEditForgotPassword, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgSettingsEditForgotPassword.ui")
)
Ui_DlgSettingsEditUpdate, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgSettingsEditUpdate.ui")
)
Ui_DlgSettingsLogin, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgSettingsLogin.ui")
)
Ui_DlgSettingsRegister, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgSettingsRegister.ui")
)
Ui_WidgetSelectArea, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/WidgetSelectArea.ui")
)
Ui_WidgetSettingsAdvanced, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/WidgetSettingsAdvanced.ui")
)
Ui_WidgetSettingsReport, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/WidgetSettingsReport.ui")
)
Ui_WidgetLandCoverCustomClassesManager, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/WidgetLCClassManage.ui")
)
Ui_WidgetLandCoverCustomClassEditor, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/WidgetLCClassEditor.ui")
)


from .logger import log
from .utils import FileUtils

ICON_PATH = os.path.join(os.path.dirname(__file__), "icons")


settings = QtCore.QSettings()


class tr_settings(QtCore.QObject):
    def tr(txt):
        return QtCore.QCoreApplication.translate(self.__class__.__name__, txt)


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
    elif tail == "":
        return False
    else:
        return is_subdir(head, parent)


def _get_user_email(auth_setup, warn=True):
    """get user email for a particular service from authConfig"""
    authConfig = auth.get_auth_config(auth_setup, warn=warn)
    if not authConfig:
        return None

    email = authConfig.config("username")
    if warn and email is None:
        QtWidgets.QMessageBox.critical(
            None,
            tr_settings.tr("Error"),
            tr_settings.tr(
                "Please setup access to {auth_setup.name} before "
                "using this function."
            ),
        )
        return None
    else:
        return email


class TrendsEarthSettings(Ui_DlgSettings, QgsOptionsPageWidget):
    message_bar: qgis.gui.QgsMessageBar

    def __init__(self, dock_widget, parent=None):
        QgsOptionsPageWidget.__init__(self, parent)

        self.setupUi(self)
        self.message_bar = qgis.gui.QgsMessageBar(self)
        self.layout().insertWidget(0, self.message_bar)
        self.dock_widget = dock_widget

        # Add subcomponent widgets
        self.widgetSettingsAdvanced = WidgetSettingsAdvanced(
            self.groupBox, self.dock_widget, message_bar=self.message_bar
        )
        self.verticalLayout_advanced.layout().insertWidget(
            0, self.widgetSettingsAdvanced
        )

        # LC configuration
        lcc_panel_stack = qgis.gui.QgsPanelWidgetStack()
        self.lcc_manager = LandCoverCustomClassesManager(
            self.groupbox_lc_config,
            self.scroll_area,
            self.groupBox,
            self.region_of_interest,
            lcc_panel_stack,
            msg_bar=self.message_bar,
        )
        lcc_panel_stack.setMainPanel(self.lcc_manager)
        self.lcc_layout.layout().insertWidget(0, lcc_panel_stack)

        # Report settings
        self.widget_settings_report = WidgetSettingsReport(
            self, message_bar=self.message_bar
        )
        self.reports_layout.layout().insertWidget(0, self.widget_settings_report)

        # Set Dialog UIs
        self.dlg_settings_register = DlgSettingsRegister()
        self.dlg_settings_login = DlgSettingsLogin()

        self.dlg_settings_register.authConfigInitialised.connect(
            self.selectDefaultAuthConfiguration
        )

        self.pushButton_register.clicked.connect(self.register)
        self.pushButton_login.clicked.connect(self.login)

        self.pushButton_update_profile.clicked.connect(self.update_profile)
        self.pushButton_delete_user.clicked.connect(self.delete)
        self.pushButton_forgot_pwd.clicked.connect(self.forgot_pwd)

        self.groupbox_lc_config.collapsedStateChanged.connect(
            self.collapsed_state_changed
        )

        self.settings = qgis.core.QgsSettings()

        self.area_widget = AreaWidget()
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.area_widget)

        self.region_of_interest.setLayout(layout)

        # Load gui default value from settings
        self.reloadAuthConfigurations()

    def apply(self):
        """This is called on OK click in the QGIS options panel."""

        old_base_dir = conf.settings_manager.get_value(conf.Setting.BASE_DIR)

        self.area_widget.save_settings()
        self.widgetSettingsAdvanced.update_settings()
        self.widget_settings_report.save_settings()
        if not self.lcc_manager.save_settings():
            print("Validation failed")
            return

        new_base_dir = conf.settings_manager.get_value(conf.Setting.BASE_DIR)
        if old_base_dir != new_base_dir:
            job_manager.clear_known_jobs()
            if hasattr(self, "dock_widget") and self.dock_widget.isVisible():
                self.dock_widget.refresh_after_cache_update()

        offline_mode = settings_manager.get_value(Setting.OFFLINE_MODE)
        if offline_mode:
            self.dock_widget.pushButton_download.setEnabled(False)
            self.dock_widget.setWindowTitle(DOCK_TITLE_OFFLINE)
        else:
            self.dock_widget.pushButton_download.setEnabled(True)
            self.dock_widget.setWindowTitle(DOCK_TITLE)

    def closeEvent(self, event):
        self.widgetSettingsAdvanced.closeEvent(event)
        self.area_widget.closeEvent(event)
        super().closeEvent(event)

    def reloadAuthConfigurations(self):
        authConfigId = settings.value(
            f"trends_earth/{auth.TE_API_AUTH_SETUP.key}", None
        )
        if not authConfigId:
            self.message_bar.pushCritical(
                "Trends.Earth", self.tr("Please register in order to use Trends.Earth")
            )
            return
        configs = qgis.core.QgsApplication.authManager().availableAuthMethodConfigs()
        if authConfigId not in configs.keys():
            QtCore.QSettings().setValue(
                f"trends_earth/{auth.TE_API_AUTH_SETUP.key}", None
            )

    def selectDefaultAuthConfiguration(self, authConfigId):
        self.reloadAuthConfigurations()

    def collapsed_state_changed(self):
        state = self.groupbox_lc_config.isCollapsed()
        if state:
            # Group box is closed, set size to 25
            self.groupbox_lc_config.setFixedHeight(25)
        else:
            # Group box is open, set accourding to table size
            self.lcc_manager.set_table_height()

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
                "Are you sure you want to delete the user {}? All of your tasks will "
                "be lost and you will no longer be able to process data online "
                "using Trends.Earth.".format(email)
            ),
            QtWidgets.QMessageBox.Yes,
            QtWidgets.QMessageBox.No,
        )

        if reply == QtWidgets.QMessageBox.Yes:
            resp = api.delete_user(email)

            if resp:
                QtWidgets.QMessageBox.information(
                    None,
                    self.tr("Success"),
                    self.tr(f"Trends.Earth user {email} deleted."),
                )
                # remove currently used config (as set in QSettings) and
                # trigger GUI
                auth.remove_current_auth_config(auth.TE_API_AUTH_SETUP)
                self.reloadAuthConfigurations()
                # self.authConfigUpdated.emit()


class AreaWidgetSection(Flag):
    """
    Defines main sections in the AreaWidget, primarily used to set which
    sections to hide/show.
    """

    COUNTRY = auto()
    REGION = auto()
    POINT = auto()
    FILE = auto()
    BUFFER = auto()
    NAME = auto()
    DISCLAIMER = auto()


class AreaWidget(QtWidgets.QWidget, Ui_WidgetSelectArea):
    admin_bounds_key: typing.Dict[str, download.Country]
    cities: typing.Dict[str, typing.Dict[str, download.City]]

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setupUi(self)

        self.canvas = iface.mapCanvas()
        self.vector_file = None
        self.current_cities_key = None
        self.hide_on_choose_point = True

        self.admin_bounds_key = download.get_admin_bounds()

        if not self.admin_bounds_key:
            raise ValueError("Admin boundaries not available")

        self.cities = download.get_cities()

        if not self.cities:
            raise ValueError("Cities list not available")

        # Populate
        self.area_admin_0.addItems(sorted(self.admin_bounds_key.keys()))
        self.populate_admin_1()
        self.populate_cities()
        self.area_admin_0.currentIndexChanged.connect(self.populate_admin_1)
        self.area_admin_0.currentIndexChanged.connect(self.populate_cities)
        self.area_admin_0.currentIndexChanged.connect(self.generate_name_setting)

        self.secondLevel_area_admin_1.currentIndexChanged.connect(
            self.generate_name_setting
        )
        self.secondLevel_city.currentIndexChanged.connect(self.generate_name_setting)
        self.area_frompoint_point_x.textChanged.connect(self.generate_name_setting)
        self.area_frompoint_point_y.textChanged.connect(self.generate_name_setting)
        self.area_fromfile_file.textChanged.connect(self.generate_name_setting)
        self.buffer_size_km.valueChanged.connect(self.generate_name_setting)
        self.checkbox_buffer.toggled.connect(self.generate_name_setting)

        self.area_fromfile_browse.clicked.connect(self.open_vector_browse)
        self.area_fromadmin.clicked.connect(self.area_type_toggle)
        self.area_fromfile.clicked.connect(self.area_type_toggle)

        self.radioButton_secondLevel_region.clicked.connect(
            self.radioButton_secondLevel_toggle
        )
        self.radioButton_secondLevel_city.clicked.connect(
            self.radioButton_secondLevel_toggle
        )

        icon = QtGui.QIcon(os.path.join(ICON_PATH, "map-marker.svg"))
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

        if area_from_option == "country_region" or area_from_option == "country_city":
            self.area_fromadmin.setChecked(True)
        elif area_from_option == "point":
            self.area_frompoint.setChecked(True)
        elif area_from_option == "vector_layer":
            self.area_fromfile.setChecked(True)
        self.area_frompoint_point_x.setText(
            str(settings_manager.get_value(Setting.POINT_X))
        )
        self.area_frompoint_point_y.setText(
            str(settings_manager.get_value(Setting.POINT_Y))
        )
        self.area_fromfile_file.setText(
            settings_manager.get_value(Setting.VECTOR_FILE_PATH)
        )
        self.area_type_toggle()
        admin_0 = settings_manager.get_value(Setting.COUNTRY_NAME)

        if admin_0:
            self.area_admin_0.setCurrentIndex(self.area_admin_0.findText(admin_0))
            self.populate_admin_1()

        if area_from_option == "country_region":
            self.radioButton_secondLevel_region.setChecked(True)
        elif area_from_option == "country_city":
            self.radioButton_secondLevel_city.setChecked(True)
        self.radioButton_secondLevel_toggle()

        secondLevel_area_admin_1 = settings_manager.get_value(Setting.REGION_NAME)

        if secondLevel_area_admin_1:
            if secondLevel_area_admin_1 == "All regions":
                # all regions is always stored untranslated in qsettings (to avoid
                # issues if user changes language) so need to convert to translated
                # version prior to searching for the value in the combo box
                secondLevel_area_admin_1 = TR_ALL_REGIONS
            self.secondLevel_area_admin_1.setCurrentIndex(
                self.secondLevel_area_admin_1.findText(secondLevel_area_admin_1)
            )
        secondLevel_city = settings_manager.get_value(Setting.CITY_NAME)

        if secondLevel_city:
            self.populate_cities()
            self.secondLevel_city.setCurrentIndex(
                self.secondLevel_city.findText(secondLevel_city)
            )
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
        self.secondLevel_area_admin_1.addItems([TR_ALL_REGIONS])
        self.secondLevel_area_admin_1.addItems(
            sorted(
                self.admin_bounds_key[
                    self.area_admin_0.currentText()
                ].level1_regions.keys()
            )
        )
        self.secondLevel_area_admin_1.setCurrentIndex(0)

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
        self.secondLevel_area_admin_1.setEnabled(
            self.radioButton_secondLevel_region.isChecked()
        )
        self.secondLevel_city.setEnabled(
            not self.radioButton_secondLevel_region.isChecked()
        )
        self.generate_name_setting()

    def point_chooser(self):
        log("Choosing point from canvas...")

        self.canvas.setMapTool(self.choose_point_tool)

        msg_bar = iface.messageBar()
        msg_duration = 5

        # Check layers
        if qgis.core.QgsProject.instance().count() == 0:
            msg_bar.pushMessage(
                self.tr("The map must have at least one layer."),
                qgis.core.Qgis.Warning,
                msg_duration,
            )
            return

        if self.hide_on_choose_point:
            self.window().hide()

        msg_bar.pushMessage(
            self.tr("Click the map to choose a point."),
            qgis.core.Qgis.Info,
            msg_duration,
        )

    def set_section_visibility(self, sections: AreaWidgetSection, show=False):
        """
        Specify one or more sections to hide with support for bitwise
        operators.
        """
        # Country (and region)
        if bool(sections & AreaWidgetSection.COUNTRY):
            self.area_fromadmin.setVisible(show)
            self.frame_country_region.setVisible(show)

        # Region
        if bool(sections & AreaWidgetSection.REGION):
            self.second_level_label.setVisible(show)
            self.second_level.setVisible(show)

        # Disclaimer
        if bool(sections & AreaWidgetSection.DISCLAIMER):
            self.label_disclaimer.setVisible(show)

        # Point
        if bool(sections & AreaWidgetSection.POINT):
            self.area_frompoint.setVisible(show)
            self.frame_area_frompoint.setVisible(show)

        # File
        if bool(sections & AreaWidgetSection.FILE):
            self.area_fromfile.setVisible(show)
            self.frame_area_fromfile.setVisible(show)

        # Buffer
        if bool(sections & AreaWidgetSection.BUFFER):
            self.checkbox_buffer.setVisible(show)
            self.frame.setVisible(show)

        # Name
        if bool(sections & AreaWidgetSection.NAME):
            self.label_2.setVisible(show)
            self.area_settings_name.setVisible(show)

        self.updateGeometry()

    def generate_name_setting(self):
        if self.area_fromadmin.isChecked():
            if self.radioButton_secondLevel_region.isChecked():
                name = "{}-{}".format(
                    self.area_admin_0.currentText().lower().replace(" ", "-"),
                    self.secondLevel_area_admin_1.currentText()
                    .lower()
                    .replace(" ", "-"),
                )
            else:
                name = "{}-{}".format(
                    self.area_admin_0.currentText().lower().replace(" ", "-"),
                    self.secondLevel_city.currentText().lower().replace(" ", "-"),
                )
        elif self.area_frompoint.isChecked():
            if (
                self.area_frompoint_point_x.text() != ""
                and self.area_frompoint_point_y.text() != ""
            ):
                name = "pt-lon{:.3f}lat{:.3f}".format(
                    float(self.area_frompoint_point_x.text()),
                    float(self.area_frompoint_point_y.text()),
                )
            else:
                return
        elif self.area_fromfile.isChecked():
            if self.area_fromfile_file.text() != "":
                layer = qgis.core.QgsVectorLayer(
                    self.area_fromfile_file.text(), "area", "ogr"
                )

                if layer.isValid():
                    centroid = layer.extent().center()
                    # Store point in EPSG:4326 crs
                    coord_transform = qgis.core.QgsCoordinateTransform(
                        layer.sourceCrs(),
                        qgis.core.QgsCoordinateReferenceSystem(4326),
                        qgis.core.QgsProject.instance(),
                    )
                    point = coord_transform.transform(centroid)
                    name = "shape-lon{:.3f}lat{:.3f}".format(point.x(), point.y())
                else:
                    return
            else:
                return

        if self.checkbox_buffer.isChecked():
            name = "{}-buffer-{:.3f}".format(name, self.buffer_size_km.value())
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
        self.point = self.canvas.getCoordinateTransform().toMapCoordinates(
            self.canvas.mouseLastXY()
        )

        # Store point in EPSG:4326 crs
        transform_instance = qgis.core.QgsCoordinateTransform(
            qgis.core.QgsProject.instance().crs(),
            qgis.core.QgsCoordinateReferenceSystem(4326),
            qgis.core.QgsProject.instance(),
        )
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
            self.tr("Select a file defining the area of interest"),
            initial_path,
            self.tr("Vector file (*.shp *.kml *.kmz *.geojson)"),
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
                        "Cannot read {}. Choose a different file.".format(vector_file)
                    ),
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
                if region_name == TR_ALL_REGIONS:
                    # To avoid issues if user changes language on their system, store
                    # special "All regions" value in English rather than in translated
                    # form
                    region_name = "All regions"
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
            Setting.VECTOR_FILE_DIR, str(Path(vector_path).parent)
        )
        settings_manager.write_value(
            Setting.BUFFER_CHECKED, self.checkbox_buffer.isChecked()
        )
        settings_manager.write_value(Setting.BUFFER_SIZE, self.buffer_size_km.value())
        settings_manager.write_value(Setting.AREA_NAME, self.area_settings_name.text())

        if self.current_cities_key is not None:
            settings_manager.write_value(Setting.CITY_KEY, self.current_cities_key)
        log("area settings have been saved")


class DlgSettingsRegister(QtWidgets.QDialog, Ui_DlgSettingsRegister):
    authConfigInitialised = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setupUi(self)

        self.admin_bounds_key = download.get_admin_bounds()
        self.country.addItems(sorted(self.admin_bounds_key.keys()))

        self.buttonBox.accepted.connect(self.register)
        self.buttonBox.rejected.connect(self.close)

    def register(self):
        if not self.email.text():
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"), self.tr("Enter your email address.")
            )

            return
        elif not self.name.text():
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"), self.tr("Enter your name.")
            )

            return
        elif not self.organization.text():
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"), self.tr("Enter your organization.")
            )

            return
        elif not self.country.currentText():
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"), self.tr("Enter your country.")
            )

            return

        resp = api.register(
            self.email.text(),
            self.name.text(),
            self.organization.text(),
            self.country.currentText(),
        )

        if resp:
            self.close()
            QtWidgets.QMessageBox.information(
                None,
                self.tr("Success"),
                self.tr(
                    "User registered. Your password "
                    f"has been emailed to {self.email.text()}. "
                    "Enter that password in Trends.Earth settings "
                    "to finish setting up the plugin."
                ),
            )

            # add a new auth conf that have to be completed with pwd
            authConfigId = auth.init_auth_config(
                auth.TE_API_AUTH_SETUP, email=self.email.text()
            )

            if authConfigId:
                self.authConfigInitialised.emit(authConfigId)
                return authConfigId
        else:
            return None


class DlgSettingsLogin(QtWidgets.QDialog, Ui_DlgSettingsLogin):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setupUi(self)

        self.buttonBox.accepted.connect(self.login)
        self.buttonBox.rejected.connect(self.close)

        self.ok = False

    def showEvent(self, event):
        super().showEvent(event)

        email = _get_user_email(auth.TE_API_AUTH_SETUP, warn=False)

        if email:
            self.email.setText(email)

    def login(self):
        if not self.email.text():
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"), self.tr("Enter your email address.")
            )

            return
        elif not self.password.text():
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"), self.tr("Enter your password.")
            )

            return

        if api.login_test(self.email.text(), self.password.text()):
            QtWidgets.QMessageBox.information(
                None,
                self.tr("Success"),
                self.tr(
                    "Logged in to the Trends.Earth server as "
                    f"{self.email.text()}.<html><p>Welcome to "
                    'Trends.Earth!<p/><p><a href= "'
                    'https://groups.google.com/forum/#!forum/trends_earth_users/join">Join '
                    "the Trends.Earth Users email group<a/></p><p> Make sure "
                    "to join the Trends.Earth users email group to keep up "
                    "with updates and Q&A about the tool, methods, and "
                    "datasets in support of Sustainable Development Goals "
                    "monitoring."
                ),
            )
            auth.init_auth_config(
                auth.TE_API_AUTH_SETUP, self.email.text(), self.password.text()
            )
            self.ok = True
            self.close()


class DlgSettingsLoginLandPKS(QtWidgets.QDialog, Ui_DlgSettingsLogin):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setupUi(self)

        self.buttonBox.accepted.connect(self.login)
        self.buttonBox.rejected.connect(self.close)

        self.ok = False

    def showEvent(self, event):
        super().showEvent(event)

        email = _get_user_email(auth.LANDPKS_AUTH_SETUP, warn=False)

        if email:
            self.email.setText(email)

    def login(self):
        if not self.email.text():
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"), self.tr("Enter your email address.")
            )

            return
        elif not self.password.text():
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"), self.tr("Enter your password.")
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
            auth.LANDPKS_AUTH_SETUP, self.email.text(), self.password.text()
        )

        QtWidgets.QMessageBox.information(
            None,
            self.tr("Success"),
            self.tr(
                "Successfully setup login to the LandPKS server as "
                f"{self.email.text()}."
            ),
        )

        self.ok = True
        self.close()


class DlgSettingsEditForgotPassword(
    QtWidgets.QDialog, Ui_DlgSettingsEditForgotPassword
):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setupUi(self)

        self.buttonBox.accepted.connect(self.reset_password)
        self.buttonBox.rejected.connect(self.close)

        self.ok = False

    def showEvent(self, event):
        super().showEvent(event)

        email = _get_user_email(auth.TE_API_AUTH_SETUP, warn=False)

        if email:
            self.email.setText(email)

    def reset_password(self):
        if not self.email.text():
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Enter your email address to reset your password."),
            )

            return

        reply = QtWidgets.QMessageBox.question(
            None,
            self.tr("Reset password?"),
            self.tr(
                "Are you sure you want to reset the password for "
                f"{self.email.text()}? Your new password will be emailed "
                "to you."
            ),
            QtWidgets.QMessageBox.Yes,
            QtWidgets.QMessageBox.No,
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
                    ),
                )
                self.ok = True


class DlgSettingsEditUpdate(QtWidgets.QDialog, Ui_DlgSettingsEditUpdate):
    def __init__(self, user, parent=None):
        super().__init__(parent)

        self.setupUi(self)

        self.user = user

        self.admin_bounds_key = download.get_admin_bounds()

        self.email.setText(user["email"])
        self.name.setText(user["name"])
        self.organization.setText(user["institution"])

        # Add countries, and set index to currently chosen country
        self.country.addItems(sorted(self.admin_bounds_key.keys()))
        index = self.country.findText(user["country"])

        if index != -1:
            self.country.setCurrentIndex(index)

        self.buttonBox.accepted.connect(self.update_profile)
        self.buttonBox.rejected.connect(self.close)

        self.ok = False

    def update_profile(self):
        if not self.email.text():
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"), self.tr("Enter your email address.")
            )

            return
        elif not self.name.text():
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"), self.tr("Enter your name.")
            )

            return
        elif not self.organization.text():
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"), self.tr("Enter your organization.")
            )

            return
        elif not self.country.currentText():
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"), self.tr("Enter your country.")
            )

            return

        resp = api.update_user(
            self.email.text(),
            self.name.text(),
            self.organization.text(),
            self.country.currentText(),
        )

        if resp:
            QtWidgets.QMessageBox.information(
                None,
                self.tr("Saved"),
                self.tr("Updated information for {}.").format(self.email.text()),
            )
            self.close()
            self.ok = True


class WidgetSettingsAdvanced(QtWidgets.QWidget, Ui_WidgetSettingsAdvanced):
    _settings_base_path: str = "trends_earth/advanced"
    _qgis_settings = qgis.core.QgsSettings()

    binaries_gb = QtWidgets.QGroupBox
    binaries_dir_le = QtWidgets.QLineEdit
    debug_checkbox: QtWidgets.QCheckBox
    filter_jobs_by_basedir_checkbox: QtWidgets.QCheckBox
    polling_frequency_gb: QtWidgets.QGroupBox
    polling_frequency_sb: QtWidgets.QSpinBox
    download_remote_datasets_chb: QtWidgets.QCheckBox
    qgsFileWidget_base_directory: qgis.gui.QgsFileWidget

    message_bar: qgis.gui.QgsMessageBar

    def __init__(
        self, group_box, dock_widget, message_bar: qgis.gui.QgsMessageBar, parent=None
    ):
        super().__init__(parent)
        self.setupUi(self)

        self.group_box = group_box
        self.dock_widget = dock_widget
        self.message_bar = message_bar

        self.dlg_settings_login_landpks = DlgSettingsLoginLandPKS()

        self.pushButton_login_landpks.clicked.connect(self.login_landpks)
        self.binaries_browse_button.clicked.connect(self.binary_folder_browse)
        self.binaries_gb.toggled.connect(self.binaries_toggle)
        self.binaries_download_button.clicked.connect(self.binaries_download)
        self.qgsFileWidget_base_directory.fileChanged.connect(
            self.base_directory_changed
        )
        self.pushButton_open_base_directory.clicked.connect(self.open_base_directory)
        self.cb_offline_mode.stateChanged.connect(self.set_offline_mode_states)

        # Flag that can be used to indicate if binary state has changed (i.e.
        # if new binaries have been downloaded)
        self.binary_state_changed = False

        # TODO: re-enable this one LandPKS login is working
        self.landpks_gb.hide()

    def closeEvent(self, event):
        super().closeEvent(event)

        if (
            self.binaries_gb.isChecked() != self.binaries_checkbox_initial
            or self.binary_state_changed
        ):
            QtWidgets.QMessageBox.warning(
                None,
                self.tr("Warning"),
                self.tr("You must restart QGIS for these changes to take effect."),
            )

    def update_settings(self):
        """Store the current value of each setting in QgsSettings"""
        log(f"poll remote: {self.polling_frequency_gb.isChecked()}")
        settings_manager.write_value(
            Setting.POLL_REMOTE, self.polling_frequency_gb.isChecked()
        )
        settings_manager.write_value(
            Setting.REMOTE_POLLING_FREQUENCY, int(self.polling_frequency_sb.value())
        )
        settings_manager.write_value(
            Setting.DOWNLOAD_RESULTS, self.download_remote_datasets_chb.isChecked()
        )
        # TODO: save the current region of interest
        settings_manager.write_value(Setting.DEBUG, self.debug_checkbox.isChecked())
        settings_manager.write_value(
            Setting.FILTER_JOBS_BY_BASE_DIR,
            self.filter_jobs_by_basedir_checkbox.isChecked(),
        )
        settings_manager.write_value(
            Setting.BINARIES_ENABLED, self.binaries_gb.isChecked()
        )
        settings_manager.write_value(Setting.BINARIES_DIR, self.binaries_dir_le.text())
        settings_manager.write_value(
            Setting.OFFLINE_MODE, self.cb_offline_mode.isChecked()
        )

        old_base_dir = settings_manager.get_value(Setting.BASE_DIR)
        new_base_dir = self.qgsFileWidget_base_directory.filePath()
        settings_manager.write_value(Setting.BASE_DIR, new_base_dir)

        if old_base_dir != new_base_dir:
            job_manager.clear_known_jobs()

    def login_landpks(self):
        self.dlg_settings_login_landpks.exec_()

    def show_settings(self):
        self.debug_checkbox.setChecked(settings_manager.get_value(Setting.DEBUG))
        self.cb_offline_mode.setChecked(
            settings_manager.get_value(Setting.OFFLINE_MODE)
        )
        self.filter_jobs_by_basedir_checkbox.setChecked(
            settings_manager.get_value(Setting.FILTER_JOBS_BY_BASE_DIR)
        )
        self.binaries_dir_le.setText(
            settings_manager.get_value(Setting.BINARIES_DIR) or ""
        )
        self.qgsFileWidget_base_directory.setFilePath(
            settings_manager.get_value(Setting.BASE_DIR) or ""
        )
        self.polling_frequency_gb.setChecked(
            settings_manager.get_value(Setting.POLL_REMOTE)
        )
        self.polling_frequency_sb.setValue(
            settings_manager.get_value(Setting.REMOTE_POLLING_FREQUENCY)
        )
        self.download_remote_datasets_chb.setChecked(
            settings_manager.get_value(Setting.DOWNLOAD_RESULTS)
        )

    def set_offline_mode_states(self):
        """This funtion is called when offline mode is enabled or disabled.
        If offline mode is enabled, then all settings related to online
        requests (e.g. download remote datasets or polling the server) will
        be disabled as well. The login section will also be disabled.
        If offline mode is disabled, all of the above features will be
        reenabled.
        """

        if self.cb_offline_mode.isChecked():
            # Offline mode is enabled
            self.download_remote_datasets_chb.setEnabled(False)
            self.download_remote_datasets_chb.setChecked(False)

            # Polling frequency settings
            self.polling_frequency_gb.setEnabled(False)
            self.polling_frequency_gb.setChecked(False)

            # Login settings
            self.group_box.setEnabled(False)

            self.message_bar.pushWarning(
                "Trends.Earth", self.tr("Offline mode is enabled.")
            )
        else:
            # Offline mode is disabled
            self.download_remote_datasets_chb.setEnabled(True)
            self.download_remote_datasets_chb.setChecked(True)

            # Polling frequency settings
            self.polling_frequency_gb.setEnabled(True)
            self.polling_frequency_gb.setChecked(True)

            # Login settings
            self.group_box.setEnabled(True)

    def showEvent(self, event):
        super().showEvent(event)
        self.show_settings()
        self.set_offline_mode_states()
        binaries_checked = settings_manager.get_value(Setting.BINARIES_ENABLED)
        # TODO: Have this actually check if they are enabled in summary_numba
        # and calculate_numba. Right now this doesn't really check if they are
        # enabled, just that they are available. Which should be the same
        # thing, but might not always be...

        if binaries_available() and binaries_checked:
            self.binaries_label.setText(self.tr("Binaries <b>are</b> loaded."))
        else:
            self.binaries_label.setText(self.tr("Binaries <b>are not</b> loaded."))
        # Set a flag that will be used to indicate whether the status of using
        # binaries or not has changed (needed to allow displaying a message to
        # the user that they need to restart when this setting is changed)
        self.binaries_checkbox_initial = binaries_checked
        self.binaries_gb.setChecked(binaries_checked)
        self.binaries_toggle()

    def base_directory_changed(self, new_base_directory):
        if not new_base_directory:
            self.message_bar.pushWarning(
                "Trends.Earth", self.tr("No base data directory set")
            )

            return

        try:
            if not os.path.exists(new_base_directory):
                os.makedirs(new_base_directory)
        except PermissionError:
            self.message_bar.pushCritical(
                "Trends.Earth",
                self.tr(
                    "Unable to write to {}. Try a different folder.".format(
                        new_base_directory
                    )
                ),
            )

            return

        settings_manager.write_value(Setting.BASE_DIR, str(new_base_directory))

    def open_base_directory(self):
        openFolder(self.qgsFileWidget_base_directory.filePath())

    def binaries_download(self):
        out_folder = os.path.join(self.binaries_dir_le.text())

        if out_folder == "":
            QtWidgets.QMessageBox.information(
                None,
                self.tr("Choose a folder"),
                self.tr("Choose a folder before downloading binaries."),
            )

            return

        if not os.access(out_folder, os.W_OK):
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Unable to write to {}. Choose a different folder.".format(
                        out_folder
                    )
                ),
            )

            return

        try:
            if not os.path.exists(out_folder):
                os.makedirs(out_folder)
        except PermissionError:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Unable to write to {}. Try a "
                    "different folder.".format(out_folder)
                ),
            )

            return None

        zip_filename = f"{binaries_name}.zip"
        zip_url = (
            "https://s3.amazonaws.com/trends.earth/plugin_binaries/" + zip_filename
        )
        downloads = download.download_files([zip_url], out_folder)

        if not downloads:
            return None

        try:
            with zipfile.ZipFile(os.path.join(out_folder, zip_filename), "r") as zf:
                zf.extractall(out_folder)
        except PermissionError:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Unable to write to {}. Check that you have permissions to write to this folder, and that you are not trying to overwrite the binaries that you currently have loaded in QGIS.".format(
                        out_folder
                    )
                ),
            )

            return None
        except FileNotFoundError:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Unable to read binaries from {}. Check that binaries were downloaded successfully.".format(
                        out_folder
                    )
                ),
            )

            return None

        os.remove(os.path.join(out_folder, zip_filename))

        if downloads is None:
            QtWidgets.QMessageBox.critical(
                None, self.tr("Error"), self.tr("Error downloading binaries.")
            )
        else:
            if len(downloads) > 0:
                self.binary_state_changed = True
                QtWidgets.QMessageBox.information(
                    None, self.tr("Success"), self.tr("Downloaded binaries.")
                )
            else:
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Success"),
                    self.tr("All binaries up to date.".format(out_folder)),
                )

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
            self.tr("Select folder containing Trends.Earth binaries"),
            initial_path,
        )

        if folder_path:
            plugin_folder = os.path.normpath(
                os.path.realpath(os.path.dirname(__file__))
            )

            if is_subdir(folder_path, plugin_folder):
                QtWidgets.QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(
                        "Choose a different folder - cannot install binaries within "
                        "the Trends.Earth QGIS plugin installation folder."
                    ),
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
                    self.tr(f"Cannot read {folder_path!r}. Choose a different folder."),
                )

                return False
        else:
            return False


class WidgetSettingsReport(QtWidgets.QWidget, Ui_WidgetSettingsReport):
    """
    Report settings widget.
    """

    disclaimer_te: QtWidgets.QPlainTextEdit
    footer_te: QtWidgets.QPlainTextEdit
    log_warnings_cb: QtWidgets.QCheckBox
    message_bar: qgis.gui.QgsMessageBar
    org_logo_le: QtWidgets.QLineEdit
    org_logo_tb: QtWidgets.QToolButton
    org_name_le: QtWidgets.QLineEdit
    template_search_path_le: QtWidgets.QLineEdit
    template_search_path_tb: QtWidgets.QToolButton

    def __init__(self, parent=None, message_bar=None):
        super().__init__(parent)
        self.setupUi(self)

        self.message_bar = message_bar

        # Set icons
        self.org_logo_tb.setIcon(FileUtils.get_icon("mActionFileOpen.svg"))
        self.template_search_path_tb.setIcon(FileUtils.get_icon("mActionFileOpen.svg"))

        # Connect signals
        self.template_search_path_tb.clicked.connect(self.on_select_template_path)
        self.org_logo_tb.clicked.connect(self.on_select_org_logo)

    def _load_settings(self):
        """
        Load settings in the configuration.
        """
        search_path = settings_manager.get_value(Setting.REPORT_TEMPLATE_SEARCH_PATH)
        self.template_search_path_le.setText(search_path)
        self.template_search_path_le.setToolTip(search_path)

        logo_path = settings_manager.get_value(Setting.REPORT_ORG_LOGO_PATH)
        self.org_logo_le.setText(logo_path)
        self.org_logo_le.setToolTip(logo_path)

        self.org_name_le.setText(settings_manager.get_value(Setting.REPORT_ORG_NAME))
        self.footer_te.setPlainText(settings_manager.get_value(Setting.REPORT_FOOTER))
        self.disclaimer_te.setPlainText(
            settings_manager.get_value(Setting.REPORT_DISCLAIMER)
        )
        log_warnings = settings_manager.get_value(Setting.REPORT_LOG_WARNING)
        self.log_warnings_cb.setChecked(log_warnings)

    def showEvent(self, event):
        super().showEvent(event)
        self._load_settings()

    def on_select_template_path(self):
        # Slot for choosing template search path
        template_dir = self.template_search_path_le.text()
        if not template_dir:
            template_dir = settings_manager.get_value(Setting.BASE_DIR)

        template_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            self.tr("Select Report Template Search Path"),
            template_dir,
            options=QtWidgets.QFileDialog.DontResolveSymlinks
            | QtWidgets.QFileDialog.ShowDirsOnly,
        )
        if template_dir:
            self.template_search_path_le.setText(template_dir)
            self.template_search_path_le.setToolTip(template_dir)
            msg = self.tr("QGIS needs to be restarted for the changes to take effect.")
            if self.message_bar is not None:
                self.message_bar.pushMessage(
                    self.tr("Template Search Path"), msg, qgis.core.Qgis.Warning, 5
                )

    def _image_files_filter(self):
        # QFileDialog filter for image files.
        formats = [
            f"*.{bytes(fmt).decode()}"
            for fmt in QtGui.QImageReader.supportedImageFormats()
        ]
        tr_prefix = self.tr("All Images")
        formats_txt = " ".join(formats)

        return f"{tr_prefix} ({formats_txt})"

    def on_select_org_logo(self):
        # Slot for selecting organization logo
        org_logo_path = self.org_logo_le.text()
        if not org_logo_path:
            logo_dir = settings_manager.get_value(Setting.BASE_DIR)
        else:
            fi = QtCore.QFileInfo(org_logo_path)
            file_dir = fi.dir()
            logo_dir = file_dir.path()

        org_logo_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr("Select Organization Logo"),
            logo_dir,
            self._image_files_filter(),
            options=QtWidgets.QFileDialog.DontResolveSymlinks,
        )
        if org_logo_path:
            self.org_logo_le.setText(org_logo_path)
            self.org_logo_le.setToolTip(org_logo_path)

    def save_settings(self):
        # Persist settings.
        settings_manager.write_value(
            Setting.REPORT_TEMPLATE_SEARCH_PATH, self.template_search_path_le.text()
        )
        settings_manager.write_value(
            Setting.REPORT_ORG_LOGO_PATH, self.org_logo_le.text()
        )
        settings_manager.write_value(Setting.REPORT_ORG_NAME, self.org_name_le.text())
        settings_manager.write_value(
            Setting.REPORT_FOOTER, self.footer_te.toPlainText()
        )
        settings_manager.write_value(
            Setting.REPORT_DISCLAIMER, self.disclaimer_te.toPlainText()
        )
        settings_manager.write_value(
            Setting.REPORT_LOG_WARNING, self.log_warnings_cb.isChecked()
        )

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(450, 350)


class DlgLandCoverRestore(QtWidgets.QDialog, Ui_DlgLandCoverRestore):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.buttonBox.rejected.connect(self.close)


class LandCoverCustomClassesManager(
    qgis.gui.QgsPanelWidget, Ui_WidgetLandCoverCustomClassesManager
):
    def __init__(
        self,
        groupbox_lc_config,
        scroll_area,
        group_box,
        region_of_interest,
        parent=None,
        msg_bar=None,
    ):
        super().__init__(parent)
        self.setupUi(self)
        self.setDockMode(True)

        self.groupbox_lc_config = groupbox_lc_config

        self.scroll_area = scroll_area
        self.group_box = group_box
        self.region_of_interest = region_of_interest
        self.msg_bar = msg_bar
        self.editor = None
        self._last_clr = None
        self._init_load = False
        self.max_classes = settings_manager.get_value(Setting.LC_MAX_CLASSES)
        self.dlg_land_cover_restore = DlgLandCoverRestore()
        self.dlg_land_cover_restore.pb_restore_unccd.clicked.connect(
            self.on_restore_unccd
        )
        self.dlg_land_cover_restore.pb_restore_esa.clicked.connect(self.on_restore_esa)
        self.current_scroll_pos = None
        self.current_scroll_max = None

        # UI initialization
        self.model = QtGui.QStandardItemModel(self)
        self.model.setHorizontalHeaderLabels(
            [self.tr("Name"), self.tr("Code"), self.tr("Parent")]
        )
        self.tb_classes.setModel(self.model)
        self.selection_model = self.tb_classes.selectionModel()
        self.selection_model.selectionChanged.connect(self.on_selection_changed)
        self.tb_classes.clicked.connect(self.on_class_info_clicked)

        add_icon = qgis.core.QgsApplication.instance().getThemeIcon("symbologyAdd.svg")
        self.btn_add_class.setIcon(add_icon)
        self.btn_add_class.clicked.connect(self.on_add_class)

        load_table_icon = qgis.core.QgsApplication.instance().getThemeIcon(
            "mActionFileOpen.svg"
        )
        self.btn_load.setIcon(load_table_icon)
        self.btn_load.clicked.connect(self.on_load_file)

        save_table_icon = qgis.core.QgsApplication.instance().getThemeIcon(
            "mActionFileSave.svg"
        )
        self.btn_save.setIcon(save_table_icon)
        self.btn_save.clicked.connect(self.on_save_file)

        restore_icon = qgis.core.QgsApplication.instance().getThemeIcon(
            "mActionReload.svg"
        )
        self.btn_restore.setIcon(restore_icon)
        self.btn_restore.clicked.connect(self.dlg_land_cover_restore.exec_)

    def on_restore_esa(self):
        # Slot raised to restore ESA land cover classes.
        self.dlg_land_cover_restore.close()
        self.clear_class_infos()
        LccInfoUtils.set_default_esa_classes(True)
        self.load_settings()

    def on_restore_unccd(self):
        # Slot raised to restore UNCCD land cover classes.
        self.dlg_land_cover_restore.close()
        self.clear_class_infos()
        LccInfoUtils.set_default_unccd_classes(True)
        self.load_settings()

    def append_msg(self, msg: str, warning=True):
        # Add warning or info message if a message bar has been defined.
        if self.msg_bar is None:
            return

        if warning:
            level = qgis.core.Qgis.MessageLevel.Warning
        else:
            level = qgis.core.Qgis.MessageLevel.Info

        self.msg_bar.pushMessage(self.tr("Land Cover"), msg, level, 5)

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(350, 420)

    def resizeEvent(self, event: QtGui.QResizeEvent):
        # Adjust column width
        width = self.tb_classes.width()
        self.tb_classes.setColumnWidth(0, int(width * 0.4))
        self.tb_classes.setColumnWidth(1, int(width * 0.16))
        self.tb_classes.setColumnWidth(2, int(width * 0.4))

    def on_add_class(self):
        # Slot raised to add a land cover class.
        # Check if max number of classes have been reached
        rows = self.model.rowCount()
        if rows >= self.max_classes:
            msg = self.tr("Maximum number of classes reached.")
            self.append_msg(msg)

            return

        self._open_editor()

    def clear_class_infos(self):
        # Clears the table of land cover classes.
        if self.has_class_infos():
            row_count = self.model.rowCount()
            self.model.removeRows(0, row_count)

    def has_class_infos(self) -> bool:
        # Returns True if there are classes in the table, else False.
        row_count = self.model.rowCount()
        if row_count == 0:
            return False

        return True

    def save_settings(self) -> bool:
        """
        Save classes to settings.
        """
        lcc_infos = self.class_infos()
        status = LccInfoUtils.save_settings(lcc_infos)
        if not status:
            log("Custom land cover classes could not be saved to settings.")

        return True

    def showEvent(self, event):
        super().showEvent(event)
        if not self._init_load:
            self.load_settings()
            self._init_load = True

    def load_settings(self):
        # Load classes from settings.
        status, lc_classes = LccInfoUtils.load_settings()
        if not status:
            log("Failed to read land cover classes from settings.")
            return

        if len(lc_classes) == 0:
            log("No land cover classes in settings.")
            return

        self._load_classes(lc_classes)

    def on_save_file(self):
        # Slot raised to save current classes to file.
        if not self.has_class_infos():
            self.append_msg(self.tr("Nothing to save"))
            return

        last_dir = settings_manager.get_value(Setting.LC_LAST_DIR)
        if not last_dir:
            last_dir = settings_manager.get_value(Setting.BASE_DIR)

        lcc_save_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            self.tr("Save Land Cover Classes"),
            last_dir,
            "JSON (*.json)",
            options=QtWidgets.QFileDialog.DontResolveSymlinks,
        )
        if lcc_save_path:
            lcc_infos = self.class_infos()
            status = LccInfoUtils.save_file(lcc_save_path, lcc_infos)
            if not status:
                log(f"Unable to save land cover " f"classes to '{lcc_save_path}'")
                return

            fi = QtCore.QFileInfo(lcc_save_path)
            cls_dir = fi.dir().path()
            settings_manager.write_value(Setting.LC_LAST_DIR, cls_dir)

    def on_load_file(self):
        # Slot raised to load JSOn file with custom LC classes.
        last_dir = settings_manager.get_value(Setting.LC_LAST_DIR)
        if not last_dir:
            last_dir = settings_manager.get_value(Setting.BASE_DIR)

        lcc_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr("Select Land Cover Classes File"),
            last_dir,
            "JSON (*.json)",
            options=QtWidgets.QFileDialog.DontResolveSymlinks,
        )
        if lcc_path:
            status, lcc_infos = LccInfoUtils.load_file(lcc_path)
            if not status:
                log("Failed to load the custom land cover file.")
                return

            fi = QtCore.QFileInfo(lcc_path)
            cls_dir = fi.dir().path()
            settings_manager.write_value(Setting.LC_LAST_DIR, cls_dir)

            if len(lcc_infos) == 0:
                self.append_msg(self.tr("No land cover classes found."))
                return

            self._load_classes(lcc_infos)

    def _load_classes(self, classes: typing.List[LCClassInfo]):
        # Load classes to the table.
        if not isinstance(classes, list):
            return

        self.clear_class_infos()

        for lc_cls in classes:
            if not isinstance(lc_cls, LCClassInfo):
                log("Not class info")
                continue
            self.add_class_info_to_table(lc_cls)

    def set_table_height(self):
        table_row_count = self.model.rowCount()
        row_0_height = self.tb_classes.rowHeight(
            0
        )  # There will always be atleast one class
        btns_height = self.horizontalLayout.totalSizeHint().height()

        # Step to avoid a too small group box. This is to accomodate the class editor
        if table_row_count > 4:
            # Adds 2 rows to the count, mostly to include the fields names row
            rows_height = row_0_height * (table_row_count + 2)
        else:
            # Uses 6 rows as the minimum
            rows_height = row_0_height * 6

        # 10 is added as an additional precaution to avoid a scroll bar
        final_height = rows_height + btns_height + 10
        self.groupbox_lc_config.setFixedHeight(final_height)

    def _parent_scroll_area(self) -> qgis.gui.QgsScrollArea:
        # Returns the innermost parent scroll area that this widget might
        # belong to, else None.
        parent = self.parentWidget()
        if parent is None:
            return None

        parent_scroll = None
        while parent is not None:
            if isinstance(parent, qgis.gui.QgsScrollArea):
                parent_scroll = parent
                break

            parent = parent.parentWidget()

        return parent_scroll

    def _open_editor(self, lc_cls_info=None):
        # Opens class editor
        p = qgis.gui.QgsPanelWidget.findParentPanel(self)
        if p and p.dockMode():
            self.editor = LandCoverCustomClassEditor(
                self,
                lc_class_info=lc_cls_info,
                default_color=self._last_clr,
                msg_bar=self.msg_bar,
                codes=self.class_codes(),
            )
            self.editor.setPanelTitle(self.tr("Land Cover Class Editor"))
            self.editor.panelAccepted.connect(self.on_editor_accepted)
            self.editor.notify_delete.connect(self.delete_class_info)

            # Manually set the value of the scroll when loading the sub-panel
            # due to unusual behavior of the vertical scroll bar scrolling
            # to the top.
            scroll_area = self._parent_scroll_area()
            init_pos = -1
            vs_bar = None
            if scroll_area is not None:
                vs_bar = scroll_area.verticalScrollBar()
                init_pos = vs_bar.value()

            self.openPanel(self.editor)

            group_box_height = self.group_box.height()
            roi_height = self.region_of_interest.height()
            total_height = group_box_height + roi_height

            vertical_scroll_bar = self.scroll_area.verticalScrollBar()

            self.current_scroll_pos = vertical_scroll_bar.value()
            self.current_scroll_max = vertical_scroll_bar.maximum()

            # Changes the size of the box to that of the
            # LC editor
            self.groupbox_lc_config.setFixedHeight(215)

            vertical_scroll_bar.setValue(total_height)

            # Restore the viewport area
            if vs_bar is not None and vs_bar.value() == 0 and init_pos != -1:
                vs_bar.setValue(init_pos)

    def on_editor_accepted(self, panel):

        vertical_scroll_bar = self.scroll_area.verticalScrollBar()

        # Sets the size to the number of rows
        self.set_table_height()

        # Slot raised when editor panel has been accepted.
        lc_cls_info = panel.lc_class_info
        if lc_cls_info is None and not panel.updated:
            return

        if panel.edit_mode:
            self.update_class_info(lc_cls_info)
        else:
            self.add_class_info_to_table(lc_cls_info)

        self._last_clr = QtGui.QColor(lc_cls_info.lcc.color)

        diff = self.current_scroll_max - vertical_scroll_bar.maximum()
        if diff == 0:
            vertical_scroll_bar.setValue(self.current_scroll_pos)
        else:
            vertical_scroll_bar.setMaximum(self.current_scroll_max)
            vertical_scroll_bar.setValue(self.current_scroll_pos)

    def update_class_info(self, lc_info: LCClassInfo):
        # Update existing LCClassInfo row.
        row = lc_info.idx
        if row == -1:
            self.append_msg(self.tr("Invalid row for land cover class"))
            return

        items = self._update_lcc_row_items(lc_info, True, row)
        if len(items) == 0:
            self.append_msg(self.tr("Unable to update class."))
            return

        self._update_row_data(row, lc_info)

    def add_class_info_to_table(self, lc_info: LCClassInfo):
        # Add land cover class info to the table view.
        if lc_info is None:
            return

        rows = self.model.rowCount()
        if rows >= self.max_classes:
            msg = self.tr("Maximum number of classes reached.")
            self.append_msg(msg)

            return

        items = self._update_lcc_row_items(lc_info)
        if len(items) == 0:
            self.append_msg(self.tr("Unable to add new class."))
            return

        self.model.insertRow(rows, items)
        self._update_row_data(rows, lc_info)

        self.set_table_height()

    def parent_child_codes(self) -> typing.Dict[str, list]:
        """
        Returns a dictionary containing parent class name and corresponding
        codes for child classes assigned to it.
        """
        lcc_infos = self.class_infos()

        return {lcci.lcc.name_long: lcci.child_codes for lcci in lcc_infos}

    def validate_child_codes(
        self, lcc_infos: typing.List["LCClassInfo"]
    ) -> typing.Tuple[bool, list]:
        """
        Validate children have been specified.
        """
        status = True
        messages = []
        child_codes = []
        for lcci in lcc_infos:
            if len(lcci.child_codes) == 0:
                msg_tr = self.tr("class does not have children assigned to it")
                warning = f"{lcci.lcc.name_long} {msg_tr}"
                messages.append(warning)
                if status:
                    status = False
            child_codes.extend(lcci.child_codes)

        # Ensure all child classes have been assigned parents
        nesting = LccInfoUtils.lc_nesting()
        child_legend = nesting.child
        ref_child_codes = [lcc.code for lcc in child_legend.key]

        if len(child_codes) != len(ref_child_codes):
            ref_child_codes_set = set(ref_child_codes)
            user_child_codes_set = set(child_codes)
            unassigned_codes = ref_child_codes_set - user_child_codes_set

            for c in unassigned_codes:
                lcc = child_legend.class_by_code(c)
                if lcc is not None:
                    msg_tr = self.tr("class has not been assigned a parent")
                    msg = f"{lcc.name_long} {msg_tr}"
                    messages.append(msg)

            if status:
                status = False

        return status, messages

    def _update_lcc_row_items(
        self, lc_info: LCClassInfo, update=False, row=None
    ) -> typing.List[QtGui.QStandardItem]:
        # Create new or update existing row items
        if update and row is None:
            return []

        lcc = lc_info.lcc
        parent = lc_info.parent

        if not update:
            name_item = QtGui.QStandardItem(lcc.name_long)
            code_item = QtGui.QStandardItem(str(lcc.code))
            parent_item = QtGui.QStandardItem(str(parent.name_long))
        else:
            name_idx = self.model.index(row, 0)
            name_item = self.model.itemFromIndex(name_idx)
            name_item.setText(lcc.name_long)

            code_idx = self.model.index(row, 1)
            code_item = self.model.itemFromIndex(code_idx)
            code_item.setText(str(lcc.code))

            parent_idx = self.model.index(row, 2)
            parent_item = self.model.itemFromIndex(parent_idx)
            parent_item.setText(str(parent.name_long))

        clr = QtGui.QColor(lcc.color)
        if clr.isValid():
            name_item.setData(clr, QtCore.Qt.DecorationRole)

        code_item.setData(lcc.code)

        parent_item.setData(parent)
        parent_clr = QtGui.QColor(parent.color)
        if parent_clr.isValid():
            parent_item.setData(parent_clr, QtCore.Qt.DecorationRole)

        return [name_item, code_item, parent_item]

    def _update_row_data(self, row, lc_info):
        # Set the lc_info object at the given row
        idx = self.model.index(row, 0)
        if idx.isValid():
            self.model.setData(idx, lc_info, QtCore.Qt.UserRole)

    def row_data(self, row: int) -> LCClassInfo:
        # Returns the lc class info object at the given row.
        if row < 0 or row > self.model.rowCount() - 1:
            return None

        idx = self.model.index(row, 0)
        if not idx.isValid():
            return None

        return self.model.data(idx, QtCore.Qt.UserRole)

    def class_infos(self) -> typing.List[LCClassInfo]:
        """
        Returns a list of LCClassInfo objects currently in the table.
        """
        row_count = self.model.rowCount()

        return [self.row_data(i) for i in range(row_count)]

    def class_codes(self) -> typing.List[int]:
        """
        Return a list of codes for the classes in the table.
        """
        return [lcc_info.lcc.code for lcc_info in self.class_infos()]

    def on_selection_changed(self, deselected, selected):
        # Slot raised when row selection has changed. This loads the class
        # editor.
        sel_rows = self.selection_model.selectedRows()
        if len(sel_rows) == 0:
            return

        sel_idx = sel_rows[0]
        self.open_editor_at_idx(sel_idx)

    def on_class_info_clicked(self, idx: QtCore.QModelIndex):
        # Slot raised when an LCClassInfo item has been clicked for a row
        # that had already been selected.
        sel_rows = self.selection_model.selectedRows()
        if len(sel_rows) == 0:
            return

        sel_idx = sel_rows[0]
        if sel_idx.row() == idx.row():
            self.open_editor_at_idx(idx)

    def open_editor_at_idx(self, idx: QtCore.QModelIndex):
        # Open the class editor at the given index.
        if not idx.isValid():
            return

        row = idx.row()
        lcc_info = self.row_data(row)
        if lcc_info is None:
            return

        lcc_info.idx = row
        self._open_editor(lcc_info)

    def delete_class_info(self, row: int):
        # Notification to remove the given row.
        if row < 0:
            log("Invalid reference of land cover class to remove.")
            return

        # Reject if there is only one record remaining
        rec_count = self.model.rowCount()
        if rec_count == 1:
            msg = self.tr(
                "There must be at least one class defined. You can create a "
                "new one then delete this one or you can restore the "
                "default UNCCD classes by clicking on the Restore button."
            )
            QtWidgets.QMessageBox.warning(self, self.tr("Delete Failed"), msg)
            return

        self.selection_model.blockSignals(True)
        self.selection_model.clearSelection()
        status = self.model.removeRows(row, 1)
        self.selection_model.blockSignals(False)
        if not status:
            log(f"Unable to remove land cover class in row {row!s}")

        self.set_table_height()


class LandCoverCustomClassEditor(
    qgis.gui.QgsPanelWidget, Ui_WidgetLandCoverCustomClassEditor
):
    """
    Widget for defining new or edit existing custom land cover class.
    """

    notify_delete = QtCore.pyqtSignal(int)

    def __init__(
        self,
        parent=None,
        lc_class_info=None,
        default_color=None,
        msg_bar=None,
        codes=None,
    ):
        super().__init__(parent)
        self.setupUi(self)

        self.default_color = default_color
        if self.default_color is None:
            self.default_color = QtGui.QColor("#8FE142")

        self._default_lc_nesting = get_default_esa_nesting()

        self.codes = codes
        self._code_max = 255
        if self.codes is None:
            self.codes = []

        self.lc_class_info = lc_class_info
        self.msg_bar = msg_bar

        self.updated = False
        self.edit_mode = False

        # UI initialization
        delete_icon = qgis.core.QgsApplication.instance().getThemeIcon(
            "mActionDeleteSelected.svg"
        )
        self.btn_remove.setIcon(delete_icon)
        self.btn_remove.setEnabled(False)
        self.btn_remove.clicked.connect(self.on_delete_class)

        self.clr_btn.setColor(self.default_color)
        self.clr_btn.setContext("class_clr")
        self.clr_btn.setColorDialogTitle(self.tr("Class Color"))

        success_icon = qgis.core.QgsApplication.instance().getThemeIcon(
            "mIconSuccess.svg"
        )
        self.btn_done.setIcon(success_icon)
        self.btn_done.clicked.connect(self.on_accept_info)

        self.cbo_cls_parent.currentIndexChanged.connect(self._on_parent_changed)

        self._load_default_lc_classes()

        self._suggest_code()

        if lc_class_info is not None:
            self.set_class_info(self.lc_class_info)
            self.edit_mode = True
            if lc_class_info.idx != -1:
                self.btn_remove.setEnabled(True)
                self.sb_cls_code.setEnabled(False)

    def _load_default_lc_classes(self):
        # Load default LC classes.
        self.cbo_cls_parent.addItem("")
        parent_legend = self._default_lc_nesting.parent
        ref_classes = parent_legend.key
        no_data = parent_legend.nodata
        if no_data is not None:
            ref_classes += [no_data]

        for idx, lcc in enumerate(ref_classes, start=1):
            self.cbo_cls_parent.insertItem(idx, lcc.name_long, lcc)
            clr = QtGui.QColor(lcc.color)
            self.cbo_cls_parent.setItemData(idx, clr, QtCore.Qt.DecorationRole)

    def _suggest_code(self):
        # Suggest a code value for a new land cover class.
        if self.edit_mode:
            return

        code_range = set(range(1, self._code_max + 1))
        used_codes = set(self.codes)
        code = min(code_range - used_codes)

        self.sb_cls_code.setValue(code)

    def append_warning_msg(self, msg: str):
        # Add warning message if a message bar has been defined.
        if self.msg_bar is None:
            return

        self.msg_bar.pushMessage(
            self.tr("Land Cover"), msg, qgis.core.Qgis.MessageLevel.Warning, 5
        )

    def clear_messages(self):
        # Removes all messages in the message bar.
        if self.msg_bar is None:
            return

        self.msg_bar.clearWidgets()

    def set_class_info(self, lc_class_info: LCClassInfo):
        # Set widget values to corresponding class info values.
        lcc = lc_class_info.lcc
        lcc_parent = lc_class_info.parent

        self.txt_cls_name.setText(lcc.name_long)
        self.clr_btn.setColor(QtGui.QColor(lcc.color))
        self.sb_cls_code.setValue(lcc.code)

        idx = self.cbo_cls_parent.findText(lcc_parent.name_long)
        if idx != -1:
            self.cbo_cls_parent.setCurrentIndex(idx)

    def validate(self) -> bool:
        """
        Validates class information specified by user.
        """
        status = True
        self.clear_messages()

        if not self.txt_cls_name.text():
            self.append_warning_msg(self.tr("Class name cannot be empty."))
            status = False

        if not self.clr_btn.color().isValid():
            self.append_warning_msg(self.tr("Invalid color selected."))
            status = False

        if not self.cbo_cls_parent.currentText():
            self.append_warning_msg(self.tr("Parent class cannot be empty."))
            status = False

        code = self.sb_cls_code.value()
        if not code:
            self.append_warning_msg(self.tr("Invalid class code value."))
            status = False

        if code in self.codes and not self.edit_mode:
            self.append_warning_msg(
                self.tr(f"Code value '{code!s}' is already in use.")
            )
            status = False

        return status

    def on_delete_class(self):
        # Slot raised to delete land cover class.
        if self.lc_class_info is None:
            log("No land cover class reference.")
            return

        idx = self.lc_class_info.idx
        if idx < 0:
            log("Invalid land cover class reference.")
            return

        row_num = self.lc_class_info.idx
        self.lc_class_info = None
        self.notify_delete.emit(row_num)
        self.acceptPanel()

    def update_class_info(self) -> bool:
        """
        Updates class info object with widget values.
        """
        status = self.validate()
        if not status:
            return False

        name = self.txt_cls_name.text()
        code = self.sb_cls_code.value()
        color = self.clr_btn.color().name()
        curr_idx = self.cbo_cls_parent.currentIndex()
        parent = self.cbo_cls_parent.itemData(curr_idx)

        lcc = LCClass(code, name, name, color=color)

        if self.lc_class_info is None:
            self.lc_class_info = LCClassInfo()

        self.lc_class_info.lcc = lcc
        self.lc_class_info.parent = parent

        return True

    def set_parent_icon(self, clr: str, idx: int):
        """
        Sets the parent class combobox to show the given color as an icon
        for the item in the given index.
        """
        if isinstance(clr, str):
            clr = QtGui.QColor(clr)

        if not clr.isValid():
            return

        size = self.cbo_cls_parent.iconSize()
        px = QtGui.QPixmap(size)
        p = QtGui.QPainter()
        px.fill(QtCore.Qt.transparent)
        p.begin(px)
        brush = QtGui.QBrush(clr, QtCore.Qt.SolidPattern)
        p.setBrush(brush)
        pen = QtGui.QPen(QtCore.Qt.NoPen)
        p.setPen(pen)
        rect = QtCore.QRect(QtCore.QPoint(0, 0), size)
        p.drawRect(rect)
        p.end()

        icon = QtGui.QIcon(px)
        self.cbo_cls_parent.setItemIcon(idx, icon)

    def _on_parent_changed(self, idx: int):
        # Slot raised when parent index has changed.
        if idx == -1:
            return

        if not self.cbo_cls_parent.currentText():
            return

        parent_lcc = self.cbo_cls_parent.itemData(self.cbo_cls_parent.currentIndex())
        if parent_lcc is None:
            return

        self.set_parent_icon(parent_lcc.color, idx)

    def on_accept_info(self):
        # Slot raised to validate and submit class details to the caller.
        status = self.update_class_info()
        if status:
            self.updated = True
            self.acceptPanel()


class TrendsEarthOptionsFactory(QgsOptionsWidgetFactory):
    def __init__(self):  # pylint: disable=useless-super-delegation
        super().__init__()

        self.dock_widget = None
        self.setTitle(OPTIONS_TITLE)

    def icon(self):  # pylint: disable=missing-function-docstring
        trends_earth_icon = os.path.join(ICON_PATH, OPTIONS_ICON)

        return QIcon(trends_earth_icon)

    def set_dock_widget(self, dock_widget):
        # Widget required to update the title for the dock based
        # on the offline mode state
        self.dock_widget = dock_widget

    def createWidget(self, parent):  # pylint: disable=missing-function-docstring
        return TrendsEarthSettings(self.dock_widget, parent)
