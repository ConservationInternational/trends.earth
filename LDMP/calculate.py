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

from PyQt4 import QtGui

from LDMP.gui.DlgCalculate import Ui_DlgCalculate as UiDialog

from LDMP.calculate_prod import DlgCalculateProd
from LDMP.calculate_lc import DlgCalculateLC

class DlgCalculate(QtGui.QDialog, UiDialog):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgCalculate, self).__init__(parent)
        self.setupUi(self)

        self.dlg_calculate_prod = DlgCalculateProd()
        self.dlg_calculate_lc = DlgCalculateLC()

        self.btn_prod.clicked.connect(self.btn_prod_clicked)
        self.btn_lc.clicked.connect(self.btn_lc_clicked)
        self.btn_soc.clicked.connect(self.btn_soc_clicked)

    def btn_prod_clicked(self):
        self.close()
        result = self.dlg_calculate_prod.exec_()

    def btn_lc_clicked(self):
        self.close()
        result = self.dlg_calculate_lc.exec_()

    def btn_soc_clicked(self):
        QtGui.QMessageBox.critical(None, self.tr("Error"),
                self.tr("SOC indicator calculation coming soon!"), None)
