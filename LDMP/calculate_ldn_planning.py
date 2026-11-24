"""Parametrization dialogs for the LDN Planning Tool.

Dialogs, all inheriting DlgCalculateBase:
  - DlgCalculateLDNPlanningARR         (ldn-planning-arr)
  - DlgCalculateLDNPlanningHotspots    (ldn-planning-hotspots)
  - DlgCalculateLDNPlanningLandTypes      (ldn-planning-land-types) — Define Land Types

All UIs are built programmatically (no .ui file), following the pattern in
LDMP/calculate_counterbalancing.py.
"""

import copy
import json
import logging
import math
import tempfile
import typing
from pathlib import Path

import qgis.gui
import te_algorithms.gdal.land_deg.config as ld_config
from qgis.PyQt import QtCore, QtWidgets
from te_algorithms.common.checksum import file_checksum
from te_algorithms.gdal.land_deg.ldn_planning_inputs import (
    inspect_targets_file,
    polygon_target,
)
from te_schemas.algorithms import ExecutionScript

from . import conf, data_io, download
from .calculate import DlgCalculateBase
from .jobs.manager import job_manager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _status_type(band: data_io.Band) -> str:
    """Resolve the encoding from the selected Trends.Earth band metadata."""
    if band.band_info.name == ld_config.SDG_BAND_NAME:
        return "3class"
    if band.band_info.name == ld_config.SDG_STATUS_BAND_NAME:
        return "7class"
    raise ValueError(
        QtCore.QCoreApplication.translate(
            "ldn_planning",
            "The selected dataset does not identify an SDG status encoding.",
        )
    )


_SDG_STATUS_LAYERS = ";".join((ld_config.SDG_BAND_NAME, ld_config.SDG_STATUS_BAND_NAME))


def _make_group(title: str, parent_layout: QtWidgets.QLayout) -> QtWidgets.QVBoxLayout:
    """Add a QGroupBox with a QVBoxLayout to parent_layout; return inner layout."""
    grp = QtWidgets.QGroupBox(title)
    inner = QtWidgets.QVBoxLayout()
    grp.setLayout(inner)
    parent_layout.addWidget(grp)
    return inner


def _add_task_name_notes(layout: QtWidgets.QVBoxLayout, default_name: str):
    """Append task-name + notes widgets to *layout*; return (name_le, notes_te)."""
    name_row = QtWidgets.QHBoxLayout()
    name_row.addWidget(QtWidgets.QLabel("Task name:"))
    name_le = QtWidgets.QLineEdit()
    name_le.setText(default_name)
    name_row.addWidget(name_le)
    layout.addLayout(name_row)

    notes_te = QtWidgets.QTextEdit()
    notes_te.setMaximumHeight(55)
    notes_te.setPlaceholderText("Task notes (optional)")
    layout.addWidget(notes_te)
    return name_le, notes_te


def _add_region_buttons(layout: QtWidgets.QVBoxLayout):
    """Append region label + wrench button row; return (label, button)."""
    row = QtWidgets.QHBoxLayout()
    region_la = QtWidgets.QLabel()
    region_btn = QtWidgets.QToolButton()
    row.addWidget(region_la)
    row.addWidget(region_btn)
    layout.addLayout(row)
    return region_la, region_btn


def _planning_help(html: str) -> QtWidgets.QTextBrowser:
    help_browser = QtWidgets.QTextBrowser()
    help_browser.setOpenExternalLinks(True)
    help_browser.setMinimumWidth(200)
    help_browser.setHtml(html)
    return help_browser


def _build_splitter_with_ok_cancel(
    dialog: QtWidgets.QDialog, left_content: QtWidgets.QWidget, help_html: str
) -> tuple:
    """
    Wrap *left_content* in a QSplitter + add a button box, as required by
    DlgCalculateBase._finish_initialization.

    Returns (splitter, button_box).
    """
    splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
    splitter.addWidget(left_content)
    splitter.addWidget(_planning_help(help_html))

    button_box = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
    )

    main_layout = QtWidgets.QVBoxLayout(dialog)
    main_layout.addWidget(splitter)
    main_layout.addWidget(button_box)
    return splitter, button_box


def _resolve_admin_zones(parent: QtWidgets.QWidget) -> typing.Optional[str]:
    """Download all ADM1 units of the current country and write to a temp file.

    Returns the path to a temporary GeoJSON or None on failure.
    """
    country_id = conf.settings_manager.get_value(conf.Setting.COUNTRY_ID)
    if not country_id:
        QtWidgets.QMessageBox.critical(
            parent,
            QtCore.QCoreApplication.translate("ldn_planning", "Error"),
            QtCore.QCoreApplication.translate(
                "ldn_planning",
                "No country selected. Use the region button to choose a "
                "country before using administrative-unit zoning.",
            ),
        )
        return None

    QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
    try:
        geojson = download.download_boundary_geojson(
            country_id, admin_level=1, shape_id=None
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Admin boundary download failed")
        geojson = None
        error_detail = str(exc)
    else:
        error_detail = ""
    finally:
        QtWidgets.QApplication.restoreOverrideCursor()

    if not geojson or not geojson.get("features"):
        QtWidgets.QMessageBox.critical(
            parent,
            QtCore.QCoreApplication.translate("ldn_planning", "Error"),
            QtCore.QCoreApplication.translate(
                "ldn_planning",
                "Could not download administrative boundaries for the selected country. "
                "Check your internet connection and try again, or choose a different "
                "zoning source.",
            )
            + (f"\n\n{error_detail}" if error_detail else ""),
        )
        return None

    tmp = tempfile.NamedTemporaryFile(suffix="_admin_zones.geojson", delete=False)
    tmp.close()
    with open(tmp.name, "w", encoding="utf-8") as fh:
        json.dump(geojson, fh)
    return tmp.name


# ---------------------------------------------------------------------------
# Import targets file dialog
# ---------------------------------------------------------------------------


class DlgImportTargetsFile(QtWidgets.QDialog):
    """Preview and field-mapping dialog shown before importing a targets file.

    Shows detected fields, lets the user map source fields to the required
    ``intervention`` and ``effectiveness`` attributes, and displays a
    validation summary of the features that will be imported.
    """

    _VALID_INTERVENTIONS = ("avoid", "reduce", "reverse")

    def __init__(
        self,
        path: str,
        info: dict,
        parent: QtWidgets.QWidget = None,
    ):
        super().__init__(parent)
        self._path = path
        self._info = info
        self.field_config: typing.Optional[typing.Dict] = None
        self._build_ui()
        self._update_ui()
        self.setWindowTitle(self.tr("Import Targets — Field Mapping"))
        self.resize(520, 480)

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        lbl_file = QtWidgets.QLabel(
            self.tr("File: <b>%s</b> (%d features)")
            % (Path(self._path).name, self._info["feature_count"])
        )
        lbl_file.setWordWrap(True)
        layout.addWidget(lbl_file)

        # --- Intervention field ---
        int_grp_box = QtWidgets.QGroupBox(self.tr("Intervention field"))
        int_grp = QtWidgets.QVBoxLayout()
        int_grp_box.setLayout(int_grp)
        layout.addWidget(int_grp_box)

        int_row = QtWidgets.QHBoxLayout()
        int_row.addWidget(QtWidgets.QLabel(self.tr("Source field:")))
        self.combo_int_field = QtWidgets.QComboBox()
        no_field_label = self.tr("(not found — set for all features)")
        self.combo_int_field.addItem(no_field_label, None)
        for f in self._info["string_fields"]:
            self.combo_int_field.addItem(f, f)
        for f in self._info["numeric_fields"]:
            if f not in self._info["string_fields"]:
                self.combo_int_field.addItem(f + self.tr(" (numeric)"), f)
        int_row.addWidget(self.combo_int_field)
        int_grp.addLayout(int_row)

        idx = self.combo_int_field.findData("intervention")
        if idx >= 0:
            self.combo_int_field.setCurrentIndex(idx)

        self._int_fallback_widget = QtWidgets.QWidget()
        fb_row = QtWidgets.QHBoxLayout(self._int_fallback_widget)
        fb_row.setContentsMargins(16, 0, 0, 0)
        fb_row.addWidget(QtWidgets.QLabel(self.tr("Apply to all features:")))
        self.combo_int_fallback = QtWidgets.QComboBox()
        self.combo_int_fallback.addItems(
            [
                self.tr("Reverse (restoration — GAINS)"),
                self.tr("Reduce (SLM — avoided losses)"),
                self.tr("Avoid (protection — avoided losses)"),
            ]
        )
        fb_row.addWidget(self.combo_int_fallback)
        int_grp.addWidget(self._int_fallback_widget)

        self.lbl_int_summary = QtWidgets.QLabel()
        self.lbl_int_summary.setWordWrap(True)
        int_grp.addWidget(self.lbl_int_summary)

        self.combo_int_field.currentIndexChanged.connect(self._update_ui)

        # --- Effectiveness field ---
        eff_grp_box = QtWidgets.QGroupBox(self.tr("Effectiveness field"))
        eff_grp = QtWidgets.QVBoxLayout()
        eff_grp_box.setLayout(eff_grp)
        layout.addWidget(eff_grp_box)

        eff_row = QtWidgets.QHBoxLayout()
        eff_row.addWidget(QtWidgets.QLabel(self.tr("Source field:")))
        self.combo_eff_field = QtWidgets.QComboBox()
        self.combo_eff_field.addItem(self.tr("(not found — use default)"), None)
        for f in self._info["numeric_fields"]:
            self.combo_eff_field.addItem(f, f)
        eff_row.addWidget(self.combo_eff_field)
        eff_grp.addLayout(eff_row)

        idx = self.combo_eff_field.findData("effectiveness")
        if idx >= 0:
            self.combo_eff_field.setCurrentIndex(idx)

        self._eff_fallback_widget = QtWidgets.QWidget()
        eff_fb_row = QtWidgets.QHBoxLayout(self._eff_fallback_widget)
        eff_fb_row.setContentsMargins(16, 0, 0, 0)
        eff_fb_row.addWidget(QtWidgets.QLabel(self.tr("Default effectiveness (0–1):")))
        self.spin_eff_fallback = QtWidgets.QDoubleSpinBox()
        self.spin_eff_fallback.setRange(0.0, 1.0)
        self.spin_eff_fallback.setSingleStep(0.05)
        self.spin_eff_fallback.setDecimals(2)
        self.spin_eff_fallback.setValue(0.80)
        eff_fb_row.addWidget(self.spin_eff_fallback)
        eff_grp.addWidget(self._eff_fallback_widget)

        self.lbl_eff_summary = QtWidgets.QLabel()
        self.lbl_eff_summary.setWordWrap(True)
        eff_grp.addWidget(self.lbl_eff_summary)

        self.combo_eff_field.currentIndexChanged.connect(self._update_ui)
        self.combo_eff_units = QtWidgets.QComboBox()
        self.combo_eff_units.addItem(self.tr("Fraction (0-1)"), "fraction")
        self.combo_eff_units.addItem(self.tr("Percent (0-100)"), "percent")
        eff_grp.addWidget(self.combo_eff_units)
        self.combo_eff_units.currentIndexChanged.connect(self._update_ui)

        self.button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _intervention_fallback_key(self) -> str:
        txt = self.combo_int_fallback.currentText().lower()
        if "reverse" in txt:
            return "reverse"
        if "reduce" in txt:
            return "reduce"
        return "avoid"

    def _update_ui(self):
        """Show/hide fallback widgets and refresh summary labels."""
        int_field = self.combo_int_field.currentData()
        using_int_fallback = int_field is None
        self._int_fallback_widget.setVisible(using_int_fallback)

        eff_field = self.combo_eff_field.currentData()
        using_eff_fallback = eff_field is None
        self._eff_fallback_widget.setVisible(using_eff_fallback)

        # Intervention summary
        if not using_int_fallback:
            if int_field == "intervention":
                counts = self._info.get("intervention_counts", {})
                known = {
                    k: v
                    for k, v in counts.items()
                    if k.lower() in self._VALID_INTERVENTIONS
                }
                unknown = {
                    k: v
                    for k, v in counts.items()
                    if k.lower() not in self._VALID_INTERVENTIONS
                }
                parts = [
                    f"{k}: {known.get(k, 0)}" for k in ("reverse", "reduce", "avoid")
                ]
                summary = ", ".join(parts)
                if unknown:
                    unk_vals = list(unknown.keys())[:5]
                    unk_str = ", ".join(f"'{v}'" for v in unk_vals)
                    if len(unknown) > 5:
                        unk_str += self.tr(" and %d more") % (len(unknown) - 5)
                    n_unk = sum(unknown.values())
                    summary += self.tr(
                        "\n\u26a0 %d feature(s) with unrecognized values (%s)"
                        " will be skipped."
                    ) % (n_unk, unk_str)
                self.lbl_int_summary.setText(summary)
            else:
                self.lbl_int_summary.setText(
                    self.tr("Field '%s' will be read for each feature.") % int_field
                )
        else:
            self.lbl_int_summary.setText(
                self.tr("All features will use the intervention selected above.")
            )

        # Effectiveness summary
        if not using_eff_fallback:
            rng = self._info.get("effectiveness_range")
            invalid_count = self._info.get("invalid_effectiveness_count", 0)
            if eff_field == "effectiveness" and rng is not None:
                mn, mx = rng
                summary = self.tr("Values range from %.3g to %.3g.") % (mn, mx)
                if invalid_count:
                    summary += (
                        self.tr(
                            "\n\u26a0 %d invalid value(s) must be corrected before import."
                        )
                        % invalid_count
                    )
                self.lbl_eff_summary.setText(summary)
            else:
                self.lbl_eff_summary.setText(
                    self.tr("Field '%s' will be read for each feature.") % eff_field
                )
        else:
            self.lbl_eff_summary.setText(
                self.tr("All features will use the default effectiveness above.")
            )

    def _on_accept(self):
        int_field = self.combo_int_field.currentData()
        eff_field = self.combo_eff_field.currentData()
        self.field_config = {
            "intervention_field": int_field,
            "default_intervention": (
                None if int_field is not None else self._intervention_fallback_key()
            ),
            "effectiveness_field": eff_field,
            "effectiveness_units": self.combo_eff_units.currentData(),
            "default_effectiveness": (
                None if eff_field is not None else self.spin_eff_fallback.value()
            ),
        }
        self.accept()


# ---------------------------------------------------------------------------
# Dialog 1 — ARR Classification
# ---------------------------------------------------------------------------


class DlgCalculateLDNPlanningARR(DlgCalculateBase):
    """Classify land into the LDN Avoid / Reduce / Reverse response hierarchy.

    Inputs:
      - SDG 15.3.1 status layer (required).
      - Land Productivity Dynamics (LPD) layer (optional). Pixels that are not
        degraded overall but whose LPD is class 3 ("stable but stressed") are
        flagged as *Reduce* (at risk) instead of *Avoid*. LPD classes 1/2 are
        already degraded (hence Reverse) and cannot supply the at-risk signal.
      - Custom risk layer (optional binary raster; >0 = at risk → *Reduce*).
    """

    LOCAL_SCRIPT_NAME: str = "ldn-planning-arr"

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

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout()

        # -- Status layer --
        inner = _make_group(self.tr("SDG 15.3.1 Status Layer (required)"), layout)
        inner.addWidget(
            QtWidgets.QLabel(self.tr("Select an existing SDG 15.3.1 status layer:"))
        )
        self.combo_status = data_io.WidgetDataIOSelectTELayerExisting()
        inner.addWidget(self.combo_status)
        # -- Land Productivity Dynamics layer (optional) --
        inner_traj = _make_group(
            self.tr("Land Productivity Dynamics Layer (optional)"), layout
        )
        inner_traj.addWidget(
            QtWidgets.QLabel(
                self.tr(
                    "Optional: non-degraded pixels whose LPD is class 3\n"
                    '("stable but stressed") are classified as Reduce (at risk)\n'
                    "instead of Avoid."
                )
            )
        )
        self.chk_use_trajectory = QtWidgets.QCheckBox(
            self.tr("Use Land Productivity Dynamics layer")
        )
        inner_traj.addWidget(self.chk_use_trajectory)
        self.combo_lpd = data_io.WidgetDataIOSelectTELayerExisting()
        self.combo_lpd.setEnabled(False)
        inner_traj.addWidget(self.combo_lpd)

        self.chk_use_trajectory.toggled.connect(self.combo_lpd.setEnabled)

        # -- Risk layer (optional) --
        inner_risk = _make_group(self.tr("Custom Risk Layer (optional)"), layout)
        inner_risk.addWidget(
            QtWidgets.QLabel(
                self.tr(
                    "Optional: pixels above the selected risk threshold are\n"
                    "classified as Reduce (at risk). Missing supplied risk remains unknown."
                )
            )
        )
        self.chk_use_risk = QtWidgets.QCheckBox(self.tr("Use custom risk layer"))
        inner_risk.addWidget(self.chk_use_risk)
        self.btn_select_risk = QtWidgets.QPushButton(self.tr("Select risk raster..."))
        self.btn_select_risk.setEnabled(False)
        inner_risk.addWidget(self.btn_select_risk)
        self.lbl_risk_path = QtWidgets.QLabel(self.tr("No file selected"))
        self.lbl_risk_path.setWordWrap(True)
        inner_risk.addWidget(self.lbl_risk_path)
        self._risk_path: typing.Optional[str] = None
        self.spin_risk_band = QtWidgets.QSpinBox()
        self.spin_risk_band.setRange(1, 10000)
        inner_risk.addWidget(QtWidgets.QLabel(self.tr("Risk raster band")))
        inner_risk.addWidget(self.spin_risk_band)
        self.spin_risk_threshold = QtWidgets.QDoubleSpinBox()
        self.spin_risk_threshold.setRange(-1e12, 1e12)
        self.spin_risk_threshold.setDecimals(6)
        inner_risk.addWidget(QtWidgets.QLabel(self.tr("At risk when value exceeds")))
        inner_risk.addWidget(self.spin_risk_threshold)

        self.chk_use_risk.toggled.connect(self.btn_select_risk.setEnabled)
        self.btn_select_risk.clicked.connect(self._select_risk)

        self.execution_name_le, self.task_notes = _add_task_name_notes(
            layout, "LDN Planning — ARR"
        )
        self.region_la, self.region_button = _add_region_buttons(layout)

        left = QtWidgets.QWidget()
        left.setLayout(layout)
        self.splitter, self.button_box = _build_splitter_with_ok_cancel(
            self,
            left,
            self.tr(
                "<h3>Avoid / Reduce / Reverse</h3>"
                "<p>Select an SDG 15.3.1 indicator or status layer. Optional "
                "productivity and risk data identify non-degraded areas at risk.</p>"
                "<p>Without risk inputs, valid non-degraded areas default to Avoid. "
                "Check the assignment-reason band and areas with missing data.</p>"
                "<p><a href='https://docs.trends.earth/en/latest/for_users/training/ldnplanning.html'>"
                "LDN planning tutorial</a></p>"
            ),
        )
        self.setWindowTitle(self.tr("Classify land for Avoid, Reduce, and Reverse"))
        self.resize(600, 560)

    def _populate_combos(self):
        self.combo_status.setProperty("layer_type", _SDG_STATUS_LAYERS)
        self.combo_status.populate()
        lpd_types = ";".join(
            [
                ld_config.TE_LPD_BAND_NAME,
                ld_config.JRC_LPD_BAND_NAME,
                ld_config.FAO_WOCAT_LPD_BAND_NAME,
                ld_config.FWV2_LPD_BAND_NAME,
                ld_config.CUSTOM_LPD_BAND_NAME,
            ]
        )
        self.combo_lpd.setProperty("layer_type", lpd_types)
        self.combo_lpd.populate()

    def showEvent(self, event):
        super().showEvent(event)
        self._populate_combos()

    def _select_risk(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr("Select risk raster"),
            "",
            self.tr("Raster files (*.tif *.tiff *.vrt);;All files (*)"),
        )
        if path:
            self._risk_path = path
            self.lbl_risk_path.setText(path)

    def btn_calculate(self):
        if not super().btn_calculate():
            return

        status_info = self.combo_status.get_current_band()
        if status_info is None:
            QtWidgets.QMessageBox.critical(
                self, self.tr("Error"), self.tr("Please select a valid status layer.")
            )
            return

        try:
            status_type = _status_type(status_info)
        except ValueError as exc:
            QtWidgets.QMessageBox.critical(self, self.tr("Error"), str(exc))
            return

        traj_path = None
        traj_band_index = 1
        if self.chk_use_trajectory.isChecked():
            lpd_info = self.combo_lpd.get_current_band()
            if lpd_info is None:
                QtWidgets.QMessageBox.critical(
                    self,
                    self.tr("Error"),
                    self.tr(
                        "Please select a Land Productivity Dynamics layer "
                        "or uncheck the option."
                    ),
                )
                return
            traj_path = str(lpd_info.path)
            traj_band_index = lpd_info.band_index

        risk_path = None
        if self.chk_use_risk.isChecked():
            risk_path = self._risk_path
            if not risk_path:
                QtWidgets.QMessageBox.critical(
                    self,
                    self.tr("Error"),
                    self.tr("Please select a risk raster or uncheck the option."),
                )
                return

        meta = status_info.band_info.metadata or {}
        params = {
            "task_name": self.execution_name_le.text(),
            "task_notes": self.task_notes.toPlainText(),
            "status_layer_path": str(status_info.path),
            "status_band_index": status_info.band_index,
            "status_job_id": str(status_info.job.id),
            "status_type": status_type,
            "trajectory_path": traj_path,
            "trajectory_band_index": traj_band_index,
            "trajectory_job_id": str(lpd_info.job.id) if traj_path else None,
            "risk_layer_path": risk_path,
            "risk_band_index": self.spin_risk_band.value(),
            "risk_threshold": self.spin_risk_threshold.value(),
            "year_initial": meta.get(
                "year_initial", meta.get("reporting_year_initial")
            ),
            "year_final": meta.get("year_final", meta.get("reporting_year_final")),
        }
        self.close()
        job_manager.submit_local_job_as_qgstask(
            params, script_name=self.LOCAL_SCRIPT_NAME, area_of_interest=self.aoi
        )


# ---------------------------------------------------------------------------
# Dialog 2 — Hotspot Prioritization
# ---------------------------------------------------------------------------


class DlgCalculateLDNPlanningHotspots(DlgCalculateBase):
    """Rank administrative units or grid cells by degraded fraction.

    Inputs:
      - SDG 15.3.1 status layer (required).
      - Zoning source (one of): administrative units (geoBoundaries ADM1 of the
        current country), an uploaded polygon layer, or an auto-generated
        fishnet grid.
    """

    LOCAL_SCRIPT_NAME: str = "ldn-planning-hotspots"

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

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout()

        # -- Status layer --
        inner = _make_group(self.tr("SDG 15.3.1 Status Layer (required)"), layout)
        inner.addWidget(QtWidgets.QLabel(self.tr("Select status layer:")))
        self.combo_status = data_io.WidgetDataIOSelectTELayerExisting()
        inner.addWidget(self.combo_status)

        # -- Zones --
        inner_z = _make_group(self.tr("Zoning source"), layout)

        # (a) Administrative units (geoBoundaries ADM1)
        self.rb_zones_admin = QtWidgets.QRadioButton(
            self.tr("Administrative units (level 1) of the selected country")
        )
        self.rb_zones_admin.setChecked(True)
        inner_z.addWidget(self.rb_zones_admin)
        inner_z.addWidget(
            QtWidgets.QLabel(
                self.tr(
                    "    Ranks each first-level administrative unit (state/province)\n"
                    "    of the current region's country as a hotspot zone."
                )
            )
        )

        # (b) Upload polygon layer
        self.rb_zones_upload = QtWidgets.QRadioButton(self.tr("Upload a polygon layer"))
        inner_z.addWidget(self.rb_zones_upload)
        zone_row = QtWidgets.QHBoxLayout()
        self.le_zones_path = QtWidgets.QLineEdit()
        self.le_zones_path.setPlaceholderText(self.tr("No file selected"))
        self.le_zones_path.setReadOnly(True)
        self.btn_zones = QtWidgets.QPushButton(self.tr("Browse..."))
        self.btn_zones.clicked.connect(self._select_zones)
        zone_row.addWidget(self.le_zones_path)
        zone_row.addWidget(self.btn_zones)
        inner_z.addLayout(zone_row)

        # (c) Fishnet grid
        self.rb_zones_grid = QtWidgets.QRadioButton(self.tr("Regular fishnet grid"))
        inner_z.addWidget(self.rb_zones_grid)
        grid_row = QtWidgets.QHBoxLayout()
        grid_row.addWidget(QtWidgets.QLabel(self.tr("Fishnet cell size (km):")))
        self.spin_grid_km = QtWidgets.QDoubleSpinBox()
        self.spin_grid_km.setRange(1.0, 500.0)
        self.spin_grid_km.setValue(50.0)
        self.spin_grid_km.setSuffix(" km")
        grid_row.addWidget(self.spin_grid_km)
        inner_z.addLayout(grid_row)

        self._zones_path: typing.Optional[str] = None

        # Enable/disable sub-widgets based on the selected zoning source
        self.rb_zones_upload.toggled.connect(self.le_zones_path.setEnabled)
        self.rb_zones_upload.toggled.connect(self.btn_zones.setEnabled)
        self.rb_zones_grid.toggled.connect(self.spin_grid_km.setEnabled)
        self.le_zones_path.setEnabled(False)
        self.btn_zones.setEnabled(False)
        self.spin_grid_km.setEnabled(False)

        self.execution_name_le, self.task_notes = _add_task_name_notes(
            layout, "LDN Planning — Hotspots"
        )
        self.region_la, self.region_button = _add_region_buttons(layout)

        left = QtWidgets.QWidget()
        left.setLayout(layout)
        self.splitter, self.button_box = _build_splitter_with_ok_cancel(
            self,
            left,
            self.tr(
                "<h3>Degradation hotspots</h3>"
                "<p>Select an SDG 15.3.1 status layer and administrative units, "
                "your own polygons, or a regular grid. Zones are ranked by their "
                "fraction of degraded land.</p>"
                "<p>Inspect the zone map and report alongside local knowledge.</p>"
                "<p><a href='https://docs.trends.earth/en/latest/for_users/training/ldnplanning.html'>"
                "LDN planning tutorial</a></p>"
            ),
        )
        self.setWindowTitle(
            self.tr("LDN Planning — Degradation Hotspot Prioritization")
        )
        self.resize(600, 560)

    def _populate_combos(self):
        self.combo_status.setProperty("layer_type", _SDG_STATUS_LAYERS)
        self.combo_status.populate()

    def showEvent(self, event):
        super().showEvent(event)
        self._populate_combos()

    def _select_zones(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr("Select zones vector layer"),
            "",
            self.tr("Vector files (*.gpkg *.shp *.geojson);;All files (*)"),
        )
        if path:
            self._zones_path = path
            self.le_zones_path.setText(path)

    def _resolve_admin_zones(self) -> typing.Optional[str]:
        return _resolve_admin_zones(self)

    def btn_calculate(self):
        if not super().btn_calculate():
            return

        status_info = self.combo_status.get_current_band()
        if status_info is None:
            QtWidgets.QMessageBox.critical(
                self, self.tr("Error"), self.tr("Please select a valid status layer.")
            )
            return

        try:
            status_type = _status_type(status_info)
        except ValueError as exc:
            QtWidgets.QMessageBox.critical(self, self.tr("Error"), str(exc))
            return

        # Resolve the zoning source
        zones_path = None
        if self.rb_zones_admin.isChecked():
            zones_path = self._resolve_admin_zones()
            if zones_path is None:
                return
        elif self.rb_zones_upload.isChecked():
            zones_path = self._zones_path
            if not zones_path:
                QtWidgets.QMessageBox.critical(
                    self,
                    self.tr("Error"),
                    self.tr(
                        "Please select a polygon layer or choose another zoning source."
                    ),
                )
                return
        # else: fishnet grid — zones_path stays None and grid_size_km is used

        meta = status_info.band_info.metadata or {}
        params = {
            "task_name": self.execution_name_le.text(),
            "task_notes": self.task_notes.toPlainText(),
            "status_layer_path": str(status_info.path),
            "status_band_index": status_info.band_index,
            "status_type": status_type,
            "zones_path": zones_path,
            "grid_size_km": self.spin_grid_km.value(),
            "year_initial": meta.get(
                "year_initial", meta.get("reporting_year_initial")
            ),
            "year_final": meta.get("year_final", meta.get("reporting_year_final")),
        }
        self.close()
        job_manager.submit_local_job_as_qgstask(
            params, script_name=self.LOCAL_SCRIPT_NAME, area_of_interest=self.aoi
        )


# ---------------------------------------------------------------------------
# Scenario target configuration
# ---------------------------------------------------------------------------


class DlgConfigureCandidateTargets(QtWidgets.QDialog):
    """Configure scenario targets from a candidate-area dataset.

    Shows each selected ARR class with its actual selected area and lets the
    planner assign a separate expected effectiveness per class. Added targets
    are immutable scenario references; their effects are projected, not observed.
    """

    def __init__(self, job, report: dict, classes, default_effectiveness, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Set expected effectiveness"))
        self.effectiveness_by_class: typing.Dict[str, float] = {}
        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(
            self.tr(
                "Set expected effectiveness for each candidate class in '%s'. "
                "Each class receives its effect only where the ARR class "
                "matches. Effectiveness is the expected fraction of the "
                "candidate area where the intervention succeeds; these are "
                "projected effects, not observed gains."
            )
            % (job.task_name or str(job.id))
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        default_form = QtWidgets.QFormLayout()
        self.default_effectiveness = QtWidgets.QDoubleSpinBox()
        self.default_effectiveness.setRange(0, 1)
        self.default_effectiveness.setDecimals(3)
        self.default_effectiveness.setSingleStep(0.05)
        self.default_effectiveness.setValue(default_effectiveness)
        default_form.addRow(
            self.tr("Default expected effectiveness"), self.default_effectiveness
        )
        layout.addLayout(default_form)
        class_labels = {
            "avoid": self.tr("Avoid"),
            "reduce": self.tr("Reduce"),
            "reverse": self.tr("Reverse"),
        }
        summaries = report.get("summary", {}).get("selections", {})
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            [
                self.tr("Class"),
                self.tr("Selected area (km²)"),
                self.tr("Selected pixels"),
                self.tr("Effectiveness (0–1)"),
            ]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self._spins: typing.Dict[str, QtWidgets.QDoubleSpinBox] = {}
        for key in classes:
            row = self.table.rowCount()
            self.table.insertRow(row)
            summary = summaries.get(key, {})
            selected_area = summary.get("selected_area_km2")
            area_text = (
                f"{selected_area:.2f}"
                if isinstance(selected_area, (int, float))
                and not isinstance(selected_area, bool)
                and math.isfinite(selected_area)
                else self.tr("Not available")
            )
            selected_pixels = summary.get("selected_pixels")
            pixels_text = (
                str(selected_pixels)
                if isinstance(selected_pixels, int)
                and not isinstance(selected_pixels, bool)
                else self.tr("Not available")
            )
            for column, text in (
                (0, class_labels.get(key, key)),
                (1, area_text),
                (2, pixels_text),
            ):
                item = QtWidgets.QTableWidgetItem(text)
                item.setFlags(QtCore.Qt.ItemIsEnabled)
                self.table.setItem(row, column, item)
            spin = QtWidgets.QDoubleSpinBox()
            spin.setRange(0, 1)
            spin.setDecimals(3)
            spin.setSingleStep(0.05)
            spin.setValue(self.default_effectiveness.value())
            self.table.setCellWidget(row, 3, spin)
            self._spins[key] = spin
        layout.addWidget(self.table)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText(
            self.tr("Add targets to scenario")
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(560, 320)

    def _accept(self):
        self.default_effectiveness_value = self.default_effectiveness.value()
        self.effectiveness_by_class = {
            key: spin.value() for key, spin in self._spins.items()
        }
        self.accept()


class ScenarioTargetsWidget(QtWidgets.QWidget):
    """Scenario-specific target editing inside the planning tab."""

    changed = QtCore.pyqtSignal()

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.main_dock = panel._main_dock
        self._targets: list[dict] = []
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        self.use_candidates = QtWidgets.QCheckBox(self.tr("Include candidate areas"))
        layout.addWidget(self.use_candidates)
        candidate_group_box = QtWidgets.QGroupBox(self.tr("Candidate areas"))
        self.candidate_group = QtWidgets.QVBoxLayout(candidate_group_box)
        layout.addWidget(candidate_group_box)
        self.candidate_summary = QtWidgets.QLabel()
        self.candidate_summary.setWordWrap(True)
        self.candidate_group.addWidget(self.candidate_summary)
        self.btn_configure_candidates = QtWidgets.QPushButton(
            self.tr("Set expected effectiveness...")
        )
        self.btn_configure_candidates.clicked.connect(self._configure_candidates)
        self.candidate_group.addWidget(self.btn_configure_candidates)
        self.btn_clear_candidate_targets = QtWidgets.QPushButton(
            self.tr("Remove candidate targets")
        )
        self.btn_clear_candidate_targets.clicked.connect(self._clear_candidate_targets)
        self.candidate_group.addWidget(self.btn_clear_candidate_targets)

        self.use_polygons = QtWidgets.QCheckBox(
            self.tr("Include drawn or imported polygons")
        )
        layout.addWidget(self.use_polygons)
        polygon_group_box = QtWidgets.QGroupBox(self.tr("Polygon targets"))
        self.polygon_group = QtWidgets.QVBoxLayout(polygon_group_box)
        layout.addWidget(polygon_group_box)

        description = QtWidgets.QLabel(
            self.tr(
                "Each polygon needs an intervention (Avoid, Reduce, or Reverse) "
                "and expected effectiveness from 0 to 1."
            )
        )
        description.setWordWrap(True)
        self.polygon_group.addWidget(description)

        self.btn_targets_help = QtWidgets.QToolButton()
        self.btn_targets_help.setText(self.tr("Required polygon fields"))
        self.btn_targets_help.setCheckable(True)
        self.btn_targets_help.setStyleSheet("QToolButton { border: none; }")
        self.polygon_group.addWidget(self.btn_targets_help)

        self._help_widget = QtWidgets.QLabel(
            self.tr(
                "Required attributes: intervention (avoid, reduce, reverse) "
                "and effectiveness (0–1 or 0–100%). Notes are optional."
            )
        )
        self._help_widget.setWordWrap(True)
        self._help_widget.setVisible(False)
        self._help_widget.setContentsMargins(12, 0, 0, 0)
        self.polygon_group.addWidget(self._help_widget)
        self.btn_targets_help.toggled.connect(self._toggle_targets_help)

        self.polygon_group.addWidget(QtWidgets.QLabel(self.tr("Saved target layer")))
        self.combo_targets_layer = QtWidgets.QComboBox()
        self.polygon_group.addWidget(self.combo_targets_layer)

        add_menu = QtWidgets.QMenu(self)
        add_menu.addAction(self.tr("Draw new polygons..."), self._create_targets_layer)
        add_menu.addAction(
            self.tr("Import polygon file..."), self._import_targets_from_file
        )
        self.load_targets_action = add_menu.addAction(
            self.tr("Use selected saved layer"), self._load_targets_from_job
        )
        self.btn_add_polygons = QtWidgets.QPushButton(self.tr("Add polygons..."))
        self.btn_add_polygons.setMenu(add_menu)
        self.polygon_group.addWidget(self.btn_add_polygons)

        self.targets_list = QtWidgets.QListWidget()
        self.targets_list.setMaximumHeight(90)
        self.polygon_group.addWidget(self.targets_list)
        self.btn_clear_polygon_targets = QtWidgets.QPushButton(
            self.tr("Remove polygon targets")
        )
        self.btn_clear_polygon_targets.clicked.connect(self._clear_polygon_targets)
        self.polygon_group.addWidget(self.btn_clear_polygon_targets)
        self._targets_jobs: list = []
        self.default_effectiveness = 0.8
        self.execution_name_le, self.task_notes = _add_task_name_notes(
            layout, "LDN Planning — Scenario"
        )
        self.use_candidates.toggled.connect(self.changed)
        self.use_polygons.toggled.connect(self.changed)
        self.use_candidates.toggled.connect(self._update_source_visibility)
        self.use_polygons.toggled.connect(self._update_source_visibility)
        self.execution_name_le.textChanged.connect(self.changed)
        self.task_notes.textChanged.connect(self.changed)
        self._update_source_visibility()

    # Land cover 7-class IPCC labels for per-land-type reporting.
    _LC_LABELS: typing.ClassVar[dict[int, str]] = {
        1: "Tree-covered",
        2: "Grassland",
        3: "Cropland",
        4: "Wetland",
        5: "Artificial",
        6: "Other land",
        7: "Water body",
    }

    def _create_targets_layer(self):
        """Create an editable targets layer without closing the planning tab."""
        if self.main_dock is None:
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("Unavailable"),
                self.tr("The targets layer can only be created from the main window."),
            )
            return
        self.main_dock.create_ldn_targets()
        QtWidgets.QMessageBox.information(
            self,
            self.tr("Draw targets"),
            self.tr(
                "An editable 'LDN Planning Targets' layer has been added to the "
                "map and set as the active layer. To draw target polygons:\n\n"
                "1. Use the QGIS 'Add Polygon Feature' tool (Edit toolbar or "
                "Layer menu → Digitize Features).\n"
                "2. Draw each polygon, then fill in the 'intervention' field "
                "(avoid / reduce / reverse) and 'effectiveness' (0\u20131) in the "
                "attribute form.\n"
                "3. When finished, save the layer (Layer → Save Layer Edits).\n"
                "4. Return to LDN Planning, select the layer, then choose "
                "'Add polygons... → Use selected saved layer'."
            ),
        )
        self._refresh_targets_combo()

    def _toggle_targets_help(self, checked: bool):
        self._help_widget.setVisible(checked)

    def _update_source_visibility(self, *_args):
        self.candidate_group.parentWidget().setVisible(self.use_candidates.isChecked())
        self.polygon_group.parentWidget().setVisible(self.use_polygons.isChecked())
        self.btn_clear_candidate_targets.setVisible(
            self.use_candidates.isChecked()
            and any(target.get("selected_mask_path") for target in self._targets)
        )
        self.btn_clear_polygon_targets.setVisible(
            self.use_polygons.isChecked()
            and any(not target.get("selected_mask_path") for target in self._targets)
        )
        self._refresh_target_list()

    def update_candidate_summary(self):
        job = self.panel._selected("candidate")
        self.btn_configure_candidates.setEnabled(job is not None)
        if job is None:
            self.candidate_summary.setText(
                self.tr("No candidate-area result selected.")
            )
        else:
            self.candidate_summary.setText(
                f"{job.task_name or str(job.id)}\n"
                f"{self.panel._result_metrics('candidate', job)}"
            )
        configured = [
            f"{target['intervention'].title()} {100 * target['effectiveness']:.0f}%"
            for target in self._targets
            if target.get("selected_mask_path")
        ]
        if configured:
            self.candidate_summary.setText(
                self.candidate_summary.text()
                + "\n"
                + self.tr("Configured effectiveness: {0}").format(", ".join(configured))
            )

    def _refresh_targets_combo(self):
        """Repopulate the targets layer combo from the job manager."""
        previous = self.combo_targets_layer.currentData()
        self._targets_jobs = job_manager.get_ldn_targets_jobs()
        self.combo_targets_layer.clear()
        if not self._targets_jobs:
            self.combo_targets_layer.addItem(self.tr("(no saved targets layers)"))
            self.combo_targets_layer.setEnabled(False)
            self.load_targets_action.setEnabled(False)
        else:
            self.combo_targets_layer.setEnabled(True)
            self.load_targets_action.setEnabled(True)
            for j in self._targets_jobs:
                self.combo_targets_layer.addItem(j.task_name or str(j.id), str(j.id))
            index = self.combo_targets_layer.findData(previous)
            if index >= 0:
                self.combo_targets_layer.setCurrentIndex(index)

    def _import_targets_from_file(self):
        """Import an external vector file as a new TE targets dataset."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr("Select target polygon file"),
            "",
            self.tr("Vector files (*.gpkg *.shp *.geojson *.json);;All files (*)"),
        )
        if not path:
            return

        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            info = inspect_targets_file(path)
        except (OSError, ValueError, RuntimeError) as exc:
            QtWidgets.QMessageBox.critical(
                self, self.tr("Cannot inspect targets"), str(exc)
            )
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        if info["feature_count"] == 0:
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("Empty file"),
                self.tr("The selected file contains no features."),
            )
            return

        dlg = DlgImportTargetsFile(path, info, parent=self)
        if dlg.exec() != QtWidgets.QDialog.Accepted or dlg.field_config is None:
            return

        task_name = Path(path).stem
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            job = job_manager.create_ldn_targets_layer_from_file(
                path, dlg.field_config, task_name
            )
        except Exception as exc:
            logger.exception("Failed to import targets from %s", path)
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.critical(
                self,
                self.tr("Import failed"),
                self.tr("Could not import the file:\n%s") % str(exc),
            )
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        if job is None:
            QtWidgets.QMessageBox.critical(
                self,
                self.tr("Import failed"),
                self.tr(
                    "The import did not produce a dataset. "
                    "Check the file and try again."
                ),
            )
            return

        self._refresh_targets_combo()
        idx = self.combo_targets_layer.findData(str(job.id))
        if idx >= 0:
            self.combo_targets_layer.setCurrentIndex(idx)
        logger.info("Imported targets from %s as job %s", path, job.id)

    def _load_targets_from_job(self):
        from te_schemas.results import VectorResults

        idx = self.combo_targets_layer.currentIndex()
        if idx < 0 or not self._targets_jobs:
            QtWidgets.QMessageBox.information(
                self,
                self.tr("No layer"),
                self.tr("No saved LDN Planning Targets layer is available."),
            )
            return
        job = self._targets_jobs[idx]
        job_manager.ensure_results_loaded(job)

        from qgis.core import QgsProject

        from LDMP import layers as _layers

        # Prefer reading from the live QGIS layer so that unsaved edits are
        # included (OGR reads only the committed on-disk state). Locate it by
        # the job_id custom property set when the layer was created.
        qgs_layer = None
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr.customProperty("job_id") == str(job.id):
                qgs_layer = lyr
                break

        # Resolve the on-disk URI as a fallback.
        uri_path = None
        vr = job.get_first_result_by_type(VectorResults)
        if vr is not None and vr.uri is not None and vr.uri.uri is not None:
            uri_path = str(vr.uri.uri)
        else:
            try:
                fp = job_manager.get_job_file_path(job).with_suffix(".gpkg")
                if fp.exists():
                    uri_path = str(fp)
            except (OSError, ValueError) as exc:
                QtWidgets.QMessageBox.critical(
                    self, self.tr("Cannot locate targets"), str(exc)
                )
                return

        # Secondary fallback: find the layer in the project by normalised source
        # path.  This is needed when job_id was stamped on a temporary layer
        # object rather than the actual project layer (e.g. because the layer
        # was already in the project when display_ldn_targets_layer ran, or
        # because of Windows path-separator normalisation in QGIS).
        if qgs_layer is None and uri_path is not None:
            from pathlib import Path as _Path

            uri_norm = _Path(uri_path).as_posix().lower()
            for lyr in QgsProject.instance().mapLayers().values():
                lyr_src = _Path(lyr.source().split("|")[0]).as_posix().lower()
                if lyr_src == uri_norm:
                    qgs_layer = lyr
                    # Stamp job_id so future lookups use the fast path.
                    qgs_layer.setCustomProperty("job_id", str(job.id))
                    break

        # If the layer isn't already in the project, add it from disk.
        if qgs_layer is None:
            if uri_path is None:
                QtWidgets.QMessageBox.critical(
                    self,
                    self.tr("Error"),
                    self.tr(
                        "Could not locate the targets layer. Open it on the map "
                        "(or re-create it) and try again."
                    ),
                )
                return
            qgs_layer = _layers.add_vector_layer(
                str(uri_path), (vr.name if vr else None) or "LDN Planning Targets"
            )
            if qgs_layer is not None:
                qgs_layer.setCustomProperty("job_id", str(job.id))
                _layers.style_ldn_targets_layer(qgs_layer)
        else:
            _layers.style_ldn_targets_layer(qgs_layer)

        # Read features; track validation issues.
        n_added = 0
        n_invalid_interv = 0
        n_null_eff = 0
        n_empty_geom = 0
        _valid = {"avoid", "reduce", "reverse"}
        _default_eff = 0.8

        loaded_targets = []
        if qgs_layer is not None:
            for feat in qgs_layer.getFeatures():
                geom = feat.geometry()
                if geom.isEmpty():
                    n_empty_geom += 1
                    continue
                interv = (feat["intervention"] or "").lower().strip()
                if interv not in _valid:
                    n_invalid_interv += 1
                    continue
                eff = feat["effectiveness"]
                if eff is None or (isinstance(eff, float) and eff != eff):
                    n_null_eff += 1
                    eff = _default_eff
                try:
                    loaded_targets.append(
                        polygon_target(
                            geom.asWkt(), interv, eff, qgs_layer.crs().toWkt()
                        )
                    )
                except (ValueError, TypeError) as exc:
                    QtWidgets.QMessageBox.critical(
                        self,
                        self.tr("Invalid target"),
                        self.tr("Feature %s: %s") % (feat.id(), str(exc)),
                    )
                    return
                n_added += 1
        else:
            from osgeo import ogr as _ogr

            ds = _ogr.Open(str(uri_path), 0) if uri_path else None
            if ds is None:
                QtWidgets.QMessageBox.critical(
                    self, self.tr("Error"), self.tr("Cannot open the selected layer.")
                )
                return
            lyr = ds.GetLayer(0)
            for feat in lyr:
                geom = feat.GetGeometryRef()
                if geom is None:
                    n_empty_geom += 1
                    continue
                interv = (feat.GetField("intervention") or "").lower().strip()
                if interv not in _valid:
                    n_invalid_interv += 1
                    continue
                eff = feat.GetField("effectiveness")
                if eff is None:
                    n_null_eff += 1
                    eff = _default_eff
                try:
                    loaded_targets.append(
                        polygon_target(
                            geom.ExportToWkt(),
                            interv,
                            eff,
                            lyr.GetSpatialRef().ExportToWkt()
                            if lyr.GetSpatialRef()
                            else None,
                        )
                    )
                except (ValueError, TypeError) as exc:
                    QtWidgets.QMessageBox.critical(
                        self, self.tr("Invalid target"), str(exc)
                    )
                    return
                n_added += 1
            del ds

        if n_added == 0 and n_invalid_interv == 0 and n_empty_geom == 0:
            QtWidgets.QMessageBox.information(
                self,
                self.tr("No polygons"),
                self.tr(
                    "The selected layer contains no polygons yet. "
                    "Draw polygons using the QGIS Add Polygon Feature tool, "
                    "then try again."
                ),
            )
            return

        # Warn about validation issues
        warnings_parts = []
        if n_empty_geom:
            warnings_parts.append(
                self.tr("%d target(s) had empty geometry and were skipped.")
                % n_empty_geom
            )
        if n_invalid_interv:
            warnings_parts.append(
                self.tr(
                    "%d polygon(s) had missing or unrecognized 'intervention' "
                    "values and were skipped.\n"
                    "Valid values: avoid, reduce, reverse."
                )
                % n_invalid_interv
            )
        if n_null_eff:
            warnings_parts.append(
                self.tr(
                    "%d polygon(s) had no 'effectiveness' value; "
                    "a default of 80%% was used."
                )
                % n_null_eff
            )
        if warnings_parts:
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("Validation warnings"),
                "\n\n".join(warnings_parts),
            )

        if n_added == 0:
            return

        source_id = str(job.id)
        if (
            any(
                target.get("source_job_id") == source_id
                and not target.get("selected_mask_path")
                for target in self._targets
            )
            and QtWidgets.QMessageBox.question(
                self,
                self.tr("Replace polygon snapshot"),
                self.tr(
                    "Replace the existing snapshot from '%s' with the selected layer?"
                )
                % (job.task_name or source_id),
            )
            != QtWidgets.QMessageBox.StandardButton.Yes
        ):
            return
        self._targets = [
            target
            for target in self._targets
            if target.get("source_job_id") != source_id
        ]
        for target in loaded_targets:
            target["source_job_id"] = source_id
            target["source_name"] = job.task_name or source_id
        self._targets.extend(loaded_targets)
        item_text = self.tr("%d polygon(s) from '%s'") % (
            n_added,
            job.task_name or str(job.id),
        )
        self.targets_list.addItem(item_text)
        logger.info(
            "Loaded %d target polygon(s) from saved layer (job %s)", n_added, job.id
        )
        self.use_polygons.setChecked(True)
        self.changed.emit()

    def _configure_candidate_targets(
        self, job, report: dict, classes: list[str]
    ) -> dict[str, float] | None:
        """Set the expected effectiveness for candidate classes.

        Returns {arr_class: effectiveness}, or None if cancelled.
        """
        dialog = DlgConfigureCandidateTargets(
            job, report, classes, self.default_effectiveness, self
        )
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return None
        self.default_effectiveness = dialog.default_effectiveness_value
        return dialog.effectiveness_by_class

    def _configure_candidates(self):
        from .calculate_ldn_priority import CLASSES, job_raster_path

        self.panel._update_status()
        job = self.panel._selected("candidate")
        if job is None:
            QtWidgets.QMessageBox.information(
                self,
                self.tr("No candidate areas"),
                self.tr("Create a candidate-area dataset first."),
            )
            return
        try:
            context = self.panel.candidate_target_context()
            path, result = job_raster_path(job)
            if not job_manager.ensure_params_loaded(job) or not job.params.get(
                "selections"
            ):
                raise ValueError(self.tr("Candidate selection settings are missing."))
            checksum = file_checksum(path)
            if checksum != result.data.get("report", {}).get("summary", {}).get(
                "mask_sha256"
            ):
                raise ValueError(
                    self.tr(
                        "Candidate raster no longer matches its report. Generate a new selection."
                    )
                )
        except (ValueError, OSError) as exc:
            QtWidgets.QMessageBox.critical(
                self, self.tr("Cannot load candidates"), str(exc)
            )
            return
        report = result.data.get("report", {})
        classes = [key for key in CLASSES if key in job.params.get("selections", {})]
        effectiveness_by_class = self._configure_candidate_targets(job, report, classes)
        if not effectiveness_by_class:
            return
        try:
            current_context = self.panel.candidate_target_context()
        except (ValueError, OSError, RuntimeError) as exc:
            QtWidgets.QMessageBox.critical(
                self, self.tr("Cannot configure candidate targets"), str(exc)
            )
            return
        if context != current_context:
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("Inputs changed"),
                self.tr(
                    "Project inputs changed while configuring candidate targets. "
                    "Configure them again to use the current inputs."
                ),
            )
            return
        source_id = str(job.id)
        self._targets = [
            target for target in self._targets if not target.get("selected_mask_path")
        ]
        for key, effectiveness in effectiveness_by_class.items():
            self._targets.append(
                {
                    "selected_mask_path": path,
                    "intervention": key,
                    "effectiveness": effectiveness,
                    "configured_effectiveness": effectiveness,
                    "source_job_id": source_id,
                    "source_name": job.task_name or source_id,
                    "priority_params": job.params,
                    "mask_sha256": checksum,
                    "configuration_context": context,
                }
            )
        self.use_candidates.setChecked(True)
        self.changed.emit()

    def _clear_targets(self):
        if not self._targets:
            return
        if (
            QtWidgets.QMessageBox.question(
                self,
                self.tr("Remove all targets"),
                self.tr("Remove all candidate and polygon targets from this draft?"),
            )
            != QtWidgets.QMessageBox.StandardButton.Yes
        ):
            return
        self._targets.clear()
        self.targets_list.clear()
        self._update_source_visibility()
        self.changed.emit()

    def _clear_candidate_targets(self):
        self._targets = [
            target for target in self._targets if not target.get("selected_mask_path")
        ]
        self._update_source_visibility()
        self.changed.emit()

    def _clear_polygon_targets(self):
        self._targets = [
            target for target in self._targets if target.get("selected_mask_path")
        ]
        self._update_source_visibility()
        self.changed.emit()

    def restore(self, draft):
        self._targets = copy.deepcopy(draft["targets"])
        self.use_candidates.setChecked(draft["use_candidates"])
        self.use_polygons.setChecked(draft["use_polygons"])
        self.execution_name_le.setText(draft["task_name"])
        self.task_notes.setPlainText(draft["task_notes"])
        self.default_effectiveness = draft["default_effectiveness"]
        self._refresh_target_list()
        self.update_candidate_summary()
        self._update_source_visibility()

    def _refresh_target_list(self):
        self.targets_list.clear()
        sources = {}
        for target in self._targets:
            if target.get("selected_mask_path"):
                continue
            sources.setdefault(target.get("source_job_id"), []).append(target)
        for targets in sources.values():
            effects = ", ".join(
                f"{target['intervention']} {100 * target['effectiveness']:.0f}%"
                for target in targets
            )
            self.targets_list.addItem(
                f"{self.tr('Polygon snapshot')} — "
                f"{len(targets)} {self.tr('polygon(s) from')} "
                f"{targets[0].get('source_name') or self.tr('Targets')} ({effects})"
            )

    def draft_values(self):
        return {
            "targets": copy.deepcopy(self._targets),
            "use_candidates": self.use_candidates.isChecked(),
            "use_polygons": self.use_polygons.isChecked(),
            "task_name": self.execution_name_le.text(),
            "task_notes": self.task_notes.toPlainText(),
            "default_effectiveness": self.default_effectiveness,
        }


# ---------------------------------------------------------------------------
# Dialog 5 — Create Analysis Zones
# ---------------------------------------------------------------------------


class DlgCalculateLDNPlanningLandTypes(DlgCalculateBase):
    """Combine categorical rasters into a reusable, styled land types layer.

    Each unique combination of the selected rasters' class values becomes one
    land type (the same spatial unit logic used by LDN Counterbalancing). The
    output is a saved Int32 land types raster that can be reused across
    analyses (Scenario & BAU Projection, Counterbalancing) without
    recomputation.
    """

    LOCAL_SCRIPT_NAME: str = "ldn-planning-land-types"

    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        script: ExecutionScript,
        parent: QtWidgets.QWidget = None,
    ):
        super().__init__(iface, script, parent)
        self._build_ui()
        self._finish_initialization()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout()

        inner = _make_group(self.tr("Land type-defining rasters (one or more)"), layout)
        inner.addWidget(
            QtWidgets.QLabel(
                self.tr(
                    "Add one or more categorical rasters (e.g. land cover, land\n"
                    "potential, administrative codes). Each unique combination of\n"
                    "their class values becomes one land type."
                )
            )
        )
        self.raster_list = QtWidgets.QListWidget()
        self.raster_list.setMaximumHeight(140)
        inner.addWidget(self.raster_list)

        btn_row = QtWidgets.QHBoxLayout()
        btn_add = QtWidgets.QPushButton(self.tr("Add raster(s)..."))
        btn_add.clicked.connect(self._add_rasters)
        btn_remove = QtWidgets.QPushButton(self.tr("Remove selected"))
        btn_remove.clicked.connect(self._remove_selected_raster)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_remove)
        inner.addLayout(btn_row)

        self.lbl_rasters_info = QtWidgets.QLabel(self.tr("0 raster(s) selected"))
        inner.addWidget(self.lbl_rasters_info)

        self.execution_name_le, self.task_notes = _add_task_name_notes(
            layout, "LDN Planning — Land Types"
        )
        self.region_la, self.region_button = _add_region_buttons(layout)

        left = QtWidgets.QWidget()
        left.setLayout(layout)
        self.splitter, self.button_box = _build_splitter_with_ok_cancel(
            self,
            left,
            self.tr(
                "<h3>Define land types</h3>"
                "<p>Add categorical rasters representing land potential, such as "
                "land cover and soil classes. Each combination becomes a land type.</p>"
                "<p>Use the saved layer for like-for-like scenario breakdowns or "
                "the LDN counterbalancing assessment.</p>"
                "<p><a href='https://docs.trends.earth/en/latest/for_users/training/ldnplanning.html'>"
                "LDN planning tutorial</a></p>"
            ),
        )
        self.setWindowTitle(self.tr("LDN Planning — Define Land Types"))
        self.resize(600, 460)

    def _add_rasters(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            self.tr("Select land type-defining raster(s)"),
            "",
            self.tr("Raster files (*.tif *.tiff *.vrt);;All files (*)"),
        )
        for path in paths:
            self.raster_list.addItem(path)
        self._update_info()

    def _remove_selected_raster(self):
        for item in self.raster_list.selectedItems():
            self.raster_list.takeItem(self.raster_list.row(item))
        self._update_info()

    def _update_info(self):
        n = self.raster_list.count()
        self.lbl_rasters_info.setText(self.tr("%d raster(s) selected") % n)

    def _raster_paths(self) -> typing.List[str]:
        return [
            self.raster_list.item(i).text() for i in range(self.raster_list.count())
        ]

    def btn_calculate(self):
        if not super().btn_calculate():
            return

        raster_paths = self._raster_paths()
        if not raster_paths:
            QtWidgets.QMessageBox.critical(
                self,
                self.tr("Error"),
                self.tr("Please add at least one land type-defining raster."),
            )
            return

        params = {
            "task_name": self.execution_name_le.text(),
            "task_notes": self.task_notes.toPlainText(),
            "raster_paths": raster_paths,
        }
        self.close()
        job_manager.submit_local_job_as_qgstask(
            params, script_name=self.LOCAL_SCRIPT_NAME, area_of_interest=self.aoi
        )
