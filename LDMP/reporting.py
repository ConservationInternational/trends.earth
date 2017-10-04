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
from PyQt4.QtCore import QSettings

from LDMP.calculate import DlgCalculateBase
from LDMP.gui.DlgReporting import Ui_DlgReporting
from LDMP.gui.DlgReportingSDG import Ui_DlgReportingSDG
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

        self.btn_sdg.clicked.connect(self.clicked_sdg)
        self.btn_unccd_prod.clicked.connect(self.clicked_unccd_prod)
        self.btn_unccd_lc.clicked.connect(self.clicked_unccd_lc)
        self.btn_unccd_soc.clicked.connect(self.clicked_unccd_soc)

    def clicked_sdg(self):
        self.close()
        self.dlg_sdg.exec_()

    def clicked_unccd_prod(self):
        self.close()
        self.dlg_unncd_prod.exec_()

    def clicked_unccd_lc(self):
        self.close()
        result = self.dlg_unncd_lc.exec_()

    def clicked_unccd_soc(self):
        QMessageBox.critical(None, QApplication.translate('LDMP', "Error"),
                QApplication.translate('LDMP', "Raw data download coming soon!"), None)
        # self.close()
        # self.dlg_unncd_soc.exec_()

class DlgReportingSDG(DlgCalculateBase, Ui_DlgReportingSDG):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgReportingSDG, self).__init__(parent)
        self.setupUi(self)
        self.setup_dialog()

        self.browse_traj.clicked.connect(self.open_browse_traj)
        self.browse_perf.clicked.connect(self.open_browse_perf)
        self.browse_state.clicked.connect(self.open_browse_state)
        self.browse_lc.clicked.connect(self.open_browse_lc)
        self.browse_output.clicked.connect(self.open_browse_output)

    def open_browse_traj(self):
        shpfile = QtGui.QFileDialog.getOpenFileName()
        self.file_traj.setText(shpfile)

    def open_browse_perf(self):
        shpfile = QtGui.QFileDialog.getOpenFileName()
        self.file_perf.setText(shpfile)

    def open_browse_state(self):
        shpfile = QtGui.QFileDialog.getOpenFileName()
        self.file_state.setText(shpfile)

    def open_browse_lc(self):
        shpfile = QtGui.QFileDialog.getOpenFileName()
        self.file_lc.setText(shpfile)

    def open_browse_output(self):
        output_dir = QtGui.QFileDialog.getExistingDirectory(self, 
                self.tr("Directory to save files"),
                QSettings.value("LDMP/output_dir", None),
                QtGui.QFileDialog.ShowDirsOnly)
        if output_dir:
            if os.access(output_dir, os.W_OK):
                QSettings.setValue("LDMP/output_dir", output_dir)
                log("outputing results to {}".format(output_dir))
            else:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                        self.tr("Cannot write to {}. Choose a different folder.".format(output_dir), None))
        self.folder_output.setText(output_dir)

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
