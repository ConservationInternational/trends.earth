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

from qgis.PyQt import QtWidgets
from qgis.core import QgsSettings

from LDMP import __version__, log
from LDMP.message_bar import MessageBar
from LDMP.gui.WidgetMain import Ui_dockWidget_trends_earth

settings = QgsSettings()

_widget = None


def get_trends_earth_dockwidget():
    global _widget
    if _widget is None:
        _widget = MainWidget()
    return _widget


class MainWidget(QtWidgets.QDockWidget, Ui_dockWidget_trends_earth):
    def __init__(self, parent=None):
        super(MainWidget, self).__init__(parent)

        self.setupUi(self)

    def closeEvent(self, event):
        super(MainWidget, self).closeEvent(event)

    def showEvent(self, event):
        super(MainWidget, self).showEvent(event)