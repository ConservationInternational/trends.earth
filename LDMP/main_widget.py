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

import os
from datetime import datetime
from _functools import partial

from qgis.core import Qgis
from qgis.PyQt import QtWidgets, QtGui, QtCore
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

from LDMP.jobs import Jobs
from LDMP.models.datasets import (
    Dataset,
    Datasets
)
from LDMP.models.algorithms_model import AlgorithmTreeModel
from LDMP.models.algorithms_delegate import AlgorithmItemDelegate

from LDMP.models.datasets_model import DatasetsModel, DatasetsSortFilterProxyModel, SortField
from LDMP.models.datasets_delegate import DatasetItemDelegate
from LDMP import tr

# used only as container of callback. Dialog will be never shown
from LDMP.calculate import (
    DlgCalculateLD,
    DlgCalculateTC,
    DlgCalculateRestBiomass,
    DlgCalculateUrban
)

from LDMP.download_data import DlgDownload
from LDMP.data_io import DlgDataIO

from LDMP.visualization import DlgVisualizationBasemap

settings = QgsSettings()

_widget = None


def get_trends_earth_dockwidget(plugin):
    global _widget
    if _widget is None:
        _widget = MainWidget(plugin=plugin)
    return _widget


class MainWidget(QtWidgets.QDockWidget, Ui_dockWidget_trends_earth):
    def __init__(self, plugin=None, parent=None):
        super(MainWidget, self).__init__(parent)
        self.plugin = plugin

        self.setupUi(self)

        # remove space before dataset item
        self.treeView_datasets.setIndentation(0)
        self.treeView_datasets.verticalScrollBar().setSingleStep(10)

        # instantiate calcluate callback container to reuse most of old code
        # do this before setting setupAlgorithmsTree
        self.dlg_calculate_LD = DlgCalculateLD()
        self.dlg_calculate_TC = DlgCalculateTC()
        self.dlg_calculate_Biomass = DlgCalculateRestBiomass()
        self.dlg_calculate_Urban = DlgCalculateUrban()

        self.message_bar_sort_filter = None
        # setup Jobs singleton store and all update mechanisms
        # self.jobs = Jobs()

        # setup Datasets and Jobs singleton store and Model update mechanism
        Jobs().updated.connect(self.updateDatasetsModel)
        Datasets().updated.connect(self.updateDatasetsModel)

        self.cleanEmptyFolders()
        self.setupAlgorithmsTree()
        self.setupDatasetsGui()
        self.updateDatasetsBasedOnJobs()

    def cleanEmptyFolders(self):
        """Remove andy Job or Dataset empty folder. Job or Dataset folder can be empty 
        due to delete action by the user.
        """
        base_data_directory = QtCore.QSettings().value("trends_earth/advanced/base_data_directory", None, type=str)
        if not base_data_directory:
            return

        def clean(folders):
            for folder in folders:
                # floder leaf is empty if ('folder', [], [])
                if ( not folder[1] and
                     not folder[2] ):
                    os.rmdir(folder[0])


        # remove empty Jobs folders
        jobs_path = os.path.join(base_data_directory, 'Jobs')
        folders = list(os.walk(jobs_path))[1:]
        clean(folders)

        # remove empty Datasets folders
        datasets_path = os.path.join(base_data_directory, 'outputs')
        folders = list(os.walk(datasets_path))[1:]
        clean(folders)

    def updateDatasetsBasedOnJobs(self):
        """Sync Datasets basing on available Jobs.
        The conditions are:
        - If Job.progress < 100 => generate and dumps related Datasets
        - If Job.progress == 100 && if related datasets is not downloaded => generate and dumps related Datasets
        """
        # update Jobs getting them from cached
        Jobs().sync()
        for job in Jobs().classes():
            if job.progress == 100:
                # TODO: check if dataset is in downloading or downloaded e.g. available = true
                available = False
                if available:
                    continue

            Datasets().appendFromJob(job)

        # add any other datasets available
        Datasets().sync()

    def setupDatasetsGui(self):
        # add sort actions
        self.toolButton_sort.setMenu(QtWidgets.QMenu())
        sort_fields = {
            SortField.NAME: "Name",
            SortField.DATE: "Date",
            SortField.ALGORITHM: "Algorithm",
            SortField.STATUS: "Status",
        }
        self.toolButton_sort.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
        self.toolButton_sort.setMenu(QtWidgets.QMenu())

        for field_type, text in sort_fields.items():
            sort_action = QtWidgets.QAction(tr(text), self)
            sort_datasets = partial(self.sort_datasets, sort_action, field_type)
            sort_action.triggered.connect(sort_datasets)
            self.toolButton_sort.menu().addAction(sort_action)
            if field_type == SortField.DATE:
                self.toolButton_sort.setDefaultAction(sort_action)
        self.toolButton_sort.defaultAction().setToolTip(
            tr('Sort the datasets using the selected property.')
        )

        # set icons
        icon = QtGui.QIcon(':/plugins/LDMP/icons/mActionRefresh.svg')
        self.pushButton_refresh.setIcon(icon)
        icon = QtGui.QIcon(':/plugins/LDMP/icons/cloud-download.svg')
        self.pushButton_import.setIcon(icon)
        self.pushButton_import.clicked.connect(self.import_data)
        icon = QtGui.QIcon(':/plugins/LDMP/icons/mActionSharingImport.svg')
        self.pushButton_download.setIcon(icon)
        self.pushButton_download.clicked.connect(self.download_data)
        self.pushButton_load.setIcon(QtGui.QIcon(':/plugins/LDMP/icons/document.svg'))
        self.pushButton_load.clicked.connect(self.loadBaseMap)

        # set manual and automatic refresh of datasets
        # avoid using lambda or partial to allow not anonymous callback => can be removed if necessary
        def refreshWithotAutorefresh():
            self.refreshDatasets(autorefresh=False)
            self.refreshJobs(autorefresh=False)
        self.pushButton_refresh.clicked.connect(refreshWithotAutorefresh) 

        # set automatic refreshes
        dataset_refresh_polling_time = QtCore.QSettings().value("trends_earth/advanced/datasets_refresh_polling_time", 25000, type=int)
        job_refresh_polling_time = QtCore.QSettings().value("trends_earth/advanced/jobs_refresh_polling_time", 60000, type=int)
        if dataset_refresh_polling_time > 0:
            QtCore.QTimer.singleShot(dataset_refresh_polling_time, self.refreshDatasets)
        if job_refresh_polling_time > 0:
            QtCore.QTimer.singleShot(job_refresh_polling_time, self.refreshJobs)


        # configure view
        self.treeView_datasets.setMouseTracking(True) # to allow emit entered events and manage editing over mouse
        self.treeView_datasets.setWordWrap(True) # add ... to wrap DisplayRole text... to have a real wrap need a custom widget
        delegate = DatasetItemDelegate(self.plugin, self.treeView_datasets)
        self.treeView_datasets.setItemDelegate(delegate)
        # configure View how to enter editing mode
        self.treeView_datasets.setEditTriggers(QtWidgets.QAbstractItemView.AllEditTriggers)

        # example of datasets
        # date_ = datetime.strptime('2021-01-20 10:30:00', '%Y-%m-%d %H:%M:%S')
        # datasets = Datasets()

        # sync datasets available in base_data_directory
        # datasets.sync()
        #     [
        #         Dataset('1dataset1', date_, 'Land productivity', run_id='run_id_1'),
        #         Dataset('2dataset2', date_, 'Downloaded from sample dataset', run_id='run_id_2'),
        #         Dataset('3dataset3', date_, 'Land change', run_id='run_id_3'),
        #         Dataset('11Productivity Trajectory1', date_, 'Land Productivity (SDG 15.3.1 sub-indicator1)', run_id='run_id_4'),
        #         Dataset('22Productivity Trajectory2', date_, 'Land Productivity (SDG 15.3.1 sub-indicator1)', run_id='run_id_5'),
        #         Dataset('33Productivity Trajectory3', date_, 'Land Productivity (SDG 15.3.1 sub-indicator1)', run_id='run_id_6'),
        #         Dataset('44Productivity Trajectory4', date_, 'Land Productivity (SDG 15.3.1 sub-indicator1)', run_id='run_id_7'),
        #         Dataset('55Productivity Trajectory5', date_, 'Land Productivity (SDG 15.3.1 sub-indicator1)', run_id='run_id_8'),
        #         Dataset('66Productivity Trajectory6', date_, 'Land Productivity (SDG 15.3.1 sub-indicator1)', run_id='run_id_9'),
        #         Dataset(
        #             '111 A very very very  much much big name with a lot of many many many many words',
        #             date_,
        #             'Land Productivity (SDG 15.3.1 sub-indicator1)', run_id='run_id_10'
        #         ),
        #         Dataset(
        #             '222 A very very very  much much big name with a lot of many many many many words',
        #             date_,
        #             'A very very very  much much big name with a lot of many many many many words', run_id='run_id_11'
        #         ),
        #     ]
        # )

        # show it

    def refreshJobs(self, autorefresh=True):
        """Refresh Jobs is composed of the following steps:
        1) Get all executions (e.g. Jobs)
        Due to API limitation it's not possible to query a job one by one but only get all jobs in a time window.
        """
        # use method of other plguin GUIs to fetch all executions
        if not self.plugin:
            return
        self.plugin.dlg_jobs.btn_refresh()
        Jobs().sync()

        # depending on config re-trigger it
        job_refresh_polling_time = QtCore.QSettings().value("trends_earth/advanced/jobs_refresh_polling_time", 60000, type=int)
        if autorefresh and job_refresh_polling_time > 0:
            QtCore.QTimer.singleShot(job_refresh_polling_time, self.refreshJobs)

    def refreshDatasets(self, autorefresh=True, autodownload=True):
        """Refresh datasets is composed of the following steps:
        1) Rebuild and dump Datasets based on the downloaded Jobs
        """
        self.updateDatasetsBasedOnJobs()

        # trigger download for terminated jobs
        dataset_auto_download = QtCore.QSettings().value("trends_earth/advanced/dataset_auto_download", True, type=bool)
        if autodownload and dataset_auto_download:
            Datasets().triggerDownloads()

        # depending on config re-trigger it
        dataset_refresh_polling_time = QtCore.QSettings().value("trends_earth/advanced/datasets_refresh_polling_time", 25000, type=int)
        if autorefresh and dataset_refresh_polling_time > 0:
            QtCore.QTimer.singleShot(dataset_refresh_polling_time, self.refreshDatasets)

    def updateDatasetsModel(self):
        datasetsModel = DatasetsModel( Datasets() )  # Datasets is a singleton
        # set filtering functionality
        self.proxy_model = DatasetsSortFilterProxyModel(Datasets())
        self.proxy_model.setSourceModel(datasetsModel)
        self.proxy_model.layoutChanged.connect(self.clear_message_bar)

        self.lineEdit_search.valueChanged.connect(self.filter_changed)

        self.treeView_datasets.reset()
        self.treeView_datasets.setModel(self.proxy_model)
        self.toolButton_sort.defaultAction().trigger()

    def filter_changed(self, filter_string: str):
        options = QtCore.QRegularExpression.NoPatternOption
        options |= QtCore.QRegularExpression.CaseInsensitiveOption
        regular_expression = QtCore.QRegularExpression(filter_string, options)
        self.proxy_model.setFilterRegularExpression(regular_expression)

    def sort_datasets(self, action: QtWidgets.QAction, field: SortField):
        # Show sorting progress, some Datasets takes a bit long to sort
        self.add_sort_filter_progress(tr("Sorting Datasets..."))
        self.toolButton_sort.setDefaultAction(action)
        self.proxy_model.setDatasetSortField(field)
        order = QtCore.Qt.AscendingOrder if not self.reverse_box.isChecked() else QtCore.Qt.DescendingOrder
        self.proxy_model.sort(0, order)

    def add_sort_filter_progress(self, message):
        self.message_bar_sort_filter = MessageBar().get().createMessage(message)
        progress_bar = QtWidgets.QProgressBar()
        progress_bar.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        progress_bar.setMinimum(0)
        progress_bar.setMaximum(0)
        self.message_bar_sort_filter.layout().addWidget(progress_bar)
        MessageBar().get().pushWidget(self.message_bar_sort_filter, Qgis.Info)

    def clear_message_bar(self):
        # Using try and catch block message bar item might be already deleted.
        try:
            MessageBar().get().popWidget(self.message_bar_sort_filter)
        except RuntimeError:
            pass

    def setupAlgorithmsTree(self):
        # setup algorithms and their hierarchy
        tree = AlgorithmGroup(name='root', name_details='root details', parent=None, algorithms=[])
        land_degradation_group = AlgorithmGroup(name=tr('SDG 15.3.1'), name_details=tr('Land degradation'), parent=tree, algorithms=[])
        urban_change_group = AlgorithmGroup(name=tr('SDG 11.3.1'), name_details=tr('Urban change and land consumption'), parent=tree, algorithms=[])
        experimental = AlgorithmGroup(name=tr('Experimental'), name_details=None, parent=tree, algorithms=[])
        total_carbon_group = AlgorithmGroup(name=tr('Total carbon'), name_details=tr('above and belowground, emissions and deforestation'), parent=experimental, algorithms=[])
        potential_change_group = AlgorithmGroup(name=tr('Potential change in biomass due to restoration'), name_details=tr('above and belowground woody'), parent=experimental, algorithms=[])

        # land_degradation_group
        land_productivity_alg = AlgorithmDescriptor(
            name=tr('Land productivity'),
            name_details=None,
            brief_description=None,
            details=None,
            parent=land_degradation_group,
            run_callbacks={AlgorithmRunMode.Remotely: self.dlg_calculate_LD.btn_prod_clicked})
        land_productivity_alg.run_mode = AlgorithmRunMode.Remotely
        land_productivity_alg_details = AlgorithmDetails(
            name=None,
            name_details=None,
            description=tr('TODO: Land productivity long description'),
            parent=land_productivity_alg)
        land_productivity_alg.setDetails(land_productivity_alg_details)

        land_cover_alg = AlgorithmDescriptor(
            name=tr('Land cover'),
            name_details=None,
            brief_description=None,
            details=None,
            parent=land_degradation_group,
            run_callbacks={AlgorithmRunMode.Remotely: self.dlg_calculate_LD.btn_lc_clicked})
        land_cover_alg.run_mode = AlgorithmRunMode.Remotely
        land_cover_alg_details = AlgorithmDetails(
            name=None,
            name_details=None,
            description=tr('TODO: Land cover long description'),
            parent=land_cover_alg)
        land_cover_alg.setDetails(land_cover_alg_details)

        soil_organic_carbon_alg = AlgorithmDescriptor(
            name=tr('Soil organic carbon'),
            name_details=None,
            brief_description=None,
            details=None,
            parent=land_degradation_group,
            run_callbacks={AlgorithmRunMode.Remotely: self.dlg_calculate_LD.btn_soc_clicked})
        soil_organic_carbon_alg.run_mode = AlgorithmRunMode.Remotely
        soil_organic_carbon_alg_details = AlgorithmDetails(
            name=None,
            name_details=None,
            description=tr('TODO: Soil organic carbon long description'),
            parent=soil_organic_carbon_alg)
        soil_organic_carbon_alg.setDetails(soil_organic_carbon_alg_details)

        all_land_degradation_alg = AlgorithmDescriptor(
            name=tr('All above sub-indicators in one step'),
            name_details=None,
            brief_description=None,
            details=None,
            parent=land_degradation_group,
            run_callbacks={AlgorithmRunMode.Remotely: self.dlg_calculate_LD.btn_sdg_onestep_clicked})
        all_land_degradation_alg.run_mode = AlgorithmRunMode.Remotely
        all_land_degradation_alg_details = AlgorithmDetails(
            name=None,
            name_details=None,
            description=tr('TODO: All abovesub-indicators in one step long description'),
            parent=all_land_degradation_alg)
        all_land_degradation_alg.setDetails(all_land_degradation_alg_details)

        final_alg = AlgorithmDescriptor(
            name=tr('Final SDG 15.3.1'),
            name_details=tr('Spatial layer and summary table for total boundary'),
            brief_description=None,
            details=None,
            parent=land_degradation_group,
            run_callbacks={AlgorithmRunMode.Locally: self.dlg_calculate_LD.btn_summary_single_polygon_clicked})
        final_alg.run_mode = AlgorithmRunMode.Locally
        final_alg_details = AlgorithmDetails(
            name=None,
            name_details=None,
            description=tr('TODO: Final SDG 15.3.1 long description'),
            parent=final_alg)
        final_alg.setDetails(final_alg_details)

        area_summaries_alg = AlgorithmDescriptor(
            name=tr('Area summaries of a raster on sub-units'),
            name_details=None,
            brief_description=None,
            details=None,
            parent=land_degradation_group,
            run_callbacks={AlgorithmRunMode.Locally: self.dlg_calculate_LD.btn_summary_multi_polygons_clicked})
        area_summaries_alg.run_mode = AlgorithmRunMode.Locally
        area_summaries_alg_details = AlgorithmDetails(
            name=None,
            name_details=None,
            description=tr('TODO: Area summaries long description'),
            parent=area_summaries_alg)
        area_summaries_alg.setDetails(area_summaries_alg_details)

        land_degradation_group.algorithms.append(land_productivity_alg)
        land_degradation_group.algorithms.append(land_cover_alg)
        land_degradation_group.algorithms.append(soil_organic_carbon_alg)
        land_degradation_group.algorithms.append(all_land_degradation_alg)
        land_degradation_group.algorithms.append(final_alg)
        land_degradation_group.algorithms.append(area_summaries_alg)

        # urban_change_group
        urban_change_alg = AlgorithmDescriptor(
            name=tr('Urban change spatial layer'),
            name_details=None,
            brief_description=None,
            details=None,
            parent=urban_change_group,
            run_callbacks={AlgorithmRunMode.Locally: self.dlg_calculate_Urban.btn_calculate_urban_change_clicked})
        urban_change_alg.run_mode = AlgorithmRunMode.Both
        urban_change_alg_details = AlgorithmDetails(
            name=None,
            name_details=None,
            description=tr('TODO: Urban change spatial layer long description'),
            parent=urban_change_alg)
        urban_change_alg.setDetails(urban_change_alg_details)

        urban_change_summary_alg = AlgorithmDescriptor(
            name=tr('Urban change summary table for city'),
            name_details=None,
            brief_description=None,
            details=None,
            parent=urban_change_group,
            run_callbacks={AlgorithmRunMode.Locally: self.dlg_calculate_Urban.btn_summary_single_polygon_clicked})
        urban_change_summary_alg.run_mode = AlgorithmRunMode.Both
        urban_change_summary_alg_details = AlgorithmDetails(
            name=None,
            name_details=None,
            description=tr('TODO: Urban change summary table for city long description'),
            parent=urban_change_summary_alg)
        urban_change_summary_alg.setDetails(urban_change_summary_alg_details)

        urban_change_group.algorithms.append(urban_change_alg)
        urban_change_group.algorithms.append(urban_change_summary_alg)

        # total_carbon_group
        carbon_change_alg = AlgorithmDescriptor(
            name=tr('Carbon change spatial layers'),
            name_details=None,
            brief_description=None,
            details=None,
            parent=total_carbon_group,
            run_callbacks={AlgorithmRunMode.Remotely: self.dlg_calculate_TC.btn_calculate_carbon_change_clicked})
        carbon_change_alg.run_mode = AlgorithmRunMode.Remotely
        carbon_change_alg_details = AlgorithmDetails(
            name=None,
            name_details=None,
            description=tr('TODO: Carbon change spatial layers long description'),
            parent=carbon_change_alg)
        carbon_change_alg.setDetails(carbon_change_alg_details)

        carbon_change_summary_alg = AlgorithmDescriptor(
            name=tr('Carbon change summary table for boundary'),
            name_details=None,
            brief_description=None,
            details=None,
            parent=total_carbon_group,
            run_callbacks={AlgorithmRunMode.Remotely: self.dlg_calculate_TC.btn_summary_single_polygon_clicked})
        carbon_change_summary_alg.run_mode = AlgorithmRunMode.Remotely
        carbon_change_summary_alg_details = AlgorithmDetails(name=None, name_details=None, description=tr('TODO: Carbon change summary table for boundary long description'), parent=carbon_change_summary_alg)
        carbon_change_summary_alg.setDetails(carbon_change_summary_alg_details)

        total_carbon_group.algorithms.append(carbon_change_alg)
        total_carbon_group.algorithms.append(carbon_change_summary_alg)
        experimental.algorithms.append(total_carbon_group)

        # potential_change_group
        estimate_biomass_change_alg = AlgorithmDescriptor(
            name=tr('Estimate biomass change'),
            name_details=None,
            brief_description=None,
            details=None,
            parent=potential_change_group,
            run_callbacks={AlgorithmRunMode.Remotely: self.dlg_calculate_Biomass.btn_calculate_rest_biomass_change_clicked})
        estimate_biomass_change_alg.run_mode = AlgorithmRunMode.Remotely
        estimate_biomass_change_alg_details = AlgorithmDetails(
            name=None,
            name_details=None,
            description=tr('TODO: Estimate biomass change long description'),
            parent=estimate_biomass_change_alg)
        estimate_biomass_change_alg.setDetails(estimate_biomass_change_alg_details)

        estimate_biomass_summary_alg = AlgorithmDescriptor(
            name=tr('Table summarizing likely changes in biomass'),
            name_details=None,
            brief_description=None,
            details=None,
            parent=potential_change_group,
            run_callbacks={AlgorithmRunMode.Remotely: self.dlg_calculate_Biomass.btn_summary_single_polygon_clicked})
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

        # show it
        algorithmsModel = AlgorithmTreeModel(tree)
        self.treeView_algorithms.setMouseTracking(True) # to allow emit entered events and manage editing over mouse
        self.treeView_algorithms.setWordWrap(True) # add ... to wrap DisplayRole text... to have a real wrap need a custom widget
        self.treeView_algorithms.setModel(algorithmsModel)
        delegate = AlgorithmItemDelegate(self.treeView_algorithms)
        self.treeView_algorithms.setItemDelegate(delegate)

        # configure View how to enter editing mode
        self.treeView_algorithms.setEditTriggers(QtWidgets.QAbstractItemView.AllEditTriggers)

    def loadBaseMap(self):
        DlgVisualizationBasemap().exec_()

    def download_data(self):
        DlgDownload().exec_()

    def import_data(self):
        DlgDataIO().exec_()

    def closeEvent(self, event):
        super(MainWidget, self).closeEvent(event)

    def showEvent(self, event):
        super(MainWidget, self).showEvent(event)