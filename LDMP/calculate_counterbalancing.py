"""Dialog for LDN Counterbalancing Assessment.

Allows the user to select:
  - An existing 7-class expanded status layer (from a prior SDG 15.3.1 run)
  - One or more raster layers that define the land types for counterbalancing
and run the counterbalancing assessment locally.
"""

import logging
import math
import typing

import numpy as np
import qgis.core
import qgis.gui
import te_algorithms.gdal.land_deg.config as ld_config
from osgeo import gdal
from qgis.PyQt import QtCore, QtWidgets
from te_schemas.algorithms import ExecutionScript

from . import areaofinterest, data_io
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

        # ----- Land type layers -----
        grp_land_type = QtWidgets.QGroupBox(self.tr("Land Type Layers"))
        lt_layout = QtWidgets.QVBoxLayout()
        lt_layout.addWidget(
            QtWidgets.QLabel(
                self.tr(
                    "Select one or more raster layers whose intersection "
                    "defines the land types for counterbalancing:"
                )
            )
        )

        self.land_type_list = QtWidgets.QListWidget()
        lt_layout.addWidget(self.land_type_list)

        btn_layout = QtWidgets.QHBoxLayout()
        self.btn_add_land_type = QtWidgets.QPushButton(self.tr("Add layer..."))
        self.btn_remove_land_type = QtWidgets.QPushButton(self.tr("Remove selected"))
        btn_layout.addWidget(self.btn_add_land_type)
        btn_layout.addWidget(self.btn_remove_land_type)
        lt_layout.addLayout(btn_layout)

        self.lbl_land_type_count = QtWidgets.QLabel(self.tr("Land type layers: 0"))
        lt_layout.addWidget(self.lbl_land_type_count)

        self.lbl_estimated_classes = QtWidgets.QLabel("")
        self.lbl_estimated_classes.setWordWrap(True)
        lt_layout.addWidget(self.lbl_estimated_classes)

        grp_land_type.setLayout(lt_layout)
        layout.addWidget(grp_land_type)

        self.btn_add_land_type.clicked.connect(self._add_land_type_layer)
        self.btn_remove_land_type.clicked.connect(self._remove_land_type_layer)

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

    def showEvent(self, event):
        super().showEvent(event)
        self._populate_combos()

    # --------------------------------------------------------------------- #
    #  Land type layer management
    # --------------------------------------------------------------------- #
    def _add_land_type_layer(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            self.tr("Select land type raster layer(s)"),
            "",
            self.tr("Raster files (*.tif *.tiff *.vrt);;All files (*)"),
        )
        for p in paths:
            if p and not self._land_type_path_already_added(p):
                self.land_type_list.addItem(p)
        self._update_land_type_info()

    def _remove_land_type_layer(self):
        for item in self.land_type_list.selectedItems():
            self.land_type_list.takeItem(self.land_type_list.row(item))
        self._update_land_type_info()

    # Target number of pixels for the downsampled estimate grid.
    _SAMPLE_PIXELS = 10_000

    def _update_land_type_info(self):
        """Update the layer count and estimated class count labels."""
        n_layers = self.land_type_list.count()
        self.lbl_land_type_count.setText(self.tr("Land type layers: %d") % n_layers)
        if n_layers == 0:
            self.lbl_estimated_classes.setText("")
            return

        paths = self._get_land_type_paths()
        n_classes = self._estimate_interaction_classes(paths)
        if n_classes is not None:
            self.lbl_estimated_classes.setText(
                self.tr("Estimated land type classes from interaction: ~%d") % n_classes
            )
        else:
            self.lbl_estimated_classes.setText(
                self.tr("Could not read class counts from the selected layers.")
            )

    def _estimate_interaction_classes(
        self, paths: typing.List[str]
    ) -> typing.Optional[int]:
        """Downsample all layers to a common coarse grid and count combos.

        Uses gdal.Translate with nearest-neighbour resampling to produce a
        small in-memory raster (~100x100) for each layer, all snapped to the
        AOI extent.  Unique value tuples across the co-registered grids give
        the estimated interaction class count.
        """
        # Get the AOI bounding box as the common extent
        aoi = areaofinterest.try_prepare_area_of_interest()
        if aoi is None:
            return None
        bb = aoi.bounding_box_geom().boundingBox()
        xmin = bb.xMinimum()
        ymin = bb.yMinimum()
        xmax = bb.xMaximum()
        ymax = bb.yMaximum()

        # Calculate output dimensions (~sqrt(SAMPLE_PIXELS) on each side)
        side = max(1, int(math.isqrt(self._SAMPLE_PIXELS)))

        # Translate each raster to the common coarse grid (in memory)
        arrays = []
        nodata_values = []
        translate_opts = gdal.TranslateOptions(
            format="MEM",
            width=side,
            height=side,
            resampleAlg="nearest",
            projWin=[xmin, ymax, xmax, ymin],
        )
        for p in paths:
            ds = gdal.Translate("", p, options=translate_opts)
            if ds is None:
                return None
            band = ds.GetRasterBand(1)
            nodata_values.append(band.GetNoDataValue())
            arr = band.ReadAsArray()
            ds = None
            if arr is None:
                return None
            arrays.append(arr.ravel())

        # Build valid-pixel mask (exclude nodata from any layer)
        valid = np.ones(arrays[0].size, dtype=bool)
        for arr, nd in zip(arrays, nodata_values):
            if nd is not None:
                valid &= arr != int(nd)

        if not np.any(valid):
            return None

        # Stack valid samples and count unique combinations
        stacked = np.column_stack([arr[valid] for arr in arrays])
        unique_rows = np.unique(stacked, axis=0)
        return int(unique_rows.shape[0])

    def _land_type_path_already_added(self, path: str) -> bool:
        for i in range(self.land_type_list.count()):
            if self.land_type_list.item(i).text() == path:
                return True
        return False

    def _get_land_type_paths(self) -> typing.List[str]:
        return [
            self.land_type_list.item(i).text()
            for i in range(self.land_type_list.count())
        ]

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

        land_type_paths = self._get_land_type_paths()
        if not land_type_paths:
            QtWidgets.QMessageBox.critical(
                self,
                self.tr("Error"),
                self.tr("Please add at least one land type layer."),
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
            "land_type_layer_paths": land_type_paths,
            "year_initial": year_initial,
            "year_final": year_final,
        }

        self.close()

        job_manager.submit_local_job_as_qgstask(
            params, script_name=self.LOCAL_SCRIPT_NAME, area_of_interest=self.aoi
        )
