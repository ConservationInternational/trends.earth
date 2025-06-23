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

import dataclasses
import functools
import json
import os
import typing
import uuid
from pathlib import Path

import numpy as np
import qgis.core
import qgis.gui
import qgis.utils
import te_algorithms.gdal.land_deg.config as ld_conf
from osgeo import gdal, osr
from qgis.PyQt import QtCore, QtWidgets, uic
from qgis.PyQt.QtCore import QSettings
from te_schemas.jobs import JobStatus
from te_schemas.results import Band as JobBand
from te_schemas.results import RasterType, ResultType

from . import (
    GetTempFilename,
    areaofinterest,
    conf,
    layers,
    metadata,
    metadata_dialog,
    utils,
    worker,
)
from .areaofinterest import prepare_area_of_interest
from .jobs.manager import job_manager, set_results_extents, update_uris_if_needed
from .jobs.models import Job
from .logger import log
from .region_selector import RegionSelector

Ui_DlgDataIOLoadTE, _ = uic.loadUiType(
    str(Path(__file__).parents[0] / "gui/DlgDataIOLoadTE.ui")
)
Ui_DlgDataIOImportSOC, _ = uic.loadUiType(
    str(Path(__file__).parents[0] / "gui/DlgDataIOImportSOC.ui")
)
Ui_DlgDataIOImportPopulation, _ = uic.loadUiType(
    str(Path(__file__).parents[0] / "gui/DlgDataIOImportPopulation.ui")
)
Ui_DlgDataIOImportProd, _ = uic.loadUiType(
    str(Path(__file__).parents[0] / "gui/DlgDataIOImportProd.ui")
)
Ui_DlgDataIOAddLayersToMap, _ = uic.loadUiType(
    str(Path(__file__).parents[0] / "gui/DlgDataIOAddLayersToMap.ui")
)
Ui_DlgJobsDetails, _ = uic.loadUiType(
    str(Path(__file__).parents[0] / "gui/DlgJobsDetails.ui")
)
Ui_WidgetDataIOImportSelectFileInput, _ = uic.loadUiType(
    str(Path(__file__).parents[0] / "gui/WidgetDataIOImportSelectFileInput.ui")
)
Ui_WidgetDataIOImportSelectRasterOutput, _ = uic.loadUiType(
    str(Path(__file__).parents[0] / "gui/WidgetDataIOImportSelectRasterOutput.ui")
)
Ui_WidgetDataIOSelectTELayerExisting, _ = uic.loadUiType(
    str(Path(__file__).parents[0] / "gui/WidgetDataIOSelectTELayerExisting.ui")
)
Ui_WidgetDataIOSelectTELayerImport, _ = uic.loadUiType(
    str(Path(__file__).parents[0] / "gui/WidgetDataIOSelectTELayerImport.ui")
)
Ui_WidgetDataIOSelectTEDatasetExisting, _ = uic.loadUiType(
    str(Path(__file__).parents[0] / "gui/WidgetDataIOSelectTEDatasetExisting.ui")
)


class tr_data_io:
    def tr(message):
        return QtCore.QCoreApplication.translate("tr_data_io", message)


@dataclasses.dataclass()
class Band:
    job: Job
    path: Path
    band_index: int
    band_info: JobBand

    def get_name_info(self):
        if self.job.task_name:
            name_info_parts = [self.job.task_name]
        else:
            name_info_parts = []
        name_info_parts.extend(
            [
                self.job.local_context.area_of_interest_name,
                layers.get_band_title(JobBand.Schema().dump(self.band_info)),
                utils.utc_to_local(self.job.start_date).strftime("%Y-%m-%d %H:%M"),
            ]
        )

        return " - ".join(name_info_parts)

    def get_hover_info(self):
        if self.job.task_name:
            hover_info_parts = [self.job.task_name]
        else:
            hover_info_parts = []
        hover_info_parts.extend(
            [
                self.job.local_context.area_of_interest_name + "\n",
                layers.get_band_title(JobBand.Schema().dump(self.band_info)) + "\n",
                utils.utc_to_local(self.job.start_date).strftime("%Y-%m-%d %H:%M")
                + "\n",
                # TODO: figure out a way to cleanup the metadata so it is
                # presentable and useful - likely need to have each script
                # contain a dictionary of metadata fields that should be
                # shown to the user by default
            ]
        )


@dataclasses.dataclass()
class Dataset:
    job: Job
    path: Path

    def get_name_info(self):
        name_info_parts = []
        name_info_parts.extend(
            [
                self.job.local_context.area_of_interest_name,
                self.job.visible_name,
                utils.utc_to_local(self.job.start_date).strftime("%Y-%m-%d %H:%M"),
            ]
        )

        return " - ".join(name_info_parts)

    def get_hover_info(self):
        hover_info_parts = []
        hover_info_parts.extend(
            [
                self.job.visible_name + " - ",
                self.job.local_context.area_of_interest_name + "\n",
                utils.utc_to_local(self.job.start_date).strftime("%Y-%m-%d %H:%M"),
            ]
        )

        return "".join(hover_info_parts)


class RemapVectorWorker(worker.AbstractWorker):
    def __init__(
        self,
        layer,
        out_file,
        attribute,
        remap_dict,
        in_data_type,
        out_res,
        out_data_type=gdal.GDT_Int16,
        output_bounds=None,
    ):
        worker.AbstractWorker.__init__(self)

        self.l = layer
        self.out_file = out_file
        self.attribute = attribute
        self.remap_dict = remap_dict
        self.in_data_type = in_data_type
        self.out_res = out_res
        self.out_data_type = out_data_type
        self.output_bounds = output_bounds

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        crs_src_string = self.l.crs().toProj()
        crs_src = qgis.core.QgsCoordinateReferenceSystem()
        crs_src.createFromProj(crs_src_string)
        crs_dst = qgis.core.QgsCoordinateReferenceSystem("epsg:4326")
        t = qgis.core.QgsCoordinateTransform(
            crs_src, crs_dst, qgis.core.QgsProject.instance()
        )

        l_out = qgis.core.QgsVectorLayer(
            "{datatype}?crs=proj4:{crs}".format(
                datatype=self.in_data_type, crs=crs_dst.toProj()
            ),
            "land cover (transformed)",
            "memory",
        )
        l_out.dataProvider().addAttributes(
            [qgis.core.QgsField("code", QtCore.QVariant.Int)]
        )
        l_out.updateFields()

        feats = []
        n = 1

        for f in self.l.getFeatures():
            if self.killed:
                log("Processing killed by user while remapping vector")

                return None
            geom = f.geometry()
            geom.transform(t)
            new_f = qgis.core.QgsFeature()
            new_f.setGeometry(geom)
            new_f.setAttributes([self.remap_dict[f.attribute(self.attribute)]])
            feats.append(new_f)
            n += 1
            # Commit the changes every 5% of the way through the length of the
            # features

            if n > (self.l.featureCount() / 20):
                l_out.dataProvider().addFeatures(feats)
                l_out.commitChanges()
                # Note there will be two progress bars that will fill to 100%,
                # first one for this loop, and then another for rasterize, both
                # with the same title.
                self.progress.emit(100 * float(n) / self.l.featureCount())
                feats = []

        if not l_out.isValid():
            log(
                'Error remapping and transforming vector layer from "{}" to "{}")'.format(
                    crs_src_string, crs_dst.toProj()
                )
            )

            return None

        # Write l_out to a shapefile for usage by gdal rasterize
        temp_shp = GetTempFilename(".shp")
        log("Writing temporary shapefile to {}".format(temp_shp))
        err = qgis.core.QgsVectorFileWriter.writeAsVectorFormat(
            l_out, temp_shp, "UTF-8", crs_dst, "ESRI Shapefile"
        )

        if err != qgis.core.QgsVectorFileWriter.NoError:
            log("Error writing layer to {}".format(temp_shp))

            return None

        log("Rasterizing...")
        res = gdal.Rasterize(
            self.out_file,
            temp_shp,
            format="GTiff",
            xRes=self.out_res,
            yRes=-self.out_res,
            noData=-32768,
            attribute="code",
            outputSRS="epsg:4326",
            outputType=self.out_data_type,
            creationOptions=["COMPRESS=LZW"],
            outputBounds=self.output_bounds,
            callback=self.progress_callback,
        )
        os.remove(temp_shp)

        if res:
            return True
        else:
            return None

    def progress_callback(self, fraction, message=None, data=None):
        if self.killed:
            return False
        else:
            self.progress.emit(100 * fraction)

            return True


class RasterizeWorker(worker.AbstractWorker):
    def __init__(
        self, in_file, out_file, out_res, attribute, out_data_type=gdal.GDT_Int16
    ):
        worker.AbstractWorker.__init__(self)

        self.in_file = in_file
        self.out_file = out_file

        self.out_res = out_res
        self.out_data_type = out_data_type
        self.attribute = attribute

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        res = gdal.Rasterize(
            self.out_file,
            self.in_file,
            format="GTiff",
            xRes=self.out_res,
            yRes=-self.out_res,
            noData=-32768,
            attribute=self.attribute,
            outputSRS="epsg:4326",
            outputType=self.out_data_type,
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


class RasterImportWorker(worker.AbstractWorker):
    def __init__(
        self, in_file, out_file, out_res, resample_mode, out_data_type=gdal.GDT_Byte
    ):
        worker.AbstractWorker.__init__(self)

        self.in_file = in_file
        self.out_file = out_file
        self.out_res = out_res
        self.resample_mode = resample_mode
        self.out_data_type = out_data_type

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        if self.out_res:
            res = gdal.Warp(
                self.out_file,
                self.in_file,
                format="GTiff",
                xRes=self.out_res,
                yRes=-self.out_res,
                dstNodata=-32768,
                dstSRS="epsg:4326",
                outputType=self.out_data_type,
                resampleAlg=self.resample_mode,
                creationOptions=["COMPRESS=LZW", "NUM_THREADS=ALL_CPUS"],
                callback=self.progress_callback,
            )
        else:
            res = gdal.Warp(
                self.out_file,
                self.in_file,
                format="GTiff",
                dstNodata=-32768,
                dstSRS="epsg:4326",
                outputType=self.out_data_type,
                resampleAlg=self.resample_mode,
                creationOptions=["COMPRESS=LZW", "NUM_THREADS=ALL_CPUS"],
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


class RemapRasterWorker(worker.AbstractWorker):
    def __init__(self, in_file, out_file, remap_list):
        worker.AbstractWorker.__init__(self)

        self.in_file = in_file
        self.out_file = out_file
        self.remap_list = remap_list

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        ds_in = gdal.Open(self.in_file)

        band = ds_in.GetRasterBand(1)

        block_sizes = band.GetBlockSize()
        x_block_size = block_sizes[0]
        y_block_size = block_sizes[1]
        xsize = band.XSize
        ysize = band.YSize

        driver = gdal.GetDriverByName("GTiff")
        ds_out = driver.Create(
            self.out_file, xsize, ysize, 1, gdal.GDT_Int16, ["COMPRESS=LZW"]
        )
        src_gt = ds_in.GetGeoTransform()
        ds_out.SetGeoTransform(src_gt)
        out_srs = osr.SpatialReference()
        out_srs.ImportFromWkt(ds_in.GetProjectionRef())
        ds_out.SetProjection(out_srs.ExportToWkt())

        blocks = 0

        for y in range(0, ysize, y_block_size):
            if self.killed:
                log(
                    "Processing of {} killed by user after processing {} out of {} blocks.".format(
                        self.in_file, y, ysize
                    )
                )

                break
            self.progress.emit(100 * float(y) / ysize)

            if y + y_block_size < ysize:
                rows = y_block_size
            else:
                rows = ysize - y

            for x in range(0, xsize, x_block_size):
                if x + x_block_size < xsize:
                    cols = x_block_size
                else:
                    cols = xsize - x

                d = band.ReadAsArray(x, y, cols, rows)

                d_original = d.copy()

                for value, replacement in zip(self.remap_list[0], self.remap_list[1]):
                    d[d_original == int(value)] = int(replacement)

                ds_out.GetRasterBand(1).WriteArray(d, x, y)
                blocks += 1

        if self.killed:
            del ds_out
            os.remove(self.out_file)

            return None
        else:
            return True


def get_unique_values_vector(layer, field, max_unique=100):
    idx = layer.fields().lookupField(field)
    values = layer.uniqueValues(idx)

    if len(values) > max_unique:
        return None
    else:
        return list(values)


def _get_min_max_tuple(values, min_min, max_max, nodata):
    values[values < nodata] = np.nan
    mn = np.nanmin(values)

    if mn < min_min:
        return None
    mx = np.nanmax(values)

    if mx > max_max:
        return None

    return (mn, mx)


def get_vector_stats(layer, attribute, min_min=0, max_max=1000, nodata=0):
    values = np.asarray(
        [feat.attribute(attribute) for feat in layer.getFeatures()], dtype=np.float32
    )

    return _get_min_max_tuple(values, min_min, max_max, nodata)


def get_raster_stats(f, band_num, sample=True, min_min=0, max_max=1000, nodata=0):
    # Note that anything less than nodata value is considered no data

    if sample:
        # Note need float to correctly mark and ignore nodata for for nanmin
        # and nanmax
        values = layers.get_sample(f, band_num, n=1e6).astype("float32")

        return _get_min_max_tuple(values, min_min, max_max, nodata)
    else:
        src_ds = gdal.Open(f)
        b = src_ds.GetRasterBand(band_num)

        block_sizes = b.GetBlockSize()
        x_block_size = block_sizes[0]
        y_block_size = block_sizes[1]
        xsize = b.XSize
        ysize = b.YSize

        stats = (None, None)

        for y in range(0, ysize, y_block_size):
            if y + y_block_size < ysize:
                rows = y_block_size
            else:
                rows = ysize - y

            for x in range(0, xsize, x_block_size):
                if x + x_block_size < xsize:
                    cols = x_block_size
                else:
                    cols = xsize - x

                d = b.ReadAsArray(x, y, cols, rows)

                mn, mx = _get_min_max_tuple(d, min_min, max_max, nodata)

                if not mn or not mx:
                    return None
                else:
                    if not stats[0] or mn < stats[0]:
                        stats[0] = mn

                    if not stats[1] or mx > stats[1]:
                        stats[1] = mx

        return stats


def get_unique_values_raster(f, band_num, sample=True, max_unique=60):
    if sample:
        values = np.unique(layers.get_sample(f, band_num, n=1e6)).tolist()

        if len(values) > max_unique:
            values = None

        return values
    else:
        src_ds = gdal.Open(f)
        b = src_ds.GetRasterBand(band_num)

        block_sizes = b.GetBlockSize()
        x_block_size = block_sizes[0]
        y_block_size = block_sizes[1]
        xsize = b.XSize
        ysize = b.YSize

        for y in range(0, ysize, y_block_size):
            if y + y_block_size < ysize:
                rows = y_block_size
            else:
                rows = ysize - y

            for x in range(0, xsize, x_block_size):
                if x + x_block_size < xsize:
                    cols = x_block_size
                else:
                    cols = xsize - x

                if x == 0 and y == 0:
                    v = np.unique(b.ReadAsArray(x, y, cols, rows).ravel())
                else:
                    v = np.unique(
                        np.concatenate((v, b.ReadAsArray(x, y, cols, rows).ravel()))
                    )

                if v.size > max_unique:
                    return None

        return v.tolist()


class DlgJobsDetails(QtWidgets.QDialog, Ui_DlgJobsDetails):
    def __init__(self, parent=None):
        """Constructor."""
        super().__init__(parent)

        self.setupUi(self)
        self.task_status.hide()
        self.statusLabel.hide()


class DlgDataIOLoadTE(QtWidgets.QDialog, Ui_DlgDataIOLoadTE):
    file_browse_btn: QtWidgets.QPushButton
    file_lineedit: QtWidgets.QLineEdit
    parsed_name_la: QtWidgets.QLabel
    parsed_name_le: QtWidgets.QLineEdit
    parsed_result_la: QtWidgets.QLabel
    parsed_result_path_le: QtWidgets.QLineEdit

    buttonBox: QtWidgets.QDialogButtonBox

    job: typing.Optional[Job]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.reset_widgets()
        self.job = None
        self.file_browse_btn.clicked.connect(self.parse_job_file)
        self.buttonBox.accepted.connect(self.ok_clicked)
        self.buttonBox.rejected.connect(self.reject)
        self.buttonBox.button(self.buttonBox.Ok).setEnabled(False)

    def reset_widgets(self):
        self.parsed_name_la.setEnabled(False)
        self.parsed_name_le.clear()
        self.parsed_name_le.setEnabled(False)
        self.parsed_result_la.setEnabled(False)
        self.parsed_result_path_le.clear()
        self.parsed_result_path_le.setEnabled(False)

    def show_job_info(self):
        self.parsed_name_la.setEnabled(True)
        self.parsed_name_le.setText(self.job.get_basename())
        self.parsed_name_le.setEnabled(True)
        self.parsed_result_la.setEnabled(True)
        try:
            local_path = str(self.job.results.uri.uri)
        except IndexError:
            local_path = ""
        self.parsed_result_path_le.setText(local_path)
        self.parsed_result_path_le.setEnabled(True)

    def parse_job_file(self):
        self.reset_widgets()
        self.job = None
        self.buttonBox.button(self.buttonBox.Ok).setEnabled(False)
        file_dialog = QtWidgets.QFileDialog(self)
        file_dialog.setFileMode(QtWidgets.QFileDialog.ExistingFile)
        file_dialog.setNameFilter("*.json")
        file_dialog.setDirectory(conf.settings_manager.get_value(conf.Setting.BASE_DIR))

        if file_dialog.exec_():
            chosen_raw_path = file_dialog.selectedFiles()[0]
            job, error_message = self.parse_chosen_path(chosen_raw_path)

            if job is not None:
                self.file_lineedit.setText(chosen_raw_path)
                self.job = job
                self.show_job_info()
                self.buttonBox.button(self.buttonBox.Ok).setEnabled(True)
            else:
                self.file_lineedit.clear()
                QtWidgets.QMessageBox.critical(
                    self, tr_data_io.tr("Could not load file"), error_message
                )

    def parse_chosen_path(
        self, raw_path: str
    ) -> typing.Tuple[typing.Optional[Job], str]:
        path = Path(raw_path)
        job = None
        error_message = ""

        if path.is_file():
            try:
                raw_job = json.loads(path.read_text())
                job = Job.Schema().load(raw_job)
                update_uris_if_needed(job, path)
                set_results_extents(job)
            except (json.JSONDecodeError, KeyError):
                error_message = tr_data_io.tr(
                    "Could not parse the selected file into a valid JSON"
                )

        return job, error_message

    def ok_clicked(self):
        log("Importing job...")
        job_manager.import_job(self.job, Path(self.file_lineedit.text()))
        self.accept()


class ImportSelectFileInputWidget(
    QtWidgets.QWidget, Ui_WidgetDataIOImportSelectFileInput
):
    inputFileChanged = QtCore.pyqtSignal(bool)
    inputTypeChanged = QtCore.pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.radio_raster_input.toggled.connect(self.radio_raster_input_toggled)

        self.btn_raster_dataset_browse.clicked.connect(self.open_raster_browse)
        self.btn_polygon_dataset_browse.clicked.connect(self.open_vector_browse)

        self.groupBox_output_resolution.clicked.connect(self.output_res_toggled)

        # Ensure the special value text (set to " ") is displayed by default
        self.spinBox_data_year.setSpecialValueText(" ")
        self.spinBox_data_year.setValue(int(self.spinBox_data_year.minimum()))

    def radio_raster_input_toggled(self):
        has_file = False

        if self.radio_raster_input.isChecked():
            self.btn_raster_dataset_browse.setEnabled(True)
            self.lineEdit_raster_file.setEnabled(True)
            self.comboBox_bandnumber.setEnabled(True)
            self.label_bandnumber.setEnabled(True)
            self.btn_polygon_dataset_browse.setEnabled(False)
            self.lineEdit_vector_file.setEnabled(False)
            self.label_fieldname.setEnabled(False)
            self.comboBox_fieldname.setEnabled(False)
            self.groupBox_output_resolution.setChecked(False)

            if self.lineEdit_raster_file.text():
                has_file = True
        else:
            self.btn_raster_dataset_browse.setEnabled(False)
            self.lineEdit_raster_file.setEnabled(False)
            self.comboBox_bandnumber.setEnabled(False)
            self.label_bandnumber.setEnabled(False)
            self.btn_polygon_dataset_browse.setEnabled(True)
            self.lineEdit_vector_file.setEnabled(True)
            self.label_fieldname.setEnabled(True)
            self.comboBox_fieldname.setEnabled(True)
            self.groupBox_output_resolution.setChecked(True)

            if self.lineEdit_vector_file.text():
                has_file = True
        self.inputTypeChanged.emit(has_file)

    def output_res_toggled(self):
        # Ensure the groupBox_output_resolution remains checked if vector
        # output is chosen

        if self.radio_raster_input.isChecked():
            pass
        else:
            self.groupBox_output_resolution.setChecked(True)

    def open_raster_browse(self):
        if self.lineEdit_raster_file.text():
            initial_file = self.lineEdit_raster_file.text()
        else:
            initial_file = QSettings().value("LDMP/input_dir", None)
        raster_file, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            tr_data_io.tr("Select a raster input file"),
            initial_file,
            tr_data_io.tr("Raster file (*.tif *.dat *.img *.vrt)"),
        )
        # Try loading this raster to verify the file works

        if raster_file:
            self.update_raster_layer(raster_file)

    def update_raster_layer(self, raster_file):
        layer = qgis.core.QgsRasterLayer(raster_file, "raster file", "gdal")

        if not os.access(raster_file, os.R_OK or not layer.isValid()):
            QtWidgets.QMessageBox.critical(
                None,
                tr_data_io.tr("Error"),
                tr_data_io.tr(
                    "Cannot read {}. Choose a different file.".format(raster_file)
                ),
            )
            self.inputFileChanged.emit(False)

            return False
        else:
            QSettings().setValue("LDMP/input_dir", os.path.dirname(raster_file))
            self.lineEdit_raster_file.setText(raster_file)
            self.comboBox_bandnumber.clear()
            self.comboBox_bandnumber.addItems(
                [str(n) for n in range(1, layer.dataProvider().bandCount() + 1)]
            )

            self.inputFileChanged.emit(True)

            return True

    def open_vector_browse(self):
        if self.lineEdit_vector_file.text():
            initial_file = self.lineEdit_vector_file.text()
        else:
            initial_file = QSettings().value("LDMP/input_dir", None)
        vector_file, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            tr_data_io.tr("Select a vector input file"),
            initial_file,
            tr_data_io.tr("Vector file (*.shp *.kml *.kmz *.geojson)"),
        )
        # Try loading this vector to verify the file works

        if vector_file:
            self.update_vector_layer(vector_file)

    def update_vector_layer(self, vector_file):
        layer = qgis.core.QgsVectorLayer(vector_file, "vector file", "ogr")

        if not os.access(vector_file, os.R_OK) or not layer.isValid():
            QtWidgets.QMessageBox.critical(
                None,
                tr_data_io.tr("Error"),
                tr_data_io.tr(
                    "Cannot read {}. Choose a different file.".format(vector_file)
                ),
            )
            self.inputFileChanged.emit(False)

            return False
        else:
            QSettings().setValue("LDMP/input_dir", os.path.dirname(vector_file))
            self.lineEdit_vector_file.setText(vector_file)
            self.comboBox_fieldname.clear()
            self.inputFileChanged.emit(True)
            self.comboBox_fieldname.addItems(
                [field.name() for field in layer.dataProvider().fields()]
            )

            return True

    def get_vector_layer(self) -> qgis.core.QgsVectorLayer:
        vector_file = self.lineEdit_vector_file.text()
        if not vector_file:
            return None

        return qgis.core.QgsVectorLayer(
            self.lineEdit_vector_file.text(), "vector file", "ogr"
        )

    def get_raster_layer(self) -> qgis.core.QgsRasterLayer:
        """
        Returns the raster layer corresponding to the input file. If
        a file path is not specified or if the layer is invalid then it
        will return None.
        """
        raster_file = self.lineEdit_raster_file.text()
        if not raster_file:
            return None

        layer = qgis.core.QgsRasterLayer(raster_file)
        if not layer.isValid():
            return None

        return layer

    def selected_file_type(self) -> str:
        """
        Returns if current selection is "raster" or "vector".
        """
        if self.radio_raster_input.isChecked():
            return "raster"
        elif self.radio_polygon_input.isChecked():
            return "vector"

        return ""


class ImportSelectRasterOutput(
    QtWidgets.QWidget, Ui_WidgetDataIOImportSelectRasterOutput
):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setupUi(self)

        self.btn_output_file_browse.clicked.connect(self.save_raster)

    def save_raster(self):
        if self.lineEdit_output_file.text():
            initial_file = self.lineEdit_output_file.text()
        else:
            initial_file = conf.settings_manager.get_value(conf.Setting.BASE_DIR)
        raw_output_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            tr_data_io.tr("Choose a name for the output file"),
            initial_file,
            tr_data_io.tr("Raster file (*.tif)"),
        )

        if raw_output_path:
            output_path = Path(raw_output_path)
            output_path = output_path.parent / f"{output_path.stem}.tif"

            if os.access(os.path.dirname(str(output_path)), os.W_OK):
                self.lineEdit_output_file.setText(str(output_path))

                return True
            else:
                QtWidgets.QMessageBox.critical(
                    self,
                    tr_data_io.tr("Error"),
                    tr_data_io.tr(
                        "Cannot write to {}. Choose a different file.".format(
                            raw_output_path
                        )
                    ),
                )

                return False


def extents_within_tolerance(
    geom1: qgis.core.QgsGeometry, geom2: qgis.core.QgsGeometry
) -> bool:
    """
    Check if the two geometries are overlapping and to which extent based on
    the tolerance setting, which is based on a ratio of the non-overlapping
    area to the total area of the reference geometry.
    Ensure the two geometries are in the same CRS.
    """
    if geom1.equals(geom2):
        return True

    diff_geom = geom1.difference(geom2)
    if diff_geom.isNull():
        return False

    # Cannot calculate tolerance based on area if not polygon based.
    if diff_geom.type() != qgis.core.QgsWkbTypes.GeometryType.PolygonGeometry:
        return False

    area_calculator = qgis.core.QgsDistanceArea()
    diff_ratio = area_calculator.measureArea(diff_geom) / area_calculator.measureArea(
        geom1
    )

    tolerance = conf.settings_manager.get_value(conf.Setting.IMPORT_AREA_TOLERANCE)

    if (1 - diff_ratio) > tolerance:
        return True

    return False


class DlgDataIOImportBase(QtWidgets.QDialog):
    """Base class for individual data loading dialogs"""

    input_widget: ImportSelectFileInputWidget
    metadata: qgis.core.QgsLayerMetadata

    layer_loaded = QtCore.pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        # Message bar
        self.msg_bar = qgis.gui.QgsMessageBar()
        self.verticalLayout.insertWidget(0, self.msg_bar)

        # Region selector
        self.region_selector = RegionSelector()
        self.region_selector.region_changed.connect(self.on_region_changed)
        self.verticalLayout.insertWidget(1, self.region_selector)

        self.input_widget = ImportSelectFileInputWidget()
        self.input_widget.inputFileChanged.connect(self.on_input_file_changed)
        self.verticalLayout.insertWidget(2, self.input_widget)

        # The datatype determines whether the dataset resampling is done with
        # nearest neighbor and mode or nearest neighbor and mean
        self.datatype = "categorical"
        self.metadata = None

        self.btnMetadata = QtWidgets.QPushButton(tr_data_io.tr("Metadata"))
        layout = self.btnBox.layout()
        layout.insertWidget(0, self.btnMetadata)
        self.btnMetadata.clicked.connect(self.open_metadata_editor)

        # Output raster file - this should be moved once a job has been
        # created by calling job_manager.move_job_results().
        self._output_raster_path = GetTempFilename(".tif")

    def on_region_changed(self, region_info):
        """
        Slot raised when the region has changed.
        """
        self.validate_overlap()

    def on_input_file_changed(self, success):
        """
        Slot raised when a raster or vector file has been uploaded.
        """
        if success:
            self.validate_overlap()

    def validate_overlap(self, user_warning=True) -> bool:
        """
        Checks the range within which the geometry of the uploaded file
        overlaps with that of the selected region. The allowed range should
        be within the tolerance specified in the settings. Sends a warning
        that the output will be expanded or clipped if the extents are not
        the same. Messaging will be sent if the child dialog contains a
        'msg_bar' attribute of type QMessageBar.
        """
        self.msg_bar.clearWidgets()

        region_geom = prepare_area_of_interest().get_unary_geometry()
        if region_geom is None or not region_geom.isGeosValid():
            return False

        file_type = self.input_widget.selected_file_type()
        if not file_type:
            return False

        layer_bbox_geom = None
        source_crs = None
        if file_type == "raster":
            lyr = self.input_widget.get_raster_layer()
            if lyr:
                layer_bbox_geom = qgis.core.QgsGeometry.fromRect(lyr.extent())
                source_crs = lyr.crs()
        else:
            lyr = self.input_widget.get_vector_layer()
            if not lyr or not lyr.isValid():
                return False

            source_crs = lyr.crs()

            # Combine the geometry for all the features
            feat_iter = lyr.getFeatures()
            geoms = [
                f.geometry()
                for f in feat_iter
                if f.isValid() and not f.geometry().isNull()
            ]
            for g in geoms:
                if layer_bbox_geom is None:
                    layer_bbox_geom = g
                    continue
                layer_bbox_geom = layer_bbox_geom.combine(g)

        if layer_bbox_geom is None:
            return False

        if source_crs is None or not source_crs.isValid():
            if user_warning:
                self.msg_bar.pushMessage(
                    self.tr("Missing or invalid CRS for input file."),
                    qgis.core.Qgis.MessageLevel.Warning,
                    8,
                )

            return False

        # Reproject the geometry to WGS if different from region
        wgs84_crs = qgis.core.QgsCoordinateReferenceSystem.fromEpsgId(4326)
        if source_crs != wgs84_crs:
            transform_ctx = qgis.core.QgsProject.instance().transformContext()
            ct = qgis.core.QgsCoordinateTransform(source_crs, wgs84_crs, transform_ctx)
            result = layer_bbox_geom.transform(ct)
            if result != qgis.core.Qgis.GeometryOperationResult.Success:
                log("Unable to reproject source file geometry.")
                return False

        # Check if within tolerance
        if not extents_within_tolerance(region_geom, layer_bbox_geom):
            # Notify user
            if user_warning:
                reg_name = self.region_selector.region_info.area_name
                self.msg_bar.pushMessage(
                    self.tr(f"Output file will be resized to '{reg_name}' extent."),
                    qgis.core.Qgis.MessageLevel.Warning,
                    8,
                )
            return False

        return True

    def extent_as_list(self) -> list:
        """
        Returns the list containing xmin, ymin, xmax, ymax of the
        region geom extent or an empty list if the extent could not be
        determined.
        """
        geom = prepare_area_of_interest().get_unary_geometry()
        if geom is None or not geom.isGeosValid():
            return []

        bbox = geom.boundingBox()

        if bbox is None:
            return []

        return [bbox.xMinimum(), bbox.yMinimum(), bbox.xMaximum(), bbox.yMaximum()]

    def validate_input(self, value):
        if self.input_widget.radio_raster_input.isChecked():
            if self.input_widget.lineEdit_raster_file.text() == "":
                QtWidgets.QMessageBox.critical(
                    self,
                    tr_data_io.tr("Error"),
                    tr_data_io.tr("Choose an input raster file."),
                )

                return
        else:
            in_file = self.input_widget.lineEdit_vector_file.text()

            if in_file == "":
                QtWidgets.QMessageBox.critical(
                    self,
                    tr_data_io.tr("Error"),
                    tr_data_io.tr("Choose an input polygon dataset."),
                )

                return
            layer = self.input_widget.get_vector_layer()

            if (
                layer.wkbType() == qgis.core.QgsWkbTypes.Polygon
                or layer.wkbType() == qgis.core.QgsWkbTypes.MultiPolygon
            ):
                self.vector_datatype = "polygon"
            elif layer.wkbType() == qgis.core.QgsWkbTypes.Point:
                self.vector_datatype = "point"
            else:
                QtWidgets.QMessageBox.critical(
                    None,
                    tr_data_io.tr("Error"),
                    tr_data_io.tr(
                        "Cannot process {}. Unknown geometry type:{}".format(
                            in_file, layer.wkbType()
                        )
                    ),
                )
                log(
                    "Failed to process {} - unknown geometry type {}.".format(
                        in_file, layer.wkbType()
                    )
                )

                return

        return True

    def get_resample_mode(self, f):
        in_res = self.get_in_res_wgs84()
        out_res = self.get_out_res_wgs84()

        if in_res < out_res:
            if self.datatype == "categorical":
                log(
                    "Resampling with mode (in res: {}, out_res: {}".format(
                        in_res, out_res
                    )
                )

                return gdal.GRA_Mode
            elif self.datatype == "continuous":
                log(
                    "Resampling with average (in res: {}, out_res: {}".format(
                        in_res, out_res
                    )
                )

                return gdal.GRA_Average
            else:
                raise ValueError("Unknown datatype")
        else:
            # If output resolution is finer than the original data, use nearest
            # neighbor
            log(
                "Resampling with nearest neighbor (in res: {}, out_res: {}".format(
                    in_res, out_res
                )
            )

            return gdal.GRA_NearestNeighbour

    def get_in_res_wgs84(self):
        ds_in = gdal.Open(self.input_widget.lineEdit_raster_file.text())
        wgs84_srs = osr.SpatialReference()
        wgs84_srs.ImportFromEPSG(4326)

        in_srs = osr.SpatialReference()
        in_srs.ImportFromWkt(ds_in.GetProjectionRef())

        tx = osr.CoordinateTransformation(in_srs, wgs84_srs)

        geo_t = ds_in.GetGeoTransform()
        x_size = ds_in.RasterXSize
        y_size = ds_in.RasterYSize
        # Work out the boundaries of the new dataset in the target projection
        (ulx, uly, ulz) = tx.TransformPoint(geo_t[0], geo_t[3])
        (lrx, lry, lrz) = tx.TransformPoint(
            geo_t[0] + geo_t[1] * x_size, geo_t[3] + geo_t[5] * y_size
        )
        log("ulx: {}, uly: {}, ulz: {}".format(ulx, uly, ulz))
        log("lrx: {}, lry: {}, lrz: {}".format(lrx, lry, lrz))
        # As an approximation of what the output res would be in WGS4, use an
        # average of the x and y res of this image

        return ((lrx - ulx) / float(x_size) + (lry - uly) / float(y_size)) / 2

    def get_out_res_wgs84(self):
        # Calculate res in degrees from input which is in meters
        res = int(self.input_widget.spinBox_resolution.value())

        return res / (111.325 * 1000)  # 111.325km in one degree

    def remap_vector(self, layer, out_file, remap_dict, attribute):
        out_res = self.get_out_res_wgs84()
        log(
            'Remapping and rasterizing {} using output resolution {}, and field "{}"'.format(
                out_file, out_res, attribute
            )
        )
        log('Remap dict "{}"'.format(remap_dict))

        target_bounds = self.extent_as_list()
        if len(target_bounds) == 0:
            log("Target bounds for remapping vector not available.")
            target_bounds = None

        remap_vector_worker = worker.StartWorker(
            RemapVectorWorker,
            "rasterizing and remapping values",
            layer,
            out_file,
            attribute,
            remap_dict,
            self.vector_datatype,
            out_res,
            target_bounds,
        )

        if not remap_vector_worker.success:
            QtWidgets.QMessageBox.critical(
                None, tr_data_io.tr("Error"), tr_data_io.tr("Vector remapping failed.")
            )

            return False
        else:
            return True

    def remap_raster(self, out_file, remap_list):
        # First warp the raster to the correct CRS
        temp_tif = GetTempFilename(".tif")
        warp_ret = self.warp_raster(temp_tif)

        if not warp_ret:
            return False

        remap_raster_worker = worker.StartWorker(
            RemapRasterWorker, "remapping values", temp_tif, out_file, remap_list
        )
        os.remove(temp_tif)

        if not remap_raster_worker.success:
            QtWidgets.QMessageBox.critical(
                None, tr_data_io.tr("Error"), tr_data_io.tr("Raster remapping failed.")
            )

            return False
        else:
            return True

    def rasterize_vector(self, in_file, out_file, attribute):
        out_res = self.get_out_res_wgs84()
        log(
            f"Rasterizing {out_file} using output resolution {out_res}, "
            f'and field "{attribute}"'
        )
        rasterize_worker = worker.StartWorker(
            RasterizeWorker,
            "rasterizing vector file",
            in_file,
            out_file,
            out_res,
            attribute,
        )

        if not rasterize_worker.success:
            QtWidgets.QMessageBox.critical(
                None, tr_data_io.tr("Error"), tr_data_io.tr("Rasterizing failed.")
            )

            return False
        else:
            return True

    def warp_raster(self, out_file):
        # Select a single output band
        in_file = self.input_widget.lineEdit_raster_file.text()
        band_number = int(self.input_widget.comboBox_bandnumber.currentText())
        temp_tif = GetTempFilename(".tif")
        target_bounds = self.extent_as_list()

        if len(target_bounds) == 0:
            log("Target bounds for warping raster not available.")
            gdal.Translate(
                temp_tif,
                in_file,
                bandList=[band_number],
                outputType=gdal.GDT_Byte,
            )
        else:
            ext_str = ",".join(map(str, target_bounds))
            log(f"Target bounds for warped raster: {ext_str}")
            # Ensure target_bounds are in the correct order: [xmin, ymax, xmax, ymin]
            xmin, ymin, xmax, ymax = target_bounds
            projwin = [xmin, ymax, xmax, ymin]
            gdal.Translate(
                temp_tif,
                in_file,
                bandList=[band_number],
                outputType=gdal.GDT_Byte,
                projWin=projwin,
            )

        log("Importing {} to {}".format(in_file, out_file))

        if self.input_widget.groupBox_output_resolution.isChecked():
            out_res = self.get_out_res_wgs84()
            resample_mode = self.get_resample_mode(temp_tif)
        else:
            out_res = None
            resample_mode = gdal.GRA_NearestNeighbour

        raster_import_worker = worker.StartWorker(
            RasterImportWorker,
            "importing raster",
            temp_tif,
            out_file,
            out_res,
            resample_mode,
        )
        os.remove(temp_tif)

        if not raster_import_worker.success:
            QtWidgets.QMessageBox.critical(
                self, tr_data_io.tr("Error"), tr_data_io.tr("Raster import failed.")
            )
            return False
        else:
            return True

    def open_metadata_editor(self):
        dlg = metadata_dialog.DlgDatasetMetadata(self)
        dlg.exec_()
        self.metadata = dlg.get_metadata()

    def save_metadata(self, job):
        metadata.init_dataset_metadata(job, self.metadata)


class DlgDataIOImportPopulation(DlgDataIOImportBase, Ui_DlgDataIOImportPopulation):
    def __init__(self, parent=None):
        super().__init__(parent)

    def done(self, value):
        if value == QtWidgets.QDialog.Accepted:
            self.validate_input(value)
        else:
            super().done(value)

    def validate_input(self, value):
        max_max = 10000000  # Maximum value for population
        if (
            self.input_widget.spinBox_data_year.text()
            == self.input_widget.spinBox_data_year.specialValueText()
        ):
            QtWidgets.QMessageBox.critical(
                self,
                tr_data_io.tr("Error"),
                tr_data_io.tr("Enter the year of the input data."),
            )

            return

        ret = super().validate_input(value)

        if not ret:
            return

        if self.input_widget.radio_raster_input.isChecked():
            in_file = self.input_widget.lineEdit_raster_file.text()
            stats = get_raster_stats(
                in_file,
                int(self.input_widget.comboBox_bandnumber.currentText()),
                max_max=max_max,
            )
        else:
            in_file = self.input_widget.lineEdit_vector_file.text()
            layer = self.input_widget.get_vector_layer()
            field = self.input_widget.comboBox_fieldname.currentText()
            idx = layer.fields().lookupField(field)

            if not layer.fields().field(idx).isNumeric():
                QtWidgets.QMessageBox.critical(
                    self,
                    tr_data_io.tr("Error"),
                    tr_data_io.tr(
                        "The chosen field ({}) is not numeric. Choose a numeric field.".format(
                            field
                        )
                    ),
                )

                return
            else:
                stats = get_vector_stats(
                    self.input_widget.get_vector_layer(), field, max_max=max_max
                )
        log("Stats are: {}".format(stats))

        if not stats:
            QtWidgets.QMessageBox.critical(
                self,
                tr_data_io.tr("Error"),
                tr_data_io.tr(
                    "The input file ({}) does not appear to be a valid population "
                    "input file. The file should contain values of soil "
                    "organic carbon in tonnes / hectare.".format(in_file)
                ),
            )

            return

        if stats[0] < 0:
            QtWidgets.QMessageBox.critical(
                self,
                tr_data_io.tr("Error"),
                tr_data_io.tr(
                    "The input file ({}) does not appear to be a valid population "
                    "input file. The minimum value in this file is {}. The no "
                    "data value should be -32768, and all other values should be >= 0.".format(
                        in_file, stats[0]
                    )
                ),
            )

            return

        if stats[1] > 10000000:
            QtWidgets.QMessageBox.critical(
                self,
                tr_data_io.tr("Error"),
                tr_data_io.tr(
                    "The input file ({}) does not appear to be a valid soil organic "
                    "carbon input file. The maximum value in this file is {}. "
                    "The maximum value allowed is {} tonnes / hectare.".format(
                        in_file, stats[1], max_max
                    )
                ),
            )

            return

        super().done(value)

        self.ok_clicked()

    def ok_clicked(self):
        out_file = self._output_raster_path

        if self.input_widget.radio_raster_input.isChecked():
            ret = self.warp_raster(out_file)
        else:
            in_file = self.input_widget.lineEdit_vector_file.text()
            attribute = self.input_widget.comboBox_fieldname.currentText()
            ret = self.rasterize_vector(in_file, out_file, attribute)

        if not ret:
            return False

        job = job_manager.create_job_from_dataset(
            dataset_path=Path(out_file),
            band_name="Population (number of people)",
            band_metadata={
                "year": int(self.input_widget.spinBox_data_year.text()),
                "source": "custom data",
                "type": "total",
            },
            task_name=tr_data_io.tr(
                "Population "
                f"({int(self.input_widget.spinBox_data_year.text())}, imported)"
            ),
        )
        job_manager.import_job(job, Path(out_file))
        job_manager.move_job_results(job)

        super().save_metadata(job)


class DlgDataIOImportSOC(DlgDataIOImportBase, Ui_DlgDataIOImportSOC):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.datatype = "continuous"

    def done(self, value):
        if value == QtWidgets.QDialog.Accepted:
            self.validate_input(value)
        else:
            super().done(value)

    def validate_input(self, value):
        if (
            self.input_widget.spinBox_data_year.text()
            == self.input_widget.spinBox_data_year.specialValueText()
        ):
            QtWidgets.QMessageBox.critical(
                self,
                tr_data_io.tr("Error"),
                tr_data_io.tr("Enter the year of the input data."),
            )

            return

        ret = super().validate_input(value)

        if not ret:
            return

        if self.input_widget.radio_raster_input.isChecked():
            in_file = self.input_widget.lineEdit_raster_file.text()
            stats = get_raster_stats(
                in_file, int(self.input_widget.comboBox_bandnumber.currentText())
            )
        else:
            in_file = self.input_widget.lineEdit_vector_file.text()
            layer = self.input_widget.get_vector_layer()
            field = self.input_widget.comboBox_fieldname.currentText()
            idx = layer.fields().lookupField(field)

            if not layer.fields().field(idx).isNumeric():
                QtWidgets.QMessageBox.critical(
                    self,
                    tr_data_io.tr("Error"),
                    tr_data_io.tr(
                        "The chosen field ({}) is not numeric. Choose a numeric field.".format(
                            field
                        )
                    ),
                )

                return
            else:
                stats = get_vector_stats(self.input_widget.get_vector_layer(), field)
        log("Stats are: {}".format(stats))

        if not stats:
            QtWidgets.QMessageBox.critical(
                self,
                tr_data_io.tr("Error"),
                tr_data_io.tr(
                    "The input file ({}) does not appear to be a valid soil organic "
                    "carbon input file. The file should contain values of soil "
                    "organic carbon in tonnes / hectare.".format(in_file)
                ),
            )

            return

        if stats[0] < 0:
            QtWidgets.QMessageBox.critical(
                self,
                tr_data_io.tr("Error"),
                tr_data_io.tr(
                    "The input file ({}) does not appear to be a valid soil organic "
                    "carbon input file. The minimum value in this file is {}. The no "
                    "data value should be -32768, and all other values should be >= 0.".format(
                        in_file, stats[0]
                    )
                ),
            )

            return

        if stats[1] > 1000:
            QtWidgets.QMessageBox.critical(
                self,
                tr_data_io.tr("Error"),
                tr_data_io.tr(
                    "The input file ({}) does not appear to be a valid soil organic "
                    "carbon input file. The maximum value in this file is {}. "
                    "The maximum value allowed is 1000 tonnes / hectare.".format(
                        in_file, stats[1]
                    )
                ),
            )

            return

        super().done(value)

        self.ok_clicked()

    def ok_clicked(self):
        out_file = self._output_raster_path

        if self.input_widget.radio_raster_input.isChecked():
            ret = self.warp_raster(out_file)
        else:
            in_file = self.input_widget.lineEdit_vector_file.text()
            attribute = self.input_widget.comboBox_fieldname.currentText()
            ret = self.rasterize_vector(in_file, out_file, attribute)

        if not ret:
            return False

        job = job_manager.create_job_from_dataset(
            dataset_path=Path(out_file),
            band_name="Soil organic carbon",
            band_metadata={
                "year": int(self.input_widget.spinBox_data_year.text()),
                "source": "custom data",
            },
            task_name=tr_data_io.tr(
                "Soil organic carbon "
                f"({int(self.input_widget.spinBox_data_year.text())}, imported)"
            ),
        )
        job_manager.import_job(job, Path(out_file))
        job_manager.move_job_results(job)

        super().save_metadata(job)


class DlgDataIOImportProd(DlgDataIOImportBase, Ui_DlgDataIOImportProd):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.input_widget.groupBox_year.hide()
        self.populate_data_types()

        # Ensure the special value text (set to " ") is displayed by default
        self.spinBox_year_initial.setSpecialValueText(" ")
        self.spinBox_year_initial.setValue(int(self.spinBox_year_initial.minimum()))
        self.spinBox_year_final.setSpecialValueText(" ")
        self.spinBox_year_final.setValue(int(self.spinBox_year_final.minimum()))

    def done(self, value):
        if value == QtWidgets.QDialog.Accepted:
            self.validate_input(value)
        else:
            super().done(value)

    def validate_input(self, value):
        try:
            _ = int(self.spinBox_year_initial.text())
            _ = int(self.spinBox_year_final.text())
        except ValueError:
            QtWidgets.QMessageBox.critical(
                self,
                tr_data_io.tr("Error"),
                tr_data_io.tr(
                    "Enter the intial and final year applying to this input data."
                ),
            )

            return
        ret = super().validate_input(value)

        if not ret:
            return

        if self.input_widget.radio_raster_input.isChecked():
            in_file = self.input_widget.lineEdit_raster_file.text()
            values = get_unique_values_raster(
                in_file,
                int(self.input_widget.comboBox_bandnumber.currentText()),
                max_unique=7,
            )
        else:
            in_file = self.input_widget.lineEdit_vector_file.text()
            layer = self.input_widget.get_vector_layer()
            field = self.input_widget.comboBox_fieldname.currentText()
            idx = layer.fields().lookupField(field)

            if not layer.fields().field(idx).isNumeric():
                QtWidgets.QMessageBox.critical(
                    self,
                    tr_data_io.tr("Error"),
                    tr_data_io.tr(
                        "The chosen field ({}) is not numeric. Choose a field that "
                        "contains numbers.".format(field)
                    ),
                )

                return
            else:
                values = get_unique_values_vector(layer, field, max_unique=7)

        if not values:
            QtWidgets.QMessageBox.critical(
                self,
                tr_data_io.tr("Error"),
                tr_data_io.tr(
                    "The input file ({}) does not appear to be a valid productivity "
                    "input file.".format(in_file)
                ),
            )

            return
        invalid_values = [v for v in values if v not in [-32768, 0, 1, 2, 3, 4, 5]]

        if len(invalid_values) > 0:
            QtWidgets.QMessageBox.warning(
                self,
                tr_data_io.tr("Warning"),
                tr_data_io.tr(
                    "The input file ({}) does not appear to be a valid productivity "
                    "input file. Trends.Earth will load the file anyway, but review "
                    "the map once it has loaded to ensure the values make sense. The "
                    "only values allowed in a productivity input file are -32768, 1, "
                    "2, 3, 4 and 5. There are {} value(s) in the input file "
                    "that were not recognized.".format(in_file, len(invalid_values))
                ),
            )

        super().done(value)

        self.ok_clicked()

    def populate_data_types(self):
        for datatype in [
            ld_conf.JRC_LPD_BAND_NAME,
            ld_conf.FAO_WOCAT_LPD_BAND_NAME,
            ld_conf.TE_LPD_BAND_NAME,
        ]:
            self.datatype_cb.addItem(datatype)

    def ok_clicked(self):
        out_file = self._output_raster_path

        if self.input_widget.radio_raster_input.isChecked():
            ret = self.warp_raster(out_file)
        else:
            in_file = self.input_widget.lineEdit_vector_file.text()
            attribute = self.input_widget.comboBox_fieldname.currentText()
            ret = self.rasterize_vector(in_file, out_file, attribute)

        if not ret:
            return False

        job = job_manager.create_job_from_dataset(
            dataset_path=Path(out_file),
            band_name=self.datatype_cb.currentText(),
            band_metadata={
                "year_initial": int(self.spinBox_year_initial.text()),
                "year_final": int(self.spinBox_year_final.text()),
            },
            task_name=self.tr(
                f"Land productivity (imported - {self.datatype_cb.currentText()})"
            ),
        )
        job_manager.import_job(job, Path(out_file))
        job_manager.move_job_results(job)

        super().save_metadata(job)


def _get_layers(node):
    layer = []

    if isinstance(node, qgis.core.QgsLayerTreeGroup):
        for child in node.children():
            if isinstance(child, qgis.core.QgsLayerTreeLayer):
                layer.append(child.layer())
            else:
                layer.extend(_get_layers(child))
    else:
        layer = node

    return layer


@functools.lru_cache(
    maxsize=None
)  # not using functools.cache, as it was only introduced in Python 3.9
def _get_usable_bands(
    band_name: typing.Optional[str] = "any",
    selected_job_id: uuid.UUID = None,
    filter_field: str = None,
    filter_value: str = None,
    aoi=None,
) -> typing.List[Band]:
    result = []

    for job in job_manager.relevant_jobs:
        job: Job
        is_available = job.status in (JobStatus.DOWNLOADED, JobStatus.GENERATED_LOCALLY)
        is_of_interest = (selected_job_id is None) or (job.id == selected_job_id)
        is_valid_type = job.results and (
            ResultType(job.results.type) == ResultType.RASTER_RESULTS
        )

        if is_available and is_of_interest and is_valid_type:
            for band_index, band_info in enumerate(job.results.get_bands(), start=1):
                if job.results.uri is not None and (
                    band_info.name == band_name or band_name == "any"
                ):
                    if aoi is not None:
                        if not _check_dataset_overlap_raster(aoi, job.results):
                            continue
                    if (
                        filter_field is None
                        or filter_value is None
                        or band_info.metadata[filter_field] == filter_value
                    ):
                        result.append(
                            Band(
                                job=job,
                                path=job.results.uri.uri,
                                band_index=band_index,
                                band_info=band_info,
                            )
                        )
    result.sort(key=lambda ub: ub.job.start_date, reverse=True)

    return result


class WidgetDataIOSelectTELayerBase(QtWidgets.QWidget):
    comboBox_layers: QtWidgets.QComboBox
    layer_list: typing.Optional[typing.List[Band]]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.layer_list = None

        self.NO_LAYERS_MESSAGE = tr_data_io.tr("No layers available in this region")

    def populate(self, selected_job_id=None):
        aoi = areaofinterest.prepare_area_of_interest()
        layer_types = self.property("layer_type").split(";")
        usable_bands = []
        for layer_type in layer_types:
            usable_bands.extend(
                _get_usable_bands(
                    band_name=layer_type,
                    selected_job_id=selected_job_id,
                    filter_field=self.property("layer_filter_field"),
                    filter_value=self.property("layer_filter_value"),
                    aoi=aoi,
                )
            )
        self.layer_list = usable_bands
        old_text = self.currentText()
        self.comboBox_layers.clear()

        if len(usable_bands) == 0:
            self.comboBox_layers.addItem(self.NO_LAYERS_MESSAGE)
        else:
            for i, usable_band in enumerate(usable_bands):
                self.comboBox_layers.addItem(usable_band.get_name_info())
                self.comboBox_layers.setItemData(
                    i, usable_band.get_hover_info(), QtCore.Qt.ToolTipRole
                )
        if not self.set_index_from_text(old_text):
            self.comboBox_layers.setCurrentIndex(0)

    def get_current_extent(self):
        band = self.get_current_band()

        return qgis.core.QgsRasterLayer(str(band.path), "raster file", "gdal").extent()

    def get_current_data_file(self) -> Path:
        return self.get_current_band().path

    def get_layer(self) -> qgis.core.QgsRasterLayer:
        return qgis.core.QgsRasterLayer(
            str(self.get_current_data_file()), "raster file", "gdal"
        )

    def get_current_band(self) -> Band:
        return self.layer_list[self.comboBox_layers.currentIndex()]

    def set_index_from_job_id(self, job_id):
        if self.layer_list:
            for i in range(len(self.layer_list)):
                if self.layer_list[i].job.id == job_id:
                    self.comboBox_layers.setCurrentIndex(i)

                    return True

        return False

    def set_index_from_text(self, text):
        if self.layer_list:
            for i, layer in enumerate(self.layer_list):
                if text == layer:
                    self.comboBox_layers.setCurrentIndex(i)
                    return True

        return False

    def get_vrt(self):
        f = GetTempFilename(".vrt")
        band = self.get_current_band()
        gdal.BuildVRT(f, str(band.path), bandList=[band.band_index])

        return f

    def currentText(self):
        return self.comboBox_layers.currentText()


class WidgetDataIOSelectTELayerExisting(
    WidgetDataIOSelectTELayerBase, Ui_WidgetDataIOSelectTELayerExisting
):
    def __init__(self, parent=None):
        super().__init__(parent)


class WidgetDataIOSelectTELayerImport(
    WidgetDataIOSelectTELayerBase, Ui_WidgetDataIOSelectTELayerImport
):
    pass


@functools.lru_cache(
    maxsize=None
)  # not using functools.cache, as it was only introduced in Python 3.9
def _extent_as_geom(extent: typing.Tuple[float, float, float, float]):
    return qgis.core.QgsGeometry.fromRect(qgis.core.QgsRectangle(*extent))


def _check_band_overlap(aoi, raster):
    if raster.type == RasterType.ONE_FILE_RASTER:
        if aoi.calc_frac_overlap(_extent_as_geom(raster.extent)) >= 0.99:
            return True
    elif raster.type == RasterType.TILED_RASTER:
        frac = 0
        for extent in raster.extents:
            frac += aoi.calc_frac_overlap(_extent_as_geom(extent))
        if frac >= 0.99:
            return True
        else:
            return False


def _check_dataset_overlap_raster(aoi, raster_results):
    frac = 0
    for extent in raster_results.get_extents():
        this_frac = aoi.calc_frac_overlap(_extent_as_geom(extent))
        frac += this_frac
    if frac >= 0.99:
        return True
    else:
        return False


def _check_dataset_overlap_vector(aoi, vector_results):
    "Checks to see if the vector results are NOT disjoint with the aoi"
    extent = vector_results.extent
    log(f"vector extent is {extent}")
    if extent is not None:
        log(f"vector calc_disjoint is {aoi.calc_disjoint(_extent_as_geom(extent))}")
        return not aoi.calc_disjoint(_extent_as_geom(extent))
    else:
        return False


@functools.lru_cache(
    maxsize=None
)  # not using functools.cache, as it was only introduced in Python 3.9
def get_usable_datasets(
    dataset_name: typing.Optional[str] = "any", aoi=None
) -> typing.List[Dataset]:
    result = []

    for job in job_manager.relevant_jobs:
        job: Job
        is_available = job.status in (JobStatus.DOWNLOADED, JobStatus.GENERATED_LOCALLY)
        try:
            is_valid_type = ResultType(job.results.type) in [
                ResultType.RASTER_RESULTS,
                ResultType.VECTOR_RESULTS,
            ]
        except AttributeError:
            # Catch case of an invalid type

            continue

        if is_available and is_valid_type:
            if (
                ResultType(job.results.type) == ResultType.RASTER_RESULTS
                and (aoi is None or _check_dataset_overlap_raster(aoi, job.results))
                and job.script.name == dataset_name
                and job.results.uri is not None
            ):
                result.append(
                    Dataset(
                        job=job,
                        path=job.results.uri.uri,
                    )
                )
            elif (
                ResultType(job.results.type) == ResultType.VECTOR_RESULTS
                and (aoi is None or _check_dataset_overlap_vector(aoi, job.results))
                and job.results.vector.type.value == dataset_name
                and job.results.vector.uri is not None
            ):
                result.append(Dataset(job=job, path=job.results.vector.uri.uri))
    result.sort(key=lambda ub: ub.job.start_date, reverse=True)

    return result


class DlgDataIOAddLayersToMap(QtWidgets.QDialog, Ui_DlgDataIOAddLayersToMap):
    layers_view: QtWidgets.QListView
    layers_model: QtCore.QStringListModel

    def __init__(self, parent, job):
        super().__init__(parent)
        self.setupUi(self)

        self.layers_model = QtCore.QStringListModel()
        self.layers_view.setModel(self.layers_model)
        self.layers_model.setStringList([])

        self.buttonBox.accepted.connect(self.ok_clicked)
        self.buttonBox.rejected.connect(self.reject)

        self.job = job

        self.layers_model.setStringList([])

        self.update_band_list()

    def ok_clicked(self):
        band_numbers = []

        for i in self.layers_view.selectionModel().selectedRows():
            band_numbers.append(i.row() + 1)  # band numbers start at 1

        if len(band_numbers) > 0:
            job_manager.display_selected_job_results(self.job, band_numbers)
            self.close()

            # QtWidgets.QMessageBox.critical(
            #     None,
            #     tr_data_io.tr("Error"),
            #     tr_data_io.tr(f'Unable to automatically add "{band.name}". '
            #             'No style is defined for this type of layer.')
            # )
        else:
            QtWidgets.QMessageBox.critical(
                None, tr_data_io.tr("Error"), tr_data_io.tr("Select a layer to load.")
            )

    def update_band_list(self):
        self.layer_list = self.job.results.get_bands()

        band_strings = [
            f"Band {n}: {layers.get_band_title(JobBand.Schema().dump(band))}"
            for n, band in enumerate(self.layer_list, start=1)
        ]
        self.layers_model.setStringList(band_strings)
        self.layers_view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        for n in range(len(self.layer_list)):
            if self.layer_list[n].add_to_map:
                self.layers_view.selectionModel().select(
                    self.layers_model.createIndex(n, 0),
                    QtCore.QItemSelectionModel.Select,
                )


class WidgetDataIOSelectTEDatasetExisting(
    QtWidgets.QWidget, Ui_WidgetDataIOSelectTEDatasetExisting
):
    comboBox_datasets: QtWidgets.QComboBox
    dataset_list: typing.Optional[typing.List[Dataset]]
    job_selected = QtCore.pyqtSignal(uuid.UUID)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.dataset_list = None

        self.comboBox_datasets.currentIndexChanged.connect(self.selected_job_changed)

        self.NO_DATASETS_MESSAGE = tr_data_io.tr("No datasets available in this region")

    def populate(self):
        aoi = areaofinterest.prepare_area_of_interest()
        usable_datasets = get_usable_datasets(self.property("dataset_type"), aoi=aoi)
        self.dataset_list = usable_datasets
        # Ensure selected_job_changed is called only once when adding items to
        # combobox
        self.comboBox_datasets.currentIndexChanged.disconnect(self.selected_job_changed)
        old_text = self.currentText()
        self.comboBox_datasets.clear()

        if len(usable_datasets) == 0:
            self.comboBox_datasets.addItem(self.NO_DATASETS_MESSAGE)
        else:
            for i, usable_dataset in enumerate(usable_datasets):
                self.comboBox_datasets.addItem(usable_dataset.get_name_info())
                self.comboBox_datasets.setItemData(
                    i, usable_dataset.get_hover_info(), QtCore.Qt.ToolTipRole
                )

        if not self.set_index_from_text(old_text):
            self.comboBox_datasets.setCurrentIndex(0)
        self.selected_job_changed()
        # Reconnect function to fire on selected dataset change
        self.comboBox_datasets.currentIndexChanged.connect(self.selected_job_changed)

    def get_current_data_file(self) -> Path:
        return self.get_current_dataset().path

    def currentText(self):
        return self.comboBox_datasets.currentText()

    def get_current_dataset(self):
        current_dataset = self.dataset_list[self.comboBox_datasets.currentIndex()]
        if current_dataset != self.NO_DATASETS_MESSAGE:
            return current_dataset
        else:
            return None

    def get_current_extent(self):
        job = self.get_current_job()
        if job:
            if ResultType(job.results.type) == ResultType.RASTER_RESULTS:
                band = self.get_bands("any")[0]
                return qgis.core.QgsRasterLayer(
                    str(band.path), "raster file", "gdal"
                ).extent()
            elif ResultType(job.results.type) == ResultType.VECTOR_RESULTS:
                rect = qgis.core.QgsVectorLayer(
                    str(self.get_current_data_file()), "vector file", "ogr"
                ).extent()
                return (
                    rect.xMinimum(),
                    rect.yMinimum(),
                    rect.yMaximum(),
                    rect.yMaximum(),
                )

    def get_bands(self, band_name) -> Band:
        aoi = areaofinterest.prepare_area_of_interest()
        return _get_usable_bands(band_name, self.get_current_dataset().job.id, aoi=aoi)

    def set_index_from_text(self, text):
        if self.dataset_list:
            for i in range(len(self.dataset_list)):
                if self.dataset_list[i] == text:
                    self.comboBox_datasets.setCurrentIndex(i)

                    return True

        return False

    def get_current_job(self):
        current_dataset = self.get_current_dataset()
        if current_dataset:
            return current_dataset.job
        else:
            return None

    def selected_job_changed(self):
        if len(self.dataset_list) >= 1:
            current_job = self.get_current_job()
            if current_job:
                job_id = current_job.id
            else:
                job_id = None
            self.job_selected.emit(job_id)
