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
        self.treeView_datasets.verticalScrollBar().setSingleStep(10)

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
        date_ = datetime.strptime('2021-01-20 10:30:00', '%Y-%m-%d %H:%M:%S')
        datasets = Datasets(
            [
                Dataset('1dataset1', date_, 'Land productivity', run_id='run_id_1'),
                Dataset('2dataset2', date_, 'Downloaded from sample dataset', run_id='run_id_2'),
                Dataset('3dataset3', date_, 'Land change', run_id='run_id_3'),
                Dataset('11Productivity Trajectory1', date_, 'Land Productivity (SDG 15.3.1 sub-indicator1)', run_id='run_id_4'),
                Dataset('22Productivity Trajectory2', date_, 'Land Productivity (SDG 15.3.1 sub-indicator1)', run_id='run_id_5'),
                Dataset('33Productivity Trajectory3', date_, 'Land Productivity (SDG 15.3.1 sub-indicator1)', run_id='run_id_6'),
                Dataset('44Productivity Trajectory4', date_, 'Land Productivity (SDG 15.3.1 sub-indicator1)', run_id='run_id_7'),
                Dataset('55Productivity Trajectory5', date_, 'Land Productivity (SDG 15.3.1 sub-indicator1)', run_id='run_id_8'),
                Dataset('66Productivity Trajectory6', date_, 'Land Productivity (SDG 15.3.1 sub-indicator1)', run_id='run_id_9'),
                Dataset(
                    '111 A very very very  much much big name with a lot of many many many many words',
                    date_,
                    'Land Productivity (SDG 15.3.1 sub-indicator1)', run_id='run_id_10'
                ),
                Dataset(
                    '222 A very very very  much much big name with a lot of many many many many words',
                    date_,
                    'A very very very  much much big name with a lot of many many many many words', run_id='run_id_11'
                ),
            ]
        )

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
        land_degradation_group = AlgorithmGroup(name=tr('SDG 15.3.1'), name_details=tr('Land degradation'), parent=tree, algorithms=[])
        urban_change_group = AlgorithmGroup(name=tr('SDG 11.3.1'), name_details=tr('Urban change and land consumption'), parent=tree, algorithms=[])
        experimental = AlgorithmGroup(name=tr('Experimental'), name_details=None, parent=tree, algorithms=[])
        total_carbon_group = AlgorithmGroup(name=tr('Total carbon'), name_details=tr('above and belowground, emissions and deforestation'), parent=experimental, algorithms=[])
        potential_change_group = AlgorithmGroup(name=tr('Potential change in biomass due to restoration'), name_details=tr('above and belowground woody'), parent=experimental, algorithms=[])

        # land_degradation_group
        land_roductivity_alg = AlgorithmDescriptor(name=tr('Land productivity'), name_details=None, brief_description=None, details=None, parent=land_degradation_group)
        land_roductivity_alg.run_mode = AlgorithmRunMode.Remotely
        land_roductivity_alg_details = AlgorithmDetails(name=None, name_details=None, description=tr('TODO: Land productivity long description'), parent=land_roductivity_alg)
        land_roductivity_alg.setDetails(land_roductivity_alg_details)

        land_cover_alg = AlgorithmDescriptor(name=tr('Land cover'), name_details=None, brief_description=None, details=None, parent=land_degradation_group)
        land_cover_alg.run_mode = AlgorithmRunMode.Remotely
        land_cover_alg_details = AlgorithmDetails(name=None, name_details=None, description=tr('TODO: Land cover long description'), parent=land_cover_alg)
        land_cover_alg.setDetails(land_cover_alg_details)

        soil_organic_carbon_alg = AlgorithmDescriptor(name=tr('Soil organic carbon'), name_details=None, brief_description=None, details=None, parent=land_degradation_group)
        soil_organic_carbon_alg.run_mode = AlgorithmRunMode.Remotely
        soil_organic_carbon_alg_details = AlgorithmDetails(name=None, name_details=None, description=tr('TODO: Soil organic carbon long description'), parent=soil_organic_carbon_alg)
        soil_organic_carbon_alg.setDetails(soil_organic_carbon_alg_details)

        all_land_degradation_alg = AlgorithmDescriptor(name=tr('All above sub-indicators in one step'), name_details=None, brief_description=None, details=None, parent=land_degradation_group)
        all_land_degradation_alg.run_mode = AlgorithmRunMode.Remotely
        all_land_degradation_alg_details = AlgorithmDetails(name=None, name_details=None, description=tr('TODO: All abovesub-indicators in one step long description'), parent=all_land_degradation_alg)
        all_land_degradation_alg.setDetails(all_land_degradation_alg_details)

        final_alg = AlgorithmDescriptor(name=tr('Final SDG 15.3.1'), name_details=tr('Spatial layer and summary table for total boundary'), brief_description=None, details=None, parent=land_degradation_group)
        final_alg.run_mode = AlgorithmRunMode.Locally
        final_alg_details = AlgorithmDetails(name=None, name_details=None, description=tr('TODO: All sub-indicators in one step long description'), parent=final_alg)
        final_alg.setDetails(final_alg_details)

        area_summaries_alg = AlgorithmDescriptor(name=tr('Area summaries of a raster on sub-units'), name_details=None, brief_description=None, details=None, parent=land_degradation_group)
        area_summaries_alg.run_mode = AlgorithmRunMode.Locally
        area_summaries_alg_details = AlgorithmDetails(name=None, name_details=None, description=tr('TODO: Area summaries long description'), parent=area_summaries_alg)
        area_summaries_alg.setDetails(area_summaries_alg_details)

        land_degradation_group.algorithms.append(land_roductivity_alg)
        land_degradation_group.algorithms.append(land_cover_alg)
        land_degradation_group.algorithms.append(soil_organic_carbon_alg)
        land_degradation_group.algorithms.append(all_land_degradation_alg)
        land_degradation_group.algorithms.append(final_alg)
        land_degradation_group.algorithms.append(area_summaries_alg)

        # urban_change_group
        urban_change_alg = AlgorithmDescriptor(name=tr('Urban change spatial layer'), name_details=None, brief_description=None, details=None, parent=urban_change_group)
        urban_change_alg.run_mode = AlgorithmRunMode.Both
        urban_change_alg_details = AlgorithmDetails(name=None, name_details=None, description=tr('TODO: Urban change spatial layer long description'), parent=urban_change_alg)
        urban_change_alg.setDetails(urban_change_alg_details)

        urban_change_summary_alg = AlgorithmDescriptor(name=tr('Urban change summary table for city'), name_details=None, brief_description=None, details=None, parent=urban_change_group)
        urban_change_summary_alg.run_mode = AlgorithmRunMode.Both
        urban_change_summary_alg_details = AlgorithmDetails(name=None, name_details=None, description=tr('TODO: Urban change summary table for city long description'), parent=urban_change_summary_alg)
        urban_change_summary_alg.setDetails(urban_change_summary_alg_details)

        urban_change_group.algorithms.append(urban_change_alg)
        urban_change_group.algorithms.append(urban_change_summary_alg)

        # total_carbon_group
        carbon_change_alg = AlgorithmDescriptor(name=tr('Carbon change spatial layers'), name_details=None, brief_description=None, details=None, parent=total_carbon_group)
        carbon_change_alg.run_mode = AlgorithmRunMode.Remotely
        carbon_change_alg_details = AlgorithmDetails(name=None, name_details=None, description=tr('TODO: Carbon change spatial layers long description'), parent=carbon_change_alg)
        carbon_change_alg.setDetails(carbon_change_alg_details)

        carbon_change_summary_alg = AlgorithmDescriptor(name=tr('Carbon change summary table for boundary'), name_details=None, brief_description=None, details=None, parent=total_carbon_group)
        carbon_change_summary_alg.run_mode = AlgorithmRunMode.Remotely
        carbon_change_summary_alg_details = AlgorithmDetails(name=None, name_details=None, description=tr('TODO: Carbon change summary table for boundary long description'), parent=carbon_change_summary_alg)
        carbon_change_summary_alg.setDetails(carbon_change_summary_alg_details)

        total_carbon_group.algorithms.append(carbon_change_alg)
        total_carbon_group.algorithms.append(carbon_change_summary_alg)
        experimental.algorithms.append(total_carbon_group)

        # potential_change_group
        estimate_biomass_change_alg = AlgorithmDescriptor(name=tr('Estimate biomass change'), name_details=None, brief_description=None, details=None, parent=potential_change_group)
        estimate_biomass_change_alg.run_mode = AlgorithmRunMode.Remotely
        estimate_biomass_change_alg_details = AlgorithmDetails(name=None, name_details=None, description=tr('TODO: Estimate biomass change long description'), parent=estimate_biomass_change_alg)
        estimate_biomass_change_alg.setDetails(estimate_biomass_change_alg_details)

        estimate_biomass_summary_alg = AlgorithmDescriptor(name=tr('Table summarizing likely changes in biomass'), name_details=None, brief_description=None, details=None, parent=potential_change_group)
        estimate_biomass_summary_alg.run_mode = AlgorithmRunMode.Remotely
        estimate_biomass_summary_alg_details = AlgorithmDetails(name=None, name_details=None, description=tr('TODO: Table summarizing likely changes in biomass long description'), parent=estimate_biomass_summary_alg)
        estimate_biomass_summary_alg.setDetails(estimate_biomass_summary_alg_details)

        potential_change_group.algorithms.append(estimate_biomass_change_alg)
        potential_change_group.algorithms.append(estimate_biomass_summary_alg)
        experimental.algorithms.append(potential_change_group)

        # populate tree
        tree.algorithms.append(land_degradation_group)
        tree.algorithms.append(urban_change_group)
        tree.algorithms.append(experimental)

        # set stylesheet for tree view
        style = """
            QTreeView::item:hover,
            QTreeView::item:disabled:hover,
            QTreeView::item:hover:!active, { background: transparent; background-color: transparent }
            QTreeView::item:disabled { background: transparent; background-color: transparent }
        """
        self.treeView_algorithms.setStyleSheet(style)

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
