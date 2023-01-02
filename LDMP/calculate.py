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
import datetime as dt
import functools
import json
import os
import typing
import uuid
from pathlib import Path
from typing import Optional

import qgis.core
import qgis.gui
from osgeo import gdal
from qgis.PyQt import QtCore
from qgis.PyQt import QtGui
from qgis.PyQt import QtWidgets
from qgis.PyQt import uic
from te_schemas.algorithms import AlgorithmRunMode
from te_schemas.algorithms import ExecutionScript

from . import areaofinterest
from . import download
from . import GetTempFilename
from . import worker
from .conf import AreaSetting
from .conf import OPTIONS_TITLE
from .conf import REMOTE_DATASETS
from .conf import Setting
from .conf import settings_crs
from .conf import settings_manager
from .logger import log


DlgCalculateUi, _ = uic.loadUiType(str(Path(__file__).parent / "gui/DlgCalculate.ui"))
DlgCalculateTCUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateTC.ui")
)
DlgCalculateRestBiomassUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateRestBiomass.ui")
)
DlgCalculateUrbanUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateUrban.ui")
)
WidgetCalculationOptionsUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/WidgetCalculationOptions.ui")
)
WidgetCalculationOutputUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/WidgetCalculationOutput.ui")
)


class tr_calculate:
    def tr(message):
        return QtCore.QCoreApplication.translate("tr_calculate", message)


ICON_PATH = os.path.join(os.path.dirname(__file__), "icons")


def json_geom_to_geojson(txt):
    d = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": json.loads(txt)}],
    }

    return d


class DlgCalculate(QtWidgets.QDialog, DlgCalculateUi):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setupUi(self)

        self.dlg_calculate_tc = DlgCalculateTC()
        self.dlg_calculate_rest_biomass = DlgCalculateRestBiomass()
        self.dlg_calculate_urban = DlgCalculateUrban()

        self.pushButton_ld.clicked.connect(self.btn_ld_clicked)
        self.pushButton_tc.clicked.connect(self.btn_tc_clicked)
        self.pushButton_rest_biomass.clicked.connect(self.btn_rest_biomass_clicked)
        self.pushButton_urban.clicked.connect(self.btn_urban_clicked)

    def btn_ld_clicked(self):
        self.close()
        self.dlg_calculate_ld.exec_()

    def btn_tc_clicked(self):
        self.close()
        self.dlg_calculate_tc.exec_()

    def btn_rest_biomass_clicked(self):
        self.close()
        self.dlg_calculate_rest_biomass.exec_()

    def btn_urban_clicked(self):
        self.close()
        self.dlg_calculate_urban.exec_()


class DlgCalculateTC(QtWidgets.QDialog, DlgCalculateTCUi):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setupUi(self)

        # TODO: Bad style - fix when refactoring
        from LDMP.calculate_tc import DlgCalculateTCData
        from LDMP.calculate_tc import DlgCalculateTCSummaryTable

        self.dlg_calculate_tc_data = DlgCalculateTCData()
        self.dlg_calculate_tc_summary = DlgCalculateTCSummaryTable()

        self.btn_calculate_carbon_change.clicked.connect(
            self.btn_calculate_carbon_change_clicked
        )
        self.btn_summary_single_polygon.clicked.connect(
            self.btn_summary_single_polygon_clicked
        )

    def btn_calculate_carbon_change_clicked(self):
        self.close()
        self.dlg_calculate_tc_data.exec_()

    def btn_summary_single_polygon_clicked(self):
        self.close()
        self.dlg_calculate_tc_summary.exec_()


class DlgCalculateRestBiomass(QtWidgets.QDialog, DlgCalculateRestBiomassUi):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setupUi(self)

        # TODO: Bad style - fix when refactoring
        from LDMP.calculate_rest_biomass import DlgCalculateRestBiomassData
        from LDMP.calculate_rest_biomass import DlgCalculateRestBiomassSummaryTable

        self.dlg_calculate_rest_biomass_data = DlgCalculateRestBiomassData()
        self.dlg_calculate_rest_biomass_summary = DlgCalculateRestBiomassSummaryTable()

        self.btn_calculate_rest_biomass_change.clicked.connect(
            self.btn_calculate_rest_biomass_change_clicked
        )
        self.btn_summary_single_polygon.clicked.connect(
            self.btn_summary_single_polygon_clicked
        )

    def btn_calculate_rest_biomass_change_clicked(self):
        self.close()
        self.dlg_calculate_rest_biomass_data.exec_()

    def btn_summary_single_polygon_clicked(self):
        self.close()
        self.dlg_calculate_rest_biomass_summary.exec_()


class DlgCalculateUrban(QtWidgets.QDialog, DlgCalculateUrbanUi):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setupUi(self)

        # TODO: Bad style - fix when refactoring
        from LDMP.calculate_urban import DlgCalculateUrbanData
        from LDMP.calculate_urban import DlgCalculateUrbanSummaryTable

        self.dlg_calculate_urban_data = DlgCalculateUrbanData()
        self.dlg_calculate_urban_summary = DlgCalculateUrbanSummaryTable()

        self.btn_calculate_urban_change.clicked.connect(
            self.btn_calculate_urban_change_clicked
        )
        self.btn_summary_single_polygon.clicked.connect(
            self.btn_summary_single_polygon_clicked
        )

    def btn_calculate_urban_change_clicked(self):
        self.close()
        self.dlg_calculate_urban_data.exec_()

    def btn_summary_single_polygon_clicked(self):
        self.close()
        self.dlg_calculate_urban_summary.exec_()


class CalculationOptionsWidget(QtWidgets.QWidget, WidgetCalculationOptionsUi):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.radioButton_run_in_cloud.toggled.connect(
            self.radioButton_run_in_cloud_changed
        )
        self.btn_local_data_folder_browse.clicked.connect(self.open_folder_browse)

    def showEvent(self, event):
        super().showEvent(event)

        local_data_folder = QtCore.QSettings().value("LDMP/localdata_dir", None)

        if local_data_folder and os.access(local_data_folder, os.R_OK):
            self.lineEdit_local_data_folder.setText(local_data_folder)
        else:
            self.lineEdit_local_data_folder.setText(None)
        self.task_name.setText("")
        self.task_notes.setText("")

    def radioButton_run_in_cloud_changed(self):
        if self.radioButton_run_in_cloud.isChecked():
            self.lineEdit_local_data_folder.setEnabled(False)
            self.btn_local_data_folder_browse.setEnabled(False)
        else:
            self.lineEdit_local_data_folder.setEnabled(True)
            self.btn_local_data_folder_browse.setEnabled(True)

    def open_folder_browse(self):
        self.lineEdit_local_data_folder.clear()

        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            tr_calculate.tr("Select folder containing data"),
            QtCore.QSettings().value("LDMP/localdata_dir", None),
        )

        if folder:
            if os.access(folder, os.R_OK):
                QtCore.QSettings().setValue(
                    "LDMP/localdata_dir", os.path.dirname(folder)
                )
                self.lineEdit_local_data_folder.setText(folder)

                return True
            else:
                QtWidgets.QMessageBox.critical(
                    None,
                    tr_calculate.tr("Error"),
                    tr_calculate.tr(
                        "Cannot read {}. Choose a different folder.".format(folder)
                    ),
                )

                return False
        else:
            return False

    def toggle_show_where_to_run(self, enable):
        if enable:
            self.where_to_run_enabled = True
            self.groupBox_where_to_run.show()
        else:
            self.where_to_run_enabled = False
            self.groupBox_where_to_run.hide()


class CalculationOutputWidget(QtWidgets.QWidget, WidgetCalculationOutputUi):
    def __init__(self, suffixes, subclass_name, parent=None):
        super().__init__(parent)

        self.output_suffixes = suffixes
        self.subclass_name = subclass_name

        self.setupUi(self)

        self.browse_output_basename.clicked.connect(self.select_output_basename)

    def select_output_basename(self):
        local_name = QtCore.QSettings().value(
            "LDMP/output_basename_{}".format(self.subclass_name), None
        )

        if local_name:
            initial_path = local_name
        else:
            initial_path = QtCore.QSettings().value("LDMP/output_dir", None)

        f, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            tr_calculate.tr("Choose a prefix to be used when naming output files"),
            initial_path,
            tr_calculate.tr("Base name (*)"),
        )

        if f:
            if os.access(os.path.dirname(f), os.W_OK):
                QtCore.QSettings().setValue("LDMP/output_dir", os.path.dirname(f))
                QtCore.QSettings().setValue(
                    "LDMP/output_basename_{}".format(self.subclass_name), f
                )
                self.output_basename.setText(f)
                self.set_output_summary(f)
            else:
                QtWidgets.QMessageBox.critical(
                    None,
                    tr_calculate.tr("Error"),
                    tr_calculate.tr(
                        "Cannot write to {}. Choose a different file.".format(f)
                    ),
                )

    def set_output_summary(self, f):
        out_files = [f + suffix for suffix in self.output_suffixes]
        self.output_summary.setText(
            "\n".join(["{}"] * len(out_files)).format(*out_files)
        )

    def check_overwrites(self):
        overwrites = []

        for suffix in self.output_suffixes:
            if os.path.exists(self.output_basename.text() + suffix):
                overwrites.append(
                    os.path.basename(self.output_basename.text() + suffix)
                )

        if len(overwrites) > 0:
            resp = QtWidgets.QMessageBox.question(
                self,
                tr_calculate.tr("Overwrite file?"),
                tr_calculate.tr(
                    'Using the prefix "{}" would lead to overwriting existing file(s) {}. Do you want to overwrite these file(s)?'.format(
                        self.output_basename.text(),
                        ", ".join(["{}"] * len(overwrites)).format(*overwrites),
                    )
                ),
                QtWidgets.QMessageBox.Yes,
                QtWidgets.QMessageBox.No,
            )

            if resp == QtWidgets.QMessageBox.No:
                QtWidgets.QMessageBox.information(
                    None,
                    tr_calculate.tr("Information"),
                    tr_calculate.tr("Choose a different output prefix and try again."),
                )

                return False

        return True


class CalculationHidedOutputWidget(QtWidgets.QWidget, WidgetCalculationOutputUi):
    process_id: uuid.UUID
    process_datetime: dt.datetime

    def __init__(self, suffixes, subclass_name, parent=None):
        super().__init__(parent)

        self.output_suffixes = suffixes
        self.subclass_name = subclass_name

        self.process_id = None
        self.process_datetime = None

        self.setupUi(self)
        self.hide()

    def set_output_summary(self, f):
        out_files = [f + suffix for suffix in self.output_suffixes]
        self.output_summary.setText(
            "\n".join(["{}"] * len(out_files)).format(*out_files)
        )

    def check_overwrites(self):
        """Method maintained only for retro compatibility with old code. Overwrite can't happen because
        filename is choosed randomly.
        """

        return True


class DlgCalculateBase(QtWidgets.QDialog):
    """Base class for individual indicator calculate dialogs"""

    LOCAL_SCRIPT_NAME: str = ""

    admin_bounds_key: typing.Dict[str, download.Country]
    aoi: areaofinterest.AOI
    button_box: QtWidgets.QDialogButtonBox
    canvas: qgis.gui.QgsMapCanvas
    cities: typing.Dict[str, typing.Dict[str, download.City]]
    datasets: typing.Dict[str, typing.Dict]
    iface: qgis.gui.QgisInterface
    main_dock: "MainWidget"
    script: ExecutionScript
    _has_output: bool
    _firstShowEvent: bool
    reset_tab_on_showEvent: bool

    firstShowEvent: QtCore.pyqtSignal = QtCore.pyqtSignal()
    changed_region: QtCore.pyqtSignal = QtCore.pyqtSignal()

    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        script: ExecutionScript,
        parent: "MainWidget" = None,
    ):
        super().__init__(parent)
        self.iface = iface
        self.main_dock = parent
        self.script = script
        self.mb = iface.messageBar()
        self._has_output = False
        self._firstShowEvent = True
        self.reset_tab_on_showEvent = True
        self.canvas = iface.mapCanvas()
        self.settings = qgis.core.QgsSettings()

        self.admin_bounds_key = download.get_admin_bounds()

        if not self.admin_bounds_key:
            raise ValueError("Admin boundaries not available")

        self.cities = download.get_cities()

        if not self.cities:
            raise ValueError("Cities list not available")

        with open(
            os.path.join(
                os.path.dirname(os.path.realpath(__file__)), "data", "scripts.json"
            )
        ) as script_file:
            self.scripts = json.load(script_file)

        self.datasets = REMOTE_DATASETS
        self.firstShowEvent.connect(self.firstShow)

    def toggle_execution_button(self, enabled: bool):
        submit_button = self.button_box.button(self.button_box.Ok)
        submit_button.setEnabled(enabled)

    def splitter_toggled(self):
        if self.splitter_collapsed:
            self.splitter.restoreState(self.splitter_state)
            self.collapse_button.setArrowType(QtCore.Qt.RightArrow)
        else:
            self.splitter_state = self.splitter.saveState()
            self.splitter.setSizes([1, 0])
            self.collapse_button.setArrowType(QtCore.Qt.LeftArrow)
        self.splitter_collapsed = not self.splitter_collapsed

    def _finish_initialization(self):

        cancel_btn = self.button_box.button(QtWidgets.QDialogButtonBox.Cancel)
        cancel_btn.clicked.connect(self.reject)
        ok_button = self.button_box.button(QtWidgets.QDialogButtonBox.Ok)
        ok_button.clicked.connect(self.btn_calculate)

        if self.script.run_mode == AlgorithmRunMode.REMOTE:
            ok_button.setText(tr_calculate.tr("Schedule remote execution"))
        else:
            ok_button.setText(tr_calculate.tr("Execute locally"))
        self.main_dock.cache_refresh_about_to_begin.connect(
            functools.partial(self.toggle_execution_button, False)
        )
        self.main_dock.cache_refresh_finished.connect(
            functools.partial(self.toggle_execution_button, True)
        )
        self.toggle_execution_button(not self.main_dock.refreshing_filesystem_cache)

        self.update_current_region()
        self.region_button.setIcon(QtGui.QIcon(os.path.join(ICON_PATH, "wrench.svg")))
        self.region_button.clicked.connect(self.run_settings)

        # adding a collapsible arrow on the splitter
        self.splitter.setCollapsible(0, False)
        splitter_handle = self.splitter.handle(1)
        handle_layout = QtWidgets.QVBoxLayout()
        handle_layout.setContentsMargins(0, 0, 0, 0)
        self.collapse_button = QtWidgets.QToolButton(splitter_handle)
        self.collapse_button.setAutoRaise(True)
        self.collapse_button.setFixedSize(12, 12)
        self.collapse_button.setCursor(QtCore.Qt.ArrowCursor)
        handle_layout.addWidget(self.collapse_button)

        handle_layout.addStretch()
        splitter_handle.setLayout(handle_layout)

        arrow_type = QtCore.Qt.RightArrow
        self.collapse_button.setArrowType(arrow_type)
        self.collapse_button.clicked.connect(self.splitter_toggled)
        self.splitter_collapsed = False

        qgis.gui.QgsGui.enableAutoGeometryRestore(self)
        self.splitter.setStretchFactor(0, 10)

    def update_current_region(self):
        region = settings_manager.get_value(Setting.AREA_NAME)
        self.region_la.setText(tr_calculate.tr(f"Current region: {region}"))
        self.changed_region.emit()

    def run_settings(self):
        self.iface.showOptionsDialog(
            self.iface.mainWindow(),
            currentPage=OPTIONS_TITLE
        )
        self.update_current_region()

    def showEvent(self, event):
        super().showEvent(event)

        if self._firstShowEvent:
            self._firstShowEvent = False
            self.firstShowEvent.emit()

    def firstShow(self):
        self.options_tab = CalculationOptionsWidget()
        self.options_tab.setParent(self)
        # By default show the local or cloud option
        self.options_tab.toggle_show_where_to_run(False)

    def accept(self):
        pass

    def settings_btn_clicked(self):
        self.iface.showOptionsDialog(
            self.iface.mainWindow(),
            currentPage=OPTIONS_TITLE
        )

    def _validate_crs_multi_layer(self, layer_defn: list) -> bool:
        """
        Compares the CRS of the layer(s) in the given definition against
        the one defined for datasets in settings.
        Each item in 'layer_defn' should a tuple containing the QgsMapLayer
        subclass and the corresponding friendly name to display in the user
        message.
        """
        is_valid = True
        dt_crs = settings_crs()
        settings_crs_description = self._crs_description(dt_crs)
        msgs = []
        for ld in layer_defn:
            if not ld[0]:
                continue
            lyr_crs = ld[0].crs()
            layer_name = ld[1]
            if lyr_crs != dt_crs:
                crs_description = self._crs_description(lyr_crs)
                tr_msg = tr_calculate.tr(
                    f"CRS for {layer_name} ({crs_description}) does not match "
                    f"the one defined in settings "
                    f"({settings_crs_description})"
                )
                msgs.append(tr_msg)

        num_msg = len(msgs)
        if num_msg > 0:
            is_valid = False
            if num_msg == 1:
                msg = msgs[0]
            else:
                s = "\n- ".join(msgs)
                msg = f"- {s}"
            QtWidgets.QMessageBox.critical(
                self,
                tr_calculate.tr("CRS Error"),
                msg
            )

        return is_valid

    @classmethod
    def _crs_description(cls, crs) -> str:
        if not crs:
            return cls.tr_calculate.tr("Not defined")

        return crs.userFriendlyIdentifier()

    def btn_calculate(self):
        area_method = settings_manager.get_value(Setting.AREA_FROM_OPTION)
        has_buffer = settings_manager.get_value(Setting.BUFFER_CHECKED)
        if (
            area_method == AreaSetting.POINT.value
            or area_method == AreaSetting.COUNTRY_CITY.value
        ) and not has_buffer:
            QtWidgets.QMessageBox.critical(
                None,
                tr_calculate.tr("Error"),
                tr_calculate.tr(
                    "You have chosen to run this calculation on a point "
                    "(or for a city). To run this tool on a point you "
                    "must also select a buffer. This can be done in the Trends.Earth settings."
                ),
            )

            return False

        self.aoi = areaofinterest.prepare_area_of_interest()
        ret = self.aoi.bounding_box_gee_geojson()

        if not ret:
            QtWidgets.QMessageBox.critical(
                None,
                tr_calculate.tr("Error"),
                tr_calculate.tr("Unable to calculate bounding box."),
            )

            return False
        else:
            self.gee_bounding_box = ret

        if self._has_output:
            if not self.output_tab.output_basename.text():
                QtWidgets.QMessageBox.information(
                    None,
                    tr_calculate.tr("Error"),
                    tr_calculate.tr("Choose an output base name."),
                )

                return False

            # Check if the chosen basename would lead to an  overwrite(s):
            ret = self.output_tab.check_overwrites()

            if not ret:
                return False

        return True


class ClipWorker(worker.AbstractWorker):
    def __init__(self, in_file, out_file, geojson, output_bounds=None):
        worker.AbstractWorker.__init__(self)

        self.in_file = in_file
        self.out_file = out_file
        self.output_bounds = output_bounds

        self.geojson = geojson

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        json_file = GetTempFilename(".geojson")
        with open(json_file, "w") as f:
            json.dump(self.geojson, f, separators=(",", ": "))

        gdal.UseExceptions()
        res = gdal.Warp(
            self.out_file,
            self.in_file,
            format="GTiff",
            cutlineDSName=json_file,
            srcNodata=-32768,
            outputBounds=self.output_bounds,
            dstNodata=-32767,
            dstSRS="epsg:4326",
            outputType=gdal.GDT_Int16,
            resampleAlg=gdal.GRA_NearestNeighbour,
            warpOptions=[
                "NUM_THREADS=ALL_CPUs",
                "GDAL_CACHEMAX=500",
            ],
            creationOptions=[
                "COMPRESS=LZW",
                "NUM_THREADS=ALL_CPUs",
                "GDAL_NUM_THREADS=ALL_CPUs",
                "TILED=YES",
            ],
            multithread=True,
            warpMemoryLimit=500,
            callback=self.progress_callback,
        )
        os.remove(json_file)

        if res:
            return True
        else:
            return None

    def progress_callback(self, fraction, message, data):
        if self.killed:
            return False
        else:
            self.progress.emit(100 * fraction)

            return True


class WarpWorker(worker.AbstractWorker):
    """Used as a substitute for gdal translate given warp is multithreaded"""

    def __init__(self, in_file, out_file):
        worker.AbstractWorker.__init__(self)

        self.in_file = in_file
        self.out_file = out_file

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        gdal.UseExceptions()

        res = gdal.Warp(
            self.out_file,
            self.in_file,
            format="GTiff",
            srcNodata=-32768,
            outputType=gdal.GDT_Int16,
            resampleAlg=gdal.GRA_NearestNeighbour,
            warpOptions=[
                "NUM_THREADS=ALL_CPUs",
                "GDAL_CACHEMAX=500",
            ],
            creationOptions=[
                "COMPRESS=LZW",
                "BIGTIFF=YES",
                "NUM_THREADS=ALL_CPUs",
                "GDAL_NUM_THREADS=ALL_CPUs",
                "TILED=YES",
            ],
            multithread=True,
            warpMemoryLimit=500,
            callback=self.progress_callback,
        )

        if res:
            return True
        else:
            return None

    def progress_callback(self, fraction, message, data):
        if self.killed:
            return False
        else:
            self.progress.emit(100 * fraction)

            return True


class MaskWorker(worker.AbstractWorker):
    def __init__(self, out_file, geojson, model_file=None):
        worker.AbstractWorker.__init__(self)

        self.out_file = out_file
        self.geojson = geojson
        self.model_file = model_file

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        json_file = GetTempFilename(".geojson")
        with open(json_file, "w") as f:
            json.dump(self.geojson, f, separators=(",", ": "))

        gdal.UseExceptions()

        if self.model_file:
            # Assumes an image with no rotation
            gt = gdal.Info(self.model_file, format="json")["geoTransform"]
            x_size, y_size = gdal.Info(self.model_file, format="json")["size"]
            x_min = min(gt[0], gt[0] + x_size * gt[1])
            x_max = max(gt[0], gt[0] + x_size * gt[1])
            y_min = min(gt[3], gt[3] + y_size * gt[5])
            y_max = max(gt[3], gt[3] + y_size * gt[5])
            output_bounds = [x_min, y_min, x_max, y_max]
            x_res = gt[1]
            y_res = gt[5]
        else:
            output_bounds = None
            x_res = None
            y_res = None

        res = gdal.Rasterize(
            self.out_file,
            json_file,
            format="GTiff",
            outputBounds=output_bounds,
            initValues=-32767,  # Areas that are masked out
            burnValues=1,  # Areas that are NOT masked out
            xRes=x_res,
            yRes=y_res,
            outputSRS="epsg:4326",
            outputType=gdal.GDT_Int16,
            creationOptions=["COMPRESS=LZW"],
            callback=self.progress_callback,
        )
        os.remove(json_file)

        if res:
            return True
        else:
            return None

    def progress_callback(self, fraction, message, data):
        if self.killed:
            return False
        else:
            self.progress.emit(100 * fraction)

            return True


class TranslateWorker(worker.AbstractWorker):
    def __init__(self, out_file, in_file):
        worker.AbstractWorker.__init__(self)

        self.out_file = out_file
        self.in_file = in_file

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        gdal.UseExceptions()

        res = gdal.Translate(
            self.out_file,
            self.in_file,
            creationOptions=["COMPRESS=LZW"],
            callback=self.progress_callback,
        )

        if res:
            return True
        else:
            return None

    def progress_callback(self, fraction, message, data):
        if self.killed:
            return False
        else:
            self.progress.emit(100 * fraction)

            return True
