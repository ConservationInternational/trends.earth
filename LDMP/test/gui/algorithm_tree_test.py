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


from PyQt5.QtWidgets import QApplication, QTreeView, QAbstractItemView
from PyQt5.QtTest import QAbstractItemModelTester

from LDMP.models.algorithms import (
       AlgorithmGroup,
       AlgorithmDescriptor,
       AlgorithmRunMode
)
from LDMP.models.algorithms_model import AlgorithmTreeModel
from LDMP.models.algorithms_delegate import AlgorithmItemDelegate

# setup algoriths and it's hierarchy
tree = AlgorithmGroup(name='root', name_details='root detauils', group=None, algorithms=[])
first = AlgorithmGroup(name='firstG', name_details='first details', group=tree, algorithms=[])
second = AlgorithmGroup(name='secondG', name_details='second details', group=tree, algorithms=[])

alg1G1 = AlgorithmDescriptor(name='alg1G1', name_details='alg1G1 details', brief_description='alg1G1 brief descr', description='alg1G1 long description', group=first)
alg1G1.run_mode = AlgorithmRunMode.Both
alg2G1 = AlgorithmDescriptor(name='alg2G1', name_details='alg2G1 details', brief_description='alg2G1 brief descr', description='alg2G1 long description', group=first)
first.algorithms.append(alg1G1)
first.algorithms.append(alg2G1)

alg1G2 = AlgorithmDescriptor(name='alg1G2', name_details='alg1G2 details', brief_description='alg1G2 brief descr', description='alg1G2 long description', group=second)
second.algorithms.append(alg1G2)

app = QApplication(["???"])

tree.algorithms.append(first)
tree.algorithms.append(second)

# show it
algorithmsModel = AlgorithmTreeModel(tree)
QAbstractItemModelTester(algorithmsModel, QAbstractItemModelTester.FailureReportingMode.Warning)

view = QTreeView()
view.setEditTriggers(QAbstractItemView.AllEditTriggers)
view.setModel(algorithmsModel)
view.setWindowTitle("Tree Model")
delegate = AlgorithmItemDelegate(view)
view.setItemDelegate(delegate)
view.show()
app.exec()