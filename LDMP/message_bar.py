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

from qgis.gui import QgsMessageBar
from qgis.utils import iface
from LDMP import singleton

@singleton
class MessageBar(object):

    def __init__ (self):
        self.reset()

    def init(self):
        self._message_bar_ = QgsMessageBar()

    def get(self):
        return self._message_bar_
    
    def reset(self):
        self._message_bar_ = iface.messageBar()
