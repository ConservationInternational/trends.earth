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

from LDMP.models.algorithms import (
   AlgorithmGroup,
   AlgorithmDescriptor,
   AlgorithmDetails,
   AlgorithmRunMode
)
from LDMP.models.algorithms_model import AlgorithmTreeModel
from LDMP.models.algorithms_delegate import AlgorithmItemDelegate

# setup algoriths and it's hierarchy
tree = AlgorithmGroup(name='root', name_details='root detauils', parent=None, algorithms=[])
first = AlgorithmGroup(name='firstG', name_details='first details', parent=tree, algorithms=[])
second = AlgorithmGroup(name='secondG', name_details='second details', parent=tree, algorithms=[])

alg1G1 = AlgorithmDescriptor(name='alg1G1', name_details='alg1G1 details', brief_description='alg1G1 brief descr', details=None, parent=first)
alg1G1.run_mode = AlgorithmRunMode.Both
alg1G1_details = AlgorithmDetails(name=None, name_details=None, description='alg1G1 long description', parent=alg1G1)
alg1G1.setDetails(alg1G1_details)

alg2G1 = AlgorithmDescriptor(name='alg2G1', name_details='alg2G1 details', brief_description='alg2G1 brief descr', details=None, parent=first)
alg2G1_details = AlgorithmDetails(name=None, name_details=None, description='alg2G1 long description', parent=alg2G1)
alg2G1.setDetails(alg2G1_details)

first.algorithms.append(alg1G1)
first.algorithms.append(alg2G1)

alg1G2 = AlgorithmDescriptor(name='alg1G2', name_details='alg1G2 details', brief_description='alg1G2 brief descr', details=None, parent=second)
alg1G2_details = AlgorithmDetails(name=None, name_details=None, description='alg1G2 long description', parent=alg1G2)
alg1G2.setDetails(alg1G2_details)

second.algorithms.append(alg1G2)

app = QApplication(["???"])

tree.algorithms.append(first)
tree.algorithms.append(second)

# show it
algorithmsModel = AlgorithmTreeModel(tree)
QAbstractItemModelTester(algorithmsModel, QAbstractItemModelTester.FailureReportingMode.Warning)

view = QTreeView()
view.mouseMoveEvent
view.setMouseTracking(True) # to allow emit entered events and manage editing over mouse
view.setEditTriggers(QAbstractItemView.AllEditTriggers)
view.setModel(algorithmsModel)
view.setWindowTitle("Tree Model")
delegate = AlgorithmItemDelegate(view)
view.setItemDelegate(delegate)
view.show()
app.exec()