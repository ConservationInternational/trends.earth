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

import json
from pathlib import Path

from PyQt5 import (
    QtWidgets,
    uic
)

import qgis.core
import qgis.gui

from . import (
    calculate,
    lc_setup,
)
from .algorithms.models import (
    AlgorithmRunMode,
    ExecutionScript,
)
from .jobs.manager import job_manager

DlgCalculateLcUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateLC.ui"))

from te_schemas.schemas import BandInfo, BandInfoSchema
from te_schemas.land_cover import LCTransitionDefinitionDeg, LCLegendNesting

class DlgCalculateLC(calculate.DlgCalculateBase, DlgCalculateLcUi):
    LOCAL_SCRIPT_NAME = "local-land-cover"

    advanced_configurations: qgis.gui.QgsCollapsibleGroupBox
    scrollAreaWidgetContents: QtWidgets.QWidget

    def __init__(
            self,
            iface: qgis.gui.QgisInterface,
            script: ExecutionScript,
            parent: QtWidgets.QWidget
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)

        lc_widget_class = {
            AlgorithmRunMode.LOCAL: lc_setup.LandCoverSetupLocalExecutionWidget,
            AlgorithmRunMode.REMOTE: lc_setup.LandCoverSetupRemoteExecutionWidget,
        }[self.script.run_mode]
        self.lc_setup_widget = lc_widget_class(parent=self)
        self.lc_define_deg_widget = lc_setup.LCDefineDegradationWidget()
        self.advanced_configurations.setCollapsed(True)
        self.scrollAreaWidgetContents.layout().insertWidget(0, self.lc_setup_widget)
        self.advanced_configurations.layout().insertWidget(0, self.lc_define_deg_widget)
        self._finish_initialization()

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgCalculateLC, self).btn_calculate()
        if not ret:
            return

        if self.script.run_mode == AlgorithmRunMode.REMOTE:
            self.calculate_on_GEE()
        elif self.script.run_mode == AlgorithmRunMode.LOCAL:
            self.calculate_locally()
        else:
            raise NotImplementedError

    def calculate_on_GEE(self):
        self.close()
        crosses_180th, geojsons = self.gee_bounding_box

        payload = {
            "year_baseline": self.lc_setup_widget.initial_year_de.date().year(),
            "year_target": self.lc_setup_widget.target_year_de.date().year(),
            "geojsons": json.dumps(geojsons),
            "crs": self.aoi.get_crs_dst_wkt(),
            "crosses_180th": crosses_180th,
            'legend_nesting': LCLegendNesting.Schema().dump(
                self.lc_setup_widget.aggregation_dialog.nesting
            ),
            'trans_matrix': LCTransitionDefinitionDeg.Schema().dump(
                self.lc_define_deg_widget.trans_matrix
            ),
            "task_name": self.execution_name_le.text(),
            "task_notes": self.task_notes.toPlainText()
        }
        job = job_manager.submit_remote_job(payload, self.script.id)

        if job is not None:
            main_msg = "Submitted"
            description = "Land cover task submitted to Google Earth Engine."
        else:
            main_msg = "Error"
            description = "Unable to submit land cover task to Google Earth Engine."
        self.mb.pushMessage(
            self.tr(main_msg),
            self.tr(description),
            level=0,
            duration=5
        )

    def calculate_locally(self):

        if len(self.lc_setup_widget.initial_year_layer_cb.layer_list) == 0:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "You must add an initial land cover layer to your map before you "
                    "can run the calculation."
                )
            )
            return

        if len(self.lc_setup_widget.target_year_layer_cb.layer_list) == 0:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "You must add a final land cover layer to your map before you "
                    "can run the calculation."
                )
            )
            return

        year_baseline = self.lc_setup_widget.get_initial_year()
        year_target = self.lc_setup_widget.get_final_year()

        if int(year_baseline) >= int(year_target):
            QtWidgets.QMessageBox.information(
                None,
                self.tr("Warning"),
                self.tr(
                    'The initial year ({}) is greater than or equal to the target '
                    'year ({}) - this analysis might generate strange '
                    'results.'.format(year_baseline, year_target)
                )
            )

        initial_layer = self.lc_setup_widget.initial_year_layer_cb.get_layer()
        initial_extent_geom = qgis.core.QgsGeometry.fromRect(initial_layer.extent())
        if self.aoi.calc_frac_overlap(initial_extent_geom) < .99:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Area of interest is not entirely within the initial land cover "
                    "layer."
                )
            )
            return

        final_layer = self.lc_setup_widget.target_year_layer_cb.get_layer()
        final_extent_geom = qgis.core.QgsGeometry.fromRect(final_layer.extent())
        if self.aoi.calc_frac_overlap(final_extent_geom) < .99:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Area of interest is not entirely within the final land "
                    "cover layer."
                )
            )
            return

        self.close()

        #TODO: Fix trans matrix and persistence remap to use new locations for these variables
        initial_usable = (
            self.lc_setup_widget.initial_year_layer_cb.get_usable_band_info())
        final_usable = self.lc_setup_widget.target_year_layer_cb.get_usable_band_info()
        job_params = {
            "task_name": self.execution_name_le.text(),
            "task_notes": self.task_notes.toPlainText(),
            "year_baseline": year_baseline,
            "year_target": year_target,
            "lc_initial_path": str(initial_usable.path),
            "lc_initial_band_index": initial_usable.band_index,
            "lc_final_path": str(final_usable.path),
            "lc_final_band_index": final_usable.band_index,
            "transformation_matrix": self.lc_define_deg_widget.trans_matrix_get()
        }
        job_manager.submit_local_job(job_params, self.LOCAL_SCRIPT_NAME, self.aoi)
