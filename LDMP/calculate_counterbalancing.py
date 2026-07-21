"""Dialog for LDN Counterbalancing Assessment.

Allows the user to select:
  - An existing 7-class expanded status layer (from a prior SDG 15.3.1 run)
  - A saved land types layer (the counterbalancing spatial units),
    produced by the LDN Planning — Define Land Types tool
and run the counterbalancing assessment locally.
"""

import logging
import typing

import qgis.core
import qgis.gui
import te_algorithms.gdal.land_deg.config as ld_config
from qgis.PyQt import QtCore, QtWidgets
from te_schemas.algorithms import ExecutionScript

from . import data_io
from .calculate import DlgCalculateBase
from .jobs.manager import job_manager

logger = logging.getLogger(__name__)


class DlgCalculateCounterbalancing(DlgCalculateBase):
    """Dialog for LDN counterbalancing assessment."""

    LOCAL_SCRIPT_NAME: str = "ldn-counterbalancing"

    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        script: ExecutionScript,
        parent: QtWidgets.QWidget = None,
    ):
        super().__init__(iface, script, parent)
        self._build_ui()
        self._finish_initialization()
        self.changed_region.connect(self._populate_combos)

    # --------------------------------------------------------------------- #
    #  UI construction (programmatic — no .ui file required)
    # --------------------------------------------------------------------- #
    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout()

        # ----- Status layer -----
        grp_status = QtWidgets.QGroupBox(
            self.tr("Status Layer (7-class expanded status)")
        )
        status_layout = QtWidgets.QVBoxLayout()
        self.combo_status_layer = data_io.WidgetDataIOSelectTELayerExisting()
        status_layout.addWidget(QtWidgets.QLabel(self.tr("Status layer:")))
        status_layout.addWidget(self.combo_status_layer)
        grp_status.setLayout(status_layout)
        layout.addWidget(grp_status)

        # ----- Land types layer (from the Define Land Types tool) -----
        grp_zones = QtWidgets.QGroupBox(self.tr("Land Types Layer"))
        z_layout = QtWidgets.QVBoxLayout()
        z_layout.addWidget(
            QtWidgets.QLabel(
                self.tr(
                    "Select a saved land types layer (the counterbalancing spatial "
                    "units). Create one with the LDN Planning —\n"
                    "Define Land Types tool, which combines one or more\n"
                    "rasters into a reusable land types layer."
                )
            )
        )
        self.combo_zones_job = QtWidgets.QComboBox()
        z_layout.addWidget(self.combo_zones_job)
        self.lbl_zones_hint = QtWidgets.QLabel("")
        self.lbl_zones_hint.setWordWrap(True)
        z_layout.addWidget(self.lbl_zones_hint)
        grp_zones.setLayout(z_layout)
        layout.addWidget(grp_zones)
        self._land_types_jobs: typing.List = []

        # ----- Task name -----
        name_layout = QtWidgets.QHBoxLayout()
        name_layout.addWidget(QtWidgets.QLabel(self.tr("Task name:")))
        self.execution_name_le = QtWidgets.QLineEdit()
        self.execution_name_le.setText("LDN Counterbalancing")
        name_layout.addWidget(self.execution_name_le)
        layout.addLayout(name_layout)

        # ----- Notes -----
        self.task_notes = QtWidgets.QTextEdit()
        self.task_notes.setMaximumHeight(60)
        self.task_notes.setPlaceholderText(self.tr("Task notes (optional)"))
        layout.addWidget(self.task_notes)

        # ----- Region + button box -----
        region_layout = QtWidgets.QHBoxLayout()
        self.region_la = QtWidgets.QLabel()
        self.region_button = QtWidgets.QToolButton()
        region_layout.addWidget(self.region_la)
        region_layout.addWidget(self.region_button)
        layout.addLayout(region_layout)

        # Splitter (required by DlgCalculateBase._finish_initialization)
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        left_widget = QtWidgets.QWidget()
        left_widget.setLayout(layout)
        self.splitter.addWidget(left_widget)
        self.splitter.addWidget(QtWidgets.QWidget())  # placeholder right pane

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.addWidget(self.splitter)

        self.button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        main_layout.addWidget(self.button_box)

        self.setWindowTitle(self.tr("LDN Counterbalancing Assessment"))
        self.resize(600, 550)

    # --------------------------------------------------------------------- #
    #  Combo population
    # --------------------------------------------------------------------- #
    def _populate_combos(self):
        self.combo_status_layer.setProperty(
            "layer_type",
            ld_config.SDG_STATUS_BAND_NAME,
        )
        self.combo_status_layer.populate()
        self._land_types_jobs = job_manager.get_ldn_land_types_jobs()
        self.combo_zones_job.clear()
        if not self._land_types_jobs:
            self.combo_zones_job.addItem(self.tr("(no saved land types)"))
            self.combo_zones_job.setEnabled(False)
            self.lbl_zones_hint.setText(
                self.tr(
                    "No land types layers found. Create one with LDN Planning — "
                    "Define Land Types, then reopen this dialog."
                )
            )
        else:
            self.combo_zones_job.setEnabled(True)
            self.lbl_zones_hint.setText("")
            for j in self._land_types_jobs:
                self.combo_zones_job.addItem(j.task_name or str(j.id), str(j.id))

    def showEvent(self, event):
        super().showEvent(event)
        self._populate_combos()

    def _selected_land_types_raster(self):
        """Return the raster path of the selected saved land types layer, or None."""
        from te_schemas.results import RasterResults

        idx = self.combo_zones_job.currentIndex()
        if idx < 0 or not self._land_types_jobs:
            return None
        job = self._land_types_jobs[idx]
        job_manager.ensure_results_loaded(job)
        rr = job.get_first_result_by_type(RasterResults)
        if rr is None or rr.uri is None or rr.uri.uri is None:
            return None
        return str(rr.uri.uri)

    # --------------------------------------------------------------------- #
    #  Execution
    # --------------------------------------------------------------------- #
    def btn_calculate(self):
        ret = super().btn_calculate()
        if not ret:
            return

        # Validate inputs
        status_info = self.combo_status_layer.get_current_band()
        if status_info is None:
            QtWidgets.QMessageBox.critical(
                self,
                self.tr("Error"),
                self.tr("Please select a valid status layer."),
            )
            return

        zones_raster_path = self._selected_land_types_raster()
        if not zones_raster_path:
            QtWidgets.QMessageBox.critical(
                self,
                self.tr("Error"),
                self.tr(
                    "Please select a saved land types layer. Create one with the "
                    "LDN Planning — Define Land Types tool."
                ),
            )
            return

        # Extract year metadata from the selected status band
        status_metadata = status_info.band_info.metadata or {}
        year_initial = status_metadata.get(
            "year_initial",
            status_metadata.get("reporting_year_initial"),
        )
        year_final = status_metadata.get(
            "year_final",
            status_metadata.get("reporting_year_final"),
        )

        params = {
            "task_name": self.execution_name_le.text(),
            "task_notes": self.task_notes.toPlainText(),
            "status_layer_path": str(status_info.path),
            "status_band_index": status_info.band_index,
            "land_type_layer_paths": [zones_raster_path],
            "year_initial": year_initial,
            "year_final": year_final,
        }

        self.close()

        job_manager.submit_local_job_as_qgstask(
            params, script_name=self.LOCAL_SCRIPT_NAME, area_of_interest=self.aoi
        )
