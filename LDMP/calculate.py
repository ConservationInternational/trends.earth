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
import typing
import uuid
from pathlib import Path
from typing import Optional

from osgeo import (
    gdal,
    ogr,
)
from PyQt5 import (
    QtCore,
    QtWidgets,
    uic,
)

import qgis.gui
import qgis.core
from qgis.utils import iface

from . import (
    GetTempFilename,
    areaofinterest,
    download,
    log,
    worker,
)
from .algorithms import models
from .conf import (
    REMOTE_DATASETS,
    Setting,
    settings_manager,
)
from .settings import DlgSettings

if settings_manager.get_value(Setting.BINARIES_ENABLED):
    try:
        from trends_earth_binaries.calculate_numba import *
        log("Using numba-compiled version of calculate_numba.")
    except (ModuleNotFoundError, ImportError) as e:
        from .calculate_numba import *
        log("Failed import of numba-compiled code, falling back to python version of calculate_numba.")
else:
    from LDMP.calculate_numba import *
    log("Using python version of calculate_numba.")

DlgCalculateUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculate.ui"))
DlgCalculateLDUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateLD.ui"))
DlgCalculateTCUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateTC.ui"))
DlgCalculateRestBiomassUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateRestBiomass.ui"))
DlgCalculateUrbanUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgCalculateUrban.ui"))
WidgetCalculationOptionsUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/WidgetCalculationOptions.ui"))
WidgetCalculationOutputUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/WidgetCalculationOutput.ui"))

mb = iface.messageBar()


class tr_calculate(object):
    def tr(message):
        return QtCore.QCoreApplication.translate("tr_calculate", message)


def get_script_slug(script_name):
    # Note that dots and underscores can't be used in the slugs, so they are 
    # replaced with dashesk
    return (script_name, script_name + '-' + scripts[script_name]['script version'].replace('.', '-'))


def get_script_group(script_name) -> Optional[str]:
    # get the configured name of the group that belongs the script
    group = None
    if (script_name in scripts) and ('group' in scripts[script_name]):
        group = scripts[script_name]['group']
    if not group:
        # check if it is a local script/process
        metadata = get_local_script_metadata(script_name)
        if not metadata:
            return None
        group = metadata.get('group', None)

    return group


def get_local_script_metadata(script_name) -> Optional[dict]:
    """Get a specific value from local_script dictionary.
    """
    # main key acess is the name of the local processing GUI class.
    metadata = local_scripts.get(script_name, None)
    if not metadata:
        # source value can be looked for into source value
        metadata = next((metadata for metadata in local_scripts.values() if metadata['source'] == script_name), None)

    return metadata


def is_local_script(script_name: str = None) -> bool:
    """check if the script name (aka source) is a local processed alg source.
    """
    if script_name in local_scripts:
        return True
    if next((metadata['source'] for metadata in local_scripts.values() if metadata['source'] == script_name), None):
        return True
    return False


# Transform CRS of a layer while optionally wrapping geometries
# across the 180th meridian
def transform_layer(l, crs_dst, datatype='polygon', wrap=False):
    log('Transforming layer from "{}" to "{}". Wrap is {}. Datatype is {}.'.format(l.crs().toProj(), crs_dst.toProj(), wrap, datatype))

    crs_src_string = l.crs().toProj()
    if wrap:
        if not l.crs().isGeographic():
            QtWidgets.QMessageBox.critical(None,tr_calculate.tr("Error"),
                   tr_calculate.tr("Error - layer is not in a geographic coordinate system. Cannot wrap layer across 180th meridian."))
            log('Can\'t wrap layer in non-geographic coordinate system: "{}"'.format(crs_src_string))
            return None
        crs_src_string = crs_src_string + ' +lon_wrap=180'
    crs_src = qgis.core.QgsCoordinateReferenceSystem()
    crs_src.createFromProj(crs_src_string)
    t = qgis.core.QgsCoordinateTransform(crs_src, crs_dst, qgis.core.QgsProject.instance())

    l_w = qgis.core.QgsVectorLayer(
        "{datatype}?crs=proj4:{crs}".format(datatype=datatype, crs=crs_dst.toProj()),
        "calculation boundary (transformed)",
        "memory"
    )
    feats = []
    for f in l.getFeatures():
        geom = f.geometry()
        if wrap:
            n = 0
            p = geom.vertexAt(n)
            # Note vertexAt returns QgsPointXY(0, 0) on error
            while p != qgis.core.QgsPointXY(0, 0):
                if p.x() < 0:
                    geom.moveVertex(p.x() + 360, p.y(), n)
                n += 1
                p = geom.vertexAt(n)
        geom.transform(t)
        f.setGeometry(geom)
        feats.append(f)
    l_w.dataProvider().addFeatures(feats)
    l_w.commitChanges()
    if not l_w.isValid():
        log('Error transforming layer from "{}" to "{}" (wrap is {})'.format(crs_src_string, crs_dst.toProj(), wrap))
        return None
    else:
        return l_w


def json_geom_to_geojson(txt):
    d = {'type': 'FeatureCollection',
         'features': [{'type': 'Feature',
                       'geometry': json.loads(txt)}]
         }
    return d


class DlgCalculate(QtWidgets.QDialog, DlgCalculateUi):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setupUi(self)

        self.dlg_calculate_ld = DlgCalculateLD()
        self.dlg_calculate_tc = DlgCalculateTC()
        self.dlg_calculate_rest_biomass = DlgCalculateRestBiomass()
        self.dlg_calculate_urban = DlgCalculateUrban()

        self.pushButton_ld.clicked.connect(self.btn_ld_clicked)
        self.pushButton_tc.clicked.connect(self.btn_tc_clicked)
        self.pushButton_rest_biomass.clicked.connect(self.btn_rest_biomass_clicked)
        self.pushButton_urban.clicked.connect(self.btn_urban_clicked)

    def btn_ld_clicked(self):
        self.close()
        result = self.dlg_calculate_ld.exec_()

    def btn_tc_clicked(self):
        self.close()
        result = self.dlg_calculate_tc.exec_()

    def btn_rest_biomass_clicked(self):
        self.close()
        result = self.dlg_calculate_rest_biomass.exec_()

    def btn_urban_clicked(self):
        self.close()
        result = self.dlg_calculate_urban.exec_()


class DlgCalculateLD(QtWidgets.QDialog, DlgCalculateLDUi):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setupUi(self)

        # TODO: Bad style - fix when refactoring
        from LDMP.calculate_prod import DlgCalculateProd
        from LDMP.calculate_lc import DlgCalculateLC
        from LDMP.calculate_soc import DlgCalculateSOC
        from LDMP.calculate_ldn import DlgCalculateOneStep, DlgCalculateLDNSummaryTableAdmin
        self.dlg_calculate_prod = DlgCalculateProd()
        self.dlg_calculate_lc = DlgCalculateLC()
        self.dlg_calculate_soc = DlgCalculateSOC()
        self.dlg_calculate_ldn_onestep = DlgCalculateOneStep()
        self.dlg_calculate_ldn_advanced = DlgCalculateLDNSummaryTableAdmin()

        self.btn_prod.clicked.connect(self.btn_prod_clicked)
        self.btn_lc.clicked.connect(self.btn_lc_clicked)
        self.btn_soc.clicked.connect(self.btn_soc_clicked)
        self.btn_sdg_onestep.clicked.connect(self.btn_sdg_onestep_clicked)
        self.btn_summary_single_polygon.clicked.connect(self.btn_summary_single_polygon_clicked)
        self.btn_summary_multi_polygons.clicked.connect(self.btn_summary_multi_polygons_clicked)

    def btn_prod_clicked(self):
        self.close()
        result = self.dlg_calculate_prod.exec_()

    def btn_lc_clicked(self):
        self.close()
        result = self.dlg_calculate_lc.exec_()

    def btn_soc_clicked(self):
        self.close()
        result = self.dlg_calculate_soc.exec_()

    def btn_sdg_onestep_clicked(self):
        self.close()
        result = self.dlg_calculate_ldn_onestep.exec_()

    def btn_summary_single_polygon_clicked(self):
        self.close()
        result = self.dlg_calculate_ldn_advanced.exec_()

    def btn_summary_multi_polygons_clicked(self):
        QtWidgets.QMessageBox.information(None, self.tr("Coming soon!"),
                                      self.tr("Multiple polygon summary table calculation coming soon!"))


class DlgCalculateTC(QtWidgets.QDialog, DlgCalculateTCUi):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setupUi(self)

        # TODO: Bad style - fix when refactoring
        from LDMP.calculate_tc import DlgCalculateTCData
        from LDMP.calculate_tc import DlgCalculateTCSummaryTable
        self.dlg_calculate_tc_data = DlgCalculateTCData()
        self.dlg_calculate_tc_summary = DlgCalculateTCSummaryTable()

        self.btn_calculate_carbon_change.clicked.connect(self.btn_calculate_carbon_change_clicked)
        self.btn_summary_single_polygon.clicked.connect(self.btn_summary_single_polygon_clicked)

    def btn_calculate_carbon_change_clicked(self):
        self.close()
        result = self.dlg_calculate_tc_data.exec_()

    def btn_summary_single_polygon_clicked(self):
        self.close()
        result = self.dlg_calculate_tc_summary.exec_()


class DlgCalculateRestBiomass(QtWidgets.QDialog, DlgCalculateRestBiomassUi):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setupUi(self)

        # TODO: Bad style - fix when refactoring
        from LDMP.calculate_rest_biomass import DlgCalculateRestBiomassData
        from LDMP.calculate_rest_biomass import DlgCalculateRestBiomassSummaryTable
        self.dlg_calculate_rest_biomass_data = DlgCalculateRestBiomassData()
        self.dlg_calculate_rest_biomass_summary = DlgCalculateRestBiomassSummaryTable()

        self.btn_calculate_rest_biomass_change.clicked.connect(self.btn_calculate_rest_biomass_change_clicked)
        self.btn_summary_single_polygon.clicked.connect(self.btn_summary_single_polygon_clicked)

    def btn_calculate_rest_biomass_change_clicked(self):
        self.close()
        result = self.dlg_calculate_rest_biomass_data.exec_()

    def btn_summary_single_polygon_clicked(self):
        self.close()
        result = self.dlg_calculate_rest_biomass_summary.exec_()


class DlgCalculateUrban(QtWidgets.QDialog, DlgCalculateUrbanUi):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setupUi(self)

        # TODO: Bad style - fix when refactoring
        from LDMP.calculate_urban import DlgCalculateUrbanData
        from LDMP.calculate_urban import DlgCalculateUrbanSummaryTable
        self.dlg_calculate_urban_data = DlgCalculateUrbanData()
        self.dlg_calculate_urban_summary = DlgCalculateUrbanSummaryTable()

        self.btn_calculate_urban_change.clicked.connect(self.btn_calculate_urban_change_clicked)
        self.btn_summary_single_polygon.clicked.connect(self.btn_summary_single_polygon_clicked)

    def btn_calculate_urban_change_clicked(self):
        self.close()
        result = self.dlg_calculate_urban_data.exec_()

    def btn_summary_single_polygon_clicked(self):
        self.close()
        result = self.dlg_calculate_urban_summary.exec_()


class CalculationOptionsWidget(QtWidgets.QWidget, WidgetCalculationOptionsUi):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.radioButton_run_in_cloud.toggled.connect(self.radioButton_run_in_cloud_changed)
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
            self.tr('Select folder containing data'),
            QtCore.QSettings().value("LDMP/localdata_dir", None)
        )
        if folder:
            if os.access(folder, os.R_OK):
                QtCore.QSettings().setValue("LDMP/localdata_dir", os.path.dirname(folder))
                self.lineEdit_local_data_folder.setText(folder)
                return True
            else:
                QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr(u"Cannot read {}. Choose a different folder.".format(folder)))
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
        super(CalculationOutputWidget, self).__init__(parent)

        self.output_suffixes = suffixes
        self.subclass_name = subclass_name

        self.setupUi(self)

        self.browse_output_basename.clicked.connect(self.select_output_basename)

    def select_output_basename(self):
        local_name = QtCore.QSettings().value("LDMP/output_basename_{}".format(self.subclass_name), None)
        if local_name:
            initial_path = local_name
        else:
            initial_path = QtCore.QSettings().value("LDMP/output_dir", None)


        f, _ = QtWidgets.QFileDialog.getSaveFileName(self,
                self.tr('Choose a prefix to be used when naming output files'),
                initial_path,
                self.tr('Base name (*)'))

        if f:
            if os.access(os.path.dirname(f), os.W_OK):
                QtCore.QSettings().setValue("LDMP/output_dir", os.path.dirname(f))
                QtCore.QSettings().setValue("LDMP/output_basename_{}".format(self.subclass_name), f)
                self.output_basename.setText(f)
                self.set_output_summary(f)
            else:
                QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr(u"Cannot write to {}. Choose a different file.".format(f)))

    def set_output_summary(self, f):
        out_files = [f + suffix for suffix in self.output_suffixes]
        self.output_summary.setText("\n".join(["{}"]*len(out_files)).format(*out_files))

    def check_overwrites(self):
        overwrites = []
        for suffix in self.output_suffixes: 
            if os.path.exists(self.output_basename.text() + suffix):
                overwrites.append(os.path.basename(self.output_basename.text() + suffix))

        if len(overwrites) > 0:
            resp = QtWidgets.QMessageBox.question(self,
                    self.tr('Overwrite file?'),
                    self.tr('Using the prefix "{}" would lead to overwriting existing file(s) {}. Do you want to overwrite these file(s)?'.format(
                        self.output_basename.text(),
                        ", ".join(["{}"]*len(overwrites)).format(*overwrites))),
                    QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No)
            if resp == QtWidgets.QMessageBox.No:
                QtWidgets.QMessageBox.information(None, self.tr("Information"),
                                           self.tr(u"Choose a different output prefix and try again."))
                return False

        return True


class CalculationHidedOutputWidget(QtWidgets.QWidget, WidgetCalculationOutputUi):
    process_id: uuid.UUID
    process_datetime: dt.datetime

    def __init__(self, suffixes, subclass_name, parent=None):
        super(CalculationHidedOutputWidget, self).__init__(parent)

        self.output_suffixes = suffixes
        self.subclass_name = subclass_name

        self.process_id = None
        self.process_datetime = None

        self.setupUi(self)
        self.hide()

    def set_output_summary(self, f):
        out_files = [f + suffix for suffix in self.output_suffixes]
        self.output_summary.setText("\n".join(["{}"]*len(out_files)).format(*out_files))

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
    script: models.ExecutionScript
    _has_output: bool
    _firstShowEvent: bool
    reset_tab_on_showEvent: bool
    _max_area: int = 5e7  # maximum size task the tool supports

    firstShowEvent = QtCore.pyqtSignal()

    def __init__(
            self,
            iface: qgis.gui.QgisInterface,
            script: models.ExecutionScript,
            parent: "MainWidget" = None
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
            raise ValueError('Admin boundaries not available')

        self.cities = download.get_cities()
        if not self.cities:
            raise ValueError('Cities list not available')

        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                               'data', 'scripts.json')) as script_file:
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
        ok_button = self.button_box.button(
            QtWidgets.QDialogButtonBox.Ok
        )
        ok_button.clicked.connect(self.btn_calculate)
        if self.script.run_mode == models.AlgorithmRunMode.REMOTE:
            ok_button.setText(self.tr("Schedule remote execution"))
        else:
            ok_button.setText(self.tr("Execute locally"))
        self.main_dock.cache_refresh_about_to_begin.connect(
            functools.partial(self.toggle_execution_button, False))
        self.main_dock.cache_refresh_finished.connect(
            functools.partial(self.toggle_execution_button, True))
        self.toggle_execution_button(not self.main_dock.refreshing_filesystem_cache)

        self.update_current_region()
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
        self.region_la.setText(self.tr(f"Current region: {region}"))

    def run_settings(self):
        dlg_settings = DlgSettings(parent=self)
        if dlg_settings.exec_():
            self.update_current_region()

    def showEvent(self, event):
        super(DlgCalculateBase, self).showEvent(event)

        if self._firstShowEvent:
            self._firstShowEvent = False
            self.firstShowEvent.emit()

    def firstShow(self):
        self.options_tab = CalculationOptionsWidget()
        self.options_tab.setParent(self)
        # By default show the local or cloud option
        self.options_tab.toggle_show_where_to_run(False)

    def btn_calculate(self):
        self.aoi = areaofinterest.prepare_area_of_interest(self._max_area)
        ret = self.aoi.bounding_box_gee_geojson()
        if not ret:
            QtWidgets.QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Unable to calculate bounding box.")
            )
            return False
        else:
            self.gee_bounding_box = ret

        if self._has_output:
            if not self.output_tab.output_basename.text():
                QtWidgets.QMessageBox.information(None, self.tr("Error"),
                                              self.tr("Choose an output base name."))
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

        json_file = GetTempFilename('.geojson')
        with open(json_file, 'w') as f:
            json.dump(self.geojson, f, separators=(',', ': '))

        gdal.UseExceptions()
        res = gdal.Warp(self.out_file, self.in_file, format='GTiff',
                        cutlineDSName=json_file, srcNodata=-32768, 
                        outputBounds=self.output_bounds,
                        dstNodata=-32767,
                        dstSRS="epsg:4326",
                        outputType=gdal.GDT_Int16,
                        resampleAlg=gdal.GRA_NearestNeighbour,
                        creationOptions=['COMPRESS=LZW'],
                        callback=self.progress_callback)
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


class MaskWorker(worker.AbstractWorker):
    def __init__(self, out_file, geojson, model_file=None):
        worker.AbstractWorker.__init__(self)

        self.out_file = out_file
        self.geojson = geojson
        self.model_file = model_file

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)


        json_file = GetTempFilename('.geojson')
        with open(json_file, 'w') as f:
            json.dump(self.geojson, f, separators=(',', ': '))

        gdal.UseExceptions()

        if self.model_file:
            # Assumes an image with no rotation
            gt = gdal.Info(self.model_file, format='json')['geoTransform']
            x_size, y_size= gdal.Info(self.model_file, format='json')['size']
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

        res = gdal.Rasterize(self.out_file, json_file, format='GTiff',
                             outputBounds=output_bounds,
                             initValues=-32767, # Areas that are masked out
                             burnValues=1, # Areas that are NOT masked out
                             xRes=x_res,
                             yRes=y_res,
                             outputSRS="epsg:4326",
                             outputType=gdal.GDT_Int16,
                             creationOptions=['COMPRESS=LZW'],
                             callback=self.progress_callback)
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
