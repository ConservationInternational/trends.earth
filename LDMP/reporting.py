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

from PyQt4 import QtGui, uic

from LDMP.gui.DlgReporting import Ui_DlgReporting
from LDMP.gui.DlgReportingUNCCDSDG import Ui_DlgReportingSDG
from LDMP.gui.DlgReportingUNCCDProd import Ui_DlgReportingUNCCDProd
from LDMP.gui.DlgReportingUNCCDLC import Ui_DlgReportingUNCCDLC
from LDMP.gui.DlgReportingUNCCDSOC import Ui_DlgReportingUNCCDSOC

class DlgReporting(QtGui.QDialog, Ui_DlgReporting):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgReporting, self).__init__(parent)
        self.setupUi(self)

        self.dlg_sdg = DlgReportingSDG()
        self.dlg_unncd_prod = DlgReportingUNCCDProd()
        self.dlg_unncd_lc = DlgReportingUNCCDLC()
        self.dlg_unncd_soc = DlgReportingUNCCDSOC()

        self.btn_sdg.clicked.connect(clicked_sdg)
        self.btn_unccd_prod.clicked.connect(clicked_unccd_prod)
        self.btn_unccd_lc.clicked.connect(clicked_unccd_lc)
        self.btn_unccd_soc.clicked.connect(clicked_unccd_soc)

    def clicked_sdg(self):
        result = self.dlg_sdg.exec_()
        # See if OK was pressed
        if result:
            self.close()

    def clicked_unccd_prod(self):
        result = self.dlg_unncd_prod.exec_()
        # See if OK was pressed
        if result:
            self.close()

    def clicked_unccd_lc(self):
        result = self.dlg_unncd_lc.exec_()
        # See if OK was pressed
        if result:
            self.close()

    def clicked_unccd_soc(self):
        QMessageBox.critical(None, QApplication.translate('LDMP', "Error"),
                QApplication.translate('LDMP', "Raw data download coming soon!"), None)
        # result = self.dlg_unncd_soc.exec_()
        # # See if OK was pressed
        # if result:
        #     self.close()

class DlgReportingSDG(QtGui.QDialog, Ui_DlgReportingSDG):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgReportingSDG, self).__init__(parent)
        self.setupUi(self)

    def calc_degradation(self):
        # Set a colormap centred on zero, going to the extreme value 
        # significant to three figures (after a 2 percent stretch)
        ds = gdal.Open(outfile) 
        band1 = np.array(ds.GetRasterBand(1).ReadAsArray()) 
        band1[band1 >=9997] = 0
        ds = None
        cutoffs = np.percentile(band1, [2, 98])
        extreme = get_extreme(cutoffs[0], cutoffs[1])

        fcn = QgsColorRampShader()

class DlgReportingUNCCDProd(QtGui.QDialog, Ui_DlgReportingUNCCDProd):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgReportingUNCCDProd, self).__init__(parent)
        self.setupUi(self)

class DlgReportingUNCCDLC(QtGui.QDialog, Ui_DlgReportingUNCCDLC):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgReportingUNCCDLC, self).__init__(parent)
        self.setupUi(self)

class DlgReportingUNCCDSOC(QtGui.QDialog, Ui_DlgReportingUNCCDSOC):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgReportingUNCCDSOC, self).__init__(parent)
        self.setupUi(self)
