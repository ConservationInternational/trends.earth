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


def polyfit(x, y, degree):
    results = {}

    coeffs = np.polyfit(x, y, degree)

     # Polynomial Coefficients
    results['polynomial'] = coeffs.tolist()

    # r-squared
    p = np.poly1d(coeffs)
    # fit values, and mean
    yhat = p(x)                         # or [p(z) for z in x]
    ybar = np.sum(y)/len(y)          # or sum(y)/len(y)
    ssreg = np.sum((yhat-ybar)**2)   # or sum([ (yihat - ybar)**2 for yihat in yhat])
    sstot = np.sum((y - ybar)**2)    # or sum([ (yi - ybar)**2 for yi in y])
    results['determination'] = ssreg / sstot

    return results


class DlgPlotTimeries(DlgPlot):
    def __init__(self, parent=None):
        super(DlgPlotTimeries, self).__init__(parent)

    def plot_data(self, x, y, labels, autoSI=False):
        line = pg.PlotCurveItem(x, y, pen='b', brush='w')
        self.plot_window.addItem(line)

        # Add trendline
        z = polyfit(x, y, 1)
        p = np.poly1d(z['polynomial'])

        trend = pg.PlotCurveItem(x, p(x), pen='r', brush='w')
        self.plot_window.addItem(trend)

        self.plot_window.setBackground('w')
        self.plot_window.showGrid(x=True, y=True)

        legend = pg.LegendItem()
        legend.addItem(line, 'NDVI')
        legend.addItem(trend, self.tr('Linear trend (r<sup>2</sup> = {0:.2f})').format(z['determination']))
        legend.setParentItem(self.plot_window.getPlotItem())
        legend.anchor((1, 0), (1, 0))

        yaxis = self.plot_window.getPlotItem().getAxis('left')
        yaxis.enableAutoSIPrefix(autoSI)

        if labels:
            self.plot_window.setLabels(**labels)


class DlgPlotBars(DlgPlot):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgPlotBars, self).__init__(parent)

    def plot_data(self, x, y, labels, autoSI=False):
        # dict to handle string x-axis labels
        xdict = dict(enumerate(x))

        bg = pg.BarGraphItem(x=xdict.keys(), height=y, width=0.6, brush='b')
        self.plot_window.addItem(bg)
        self.plot_window.setBackground('w')

        xaxis = self.plot_window.getPlotItem().getAxis('bottom')
        xaxis.setTicks([xdict.items()])

        yaxis = self.plot_window.getPlotItem().getAxis('left')
        yaxis.enableAutoSIPrefix(autoSI)

        if labels:
            self.plot_window.setLabels(**labels)
