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
from LDMP import tr

# callback mock
class Runner(object):
    def btn_prod_clicked():
        pass
    def btn_lc_clicked():
        pass
    def btn_soc_clicked():
        pass
    def btn_sdg_onestep_clicked():
        pass
    def btn_summary_single_polygon_clicked():
        pass
    def btn_summary_multi_polygons_clicked():
        pass
    def btn_calculate_urban_change_clicked():
        pass
    def btn_summary_single_polygon_clicked():
        pass
    def btn_calculate_carbon_change_clicked():
        pass
    def btn_summary_single_polygon_clicked():
        pass
    def btn_calculate_rest_biomass_change_clicked():
        pass
    def btn_summary_single_polygon_clicked():
        pass

class Test(object):

    def __init__(self):
        super().__init__()
        self.dlg_calculate_LD = Runner()
        self.dlg_calculate_TC = Runner()
        self.dlg_calculate_Biomass = Runner()
        self.dlg_calculate_Urban = Runner()

    def run(self):
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

        app = QApplication(["???"])

        # show it
        algorithmsModel = AlgorithmTreeModel(tree)
        QAbstractItemModelTester(algorithmsModel, QAbstractItemModelTester.FailureReportingMode.Warning)

        view = QTreeView()
        view.setMouseTracking(True) # to allow emit entered events and manage editing over mouse
        view.setWordWrap(True)
        view.setEditTriggers(QAbstractItemView.AllEditTriggers)
        view.setModel(algorithmsModel)
        view.setWindowTitle("Tree Model")
        delegate = AlgorithmItemDelegate(view)
        view.setItemDelegate(delegate)
        view.show()
        app.exec()


if __name__ == '__main__':
    test = Test()
    test.run()