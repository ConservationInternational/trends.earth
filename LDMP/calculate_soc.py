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

from qgis.utils import iface
mb = iface.messageBar()

from LDMP import log
from LDMP.calculate import DlgCalculateBase
from LDMP.gui.DlgCalculateSOC import Ui_DlgCalculateSOC

# Number of classes in land cover dataset
NUM_CLASSES = 7

class DlgCalculateSOC(DlgCalculateBase, Ui_DlgCalculateSOC):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgCalculateSOC, self).__init__(parent)

        self.setupUi(self)
