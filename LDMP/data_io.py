# -*- coding: utf-8 -*-
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
import os
import typing
import uuid
from pathlib import Path

import json

from PyQt5 import (
    QtCore,
    QtWidgets,
)
from PyQt5.QtCore import QSettings

import qgis.core
import qgis.utils


import numpy as np

from osgeo import (
    gdal,
    osr,
)

from . import (
    conf,
    GetTempFilename,
    layers,
    worker,
)
from .gui.DlgDataIO import Ui_DlgDataIO
from .gui.DlgDataIOLoadTE import Ui_DlgDataIOLoadTE
from .gui.DlgDataIOLoadTESingleLayer import Ui_DlgDataIOLoadTESingleLayer
from .gui.DlgDataIOImportLC import Ui_DlgDataIOImportLC
from .gui.DlgDataIOImportSOC import Ui_DlgDataIOImportSOC
from .gui.DlgDataIOImportProd import Ui_DlgDataIOImportProd
from .gui.DlgJobsDetails import Ui_DlgJobsDetails
from .gui.WidgetDataIOImportSelectFileInput import Ui_WidgetDataIOImportSelectFileInput
from .gui.WidgetDataIOImportSelectRasterOutput import Ui_WidgetDataIOImportSelectRasterOutput
from .gui.WidgetDataIOSelectTELayerExisting import Ui_WidgetDataIOSelectTELayerExisting
from .gui.WidgetDataIOSelectTELayerImport import Ui_WidgetDataIOSelectTELayerImport
from .gui.WidgetDataIOSelectTEDatasetExisting import Ui_WidgetDataIOSelectTEDatasetExisting
from .jobs.manager import job_manager
from .jobs import models as job_models
from .logger import log

mb = qgis.utils.iface.messageBar()


@dataclasses.dataclass()
class UsableBandInfo:
    job: job_models.Job
    path: Path
    band_index: int
    band_info: job_models.JobBand


@dataclasses.dataclass()
class UsableDatasetInfo:
    job: job_models.Job
    path: Path


class RemapVectorWorker(worker.AbstractWorker):
    def __init__(self, l, out_file, attribute, remap_dict, in_data_type, 
                 out_res, out_data_type=gdal.GDT_Int16):
        worker.AbstractWorker.__init__(self)

        self.l = l
        self.out_file = out_file
        self.attribute = attribute
        self.remap_dict = remap_dict
        self.in_data_type = in_data_type
        self.out_res = out_res
        self.out_data_type = out_data_type

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        crs_src_string = self.l.crs().toProj()
        crs_src = qgis.core.QgsCoordinateReferenceSystem()
        crs_src.createFromProj(crs_src_string)
        crs_dst = qgis.core.QgsCoordinateReferenceSystem('epsg:4326')
        t = qgis.core.QgsCoordinateTransform(
            crs_src, crs_dst, qgis.core.QgsProject.instance())

        l_out = qgis.core.QgsVectorLayer(
            u"{datatype}?crs=proj4:{crs}".format(datatype=self.in_data_type, crs=crs_dst.toProj()),
            "land cover (transformed)",
            "memory"
        )
        l_out.dataProvider().addAttributes(
            [qgis.core.QgsField('code', QtCore.QVariant.Int)])
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
                self.progress.emit(100 * float(n)/self.l.featureCount())
                feats = []
        if not l_out.isValid():
            log(u'Error remapping and transforming vector layer from "{}" to "{}")'.format(crs_src_string, crs_dst.toProj()))
            return None

        # Write l_out to a shapefile for usage by gdal rasterize
        temp_shp = GetTempFilename('.shp')
        log(u'Writing temporary shapefile to {}'.format(temp_shp))
        err = qgis.core.QgsVectorFileWriter.writeAsVectorFormat(
            l_out, temp_shp, "UTF-8", crs_dst, "ESRI Shapefile")
        if err != qgis.core.QgsVectorFileWriter.NoError:
            log(u'Error writing layer to {}'.format(temp_shp))
            return None

        log('Rasterizing...')
        res = gdal.Rasterize(self.out_file, temp_shp,
                             format='GTiff',
                             xRes=self.out_res, yRes=-self.out_res,
                             noData=-32768, attribute='code',
                             outputSRS="epsg:4326",
                             outputType=self.out_data_type,
                             creationOptions=['COMPRESS=LZW'],
                             callback=self.progress_callback)
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
    def __init__(self, in_file, out_file, out_res, 
                 attribute, out_data_type=gdal.GDT_Int16):
        worker.AbstractWorker.__init__(self)

        self.in_file = in_file
        self.out_file = out_file

        self.out_res = out_res
        self.out_data_type = out_data_type
        self.attribute = attribute

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        res = gdal.Rasterize(self.out_file, self.in_file,
                             format='GTiff',
                             xRes=self.out_res, yRes=-self.out_res,
                             noData=-32768, attribute=self.attribute,
                             outputSRS="epsg:4326",
                             outputType=self.out_data_type,
                             creationOptions=['COMPRESS=LZW'],
                             callback=self.progress_callback)
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
    def __init__(self, in_file, out_file, out_res, 
                 resample_mode, out_data_type=gdal.GDT_Int16):
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
            res = gdal.Warp(self.out_file, self.in_file, format='GTiff',
                            xRes=self.out_res, yRes=-self.out_res,
                            dstNodata=-32768,
                            dstSRS="epsg:4326",
                            outputType=self.out_data_type,
                            resampleAlg=self.resample_mode,
                            creationOptions=['COMPRESS=LZW'],
                            callback=self.progress_callback)
        else:
            res = gdal.Warp(self.out_file, self.in_file, format='GTiff',
                            dstNodata=-32768,
                            dstSRS="epsg:4326",
                            outputType=self.out_data_type,
                            resampleAlg=self.resample_mode,
                            creationOptions=['COMPRESS=LZW'],
                            callback=self.progress_callback)
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
        ds_out = driver.Create(self.out_file, xsize, ysize, 1, gdal.GDT_Int16, 
                               ['COMPRESS=LZW'])
        src_gt = ds_in.GetGeoTransform()
        ds_out.SetGeoTransform(src_gt)
        out_srs = osr.SpatialReference()
        out_srs.ImportFromWkt(ds_in.GetProjectionRef())
        ds_out.SetProjection(out_srs.ExportToWkt())


        blocks = 0
        for y in range(0, ysize, y_block_size):
            if self.killed:
                log(u"Processing of {} killed by user after processing {} out of {} blocks.".format(deg_file, y, ysize))
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
                    for value, replacement in zip(self.remap_list[0], self.remap_list[1]):
                        d[d == int(value)] = int(replacement)
                ds_out.GetRasterBand(1).WriteArray(d, x, y)
                blocks += 1

        if self.killed:
            del ds_out
            os.remove(out_file)
            return None
        else:
            return True


def get_unique_values_vector(l, field, max_unique=100):
    idx = l.fields().lookupField(field)
    values = l.uniqueValues(idx)
    if len(values) > max_unique:
        return None
    else:
        return values


def _get_min_max_tuple(values, min_min, max_max, nodata):
    values[values < nodata] = np.nan
    mn = np.nanmin(values)
    if mn < min_min:
        return None
    mx = np.nanmax(values)
    if mx > max_max:
        return None
    return (mn, mx)


def get_vector_stats(l, attribute, min_min=0, max_max=1000, nodata=0):
    values = np.asarray([feat.attribute(attribute) for feat in l.getFeatures()], dtype=np.float32)
    return _get_min_max_tuple(values, min_min, max_max, nodata)


def get_raster_stats(f, band_num, sample=True, min_min=0, max_max=1000, nodata=0):
    # Note that anything less than nodata value is considered no data
    if sample:
        # Note need float to correctly mark and ignore nodata for for nanmin 
        # and nanmax 
        values = layers.get_sample(f, band_num, n=1e6).astype('float32')
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

                d = b.ReadAsArray(x, y, cols, rows).ravel()
                mn, mx = _get_min_max_tuple(values, min_min, max_max, nodata)
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
                    v = np.unique(np.concatenate((v, b.ReadAsArray(x, y, cols, rows).ravel())))

                if v.size > max_unique:
                    return None
        return v.tolist()


class DlgJobsDetails(QtWidgets.QDialog, Ui_DlgJobsDetails):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgJobsDetails, self).__init__(parent)

        self.setupUi(self)
        self.task_status.hide()
        self.statusLabel.hide()

class DlgDataIO(QtWidgets.QDialog, Ui_DlgDataIO):
    def __init__(self, parent=None):
        super(DlgDataIO, self).__init__(parent)

        self.setupUi(self)

        self.dlg_DataIOLoad_te = DlgDataIOLoadTE()
        self.dlg_DataIOLoad_lc = DlgDataIOImportLC()
        self.dlg_DataIOLoad_soc = DlgDataIOImportSOC()
        self.dlg_DataIOLoad_prod = DlgDataIOImportProd()

        self.btn_te.clicked.connect(self.run_te)
        self.btn_lc.clicked.connect(self.run_lc)
        self.btn_soc.clicked.connect(self.run_soc)
        self.btn_prod.clicked.connect(self.run_prod)

    def run_te(self):
        self.close()
        self.dlg_DataIOLoad_te.exec_()

    def run_lc(self):
        self.close()
        self.dlg_DataIOLoad_lc.exec_()

    def run_soc(self):
        self.close()
        self.dlg_DataIOLoad_soc.exec_()

    def run_prod(self):
        self.close()
        self.dlg_DataIOLoad_prod.exec_()

class DlgDataIOLoadTEBase(QtWidgets.QDialog):
    layers_view: QtWidgets.QListView
    layers_model: QtCore.QStringListModel

    layers_loaded = QtCore.pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.layers_model = QtCore.QStringListModel()
        self.layers_view.setModel(self.layers_model)
        self.layers_model.setStringList([])

        self.buttonBox.accepted.connect(self.ok_clicked)
        self.buttonBox.rejected.connect(self.reject)

    def ok_clicked(self):
        rows = []
        for i in self.layers_view.selectionModel().selectedRows():
            rows.append(i.row())
        if len(rows) > 0:
            added_layers = []
            for row in rows:
                f = os.path.normcase(os.path.normpath(self.layer_list[row][0]))
                # Note that the third item in the tuple is the band number, and 
                # the fourth (layer_list[3]) is the band info object
                resp = layers.add_layer(
                    f, self.layer_list[row][2], self.layer_list[row][3], activated=True)
                if resp:
                    added_layers.append(self.layer_list[row])
                else:
                    QtWidgets.QMessageBox.critical(None, self.tr("Error"), 
                                                   self.tr(u'Unable to automatically add "{}". No style is defined for this type of layer.'.format(self.layer_list[row][2]['name'])))
            self.layers_loaded.emit(added_layers)
        else:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr("Select a layer to load."))
            return

        self.close()


class DlgDataIOLoadTE(QtWidgets.QDialog, Ui_DlgDataIOLoadTE):
    file_browse_btn: QtWidgets.QPushButton
    file_lineedit: QtWidgets.QLineEdit
    parsed_name_la: QtWidgets.QLabel
    parsed_name_le: QtWidgets.QLineEdit
    parsed_result_la: QtWidgets.QLabel
    parsed_result_path_le: QtWidgets.QLineEdit

    buttonBox: QtWidgets.QDialogButtonBox

    job: typing.Optional[job_models.Job]


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
        self.parsed_name_le.setText(job_manager.get_job_basename(self.job))
        self.parsed_name_le.setEnabled(True)
        self.parsed_result_la.setEnabled(True)
        try:
            local_path = str(self.job.results.local_paths[0])
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
                    self, self.tr("Could not load file"), error_message)

    def parse_chosen_path(
            self, raw_path: str) -> typing.Tuple[typing.Optional[job_models.Job], str]:
        path = Path(raw_path)
        job = None
        error_message = ""
        if path.is_file():
            try:
                raw_job = json.loads(path.read_text())
                job = job_models.Job.deserialize(raw_job)
            except json.JSONDecodeError:
                error_message = "Could not parse the selected file into a valid JSON"
        return job, error_message

    def ok_clicked(self):
        log("Importing job...")
        job_manager.import_job(self.job)
        self.accept()


class DlgDataIOLoadTESingleLayer(DlgDataIOLoadTEBase, Ui_DlgDataIOLoadTESingleLayer):
    def __init__(self, parent=None):
        super(DlgDataIOLoadTESingleLayer, self).__init__(parent)

    def update_layer_list(self, layers):
        self.layer_list = layers
        bands = [layer[1] for layer in layers]
        self.layers_model.setStringList(bands)
        self.layers_view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)


class ImportSelectFileInputWidget(QtWidgets.QWidget, Ui_WidgetDataIOImportSelectFileInput):
    inputFileChanged = QtCore.pyqtSignal(bool)
    inputTypeChanged = QtCore.pyqtSignal(bool)

    def __init__(self, parent=None):
        super(ImportSelectFileInputWidget, self).__init__(parent)
        self.setupUi(self)

        self.radio_raster_input.toggled.connect(self.radio_raster_input_toggled)

        self.btn_raster_dataset_browse.clicked.connect(self.open_raster_browse)
        self.btn_polygon_dataset_browse.clicked.connect(self.open_vector_browse)

        self.groupBox_output_resolution.clicked.connect(self.output_res_toggled)

        # Ensure the special value text (set to " ") is displayed by default
        self.spinBox_data_year.setSpecialValueText(' ')
        self.spinBox_data_year.setValue(self.spinBox_data_year.minimum())

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
                has_file=True
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
        raster_file, _ = QtWidgets.QFileDialog.getOpenFileName(self,
                                                        self.tr('Select a raster input file'),
                                                        initial_file,
                                                        self.tr('Raster file (*.tif *.dat *.img)'))
        # Try loading this raster to verify the file works
        if raster_file:
            self.update_raster_layer(raster_file)

    def update_raster_layer(self, raster_file):
        l = qgis.core.QgsRasterLayer(raster_file, "raster file", "gdal")

        if not os.access(raster_file, os.R_OK or not l.isValid()):
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr(u"Cannot read {}. Choose a different file.".format(raster_file)))
            self.inputFileChanged.emit(False)
            return False
        else:
            QSettings().setValue("LDMP/input_dir", os.path.dirname(raster_file))
            self.lineEdit_raster_file.setText(raster_file)
            self.comboBox_bandnumber.clear()
            self.comboBox_bandnumber.addItems([str(n) for n in range(1, l.dataProvider().bandCount() + 1)])

            self.inputFileChanged.emit(True)
            return True

    def open_vector_browse(self):
        if self.lineEdit_vector_file.text():
            initial_file = self.lineEdit_vector_file.text()
        else:
            initial_file = QSettings().value("LDMP/input_dir", None)
        vector_file, _ = QtWidgets.QFileDialog.getOpenFileName(self,
                                                        self.tr('Select a vector input file'),
                                                        initial_file,
                                                        self.tr('Vector file (*.shp *.kml *.kmz *.geojson)'))
        # Try loading this vector to verify the file works
        if vector_file:
            self.update_vector_layer(vector_file)

    def update_vector_layer(self, vector_file):
        l = qgis.core.QgsVectorLayer(vector_file, "vector file", "ogr")

        if not os.access(vector_file, os.R_OK) or not l.isValid():
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr(u"Cannot read {}. Choose a different file.".format(vector_file)))
            self.inputFileChanged.emit(False)
            return False
        else:
            QSettings().setValue("LDMP/input_dir", os.path.dirname(vector_file))
            self.lineEdit_vector_file.setText(vector_file)
            self.comboBox_fieldname.clear()
            self.inputFileChanged.emit(True)
            self.comboBox_fieldname.addItems([field.name() for field in l.dataProvider().fields()])
            return True

    def get_vector_layer(self):
        return qgis.core.QgsVectorLayer(
            self.lineEdit_vector_file.text(), "vector file", "ogr")


class ImportSelectRasterOutput(QtWidgets.QWidget, Ui_WidgetDataIOImportSelectRasterOutput):
    def __init__(self, parent=None):
        super(ImportSelectRasterOutput, self).__init__(parent)

        self.setupUi(self)

        self.btn_output_file_browse.clicked.connect(self.save_raster)

    def save_raster(self):
        if self.lineEdit_output_file.text():
            initial_file = self.lineEdit_output_file.text()
        else:
            initial_file = conf.settings_manager.get_value(conf.Setting.BASE_DIR)
        raw_output_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            self.tr('Choose a name for the output file'),
            initial_file,
            self.tr('Raster file (*.tif)')
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
                    self.tr("Error"),
                    self.tr(u"Cannot write to {}. Choose a different file.".format(
                        raw_output_path))
                )
                return False


class DlgDataIOImportBase(QtWidgets.QDialog):
    """Base class for individual data loading dialogs"""

    input_widget: ImportSelectFileInputWidget

    layer_loaded = QtCore.pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.input_widget = ImportSelectFileInputWidget()
        self.verticalLayout.insertWidget(0, self.input_widget)

        # The datatype determines whether the dataset resampling is done with 
        # nearest neighbor and mode or nearest neighbor and mean
        self.datatype = 'categorical'

    def validate_input(self, value):
        if self.input_widget.radio_raster_input.isChecked():
            if self.input_widget.lineEdit_raster_file.text() == '':
                QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr("Choose an input raster file."))
                return
        else:
            in_file = self.input_widget.lineEdit_vector_file.text()
            if in_file  == '':
                QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr("Choose an input polygon dataset."))
                return
            l = self.input_widget.get_vector_layer()
            if l.wkbType() == qgis.core.QgsWkbTypes.Polygon or l.wkbType() == qgis.core.QgsWkbTypes.MultiPolygon:
                self.vector_datatype = "polygon"
            elif l.wkbType() == qgis.core.QgsWkbTypes.Point:
                self.vector_datatype = "point"
            else:
                QtWidgets.QMessageBox.critical(None,
                                               self.tr("Error"),
                                               self.tr(u"Cannot process {}. Unknown geometry type:{}".format(in_file, l.wkbType())))
                log(u"Failed to process {} - unknown geometry type {}.".format(in_file, l.wkbType()))
                return

        return True

    def get_resample_mode(self, f):
        in_res = self.get_in_res_wgs84()
        out_res = self.get_out_res_wgs84()
        if in_res < out_res:
            if self.datatype == 'categorical':
                log(u'Resampling with mode (in res: {}, out_res: {}'.format(in_res, out_res))
                return gdal.GRA_Mode
            elif self.datatype == 'continuous':
                log(u'Resampling with average (in res: {}, out_res: {}'.format(in_res, out_res))
                return gdal.GRA_Average
            else:
                raise ValueError('Unknown datatype')
        else:
            # If output resolution is finer than the original data, use nearest 
            # neighbor
            log(u'Resampling with nearest neighbor (in res: {}, out_res: {}'.format(in_res, out_res))
            return gdal.GRA_NearestNeighbour

    def get_in_res_wgs84(self):
        ds_in = gdal.Open(self.input_widget.lineEdit_raster_file.text())
        wgs84_srs = osr.SpatialReference()
        wgs84_srs.ImportFromEPSG(4326)

        in_srs = osr.SpatialReference()
        in_srs.ImportFromWkt(ds_in.GetProjectionRef())

        tx = osr.CoordinateTransformation(
            in_srs, wgs84_srs, qgis.core.QgsProject.instance())

        geo_t = ds_in.GetGeoTransform()
        x_size = ds_in.RasterXSize
        y_size = ds_in.RasterYSize
        # Work out the boundaries of the new dataset in the target projection
        (ulx, uly, ulz) = tx.TransformPoint(geo_t[0], geo_t[3])
        (lrx, lry, lrz) = tx.TransformPoint(geo_t[0] + geo_t[1]*x_size, \
                                                     geo_t[3] + geo_t[5]*y_size)
        log(u'ulx: {}, uly: {}, ulz: {}'.format(ulx, uly, ulz))
        log(u'lrx: {}, lry: {}, lrz: {}'.format(lrx, lry, lrz))
        # As an approximation of what the output res would be in WGS4, use an 
        # average of the x and y res of this image
        return ((lrx - ulx)/float(x_size) + (lry - uly)/float(y_size)) / 2

    def get_out_res_wgs84(self):
        # Calculate res in degrees from input which is in meters
        res = int(self.input_widget.spinBox_resolution.value())
        return res / (111.325 * 1000) # 111.325km in one degree

    def remap_vector(self, l, out_file, remap_dict, attribute):
        out_res = self.get_out_res_wgs84()
        log(u'Remapping and rasterizing {} using output resolution {}, and field "{}"'.format(out_file, out_res, attribute))
        log(u'Remap dict "{}"'.format(remap_dict))
        remap_vector_worker = worker.StartWorker(
            RemapVectorWorker,
            'rasterizing and remapping values',
            l,
            out_file,
            attribute,
            remap_dict,
            self.vector_datatype,
            out_res
        )
        if not remap_vector_worker.success:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Vector remapping failed."))
            return False
        else:
            return True

    def remap_raster(self, in_file, out_file, remap_list):
        # First warp the raster to the correct CRS
        temp_tif = GetTempFilename('.tif')
        warp_ret = self.warp_raster(temp_tif)
        if not warp_ret:
            return False

        remap_raster_worker = worker.StartWorker(
            RemapRasterWorker, 'remapping values', temp_tif, out_file, remap_list)
        os.remove(temp_tif)
        if not remap_raster_worker.success:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Raster remapping failed."))
            return False
        else:
            return True

    def rasterize_vector(self, in_file, out_file, attribute):
        out_res = self.get_out_res_wgs84()
        log(u'Rasterizing {} using output resolution {}, and field "{}"'.format(out_file, out_res, attribute))
        rasterize_worker = worker.StartWorker(
            RasterizeWorker, 'rasterizing vector file', in_file,
            out_file, out_res, attribute
        )
        if not rasterize_worker.success:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Rasterizing failed."))
            return False
        else:
            return True

    def warp_raster(self, out_file):
        # Select a single output band
        in_file = self.input_widget.lineEdit_raster_file.text()
        band_number = int(self.input_widget.comboBox_bandnumber.currentText())
        temp_vrt = GetTempFilename('.vrt')
        gdal.BuildVRT(temp_vrt, in_file, bandList=[band_number])
                      
        log(u'Importing {} to {}'.format(in_file, out_file))
        if self.input_widget.groupBox_output_resolution.isChecked():
            out_res = self.get_out_res_wgs84()
            resample_mode = self.get_resample_mode(temp_vrt)
        else:
            out_res = None
            resample_mode = gdal.GRA_NearestNeighbour
        raster_import_worker = worker.StartWorker(
            RasterImportWorker, 'importing raster', temp_vrt,
            out_file, out_res, resample_mode
        )
        os.remove(temp_vrt)
        if not raster_import_worker.success:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Raster import failed."))
            return False
        else:
            return True


class DlgDataIOImportLC(DlgDataIOImportBase, Ui_DlgDataIOImportLC):

    def __init__(self, parent=None):
        super().__init__(parent)

        # This needs to be inserted after the lc definition widget but before 
        # the button box with ok/cancel
        self.output_widget = ImportSelectRasterOutput()
        self.verticalLayout.insertWidget(2, self.output_widget)

        self.input_widget.inputFileChanged.connect(self.input_changed)
        self.input_widget.inputTypeChanged.connect(self.input_changed)

        self.checkBox_use_sample.stateChanged.connect(self.clear_dlg_agg)

        self.btn_agg_edit_def.clicked.connect(self.agg_edit)
        self.btn_agg_edit_def.setEnabled(False)

        self.dlg_agg = None

    def showEvent(self, event):
        super(DlgDataIOImportLC, self).showEvent(event)

        # Reset flags to avoid reloading of unique values when files haven't 
        # changed:
        self.last_raster = None
        self.last_band_number = None
        self.last_vector = None
        self.idx = None

    def done(self, value):
        if value == QtWidgets.QDialog.Accepted:
            self.validate_input(value)
        else:
            super().done(value)

    def validate_input(self, value):
        if self.output_widget.lineEdit_output_file.text() == '':
            QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr("Choose an output file."))
            return
        if  not self.dlg_agg:
            QtWidgets.QMessageBox.information(None, self.tr("No definition set"), self.tr('Click "Edit Definition" to define the land cover definition before exporting.', None))
            return
        if self.input_widget.spinBox_data_year.text() == self.input_widget.spinBox_data_year.specialValueText():
            QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr(u"Enter the year of the input data."))
            return

        ret = super(DlgDataIOImportLC, self).validate_input(value)
        if not ret:
            return

        super(DlgDataIOImportLC, self).done(value)

        self.ok_clicked()

    def clear_dlg_agg(self):
        self.dlg_agg = None

    def input_changed(self, valid):
        if valid:
            self.btn_agg_edit_def.setEnabled(True)
        else:
            self.btn_agg_edit_def.setEnabled(False)
        self.clear_dlg_agg()
        if self.input_widget.radio_raster_input.isChecked():
            self.checkBox_use_sample.setEnabled(True)
            self.checkBox_use_sample_description.setEnabled(True)
        else:
            self.checkBox_use_sample.setEnabled(False)
            self.checkBox_use_sample_description.setEnabled(False)

    def load_agg(self, values):
        # Set all of the classes to no data by default
        classes = [{'Initial_Code':value, u'Initial_Label':str(value), 'Final_Label':'No data', 'Final_Code':-32768} for value in sorted(values)]
        #TODO Fix on refactor
        from LDMP.lc_setup import DlgCalculateLCSetAggregation
        self.dlg_agg = DlgCalculateLCSetAggregation(classes, parent=self)

    def agg_edit(self):
        if self.input_widget.radio_raster_input.isChecked():
            f = self.input_widget.lineEdit_raster_file.text()
            band_number = int(self.input_widget.comboBox_bandnumber.currentText())
            if not self.dlg_agg or \
                    (self.last_raster != f or self.last_band_number != band_number):
                values = get_unique_values_raster(f, int(self.input_widget.comboBox_bandnumber.currentText()), self.checkBox_use_sample.isChecked())
                if not values:
                    QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr("Error reading data. Trends.Earth supports a maximum of 60 different land cover classes"))
                    return
                self.last_raster = f
                self.last_band_number = band_number
                self.load_agg(values)
        else:
            f = self.input_widget.lineEdit_vector_file.text()
            l = self.input_widget.get_vector_layer()
            idx = l.fields().lookupField(self.input_widget.comboBox_fieldname.currentText())
            if not self.dlg_agg or \
                    (self.last_vector != f or self.last_idx != idx):
                values = get_unique_values_vector(l, self.input_widget.comboBox_fieldname.currentText())
                if not values:
                    QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr("Error reading data. Trends.Earth supports a maximum of 60 different land cover classes"))
                    return
                self.last_vector = f
                self.last_idx = idx
                self.load_agg(values)
        self.dlg_agg.exec_()

    def ok_clicked(self):
        out_file = self.output_widget.lineEdit_output_file.text()
        if self.input_widget.radio_raster_input.isChecked():
            in_file = self.input_widget.lineEdit_raster_file.text()
            #TODO: Fix this for new nesting format
            remap_ret = self.remap_raster(in_file, out_file, self.dlg_agg.get_agg_as_list())
        else:
            attribute = self.input_widget.comboBox_fieldname.currentText()
            l = self.input_widget.get_vector_layer()
            remap_ret = self.remap_vector(l,
                                          out_file, 
            #TODO: Fix this for new nesting format
                                          self.dlg_agg.get_agg_as_dict(), 
                                          attribute)
        if not remap_ret:
            return False

        job = job_manager.create_job_from_dataset(
            Path(out_file),
            "Land cover (7 class)",
            {
                'year': int(self.input_widget.spinBox_data_year.text()),
                'source': 'custom data'
            }
        )
        job_manager.import_job(job)


class DlgDataIOImportSOC(DlgDataIOImportBase, Ui_DlgDataIOImportSOC):
    def __init__(self, parent=None):
        super().__init__(parent)

        # This needs to be inserted after the input widget but before the 
        # button box with ok/cancel
        self.output_widget = ImportSelectRasterOutput()
        self.verticalLayout.insertWidget(1, self.output_widget)
        self.datatype = 'continuous'

    def done(self, value):
        if value == QtWidgets.QDialog.Accepted:
            self.validate_input(value)
        else:
            super(DlgDataIOImportSOC, self).done(value)

    def validate_input(self, value):
        if self.output_widget.lineEdit_output_file.text() == '':
            QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr("Choose an output file."))
            return
        if self.input_widget.spinBox_data_year.text() == self.input_widget.spinBox_data_year.specialValueText():
            QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr(u"Enter the year of the input data."))
            return

        ret = super(DlgDataIOImportSOC, self).validate_input(value)
        if not ret:
            return
        
        if self.input_widget.radio_raster_input.isChecked():
            in_file = self.input_widget.lineEdit_raster_file.text()
            stats = get_raster_stats(in_file, int(self.input_widget.comboBox_bandnumber.currentText()))
        else:
            in_file = self.input_widget.lineEdit_vector_file.text()
            l = self.input_widget.get_vector_layer()
            field = self.input_widget.comboBox_fieldname.currentText()
            idx = l.fields().lookupField(field)
            if not l.fields().field(idx).isNumeric():
                QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr(u"The chosen field ({}) is not numeric. Choose a numeric field.".format(field)))
                return
            else:
                stats = get_vector_stats(self.input_widget.get_vector_layer(), field)
        log(u'Stats are: {}'.format(stats))
        if not stats:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr(u"The input file ({}) does not appear to be a valid soil organic carbon input file. The file should contain values of soil organic carbon in tonnes / hectare.".format(in_file)))
            return
        if stats[0] < 0:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr(u"The input file ({}) does not appear to be a valid soil organic carbon input file. The minimum value in this file is {}. The no data value should be -32768, and all other values should be >= 0.".format(in_file, stats[0])))
            return
        if stats[1] > 1000:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr(u"The input file ({}) does not appear to be a valid soil organic carbon input file. The maximum value in this file is {}. The maximum value allowed is 1000 tonnes / hectare.".format(in_file, stats[1])))
            return

        super(DlgDataIOImportSOC, self).done(value)

        self.ok_clicked()

    def ok_clicked(self):
        out_file = self.output_widget.lineEdit_output_file.text()
        if self.input_widget.radio_raster_input.isChecked():
            ret = self.warp_raster(out_file)
        else:
            in_file = self.input_widget.lineEdit_vector_file.text()
            attribute = self.input_widget.comboBox_fieldname.currentText()
            ret = self.rasterize_vector(in_file, out_file, attribute)

        if not ret:
            return False

        job = job_manager.create_job_from_dataset(
            Path(out_file),
            "Soil organic carbon",
            {
                'year': int(self.input_widget.spinBox_data_year.text()),
                'source': 'custom data'
            }
        )
        job_manager.import_job(job)


class DlgDataIOImportProd(DlgDataIOImportBase, Ui_DlgDataIOImportProd):
    output_widget: ImportSelectRasterOutput

    def __init__(self, parent=None):
        super().__init__(parent)

        # This needs to be inserted after the input widget but before the 
        # button box with ok/cancel
        self.output_widget = ImportSelectRasterOutput()
        self.verticalLayout.insertWidget(1, self.output_widget)

        self.input_widget.groupBox_year.hide()

    def done(self, value):
        if value == QtWidgets.QDialog.Accepted:
            self.validate_input(value)
        else:
            super(DlgDataIOImportProd, self).done(value)

    def validate_input(self, value):
        if self.output_widget.lineEdit_output_file.text() == '':
            QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr("Choose an output file."))
            return

        ret = super().validate_input(value)
        if not ret:
            return

        if self.input_widget.radio_raster_input.isChecked():
            in_file = self.input_widget.lineEdit_raster_file.text()
            values = get_unique_values_raster(in_file, int(self.input_widget.comboBox_bandnumber.currentText()), max_unique=7)
        else:
            in_file = self.input_widget.lineEdit_vector_file.text()
            l = self.input_widget.get_vector_layer()
            field = self.input_widget.comboBox_fieldname.currentText()
            idx = l.fields().lookupField(field)
            if not l.fields().field(idx).isNumeric():
                QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr(u"The chosen field ({}) is not numeric. Choose a field that contains numbers.".format(field)))
                return
            else:
                values = get_unique_values_vector(l, field, max_unique=7)
        if not values:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"), self.tr(u"The input file ({}) does not appear to be a valid productivity input file.".format(in_file)))
            return
        invalid_values = [v for v in values if v not in [-32768, 0, 1, 2, 3, 4, 5]]
        if len(invalid_values) > 0:
            QtWidgets.QMessageBox.warning(None, self.tr("Warning"), self.tr(u"The input file ({}) does not appear to be a valid productivity input file. Trends.Earth will load the file anyway, but review the map once it has loaded to ensure the values make sense. The only values allowed in a productivity input file are -32768, 1, 2, 3, 4 and 5. There are {} value(s) in the input file that were not recognized.".format(in_file, len(invalid_values))))

        super().done(value)

        self.ok_clicked()

    def ok_clicked(self):
        out_file = self.output_widget.lineEdit_output_file.text()
        if self.input_widget.radio_raster_input.isChecked():
            ret = self.warp_raster(out_file)
        else:
            in_file = self.input_widget.lineEdit_vector_file.text()
            attribute = self.input_widget.comboBox_fieldname.currentText()
            ret = self.rasterize_vector(in_file, out_file, attribute)

        if not ret:
            return False

        job = job_manager.create_job_from_dataset(
            Path(out_file),
            "Land Productivity Dynamics (LPD)",
            {
                "source": "custom data"
            }
        )
        job_manager.import_job(job)


def _get_layers(node):
    l = []
    if isinstance(node, qgis.core.QgsLayerTreeGroup):
        for child in node.children():
            if isinstance(child, qgis.core.QgsLayerTreeLayer):
                l.append(child.layer())
            else:
                l.extend(_get_layers(child))
    else:
        l = node
    return l


def get_usable_bands(
        band_name: typing.Optional[str] = "any",
        selected_job_id: uuid.UUID = None,
) -> typing.List[UsableBandInfo]:
    result = []
    for job in job_manager.relevant_jobs:
        job: job_models.Job
        is_downloaded = job.status == job_models.JobStatus.DOWNLOADED
        is_of_interest = (selected_job_id is None) or (job.id == selected_job_id)
        is_valid_type = job.results.type in (job_models.JobResult.CLOUD_RESULTS,
                                             job_models.JobResult.LOCAL_RESULTS)
        if is_downloaded and is_of_interest and is_valid_type:
            path = job.results.local_paths[0]
            for band_index, band_info in enumerate(job.results.bands):
                if band_info.name == band_name:
                    result.append(
                        UsableBandInfo(
                            job=job,
                            path=path,
                            band_index=band_index+1,
                            band_info=band_info
                        )
                    )
    result.sort(key=lambda ub: ub.job.start_date, reverse=True)
    return result

    
class WidgetDataIOSelectTELayerBase(QtWidgets.QWidget):
    comboBox_layers: QtWidgets.QComboBox
    dlg_layer: DlgDataIOLoadTESingleLayer
    layer_list: typing.Optional[typing.List[UsableBandInfo]]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.dlg_layer = DlgDataIOLoadTESingleLayer()

        self.dlg_layer.layers_loaded.connect(self.populate)

        self.layer_list = None

    def populate(self, selected_job_id=None):
        usable_bands = get_usable_bands(self.property("layer_type"), selected_job_id)
        self.layer_list = usable_bands
        old_text = self.currentText()
        self.comboBox_layers.clear()
        self.comboBox_layers.addItem('')
        i = 0
        for usable_band in usable_bands:
            task_name = usable_band.job.params.task_name
            if task_name != "":
                name_info_parts = [task_name]
            else:
                name_info_parts = []
            hover_info_parts = name_info_parts[:]
            name_info_parts.extend(
                [
                    usable_band.band_info.name,
                    usable_band.job.params.task_notes.local_context.area_of_interest_name
                ]
            )
            hover_info_parts.extend(
                [
                    usable_band.band_info.name + ' - ',
                    usable_band.job.params.task_notes.local_context.area_of_interest_name + '\n',
                    usable_band.job.start_date.strftime("%Y-%m-%d %H:%M") + '\n',
                    # TODO: figure out a way to cleanup the metadata so it is 
                    # presentable and useful - likely need to have each script 
                    # contain a dictionary of metadata fields that should be 
                    # shown to the user by default
                    #str(usable_band.band_info.metadata),
                ]
            )
            self.comboBox_layers.addItem(" - ".join(name_info_parts))
            # the "+ 1" below is to account for blank entry at the beginning of 
            # the combobox
            self.comboBox_layers.setItemData(i + 1, "".join(hover_info_parts), QtCore.Qt.ToolTipRole)
            i += 1
        if not self.set_index_from_text(old_text):
            # Set current index to 1 so that the blank line isn't chosen by 
            # default
            self.comboBox_layers.setCurrentIndex(1)

    def get_data_file(self) -> Path:
        current_index = self.comboBox_layers.currentIndex()
        current_usable_band_info = self.layer_list[current_index]
        return current_usable_band_info.path

    def get_layer(self) -> qgis.core.QgsRasterLayer:
        return qgis.core.QgsRasterLayer(
            str(self.get_data_file()), "raster file", "gdal")

    def get_usable_band_info(self) -> UsableBandInfo:
        return self.layer_list[self.comboBox_layers.currentIndex()]

    def get_band_info(self):
        usable_band_info = self.get_usable_band_info()
        return usable_band_info.band_info

    def set_index_from_job_id(self, job_id):
        if self.layer_list:
            for i in range(len(self.layer_list)):
                if self.layer_list[i].job.id == job_id:
                    # the "+ 1" below is to account for blank entry
                    # at the beginning of the combobox
                    self.comboBox_layers.setCurrentIndex(i + 1)
                    return True
        return False

    def set_index_from_text(self, text):
        if self.layer_list:
            for i in range(len(self.layer_list)):
                if self.layer_list[i] == text:
                    # the "+ 1" below is to account for blank entry
                    # at the beginning of the combobox
                    self.comboBox_layers.setCurrentIndex(i + 1)
                    return True
        return False

    def get_vrt(self):
        f = GetTempFilename('.vrt')
        usable_band_info = self.get_usable_band_info()
        gdal.BuildVRT(
            f,
            str(usable_band_info.path),
            bandList=[usable_band_info.band_index]
        )
        return f

    def currentText(self):
        return self.comboBox_layers.currentText()


class WidgetDataIOSelectTELayerExisting(
    WidgetDataIOSelectTELayerBase,
    Ui_WidgetDataIOSelectTELayerExisting
):
    def __init__(self, parent=None):
        super().__init__(parent)


class WidgetDataIOSelectTELayerImport(
    WidgetDataIOSelectTELayerBase, Ui_WidgetDataIOSelectTELayerImport
):
    pass


def get_usable_datasets(
        dataset_name: typing.Optional[str] = "any"
) -> typing.List[UsableDatasetInfo]:
    result = []
    for job in job_manager.relevant_jobs:
        job: job_models.Job
        is_downloaded = job.status == job_models.JobStatus.DOWNLOADED
        is_valid_type = job.results.type in (job_models.JobResult.CLOUD_RESULTS,
                                             job_models.JobResult.LOCAL_RESULTS)
        if is_downloaded and is_valid_type:
            path = job.results.local_paths[0]
            if job.script.name == dataset_name:
                result.append(
                    UsableDatasetInfo(
                        job=job,
                        path=path,
                    )
                )
    result.sort(key=lambda ub: ub.job.start_date, reverse=True)
    return result


class WidgetDataIOSelectTEDatasetExisting(
        QtWidgets.QWidget,
        Ui_WidgetDataIOSelectTEDatasetExisting
):
    comboBox_datasets: QtWidgets.QComboBox
    # dlg_dataset: DlgDataIOLoadTEDataset
    dataset_list: typing.Optional[typing.List[UsableDatasetInfo]]
    job_selected = QtCore.pyqtSignal(uuid.UUID)

    def __init__(self, parent=None):
        super(WidgetDataIOSelectTEDatasetExisting, self).__init__(parent)
        self.setupUi(self)

        self.dataset_list = None

        self.comboBox_datasets.currentIndexChanged.connect(self.selected_job_changed)

    def populate(self):
        usable_datasets = get_usable_datasets(self.property("dataset_type"))
        self.dataset_list = usable_datasets
        # Ensure selected_job_changed is called only once when adding items to 
        # combobox
        self.comboBox_datasets.currentIndexChanged.disconnect(self.selected_job_changed)
        old_text = self.currentText()
        self.comboBox_datasets.clear()
        # Add a blank item to be shown when no dataset is chosen
        self.comboBox_datasets.addItem('')
        i = 0
        for usable_dataset in usable_datasets:
            name_info_parts = []
            hover_info_parts = []
            name_info_parts.extend(
                [
                    usable_dataset.job.visible_name,
                    usable_dataset.job.params.task_notes.local_context.area_of_interest_name,
                    usable_dataset.job.start_date.strftime("%Y-%m-%d %H:%M")
                ]
            )
            hover_info_parts.extend(
                [
                    usable_dataset.job.visible_name + ' - ',
                    usable_dataset.job.params.task_notes.local_context.area_of_interest_name + '\n',
                    usable_dataset.job.start_date.strftime("%Y-%m-%d %H:%M")
                ]
            )
            self.comboBox_datasets.addItem(" - ".join(name_info_parts))
            # the "+ 1" below is to account for blank entry at the beginning of 
            # the combobox
            self.comboBox_datasets.setItemData(i + 1, "".join(hover_info_parts), QtCore.Qt.ToolTipRole)
            i += 1
        if not self.set_index_from_text(old_text):
            # Set current index to 1 so that the blank line isn't chosen by 
            # default
            self.comboBox_datasets.setCurrentIndex(1)
        self.selected_job_changed()
        self.comboBox_datasets.currentIndexChanged.connect(self.selected_job_changed)

    def currentText(self):
        return self.comboBox_datasets.currentText()

    def set_index_from_text(self, text):
        if self.dataset_list:
            for i in range(len(self.dataset_list)):
                if self.dataset_list[i] == text:
                    # the "+ 1" below is to account for blank entry
                    # at the beginning of the combobox
                    self.comboBox_datasets.setCurrentIndex(i + 1)
                    return True
        return False

    def selected_job_changed(self):
        # the "- 1" below is to account for blank entry
        # at the beginning of the combobox
        current_job = self.dataset_list[self.comboBox_datasets.currentIndex() - 1]
        # Allow for a current_job of '' (no job selected)
        if current_job != '':
            # the "- 1" below i
            # s to account for blank entry
            # at the beginning of the combobox
            job_id = current_job.job.id
        else:
            job_id = None
        self.job_selected.emit(job_id)
