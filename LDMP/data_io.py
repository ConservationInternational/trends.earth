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

import os
import re
import tempfile

import json
from marshmallow import ValidationError

from PyQt4 import QtGui
from PyQt4.QtCore import QSettings, Qt, QCoreApplication, pyqtSignal

from qgis.core import QgsRasterShader, QgsVectorLayer, QgsRasterLayer, \
    QgsProject, QgsLayerTreeLayer, QgsLayerTreeGroup
from qgis.utils import iface
mb = iface.messageBar()

import numpy as np

from osgeo import gdal, osr

from LDMP import log
from LDMP.layers import create_local_json_metadata, add_layer, \
    get_file_metadata, get_band_title, get_sample, get_band_info
from LDMP.worker import AbstractWorker, StartWorker
from LDMP.gui.DlgDataIO import Ui_DlgDataIO
from LDMP.gui.DlgDataIOLoadTE import Ui_DlgDataIOLoadTE
from LDMP.gui.DlgDataIOLoadTESingleLayer import Ui_DlgDataIOLoadTESingleLayer
from LDMP.gui.DlgDataIOImportLC import Ui_DlgDataIOImportLC
from LDMP.gui.DlgDataIOImportSOC import Ui_DlgDataIOImportSOC
from LDMP.gui.DlgDataIOImportProd import Ui_DlgDataIOImportProd
from LDMP.gui.DlgJobsDetails import Ui_DlgJobsDetails
from LDMP.gui.WidgetDataIOImportSelectFileInput import Ui_WidgetDataIOImportSelectFileInput
from LDMP.gui.WidgetDataIOImportSelectRasterOutput import Ui_WidgetDataIOImportSelectRasterOutput
from LDMP.gui.WidgetDataIOSelectTELayerExisting import Ui_WidgetDataIOSelectTELayerExisting
from LDMP.gui.WidgetDataIOSelectTELayerImport import Ui_WidgetDataIOSelectTELayerImport
from LDMP.schemas.schemas import BandInfo, BandInfoSchema

class ShapefileImportWorker(AbstractWorker):
    def __init__(self, in_file, out_file, out_res, 
                 out_data_type=gdal.GDT_Int16):
        AbstractWorker.__init__(self)

        self.in_file = in_file
        self.out_file = out_file

        self.out_res = out_res
        self.out_data_type = out_data_type

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        res = gdal.Rasterize(self.out_file, self.in_file,
                             format='GTiff',
                             xRes=self.out_res, yRes=-self.out_res,
                             noData=-32767, attribute=attribute,
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


class RasterImportWorker(AbstractWorker):
    def __init__(self, in_file, out_file, out_res, 
                 resample_mode, out_data_type=gdal.GDT_Int16):
        AbstractWorker.__init__(self)

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
                            srcNodata=-32768, dstNodata=-32767,
                            dstSRS="epsg:4326",
                            outputType=self.out_data_type,
                            resampleAlg=self.resample_mode,
                            creationOptions=['COMPRESS=LZW'],
                            callback=self.progress_callback)
        else:
            res = gdal.Warp(self.out_file, self.in_file, format='GTiff',
                            srcNodata=-32768, dstNodata=-32767,
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


class RasterRemapWorker(AbstractWorker):
    def __init__(self, in_file, out_file, remap_list):
        AbstractWorker.__init__(self)

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
        for y in xrange(0, ysize, y_block_size):
            if self.killed:
                log(u"Processing of {} killed by user after processing {} out of {} blocks.".format(deg_file, y, ysize))
                break
            self.progress.emit(100 * float(y) / ysize)
            if y + y_block_size < ysize:
                rows = y_block_size
            else:
                rows = ysize - y
            for x in xrange(0, xsize, x_block_size):
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
            os.remove(out_file)
            return None
        else:
            return True

    def progress_callback(self, fraction, message, data):
        if self.killed:
            return False
        else:
            self.progress.emit(100 * fraction)
            return True


def get_unique_values_vector(l, field, max_unique=60):
    idx = l.fieldNameIndex(self.input_widget.comboBox_fieldname.currentText())
    values = l.uniqueValues(idx)
    if len(values) > max_unique:
        return None
    else:
        return values


def get_raster_stats(f, band_num, sample=True, min_min=0, max_max=1000, nodata=-32768):
    if sample:
        # Note need float to correctly mark and ignore nodata for for nanmin 
        # and nanmax 
        values = get_sample(f, band_num, n=1e6).astype('float32')
        values[values == nodata] = np.nan
        mn = np.nanmin(values)
        if mn < min_min:
            return None
        mx = np.nanmax(values)
        if mx > max_max:
            return None
        return (mn, mx)
    else:
        src_ds = gdal.Open(f)
        b = src_ds.GetRasterBand(band_num)

        block_sizes = b.GetBlockSize()
        x_block_size = block_sizes[0]
        y_block_size = block_sizes[1]
        xsize = b.XSize
        ysize = b.YSize

        stats = (None, None)
        for y in xrange(0, ysize, y_block_size):
            if y + y_block_size < ysize:
                rows = y_block_size
            else:
                rows = ysize - y

            for x in xrange(0, xsize, x_block_size):
                if x + x_block_size < xsize:
                    cols = x_block_size
                else:
                    cols = xsize - x

                d = b.ReadAsArray(x, y, cols, rows).ravel()
                mx = x.max()
                mn = x.min()
                if mx > max_max:
                    return None
                else:
                    if not stats[0] or mn < stats[0]:
                        stats[0] = mn
                if mn < min_min:
                    return None
                else:
                    if not stats[1] or mx > stats[1]:
                        stats[1] = mx
        return stats


def get_unique_values_raster(f, band_num, sample=True, max_unique=60):
    if sample:
        values = np.unique(get_sample(f, band_num, n=1e6)).tolist()
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

        for y in xrange(0, ysize, y_block_size):
            if y + y_block_size < ysize:
                rows = y_block_size
            else:
                rows = ysize - y

            for x in xrange(0, xsize, x_block_size):
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


class DlgJobsDetails(QtGui.QDialog, Ui_DlgJobsDetails):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgJobsDetails, self).__init__(parent)

        self.setupUi(self)
        self.task_status.hide()
        self.statusLabel.hide()

        #TODO: This is not yet working...
        # # Convert from a grid layout to a vbox layout
        # temp = QtGui.QWidget()
        # temp.setLayout(self.layout())
        # new_layout = QtGui.QVBoxLayout(self)
        # while True:
        #     layout_item = temp.layout().takeAt(0)
        #     if not layout_item:
        #         break
        #     new_layout.addWidget(layout_item.widget())

class DlgDataIO(QtGui.QDialog, Ui_DlgDataIO):
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

class DlgDataIOLoadTEBase(QtGui.QDialog):
    layers_loaded = pyqtSignal(list)

    def __init__(self, parent=None):
        super(DlgDataIOLoadTEBase, self).__init__(parent)

        self.setupUi(self)

        self.layers_model = QtGui.QStringListModel()
        self.layers_view.setModel(self.layers_model)
        self.layers_model.setStringList([])

        self.buttonBox.accepted.connect(self.ok_clicked)
        self.buttonBox.rejected.connect(self.cancel_clicked)

    def cancel_clicked(self):
        self.close()

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
                resp = add_layer(f, self.layer_list[row][2], self.layer_list[row][3])
                if resp:
                    added_layers.append(self.layer_list[row])
                else:
                    QtGui.QMessageBox.critical(None, self.tr("Error"), 
                                               self.tr(u'Unable to automatically add "{}". No style is defined for this type of layer.'.format(self.layer_list[row][2]['name'])))
            self.layers_loaded.emit(added_layers)
        else:
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Select a layer to load."))
            return

        self.close()


class DlgDataIOLoadTE(DlgDataIOLoadTEBase, Ui_DlgDataIOLoadTE):
    def __init__(self, parent=None):
        super(DlgDataIOLoadTE, self).__init__(parent)

        self.file_browse_btn.clicked.connect(self.browse_file)
        self.btn_view_metadata.clicked.connect(self.view_metadata)

    def showEvent(self, e):
        super(DlgDataIOLoadTE, self).showEvent(e)
        self.file_lineedit.clear()
        self.file = None
        self.layers_model.setStringList([])
        self.btn_view_metadata.setEnabled(False)

    def browse_file(self):
        f = QtGui.QFileDialog.getOpenFileName(self,
                                              self.tr('Select a Trends.Earth output file'),
                                              QSettings().value("LDMP/output_dir", None),
                                              self.tr('Trends.Earth metadata file (*.json)'))
        if f:
            if os.access(f, os.R_OK):
                QSettings().setValue("LDMP/output_dir", os.path.dirname(f))
                self.file = f
            else:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr(u"Cannot read {}. Choose a different file.".format(f)))
                return

        res = self.update_layer_list(f)
        if res:
            self.file_lineedit.setText(f)
        else:
            self.file_lineedit.clear()

    def update_layer_list(self, f):
        if f:
            self.layer_list = get_layer_info_from_file(os.path.normcase(os.path.normpath(f)))
            if self.layer_list:
                bands = ['Band {}: {}'.format(layer[2], layer[1]) for layer in self.layer_list]
                self.layers_model.setStringList(bands)
                self.layers_view.setEditTriggers(QtGui.QAbstractItemView.NoEditTriggers)
                for n in range(len(self.layer_list)):
                    if self.layer_list[n][3]['add_to_map']:
                        self.layers_view.selectionModel().select(self.layers_model.createIndex(n, 0), QtGui.QItemSelectionModel.Select)
            else:
                self.layers_model.setStringList([])
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr(u"{} does not appear to be a Trends.Earth output file".format(f)))
                self.layers_model.setStringList([])
                self.btn_view_metadata.setEnabled(False)
                return None
        else:
            self.btn_view_metadata.setEnabled(False)
            self.layers_model.setStringList([])
            return None

        self.btn_view_metadata.setEnabled(True)
        return True

    def view_metadata(self):
        details_dlg = DlgJobsDetails(self)
        m = get_file_metadata(self.file)
        m = m['metadata']
        if m:
            details_dlg.task_name.setText(m.get('task_name', ''))
            details_dlg.comments.setText(m.get('task_notes', ''))
            details_dlg.input.setText(json.dumps(m.get('params', {}), indent=4, sort_keys=True))
            details_dlg.output.setText(json.dumps(m.get('results', {}), indent=4, sort_keys=True))
            details_dlg.show()
            details_dlg.exec_()
        else:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr(u"Cannot read {}. Choose a different file.".format(self.file)))


class DlgDataIOLoadTESingleLayer(DlgDataIOLoadTEBase, Ui_DlgDataIOLoadTESingleLayer):
    def __init__(self, parent=None):
        super(DlgDataIOLoadTESingleLayer, self).__init__(parent)

    def update_layer_list(self, layers):
        self.layer_list = layers
        bands = [layer[1] for layer in layers]
        self.layers_model.setStringList(bands)
        self.layers_view.setEditTriggers(QtGui.QAbstractItemView.NoEditTriggers)


class ImportSelectFileInputWidget(QtGui.QWidget, Ui_WidgetDataIOImportSelectFileInput):
    inputFileChanged = pyqtSignal(bool)
    inputTypeChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super(ImportSelectFileInputWidget, self).__init__(parent)
        self.setupUi(self)

        self.radio_raster_input.toggled.connect(self.radio_raster_input_toggled)

        self.btn_raster_dataset_browse.clicked.connect(self.open_raster_browse)
        self.btn_polygon_dataset_browse.clicked.connect(self.open_vector_browse)

    def radio_raster_input_toggled(self):
        has_file = False
        if self.radio_raster_input.isChecked():
            self.btn_raster_dataset_browse.setEnabled(True)
            self.lineEdit_raster_file.setEnabled(True)
            self.comboBox_bandnumber.setEnabled(True)
            self.label_bandnumber.setEnabled(True)
            self.btn_polygon_dataset_browse.setEnabled(False)
            self.lineEdit_polygon_file.setEnabled(False)
            self.label_fieldname.setEnabled(False)
            self.comboBox_fieldname.setEnabled(False)

            if self.lineEdit_raster_file.text():
                has_file = True
        else:
            QtGui.QMessageBox.information(None, self.tr("Coming soon!"),
                                          self.tr("Processing of vector input datasets coming soon!"))
            self.radio_raster_input.setChecked(True)
            # self.btn_raster_dataset_browse.setEnabled(False)
            # self.lineEdit_raster_file.setEnabled(False)
            # self.comboBox_bandnumber.setEnabled(False)
            # self.label_bandnumber.setEnabled(False)
            # self.btn_polygon_dataset_browse.setEnabled(True)
            # self.lineEdit_polygon_file.setEnabled(True)
            # self.label_fieldname.setEnabled(True)
            # self.comboBox_fieldname.setEnabled(True)

            if self.lineEdit_polygon_file.text():
                has_file=True
        self.inputTypeChanged.emit(has_file)

    def open_raster_browse(self):
        self.lineEdit_raster_file.clear()
        self.comboBox_bandnumber.clear()

        raster_file = QtGui.QFileDialog.getOpenFileName(self,
                                                        self.tr('Select a raster input file'),
                                                        QSettings().value("LDMP/input_dir", None),
                                                        self.tr('Raster file (*.tif *.dat *.img)'))
        # Try loading this raster to verify the file works
        if raster_file:
            self.get_raster_layer(raster_file)
        else:
            self.inputFileChanged.emit(False)

    def get_raster_layer(self, raster_file):
        l = QgsRasterLayer(raster_file, "raster file", "gdal")

        if not os.access(raster_file, os.R_OK or not l.isValid()):
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr(u"Cannot read {}. Choose a different file.".format(raster_file)))
            self.inputFileChanged.emit(False)
            return False

        QSettings().setValue("LDMP/input_dir", os.path.dirname(raster_file))
        self.lineEdit_raster_file.setText(raster_file)

        self.comboBox_bandnumber.addItems([str(n) for n in range(1, l.dataProvider().bandCount() + 1)])

        self.inputFileChanged.emit(True)
        return True

    def open_vector_browse(self):
        self.comboBox_fieldname.clear()
        self.lineEdit_polygon_file.clear()

        vector_file = QtGui.QFileDialog.getOpenFileName(self,
                                                        self.tr('Select a vector input file'),
                                                        QSettings().value("LDMP/input_dir", None),
                                                        self.tr('Vector file (*.shp *.kml *.kmz *.geojson)'))
        # Try loading this vector to verify the file works
        if vector_file:
            self.get_vector_layer(vector_file)
        else:
            self.inputFileChanged.emit(False)

    def get_vector_layer(self, vector_file):
        l = QgsVectorLayer(vector_file, "vector file", "ogr")

        if not os.access(vector_file, os.R_OK) or not l.isValid():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr(u"Cannot read {}. Choose a different file.".format(vector_file)))
            self.inputFileChanged.emit(False)
            return False

        QSettings().setValue("LDMP/input_dir", os.path.dirname(vector_file))
        self.lineEdit_polygon_file.setText(vector_file)
        self.inputFileChanged.emit(True)

        self.comboBox_fieldname.addItems([field.name() for field in l.dataProvider().fields()])

        return l


class ImportSelectRasterOutput(QtGui.QWidget, Ui_WidgetDataIOImportSelectRasterOutput):
    def __init__(self, parent=None):
        super(ImportSelectRasterOutput, self).__init__(parent)
        self.setupUi(self)

        self.btn_output_file_browse.clicked.connect(self.save_raster)

    def save_raster(self):
        self.lineEdit_output_file.clear()

        raster_file = QtGui.QFileDialog.getSaveFileName(self,
                                                        self.tr('Choose a name for the output file'),
                                                        QSettings().value("LDMP/output_dir", None),
                                                        self.tr('Raster file (*.tif)'))
        if raster_file:
            if os.access(os.path.dirname(raster_file), os.W_OK):
                QSettings().setValue("LDMP/input_dir", os.path.dirname(raster_file))
                self.lineEdit_output_file.setText(raster_file)
                return True
            else:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr(u"Cannot write to {}. Choose a different file.".format(raster_file)))
                return False


class DlgDataIOImportBase(QtGui.QDialog):
    """Base class for individual data loading dialogs"""
    layer_loaded = pyqtSignal(list)

    def __init__(self, parent=None):
        super(DlgDataIOImportBase, self).__init__(parent)

        self.setupUi(self)

        self.input_widget = ImportSelectFileInputWidget()
        self.verticalLayout.insertWidget(0, self.input_widget)

    def validate_input(self, value):
        if self.input_widget.radio_raster_input.isChecked():
            if self.input_widget.lineEdit_raster_file.text() == '':
                QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Choose an input raster file."))
                return
        else:
            if self.input_widget.lineEdit_polygon_file.text() == '':
                QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Choose an input polygon dataset."))
                return

    def get_resample_mode(self, f):
        in_res = self.get_in_res_wgs84()
        out_res = self.get_out_res_wgs84()
        if in_res < out_res:
            # If output resolution is lower than the original data, use mode
            log('Resampling with mode (in res: {}, out_res: {}'.format(in_res, out_res))
            return gdal.GRA_Mode
        else:
            # If output resolution is finer than the original data, use nearest 
            # neighbor
            log('Resampling with nearest neighbor (in res: {}, out_res: {}'.format(in_res, out_res))
            return gdal.GRA_NearestNeighbour

    def get_in_res_wgs84(self):
        ds_in = gdal.Open(self.input_widget.lineEdit_raster_file.text())
        wgs84_srs = osr.SpatialReference()
        wgs84_srs.ImportFromEPSG(4326)

        in_srs = osr.SpatialReference()
        in_srs.ImportFromWkt(ds_in.GetProjectionRef())

        tx = osr.CoordinateTransformation(in_srs, wgs84_srs)

        geo_t = ds_in.GetGeoTransform()
        x_size = ds_in.RasterXSize # Raster xsize
        y_size = ds_in.RasterYSize # Raster ysize
        # Work out the boundaries of the new dataset in the target projection
        (ulx, uly, ulz) = tx.TransformPoint(geo_t[0], geo_t[3])
        (lrx, lry, lrz) = tx.TransformPoint(geo_t[0] + geo_t[1]*x_size, \
                                                     geo_t[3] + geo_t[5]*y_size)
        # As an approximation of what the output res would be in WGS4, use an 
        # average of the x and y res of this image
        return ((lrx - ulx)/float(x_size) + (lry - uly)/float(y_size)) / 2

    def get_out_res_wgs84(self):
        # Calculate res in degrees from input which is in meters
        res = int(self.input_widget.spinBox_resolution.value())
        return res / (111.325 * 1000) # 111.325km in one degree

    def remap_raster(self, remap_list):
        in_file = self.input_widget.lineEdit_raster_file.text()
        out_file = self.output_widget.lineEdit_output_file.text()

        # First warp the raster to the correct CRS
        temp_tif = tempfile.NamedTemporaryFile(suffix='.tif').name
        self.warp_raster(temp_tif)

        raster_remap_worker = StartWorker(RasterRemapWorker,
                                          'remapping values', temp_tif, 
                                           out_file, remap_list)
        if not raster_remap_worker.success:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Raster import failed."), None)
            return False
        else:
            return True

    def warp_raster(self, out_file):
        in_file = self.input_widget.lineEdit_raster_file.text()

        # Select a single output band
        band_number = int(self.input_widget.comboBox_bandnumber.currentText())
        temp_vrt = tempfile.NamedTemporaryFile(suffix='.vrt').name
        gdal.BuildVRT(temp_vrt, in_file, bandList=[band_number])
                      
        log(u'Importing {} to {}'.format(in_file, out_file))
        if self.input_widget.groupBox_output_resolution.isChecked():
            out_res = self.get_out_res_wgs84()
            resample_mode = self.get_resample_mode(temp_vrt)
        else:
            out_res = None
            resample_mode = gdal.GRA_NearestNeighbour
        raster_import_worker = StartWorker(RasterImportWorker,
                                           'importing raster', temp_vrt, 
                                           out_file, out_res, resample_mode)
        if not raster_import_worker.success:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Raster import failed."), None)
            return False
        else:
            return True

    def add_layer(self, band_name, metadata):
        out_file = os.path.normcase(os.path.normpath(self.output_widget.lineEdit_output_file.text()))
        out_json = os.path.splitext(out_file)[0] + '.json'
        band_info = [BandInfo(band_name, add_to_map=True, metadata=metadata)]
        create_local_json_metadata(out_json, out_file, band_info)
        schema = BandInfoSchema()
        band_info_dict = schema.dump(band_info[0])
        add_layer(out_file, 1, band_info_dict)
        return (out_file, get_band_title(band_info_dict), 1, schema.dump(band_info[0]))

class DlgDataIOImportLC(DlgDataIOImportBase, Ui_DlgDataIOImportLC):
    def __init__(self, parent=None):
        super(DlgDataIOImportLC, self).__init__(parent)

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

    def done(self, value):
        if value == QtGui.QDialog.Accepted:
            self.validate_input(value)
        else:
            super(DlgDataIOImportLC, self).done(value)

    def validate_input(self, value):
        if self.output_widget.lineEdit_output_file.text() == '':
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Choose an output file."))
            return
        if  not self.dlg_agg:
            QtGui.QMessageBox.information(None, self.tr("No definition set"), self.tr('Click "Edit Definition" to define the land cover definition before exporting.', None))
            return

        super(DlgDataIOImportLC, self).validate_input(value)

        super(DlgDataIOImportLC, self).done(value)

        self.ok_clicked()

    def clear_dlg_agg(self):
        self.dlg_agg = None

    def showEvent(self, event):
        super(DlgDataIOImportLC, self).showEvent(event)

        # Reset flags to avoid reloading of unique values when files haven't 
        # changed:
        self.last_raster = None
        self.last_band_number = None
        self.last_vector = None
        self.idx = None

    def input_changed(self, valid):
        if valid:
            self.btn_agg_edit_def.setEnabled(True)
        else:
            self.btn_agg_edit_def.setEnabled(False)
        self.clear_dlg_agg()

    def load_agg(self, values):
        # Set all of the classes to no data by default
        classes = [{'Initial_Code':value, 'Initial_Label':str(value), 'Final_Label':'No data', 'Final_Code':-32768} for value in sorted(values)]
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
                    QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Error reading data. Trends.Earth supports a maximum of 60 different land cover classes", None))
                    return
                self.last_raster = f
                self.last_band_number = band_number
                self.load_agg(values)
        else:
            f = self.input_widget.lineEdit_polygon_file.text()
            l = self.input_widget.get_vector_layer(f)
            idx = l.fieldNameIndex(self.input_widget.comboBox_fieldname.currentText())
            if not self.dlg_agg or \
                    (self.last_vector != f or self.last_idx != idx):
                get_unique_values_vector(l, field, max_unique=60)
                if not values:
                    QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Error reading data. Trends.Earth supports a maximum of 60 different land cover classes", None))
                    return
                self.last_vector = f
                self.last_idx = idx
                self.load_agg(values)
        self.dlg_agg.exec_()

    def ok_clicked(self):
        if self.input_widget.radio_raster_input.isChecked():
            self.remap_raster(self.dlg_agg.get_agg_as_list())
        else:
            self.convert_vector()

        l_info = self.add_layer('Land cover (7 class)',
                                {'year': int(self.input_widget.spinBox_data_year.date().year()),
                                'source': 'custom data'})

        self.layer_loaded.emit([l_info])

class DlgDataIOImportSOC(DlgDataIOImportBase, Ui_DlgDataIOImportSOC):
    def __init__(self, parent=None):
        super(DlgDataIOImportSOC, self).__init__(parent)

        # This needs to be inserted after the input widget but before the 
        # button box with ok/cancel
        self.output_widget = ImportSelectRasterOutput()
        self.verticalLayout.insertWidget(1, self.output_widget)

    def done(self, value):
        if value == QtGui.QDialog.Accepted:
            self.validate_input(value)
        else:
            super(DlgDataIOImportSOC, self).done(value)

    def validate_input(self, value):
        if self.output_widget.lineEdit_output_file.text() == '':
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Choose an output file."))
            return

        super(DlgDataIOImportSOC, self).validate_input(value)

        if self.input_widget.radio_raster_input.isChecked():
            in_file = self.input_widget.lineEdit_raster_file.text()
            stats = get_raster_stats(in_file, int(self.input_widget.comboBox_bandnumber.currentText()))
        else:
            in_file = self.input_widget.lineEdit_polygon_file.text()
            l = self.input_widget.get_vector_layer(in_file)
            stats = get_vector_stats(l)
        log('Stats are: {}'.format(stats))
        if not stats:
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr(u"The input file ({}) does not appear to be a valid soil organic carbon input file. The file should contain values of soil organic carbon in tonnes / hectare.".format(in_file)))
            return
        if stats[0] < 0:
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr(u"The input file ({}) does not appear to be a valid soil organic carbon input file. The minimum value in this file is {}. The no data value should be -32768, and all other values should be >= 0.".format(in_file, stats[0])))
            return
        if stats[1] > 1000:
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr(u"The input file ({}) does not appear to be a valid soil organic carbon input file. The maximum value in this file is {}. The maximum value allowed is 1000 tonnes / hectare.".format(in_file, stats[1])))
            return

        super(DlgDataIOImportSOC, self).done(value)

        self.ok_clicked()

    def ok_clicked(self):
        if self.input_widget.radio_raster_input.isChecked():
            out_file = self.output_widget.lineEdit_output_file.text()
            self.warp_raster(out_file)
        else:
            self.convert_vector()

        l_info = self.add_layer('Soil organic carbon',
                                {'year': int(self.input_widget.spinBox_data_year.date().year()),
                                'source': 'custom data'})
        self.layer_loaded.emit([l_info])


class DlgDataIOImportProd(DlgDataIOImportBase, Ui_DlgDataIOImportProd):
    def __init__(self, parent=None):
        super(DlgDataIOImportProd, self).__init__(parent)

        # This needs to be inserted after the input widget but before the 
        # button box with ok/cancel
        self.output_widget = ImportSelectRasterOutput()

        self.input_widget.groupBox_year.hide()

        self.verticalLayout.insertWidget(1, self.output_widget)

    def done(self, value):
        if value == QtGui.QDialog.Accepted:
            self.validate_input(value)
        else:
            super(DlgDataIOImportProd, self).done(value)

    def validate_input(self, value):
        if self.output_widget.lineEdit_output_file.text() == '':
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Choose an output file."))
            return

        super(DlgDataIOImportProd, self).validate_input(value)

        if self.input_widget.radio_raster_input.isChecked():
            in_file = self.input_widget.lineEdit_raster_file.text()
            values = get_unique_values_raster(in_file, int(self.input_widget.comboBox_bandnumber.currentText()), max_unique=7)
        else:
            in_file = self.input_widget.lineEdit_polygon_file.text()
            l = self.input_widget.get_vector_layer(in_file)
            values = get_unique_values_vector(l, field, max_unique=7)
        if not values:
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr(u"The input file ({}) does not appear to be a valid productivity input file.".format(in_file)))
            return
        invalid_values = [v for v in values if v not in [-32768, 0, 1, 2, 3, 4, 5]]
        if len(invalid_values) > 0:
            QtGui.QMessageBox.warning(None, self.tr("Warning"), self.tr(u"The input file ({}) does not appear to be a valid productivity input file. Trends.Earth will load the file anyway, but review the map once it has loaded to ensure the values make sense. The only values allowed in a productivity input file are -32768, 1, 2, 3, 4 and 5. There are {} value(s) in the input file that were not recognized.".format(in_file, len(invalid_values))))

        super(DlgDataIOImportProd, self).done(value)

        self.ok_clicked()

    def ok_clicked(self):
        if self.input_widget.radio_raster_input.isChecked():
            out_file = self.output_widget.lineEdit_output_file.text()
            self.warp_raster(out_file)
        else:
            self.convert_vector("Land Productivity Dynamics (LPD)")

        l_info = self.add_layer("Land Productivity Dynamics (LPD)",
                                {'source': 'custom data'})
        self.layer_loaded.emit([l_info])


def _get_layers(node):
    l = []
    if isinstance(node, QgsLayerTreeGroup):
        for child in node.children():
            if isinstance(child, QgsLayerTreeLayer):
                l.append(child.layer())
            else:
                l.extend(_get_layers(child))
    else:
        l = node
    return l


# Get a list of layers of a particular type, out of those in the TOC that were
# produced by trends.earth
def get_TE_TOC_layers(layer_type=None):
    root = QgsProject.instance().layerTreeRoot()
    layers_filtered = []
    layers = _get_layers(root)
    if len(layers) > 0:
        for l in layers:
            if not isinstance(l, QgsRasterLayer):
                # Allows skipping other layer types, like OpenLayers layers, that
                # are irrelevant for the toolbox
                continue
            data_file = os.path.normcase(os.path.normpath(l.dataProvider().dataSourceUri()))
            band_infos = get_band_info(data_file)
            # Layers not produced by trends.earth won't have bandinfo, and 
            # aren't of interest, so skip if there is no bandinfo.
            if band_infos:
                # If a band_number is not supplied, use the one that is used by 
                # this raster's renderer
                band_number = l.renderer().usesBands()
                if len(band_number) == 1:
                    band_number = band_number[0]
                else:
                    # Can't handle multi-band rasters right now
                    continue
                band_info = band_infos[band_number - 1]
                if layer_type == band_info['name'] or layer_type == 'any':
                    # Note the layer name here could be different from the 
                    # band_info derived name, since the name accompanying the 
                    # layer is the one in the TOC
                    layers_filtered.append((data_file, l.name(), band_number, band_info))
    return layers_filtered


def get_layer_info_from_file(json_file, layer_type='any'):
    m = get_file_metadata(json_file)
    band_infos = get_band_info(json_file)
    layers_filtered = []
    for n in range(len(band_infos)):
        band_info = band_infos[n - 1]
        data_file = os.path.normcase(os.path.normpath(os.path.join(os.path.dirname(json_file), m['file'])))
        if layer_type == band_info['name'] or layer_type == 'any':
            layers_filtered.append((data_file, get_band_title(band_info), n, band_info))
    return layers_filtered

    
class WidgetDataIOSelectTELayerBase(QtGui.QWidget):
    def __init__(self, parent=None):
        super(WidgetDataIOSelectTELayerBase, self).__init__(parent)

        self.setupUi(self)

        self.pushButton_load_existing.clicked.connect(self.load_file)

        self.dlg_layer = DlgDataIOLoadTESingleLayer()

        self.dlg_layer.layers_loaded.connect(self.populate)

        self.layer_list = None

    def populate(self, selected_layer=None):
        if self.layer_list:
            last_layer = self.layer_list[self.comboBox_layers.currentIndex()]
        else:
            last_layer = None
        self.layer_list = get_TE_TOC_layers(self.property("layer_type"))
        self.comboBox_layers.clear()
        self.comboBox_layers.addItems([l[1] for l in self.layer_list])

        # Set the selected layer to the one that was just loaded, or to the 
        # last layer that was selected
        if selected_layer:
            assert(len(selected_layer) == 1)
            set_layer = selected_layer[0]
        elif last_layer:
            set_layer = last_layer
        else:
            set_layer = None
        if set_layer:
            # It is possible the last or selected layer has been removed, in 
            # which case an exception will be thrown
            try:
                self.comboBox_layers.setCurrentIndex(self.layer_list.index(set_layer))
            except ValueError:
                log(u"Failed to locate {} in layer list ({})".format(set_layer, self.layer_list))
                pass

    def load_file(self):
        while True:
            f = QtGui.QFileDialog.getOpenFileName(self,
                                                  self.tr('Select a Trends.Earth output file'),
                                                  QSettings().value("LDMP/output_dir", None),
                                                  self.tr('Trends.Earth metadata file (*.json)'))
            if f:
                if os.access(f, os.R_OK):
                    QSettings().setValue("LDMP/output_dir", os.path.dirname(f))

                    new_layers = get_layer_info_from_file(os.path.normcase(os.path.normpath(f)), self.property("layer_type"))
                    if new_layers:
                        self.dlg_layer.file = f
                        self.dlg_layer.update_layer_list(new_layers)
                        self.dlg_layer.exec_()
                        break
                    else:
                        # otherwise warn, and raise the layer selector again
                        QtGui.QMessageBox.critical(None, self.tr("Error"),
                                                   self.tr(u"{} failed to load or does not contain any layers of this layer type. Choose a different file.".format(f)))
                else:
                    # otherwise warn, and raise the layer selector again
                    QtGui.QMessageBox.critical(None, self.tr("Error"),
                                               self.tr(u"Cannot read {}. Choose a different file.".format(f)))
            else:
                break

    def get_layer(self):
        return QgsRasterLayer(self.layer_list[self.comboBox_layers.currentIndex()][0], "raster file", "gdal")

    def get_bandnumber(self):
        return self.layer_list[self.comboBox_layers.currentIndex()][1]

    def get_vrt(self):
        f = tempfile.NamedTemporaryFile(suffix='.vrt').name
        gdal.BuildVRT(f,
                      self.get_layer().dataProvider().dataSourceUri(),
                      bandList=[self.get_bandnumber()])
        return f


class WidgetDataIOSelectTELayerExisting(WidgetDataIOSelectTELayerBase, Ui_WidgetDataIOSelectTELayerExisting):
    def __init__(self, parent=None):
        super(WidgetDataIOSelectTELayerExisting, self).__init__(parent)


class WidgetDataIOSelectTELayerImport(WidgetDataIOSelectTELayerBase, Ui_WidgetDataIOSelectTELayerImport):
    def __init__(self, parent=None):
        super(WidgetDataIOSelectTELayerImport, self).__init__(parent)

        self.pushButton_import.clicked.connect(self.import_file)

    def import_file(self):
        if self.property("layer_type") == 'Land Productivity Dynamics (LPD)':
            self.dlg_load = DlgDataIOImportProd()
        if self.property("layer_type") == 'Land cover (7 class)':
            self.dlg_load = DlgDataIOImportLC()
        if self.property("layer_type") == 'Soil organic carbon':
            self.dlg_load = DlgDataIOImportSOC()
        self.dlg_load.layer_loaded.connect(self.populate)
        self.dlg_load.exec_()
