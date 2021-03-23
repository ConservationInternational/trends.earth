"""
/***************************************************************************
 LDMP - A QGIS plugin
 This plugin supports monitoring and reporting of land degradation to the UNCCD 
 and in support of the SDG Land Degradation Neutrality (LDN) target.
                              -------------------
        begin                : 2021-02-25
        git sha              : $Format:%H$
        copyright            : (C) 2017 by Conservation International
        email                : trends.earth@conservation.org
 ***************************************************************************/
"""

__author__ = 'Luigi Pirelli / Kartoza'
__date__ = '2021-03-03'

import os, sys
from datetime import datetime
sys.path.append(os.path.join(os.path.dirname(__file__), "../../../"))


from PyQt5.QtWidgets import QApplication, QTreeView, QAbstractItemView, QHeaderView
from PyQt5.QtTest import QAbstractItemModelTester
from PyQt5.QtGui import (
    QFocusEvent,
    QCursor
)
from PyQt5.QtCore import (
    QModelIndex
)

from LDMP.models.datasets import (
    Dataset,
    Datasets
)
from LDMP.models.algorithms import (
    AlgorithmGroup,
    AlgorithmDescriptor,
    AlgorithmDetails,
    AlgorithmRunMode
)

from LDMP.models.datasets_model import DatasetsModel
from LDMP.models.datasets_delegate import DatasetItemDelegate

# setup algoriths and it's hierarchy
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

# setup datasets link to the available algorithms
tree = Datasets()

date = datetime.strptime('2021-01-20 10:30:00', '%Y-%m-%d %H:%M:%S')
ds1 = Dataset(name='dataset1', creation_date=date, source=alg1G1.name)
ds2 = Dataset(name='dataset2', creation_date=date, source='Downloaded from sample dataset')
ds3 = Dataset(name='dataset3', creation_date=date, source=alg3G1.name)

tree.datasets.append(ds1)
tree.datasets.append(ds2)
tree.datasets.append(ds3)


app = QApplication(["???"])

# show it
datasetsModel = DatasetsModel(tree)
QAbstractItemModelTester(datasetsModel, QAbstractItemModelTester.FailureReportingMode.Warning)

view = QTreeView()
view.setIndentation(0)
view.setMouseTracking(True) # to allow emit entered events and manage editing over mouse
view.setWordWrap(True)
view.setEditTriggers(QAbstractItemView.AllEditTriggers)
view.setModel(datasetsModel)
view.setWindowTitle("Tree Model")
delegate = DatasetItemDelegate(view)
view.setItemDelegate(delegate)
# view.setStyleSheet("QTreeView::item {  border: 10px;  padding: 0 10px; }")
view.show()
app.exec()