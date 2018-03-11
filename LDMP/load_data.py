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
from math import floor, log10

import json
from marshmallow import ValidationError

from PyQt4 import QtGui
from PyQt4.QtCore import QSettings, Qt, QCoreApplication, pyqtSignal

from LDMP.layers import create_local_json_metadata, add_layer, \
    get_file_metadata, get_band_title
from qgis.core import QgsRasterShader, QgsVectorLayer, QgsRasterLayer
from qgis.utils import iface
mb = iface.messageBar()

import numpy as np

from osgeo import gdal, osr

from LDMP import log
from LDMP.calculate_lc import DlgCalculateLCSetAggregation
from LDMP.worker import AbstractWorker, StartWorker
from LDMP.gui.DlgLoadData import Ui_DlgLoadData
from LDMP.gui.DlgLoadDataTE import Ui_DlgLoadDataTE
from LDMP.gui.DlgLoadDataLC import Ui_DlgLoadDataLC
from LDMP.gui.DlgLoadDataSOC import Ui_DlgLoadDataSOC
from LDMP.gui.DlgLoadDataProd import Ui_DlgLoadDataProd
from LDMP.gui.DlgJobsDetails import Ui_DlgJobsDetails
from LDMP.schemas.schemas import BandInfo, BandInfoSchema
from LDMP.gui.WidgetLoadDataSelectFileInput import Ui_WidgetLoadDataSelectFileInput
from LDMP.gui.WidgetLoadDataSelectRasterOutput import Ui_WidgetLoadDataSelectRasterOutput


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

        res = gdal.Warp(self.out_file, self.in_file, format='GTiff',
                        xRes=self.out_res, yRes=-self.out_res,
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
                log("Processing of {} killed by user after processing {} out of {} blocks.".format(deg_file, y, ysize))
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

def round_to_n(x, sf=3):
    'Function to round a positive value to n significant figures'
    if np.isnan(x):
        return x
    else:
        return round(x, -int(floor(log10(x))) + (sf - 1))


def get_sample(f, band_number, n=10000):
    '''Get a gridded sample of a raster dataset'''
    ds = gdal.Open(f)
    b = ds.GetRasterBand(band_number)

    xsize = b.XSize
    ysize = b.YSize

    # Select grid size from shortest side to ensure we have enough samples
    if xsize > ysize:
        edge = ysize
    else:
        edge = xsize
    grid_size = np.ceil(edge / np.sqrt(n))
    if (grid_size * grid_size) > (b.XSize * b.YSize):
        # Don't sample if the sample would be larger than the array itself
        return b.ReadAsArray().astype(np.float)
    else:
        rows = np.arange(0, ysize, grid_size)
        cols = np.arange(0, xsize, grid_size).astype('int64')

        out = np.zeros((rows.shape[0], cols.shape[0]), np.float64)
        log("Sampling from a ({}, {}) array to a {} array (grid size: {}, samples: {})".format(ysize, xsize, out.shape, grid_size, out.shape[0] * out.shape[1]))

        for n in range(rows.shape[0]):
            out[n, :] = b.ReadAsArray(0, int(rows[n]), xsize, 1)[:, cols]

        return out


def get_cutoff(f, band_number, band_info, percentiles):
    if len(percentiles) != 1 and len(percentiles) != 2:
        raise ValueError("Percentiles must have length 1 or 2. Percentiles that were passed: {}".format(percentiles))
    d = get_sample(f, band_number)
    md = np.ma.masked_where(d == band_info['no_data_value'], d)
    if md.size == 0:
        # If all of the values are no data, return 0
        return 0
    else:
        cutoffs = np.nanpercentile(md.compressed(), percentiles)
        if cutoffs.size == 2:
            max_cutoff = np.amax(np.absolute(cutoffs))
            if max_cutoff < 0:
                return 0
            else:
                return round_to_n(max_cutoff, 2)

        elif cutoffs.size == 1:
            if cutoffs < 0:
                # Negative cutoffs are not allowed as stretch is either zero 
                # centered or starting at zero
                return 0
            else:
                return round_to_n(cutoffs, 2)
        else:
            # We only get here if cutoffs is not size 1 or 2, which should 
            # never happen, so raise
            raise ValueError("Stretch calculation returned cutoffs array of size {} ({})".format(cutoffs.size, cutoffs))

def get_unique_values(f, band_num, max_unique=50):
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

class DlgLoadData(QtGui.QDialog, Ui_DlgLoadData):
    def __init__(self, parent=None):
        super(DlgLoadData, self).__init__(parent)

        self.setupUi(self)

        self.dlg_loaddata_te = DlgLoadDataTE()
        self.dlg_loaddata_lc = DlgLoadDataLC()
        self.dlg_loaddata_soc = DlgLoadDataSOC()
        self.dlg_loaddata_prod = DlgLoadDataProd()

        self.btn_te.clicked.connect(self.run_te)
        self.btn_lc.clicked.connect(self.run_lc)
        self.btn_soc.clicked.connect(self.run_soc)
        self.btn_prod.clicked.connect(self.run_prod)

        # TODO: temporarily hide soc button
        self.btn_soc.hide()

    def run_te(self):
        self.close()
        self.dlg_loaddata_te.exec_()

    def run_lc(self):
        self.close()
        self.dlg_loaddata_lc.exec_()

    def run_soc(self):
        self.close()
        self.dlg_loaddata_soc.exec_()

    def run_prod(self):
        self.close()
        self.dlg_loaddata_prod.exec_()

class DlgLoadDataTE(QtGui.QDialog, Ui_DlgLoadDataTE):
    def __init__(self, parent=None):
        super(DlgLoadDataTE, self).__init__(parent)

        self.setupUi(self)

        self.layers_model = QtGui.QStringListModel()
        self.layers_view.setModel(self.layers_model)
        self.layers_model.setStringList([])

        self.file_browse_btn.clicked.connect(self.browse_file)

        self.file_lineedit.editingFinished.connect(self.update_layer_list)

        self.buttonBox.accepted.connect(self.ok_clicked)
        self.buttonBox.rejected.connect(self.cancel_clicked)

        self.btn_view_metadata.clicked.connect(self.btn_details)


    def showEvent(self, e):
        super(DlgLoadDataTE, self).showEvent(e)

        self.file_lineedit.clear()
        self.layers_model.setStringList([])
        self.btn_view_metadata.setEnabled(False)


    def btn_details(self):
        details_dlg = DlgJobsDetails(self)
        m = get_file_metadata(self.file_lineedit.text())
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
                                       self.tr("Cannot read {}. Choose a different file.".format(self.file_lineedit.text())))


    def browse_file(self):
        f = QtGui.QFileDialog.getOpenFileName(self,
                                              self.tr('Select a trends.earth output file'),
                                              QSettings().value("LDMP/output_dir", None),
                                              self.tr('trends.earth metadata file (*.json)'))
        if f:
            if os.access(f, os.R_OK):
                QSettings().setValue("LDMP/output_dir", os.path.dirname(f))
            else:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Cannot read {}. Choose a different file.".format(f)))

        res = self.update_layer_list(f)
        if res:
            self.file_lineedit.setText(f)
        else:
            self.file_lineedit.clear()


    def cancel_clicked(self):
        self.close()

    def ok_clicked(self):
        rows = []
        for i in self.layers_view.selectionModel().selectedRows():
            rows.append(i.row())
        if len(rows) > 0:
            m = get_file_metadata(self.file_lineedit.text())
            if m:
                for row in rows:
                    # The plus 1 is because band numbers start at 1, not zero
                    resp = add_layer(m['file'], row + 1, m['bands'][row])
                    if not resp:
                        QtGui.QMessageBox.critical(None, self.tr("Error"), 
                                                   self.tr('Unable to automatically add "{}". No style is defined for this type of layer.'.format(m['bands'][row]['name'])))
                        return
            else:
                log('Error loading results from {}'.format(self.file_lineedit.text()))
        else:
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Select a layer to load."))
            return

        self.close()

    def update_layer_list(self, f=None):
        if not f:
            f = self.file_lineedit.text()
        if f:
            m = get_file_metadata(f)
            if m :
                bands = ['Band {}: {}'.format(i + 1, get_band_title(band)) for i, band in enumerate(m['bands'])]
                self.layers_model.setStringList(bands)
                self.layers_view.setEditTriggers(QtGui.QAbstractItemView.NoEditTriggers)
                for n in range(len(m['bands'])):
                    if m['bands'][n]['add_to_map']:
                        self.layers_view.selectionModel().select(self.layers_model.createIndex(n, 0), QtGui.QItemSelectionModel.Select)
            else:
                self.layers_model.setStringList([])
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("{} does not appear to be a trends.earth output file".format(f)))
                self.layers_model.setStringList([])
                self.btn_view_metadata.setEnabled(False)
                return None
        else:
            self.btn_view_metadata.setEnabled(False)
            self.layers_model.setStringList([])
            return None

        self.btn_view_metadata.setEnabled(True)
        return True


class LoadDataSelectFileInputWidget(QtGui.QWidget, Ui_WidgetLoadDataSelectFileInput):
    inputFileChanged = pyqtSignal(bool)
    inputTypeChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super(LoadDataSelectFileInputWidget, self).__init__(parent)
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
            self.btn_raster_dataset_browse.setEnabled(False)
            self.lineEdit_raster_file.setEnabled(False)
            self.comboBox_bandnumber.setEnabled(False)
            self.label_bandnumber.setEnabled(False)
            self.btn_polygon_dataset_browse.setEnabled(True)
            self.lineEdit_polygon_file.setEnabled(True)
            self.label_fieldname.setEnabled(True)
            self.comboBox_fieldname.setEnabled(True)

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
                                       self.tr("Cannot read {}. Choose a different file.".format(raster_file)))
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
                                       self.tr("Cannot read {}. Choose a different file.".format(vector_file)))
            self.inputFileChanged.emit(False)
            return False

        QSettings().setValue("LDMP/input_dir", os.path.dirname(vector_file))
        self.lineEdit_polygon_file.setText(vector_file)
        self.inputFileChanged.emit(True)

        self.comboBox_fieldname.addItems([field.name() for field in l.dataProvider().fields()])

        return l


class LoadDataSelectRasterOutput(QtGui.QWidget, Ui_WidgetLoadDataSelectRasterOutput):
    def __init__(self, parent=None):
        super(LoadDataSelectRasterOutput, self).__init__(parent)
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
                                           self.tr("Cannot write to {}. Choose a different file.".format(raster_file)))
                return False


class DlgLoadDataBase(QtGui.QDialog):
    """Base class for individual data loading dialogs"""
    def __init__(self, parent=None):
        super(DlgLoadDataBase, self).__init__(parent)

        self.setupUi(self)

        self.input_widget = LoadDataSelectFileInputWidget()
        self.verticalLayout.insertWidget(0, self.input_widget)

    def done(self, value):
        if value == QtGui.QDialog.Accepted:
            self.validate_input(value)
        else:
            super(DlgLoadDataBase, self).done(value)

    def validate_input(self, value):
        if self.input_widget.radio_raster_input.isChecked():
            if self.input_widget.lineEdit_raster_file.text() == '':
                QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Choose an input raster file."))
                return
        else:
            if self.input_widget.lineEdit_polygon_file.text() == '':
                QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Choose an input polygon dataset."))
                return
        super(DlgLoadDataBase, self).done(value)

    def get_resample_mode(self, f):
        ds_in = gdal.Open(f)
        gt_in = ds_in.GetGeoTransform()
        in_res = gt_in[1]
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

    def get_out_res_wgs84(self):
        if self.input_widget.groupBox_output_resolution.isChecked():
            # Calculate res in degrees from input which is in meters
            res = int(self.input_widget.spinBox_resolution.value())
            return res / (111.325 * 1000) # 111.325km in one degree
        else:
            ds_in = gdal.Open(self.input_widget.lineEdit_raster_file.text())
            gt_in = ds_in.GetGeoTransform()
            #TODO: Need to fix this to convert the in res to wgs84 if needed
            return gt_in[1]

    def remap_raster(self, remap_list):
        in_file = self.input_widget.lineEdit_raster_file.text()
        out_file = self.output_widget.lineEdit_output_file.text()

        # First warp the raster to the correct output res and CRS
        temp_tif = tempfile.NamedTemporaryFile(suffix='.tif').name
        self.warp_raster(temp_tif)

        log('Importing and recoding {} to {} using remap list: {}'.format(temp_tif, out_file, remap_list))
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
                      
        log('Importing {} to {}'.format(in_file, out_file))
        raster_import_worker = StartWorker(RasterImportWorker,
                                           'importing raster', temp_vrt, 
                                           out_file, self.get_out_res_wgs84(),
                                           self.get_resample_mode(temp_vrt))
        if not raster_import_worker.success:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Raster import failed."), None)
            return False
        else:
            return True

    def create_json(self, band_name, metadata):
        out_file = self.output_widget.lineEdit_output_file.text()
        out_json = os.path.splitext(out_file)[0] + '.json'
        band_info = [BandInfo(band_name, add_to_map=True, metadata=metadata)]
        create_local_json_metadata(out_json, out_file, band_info)
        schema = BandInfoSchema()
        return add_layer(out_file, 1, schema.dump(band_info[0]))


class DlgLoadDataLC(DlgLoadDataBase, Ui_DlgLoadDataLC):
    def __init__(self, parent=None):
        super(DlgLoadDataLC, self).__init__(parent)

        # This needs to be inserted after the lc definition widget but before 
        # the button box with ok/cancel
        self.output_widget = LoadDataSelectRasterOutput()
        self.verticalLayout.insertWidget(2, self.output_widget)

        self.input_widget.inputFileChanged.connect(self.input_changed)
        self.input_widget.inputTypeChanged.connect(self.input_changed)

        self.btn_agg_edit_def.clicked.connect(self.agg_edit)
        self.btn_agg_edit_def.setEnabled(False)

        self.dlg_agg = None

    def validate_input(self, value):
        if self.output_widget.lineEdit_output_file.text() == '':
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Choose an output file."))
            return
        if  not self.dlg_agg:
            QtGui.QMessageBox.information(None, self.tr("No definition set"), self.tr('Click "Edit Definition" to define the land cover definition before exporting.'.format(), None))
            return
        super(DlgLoadDataLC, self).validate_input(value)

        self.ok_clicked()

    def clear_dlg_agg(self):
        self.dlg_agg = None

    def showEvent(self, event):
        super(DlgLoadDataLC, self).showEvent(event)

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
        classes = [{'Initial_Code':str(value), 'Initial_Label':str(value), 'Final_Label':'No data', 'Final_Code':'-32768'} for value in sorted(values)]
        self.dlg_agg = DlgCalculateLCSetAggregation(classes, parent=self)

    def agg_edit(self):
        if self.input_widget.radio_raster_input.isChecked():
            f = self.input_widget.lineEdit_raster_file.text()
            band_number = int(self.input_widget.comboBox_bandnumber.currentText())
            if not self.dlg_agg or \
                    (self.last_raster != f or self.last_band_number != band_number):
                #TODO: Need to display a progress bar onscreen while this is happening
                values = get_unique_values(f, int(self.input_widget.comboBox_bandnumber.currentText()))
                if not values:
                    QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Error reading data. Trends.Earth supports a maximum of 50 different land cover classes".format(), None))
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
                values = get_unique_values(f, int(self.input_widget.comboBox_bandnumber.currentText()))
                values = l.uniqueValues(idx)
                if len(values) > 50:
                    QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Error reading data. Trends.Earth supports a maximum of 50 different land cover classes".format(), None))
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

        self.create_json('Land cover (7 class)',
                         {'year': int(self.input_widget.spinBox_data_year.date().year()),
                          'source': 'custom data'})

class DlgLoadDataSOC(DlgLoadDataBase, Ui_DlgLoadDataSOC):
    def __init__(self, parent=None):
        super(DlgLoadDataSOC, self).__init__(parent)

        # This needs to be inserted after the input widget but before the 
        # button box with ok/cancel
        self.output_widget = LoadDataSelectRasterOutput()
        self.verticalLayout.insertWidget(1, self.output_widget)

        self.btnBox.accepted.connect(self.ok_clicked)

    def ok_clicked(self):
        if self.input_widget.radio_raster_input.isChecked():
            in_file = self.input_widget.lineEdit_raster_file.text()
            self.warp_raster(temp_tif)
        else:
            self.convert_vector()

        self.create_json('Soil organic carbon',
                         {'year': int(self.input_widget.spinBox_data_year.date().year()),
                          'source': 'custom data'})


class DlgLoadDataProd(DlgLoadDataBase, Ui_DlgLoadDataProd):
    def __init__(self, parent=None):
        super(DlgLoadDataProd, self).__init__(parent)

        # This needs to be inserted after the input widget but before the 
        # button box with ok/cancel
        self.output_widget = LoadDataSelectRasterOutput()
        self.verticalLayout.insertWidget(1, self.output_widget)

        self.btnBox.accepted.connect(self.ok_clicked)

    def ok_clicked(self):
        if self.input_widget.radio_raster_input.isChecked():
            self.warp_raster("Land Productivity Dynamics (LPD)")
        else:
            self.convert_vector("Land Productivity Dynamics (LPD)")

        self.create_json('Soil organic carbon',
                         {'year': int(self.input_widget.spinBox_data_year.date().year()),
                          'source': 'custom data'})
