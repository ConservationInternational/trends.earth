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
import numpy as np

import pyqtgraph as pg

from PyQt4 import QtGui

from LDMP import log
from LDMP.gui.DlgPlot import Ui_DlgPlot as UiDialog

class DlgPlot(QtGui.QDialog, UiDialog):
    def __init__(self, parent=None):
        super(DlgPlot, self).__init__(parent)
        self.setupUi(self)

        self.save_data.clicked.connect(self.save_data_clicked)
        self.save_image.clicked.connect(self.save_image_clicked)

        #TODO: Temporary
        self.save_data.hide()
        self.save_image.hide()

    def save_data_clicked(self):
        pass

    def save_image_clicked(self):
        pass

class DlgPlotTimeries(DlgPlot):
    def __init__(self, parent=None):
        super(DlgPlotTimeries, self).__init__(parent)

    def plot_data(self, x, y, title=None):
        self.plot_window.plot(x, y, pen='b', brush='w')
        # Add trendline
        z = np.polyfit(x, y, 1)
        p = np.poly1d(z)
        self.plot_window.plot(x, p(x), pen='r', brush='w')
        self.plot_window.setBackground('w')
        self.plot_window.showGrid(x=True, y=True)
        if title:
            self.plot_window.setTitle(title)

class DlgPlotBars(DlgPlot):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgPlotBars, self).__init__(parent)
    
    def plot_data(self, x, y, title=None):
        # dict to handle string x-axis labels
        xdict = dict(enumerate(x))

        bg = pg.BarGraphItem(x=xdict.keys(), height=y, width=0.6, brush='b')
        self.plot_window.addItem(bg)
        self.plot_window.setBackground('w')

        xaxis = self.plot_window.getPlotItem().getAxis('bottom')
        xaxis.setTicks([xdict.items()])

        if title:
            self.plot_window.setTitle(title)
