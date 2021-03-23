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

from datetime import datetime

from qgis.PyQt import QtWidgets, QtGui
from qgis.core import QgsSettings

from LDMP import __version__, log
from LDMP.message_bar import MessageBar
from LDMP.gui.WidgetMain import Ui_dockWidget_trends_earth
from LDMP.models.algorithms import (
    AlgorithmGroup,
    AlgorithmDescriptor,
    AlgorithmRunMode,
    AlgorithmDetails
)
from LDMP.models.datasets import (
    Dataset,
    Datasets
)
from LDMP.models.algorithms_model import AlgorithmTreeModel
from LDMP.models.algorithms_delegate import AlgorithmItemDelegate

from LDMP.models.datasets_model import DatasetsModel
from LDMP.models.datasets_delegate import DatasetItemDelegate
from LDMP import tr

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
        # remove space before dataset item
        self.treeView_datasets.setIndentation(0)

        self.setupAlgorithmsTree()
        self.setupDatasets()

    def setupDatasets(self):
        # add sort actions
        self.toolButton_sort.setMenu(QtWidgets.QMenu())

        # add action entries of the pull down menu
        byNameSortAction = QtWidgets.QAction(tr('Name'), self)
        self.toolButton_sort.menu().addAction(byNameSortAction)
        self.toolButton_sort.setDefaultAction(byNameSortAction)
        byDateSortAction = QtWidgets.QAction(tr('Date'), self)
        self.toolButton_sort.menu().addAction(byDateSortAction)

        # set icons
        icon = QtGui.QIcon(':/plugins/LDMP/icons/mActionRefresh.svg')
        self.pushButton_refresh.setIcon(icon)
        icon = QtGui.QIcon(':/plugins/LDMP/icons/cloud-download.svg')
        self.pushButton_import.setIcon(icon)
        icon = QtGui.QIcon(':/plugins/LDMP/icons/mActionSharingImport.svg')
        self.pushButton_download.setIcon(icon)

        # example of datasets
        datasets = Datasets()

        date = datetime.strptime('2021-01-20 10:30:00', '%Y-%m-%d %H:%M:%S')
        ds1 = Dataset(name='dataset1', creation_date=date, source='Land productivity')
        ds2 = Dataset(name='dataset2', creation_date=date, source='Downloaded from sample dataset')
        ds3 = Dataset(name='dataset3', creation_date=date, source='Land change')

        datasets.datasets.append(ds1)
        datasets.datasets.append(ds2)
        datasets.datasets.append(ds3)

        # show it
        datasetsModel = DatasetsModel(datasets)
        self.treeView_datasets.setMouseTracking(True) # to allow emit entered events and manage editing over mouse
        self.treeView_datasets.setWordWrap(True) # add ... to wrap DisplayRole text... to have a real wrap need a custom widget
        self.treeView_datasets.setModel(datasetsModel)
        delegate = DatasetItemDelegate(self.treeView_datasets)
        self.treeView_datasets.setItemDelegate(delegate)

        # configure View how to enter editing mode
        self.treeView_datasets.setEditTriggers(QtWidgets.QAbstractItemView.AllEditTriggers)


    def setupAlgorithmsTree(self):
        # setup algorithms and their hierarchy
        tree = AlgorithmGroup(name='root', name_details='root details', parent=None, algorithms=[])
        first = AlgorithmGroup(name='Proportion of land that is degradated over total land area', name_details='SDG 15.3.1', parent=tree, algorithms=[])
        second = AlgorithmGroup(name='Ratio of land consumption rate to population growth rate', name_details='SDG 11.3.1', parent=tree, algorithms=[])
        third = AlgorithmGroup(name='Miscellaneous', name_details=None, parent=tree, algorithms=[])

        alg1G1 = AlgorithmDescriptor(name='Land productivity', name_details='sub-indicator 1', brief_description=None, details=None, parent=first)
        alg1G1.run_mode = AlgorithmRunMode.Both
        alg1G1_details = AlgorithmDetails(name=None, name_details=None, description='alg1G1 long description', parent=alg1G1)
        alg1G1.setDetails(alg1G1_details)

        alg2G1 = AlgorithmDescriptor(name='Land productivity based on JRC LDP', name_details='sub-indicator 1', brief_description=None, details=None, parent=first)
        alg2G1.run_mode = AlgorithmRunMode.Locally
        alg2G1_details = AlgorithmDetails(name=None, name_details=None, description='alg2G1 long description', parent=alg2G1)
        alg2G1.setDetails(alg2G1_details)

        alg3G1 = AlgorithmDescriptor(name='Land change', name_details='sub-indicator 2', brief_description=None, details=None, parent=first)
        alg3G1.run_mode = AlgorithmRunMode.Remotely
        # no details here!

        alg4G1 = AlgorithmDescriptor(name='Carbon soil', name_details='sub-indicator 3', brief_description=None, details=None, parent=first)
        alg4G1.run_mode = AlgorithmRunMode.NotApplicable
        alg4G1_details = AlgorithmDetails(name=None, name_details=None, description='alg4G1 long description', parent=alg4G1)
        alg4G1.setDetails(alg4G1_details)

        alg5G1 = AlgorithmDescriptor(name='Land degradation neutrality', name_details='main SDG 15.3.1 indicator', brief_description=None, details=None, parent=first)
        alg5G1.run_mode = AlgorithmRunMode.Both
        alg5G1_details = AlgorithmDetails(name=None, name_details=None, description='This is the main dindicator that bla bla bla bla bla', parent=alg5G1)
        alg5G1.setDetails(alg5G1_details)

        first.algorithms.append(alg1G1)
        first.algorithms.append(alg2G1)
        first.algorithms.append(alg3G1)
        first.algorithms.append(alg4G1)
        first.algorithms.append(alg5G1)

        alg1G2 = AlgorithmDescriptor(name='alg1G2', name_details='alg1G2 details', brief_description=None, details=None, parent=second)
        alg1G2.run_mode = AlgorithmRunMode.Both
        alg1G2_details = AlgorithmDetails(name=None, name_details=None, description='This is the second dindicator that bla bla bla bla bla', parent=alg1G2)
        alg1G2.setDetails(alg1G2_details)
        second.algorithms.append(alg1G2)

        alg1G3 = AlgorithmDescriptor(name='alg1G3', name_details='alg1G3 details', brief_description=None, details=None, parent=third)
        alg1G3.run_mode = AlgorithmRunMode.NotApplicable
        alg1G3_details = AlgorithmDetails(name=None, name_details=None, description='This is description for miscellaneous stuffs', parent=alg1G3)
        alg1G3.setDetails(alg1G3_details)
        third.algorithms.append(alg1G3)


        tree.algorithms.append(first)
        tree.algorithms.append(second)
        tree.algorithms.append(third)

        # show it
        algorithmsModel = AlgorithmTreeModel(tree)
        self.treeView_algorithms.setMouseTracking(True) # to allow emit entered events and manage editing over mouse
        self.treeView_algorithms.setWordWrap(True) # add ... to wrap DisplayRole text... to have a real wrap need a custom widget
        self.treeView_algorithms.setModel(algorithmsModel)
        delegate = AlgorithmItemDelegate(self.treeView_algorithms)
        self.treeView_algorithms.setItemDelegate(delegate)

        # configure View how to enter editing mode
        self.treeView_algorithms.setEditTriggers(QtWidgets.QAbstractItemView.AllEditTriggers)


    def closeEvent(self, event):
        super(MainWidget, self).closeEvent(event)

    def showEvent(self, event):
        super(MainWidget, self).showEvent(event)
