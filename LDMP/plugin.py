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

from builtins import object
import os

from qgis.core import QgsApplication, QgsMessageLog, Qgis
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QApplication, QMenu, QToolButton
from qgis.PyQt.QtGui import QIcon

from . import (
    about,
    conf,
    log,
    main_widget,
)
from .jobs.manager import job_manager
from .processing_provider.provider import Provider
from .settings import DlgSettings


# Initialize Qt resources from file resources.py
from . import resources


class LDMPPlugin(object):
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)

        self.provider = None

        # Declare instance attributes
        self.actions = []
        self.menu = QMenu(self.tr(u'&Trends.Earth'))
        self.menu.setIcon(QIcon(':/plugins/LDMP/trends_earth_logo_square_32x32.png'))
        self.raster_menu = self.iface.rasterMenu()
        self.raster_menu.addMenu(self.menu)

        self.toolbar = self.iface.addToolBar(u'trends.earth')
        self.toolbar.setObjectName('trends_earth_toolbar')
        self.toolButton = QToolButton()
        self.toolButton.setMenu(QMenu())
        self.toolButton.setPopupMode(QToolButton.MenuButtonPopup)
        self.toolBtnAction = self.toolbar.addWidget(self.toolButton)
        self.actions.append(self.toolBtnAction)

        self.dlg_settings = DlgSettings()
        self.dlg_about = about.DlgAbout()

    def initProcessing(self):
        self.provider = Provider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def tr(self, message):
        return QCoreApplication.translate("plugin", message)
        
    def add_action(
            self,
            icon_path,
            text,
            callback,
            enabled_flag=True,
            add_to_menu=True,
            add_to_toolbar=True,
            set_as_default_action=False,
            status_tip=None,
            whats_this=None,
            parent=None):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param set_as_default_action: Flag indicating whether the action have to be
            set as default shown in the added toolButton menu. Defaults to False.
        :type set_as_default_action: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolButton.menu().addAction(action)

            if set_as_default_action:
                self.toolButton.setDefaultAction(action)

        if add_to_menu:
            self.menu.addAction(action)

        self.actions.append(action)

        return action

    def initGui(self):
        self.initProcessing()

        """Create Main manu icon and plugins menu entries."""
        start_action = self.add_action(
            ':/plugins/LDMP/icons/trends_earth_logo_square_32x32.ico',
            text='Trends.Earth',
            callback=self.run_docked_interface,
            parent=self.iface.mainWindow(),
            status_tip=self.tr('Trends.Earth dock interface'),
            set_as_default_action=True)
        start_action.setCheckable(True)

        self.add_action(
            ':/plugins/LDMP/icons/wrench.svg',
            text=self.tr(u'Settings'),
            callback=self.run_settings,
            parent=self.iface.mainWindow(),
            status_tip=self.tr('Trends.Earth Settings'))

        self.add_action(
            ':/plugins/LDMP/icons/info.svg',
            text=self.tr(u'About'),
            add_to_toolbar=False,
            callback=self.run_about,
            parent=self.iface.mainWindow(),
            status_tip=self.tr('About trends.earth'))

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginRasterMenu(
                self.tr(u'&trends.earth'), action)
            self.iface.removeToolBarIcon(action)
        # remove the menu
        self.raster_menu.removeAction(self.menu.menuAction())
        # remove the toolbar
        del self.toolbar

        QgsApplication.processingRegistry().removeProvider(self.provider)

    def run_docked_interface(self, checked):
        if checked:
            self.dock_widget = main_widget.MainWidget(
                self.iface, parent=self.iface.mainWindow())
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock_widget)
            self.dock_widget.show()
        else:
            if hasattr(self, 'dock_widget') and self.dock_widget.isVisible():
                self.dock_widget.hide()

    def run_settings(self):
        old_base_dir = conf.settings_manager.get_value(conf.Setting.BASE_DIR)
        self.dlg_settings.show()
        self.dlg_settings.exec_()  # TODO: Use open() instead of exec_()
        new_base_dir = conf.settings_manager.get_value(conf.Setting.BASE_DIR)
        if old_base_dir != new_base_dir:
            job_manager.clear_known_jobs()
            if hasattr(self, "dock_widget") and self.dock_widget.isVisible():
                self.dock_widget.refresh_after_cache_update()

    def run_about(self):
        self.dlg_about.show()
        result = self.dlg_about.exec_()
