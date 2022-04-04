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
from builtins import object

from qgis.core import Qgis
from qgis.core import QgsApplication
from qgis.core import QgsExpression
from qgis.core import QgsMessageLog
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtCore import Qt
from qgis.core import (
    QgsApplication,
    QgsMasterLayoutInterface
)
from qgis.gui import QgsLayoutDesignerInterface
from qgis.PyQt.QtCore import (
    QCoreApplication,
    Qt
)
from qgis.PyQt.QtWidgets import (
    QAction,
    QMenu,
    QToolButton
)
from qgis.core import (
    QgsApplication,
    QgsMasterLayoutInterface
)
from qgis.gui import QgsLayoutDesignerInterface
from qgis.PyQt.QtCore import (
    QCoreApplication,
    Qt
)
from qgis.PyQt.QtWidgets import (
    QAction,
    QMenu,
    QToolButton
)
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtWidgets import QApplication
from qgis.PyQt.QtWidgets import QMenu
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.PyQt.QtWidgets import QToolButton

from . import about
from . import conf
from . import main_widget
from .charts import calculate_charts
from .jobs.manager import job_manager
from .maptools import BufferMapTool
from .maptools import PolygonMapTool
from .processing_provider.provider import Provider
from .reports.expressions import ReportExpressionUtils
from .reports.template_manager import template_manager
from .settings import DlgSettings
from .visualization import download_base_map


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
        self.menu = QMenu(self.tr(u"&Trends.Earth"))
        self.menu.setIcon(
            QIcon(
                os.path.join(
                    os.path.dirname(__file__), "trends_earth_logo_square_32x32.png"
                )
            )
        )

        self.raster_menu = None
        self.toolbar = None
        self.toolButton = None
        self.toolBtnAction = None
        self.dlg_about = None
        self.start_action = None
        self.dock_widget = None

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
        parent=None,
    ):
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
        QgsExpression.registerFunction(calculate_charts)

        """
        Moved the initialization here so that the processing can be 
        initialized first thereby enabling the plugin to be used in 
        qgis_process executable for batch processes particularly in 
        report generation.
        """
        self.raster_menu = self.iface.rasterMenu()
        self.raster_menu.addMenu(self.menu)

        self.toolbar = self.iface.addToolBar(u'trends.earth')
        self.toolbar.setObjectName('trends_earth_toolbar')
        self.toolButton = QToolButton()
        self.toolButton.setMenu(QMenu())
        self.toolButton.setPopupMode(QToolButton.MenuButtonPopup)
        self.toolBtnAction = self.toolbar.addWidget(self.toolButton)
        self.actions.append(self.toolBtnAction)
        self.dlg_about = about.DlgAbout()

        # Initialize reports module
        self.init_reports()

        """Create Main manu icon and plugins menu entries."""
        self.start_action = self.add_action(
            os.path.join(
                os.path.dirname(__file__),
                'icons',
                'trends_earth_logo_square_32x32.ico'
            ),
            text='Trends.Earth',
            callback=self.run_docked_interface,
            parent=self.iface.mainWindow(),
            status_tip=self.tr("Trends.Earth dock interface"),
            set_as_default_action=True,
        )
        self.start_action.setCheckable(True)

        self.add_action(
            os.path.join(os.path.dirname(__file__), "icons", "wrench.svg"),
            text=self.tr(u"Settings"),
            callback=self.run_settings,
            parent=self.iface.mainWindow(),
            status_tip=self.tr("Trends.Earth Settings"),
        )

        self.add_action(
            os.path.join(os.path.dirname(__file__), "icons", "info.svg"),
            text=self.tr(u"About"),
            callback=self.run_about,
            parent=self.iface.mainWindow(),
            status_tip=self.tr("About trends.earth"),
        )

        self.action_polygon = QAction(
            QIcon(
                os.path.join(
                    os.path.dirname(__file__), "icons", "mActionCapturePolygon.svg"
                )
            ),
            self.tr(u"Digitize polygon"),
            self.iface.mainWindow(),
        )
        self.action_polygon.triggered.connect(self.activate_polygon_tool)
        self.action_polygon.setCheckable(True)
        # self.action_polygon.setEnabled(False)

        self.action_buffer = QAction(
            QIcon(
                os.path.join(
                    os.path.dirname(__file__), "icons", "mActionCaptureBuffer.svg"
                )
            ),
            self.tr(u"Buffer tool"),
            self.iface.mainWindow(),
        )
        self.action_buffer.triggered.connect(self.activate_buffer_tool)
        self.action_buffer.setCheckable(True)
        # self.action_buffer.setEnabled(False)

        self.polygon_tool = PolygonMapTool(self.iface.mapCanvas())
        self.polygon_tool.setAction(self.action_polygon)
        # self.polygon_tool.digitized.connect()

        self.buffer_tool = BufferMapTool(self.iface.mapCanvas())
        self.buffer_tool.setAction(self.action_buffer)
        # self.buffer_tool.digitized.connect()

        self.toolbar.addActions([self.action_polygon, self.action_buffer])

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginRasterMenu(self.tr(u"&trends.earth"), action)
            self.iface.removeToolBarIcon(action)
        # remove the menu
        self.raster_menu.removeAction(self.menu.menuAction())
        # remove the toolbar
        del self.toolbar

        QgsApplication.processingRegistry().removeProvider(self.provider)
        QgsExpression.unregisterFunction(calculate_charts.name())

    def run_docked_interface(self, checked):
        if checked:
            if self.dock_widget is None:
                self.dock_widget = main_widget.MainWidget(
                    self.iface, parent=self.iface.mainWindow())
                self.iface.addDockWidget(
                    Qt.RightDockWidgetArea,
                    self.dock_widget
                )
                self.dock_widget.visibilityChanged.connect(
                    self.on_dock_visibility_changed
                )
            self.dock_widget.show()
        else:
            if self.dock_widget is not None and self.dock_widget.isVisible():
                self.dock_widget.hide()

    def on_dock_visibility_changed(self, status):
        """
        Check/uncheck start action.
        """
        if status:
            self.start_action.setChecked(True)
        else:
            self.start_action.setChecked(False)

    def run_settings(self):
        old_base_dir = conf.settings_manager.get_value(conf.Setting.BASE_DIR)
        dialog = DlgSettings(self.iface.mainWindow())
        dialog.exec_()
        new_base_dir = conf.settings_manager.get_value(conf.Setting.BASE_DIR)
        if old_base_dir != new_base_dir:
            job_manager.clear_known_jobs()
            if hasattr(self, "dock_widget") and self.dock_widget.isVisible():
                self.dock_widget.refresh_after_cache_update()

    def run_about(self):
        self.dlg_about.show()
        result = self.dlg_about.exec_()

    def activate_polygon_tool(self):
        self.iface.mapCanvas().setMapTool(self.polygon_tool)

    def activate_buffer_tool(self):
        self.iface.mapCanvas().setMapTool(self.buffer_tool)

    def init_reports(self):
        # Initialize report module.
        # Register custom report variables on opening the layout designer
        self.iface.layoutDesignerOpened.connect(
            self.on_layout_designer_opened
        )
        # Copy report config and templates to data directory
        template_manager.use_data_dir_config_source()

        # Download basemap as its required in the reports
        download_base_map(use_mask=False)

    def on_layout_designer_opened(self, designer: QgsLayoutDesignerInterface):
        # Register custom report variables in a print layout only.
        layout_type = designer.masterLayout().layoutType()
        if layout_type == QgsMasterLayoutInterface.PrintLayout:
            layout = designer.layout()
            ReportExpressionUtils.register_variables(layout)

    def init_reports(self):
        # Initialize report module.
        # Register custom report variables on opening the layout designer
        self.iface.layoutDesignerOpened.connect(
            self.on_layout_designer_opened
        )
        # Copy report config and templates to data directory
        template_manager.use_data_dir_config_source()

        # Download basemap as its required in the reports
        download_base_map(use_mask=False)

    def on_layout_designer_opened(self, designer: QgsLayoutDesignerInterface):
        # Register custom report variables in a print layout only.
        layout_type = designer.masterLayout().layoutType()
        if layout_type == QgsMasterLayoutInterface.PrintLayout:
            layout = designer.layout()
            ReportExpressionUtils.register_variables(layout)
