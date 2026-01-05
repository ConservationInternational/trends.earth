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

# pylint: disable=import-error
import json
import typing
import weakref
from dataclasses import asdict, dataclass
from pathlib import Path

import qgis.gui
import te_algorithms.gdal.land_deg.config as ld_config
from qgis.core import QgsGeometry
from qgis.PyQt import QtCore, QtGui, QtWidgets, uic
from te_schemas.algorithms import ExecutionScript
from te_schemas.land_cover import LCLegendNesting, LCTransitionDefinitionDeg
from te_schemas.productivity import ProductivityMode

from . import conf, lc_setup
from .calculate import DlgCalculateBase
from .jobs.manager import job_manager
from .localexecution import ldn
from .logger import log

DlgCalculateOneStepUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateOneStep.ui")
)
DlgCalculateLdnSummaryTableAdminUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateLDNSummaryTableAdmin.ui")
)
DlgCalculateLdnErrorRecodeUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateLDNErrorRecode.ui")
)
DlgTimelinePeriodGraphUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgTimelinePeriodGraph.ui")
)


class tr_calculate_ldn:
    def tr(self, message):
        return QtCore.QCoreApplication.translate("tr_calculate_ldn", message)


@dataclass
class TimePeriodWidgets:
    radio_time_period_same: QtWidgets.QRadioButton
    radio_lpd_te: QtWidgets.QRadioButton
    cb_lpd: QtWidgets.QRadioButton
    year_initial: QtWidgets.QDateEdit
    year_final: QtWidgets.QDateEdit
    label_prod: QtWidgets.QLabel
    year_initial_prod: QtWidgets.QDateEdit
    year_final_prod: QtWidgets.QDateEdit
    label_lc: QtWidgets.QLabel
    year_initial_lc: QtWidgets.QDateEdit
    year_final_lc: QtWidgets.QDateEdit
    label_soc: QtWidgets.QLabel
    year_initial_soc: QtWidgets.QDateEdit
    year_final_soc: QtWidgets.QDateEdit
    radio_fao_wocat: QtWidgets.QRadioButton
    radio_lpd_precalculated: QtWidgets.QRadioButton
    radio_lpd_custom: QtWidgets.QRadioButton = None
    cb_custom_lpd: QtWidgets.QComboBox = None


@dataclass
class LDNPresetPeriod:
    """Base class for period configuration for LDN calculations."""

    year_initial: int
    year_final: int
    year_initial_lc: int
    year_final_lc: int
    year_initial_soc: int
    year_final_soc: int
    time_period_same: bool

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data["period_type"] = self.__class__.__name__
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "LDNPresetPeriod":
        """Create from dictionary for JSON deserialization."""
        # Remove period_type from data to avoid constructor issues
        data_copy = data.copy()
        period_type = data_copy.pop("period_type", cls.__name__)

        # Route to appropriate subclass based on period_type
        if period_type == ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value:
            return TrendsEarthPeriod(**data_copy)
        elif period_type == ProductivityMode.JRC_5_CLASS_LPD.value:
            return JRCPeriod(**data_copy)
        elif period_type == ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value:
            return FAOWOCATPeriod(**data_copy)
        else:
            return cls(**data_copy)


@dataclass
class TrendsEarthPeriod(LDNPresetPeriod):
    """Period configuration for Trends.Earth productivity mode"""

    year_initial_prod: int
    year_final_prod: int
    period_type: str = ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value


@dataclass
class JRCPeriod(LDNPresetPeriod):
    """Period configuration for JRC pre-calculated productivity mode."""

    year_initial_prod: int
    year_final_prod: int
    jrc_dataset: str = ""
    period_type: str = ProductivityMode.JRC_5_CLASS_LPD.value


@dataclass
class FAOWOCATPeriod(LDNPresetPeriod):
    """Period configuration for FAO-WOCAT productivity mode."""

    year_initial_prod: int
    year_final_prod: int
    period_type: str = ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value


@dataclass
class LDNPreset:
    """Represents a complete preset configuration for LDN calculations."""

    name: str
    description: str = ""
    progress_periods_enabled: bool = True
    productivity_mode: str = (
        ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value
    )  # ProductivityMode values
    baseline_period: typing.Optional[LDNPresetPeriod] = None
    progress_periods: typing.Optional[list[LDNPresetPeriod]] = None
    reset_legend: bool = True
    is_built_in: bool = False

    def __post_init__(self):
        """Initialize default values for mutable fields."""
        if self.progress_periods is None:
            self.progress_periods = []

    def _create_period_for_mode(self, **kwargs) -> LDNPresetPeriod:
        """Create appropriate period type based on productivity mode."""
        # Remove period_type if it's in kwargs to avoid conflicts
        kwargs.pop("period_type", None)

        if self.productivity_mode == ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value:
            return TrendsEarthPeriod(**kwargs)
        elif self.productivity_mode == ProductivityMode.JRC_5_CLASS_LPD.value:
            return JRCPeriod(**kwargs)
        elif self.productivity_mode == ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value:
            return FAOWOCATPeriod(**kwargs)
        else:
            # Default to base class for unknown modes
            return LDNPresetPeriod(**kwargs)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        if self.baseline_period:
            data["baseline_period"] = self.baseline_period.to_dict()
        data["progress_periods"] = [
            period.to_dict() for period in (self.progress_periods or [])
        ]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "LDNPreset":
        """Create from dictionary for JSON deserialization."""
        data = data.copy()  # Don't modify original
        if "baseline_period" in data and data["baseline_period"]:
            data["baseline_period"] = LDNPresetPeriod.from_dict(data["baseline_period"])
        if "progress_periods" in data:
            data["progress_periods"] = [
                LDNPresetPeriod.from_dict(p) for p in data["progress_periods"]
            ]
        return cls(**data)


class LDNPresetManager:
    """Manages LDN presets including built-in and user-defined presets."""

    SETTINGS_KEY = "LDMP/ldn_presets"

    def __init__(self):
        # Use default QSettings to match other LDMP plugin usage patterns
        self.settings = QtCore.QSettings()
        self._built_in_presets = self._create_built_in_presets()
        self._user_presets = self._load_user_presets()

    def _create_built_in_presets(self) -> list[LDNPreset]:
        """Create the built-in UNCCD presets."""
        presets = []

        presets.append(
            LDNPreset(
                name="UNCCD Reporting (2026 reporting cycle - Default Data, Trends.Earth)",
                description="Default UNCCD reporting period using Trends.Earth land productivity dynamics",
                progress_periods_enabled=True,
                productivity_mode=ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value,
                baseline_period=TrendsEarthPeriod(
                    year_initial=2000,
                    year_final=2015,
                    year_initial_lc=2000,
                    year_final_lc=2015,
                    year_initial_soc=2000,
                    year_final_soc=2015,
                    time_period_same=False,
                    year_initial_prod=2001,
                    year_final_prod=2015,
                ),
                progress_periods=[
                    TrendsEarthPeriod(
                        year_initial=2015,
                        year_final=2019,
                        year_initial_lc=2015,
                        year_final_lc=2019,
                        year_initial_soc=2015,
                        year_final_soc=2019,
                        time_period_same=False,
                        year_initial_prod=2004,
                        year_final_prod=2019,
                    ),
                    TrendsEarthPeriod(
                        year_initial=2015,
                        year_final=2023,
                        year_initial_lc=2015,
                        year_final_lc=2022,
                        year_initial_soc=2015,
                        year_final_soc=2022,
                        time_period_same=False,
                        year_initial_prod=2008,
                        year_final_prod=2023,
                    ),
                ],
                reset_legend=True,
                is_built_in=True,
            )
        )

        presets.append(
            LDNPreset(
                name="UNCCD Reporting (2026 reporting cycle, JRC)",
                description="Default UNCCD reporting period using JRC data",
                progress_periods_enabled=True,
                productivity_mode=ProductivityMode.JRC_5_CLASS_LPD.value,
                baseline_period=JRCPeriod(
                    year_initial=2000,
                    year_final=2015,
                    year_initial_lc=2000,
                    year_final_lc=2015,
                    year_initial_soc=2000,
                    year_final_soc=2015,
                    time_period_same=False,
                    year_initial_prod=2000,
                    year_final_prod=2015,
                    jrc_dataset="JRC Land Productivity Dynamics (2000-2015)",
                ),
                progress_periods=[
                    JRCPeriod(
                        year_initial=2015,
                        year_final=2019,
                        year_initial_lc=2015,
                        year_final_lc=2019,
                        year_initial_soc=2015,
                        year_final_soc=2019,
                        time_period_same=False,
                        year_initial_prod=2004,
                        year_final_prod=2019,
                        jrc_dataset="JRC Land Productivity Dynamics (2004-2019)",
                    ),
                    JRCPeriod(
                        year_initial=2015,
                        year_final=2023,
                        year_initial_lc=2015,
                        year_final_lc=2022,
                        year_initial_soc=2015,
                        year_final_soc=2022,
                        time_period_same=False,
                        year_initial_prod=2008,
                        year_final_prod=2023,
                        jrc_dataset="JRC Land Productivity Dynamics (2008-2023)",
                    ),
                ],
                reset_legend=True,
                is_built_in=True,
            )
        )

        presets.append(
            LDNPreset(
                name="UNCCD Reporting (2026 reporting cycle, FAO-WOCAT)",
                description="Default UNCCD reporting period using FAO-WOCAT data",
                progress_periods_enabled=True,
                productivity_mode=ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value,
                baseline_period=FAOWOCATPeriod(
                    year_initial=2000,
                    year_final=2015,
                    year_initial_lc=2000,
                    year_final_lc=2015,
                    year_initial_soc=2000,
                    year_final_soc=2015,
                    time_period_same=False,
                    year_initial_prod=2001,
                    year_final_prod=2015,
                ),
                progress_periods=[
                    FAOWOCATPeriod(
                        year_initial=2015,
                        year_final=2019,
                        year_initial_lc=2015,
                        year_final_lc=2019,
                        year_initial_soc=2015,
                        year_final_soc=2019,
                        time_period_same=False,
                        year_initial_prod=2004,
                        year_final_prod=2019,
                    ),
                    FAOWOCATPeriod(
                        year_initial=2015,
                        year_final=2023,
                        year_initial_lc=2015,
                        year_final_lc=2022,
                        year_initial_soc=2015,
                        year_final_soc=2022,
                        time_period_same=False,
                        year_initial_prod=2008,
                        year_final_prod=2023,
                    ),
                ],
                reset_legend=True,
                is_built_in=True,
            )
        )

        return presets

    def _load_user_presets(self) -> list[LDNPreset]:
        """Load user-defined presets from QSettings."""
        presets = []
        presets_data = self.settings.value(self.SETTINGS_KEY, [])

        if isinstance(presets_data, str):
            try:
                presets_data = json.loads(presets_data)
            except (json.JSONDecodeError, TypeError):
                presets_data = []

        for preset_data in presets_data:
            try:
                preset = LDNPreset.from_dict(preset_data)
                presets.append(preset)
            except (TypeError, KeyError) as e:
                log(f"Failed to load preset: {e}")

        return presets

    def _save_user_presets(self):
        """Save user-defined presets to QSettings."""
        presets_data = [preset.to_dict() for preset in self._user_presets]
        self.settings.setValue(self.SETTINGS_KEY, json.dumps(presets_data))
        self.settings.sync()  # Force write to disk

    def get_all_presets(self) -> list[LDNPreset]:
        """Get all presets (built-in and user-defined)."""
        return self._built_in_presets + self._user_presets

    def get_preset_by_name(self, name: str) -> typing.Optional[LDNPreset]:
        """Get a preset by name."""
        for preset in self.get_all_presets():
            if preset.name == name:
                return preset
        return None

    def add_user_preset(self, preset: LDNPreset):
        """Add a new user-defined preset."""
        preset.is_built_in = False
        self._user_presets.append(preset)
        self._save_user_presets()

    def update_user_preset(self, name: str, preset: LDNPreset):
        """Update an existing user-defined preset."""
        for i, existing_preset in enumerate(self._user_presets):
            if existing_preset.name == name:
                preset.is_built_in = False
                self._user_presets[i] = preset
                self._save_user_presets()
                return True
        return False

    def delete_user_preset(self, name: str) -> bool:
        """Delete a user-defined preset."""
        for i, preset in enumerate(self._user_presets):
            if preset.name == name:
                del self._user_presets[i]
                self._save_user_presets()
                return True
        return False

    def export_presets(
        self, file_path: str, preset_names: typing.Optional[list[str]] = None
    ):
        """Export presets to JSON file."""
        if preset_names is None:
            presets_to_export = self.get_all_presets()
        else:
            presets_to_export = [
                p
                for p in [self.get_preset_by_name(name) for name in preset_names]
                if p is not None
            ]

        export_data = {
            "version": "1.0",
            "presets": [preset.to_dict() for preset in presets_to_export],
        }

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

    def import_presets(self, file_path: str) -> tuple[int, list[str]]:
        """Import presets from JSON file. Returns (count_imported, errors)."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                import_data = json.load(f)

            if not isinstance(import_data, dict) or "presets" not in import_data:
                return 0, ["Invalid preset file format"]

            imported_count = 0
            errors = []

            for preset_data in import_data["presets"]:
                try:
                    preset = LDNPreset.from_dict(preset_data)
                    # Check if preset with same name exists
                    existing = self.get_preset_by_name(preset.name)
                    if existing and existing.is_built_in:
                        errors.append(
                            f"Cannot overwrite built-in preset: {preset.name}"
                        )
                        continue
                    elif existing:
                        self.update_user_preset(preset.name, preset)
                    else:
                        self.add_user_preset(preset)
                    imported_count += 1
                except (TypeError, KeyError) as e:
                    errors.append(f"Failed to import preset: {e}")

            return imported_count, errors

        except (IOError, json.JSONDecodeError) as e:
            return 0, [f"Failed to read preset file: {e}"]


class PresetSaveDialog(QtWidgets.QDialog):
    """Dialog for saving a new preset."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Save Preset")
        self.setModal(True)
        self.resize(400, 150)

        layout = QtWidgets.QVBoxLayout(self)

        # Name input
        layout.addWidget(QtWidgets.QLabel("Preset Name:"))
        self.name_edit = QtWidgets.QLineEdit()
        layout.addWidget(self.name_edit)

        # Description input
        layout.addWidget(QtWidgets.QLabel("Description (optional):"))
        self.description_edit = QtWidgets.QTextEdit()
        self.description_edit.setMaximumHeight(60)
        layout.addWidget(self.description_edit)

        # Buttons
        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # Validation
        button_box.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
        self.name_edit.textChanged.connect(self._validate)

    def _validate(self):
        """Enable OK button only if name is provided."""
        ok_button = self.findChild(QtWidgets.QDialogButtonBox).button(
            QtWidgets.QDialogButtonBox.Ok
        )
        ok_button.setEnabled(bool(self.name_edit.text().strip()))

    def get_name(self) -> str:
        """Get the preset name."""
        return self.name_edit.text().strip()

    def get_description(self) -> str:
        """Get the preset description."""
        return self.description_edit.toPlainText().strip()


class PresetExportDialog(QtWidgets.QDialog):
    """Dialog for selecting presets to export."""

    def __init__(self, presets: list[LDNPreset], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Presets")
        self.setModal(True)
        self.resize(400, 300)

        layout = QtWidgets.QVBoxLayout(self)

        layout.addWidget(QtWidgets.QLabel("Select presets to export:"))

        # Preset list with checkboxes
        self.preset_list = QtWidgets.QListWidget()
        for preset in presets:
            item = QtWidgets.QListWidgetItem(preset.name)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked)
            item.setData(QtCore.Qt.UserRole, preset.name)
            self.preset_list.addItem(item)

        layout.addWidget(self.preset_list)

        # Select all/none buttons
        button_layout = QtWidgets.QHBoxLayout()
        select_all_btn = QtWidgets.QPushButton("Select All")
        select_none_btn = QtWidgets.QPushButton("Select None")
        select_all_btn.clicked.connect(self._select_all)
        select_none_btn.clicked.connect(self._select_none)
        button_layout.addWidget(select_all_btn)
        button_layout.addWidget(select_none_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        # Dialog buttons
        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _select_all(self):
        """Select all presets."""
        for i in range(self.preset_list.count()):
            self.preset_list.item(i).setCheckState(QtCore.Qt.Checked)

    def _select_none(self):
        """Deselect all presets."""
        for i in range(self.preset_list.count()):
            self.preset_list.item(i).setCheckState(QtCore.Qt.Unchecked)

    def get_selected_presets(self) -> list[str]:
        """Get the names of selected presets."""
        selected = []
        for i in range(self.preset_list.count()):
            item = self.preset_list.item(i)
            if item.checkState() == QtCore.Qt.Checked:
                selected.append(item.data(QtCore.Qt.UserRole))
        return selected


MIN_YEARS_FOR_PROD_UPDATE: int = 12
MIN_YEARS_FOR_MANN_KENDALL: int = 4  # Minimum years required for Mann-Kendall test


class DlgTimelinePeriodGraph(QtWidgets.QDialog, DlgTimelinePeriodGraphUi):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.setMinimumSize(800, 400)
        self.graphic_view.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )

        self.extra_progress_widgets: list[TimePeriodWidgets] = []

        self.scene = QtWidgets.QGraphicsScene()
        self.graphic_view.setScene(self.scene)

        self.widgets_baseline = None
        self.widgets_progress = None
        self.progress_period_enabled = False

    def set_timeline_data(
        self, widgets_baseline, widgets_progress, extra_widgets, progress_period_enabled
    ):
        """
        Receive references to the baseline/progress TimePeriodWidgets from the
        main dialog.
        """
        self.widgets_baseline = widgets_baseline
        self.widgets_progress = widgets_progress
        self.extra_progress_widgets = extra_widgets
        self.progress_period_enabled = progress_period_enabled

        self.draw_timeline()

    def draw_timeline(self, progress_period_enabled=None):
        if progress_period_enabled is not None:
            self.progress_period_enabled = progress_period_enabled

        self.scene.clear()

        title_text = "SDG Status Calculation"
        title_item = QtWidgets.QGraphicsTextItem(title_text)
        title_font = QtGui.QFont("Arial", 18, QtGui.QFont.Bold)
        title_item.setFont(title_font)
        title_item.setDefaultTextColor(QtCore.Qt.black)
        title_item.setPos(0, 0)
        self.scene.addItem(title_item)

        years = []
        widgets = [self.widgets_baseline]

        # Reporting period years, if active
        if self.progress_period_enabled:
            widgets.append(self.widgets_progress)
            widgets.extend(self.extra_progress_widgets)

        for widget in widgets:
            baseline_years = [
                (
                    widget.year_initial_prod.date().year(),
                    widget.year_final_prod.date().year(),
                ),
                (
                    widget.year_initial_lc.date().year(),
                    widget.year_final_lc.date().year(),
                ),
                (
                    widget.year_initial_soc.date().year(),
                    widget.year_final_soc.date().year(),
                ),
            ]
            years.extend(baseline_years)

        timeline_years = set()
        for year_range in years:
            timeline_years.update(year_range)
        min_year = min(timeline_years)
        max_year = max(timeline_years)
        self.timeline_years = sorted(timeline_years)

        content_start_y = 100
        self.draw_timeline_graph(
            widgets=self.widgets_baseline,
            content_start_y=content_start_y,
            title="Baseline period",
            min_year=min_year,
            max_year=max_year,
        )

        if self.progress_period_enabled:
            for idx, w in enumerate(
                [self.widgets_progress] + self.extra_progress_widgets, start=1
            ):
                content_start_y += 125
                self.draw_timeline_graph(
                    widgets=w,
                    content_start_y=content_start_y,
                    title=f"Reporting period #{idx}",
                    min_year=min_year,
                    max_year=max_year,
                )

        self.draw_x_axis(min_year, max_year)

        bounding = self.scene.itemsBoundingRect()
        padded = bounding.adjusted(-25, -25, 25, 25)
        self.scene.setSceneRect(padded)

    def draw_x_axis(self, min_year, max_year):
        chart_width = 800
        padding = 25

        if not self.timeline_years:
            return

        chart_height = 500
        axis_pen = QtGui.QPen(QtCore.Qt.black, 2)
        axis_y = 75
        self.scene.addLine(0, axis_y, chart_width, axis_y, axis_pen)

        dotted_pen = QtGui.QPen(QtCore.Qt.black)
        dotted_pen.setStyle(QtCore.Qt.DotLine)
        dotted_pen.setWidth(1)

        scale_factor = chart_width / (max_year - min_year)

        for year in self.timeline_years:
            x_pos = (year - min_year) * scale_factor

            vertical_line = self.scene.addLine(
                x_pos, axis_y, x_pos, chart_height + padding, dotted_pen
            )
            vertical_line.setZValue(-2)

            tick_mark = self.scene.addLine(
                x_pos, axis_y - 5, x_pos, axis_y + 5, axis_pen
            )
            tick_mark.setZValue(-1)

            label = QtWidgets.QGraphicsTextItem(str(year))
            label.setPos(x_pos - 10, axis_y - 25)
            self.scene.addItem(label)

    def draw_timeline_graph(self, title, widgets, content_start_y, min_year, max_year):
        colors = [
            QtGui.QColor(78, 92, 196),
            QtGui.QColor(61, 142, 46),
            QtGui.QColor(129, 101, 5),
        ]
        labels = [
            "Productivity degradation",
            "Land cover degradation",
            "Soil organic carbon degradation",
        ]

        years = [
            (
                widgets.year_initial_prod.date().year(),
                widgets.year_final_prod.date().year(),
            ),
            (
                widgets.year_initial_lc.date().year(),
                widgets.year_final_lc.date().year(),
            ),
            (
                widgets.year_initial_soc.date().year(),
                widgets.year_final_soc.date().year(),
            ),
        ]

        title_min_year = min(year[0] for year in years)
        title_max_year = max(year[1] for year in years)

        # Constants
        chart_width = 800
        bar_height = 20
        scale_factor = chart_width / (max_year - min_year)

        y_offset = content_start_y

        # Draw the title bar
        title_bar_height = 30
        title_bar_width = (title_max_year - title_min_year) * scale_factor
        title_bar_rect = QtCore.QRectF(
            (title_min_year - min_year) * scale_factor,
            y_offset,
            title_bar_width,
            title_bar_height,
        )
        self.scene.addRect(
            title_bar_rect,
            QtGui.QPen(QtGui.QColor(118, 112, 111)),
            QtGui.QBrush(QtGui.QColor(118, 112, 111)),
        )

        title_font = QtGui.QFont("Arial", 16, QtGui.QFont.Bold)
        title_metrics = QtGui.QFontMetrics(title_font)
        title_x = (
            title_bar_rect.left()
            + (title_bar_width - title_metrics.horizontalAdvance(title)) / 2
        )
        title_y = y_offset + (title_bar_height - title_metrics.height()) / 2 - 2

        title_label = QtWidgets.QGraphicsTextItem(title)
        title_label.setDefaultTextColor(QtCore.Qt.white)
        title_label.setFont(title_font)
        title_label.setPos(title_x, title_y)
        self.scene.addItem(title_label)
        y_offset += title_bar_height

        for i, (label, color, year) in enumerate(zip(labels, colors, years)):
            bar_start_x = (year[0] - min_year) * scale_factor
            bar_width = (year[1] - year[0]) * scale_factor
            bar_rect = QtCore.QRectF(bar_start_x, y_offset, bar_width, bar_height)

            self.scene.addRect(bar_rect, QtGui.QPen(color), QtGui.QBrush(color))

            label_item = QtWidgets.QGraphicsTextItem(label)
            label_item.setDefaultTextColor(QtCore.Qt.white)
            label_item.setFont(QtGui.QFont("Arial", 10))
            label_x = bar_start_x + 10
            label_y = y_offset + (bar_height - label_item.boundingRect().height()) / 2
            label_item.setPos(label_x, label_y)
            self.scene.addItem(label_item)

            y_offset += bar_height

    def resizeEvent(self, event):
        """
        Override resizeEvent to re-fit the scene whenever the user resizes
        the dialog.
        """
        super().resizeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)


class DlgCalculateOneStep(DlgCalculateBase, DlgCalculateOneStepUi):
    def _on_common_period_changed(self, widgets, source):
        if source == "year_initial":
            self.update_start_dates(widgets)
        elif source == "year_final":
            self.update_end_dates(widgets)
        else:
            self.update_start_dates(widgets)
            self.update_end_dates(widgets)
        self.enforce_prod_date_range(widgets, source)

    def _connect_enforce_any_touch(
        self, qde: QtWidgets.QDateEdit, widgets, source: str
    ):
        timer = QtCore.QTimer(qde)
        timer.setSingleShot(True)
        timer.setInterval(300)
        le = qde.lineEdit()
        le.textEdited.connect(lambda _t: timer.start())
        timer.timeout.connect(lambda: self._on_common_period_changed(widgets, source))
        qde.dateChanged.connect(
            lambda _d: self._on_common_period_changed(widgets, source)
        )

    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        script: ExecutionScript,
        parent: QtWidgets.QWidget = None,
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)

        self.timeline_button.clicked.connect(self.on_show_timeline_clicked)
        self.timeline_dlg = None

        self.widgets_baseline = TimePeriodWidgets(
            self.radio_time_period_same_baseline,
            self.radio_lpd_te,
            self.cb_jrc_baseline,
            self.year_initial_baseline,
            self.year_final_baseline,
            self.label_baseline_prod,
            self.year_initial_baseline_prod,
            self.year_final_baseline_prod,
            self.label_baseline_lc,
            self.year_initial_baseline_lc,
            self.year_final_baseline_lc,
            self.label_baseline_soc,
            self.year_initial_baseline_soc,
            self.year_final_baseline_soc,
            self.radio_fao_wocat,
            self.radio_lpd_precalculated,
        )

        self.widgets_progress = TimePeriodWidgets(
            self.radio_time_period_same_progress,
            self.radio_lpd_te,
            self.cb_jrc_progress,
            self.year_initial_progress,
            self.year_final_progress,
            self.label_progress_prod,
            self.year_initial_progress_prod,
            self.year_final_progress_prod,
            self.label_progress_lc,
            self.year_initial_progress_lc,
            self.year_final_progress_lc,
            self.label_progress_soc,
            self.year_initial_progress_soc,
            self.year_final_progress_soc,
            self.radio_fao_wocat,
            self.radio_lpd_precalculated,
        )

        self.timeline_years = []

        baseline_date_widgets = [
            self.year_initial_baseline_prod,
            self.year_final_baseline_prod,
            self.year_initial_baseline_lc,
            self.year_final_baseline_lc,
            self.year_initial_baseline_soc,
            self.year_final_baseline_soc,
        ]
        progress_date_widgets = [
            self.year_initial_progress_prod,
            self.year_final_progress_prod,
            self.year_initial_progress_lc,
            self.year_final_progress_lc,
            self.year_initial_progress_soc,
            self.year_final_progress_soc,
        ]

        for widget in baseline_date_widgets:
            widget.dateChanged.connect(self.on_date_changed)
        for widget in progress_date_widgets:
            widget.dateChanged.connect(self.on_date_changed)

        self.cb_jrc_baseline.addItems(
            [*conf.REMOTE_DATASETS["Land Productivity Dynamics"].keys()]
        )
        self.cb_jrc_baseline.setCurrentIndex(1)
        self.cb_jrc_progress.addItems(
            [*conf.REMOTE_DATASETS["Land Productivity Dynamics"].keys()]
        )
        self.cb_jrc_progress.setCurrentIndex(2)

        self.toggle_lpd_options()

        self.cb_jrc_baseline.currentIndexChanged.connect(
            lambda: self.update_time_bounds(self.widgets_baseline)
        )
        self.cb_jrc_progress.currentIndexChanged.connect(
            lambda: self.update_time_bounds(self.widgets_progress)
        )
        self.radio_time_period_same_baseline.toggled.connect(
            lambda: self.toggle_time_period(self.widgets_baseline)
        )
        self.radio_time_period_same_progress.toggled.connect(
            lambda: self.toggle_time_period(self.widgets_progress)
        )

        self.lc_setup_widget = lc_setup.LandCoverSetupRemoteExecutionWidget(
            self, hide_min_year=True, hide_max_year=True
        )

        self._connect_enforce_any_touch(
            self.year_initial_baseline, self.widgets_baseline, "year_initial"
        )
        self._connect_enforce_any_touch(
            self.year_final_baseline, self.widgets_baseline, "year_final"
        )

        self.year_initial_baseline_prod.dateChanged.connect(
            lambda: self.enforce_prod_date_range(self.widgets_baseline)
        )
        self.year_final_baseline_prod.dateChanged.connect(
            lambda: self.enforce_prod_date_range(self.widgets_baseline)
        )
        self._connect_enforce_any_touch(
            self.year_initial_progress, self.widgets_progress, "year_initial"
        )
        self._connect_enforce_any_touch(
            self.year_final_progress, self.widgets_progress, "year_final"
        )
        self.year_initial_progress_prod.dateChanged.connect(
            lambda: self.enforce_prod_date_range(self.widgets_progress)
        )
        self.year_final_progress_prod.dateChanged.connect(
            lambda: self.enforce_prod_date_range(self.widgets_progress)
        )

        self.enforce_prod_date_range(self.widgets_baseline)
        self.enforce_prod_date_range(self.widgets_progress)

        self.radio_lpd_te.toggled.connect(self.toggle_lpd_options)
        self.radio_lpd_precalculated.toggled.connect(self.toggle_lpd_options)
        self.radio_fao_wocat.toggled.connect(self.toggle_lpd_options)

        self.lc_define_deg_widget = lc_setup.LCDefineDegradationWidget()

        self.checkBox_progress_period.toggled.connect(self.toggle_progress_period)
        self.toggle_progress_period()

        # Initialize preset system
        self.preset_manager = LDNPresetManager()
        self._setup_preset_ui()

        self.add_period_button.clicked.connect(self.on_add_period_clicked)

        self.extra_progress_boxes: list[
            tuple[QtWidgets.QGroupBox, TimePeriodWidgets]
        ] = []

        self._finish_initialization()

    def update_timeline_graph(self):
        if self.timeline_dlg:
            self.timeline_dlg.extra_progress_widgets = [
                w for _, w in self.extra_progress_boxes
            ]
            self.timeline_dlg.draw_timeline(
                progress_period_enabled=self.checkBox_progress_period.isChecked()
            )

    def on_date_changed(self, date):
        self.update_timeline_graph()

    def on_show_timeline_clicked(self):
        """
        Only show the timeline dialog once. If it's already open, do nothing;
        otherwise create and show it.
        """
        if self.timeline_dlg is not None and self.timeline_dlg.isVisible():
            self.timeline_dlg.raise_()
            self.timeline_dlg.activateWindow()
            return

        self.timeline_dlg = DlgTimelinePeriodGraph(parent=self)
        self.timeline_dlg.set_timeline_data(
            widgets_baseline=self.widgets_baseline,
            widgets_progress=self.widgets_progress,
            extra_widgets=[w for _, w in self.extra_progress_boxes],
            progress_period_enabled=self.checkBox_progress_period.isChecked(),
        )

        parent_pos = self.mapToGlobal(QtCore.QPoint(0, 0))
        self.timeline_dlg.move(parent_pos.x() + 700, parent_pos.y() + 50)

        flags = self.timeline_dlg.windowFlags()
        self.timeline_dlg.setWindowFlags(flags | QtCore.Qt.WindowStaysOnTopHint)

        self.timeline_dlg.destroyed.connect(self.on_timeline_destroyed)
        self.timeline_dlg.show()

    def on_timeline_destroyed(self, *args):
        self.timeline_dlg = None

    def _ask_reset_legend(self):
        resp = QtWidgets.QMessageBox.question(
            None,
            self.tr("Also reset land cover legend?"),
            self.tr(
                "The UNCCD default data uses a 7 class land cover legend. Do you "
                "also want to reset the land cover legend to the UNCCD default? "
                "This will mean any changes you may have made to the land "
                "cover legend will be lost."
            ),
            QtWidgets.QMessageBox.Yes,
            QtWidgets.QMessageBox.No,
        )
        if resp == QtWidgets.QMessageBox.Yes:
            return True
        else:
            return False

    def _setup_preset_ui(self):
        """Initialize the preset UI components."""
        # Populate the combobox with presets
        self.comboBox_presets.clear()
        presets = self.preset_manager.get_all_presets()
        for i, preset in enumerate(presets):
            display_name = f"{preset.name}"
            if preset.is_built_in:
                display_name += " (Built-in)"
            self.comboBox_presets.addItem(display_name, preset.name)
            # Set tooltip with description if available
            if preset.description:
                self.comboBox_presets.setItemData(
                    i, preset.description, QtCore.Qt.ToolTipRole
                )

        # Connect preset UI signals
        self.comboBox_presets.currentTextChanged.connect(
            self._on_preset_selection_changed
        )
        self.button_apply_preset.clicked.connect(self.on_apply_preset)
        self.button_save_preset.clicked.connect(self.on_save_preset)
        self.button_delete_preset.clicked.connect(self.on_delete_preset)
        self.button_export_presets.clicked.connect(self.on_export_presets)
        self.button_import_presets.clicked.connect(self.on_import_presets)

        # Update UI state
        self._update_preset_ui_state()

    def _update_preset_ui_state(self):
        """Update the enabled state of preset buttons."""
        has_selection = self.comboBox_presets.currentIndex() >= 0
        current_preset_name = (
            self.comboBox_presets.currentData() if has_selection else None
        )
        current_preset = (
            self.preset_manager.get_preset_by_name(current_preset_name)
            if current_preset_name
            else None
        )

        self.button_apply_preset.setEnabled(has_selection)
        self.button_delete_preset.setEnabled(
            has_selection and current_preset and not current_preset.is_built_in
        )

        # Update the description tooltip
        self._update_preset_description()

    def _on_preset_selection_changed(self):
        """Handle preset selection changes."""
        self._update_preset_description()
        self._update_preset_ui_state()

    def _update_preset_description(self):
        """Update the combobox tooltip with the current preset's description."""
        preset_name = self.comboBox_presets.currentData()
        if preset_name:
            preset = self.preset_manager.get_preset_by_name(preset_name)
            if preset and preset.description:
                self.comboBox_presets.setToolTip(preset.description)
            else:
                self.comboBox_presets.setToolTip("")
        else:
            self.comboBox_presets.setToolTip("")

    def on_apply_preset(self):
        """Apply the selected preset."""
        preset_name = self.comboBox_presets.currentData()
        if not preset_name:
            return

        preset = self.preset_manager.get_preset_by_name(preset_name)
        if not preset:
            QtWidgets.QMessageBox.warning(
                self, "Error", f"Preset '{preset_name}' not found."
            )
            return

        self.apply_preset(preset)

    def apply_preset(self, preset: LDNPreset):
        """Apply a preset to the dialog controls."""
        # Set reporting periods enabled state
        self.checkBox_progress_period.setChecked(preset.progress_periods_enabled)

        # Set productivity mode
        if preset.productivity_mode == ProductivityMode.JRC_5_CLASS_LPD.value:
            self.radio_lpd_precalculated.setChecked(True)
            # Get JRC dataset from baseline period if it's a JRCPeriod
            if preset.baseline_period and isinstance(preset.baseline_period, JRCPeriod):
                if preset.baseline_period.jrc_dataset:
                    idx = self.cb_jrc_baseline.findText(
                        preset.baseline_period.jrc_dataset
                    )
                    if idx >= 0:
                        self.cb_jrc_baseline.setCurrentIndex(idx)
            # Get JRC dataset from first reporting period if it's a JRCPeriod
            if preset.progress_periods and isinstance(
                preset.progress_periods[0], JRCPeriod
            ):
                if preset.progress_periods[0].jrc_dataset:
                    idx = self.cb_jrc_progress.findText(
                        preset.progress_periods[0].jrc_dataset
                    )
                    if idx >= 0:
                        self.cb_jrc_progress.setCurrentIndex(idx)
        elif preset.productivity_mode == ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value:
            self.radio_fao_wocat.setChecked(True)
        else:  # ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value
            self.radio_lpd_te.setChecked(True)

        # Apply baseline period
        if preset.baseline_period:
            self._apply_period_to_widgets(
                preset.baseline_period, self.widgets_baseline, is_baseline=True
            )

        # Clear existing extra periods
        self._clear_extra_periods()

        # Apply reporting periods
        for i, period in enumerate(preset.progress_periods or []):
            if i == 0:
                # Apply first reporting period to the main progress widgets
                self._apply_period_to_widgets(
                    period, self.widgets_progress, is_baseline=False
                )
            else:
                # Add extra periods for subsequent ones
                self._add_extra_period_from_preset(period)

        # Reset legend if requested
        if preset.reset_legend and self._ask_reset_legend():
            lc_setup.LccInfoUtils.set_default_unccd_classes(force_update=True)
            self.lc_setup_widget.aggregation_dialog.reset_nesting_table(
                get_default=True
            )
            self.lc_define_deg_widget.set_trans_matrix(get_default=True)

        self.update_timeline_graph()

    def _apply_period_to_widgets(
        self, period: LDNPresetPeriod, widgets: TimePeriodWidgets, is_baseline: bool
    ):
        """Apply a period configuration to widget controls."""
        # Set the time period radio button state
        # For radio buttons in a group, setting one to checked automatically unchecks the others
        if period.time_period_same:
            widgets.radio_time_period_same.setChecked(True)
        else:
            # Find the "vary" radio button in the same parent widget group
            parent_widget = widgets.radio_time_period_same.parent()
            if parent_widget:
                # Look for any other radio button in the same parent that isn't the "same" button
                radio_buttons = parent_widget.findChildren(QtWidgets.QRadioButton)
                for radio_btn in radio_buttons:
                    if radio_btn != widgets.radio_time_period_same:
                        # This should be the "vary" button - check it
                        radio_btn.setChecked(True)
                        break
                else:
                    # Fallback: just uncheck the "same" button
                    widgets.radio_time_period_same.setChecked(False)

        widgets.year_initial.setDate(QtCore.QDate(period.year_initial, 1, 1))
        widgets.year_final.setDate(QtCore.QDate(period.year_final, 1, 1))

        # Only set productivity dates if the period type supports them
        year_initial_prod = getattr(period, "year_initial_prod", period.year_initial)
        year_final_prod = getattr(period, "year_final_prod", period.year_final)
        widgets.year_initial_prod.setDate(QtCore.QDate(year_initial_prod, 1, 1))
        widgets.year_final_prod.setDate(QtCore.QDate(year_final_prod, 1, 1))

        widgets.year_initial_lc.setDate(QtCore.QDate(period.year_initial_lc, 1, 1))
        widgets.year_final_lc.setDate(QtCore.QDate(period.year_final_lc, 1, 1))
        widgets.year_initial_soc.setDate(QtCore.QDate(period.year_initial_soc, 1, 1))
        widgets.year_final_soc.setDate(QtCore.QDate(period.year_final_soc, 1, 1))

    def _clear_extra_periods(self):
        """Remove all extra reporting period widgets."""
        for group_box, _ in self.extra_progress_boxes:
            group_box.setParent(None)
        self.extra_progress_boxes.clear()

    def _add_extra_period_from_preset(self, period: LDNPresetPeriod):
        """Add an extra reporting period from a preset."""
        # Create the extra reporting period UI components
        grp, widgets = self._create_progress_period()
        grp.setTitle(f"Reporting period #{len(self.extra_progress_boxes) + 2}")

        # Apply the period data to the widgets
        self._apply_period_to_widgets(period, widgets, is_baseline=False)

        # Set the JRC dataset if this is a JRCPeriod
        if isinstance(period, JRCPeriod) and period.jrc_dataset:
            idx = widgets.cb_lpd.findText(period.jrc_dataset)
            if idx >= 0:
                widgets.cb_lpd.setCurrentIndex(idx)

        # Add to the UI layout
        wrapper = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(wrapper)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.addWidget(grp)

        container_layout: QtWidgets.QVBoxLayout = self.verticalLayout_7
        idx = container_layout.indexOf(
            self.findChild(QtWidgets.QHBoxLayout, "verticalLayout_9")
        )
        container_layout.insertWidget(idx, wrapper)

        self.extra_progress_boxes.append((grp, widgets))

        # Update UI state based on current productivity mode
        is_precalc = self.radio_lpd_precalculated.isChecked()
        widgets.cb_lpd.setVisible(is_precalc)
        lbl = grp.findChild(QtWidgets.QLabel, "label_jrc_progress")
        if lbl is not None:
            lbl.setVisible(is_precalc)

    def on_save_preset(self):
        """Save current configuration as a new preset."""
        dialog = PresetSaveDialog(self)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            name = dialog.get_name()
            description = dialog.get_description()

            if self.preset_manager.get_preset_by_name(name):
                reply = QtWidgets.QMessageBox.question(
                    self,
                    "Preset Exists",
                    f"A preset named '{name}' already exists. Overwrite it?",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                )
                if reply != QtWidgets.QMessageBox.Yes:
                    return

            preset = self._create_preset_from_current_settings(name, description)

            existing = self.preset_manager.get_preset_by_name(name)
            if existing and not existing.is_built_in:
                self.preset_manager.update_user_preset(name, preset)
            else:
                self.preset_manager.add_user_preset(preset)

            self._refresh_preset_list()
            self._select_preset_by_name(name)

    def _create_preset_from_current_settings(
        self, name: str, description: str
    ) -> LDNPreset:
        """Create a preset from current dialog settings."""
        # Determine productivity mode
        if self.radio_lpd_precalculated.isChecked():
            productivity_mode = ProductivityMode.JRC_5_CLASS_LPD.value
        elif self.radio_fao_wocat.isChecked():
            productivity_mode = ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value
        else:
            productivity_mode = ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value

        # Create a temporary preset to use its _create_period_for_mode method
        temp_preset = LDNPreset(
            name="temp",
            productivity_mode=productivity_mode,
        )

        # Get baseline period
        baseline_period = self._extract_period_from_widgets(
            self.widgets_baseline, temp_preset, is_baseline=True
        )

        # Get reporting periods - now unified!
        progress_periods = []
        if self.checkBox_progress_period.isChecked():
            # Add the main reporting period
            progress_periods.append(
                self._extract_period_from_widgets(
                    self.widgets_progress, temp_preset, is_baseline=False
                )
            )
            # Add any extra periods
            for _, widgets in self.extra_progress_boxes:
                progress_periods.append(
                    self._extract_period_from_widgets(
                        widgets, temp_preset, is_baseline=False
                    )
                )

        return LDNPreset(
            name=name,
            description=description,
            progress_periods_enabled=self.checkBox_progress_period.isChecked(),
            productivity_mode=productivity_mode,
            baseline_period=baseline_period,
            progress_periods=progress_periods,
            reset_legend=True,
            is_built_in=False,
        )

    def _extract_period_from_widgets(
        self, widgets: TimePeriodWidgets, preset: LDNPreset, is_baseline: bool = False
    ) -> LDNPresetPeriod:
        """Extract period configuration from widgets using appropriate period type."""
        period_args = {
            "year_initial": widgets.year_initial.date().year(),
            "year_final": widgets.year_final.date().year(),
            "year_initial_lc": widgets.year_initial_lc.date().year(),
            "year_final_lc": widgets.year_final_lc.date().year(),
            "year_initial_soc": widgets.year_initial_soc.date().year(),
            "year_final_soc": widgets.year_final_soc.date().year(),
            "time_period_same": widgets.radio_time_period_same.isChecked(),
        }

        # Add mode-specific fields
        if preset.productivity_mode == ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value:
            # TrendsEarthPeriod uses standard productivity date fields (derived values calculated at runtime)
            period_args.update(
                {
                    "year_initial_prod": widgets.year_initial_prod.date().year(),
                    "year_final_prod": widgets.year_final_prod.date().year(),
                }
            )
        elif preset.productivity_mode in [
            ProductivityMode.JRC_5_CLASS_LPD.value,
            ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value,
        ]:
            # JRC and FAO-WOCAT periods use standard productivity dates
            period_args.update(
                {
                    "year_initial_prod": widgets.year_initial_prod.date().year(),
                    "year_final_prod": widgets.year_final_prod.date().year(),
                }
            )

        # Add JRC dataset for JRC periods
        if preset.productivity_mode == ProductivityMode.JRC_5_CLASS_LPD.value:
            # Use appropriate dataset based on whether this is baseline or reporting period
            if is_baseline:
                jrc_dataset = self.cb_jrc_baseline.currentText()
            else:
                # For reporting periods, check if this widget has its own JRC combobox (extra periods)
                # or use the main progress combobox (main reporting period)
                if hasattr(widgets, "cb_lpd") and widgets.cb_lpd:
                    jrc_dataset = widgets.cb_lpd.currentText()
                else:
                    jrc_dataset = self.cb_jrc_progress.currentText()
            period_args.update(
                {
                    "jrc_dataset": jrc_dataset,
                }
            )

        return preset._create_period_for_mode(**period_args)

    def _calculate_trends_earth_productivity_params(
        self, year_initial_prod: int, year_final_prod: int
    ) -> dict:
        """Calculate TrendsEarth-specific productivity parameters from basic productivity dates.

        Args:
            year_initial_prod: Initial productivity year
            year_final_prod: Final productivity year

        Returns:
            Dictionary with TrendsEarth productivity parameters
        """
        # Default method
        traj_method = "ndvi_trend"

        # For trajectory analysis, use the provided productivity period
        traj_year_initial = year_initial_prod
        traj_year_final = year_final_prod

        # For state analysis, use the original TrendsEarth logic:
        # Have productivity state consider the last 3 years for the current
        # period, and the years preceding those last 3 for the baseline
        state_year_bl_start = year_initial_prod
        state_year_bl_end = year_final_prod - 3
        state_year_tg_start = state_year_bl_end + 1
        state_year_tg_end = year_final_prod  # This should equal year_final

        # For performance analysis, use the same years as trajectory/productivity
        perf_year_initial = year_initial_prod
        perf_year_final = year_final_prod

        return {
            "traj_method": traj_method,
            "traj_year_initial": traj_year_initial,
            "traj_year_final": traj_year_final,
            "state_year_bl_start": state_year_bl_start,
            "state_year_bl_end": state_year_bl_end,
            "state_year_tg_start": state_year_tg_start,
            "state_year_tg_end": state_year_tg_end,
            "perf_year_initial": perf_year_initial,
            "perf_year_final": perf_year_final,
        }

    def on_delete_preset(self):
        """Delete the selected user preset."""
        preset_name = self.comboBox_presets.currentData()
        if not preset_name:
            return

        preset = self.preset_manager.get_preset_by_name(preset_name)
        if not preset or preset.is_built_in:
            QtWidgets.QMessageBox.warning(
                self, "Error", "Cannot delete built-in presets."
            )
            return

        reply = QtWidgets.QMessageBox.question(
            self,
            "Delete Preset",
            f"Are you sure you want to delete the preset '{preset_name}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )

        if reply == QtWidgets.QMessageBox.Yes:
            self.preset_manager.delete_user_preset(preset_name)
            self._refresh_preset_list()

    def on_export_presets(self):
        """Export presets to JSON file."""
        dialog = PresetExportDialog(self.preset_manager.get_all_presets(), self)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            selected_presets = dialog.get_selected_presets()
            file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Export Presets", "ldn_presets.json", "JSON Files (*.json)"
            )

            if file_path:
                try:
                    self.preset_manager.export_presets(file_path, selected_presets)
                    QtWidgets.QMessageBox.information(
                        self, "Export Successful", f"Presets exported to {file_path}"
                    )
                except Exception as e:
                    QtWidgets.QMessageBox.critical(
                        self, "Export Failed", f"Failed to export presets: {e}"
                    )

    def on_import_presets(self):
        """Import presets from JSON file."""
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Import Presets", "", "JSON Files (*.json)"
        )

        if file_path:
            try:
                count, errors = self.preset_manager.import_presets(file_path)
                message = f"Successfully imported {count} presets."
                if errors:
                    message += "\n\nErrors:\n" + "\n".join(errors)

                QtWidgets.QMessageBox.information(self, "Import Results", message)
                self._refresh_preset_list()
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self, "Import Failed", f"Failed to import presets: {e}"
                )

    def _refresh_preset_list(self):
        """Refresh the preset combobox."""
        current_selection = self.comboBox_presets.currentData()
        self.comboBox_presets.clear()

        presets = self.preset_manager.get_all_presets()
        for i, preset in enumerate(presets):
            display_name = f"{preset.name}"
            if preset.is_built_in:
                display_name += " (Built-in)"
            self.comboBox_presets.addItem(display_name, preset.name)
            # Set tooltip with description if available
            if preset.description:
                self.comboBox_presets.setItemData(
                    i, preset.description, QtCore.Qt.ToolTipRole
                )

        # Restore selection if possible
        if current_selection:
            self._select_preset_by_name(current_selection)

        self._update_preset_ui_state()

    def _select_preset_by_name(self, name: str):
        """Select a preset by name in the combobox."""
        for i in range(self.comboBox_presets.count()):
            if self.comboBox_presets.itemData(i) == name:
                self.comboBox_presets.setCurrentIndex(i)
                break

    def _update_common_dates(self, widgets):
        if widgets.radio_time_period_same.isChecked():
            # Same period mode: use common dates for all indicators
            year_initial = widgets.year_initial.date()
            year_final = widgets.year_final.date()

            lc_start, lc_end = year_initial, year_final

            widgets.year_initial_lc.setDate(lc_start)
            widgets.year_initial_soc.setDate(lc_start)
            widgets.year_final_lc.setDate(lc_end)
            widgets.year_final_soc.setDate(lc_end)

            if not self.radio_lpd_precalculated.isChecked():
                if not widgets.radio_fao_wocat.isChecked():
                    widgets.year_initial_prod.setDate(year_initial)

                widgets.year_final_prod.setDate(year_final)
        else:
            # Vary by indicator mode: don't override individual indicator dates
            # Only apply LC/SOC overrides if they exist
            lc_soc_override = (
                getattr(widgets, "_lc_soc_override", None)
                if self.radio_lpd_precalculated.isChecked()
                else None
            )
            if lc_soc_override:
                lc_start, lc_end = lc_soc_override
                widgets.year_initial_lc.setDate(lc_start)
                widgets.year_initial_soc.setDate(lc_start)
                widgets.year_final_lc.setDate(lc_end)
                widgets.year_final_soc.setDate(lc_end)

        self.update_timeline_graph()

    def update_start_dates(self, widgets):
        self._update_common_dates(widgets)

    def update_end_dates(self, widgets):
        self._update_common_dates(widgets)

    def toggle_time_period(self, widgets):
        # First, update the time bounds based on the new radio button state
        self.update_time_bounds(widgets)

        # Check if we're in JRC mode - if so, productivity widgets should remain disabled
        is_precalc = self.radio_lpd_precalculated.isChecked()

        if widgets.radio_time_period_same.isChecked():
            widgets.label_lc.setEnabled(False)
            widgets.year_initial_lc.setEnabled(False)
            widgets.year_final_lc.setEnabled(False)

            widgets.label_soc.setEnabled(False)
            widgets.year_initial_soc.setEnabled(False)
            widgets.year_final_soc.setEnabled(False)

            widgets.year_initial.setEnabled(True)
            widgets.year_final.setEnabled(True)

            widgets.label_prod.setEnabled(False)
            # Only disable productivity widgets if not in JRC mode (they're already disabled in JRC mode)
            if not is_precalc:
                widgets.year_initial_prod.setEnabled(False)
                widgets.year_final_prod.setEnabled(False)

            widgets.year_initial.setEnabled(True)

            self.update_start_dates(widgets)
            self.update_end_dates(widgets)
        else:
            widgets.label_lc.setEnabled(True)
            widgets.year_initial_lc.setEnabled(True)
            widgets.year_final_lc.setEnabled(True)

            widgets.label_soc.setEnabled(True)
            widgets.year_initial_soc.setEnabled(True)
            widgets.year_final_soc.setEnabled(True)

            widgets.year_initial.setEnabled(False)
            widgets.year_final.setEnabled(False)

            # Only enable productivity widgets if not in JRC mode
            if not is_precalc:
                widgets.year_initial_prod.setEnabled(True)
                widgets.year_final_prod.setEnabled(True)

            if widgets.radio_lpd_te.isChecked() and not is_precalc:
                widgets.label_prod.setEnabled(True)
                widgets.year_initial_prod.setEnabled(True)

    def toggle_lpd_options(self):
        """
        Adjust visibility of Land Productivity Dynamics (LPD) widgets
        according to the chosen LPD mode.
        """
        is_precalc = self.radio_lpd_precalculated.isChecked()

        # Main widgets (baseline & first reporting period)
        # JRC/FAO-WOCAT combo boxes
        if is_precalc:
            self.cb_jrc_baseline.show()
            self.label_jrc_baseline.show()
            self.cb_jrc_progress.show()
            self.label_jrc_progress.show()
        else:
            self.cb_jrc_baseline.hide()
            self.label_jrc_baseline.hide()
            self.cb_jrc_progress.hide()
            self.label_jrc_progress.hide()

        # Make productivity date controls disabled when JRC mode is selected
        # (users can still configure LC and SOC periods, but productivity is fixed by dataset)
        productivity_widgets = [
            # Baseline productivity widgets
            self.widgets_baseline.year_initial_prod,
            self.widgets_baseline.year_final_prod,
            # Progress productivity widgets
            self.widgets_progress.year_initial_prod,
            self.widgets_progress.year_final_prod,
        ]

        for widget in productivity_widgets:
            if widget:
                widget.setEnabled(
                    not is_precalc
                )  # Disable in JRC mode, enable otherwise

        # Extra progress‑period widgets
        for _box, w in getattr(self, "extra_progress_boxes", []):
            w.cb_lpd.setVisible(is_precalc)

            lbl = _box.findChild(QtWidgets.QLabel, "label_jrc_progress")
            if lbl is not None:
                lbl.setVisible(is_precalc)

            # Disable productivity date controls in extra reporting periods too
            if w.year_initial_prod:
                w.year_initial_prod.setEnabled(not is_precalc)
            if w.year_final_prod:
                w.year_final_prod.setEnabled(not is_precalc)

        # Refresh dependent controls
        self.update_time_bounds(self.widgets_baseline)
        self.update_time_bounds(self.widgets_progress)
        for _box, w in getattr(self, "extra_progress_boxes", []):
            self.update_time_bounds(w)

        self.toggle_time_period(self.widgets_baseline)
        self.toggle_time_period(self.widgets_progress)
        for _box, w in getattr(self, "extra_progress_boxes", []):
            self.toggle_time_period(w)

    def update_time_bounds(self, widgets):
        lc_dataset = conf.REMOTE_DATASETS["Land cover"]["ESA CCI"]
        start_year_lc = lc_dataset["Start year"]
        end_year_lc = lc_dataset["End year"]
        start_year_lc = QtCore.QDate(start_year_lc, 1, 1)
        end_year_lc = QtCore.QDate(end_year_lc, 1, 1)

        prod_dataset = conf.REMOTE_DATASETS["NDVI"]["MODIS (MOD13Q1, annual)"]
        start_year_prod = prod_dataset["Start year"]
        end_year_prod = prod_dataset["End year"]

        start_year_prod = QtCore.QDate(start_year_prod, 1, 1)
        end_year_prod = QtCore.QDate(end_year_prod, 1, 1)

        if self.radio_lpd_precalculated.isChecked():
            if not widgets.cb_lpd.currentText():
                widgets.cb_lpd.setCurrentIndex(0)

            prod_dataset = conf.REMOTE_DATASETS["Land Productivity Dynamics"][
                widgets.cb_lpd.currentText()
            ]
            start_year_prod = prod_dataset["Start year"]
            end_year_prod = prod_dataset["End year"]
            start_year_prod = QtCore.QDate(start_year_prod, 1, 1)
            end_year_prod = QtCore.QDate(end_year_prod, 1, 1)

        # Apply special LC/SOC windows for specific JRC datasets
        if self.radio_lpd_precalculated.isChecked():
            label = widgets.cb_lpd.currentText() if hasattr(widgets, "cb_lpd") else ""
            jrc_overrides = {
                "JRC Land Productivity Dynamics (2004-2019)": (
                    QtCore.QDate(2015, 1, 1),
                    QtCore.QDate(2019, 1, 1),
                ),
                "JRC Land Productivity Dynamics (2008-2023)": (
                    QtCore.QDate(2015, 1, 1),
                    QtCore.QDate(2023, 1, 1),
                ),
            }
            override = jrc_overrides.get(label)
            if override:
                widgets._lc_soc_override = override
            else:
                if hasattr(widgets, "_lc_soc_override"):
                    delattr(widgets, "_lc_soc_override")

        # Check radio button state to determine how to calculate bounds
        if widgets.radio_time_period_same.isChecked():
            # Same period mode: use unified bounds across all datasets
            start_year = max(start_year_prod, start_year_lc)
            end_year = min(end_year_prod, end_year_lc)

            # Set unified bounds for all widgets
            widgets.year_initial.setMinimumDate(start_year)
            widgets.year_initial.setMaximumDate(end_year)
            widgets.year_final.setMinimumDate(start_year)
            widgets.year_final.setMaximumDate(end_year)

            widgets.year_initial_prod.setMinimumDate(start_year)
            widgets.year_initial_prod.setMaximumDate(end_year)
            widgets.year_final_prod.setMinimumDate(start_year)
            widgets.year_final_prod.setMaximumDate(end_year)

            widgets.year_initial_lc.setMinimumDate(start_year)
            widgets.year_initial_lc.setMaximumDate(end_year)
            widgets.year_final_lc.setMinimumDate(start_year)
            widgets.year_final_lc.setMaximumDate(end_year)

            widgets.year_initial_soc.setMinimumDate(start_year)
            widgets.year_initial_soc.setMaximumDate(end_year)
            widgets.year_final_soc.setMinimumDate(start_year)
            widgets.year_final_soc.setMaximumDate(end_year)
        else:
            # Vary by indicator mode: calculate independent bounds for each dataset type

            # Productivity bounds (for both year_initial/year_final and year_initial_prod/year_final_prod)
            widgets.year_initial.setMinimumDate(start_year_prod)
            widgets.year_initial.setMaximumDate(end_year_prod)
            widgets.year_final.setMinimumDate(start_year_prod)
            widgets.year_final.setMaximumDate(end_year_prod)

            widgets.year_initial_prod.setMinimumDate(start_year_prod)
            widgets.year_initial_prod.setMaximumDate(end_year_prod)
            widgets.year_final_prod.setMinimumDate(start_year_prod)
            widgets.year_final_prod.setMaximumDate(end_year_prod)

            # LC/SOC bounds (independent calculation)
            widgets.year_initial_lc.setMinimumDate(start_year_lc)
            widgets.year_initial_lc.setMaximumDate(end_year_lc)
            widgets.year_final_lc.setMinimumDate(start_year_lc)
            widgets.year_final_lc.setMaximumDate(end_year_lc)

            widgets.year_initial_soc.setMinimumDate(start_year_lc)
            widgets.year_initial_soc.setMaximumDate(end_year_lc)
            widgets.year_final_soc.setMinimumDate(start_year_lc)
            widgets.year_final_soc.setMaximumDate(end_year_lc)

        # Set default dates for productivity (always use productivity dataset dates)
        widgets.year_initial_prod.setDate(start_year_prod)
        widgets.year_final_prod.setDate(end_year_prod)

        # If an override exists, set LC/SOC default dates to it now (for both same/vary modes)
        if hasattr(widgets, "_lc_soc_override") and widgets._lc_soc_override:
            lc_start, lc_end = widgets._lc_soc_override
            widgets.year_initial_lc.setDate(lc_start)
            widgets.year_final_lc.setDate(lc_end)
            widgets.year_initial_soc.setDate(lc_start)
            widgets.year_final_soc.setDate(lc_end)

        widgets.year_initial.setDate(start_year_prod)
        widgets.year_final.setDate(end_year_prod)

        self.update_start_dates(widgets)
        self.update_end_dates(widgets)

    def showEvent(self, event):
        super().showEvent(event)

        if self.land_cover_content.layout() is None:
            layout = QtWidgets.QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(1)
            layout.addWidget(self.lc_setup_widget)
            self.land_cover_content.setLayout(layout)

        if self.effects_content.layout() is None:
            layout = QtWidgets.QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(1)
            layout.addWidget(self.lc_define_deg_widget)
            self.effects_content.setLayout(layout)

    def toggle_progress_period(self):
        if self.checkBox_progress_period.isChecked():
            self.groupBox_progress_period.setVisible(True)
            self.add_period_button.setVisible(True)
        else:
            self.groupBox_progress_period.setVisible(False)
            self.add_period_button.setVisible(False)

        self.update_timeline_graph()

    def _create_progress_period(self) -> tuple[QtWidgets.QGroupBox, TimePeriodWidgets]:
        """
        Build an independent copy of the original groupBox_progress_period
        and return both the box itself and a freshly‑wired TimePeriodWidgets
        structure that points to the new widgets.
        """
        grp = QtWidgets.QGroupBox(parent=self)
        uic.loadUi(str(Path(__file__).parent / "gui/fragment_progress_period.ui"), grp)

        cb_lpd: QtWidgets.QComboBox = grp.findChild(
            QtWidgets.QComboBox, "cb_jrc_progress"
        )

        cb_lpd.addItems([*conf.REMOTE_DATASETS["Land Productivity Dynamics"].keys()])
        cb_lpd.setCurrentIndex(0)

        cb_lpd.currentIndexChanged.connect(
            lambda _ix, wref=weakref.ref(self): wref() and wref().update_time_bounds(w)
        )

        w = TimePeriodWidgets(
            grp.findChild(QtWidgets.QRadioButton, "radio_time_period_same_progress"),
            self.radio_lpd_te,
            grp.findChild(QtWidgets.QComboBox, "cb_jrc_progress"),
            grp.findChild(QtWidgets.QDateEdit, "year_initial_progress"),
            grp.findChild(QtWidgets.QDateEdit, "year_final_progress"),
            grp.findChild(QtWidgets.QLabel, "label_progress_prod"),
            grp.findChild(QtWidgets.QDateEdit, "year_initial_progress_prod"),
            grp.findChild(QtWidgets.QDateEdit, "year_final_progress_prod"),
            grp.findChild(QtWidgets.QLabel, "label_progress_lc"),
            grp.findChild(QtWidgets.QDateEdit, "year_initial_progress_lc"),
            grp.findChild(QtWidgets.QDateEdit, "year_final_progress_lc"),
            grp.findChild(QtWidgets.QLabel, "label_progress_soc"),
            grp.findChild(QtWidgets.QDateEdit, "year_initial_progress_soc"),
            grp.findChild(QtWidgets.QDateEdit, "year_final_progress_soc"),
            self.radio_fao_wocat,
            self.radio_lpd_precalculated,
        )

        for de in (
            w.year_initial,
            w.year_final,
            w.year_initial_prod,
            w.year_final_prod,
            w.year_initial_lc,
            w.year_final_lc,
            w.year_initial_soc,
            w.year_final_soc,
        ):
            de.dateChanged.connect(self.on_date_changed)

        self.update_time_bounds(w)
        self.toggle_time_period(w)

        is_precalc_now = self.radio_lpd_precalculated.isChecked()
        w.cb_lpd.setVisible(is_precalc_now)
        lbl_now = grp.findChild(QtWidgets.QLabel, "label_jrc_progress")
        if lbl_now is not None:
            lbl_now.setVisible(is_precalc_now)

        if w.year_initial_prod:
            w.year_initial_prod.setEnabled(not is_precalc_now)
        if w.year_final_prod:
            w.year_final_prod.setEnabled(not is_precalc_now)

        same_btn = w.radio_time_period_same
        vary_btn = grp.findChild(
            QtWidgets.QRadioButton, "radio_time_period_vary_progress"
        )

        same_btn.toggled.connect(
            lambda _checked, w_local=w: self.toggle_time_period(w_local)
        )
        vary_btn.toggled.connect(
            lambda _checked, w_local=w: self.toggle_time_period(w_local)
        )

        w.year_initial.dateChanged.connect(lambda _d, ww=w: self.update_start_dates(ww))
        w.year_final.dateChanged.connect(lambda _d, ww=w: self.update_end_dates(ww))

        self._connect_enforce_any_touch(w.year_initial, w, "year_initial")
        self._connect_enforce_any_touch(w.year_final, w, "year_final")

        return grp, w

    @QtCore.pyqtSlot()
    def on_add_period_clicked(self):
        grp, widgets = self._create_progress_period()
        grp.setTitle(f"Reporting period #{len(self.extra_progress_boxes) + 2}")

        wrapper = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(wrapper)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.addWidget(grp)

        container_layout: QtWidgets.QVBoxLayout = self.verticalLayout_7
        idx = container_layout.indexOf(
            self.findChild(QtWidgets.QHBoxLayout, "verticalLayout_9")
        )
        container_layout.insertWidget(idx, wrapper)

        self.extra_progress_boxes.append((grp, widgets))

        self.update_timeline_graph()

        is_precalc = self.radio_lpd_precalculated.isChecked()

        widgets.cb_lpd.setVisible(is_precalc)
        lbl = grp.findChild(QtWidgets.QLabel, "label_jrc_progress")
        if lbl is not None:
            lbl.setVisible(is_precalc)

        if widgets.year_initial_prod:
            widgets.year_initial_prod.setEnabled(not is_precalc)
        if widgets.year_final_prod:
            widgets.year_final_prod.setEnabled(not is_precalc)

        self.toggle_lpd_options()

        self.enforce_prod_date_range(widgets)

    def _get_period_years(self, widgets):
        return {
            "period_year_initial": widgets.year_initial_prod.date().year(),
            "period_year_final": widgets.year_final_prod.date().year(),
        }

    def _get_prod_mode(self, widgets):
        if widgets.radio_lpd_te.isChecked():
            return ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value
        elif widgets.radio_fao_wocat.isChecked():
            return ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value
        elif widgets.radio_lpd_precalculated.isChecked():
            return ProductivityMode.JRC_5_CLASS_LPD.value
        elif (
            widgets.radio_lpd_custom is not None
            and widgets.radio_lpd_custom.isChecked()
        ):
            return ProductivityMode.CUSTOM_5_CLASS_LPD.value
        return None

    def enforce_prod_date_range(self, widgets, source=None):
        """
        Keep productivity range coupled to the common period when the
        "same period" option is active.

        - If the user updates the period start (year_initial), set
          year_final_prod = year_initial + MIN_YEARS_FOR_PROD_UPDATE.
        - If the user updates the period end (year_final), set
          year_initial_prod = year_final - MIN_YEARS_FOR_PROD_UPDATE.

        Returns True if any date widget was changed
        """
        if not widgets.radio_time_period_same.isChecked():
            return False

        if widgets.radio_lpd_precalculated.isChecked():
            return False

        period_start = widgets.year_initial.date()
        period_end = widgets.year_final.date()

        prod_start_widget = widgets.year_initial_prod
        prod_end_widget = widgets.year_final_prod

        min_prod_start = prod_start_widget.minimumDate()
        max_prod_start = prod_start_widget.maximumDate()
        min_prod_end = prod_end_widget.minimumDate()
        max_prod_end = prod_end_widget.maximumDate()

        def clamp_qdate(qdate, qmin, qmax):
            if qdate < qmin:
                return qmin
            if qdate > qmax:
                return qmax
            return qdate

        years = MIN_YEARS_FOR_PROD_UPDATE
        changed = False

        with (
            QtCore.QSignalBlocker(prod_start_widget),
            QtCore.QSignalBlocker(prod_end_widget),
        ):
            if source == "year_initial":
                target_start = clamp_qdate(period_start, min_prod_start, max_prod_start)
                if prod_start_widget.date() != target_start:
                    prod_start_widget.setDate(target_start)
                    changed = True

                end_delta = (
                    years - 1 if target_start == QtCore.QDate(2001, 1, 1) else years
                )
                new_prod_end = clamp_qdate(
                    target_start.addYears(end_delta), min_prod_end, max_prod_end
                )
                if prod_end_widget.date() != new_prod_end:
                    prod_end_widget.setDate(new_prod_end)
                    changed = True

            elif source == "year_final":
                target_end = clamp_qdate(period_end, min_prod_end, max_prod_end)
                if prod_end_widget.date() != target_end:
                    prod_end_widget.setDate(target_end)
                    changed = True

                new_prod_start = clamp_qdate(
                    target_end.addYears(-years), min_prod_start, max_prod_start
                )
                if prod_start_widget.date() != new_prod_start:
                    prod_start_widget.setDate(new_prod_start)
                    changed = True

            else:
                current_start = clamp_qdate(
                    prod_start_widget.date(), min_prod_start, max_prod_start
                )
                if prod_start_widget.date() != current_start:
                    prod_start_widget.setDate(current_start)
                    changed = True

                end_delta = years - 1
                expected_end = clamp_qdate(
                    current_start.addYears(end_delta), min_prod_end, max_prod_end
                )
                if prod_end_widget.date() != expected_end:
                    prod_end_widget.setDate(expected_end)
                    changed = True

        if changed:
            self.update_timeline_graph()

        return True

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super().btn_calculate()

        if not ret:
            return

        trans_matrix = self.lc_define_deg_widget.get_trans_matrix_from_widget()
        lc_setup.trans_matrix_to_settings(trans_matrix)

        periods = {"baseline": self._get_period_years(self.widgets_baseline)}

        progress_period = self._get_period_years(self.widgets_progress)
        if self.checkBox_progress_period.isChecked() and progress_period:
            periods["reporting_1"] = progress_period

        for i, (_, w) in enumerate(self.extra_progress_boxes, start=1):
            key = f"reporting_{i + 1}"
            periods[key] = self._get_period_years(w)

        crosses_180th, geojsons = self.gee_bounding_box

        payloads = []

        for (period, values), widgets in zip(
            periods.items(),
            [self.widgets_baseline, self.widgets_progress]
            + [w for _, w in self.extra_progress_boxes],
        ):
            payload = {}
            year_initial = values["period_year_initial"]
            year_final = values["period_year_final"]

            log(
                f"Setting parameters for {period} period ({year_initial} - {year_final})"
            )

            prod_mode = self._get_prod_mode(widgets)
            payload["productivity"] = {"mode": prod_mode}

            if prod_mode == ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value:
                # Critical check: Mann-Kendall test requires at least 4 years
                if (year_final - year_initial) < MIN_YEARS_FOR_MANN_KENDALL:
                    QtWidgets.QMessageBox.critical(
                        None,
                        self.tr("Error"),
                        self.tr(
                            f"Land productivity analysis requires at least {MIN_YEARS_FOR_MANN_KENDALL} years of data "
                            f"for the Mann-Kendall trend test. The {period} period ({year_initial} - {year_final}) "
                            f"only spans {year_final - year_initial} years. Please select a longer time period."
                        ),
                    )
                    return

                # Warning for suboptimal period length
                if (
                    year_final - year_initial
                ) < MIN_YEARS_FOR_PROD_UPDATE and year_initial != 2001:
                    QtWidgets.QMessageBox.warning(
                        None,
                        self.tr("Warning"),
                        self.tr(
                            f"Initial and final year are less {MIN_YEARS_FOR_PROD_UPDATE} years "
                            f"apart in {period} - results will be more "
                            "reliable if more data (years) are included "
                            "in the analysis."
                        ),
                    )

                # Calculate TrendsEarth productivity parameters using helper function
                trends_earth_params = self._calculate_trends_earth_productivity_params(
                    year_initial, year_final
                )

                payload["productivity"].update(
                    {
                        "asset_productivity": conf.REMOTE_DATASETS["NDVI"][
                            "MODIS (MOD13Q1, annual)"
                        ]["GEE Dataset"],
                        **trends_earth_params,
                        "asset_climate": None,
                    }
                )
            elif prod_mode == ProductivityMode.JRC_5_CLASS_LPD.value:
                prod_dataset = conf.REMOTE_DATASETS["Land Productivity Dynamics"][
                    widgets.cb_lpd.currentText()
                ]
                prod_asset = prod_dataset["GEE Dataset"]
                prod_start_year = prod_dataset["Start year"]
                prod_end_year = prod_dataset["End year"]
                prod_date_source = prod_dataset["Data source"]
                payload["productivity"].update(
                    {
                        "asset": prod_asset,
                        "year_initial": prod_start_year,
                        "year_final": prod_end_year,
                        "data_source": prod_date_source,
                    }
                )
            elif prod_mode == ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value:
                # Critical check: FAO WOCAT also uses Mann-Kendall test which requires at least 4 years
                if (year_final - year_initial) < MIN_YEARS_FOR_MANN_KENDALL:
                    QtWidgets.QMessageBox.critical(
                        None,
                        self.tr("Error"),
                        self.tr(
                            f"FAO WOCAT land productivity analysis requires at least {MIN_YEARS_FOR_MANN_KENDALL} years of data "
                            f"for the Mann-Kendall trend test. The {period} period ({year_initial} - {year_final}) "
                            f"only spans {year_final - year_initial} years. Please select a longer time period."
                        ),
                    )
                    return

                ndvi_dataset = conf.REMOTE_DATASETS["NDVI"]["MODIS (MOD13Q1, annual)"][
                    "GEE Dataset"
                ]

                low_biomass = getattr(
                    ld_config, "FAO_WOCAT_LOW_BIOMASS_THRESHOLD", 0.30
                )
                high_biomass = getattr(
                    ld_config, "FAO_WOCAT_HIGH_BIOMASS_THRESHOLD", 0.50
                )

                years_interval = 3

                payload["productivity"].update(
                    {
                        "ndvi_gee_dataset": ndvi_dataset,
                        "low_biomass": low_biomass,
                        "high_biomass": high_biomass,
                        "years_interval": years_interval,
                        "year_initial": widgets.year_initial_prod.date().year(),
                        "year_final": widgets.year_final_prod.date().year(),
                    }
                )
            else:
                raise ValueError("Unknown prod_mode {prod_mode}")

            payload["land_cover"] = {
                "year_initial": widgets.year_initial_lc.date().year(),
                "year_final": widgets.year_final_lc.date().year(),
                "legend_nesting_esa_to_custom": LCLegendNesting.Schema().dump(
                    lc_setup.esa_lc_nesting_from_settings()
                ),
                "legend_nesting_custom_to_ipcc": LCLegendNesting.Schema().dump(
                    lc_setup.ipcc_lc_nesting_from_settings()
                ),
                "trans_matrix": LCTransitionDefinitionDeg.Schema().dump(trans_matrix),
            }
            payload["soil_organic_carbon"] = {
                "year_initial": widgets.year_initial_soc.date().year(),
                "year_final": widgets.year_final_soc.date().year(),
                "fl": 0.80,
                "legend_nesting_esa_to_custom": LCLegendNesting.Schema().dump(
                    lc_setup.esa_lc_nesting_from_settings()
                ),
                "legend_nesting_custom_to_ipcc": LCLegendNesting.Schema().dump(
                    lc_setup.ipcc_lc_nesting_from_settings()
                ),
            }

            pop_dataset = conf.REMOTE_DATASETS["WorldPop"][
                "Gridded Population Count (gender breakdown)"
            ]
            pop_start_year = pop_dataset["Start year"]
            pop_end_year = pop_dataset["End year"]
            # Use a population dataset that is as close as possible to the
            # chosen final year, but no more than three years earlier or later
            # than that year
            if year_final < (pop_start_year - 3) or year_final > (pop_end_year + 3):
                log(
                    f"final year {year_final} is too far away from available worldpop data years"
                )
                QtWidgets.QMessageBox.information(
                    None,
                    self.tr("Error"),
                    self.tr(
                        f"Final year of the productivity data ({year_final}) must be "
                        "within three years of the years for which population data "
                        f"is available from the WorldPop dataset ({pop_start_year}-{pop_end_year})."
                    ),
                )
                return
            else:
                if year_final < pop_start_year:
                    pop_year = pop_start_year
                elif year_final > pop_end_year:
                    pop_year = pop_end_year
                else:
                    pop_year = year_final
            payload["population"] = {
                "year": pop_year,
                "asset": pop_dataset["GEE Dataset"],
                "source": "WorldPop (gender breakdown)",
            }

            task_name = self.execution_name_le.text()

            if len(periods.items()) == 1:
                task_name = f"{period}"
            else:
                task_name = f"{task_name} - {period}"

            payload.update(
                {
                    "geojsons": geojsons,
                    "crs": self.aoi.get_crs_dst_wkt(),
                    "crosses_180th": crosses_180th,
                    "task_name": task_name,
                    "task_notes": self.task_notes.toPlainText(),
                    "script": ExecutionScript.Schema().dump(self.script),
                    "period": {
                        "name": period,
                        "year_initial": year_initial,
                        "year_final": year_final,
                    },
                }
            )

            payloads.append(payload)

        self.close()

        for payload in payloads:
            resp = job_manager.submit_remote_job(payload, self.script.id)

            if resp:
                main_msg = "Submitted"
                description = "SDG sub-indicator task submitted to Trends.Earth server."
            else:
                main_msg = "Error"
                description = (
                    "Unable to submit SDG sub-indicator task to Trends.Earth server."
                )
            self.mb.pushMessage(
                self.tr(main_msg), self.tr(description), level=0, duration=5
            )


class DlgCalculateLDNSummaryTableAdmin(
    DlgCalculateBase, DlgCalculateLdnSummaryTableAdminUi
):
    LOCAL_SCRIPT_NAME: str = "sdg-15-3-1-summary"

    button_calculate: QtWidgets.QPushButton
    combo_boxes: typing.Dict[str, ldn.SummaryTableLDWidgets] = {}

    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        script: ExecutionScript,
        parent: QtWidgets.QWidget = None,
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)

        self.checkBox_progress_period.toggled.connect(self.toggle_progress_period)
        self.pushButton_progress_period.clicked.connect(
            self.on_add_progress_period_clicked
        )

        self.combo_boxes = dict()

        self._finish_initialization()

        self.combo_datasets_baseline.NO_DATASETS_MESSAGE = self.tr(
            "No datasets available in this region (see advanced)"
        )
        self.combo_datasets_progress.NO_DATASETS_MESSAGE = self.tr(
            "No datasets available in this region (see advanced)"
        )
        self.combo_boxes["baseline"] = ldn.SummaryTableLDWidgets(
            combo_datasets=self.combo_datasets_baseline,
            combo_layer_traj=self.combo_layer_traj_baseline,
            combo_layer_traj_label=self.combo_layer_traj_label_baseline,
            combo_layer_perf=self.combo_layer_perf_baseline,
            combo_layer_perf_label=self.combo_layer_perf_label_baseline,
            combo_layer_state=self.combo_layer_state_baseline,
            combo_layer_state_label=self.combo_layer_state_label_baseline,
            combo_layer_lpd=self.combo_layer_lpd_baseline,
            combo_layer_lpd_label=self.combo_layer_lpd_label_baseline,
            combo_layer_lc=self.combo_layer_lc_baseline,
            combo_layer_soc=self.combo_layer_soc_baseline,
            combo_layer_pop_total=self.combo_layer_population_baseline_total,
            combo_layer_pop_male=self.combo_layer_population_baseline_male,
            combo_layer_pop_female=self.combo_layer_population_baseline_female,
            radio_lpd_te=self.radio_lpd_te,
            radio_fao_wocat=self.radio_fao_wocat,
            radio_lpd_custom=self.radio_lpd_custom,
        )
        self.combo_boxes["report_1"] = ldn.SummaryTableLDWidgets(
            combo_datasets=self.combo_datasets_progress,
            combo_layer_traj=self.combo_layer_traj_progress,
            combo_layer_traj_label=self.combo_layer_traj_label_progress,
            combo_layer_perf=self.combo_layer_perf_progress,
            combo_layer_perf_label=self.combo_layer_perf_label_progress,
            combo_layer_state=self.combo_layer_state_progress,
            combo_layer_state_label=self.combo_layer_state_label_progress,
            combo_layer_lpd=self.combo_layer_lpd_progress,
            combo_layer_lpd_label=self.combo_layer_lpd_label_progress,
            combo_layer_lc=self.combo_layer_lc_progress,
            combo_layer_soc=self.combo_layer_soc_progress,
            combo_layer_pop_total=self.combo_layer_population_progress_total,
            combo_layer_pop_male=self.combo_layer_population_progress_male,
            combo_layer_pop_female=self.combo_layer_population_progress_female,
            radio_lpd_te=self.radio_lpd_te,
            radio_fao_wocat=self.radio_fao_wocat,
            radio_lpd_custom=self.radio_lpd_custom,
        )

        self.radio_population_baseline_bysex.toggled.connect(
            self.toggle_pop_options_baseline
        )
        self.toggle_pop_options_baseline()

        self.radio_population_progress_bysex.toggled.connect(
            self.toggle_pop_options_progress
        )
        self.toggle_pop_options_progress()
        self.changed_region.connect(self.populate_combos)

        self.extra_progress_boxes = dict()

    def populate_combos(self):
        for combo in self.combo_boxes.values():
            combo.populate()

    def showEvent(self, event):
        super().showEvent(event)
        self.populate_combos()
        self.toggle_progress_period()

    def toggle_pop_options_baseline(self):
        if self.radio_population_baseline_bysex.isChecked():
            self.combo_layer_population_baseline_male.setEnabled(True)
            self.combo_layer_population_baseline_female.setEnabled(True)
            self.label_male_population_baseline.setEnabled(True)
            self.label_female_population_baseline.setEnabled(True)
            self.combo_layer_population_baseline_total.setEnabled(False)
            self.label_total_population_baseline.setEnabled(False)
        else:
            self.combo_layer_population_baseline_male.setEnabled(False)
            self.combo_layer_population_baseline_female.setEnabled(False)
            self.label_male_population_baseline.setEnabled(False)
            self.label_female_population_baseline.setEnabled(False)
            self.combo_layer_population_baseline_total.setEnabled(True)
            self.label_total_population_baseline.setEnabled(True)

    def toggle_pop_options_progress(self):
        if self.radio_population_progress_bysex.isChecked():
            self.combo_layer_population_progress_male.setEnabled(True)
            self.combo_layer_population_progress_female.setEnabled(True)
            self.label_male_population_progress.setEnabled(True)
            self.label_female_population_progress.setEnabled(True)
            self.combo_layer_population_progress_total.setEnabled(False)
            self.label_total_population_progress.setEnabled(False)
        else:
            self.combo_layer_population_progress_male.setEnabled(False)
            self.combo_layer_population_progress_female.setEnabled(False)
            self.label_male_population_progress.setEnabled(False)
            self.label_female_population_progress.setEnabled(False)
            self.combo_layer_population_progress_total.setEnabled(True)
            self.label_total_population_progress.setEnabled(True)

    def on_add_progress_period_clicked(self):
        """
        Create a new reporting period group box and add it to the layout.
        """

        class DlgAdvancedSettingsProgressPeriod(
            DlgCalculateBase, DlgCalculateLdnSummaryTableAdminUi
        ):
            def __init__(
                self,
                iface,
                script,
            ):
                super().__init__(iface, script)
                self.setupUi(self)

        dlg_instance = DlgAdvancedSettingsProgressPeriod(self.iface, self.script)
        grp = QtWidgets.QGroupBox()
        # Calculate the next report period number
        # Base combo boxes are "baseline" and "report_1", so we start from report_2
        existing_report_numbers = [
            int(key.split("_")[1])
            for key in self.combo_boxes.keys()
            if key.startswith("report_")
        ]
        next_idx = max(existing_report_numbers, default=0) + 1
        grp.setTitle(f"Reporting period #{next_idx}")
        layout = QtWidgets.QVBoxLayout(grp)

        key = f"report_{next_idx}"
        self.combo_boxes[key] = ldn.SummaryTableLDWidgets(
            combo_datasets=dlg_instance.combo_datasets_baseline,
            combo_layer_traj=dlg_instance.combo_layer_traj_progress,
            combo_layer_traj_label=dlg_instance.combo_layer_traj_label_progress,
            combo_layer_perf=dlg_instance.combo_layer_perf_progress,
            combo_layer_perf_label=dlg_instance.combo_layer_perf_label_progress,
            combo_layer_state=dlg_instance.combo_layer_state_progress,
            combo_layer_state_label=dlg_instance.combo_layer_state_label_progress,
            combo_layer_lpd=dlg_instance.combo_layer_lpd_progress,
            combo_layer_lpd_label=dlg_instance.combo_layer_lpd_label_progress,
            combo_layer_lc=dlg_instance.combo_layer_lc_progress,
            combo_layer_soc=dlg_instance.combo_layer_soc_progress,
            combo_layer_pop_total=dlg_instance.combo_layer_population_progress_total,
            combo_layer_pop_male=dlg_instance.combo_layer_population_progress_male,
            combo_layer_pop_female=dlg_instance.combo_layer_population_progress_female,
            radio_lpd_te=self.radio_lpd_te,
            radio_fao_wocat=self.radio_fao_wocat,
            radio_lpd_custom=self.radio_lpd_custom,
        )
        self.combo_boxes[key].populate()

        layout.insertWidget(0, dlg_instance.combo_datasets_baseline)
        count = self.verticalLayout_progress.count()
        self.verticalLayout_progress.insertWidget(count - 1, grp)
        dlg_instance.advanced_configuration_progress.setTitle(
            f"Advanced (reporting period) #{next_idx}"
        )
        self.verticalLayout_progress.insertWidget(
            count, dlg_instance.advanced_configuration_progress
        )
        self.extra_progress_boxes[key] = (
            grp,
            dlg_instance.advanced_configuration_progress,
        )

    def toggle_progress_period(self):
        if self.checkBox_progress_period.isChecked():
            self.groupBox_progress_period.setVisible(True)
            self.advanced_configuration_progress.setVisible(True)
            self.pushButton_progress_period.setVisible(True)
        else:
            self.groupBox_progress_period.setVisible(False)
            self.advanced_configuration_progress.setVisible(False)
            self.pushButton_progress_period.setVisible(False)
            for grp, settings in self.extra_progress_boxes.items():
                grp.setParent(None)
                grp.deleteLater()
                settings.setParent(None)
                settings.deleteLater()

            # Keep only baseline and report_1 combo boxes
            base_keys = ["baseline", "report_1"]
            self.combo_boxes = {
                k: v for k, v in self.combo_boxes.items() if k in base_keys
            }
            self.extra_progress_boxes = dict()

    def _validate_layer_selection(self, combo_box, layer_name):
        if len(combo_box.layer_list) == 0:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    f"You must select a {layer_name} layer "
                    "before you can use the SDG calculation tool."
                ),
            )
            return False
        else:
            return True

    def validate_layer_selections(self, combo_boxes, pop_mode):
        """validate all needed layers are selected"""

        if self.radio_lpd_te.isChecked():
            if not self._validate_layer_selection(
                combo_boxes.combo_layer_traj, "trend"
            ):
                return False
            if not self._validate_layer_selection(
                combo_boxes.combo_layer_state, "state"
            ):
                return False
            if not self._validate_layer_selection(
                combo_boxes.combo_layer_perf, "performance"
            ):
                return False

        else:
            if not self._validate_layer_selection(
                combo_boxes.combo_layer_lpd, "Land Productivity Dynamics"
            ):
                return False

        if not self._validate_layer_selection(combo_boxes.combo_layer_lc, "land cover"):
            return False

        if not self._validate_layer_selection(
            combo_boxes.combo_layer_soc, "soil organic carbon"
        ):
            return False

        if pop_mode == ldn.PopulationMode.BySex.value:
            if not self._validate_layer_selection(
                combo_boxes.combo_layer_pop_male, "population (male)"
            ):
                return False
            if not self._validate_layer_selection(
                combo_boxes.combo_layer_pop_female, "population (female)"
            ):
                return False
        else:
            if not self._validate_layer_selection(
                combo_boxes.combo_layer_pop_total, "population (total)"
            ):
                return False

        return True

    def _validate_layer_extent(self, check_layer, check_layer_name):
        log(
            f"fraction of overlap is {self.aoi.calc_frac_overlap(QgsGeometry.fromRect(check_layer.extent()))}"
        )
        if (
            self.aoi.calc_frac_overlap(QgsGeometry.fromRect(check_layer.extent()))
            < 0.99
        ):
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    f"Area of interest is not entirely within the {check_layer_name} layer."
                ),
            )
            return False
        else:
            return True

    def validate_layer_extents(self, combo_boxes, pop_mode):
        """Check that the layers cover the full extent of the AOI"""

        if self.radio_lpd_te.isChecked():
            if not self._validate_layer_extent(
                combo_boxes.combo_layer_traj.get_layer(), "trend"
            ):
                return False

            if not self._validate_layer_extent(
                combo_boxes.combo_layer_perf.get_layer(), "performance"
            ):
                return False

            if not self._validate_layer_extent(
                combo_boxes.combo_layer_state.get_layer(), "state"
            ):
                return False

        else:
            if not self._validate_layer_extent(
                combo_boxes.combo_layer_lpd.get_layer(), "Land Productivity Dynamics"
            ):
                return False

        if not self._validate_layer_extent(
            combo_boxes.combo_layer_lc.get_layer(), "land cover"
        ):
            return False

        if not self._validate_layer_extent(
            combo_boxes.combo_layer_soc.get_layer(), "soil organic carbon"
        ):
            return False

        if pop_mode == ldn.PopulationMode.BySex.value:
            if not self._validate_layer_extent(
                combo_boxes.combo_layer_pop_male.get_layer(), "population (male)"
            ):
                return False
            if not self._validate_layer_extent(
                combo_boxes.combo_layer_pop_female.get_layer(), "population (female)"
            ):
                return False
        else:
            if not self._validate_layer_extent(
                combo_boxes.combo_layer_pop_total.get_layer(), "population (total)"
            ):
                return False

        return True

    def _validate_crs(
        self,
        model_layer,
        model_layer_name,
        check_layer,
        check_layer_name,
        check_res=True,
    ):
        def _res(layer):
            return (
                round(layer.rasterUnitsPerPixelX(), 10),
                round(layer.rasterUnitsPerPixelY(), 10),
            )

        if check_res and _res(model_layer) != _res(check_layer):
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    f"Resolutions of {model_layer_name} layer and {check_layer_name} layer do not match."
                ),
            )
            return False
        elif model_layer.crs() != check_layer.crs():
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    f"Coordinate systems of {model_layer_name} layer and {check_layer_name} layer do not match."
                ),
            )
            return False
        else:
            return True

    def validate_layer_crs(self, combo_boxes, pop_mode):
        """check all layers have the same resolution and CRS"""
        if self.radio_lpd_te.isChecked():
            model_layer = combo_boxes.combo_layer_traj.get_layer()
            model_layer_name = "trend"

            if not self._validate_crs(
                model_layer,
                model_layer_name,
                combo_boxes.combo_layer_state.get_layer(),
                "state",
            ):
                return False

            if not self._validate_crs(
                model_layer,
                model_layer_name,
                combo_boxes.combo_layer_perf.get_layer(),
                "performance",
            ):
                return False

        if pop_mode == ldn.PopulationMode.BySex.value:
            if not self._validate_crs(
                combo_boxes.combo_layer_pop_male.get_layer(),
                "population (male)",
                combo_boxes.combo_layer_pop_female.get_layer(),
                "population (female)",
            ):
                return False

        return True

    def _get_prod_mode(self, radio_lpd_te, radio_fao_wocat):
        if radio_lpd_te.isChecked():
            return ProductivityMode.TRENDS_EARTH_5_CLASS_LPD.value
        elif radio_fao_wocat.isChecked():
            return ProductivityMode.FAO_WOCAT_5_CLASS_LPD.value
        elif self.radio_lpd_custom is not None and self.radio_lpd_custom.isChecked():
            return ProductivityMode.CUSTOM_5_CLASS_LPD.value
        else:
            return ProductivityMode.JRC_5_CLASS_LPD.value

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super().btn_calculate()

        if not ret:
            return

        # Baseline
        #

        if self.radio_population_baseline_bysex.isChecked():
            pop_mode_baseline = ldn.PopulationMode.BySex.value
        else:
            pop_mode_baseline = ldn.PopulationMode.Total.value

        if (
            not self.validate_layer_selections(
                self.combo_boxes["baseline"], pop_mode_baseline
            )
            or not self.validate_layer_crs(
                self.combo_boxes["baseline"], pop_mode_baseline
            )
            or not self.validate_layer_extents(
                self.combo_boxes["baseline"], pop_mode_baseline
            )
        ):
            log("failed baseline layer validation")

            return

        prod_mode_baseline = self._get_prod_mode(
            self.radio_lpd_te, self.radio_fao_wocat
        )

        periods = [
            {
                "name": "baseline",
                "params": ldn.get_main_sdg_15_3_1_job_params(
                    task_name=self.execution_name_le.text(),
                    aoi=self.aoi,
                    prod_mode=prod_mode_baseline,
                    pop_mode=pop_mode_baseline,
                    period_name="baseline",
                    combo_layer_lc=self.combo_boxes["baseline"].combo_layer_lc,
                    combo_layer_soc=self.combo_boxes["baseline"].combo_layer_soc,
                    combo_layer_traj=self.combo_boxes["baseline"].combo_layer_traj,
                    combo_layer_perf=self.combo_boxes["baseline"].combo_layer_perf,
                    combo_layer_state=self.combo_boxes["baseline"].combo_layer_state,
                    combo_layer_lpd=self.combo_boxes["baseline"].combo_layer_lpd,
                    combo_layer_pop_total=self.combo_boxes[
                        "baseline"
                    ].combo_layer_pop_total,
                    combo_layer_pop_male=self.combo_boxes[
                        "baseline"
                    ].combo_layer_pop_male,
                    combo_layer_pop_female=self.combo_boxes[
                        "baseline"
                    ].combo_layer_pop_female,
                    task_notes=self.task_notes.toPlainText(),
                ),
            }
        ]

        ##########
        # Progress

        if self.checkBox_progress_period.isChecked():
            for key, combobox in list(self.combo_boxes.items()):
                if key == "baseline":
                    continue
                prod_mode_progress = self._get_prod_mode(
                    self.radio_lpd_te, self.radio_fao_wocat
                )

                if self.radio_population_progress_bysex.isChecked():
                    pop_mode_progress = ldn.PopulationMode.BySex.value
                else:
                    pop_mode_progress = ldn.PopulationMode.Total.value

                if (
                    not self.validate_layer_selections(
                        self.combo_boxes[key], pop_mode_progress
                    )
                    or not self.validate_layer_crs(
                        self.combo_boxes[key], pop_mode_progress
                    )
                    or not self.validate_layer_extents(
                        self.combo_boxes[key], pop_mode_progress
                    )
                ):
                    log("failed progress layer validation")

                    return

                periods.append(
                    {
                        "name": key,
                        "params": ldn.get_main_sdg_15_3_1_job_params(
                            task_name=self.execution_name_le.text(),
                            aoi=self.aoi,
                            prod_mode=prod_mode_progress,
                            pop_mode=pop_mode_progress,
                            period_name=key,
                            combo_layer_lc=self.combo_boxes[key].combo_layer_lc,
                            combo_layer_soc=self.combo_boxes[key].combo_layer_soc,
                            combo_layer_traj=self.combo_boxes[key].combo_layer_traj,
                            combo_layer_perf=self.combo_boxes[key].combo_layer_perf,
                            combo_layer_state=self.combo_boxes[key].combo_layer_state,
                            combo_layer_lpd=self.combo_boxes[key].combo_layer_lpd,
                            combo_layer_pop_total=self.combo_boxes[
                                key
                            ].combo_layer_pop_total,
                            combo_layer_pop_male=self.combo_boxes[
                                key
                            ].combo_layer_pop_male,
                            combo_layer_pop_female=self.combo_boxes[
                                key
                            ].combo_layer_pop_female,
                            task_notes=self.task_notes.toPlainText(),
                        ),
                    }
                )

        params = {
            "periods": periods,
            "task_name": self.execution_name_le.text(),
            "task_notes": self.task_notes.toPlainText(),
        }

        self.close()

        job_manager.submit_local_job_as_qgstask(
            params, script_name=self.LOCAL_SCRIPT_NAME, area_of_interest=self.aoi
        )


class DlgCalculateLDNErrorRecode(DlgCalculateBase, DlgCalculateLdnErrorRecodeUi):
    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        script: ExecutionScript,
        parent: QtWidgets.QWidget = None,
    ):
        super().__init__(iface, script, parent)
        self.setupUi(self)

        self.changed_region.connect(self.combo_dataset_error_recode.populate)

        self._finish_initialization()

    def showEvent(self, event):
        super().showEvent(event)
        self.combo_dataset_error_recode.populate()
        self.rb_grp_input_layer.buttonClicked.connect(self.set_layer_filter)
        self.set_layer_filter()

    def set_layer_filter(self):
        if self.rb_sdg.isChecked():
            self.combo_layer_input.setProperty(
                "layer_type",
                ";".join([ld_config.SDG_BAND_NAME, ld_config.SDG_STATUS_BAND_NAME]),
            )
        elif self.rb_prod.isChecked():
            self.combo_layer_input.setProperty(
                "layer_type",
                ";".join(
                    [
                        ld_config.JRC_LPD_BAND_NAME,
                        ld_config.FAO_WOCAT_LPD_BAND_NAME,
                        ld_config.TE_LPD_BAND_NAME,
                    ]
                ),
            )
        elif self.rb_lc.isChecked():
            self.combo_layer_input.setProperty(
                "layer_type",
                ";".join(
                    [ld_config.LC_DEG_BAND_NAME, ld_config.LC_DEG_COMPARISON_BAND_NAME]
                ),
            )
        elif self.rb_soc.isChecked():
            self.combo_layer_input.setProperty(
                "layer_type", ld_config.SOC_DEG_BAND_NAME
            )
        self.combo_layer_input.populate()
        log(f"filter set to {self.combo_layer_input.property('layer_type')}")

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.

        QtWidgets.QMessageBox.information(
            None, self.tr("Coming soon!"), self.tr("This function coming soon!")
        )
        self.close()
        return

        # ret = super(DlgCalculateUNCCD, self).btn_calculate()
        #
        # if not ret:
        #     return
        #
        # crosses_180th, geojsons = self.gee_bounding_box
        #
        # year_initial = self.year_initial_de.date().year()
        # year_final = self.year_final_de.date().year()
        #
        # if (year_final - year_initial) < 5:
        #     QtWidgets.QMessageBox.warning(
        #         None,
        #         self.tr("Error"),
        #         self.tr(
        #             "Initial and final year are less 5 years "
        #             "apart in - results will be more reliable "
        #             "if more data (years) are included in the analysis."
        #         ),
        #     )
        #
        #     return
        #
        # payload = {}
        # payload["population"] = {
        #     "asset": self.population_dataset["GEE Dataset"],
        #     "source": self.population_dataset_name,
        # }
        #
        # payload["spi"] = {
        #     "asset": self.spi_dataset["GEE Dataset"],
        #     "source": self.spi_dataset_name,
        #     "lag": int(self.lag_cb.currentText()),
        # }
        #
        # payload.update(
        #     {
        #         "geojsons": geojsons,
        #         "crs": self.aoi.get_crs_dst_wkt(),
        #         "crosses_180th": crosses_180th,
        #         "task_name": self.execution_name_le.text(),
        #         "task_notes": self.task_notes.toPlainText(),
        #         "script": ExecutionScript.Schema().dump(self.script),
        #         "year_initial": year_initial,
        #         "year_final": year_final,
        #     }
        # )
        #
        # self.close()
        #
        # resp = job_manager.submit_remote_job(payload, self.script.id)
        #
        # if resp:
        #     main_msg = "Submitted"
        #     description = "UNCCD default data task submitted to Trends.Earth server."
        # else:
        #     main_msg = "Error"
        #     description = "Unable to UNCCD default data task to Trends.Earth server."
        # self.mb.pushMessage(
        #     self.tr(main_msg), self.tr(description), level=0, duration=5
        # )
