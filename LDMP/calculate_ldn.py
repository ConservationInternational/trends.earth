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
import typing
import weakref
from dataclasses import dataclass
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


MIN_YEARS_FOR_PROD_UPDATE: int = 15


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

        # Progress period years, if active
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
                    title=f"Progress period #{idx}",
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

        self.year_initial_baseline.dateChanged.connect(
            lambda: self.update_start_dates(self.widgets_baseline)
        )
        self.year_final_baseline.dateChanged.connect(
            lambda: self.update_end_dates(self.widgets_baseline)
        )
        self.year_initial_baseline_prod.dateChanged.connect(
            lambda: self.enforce_prod_date_range(self.widgets_baseline)
        )
        self.year_final_baseline_prod.dateChanged.connect(
            lambda: self.enforce_prod_date_range(self.widgets_baseline)
        )
        self.year_initial_progress.dateChanged.connect(
            lambda: self.update_start_dates(self.widgets_progress)
        )
        self.year_final_progress.dateChanged.connect(
            lambda: self.update_end_dates(self.widgets_progress)
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

        self.button_preset_unccd_default_jrc.clicked.connect(
            self.set_preset_unccd_default_jrc
        )
        self.button_preset_unccd_default_te.clicked.connect(
            self.set_preset_unccd_default_te
        )
        self.button_preset_unccd_default_fao_wocat.clicked.connect(
            self.set_preset_unccd_default_fao_wocat
        )

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

    def set_preset_unccd_default_jrc(self):
        self.checkBox_progress_period.setChecked(True)
        self.radio_lpd_precalculated.setChecked(True)
        self.cb_jrc_baseline.setCurrentIndex(
            self.cb_jrc_baseline.findText("JRC Land Productivity Dynamics (2000-2015)")
        )
        self.cb_jrc_progress.setCurrentIndex(
            self.cb_jrc_baseline.findText("JRC Land Productivity Dynamics (2005-2019)")
        )
        self.radio_time_period_same_baseline.setChecked(True)
        self.radio_time_period_vary_progress.setChecked(True)
        self.year_initial_baseline.setDate(QtCore.QDate(2000, 1, 1))
        self.year_final_baseline.setDate(QtCore.QDate(2015, 1, 1))
        self.year_initial_progress.setDate(QtCore.QDate(2005, 1, 1))
        self.year_final_progress.setDate(QtCore.QDate(2019, 1, 1))
        self.year_initial_progress_lc.setDate(QtCore.QDate(2015, 1, 1))
        self.year_final_progress_lc.setDate(QtCore.QDate(2019, 1, 1))
        self.year_initial_progress_soc.setDate(QtCore.QDate(2015, 1, 1))
        self.year_final_progress_soc.setDate(QtCore.QDate(2019, 1, 1))
        if self._ask_reset_legend():
            lc_setup.LccInfoUtils.set_default_unccd_classes(force_update=True)
            self.lc_setup_widget.aggregation_dialog.reset_nesting_table(
                get_default=True
            )
            self.lc_define_deg_widget.set_trans_matrix(get_default=True)

    def set_preset_unccd_default_fao_wocat(self):
        self.checkBox_progress_period.setChecked(True)
        self.radio_fao_wocat.setChecked(True)
        self.radio_time_period_same_baseline.setChecked(True)
        self.radio_time_period_vary_progress.setChecked(True)
        self.year_initial_baseline.setDate(QtCore.QDate(2001, 1, 1))
        self.year_final_baseline.setDate(QtCore.QDate(2015, 1, 1))
        self.year_initial_progress.setDate(QtCore.QDate(2005, 1, 1))
        self.year_final_progress.setDate(QtCore.QDate(2019, 1, 1))
        self.year_initial_progress_lc.setDate(QtCore.QDate(2015, 1, 1))
        self.year_final_progress_lc.setDate(QtCore.QDate(2019, 1, 1))
        self.year_initial_progress_soc.setDate(QtCore.QDate(2015, 1, 1))
        self.year_final_progress_soc.setDate(QtCore.QDate(2019, 1, 1))

        if self._ask_reset_legend():
            lc_setup.LccInfoUtils.set_default_unccd_classes(force_update=True)
            self.lc_setup_widget.aggregation_dialog.reset_nesting_table(
                get_default=True
            )
            self.lc_define_deg_widget.set_trans_matrix(get_default=True)

    def set_preset_unccd_default_te(self):
        self.checkBox_progress_period.setChecked(True)
        self.radio_lpd_te.setChecked(True)
        self.radio_time_period_same_baseline.setChecked(True)
        self.radio_time_period_vary_progress.setChecked(True)
        self.year_initial_baseline.setDate(QtCore.QDate(2001, 1, 1))
        self.year_final_baseline.setDate(QtCore.QDate(2015, 1, 1))
        self.year_initial_progress.setDate(QtCore.QDate(2005, 1, 1))
        self.year_final_progress.setDate(QtCore.QDate(2019, 1, 1))
        self.year_initial_progress_lc.setDate(QtCore.QDate(2015, 1, 1))
        self.year_final_progress_lc.setDate(QtCore.QDate(2019, 1, 1))
        self.year_initial_progress_soc.setDate(QtCore.QDate(2015, 1, 1))
        self.year_final_progress_soc.setDate(QtCore.QDate(2019, 1, 1))

        if self._ask_reset_legend():
            lc_setup.LccInfoUtils.set_default_unccd_classes(force_update=True)
            self.lc_setup_widget.aggregation_dialog.reset_nesting_table(
                get_default=True
            )
            self.lc_define_deg_widget.set_trans_matrix(get_default=True)

    def _update_common_dates(self, widgets):
        year_initial = widgets.year_initial.date()
        year_final = widgets.year_final.date()

        widgets.year_initial_lc.setDate(year_initial)
        widgets.year_initial_soc.setDate(year_initial)
        widgets.year_final_lc.setDate(year_final)
        widgets.year_final_soc.setDate(year_final)

        # if FAO-WOCAT checked, prod initial date can't be updated
        if not widgets.radio_fao_wocat.isChecked():
            widgets.year_initial_prod.setDate(year_initial)

        widgets.year_final_prod.setDate(year_final)

        self.update_timeline_graph()

    def update_start_dates(self, widgets):
        self._update_common_dates(widgets)

    def update_end_dates(self, widgets):
        self._update_common_dates(widgets)

    def toggle_time_period(self, widgets):
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
            widgets.year_final_prod.setEnabled(True)

            if widgets.radio_lpd_te.isChecked():
                widgets.label_prod.setEnabled(True)
                widgets.year_initial_prod.setEnabled(True)

    def toggle_lpd_options(self):
        """
        Adjust visibility of Land Productivity Dynamics (LPD) widgets
        according to the chosen LPD mode.
        """
        is_precalc = self.radio_lpd_precalculated.isChecked()

        # Main widgets (baseline & first progress period)
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

        # Extra progress‑period widgets
        for _box, w in getattr(self, "extra_progress_boxes", []):
            w.cb_lpd.setVisible(is_precalc)

            lbl = _box.findChild(QtWidgets.QLabel, "label_jrc_progress")
            if lbl is not None:
                lbl.setVisible(is_precalc)

        # Refresh dependent controls
        self.update_time_bounds(self.widgets_baseline)
        self.update_time_bounds(self.widgets_progress)
        for _box, w in getattr(self, "extra_progress_boxes", []):
            self.update_time_bounds(w)

        self.toggle_time_period(self.widgets_baseline)
        self.toggle_time_period(self.widgets_progress)
        for _box, w in getattr(self, "extra_progress_boxes", []):
            self.toggle_time_period(w)

    # Remove any remaining merge conflict markers in the rest of the file

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
        start_year = max(start_year_prod, start_year_lc)
        end_year = min(end_year_prod, end_year_lc)

        if self.radio_lpd_precalculated.isChecked():
            if not widgets.cb_lpd.currentText():
                widgets.cb_lpd.setCurrentIndex(0)

            prod_dataset = conf.REMOTE_DATASETS["Land Productivity Dynamics"][
                widgets.cb_lpd.currentText()
            ]
            start_year_prod = prod_dataset["Start year"]
            end_year_prod = prod_dataset["End year"]

            # Don't need to consider prod dates in below lims when using JRC, but do use
            # them to set default time period
            start_year = start_year_lc
            end_year = end_year_lc
            start_year_prod = QtCore.QDate(start_year_prod, 1, 1)
            end_year_prod = QtCore.QDate(end_year_prod, 1, 1)

        widgets.year_initial.setMinimumDate(start_year)
        widgets.year_initial.setMaximumDate(end_year)
        widgets.year_final.setMinimumDate(start_year)
        widgets.year_final.setMaximumDate(end_year)

        widgets.year_initial_prod.setDate(start_year_prod)
        widgets.year_final_prod.setDate(end_year_prod)
        widgets.year_initial_prod.setMinimumDate(start_year_lc)
        widgets.year_initial_prod.setMaximumDate(end_year_lc)
        widgets.year_final_prod.setMinimumDate(start_year_lc)
        widgets.year_final_prod.setMaximumDate(end_year_lc)

        widgets.year_initial_lc.setMinimumDate(start_year_lc)
        widgets.year_initial_lc.setMaximumDate(end_year_lc)
        widgets.year_final_lc.setMinimumDate(start_year_lc)
        widgets.year_final_lc.setMaximumDate(end_year_lc)

        widgets.year_initial_soc.setMinimumDate(start_year_lc)
        widgets.year_initial_soc.setMaximumDate(end_year_lc)
        widgets.year_final_soc.setMinimumDate(start_year_lc)
        widgets.year_final_soc.setMaximumDate(end_year_lc)

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

        return grp, w

    @QtCore.pyqtSlot()
    def on_add_period_clicked(self):
        grp, widgets = self._create_progress_period()
        grp.setTitle(f"Progress period #{len(self.extra_progress_boxes) + 2}")

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

        is_te = self.radio_lpd_te.isChecked()
        for _box, w in getattr(self, "extra_progress_boxes", []):
            w.cb_lpd.setVisible(not is_te)

            lbl = _box.findChild(QtWidgets.QLabel, "label_jrc_progress")
            if lbl is not None:
                lbl.setVisible(not is_te)

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
        return None

    def enforce_prod_date_range(self, widgets):
        if not widgets.radio_time_period_same.isChecked():
            return False
        initial_date = widgets.year_initial_prod.date()
        final_date = widgets.year_final_prod.date()

        max_final = widgets.year_final.maximumDate()
        min_final = widgets.year_final.minimumDate()
        min_initial = widgets.year_initial.minimumDate()

        expected_final = initial_date.addYears(MIN_YEARS_FOR_PROD_UPDATE)
        expected_initial = final_date.addYears(-MIN_YEARS_FOR_PROD_UPDATE)

        widgets.year_initial_prod.setMinimumDate(min_initial)

        if expected_final <= max_final and initial_date != expected_initial:
            widgets.year_final_prod.blockSignals(True)
            widgets.year_final_prod.setDate(expected_final)
            widgets.year_final_prod.setMinimumDate(min_final)
            widgets.year_final_prod.setMaximumDate(max_final)
            widgets.year_final_prod.blockSignals(False)
        elif expected_initial >= min_initial and final_date != expected_final:
            widgets.year_initial_prod.blockSignals(True)
            widgets.year_initial_prod.setDate(expected_initial)
            widgets.year_initial_prod.blockSignals(False)

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
            periods["progress_1"] = progress_period

        for i, (_, w) in enumerate(self.extra_progress_boxes, start=1):
            key = f"progress_{i + 1}"
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
                if (year_final - year_initial) < MIN_YEARS_FOR_PROD_UPDATE:
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

                # Have productivity state consider the last 3 years for the
                # current
                # period, and the years preceding those last 3 for the baseline
                prod_state_year_bl_start = year_initial
                prod_state_year_bl_end = year_final - 3
                prod_state_year_tg_start = prod_state_year_bl_end + 1
                prod_state_year_tg_end = prod_state_year_bl_end + 3
                assert prod_state_year_tg_end == year_final

                payload["productivity"].update(
                    {
                        "asset_productivity": conf.REMOTE_DATASETS["NDVI"][
                            "MODIS (MOD13Q1, annual)"
                        ]["GEE Dataset"],
                        "traj_method": "ndvi_trend",
                        "traj_year_initial": year_initial,
                        "traj_year_final": year_final,
                        "perf_year_initial": year_initial,
                        "perf_year_final": year_final,
                        "state_year_bl_start": prod_state_year_bl_start,
                        "state_year_bl_end": prod_state_year_bl_end,
                        "state_year_tg_start": prod_state_year_tg_start,
                        "state_year_tg_end": prod_state_year_tg_end,
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
                ndvi_dataset = conf.REMOTE_DATASETS["NDVI"]["MODIS (MOD13Q1, annual)"][
                    "GEE Dataset"
                ]

                low_biomass = getattr(
                    ld_config, "FAO_WOCAT_LOW_BIOMASS_THRESHOLD", 0.30
                )
                high_biomass = getattr(
                    ld_config, "FAO_WOCAT_HIGH_BIOMASS_THRESHOLD", 0.50
                )

                years_interval = (
                    widgets.year_final_prod.date().year() + 1
                ) - widgets.year_initial_prod.date().year()

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
        )
        self.combo_boxes["progress"] = ldn.SummaryTableLDWidgets(
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
        Create a new progress period group box and add it to the layout.
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
        idx = len(self.combo_boxes)
        grp.setTitle(f"Progress period #{idx}")
        layout = QtWidgets.QVBoxLayout(grp)

        key = f"progress_{idx}"
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
            radio_lpd_te=dlg_instance.radio_lpd_te,
            radio_fao_wocat=dlg_instance.radio_fao_wocat,
        )
        self.combo_boxes[key].populate()

        layout.insertWidget(0, dlg_instance.combo_datasets_baseline)
        count = self.verticalLayout_progress.count()
        self.verticalLayout_progress.insertWidget(count - 1, grp)
        dlg_instance.advanced_configuration_progress.setTitle(
            f"Advanced (progress period) #{idx}"
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

            self.combo_boxes = dict(list(self.combo_boxes.items())[:2])
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
                    task_notes=self.options_tab.task_notes.toPlainText(),
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
                            task_name=self.options_tab.task_name.text(),
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
                            task_notes=self.options_tab.task_notes.toPlainText(),
                        ),
                    }
                )

        params = {
            "periods": periods,
            "task_name": self.options_tab.task_name.text(),
            "task_notes": self.options_tab.task_notes.toPlainText(),
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
