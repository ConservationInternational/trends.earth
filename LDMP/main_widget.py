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
from LDMP.models.algorithms import AlgorithmGroup, AlgorithmDescriptor, AlgorithmRunMode
from LDMP.models.algorithms_model import AlgorithmTreeModel
from LDMP.models.algorithms_delegate import AlgorithmItemDelegate

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
        self.setupAlgorithmsTree()

    def setupAlgorithmsTree(self):
        # setup algorithms and their hierarchy
        tree = AlgorithmGroup(name='root', name_details='root details', group=None, algorithms=[])
        first = AlgorithmGroup(name='firstG', name_details='first details', group=tree, algorithms=[])
        second = AlgorithmGroup(name='secondG', name_details='second details', group=tree, algorithms=[])

        alg1G1 = AlgorithmDescriptor(name='alg1G1', name_details='alg1G1 details', brief_description='alg1G1 brief descr', description='alg1G1 long description', group=first)
        alg1G1.run_mode = AlgorithmRunMode.Both
        alg2G1 = AlgorithmDescriptor(name='alg2G1', name_details='alg2G1 details', brief_description='alg2G1 brief descr', description='alg2G1 long description', group=first)
        first.algorithms.append(alg1G1)
        first.algorithms.append(alg2G1)

        alg1G2 = AlgorithmDescriptor(name='alg1G2', name_details='alg1G2 details', brief_description='alg1G2 brief descr', description='alg1G2 long description', group=second)
        alg1G2.run_mode = AlgorithmRunMode.Both
        second.algorithms.append(alg1G2)

        tree.algorithms.append(first)
        tree.algorithms.append(second)

        # show it
        algorithmsModel = AlgorithmTreeModel(tree)
        self.treeView_algorithms.setModel(algorithmsModel)
        delegate = AlgorithmItemDelegate(self.treeView_algorithms)
        self.treeView_algorithms.setItemDelegate(delegate)

        # configure View how to enter editing mode
        self.treeView_algorithms.setEditTriggers(QtWidgets.QAbstractItemView.AllEditTriggers)


    def closeEvent(self, event):
        super(MainWidget, self).closeEvent(event)

    def showEvent(self, event):
        super(MainWidget, self).showEvent(event)
