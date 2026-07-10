"""Parametrization dialogs for the LDN Planning Tool.

Dialogs, all inheriting DlgCalculateBase:
  - DlgCalculateLDNPlanningARR         (ldn-planning-arr)
  - DlgCalculateLDNPlanningHotspots    (ldn-planning-hotspots)
  - DlgCalculateLDNPlanningProjection  (ldn-planning-projection) — Scenario & BAU
  - DlgCalculateLDNPlanningLandTypes      (ldn-planning-land-types) — Define Land Types

All UIs are built programmatically (no .ui file), following the pattern in
LDMP/calculate_counterbalancing.py.
"""

import json
import logging
import tempfile
import typing
from pathlib import Path

import qgis.gui
import te_algorithms.gdal.land_deg.config as ld_config
from qgis.PyQt import QtCore, QtWidgets
from te_schemas.algorithms import ExecutionScript

from . import conf, data_io, download
from .calculate import DlgCalculateBase
from .jobs.manager import job_manager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


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


def _build_splitter_with_ok_cancel(
    dialog: QtWidgets.QDialog, left_content: QtWidgets.QWidget
) -> tuple:
    """
    Wrap *left_content* in a QSplitter + add a button box, as required by
    DlgCalculateBase._finish_initialization.

    Returns (splitter, button_box).
    """
    splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
    splitter.addWidget(left_content)
    splitter.addWidget(QtWidgets.QWidget())  # empty right pane

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


def _inspect_targets_file(path: str) -> dict:
    """Inspect a vector file and return field/feature statistics for the import dialog.

    Returns a dict with:
      - field_names: list of all field names
      - string_fields: fields of string type
      - numeric_fields: fields of numeric type (OFTReal / OFTInteger / OFTInteger64)
      - feature_count: total features
      - intervention_counts: dict {value: count} if 'intervention' field detected
      - effectiveness_range: (min, max) tuple if 'effectiveness' field detected, else None
      - invalid_effectiveness_count: count of records with effectiveness outside [0, 100]
    """
    from osgeo import ogr

    result: dict = {
        "field_names": [],
        "string_fields": [],
        "numeric_fields": [],
        "feature_count": 0,
        "intervention_counts": {},
        "effectiveness_range": None,
        "invalid_effectiveness_count": 0,
    }

    ds = ogr.Open(path, 0)
    if ds is None:
        return result

    try:
        lyr = ds.GetLayer(0)
        if lyr is None:
            return result

        lyr_defn = lyr.GetLayerDefn()
        for i in range(lyr_defn.GetFieldCount()):
            fld = lyr_defn.GetFieldDefn(i)
            name = fld.GetName()
            ftype = fld.GetType()
            result["field_names"].append(name)
            if ftype in (ogr.OFTString, ogr.OFTWideString):
                result["string_fields"].append(name)
            elif ftype in (ogr.OFTReal, ogr.OFTInteger, ogr.OFTInteger64):
                result["numeric_fields"].append(name)

        result["feature_count"] = lyr.GetFeatureCount()

        has_intervention = "intervention" in result["field_names"]
        has_effectiveness = "effectiveness" in result["field_names"]
        eff_values: typing.List[float] = []

        lyr.ResetReading()
        for feat in lyr:
            if has_intervention:
                val = feat.GetField("intervention")
                key = (val or "").strip()
                result["intervention_counts"][key] = (
                    result["intervention_counts"].get(key, 0) + 1
                )
            if has_effectiveness:
                eff = feat.GetField("effectiveness")
                if eff is not None:
                    eff_values.append(float(eff))

        if eff_values:
            mn, mx = min(eff_values), max(eff_values)
            result["effectiveness_range"] = (mn, mx)
            result["invalid_effectiveness_count"] = sum(
                1 for v in eff_values if v < 0 or v > 100
            )
    finally:
        ds = None  # noqa: F841 — closes OGR datasource

    return result


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
                if mx > 1.0:
                    summary += self.tr(
                        " Values > 1 will be treated as percentages (÷ 100)."
                    )
                if invalid_count:
                    summary += (
                        self.tr(
                            "\n\u26a0 %d value(s) outside 0\u2013100 will be clamped."
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
                    "Optional: Binary raster — pixels with value > 0 will be\n"
                    "classified as Reduce (at risk)."
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

        self.chk_use_risk.toggled.connect(self.btn_select_risk.setEnabled)
        self.btn_select_risk.clicked.connect(self._select_risk)

        self.execution_name_le, self.task_notes = _add_task_name_notes(
            layout, "LDN Planning — ARR"
        )
        self.region_la, self.region_button = _add_region_buttons(layout)

        left = QtWidgets.QWidget()
        left.setLayout(layout)
        self.splitter, self.button_box = _build_splitter_with_ok_cancel(self, left)
        self.setWindowTitle(
            self.tr("LDN Planning — Avoid/Reduce/Reverse Classification")
        )
        self.resize(600, 560)

    def _populate_combos(self):
        self.combo_status.setProperty("layer_type", ld_config.SDG_STATUS_BAND_NAME)
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
            "trajectory_path": traj_path,
            "trajectory_band_index": traj_band_index,
            "risk_layer_path": risk_path,
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
        self.splitter, self.button_box = _build_splitter_with_ok_cancel(self, left)
        self.setWindowTitle(
            self.tr("LDN Planning — Degradation Hotspot Prioritization")
        )
        self.resize(600, 560)

    def _populate_combos(self):
        self.combo_status.setProperty("layer_type", ld_config.SDG_STATUS_BAND_NAME)
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
# Dialog 3 — Scenario & BAU Projection (combined)
# ---------------------------------------------------------------------------


class DlgCalculateLDNPlanningProjection(DlgCalculateBase):
    """Combined Scenario & BAU Projection tool.

    Computes the Business-As-Usual degradation trajectory, applies planning
    targets over the same horizon, and compares the scenario against BAU.

    The dialog is organised into tabs (Data / Time / Targets / Breakdown) so it
    stays compact on small screens. The balance sheet separates:
      - Gains  = Reverse targets (only these feed counterbalancing)
      - Avoided losses = Avoid + Reduce targets
    per Cowie et al. (2018) and GPG Addendum §2.2.
    """

    LOCAL_SCRIPT_NAME: str = "ldn-planning-projection"

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
        self._targets: typing.List[typing.Dict] = []

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout()
        tabs = QtWidgets.QTabWidget()
        layout.addWidget(tabs)

        # ================= Tab 1: Data =================
        tab_data = QtWidgets.QWidget()
        data_layout = QtWidgets.QVBoxLayout()
        tab_data.setLayout(data_layout)
        tabs.addTab(tab_data, self.tr("Data"))

        inner_arr = _make_group(
            self.tr("ARR Classification Layer (required)"), data_layout
        )
        inner_arr.addWidget(
            QtWidgets.QLabel(
                self.tr(
                    "Select the Avoid/Reduce/Reverse raster produced by\n"
                    "LDN Planning — ARR Classification:"
                )
            )
        )
        self.combo_arr = data_io.WidgetDataIOSelectTELayerExisting()
        inner_arr.addWidget(self.combo_arr)

        inner_bl = _make_group(
            self.tr("Baseline Period Status Layer (required)"), data_layout
        )
        inner_bl.addWidget(
            QtWidgets.QLabel(
                self.tr("Select the SDG 15.3.1 status layer for the baseline period:")
            )
        )
        self.combo_baseline = data_io.WidgetDataIOSelectTELayerExisting()
        inner_bl.addWidget(self.combo_baseline)

        inner_rp = _make_group(
            self.tr("Reporting Period Status Layer (optional)"), data_layout
        )
        self.chk_use_reporting = QtWidgets.QCheckBox(
            self.tr("Include reporting period layer (needed for the BAU rate)")
        )
        inner_rp.addWidget(self.chk_use_reporting)
        self.combo_reporting = data_io.WidgetDataIOSelectTELayerExisting()
        self.combo_reporting.setEnabled(False)
        inner_rp.addWidget(self.combo_reporting)
        self.chk_use_reporting.toggled.connect(self.combo_reporting.setEnabled)
        data_layout.addStretch()

        # ================= Tab 2: Time =================
        tab_time = QtWidgets.QWidget()
        time_layout = QtWidgets.QVBoxLayout()
        tab_time.setLayout(time_layout)
        tabs.addTab(tab_time, self.tr("Time"))

        inner_yr = _make_group(self.tr("Projection Time Period"), time_layout)
        yr_grid = QtWidgets.QGridLayout()
        yr_grid.addWidget(QtWidgets.QLabel(self.tr("Baseline start year:")), 0, 0)
        self.spin_yr_initial = QtWidgets.QSpinBox()
        self.spin_yr_initial.setRange(1980, 2100)
        self.spin_yr_initial.setValue(2000)
        yr_grid.addWidget(self.spin_yr_initial, 0, 1)
        yr_grid.addWidget(
            QtWidgets.QLabel(self.tr("Baseline / reporting end year:")), 1, 0
        )
        self.spin_yr_final = QtWidgets.QSpinBox()
        self.spin_yr_final.setRange(1980, 2100)
        self.spin_yr_final.setValue(2015)
        yr_grid.addWidget(self.spin_yr_final, 1, 1)
        yr_grid.addWidget(QtWidgets.QLabel(self.tr("Projection target year:")), 2, 0)
        self.spin_target_yr = QtWidgets.QSpinBox()
        self.spin_target_yr.setRange(2000, 2100)
        self.spin_target_yr.setValue(2030)
        yr_grid.addWidget(self.spin_target_yr, 2, 1)
        inner_yr.addLayout(yr_grid)
        info = QtWidgets.QLabel(
            self.tr(
                "LDN frame of reference: the target equals the baseline "
                "(no net loss). Neutrality is the minimum objective. The "
                "scenario is evaluated at the target year against BAU."
            )
        )
        info.setWordWrap(True)
        inner_yr.addWidget(info)
        time_layout.addStretch()

        # ================= Tab 3: Targets =================
        tab_targets = QtWidgets.QWidget()
        t_layout = QtWidgets.QVBoxLayout()
        tab_targets.setLayout(t_layout)
        tabs.addTab(tab_targets, self.tr("Targets"))

        inner_t = _make_group(self.tr("Planning Targets"), t_layout)

        # Intervention description
        inner_t.addWidget(
            QtWidgets.QLabel(
                self.tr(
                    "Add target polygons.  Assign each one an intervention:\n"
                    "  Reverse = restoration → generates counterbalancing GAINS\n"
                    "  Reduce  = SLM         → avoids losses (not gains)\n"
                    "  Avoid   = protection  → avoids losses (not gains)"
                )
            )
        )

        # Collapsible required-fields help section
        self.btn_targets_help = QtWidgets.QToolButton()
        self.btn_targets_help.setText(self.tr("▶ Required dataset fields"))
        self.btn_targets_help.setCheckable(True)
        self.btn_targets_help.setStyleSheet("QToolButton { border: none; }")
        inner_t.addWidget(self.btn_targets_help)

        self._help_widget = QtWidgets.QLabel(
            self.tr(
                "Datasets must have these attribute fields:\n"
                "  intervention  (text)   — 'avoid', 'reduce', or 'reverse'\n"
                "  effectiveness (number) — 0.0\u20131.0  (or 0\u2013100%)\n"
                "  notes         (text, optional)\n\n"
                "Use 'Create layer to draw...' to create a new blank dataset\n"
                "  and digitize polygons directly on the map.\n"
                "Use 'Import from file...' to create a dataset from an existing\n"
                "  GeoJSON, GPKG, or SHP file that already has these fields."
            )
        )
        self._help_widget.setWordWrap(True)
        self._help_widget.setVisible(False)
        self._help_widget.setContentsMargins(12, 0, 0, 0)
        inner_t.addWidget(self._help_widget)
        self.btn_targets_help.toggled.connect(self._toggle_targets_help)

        # Combo listing all TE target layers (drawn + imported)
        inner_t.addWidget(QtWidgets.QLabel(self.tr("Select a targets layer:")))
        self.combo_targets_layer = QtWidgets.QComboBox()
        inner_t.addWidget(self.combo_targets_layer)

        # Three action buttons
        action_row = QtWidgets.QHBoxLayout()
        self.btn_create_targets = QtWidgets.QPushButton(
            self.tr("Create layer to draw...")
        )
        self.btn_create_targets.clicked.connect(self._create_targets_layer)
        self.btn_import_targets = QtWidgets.QPushButton(self.tr("Import from file..."))
        self.btn_import_targets.clicked.connect(self._import_targets_from_file)
        self.btn_load_targets = QtWidgets.QPushButton(
            self.tr("Load from selected layer")
        )
        self.btn_load_targets.clicked.connect(self._load_targets_from_job)
        action_row.addWidget(self.btn_create_targets)
        action_row.addWidget(self.btn_import_targets)
        action_row.addWidget(self.btn_load_targets)
        inner_t.addLayout(action_row)

        btn_clear = QtWidgets.QPushButton(self.tr("Clear loaded targets"))
        btn_clear.clicked.connect(self._clear_targets)
        inner_t.addWidget(btn_clear)

        self.targets_list = QtWidgets.QListWidget()
        self.targets_list.setMaximumHeight(90)
        inner_t.addWidget(self.targets_list)

        self._targets_jobs: typing.List = []
        t_layout.addStretch()

        # ================= Tab 4: Breakdown =================
        tab_bd = QtWidgets.QWidget()
        bd_layout = QtWidgets.QVBoxLayout()
        tab_bd.setLayout(bd_layout)
        tabs.addTab(tab_bd, self.tr("Breakdown"))

        inner_lt = _make_group(
            self.tr("Land types (for per-land-type balance sheet)"), bd_layout
        )
        inner_lt.addWidget(
            QtWidgets.QLabel(
                self.tr(
                    "Choose how land types (land potential classes) are defined\n"
                    "for the 'like for like' balance sheet."
                )
            )
        )
        self.rb_lt_lc = QtWidgets.QRadioButton(self.tr("Land cover layer"))
        self.rb_lt_lc.setChecked(True)
        inner_lt.addWidget(self.rb_lt_lc)
        self.combo_land_type = data_io.WidgetDataIOSelectTELayerExisting()
        inner_lt.addWidget(self.combo_land_type)
        self.rb_lt_saved = QtWidgets.QRadioButton(
            self.tr("Saved land types layer (from the Define Land Types tool)")
        )
        inner_lt.addWidget(self.rb_lt_saved)
        saved_lt_row = QtWidgets.QHBoxLayout()
        self.combo_scn_zones_job = QtWidgets.QComboBox()
        self.combo_scn_zones_job.setEnabled(False)
        saved_lt_row.addWidget(self.combo_scn_zones_job)
        inner_lt.addLayout(saved_lt_row)
        self.rb_lt_saved.toggled.connect(self.combo_scn_zones_job.setEnabled)
        self.rb_lt_none = QtWidgets.QRadioButton(self.tr("No land type breakdown"))
        inner_lt.addWidget(self.rb_lt_none)
        self.rb_lt_lc.toggled.connect(self.combo_land_type.setEnabled)

        inner_j = _make_group(
            self.tr("Jurisdictions (for per-jurisdiction balance sheet, optional)"),
            bd_layout,
        )
        inner_j.addWidget(
            QtWidgets.QLabel(
                self.tr(
                    "Optionally break down gains and avoided losses by sub-national\n"
                    "jurisdiction (administrative units or custom polygons)."
                )
            )
        )
        self.rb_jur_none = QtWidgets.QRadioButton(
            self.tr("No jurisdictions — national totals only")
        )
        self.rb_jur_none.setChecked(True)
        inner_j.addWidget(self.rb_jur_none)
        self.rb_jur_admin = QtWidgets.QRadioButton(
            self.tr("Administrative units (level 1) of the selected country")
        )
        inner_j.addWidget(self.rb_jur_admin)
        self.rb_jur_upload = QtWidgets.QRadioButton(self.tr("Upload a polygon layer"))
        inner_j.addWidget(self.rb_jur_upload)
        scn_zone_row = QtWidgets.QHBoxLayout()
        self.le_scn_zones = QtWidgets.QLineEdit()
        self.le_scn_zones.setPlaceholderText(self.tr("No file selected"))
        self.le_scn_zones.setReadOnly(True)
        self.btn_scn_zones = QtWidgets.QPushButton(self.tr("Browse..."))
        self.btn_scn_zones.clicked.connect(self._select_scn_zones)
        scn_zone_row.addWidget(self.le_scn_zones)
        scn_zone_row.addWidget(self.btn_scn_zones)
        inner_j.addLayout(scn_zone_row)
        self._scn_zones_path: typing.Optional[str] = None
        self._land_types_jobs: typing.List = []
        self.le_scn_zones.setEnabled(False)
        self.btn_scn_zones.setEnabled(False)
        self.rb_jur_upload.toggled.connect(self.le_scn_zones.setEnabled)
        self.rb_jur_upload.toggled.connect(self.btn_scn_zones.setEnabled)
        bd_layout.addStretch()

        # ================= Below tabs (always visible) =================
        self.execution_name_le, self.task_notes = _add_task_name_notes(
            layout, "LDN Planning — Scenario & BAU"
        )
        self.region_la, self.region_button = _add_region_buttons(layout)

        left = QtWidgets.QWidget()
        left.setLayout(layout)
        self.splitter, self.button_box = _build_splitter_with_ok_cancel(self, left)
        self.setWindowTitle(self.tr("LDN Planning — Scenario & BAU Projection"))
        self.resize(680, 600)

    # Land cover 7-class IPCC labels for per-land-type reporting.
    _LC_LABELS = {
        1: "Tree-covered",
        2: "Grassland",
        3: "Cropland",
        4: "Wetland",
        5: "Artificial",
        6: "Other land",
        7: "Water body",
    }

    def _select_scn_zones(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr("Select land types vector layer"),
            "",
            self.tr("Vector files (*.gpkg *.shp *.geojson);;All files (*)"),
        )
        if path:
            self._scn_zones_path = path
            self.le_scn_zones.setText(path)

    def _selected_saved_land_types(self):
        """Return (land_types_raster_path, {id: label}) for the selected land types job."""
        from te_schemas.results import RasterResults

        idx = self.combo_scn_zones_job.currentIndex()
        if idx < 0 or not self._land_types_jobs:
            QtWidgets.QMessageBox.critical(
                self,
                self.tr("Error"),
                self.tr("No saved land types layer is available."),
            )
            return None, None
        job = self._land_types_jobs[idx]
        job_manager.ensure_results_loaded(job)
        rr = job.get_first_result_by_type(RasterResults)
        if rr is None or rr.uri is None or rr.uri.uri is None:
            QtWidgets.QMessageBox.critical(
                self,
                self.tr("Error"),
                self.tr("The selected land types layer has no raster data."),
            )
            return None, None
        labels = {}
        data = getattr(rr, "data", None) or {}
        units = (data.get("land_types_key") or {}).get("units", {})
        for k, v in units.items():
            try:
                labels[int(k)] = (
                    v.get("label", str(k)) if isinstance(v, dict) else str(v)
                )
            except (TypeError, ValueError):
                continue
        return str(rr.uri.uri), labels

    def _populate_combos(self):
        self.combo_arr.setProperty("layer_type", "LDN Planning — Avoid/Reduce/Reverse")
        self.combo_arr.populate()
        self.combo_baseline.setProperty("layer_type", ld_config.SDG_STATUS_BAND_NAME)
        self.combo_baseline.populate()
        self.combo_reporting.setProperty("layer_type", ld_config.SDG_STATUS_BAND_NAME)
        self.combo_reporting.populate()
        # Land cover layers (7-class or standard) act as the land-type proxy.
        lc_types = ld_config.LC_BAND_NAME
        if isinstance(lc_types, (list, tuple)):
            lc_types = ";".join(lc_types)
        self.combo_land_type.setProperty("layer_type", lc_types)
        self.combo_land_type.populate()
        # Saved land types (from the Define Land Types tool)
        self._land_types_jobs = job_manager.get_ldn_land_types_jobs()
        self.combo_scn_zones_job.clear()
        if not self._land_types_jobs:
            self.combo_scn_zones_job.addItem(self.tr("(no saved land types)"))
            self.rb_lt_saved.setEnabled(False)
        else:
            self.rb_lt_saved.setEnabled(True)
            for j in self._land_types_jobs:
                self.combo_scn_zones_job.addItem(j.task_name or str(j.id), str(j.id))
        self._targets_jobs = job_manager.get_ldn_targets_jobs()
        self._refresh_targets_combo()

    def _create_targets_layer(self):
        """Create an editable targets layer and close so the user can digitize."""
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
                "4. Re-open this tool, select the layer in the combo, and click "
                "'Load from selected layer'."
            ),
        )
        self.reject()

    def _toggle_targets_help(self, checked: bool):
        self.btn_targets_help.setText(
            self.tr("▼ Required dataset fields")
            if checked
            else self.tr("▶ Required dataset fields")
        )
        self._help_widget.setVisible(checked)

    def _refresh_targets_combo(self):
        """Repopulate the targets layer combo from the job manager."""
        self._targets_jobs = job_manager.get_ldn_targets_jobs()
        self.combo_targets_layer.clear()
        if not self._targets_jobs:
            self.combo_targets_layer.addItem(self.tr("(no saved targets layers)"))
            self.combo_targets_layer.setEnabled(False)
            self.btn_load_targets.setEnabled(False)
        else:
            self.combo_targets_layer.setEnabled(True)
            self.btn_load_targets.setEnabled(True)
            for j in self._targets_jobs:
                self.combo_targets_layer.addItem(j.task_name or str(j.id), str(j.id))

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
            info = _inspect_targets_file(path)
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
            except Exception:
                uri_path = None

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
        _valid = {"avoid", "reduce", "reverse"}
        _default_eff = 0.8

        if qgs_layer is not None:
            if qgs_layer.isEditable():
                qgs_layer.commitChanges(stopEditing=False)
            for feat in qgs_layer.getFeatures():
                geom = feat.geometry()
                if geom.isEmpty():
                    continue
                interv = (feat["intervention"] or "").lower().strip()
                if interv not in _valid:
                    n_invalid_interv += 1
                    continue
                eff = feat["effectiveness"]
                if eff is None or (isinstance(eff, float) and eff != eff):
                    n_null_eff += 1
                    eff = _default_eff
                self._targets.append(
                    {
                        "wkt_geometry": geom.asWkt(),
                        "intervention": interv,
                        "effectiveness": float(eff),
                    }
                )
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
                    continue
                interv = (feat.GetField("intervention") or "").lower().strip()
                if interv not in _valid:
                    n_invalid_interv += 1
                    continue
                eff = feat.GetField("effectiveness")
                if eff is None:
                    n_null_eff += 1
                    eff = _default_eff
                self._targets.append(
                    {
                        "wkt_geometry": geom.ExportToWkt(),
                        "intervention": interv,
                        "effectiveness": float(eff),
                    }
                )
                n_added += 1
            del ds

        if n_added == 0 and n_invalid_interv == 0:
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

        item_text = self.tr("%d polygon(s) from '%s'") % (
            n_added,
            job.task_name or str(job.id),
        )
        self.targets_list.addItem(item_text)
        logger.info(
            "Loaded %d target polygon(s) from saved layer (job %s)", n_added, job.id
        )

    def showEvent(self, event):
        super().showEvent(event)
        self._populate_combos()

    def _clear_targets(self):
        self._targets.clear()
        self.targets_list.clear()

    def btn_calculate(self):
        if not super().btn_calculate():
            return

        arr_info = self.combo_arr.get_current_band()
        if arr_info is None:
            QtWidgets.QMessageBox.critical(
                self,
                self.tr("Error"),
                self.tr("Please select a valid ARR classification layer."),
            )
            return

        bl_info = self.combo_baseline.get_current_band()
        if bl_info is None:
            QtWidgets.QMessageBox.critical(
                self,
                self.tr("Error"),
                self.tr("Please select a baseline status layer (Data tab)."),
            )
            return

        rp_info = None
        if self.chk_use_reporting.isChecked():
            rp_info = self.combo_reporting.get_current_band()
            if rp_info is None:
                QtWidgets.QMessageBox.critical(
                    self,
                    self.tr("Error"),
                    self.tr(
                        "Please select a reporting status layer or uncheck the "
                        "option (Data tab)."
                    ),
                )
                return

        if not self._targets:
            reply = QtWidgets.QMessageBox.question(
                self,
                self.tr("No targets"),
                self.tr(
                    "No planning targets have been added. "
                    "The scenario will produce no changes. Continue anyway?"
                ),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return

        # Land-type layer: land cover combo OR saved land types raster
        land_type_path = None
        land_type_band_index = 1
        land_type_labels = None
        zones_raster_path = None
        zones_raster_labels = None
        if self.rb_lt_lc.isChecked():
            lt_info = self.combo_land_type.get_current_band()
            if lt_info is not None:
                land_type_path = str(lt_info.path)
                land_type_band_index = lt_info.band_index
                land_type_labels = self._LC_LABELS
        elif self.rb_lt_saved.isChecked():
            _lt_raster, _lt_labels = self._selected_saved_land_types()
            if _lt_raster is None:
                return
            land_type_path = _lt_raster
            land_type_band_index = 1
            land_type_labels = _lt_labels

        # Jurisdiction source (optional): admin boundaries / uploaded vector
        jurisdictions_path = None
        if self.rb_jur_admin.isChecked():
            jurisdictions_path = _resolve_admin_zones(self)
            if jurisdictions_path is None:
                return
        elif self.rb_jur_upload.isChecked():
            jurisdictions_path = self._scn_zones_path
            if not jurisdictions_path:
                QtWidgets.QMessageBox.critical(
                    self,
                    self.tr("Error"),
                    self.tr("Please select a polygon layer for jurisdictions."),
                )
                return

        params = {
            "task_name": self.execution_name_le.text(),
            "task_notes": self.task_notes.toPlainText(),
            "arr_layer_path": str(arr_info.path),
            "arr_band_index": arr_info.band_index,
            "status_baseline_path": str(bl_info.path),
            "status_baseline_band_index": bl_info.band_index,
            "status_reporting_path": str(rp_info.path) if rp_info else None,
            "status_reporting_band_index": rp_info.band_index if rp_info else 1,
            "year_initial": self.spin_yr_initial.value(),
            "year_final": self.spin_yr_final.value(),
            "target_year": self.spin_target_yr.value(),
            "targets": self._targets,
            "land_type_path": land_type_path,
            "land_type_band_index": land_type_band_index,
            "land_type_labels": land_type_labels,
            "jurisdictions_path": jurisdictions_path,
        }
        self.close()
        job_manager.submit_local_job_as_qgstask(
            params, script_name=self.LOCAL_SCRIPT_NAME, area_of_interest=self.aoi
        )


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
        self.splitter, self.button_box = _build_splitter_with_ok_cancel(self, left)
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
