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
        email                : GEF-LDMP@conservation.org
 ***************************************************************************/
"""

import os
import re
import csv
import json
import tempfile

import numpy as np

from osgeo import ogr, osr, gdal

from PyQt4 import QtGui, uic
from PyQt4.QtCore import QSettings, QEventLoop

from qgis.core import QgsGeometry, QgsProject, QgsLayerTreeLayer, QgsLayerTreeGroup, \
    QgsRasterLayer, QgsColorRampShader, QgsRasterShader, \
    QgsSingleBandPseudoColorRenderer, QgsVectorLayer, QgsFeature, \
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, \
    QgsVectorFileWriter
from qgis.utils import iface
mb = iface.messageBar()

import processing

from LDMP import log
from LDMP.calculate import DlgCalculateBase
from LDMP.plot import DlgPlotBars
from LDMP.gui.DlgReporting import Ui_DlgReporting
from LDMP.gui.DlgReportingSDG import Ui_DlgReportingSDG
from LDMP.gui.DlgReportingUNCCDProd import Ui_DlgReportingUNCCDProd
from LDMP.gui.DlgReportingUNCCDLC import Ui_DlgReportingUNCCDLC
from LDMP.gui.DlgReportingUNCCDSOC import Ui_DlgReportingUNCCDSOC
from LDMP.worker import AbstractWorker, start_worker

# Checks the file type (land cover, state, etc...) for a LDMP output file using
# the JSON accompanying each file


def get_file_type(data_file):
    json_file = os.path.splitext(data_file)[0] + '.json'
    try:
        with open(json_file) as f:
            d = json.load(f)
    except (OSError, IOError) as e:
        return None
    s = d.get('script_id', None)
    t = d.get('results', {}).get('type', None)
    if not s or not t:
        return None
    return {'script_id': s, 'type': t}


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


#  Calculate the area of a slice of the globe from the equator to the parallel 
#  at latitude f (on WGS84 ellipsoid). Based on:
# https://gis.stackexchange.com/questions/127165/more-accurate-way-to-calculate-area-of-rasters
def _slice_area(f):
    a = 6378137 # in meters
    b =  6356752.3142 # in meters,
    e = np.sqrt(1 - np.square(b / a))
    zp = 1 + e * np.sin(f)
    zm = 1 - e * np.sin(f)
    return np.pi * np.square(b) * ((2*np.arctanh(e * np.sin(f))) / (2 * e) + np.sin(f) / (zp * zm))


# Formula to calculate area of a raster cell Convert the contents of this_tab 
# to refer to areas in sq km, not to pixel counts, following:
# https://gis.stackexchange.com/questions/127165/more-accurate-way-to-calculate-area-of-rasters
def cell_area(ymin, ymax, x_width):
    'Calculate cell area on WGS84 ellipsoid'
    if ymin > ymax:
        temp = ymax
        ymax = ymin
        ymin = temp
    # ymin: minimum latitude
    # ymax: maximum latitude
    # x_width: width of cell in degrees
    return (_slice_area(np.deg2rad(ymax)) - _slice_area(np.deg2rad(ymin))) * (x_width / 360.)


# TODO: Should be determining layer types based on content of json, not on 
# filenames
def get_ld_layers(layer_type):
    root = QgsProject.instance().layerTreeRoot()
    layers = _get_layers(root)
    layers_filtered = []
    for l in layers:
        if not isinstance(l, QgsRasterLayer):
            # Allows skipping other layer types, like OpenLayers layers, that
            # are irrelevant for the toolbox
            continue
        f = l.dataProvider().dataSourceUri()
        m = get_file_type(f)
        if not m:
            # Ignore any layers that don't have .json files
            continue
        if layer_type == 'traj':
            if m['script_id'] == "13740fa7-4312-4cf2-829d-cdaee5a3d37c":
                layers_filtered.append(l)
        elif layer_type == 'state':
            if m['script_id'] == "cd03646c-9d4c-44a9-89ae-3309ae7bade3":
                if not '_eme_degr' in f:
                    continue
                layers_filtered.append(l)
        elif layer_type == 'perf':
            if m['script_id'] == "d2dcfb95-b8b7-4802-9bc0-9b72e586fc82":
                layers_filtered.append(l)
        elif layer_type == 'lc':
            if m['script_id'] == "9a6e5eb6-953d-4993-a1da-23169da0382e":
                if not '_land_deg' in f:
                    continue
                layers_filtered.append(l)
    return layers_filtered


def style_sdg_ld(outfile):
    # Significance layer
    log('Loading layers onto map.')
    layer = iface.addRasterLayer(outfile, QtGui.QApplication.translate('LDMPPlugin', 'Degradation (SDG 15.3 - without soil carbon)'))
    if not layer.isValid():
        log('Failed to add layer')
        return None
    fcn = QgsColorRampShader()
    fcn.setColorRampType(QgsColorRampShader.EXACT)
    lst = [QgsColorRampShader.ColorRampItem(-1, QtGui.QColor(153, 51, 4), QtGui.QApplication.translate('LDMPPlugin', 'Degradation')),
           QgsColorRampShader.ColorRampItem(0, QtGui.QColor(246, 246, 234), QtGui.QApplication.translate('LDMPPlugin', 'Stable')),
           QgsColorRampShader.ColorRampItem(1, QtGui.QColor(0, 140, 121), QtGui.QApplication.translate('LDMPPlugin', 'Improvement')),
           QgsColorRampShader.ColorRampItem(2, QtGui.QColor(58, 77, 214), QtGui.QApplication.translate('LDMPPlugin', 'Water')),
           QgsColorRampShader.ColorRampItem(3, QtGui.QColor(192, 105, 223), QtGui.QApplication.translate('LDMPPlugin', 'Urban land cover'))]
    fcn.setColorRampItemList(lst)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(fcn)
    pseudoRenderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
    layer.setRenderer(pseudoRenderer)
    layer.triggerRepaint()
    iface.legendInterface().refreshLayerSymbology(layer)


class ReprojectionWorker(AbstractWorker):
    def __init__(self, src_dataset, ref_dataset, out_file=None):
        AbstractWorker.__init__(self)

        self.src_dataset = src_dataset
        self.ref_dataset = ref_dataset
        if out_file:
            self.out_file = out_file
        else:
            self.out_file = tempfile.NamedTemporaryFile(suffix='.tif').name

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        ds_ref = gdal.Open(self.ref_dataset)
        sr_dest = osr.SpatialReference()
        sr_dest.ImportFromWkt(ds_ref.GetProjectionRef())

        src_ds = gdal.Open(self.src_dataset)
        sr_src = osr.SpatialReference()
        sr_src.ImportFromWkt(src_ds.GetProjectionRef())

        driver = gdal.GetDriverByName("GTiff")
        ds_dest = driver.Create(self.out_file, ds_ref.RasterXSize, 
                                ds_ref.RasterYSize, 1, gdal.GDT_Int16, 
                                ['COMPRESS=LZW'])

        gt_ref = ds_ref.GetGeoTransform()
        ds_dest.SetGeoTransform(gt_ref)
        ds_dest.SetProjection(sr_dest.ExportToWkt())

        gt_src = src_ds.GetGeoTransform()
        if gt_ref[1] > gt_src[1]:
            # If new dataset is a lower resolution than the source, use the MODE
            log('Resampling with: mode')
            resample_alg = gdal.GRA_Mode
        else:
            log('Resampling with: nearest neighour')
            resample_alg = gdal.GRA_NearestNeighbour
        # Perform the projection/resampling
        res = gdal.ReprojectImage(src_ds,
                                  ds_dest,
                                  sr_src.ExportToWkt(),
                                  sr_dest.ExportToWkt(),
                                  resample_alg,
                                  dstNodata=9999,
                                  callback=self.progress_callback)
        if res == 0:
            return ds_dest
        else:
            return None

    def progress_callback(self, fraction, message, data):
        if self.killed:
            return False
        else:
            self.progress.emit(100 * fraction)
            return True


class DegradationWorker(AbstractWorker):
    def __init__(self, src_file):
        AbstractWorker.__init__(self)

        self.src_file = src_file

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        src_ds = gdal.Open(self.src_file)

        traj_band = src_ds.GetRasterBand(1)
        perf_band = src_ds.GetRasterBand(2)
        state_band = src_ds.GetRasterBand(3)
        lc_band = src_ds.GetRasterBand(4)

        block_sizes = traj_band.GetBlockSize()
        x_block_size = block_sizes[0]
        y_block_size = block_sizes[1]
        xsize = traj_band.XSize
        ysize = traj_band.YSize

        driver = gdal.GetDriverByName("GTiff")
        temp_deg_file = tempfile.NamedTemporaryFile(suffix='.tif').name
        dst_ds = driver.Create(temp_deg_file, xsize, ysize, 1, gdal.GDT_Int16, ['COMPRESS=LZW'])

        src_gt = src_ds.GetGeoTransform()
        dst_ds.SetGeoTransform(src_gt)
        dst_srs = osr.SpatialReference()
        dst_srs.ImportFromWkt(src_ds.GetProjectionRef())
        dst_ds.SetProjection(dst_srs.ExportToWkt())

        xsize = traj_band.XSize
        ysize = traj_band.YSize
        blocks = 0
        for y in xrange(0, ysize, y_block_size):
            if self.killed:
                log("Processing of {} killed by user after processing {} out of {} blocks.".format(temp_deg_file, y, ysize))
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

                # TODO: Could make this cleaner by reading all four bands at 
                # same time from VRT
                deg = traj_band.ReadAsArray(x, y, cols, rows)
                state_array = state_band.ReadAsArray(x, y, cols, rows)
                perf_array = perf_band.ReadAsArray(x, y, cols, rows)
                lc_array = lc_band.ReadAsArray(x, y, cols, rows)

                deg[lc_array == -1] = -1
                deg[(state_array == -1) & (perf_array == -1)] = -1

                dst_ds.GetRasterBand(1).WriteArray(deg, x, y)
                del deg
                blocks += 1
        self.progress.emit(100)
        src_ds = None
        dst_ds = None

        if self.killed:
            os.remove(temp_deg_file)
            return None
        else:
            return temp_deg_file

def xtab(*cols):
    # Based on https://gist.github.com/alexland/d6d64d3f634895b9dc8e, but
    # modified to ignore np.nan
    if not all(len(col) == len(cols[0]) for col in cols[1:]):
     raise ValueError("all arguments must be same size")

    if len(cols) == 0:
        raise TypeError("xtab() requires at least one argument")

    fnx1 = lambda q: len(q.squeeze().shape)
    if not all([fnx1(col) == 1 for col in cols]):
        raise ValueError("all input arrays must be 1D")
        
    # Filter na values out of all columns
    nafilter = ~np.any(np.isnan(cols), 0)

    headers, idx = zip( *(np.unique(col[nafilter], return_inverse=True) for col in cols) )
    shape_xt = [uniq_vals_col.size for uniq_vals_col in headers]
    xt = np.zeros(shape_xt)
    np.add.at(xt, idx, 1)

    return list((headers, xt))


def merge_xtabs(tab1, tab2):
    """Function for merging two crosstabs - allows for block-by-block crosstabs"""
    headers = tuple(np.array(np.unique(np.concatenate(header))) for header in zip(tab1[0], tab2[0]))
    shape_xt = [uniq_vals_col.size for uniq_vals_col in headers]
    # Make this array flat since it will be used later with ravelled indexing
    xt = np.zeros(np.prod(shape_xt))

    # This handles combining a crosstab from a new block with an existing one 
    # that has been maintained across blocks
    def add_xt_block(xt_bl):
        col_ind = np.tile(tuple(np.where(headers[0] == item) for item in xt_bl[0][0]), xt_bl[0][1].size)
        row_ind = np.transpose(np.tile(tuple(np.where(headers[1] == item) for item in xt_bl[0][1]), xt_bl[0][0].size))
        ind = np.ravel_multi_index((col_ind, row_ind), shape_xt)
        np.add.at(xt, ind.ravel(), xt_bl[1].ravel())
    add_xt_block(tab1)
    add_xt_block(tab2)

    return list((headers, xt.reshape(shape_xt)))


class CrosstabWorker(AbstractWorker):
    def __init__(self, in_file):
        AbstractWorker.__init__(self)
        self.in_file = in_file

    def work(self):
        ds = gdal.Open(self.in_file)
        band_1 = ds.GetRasterBand(1)
        band_2 = ds.GetRasterBand(2)

        block_sizes = band_1.GetBlockSize()
        x_block_size = block_sizes[0]
        # Need to process y line by line so that pixel area calculation can be 
        # done accurately (to calculate area of each pixel based on latitude)
        y_block_size = 1
        xsize = band_1.XSize
        ysize = band_1.YSize

        gt = ds.GetGeoTransform()
        # Width of cells in longitude
        long_width = gt[1]
        
        # Set initial lat ot the top left corner latitude
        lat = gt[3]
        # Width of cells in latitude
        pixel_height = gt[5]

        blocks = 0
        tab = None
        for y in xrange(0, ysize, y_block_size):
            if self.killed:
                log("Processing killed by user after processing {} out of {} blocks.".format(y, ysize))
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

                a1 = band_1.ReadAsArray(x, y, cols, rows)
                a2 = band_2.ReadAsArray(x, y, cols, rows)

                # Flatten the arrays before passing to xtab
                this_tab = xtab(a1.ravel(), a2.ravel())

                # Don't use this_tab if it is empty (could happen if take a 
                # crosstab where all of the values are nan's)
                if this_tab[0][0].size != 0:
                    this_tab[1] = this_tab[1] * cell_area(lat, lat + pixel_height, long_width)
                    if tab == None:
                        tab = this_tab
                    else:
                        tab = merge_xtabs(tab, this_tab)

                blocks += 1
            lat += pixel_height
        self.progress.emit(100)
        self.ds_1 = None
        self.ds_2 = None

        if self.killed:
            return None
        else:
            return tab


# Returns value from crosstab table for particular deg/lc class combination
def get_area(table, deg_class=None, lc_class=None):
    deg_ind = np.where(table[0][0] == deg_class)[0]
    lc_ind = np.where(table[0][1] == lc_class)[0]
    if deg_ind.size != 0 and lc_ind.size != 0:
        return float(table[1][deg_ind, lc_ind])
    elif deg_ind.size != 0 and lc_class == None:
        return float(np.sum(table[1][deg_ind, :]))
    elif lc_ind.size != 0 and deg_class == None:
        return float(np.sum(table[1][:, lc_ind]))
    elif lc_class == None and deg_class == None:
        return float(np.sum(table[1].ravel()))
    else:
        return 0


class ClipWorker(AbstractWorker):
    def __init__(self, in_file, out_file, aoi, dstSRS=None):
        AbstractWorker.__init__(self)

        self.in_file = in_file
        self.out_file = out_file
        # Make a copy of the geometry so that we aren't modifying the CRS of 
        # the original
        self.aoi = QgsGeometry(aoi)
        if dstSRS:
            self.dstSRS = dstSRS
        else:
            self.dstSRS = 4326

        if self.dstSRS != 4326:
            crs_src = QgsCoordinateReferenceSystem(4326)
            crs_dest = QgsCoordinateReferenceSystem(self.dstSRS)
            self.aoi.transform(QgsCoordinateTransform(crs_src, crs_dest))

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)
        
        mask_layer = QgsVectorLayer("Polygon?crs=epsg:{}".format(self.dstSRS), "mask", "memory")
        mask_pr = mask_layer.dataProvider()
        fet = QgsFeature()
        fet.setGeometry(self.aoi)
        mask_pr.addFeatures([fet])
        mask_layer_file = tempfile.NamedTemporaryFile(suffix='.shp').name
        QgsVectorFileWriter.writeAsVectorFormat(mask_layer, mask_layer_file,
                                                "CP1250", None, "ESRI Shapefile")

        res = gdal.Warp(self.out_file, self.in_file, format='GTiff',
                        cutlineDSName=mask_layer_file, cropToCutline=True,
                        dstNodata=9999, dstSRS="epsg:{}".format(self.dstSRS),
                        outputType=gdal.GDT_Int16,
                        resampleAlg=gdal.GRA_NearestNeighbour,
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


class StartWorker(object):
    def __init__(self, worker_class, process_name, *args):
        self.exception = None
        self.success = None

        self.worker = worker_class(*args)

        pause = QEventLoop()
        self.worker.finished.connect(pause.quit)
        self.worker.successfully_finished.connect(self.save_success)
        self.worker.error.connect(self.save_exception)
        start_worker(self.worker, iface,
                     QtGui.QApplication.translate("LDMP", 'Processing: {}').format(process_name))
        pause.exec_()

        if self.exception:
            raise self.exception

    def save_success(self, val=None):
        self.return_val = val
        self.success = True

    def get_return(self):
        return self.return_val

    def save_exception(self, exception):
        self.exception = exception

    def get_exception(self):
        return self.exception


class DlgReporting(QtGui.QDialog, Ui_DlgReporting):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgReporting, self).__init__(parent)
        self.setupUi(self)

        self.dlg_sdg = DlgReportingSDG()
        self.dlg_unncd_prod = DlgReportingUNCCDProd()
        self.dlg_unncd_lc = DlgReportingUNCCDLC()
        self.dlg_unncd_soc = DlgReportingUNCCDSOC()

        self.btn_sdg.clicked.connect(self.clicked_sdg)
        self.btn_unccd_prod.clicked.connect(self.clicked_unccd_prod)
        self.btn_unccd_lc.clicked.connect(self.clicked_unccd_lc)
        self.btn_unccd_soc.clicked.connect(self.clicked_unccd_soc)

    def clicked_sdg(self):
        self.close()
        self.dlg_sdg.exec_()

    def clicked_unccd_prod(self):
        self.close()
        self.dlg_unncd_prod.exec_()

    def clicked_unccd_lc(self):
        self.close()
        result = self.dlg_unncd_lc.exec_()

    def clicked_unccd_soc(self):
        QMessageBox.critical(None, QApplication.translate('LDMP', "Error"),
                             QApplication.translate('LDMP', "Raw data download coming soon!"), None)
        # self.close()
        # self.dlg_unncd_soc.exec_()


class DlgReportingSDG(DlgCalculateBase, Ui_DlgReportingSDG):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgReportingSDG, self).__init__(parent)
        self.setupUi(self)
        self.setup_dialog()

        self.browse_output_folder.clicked.connect(self.select_output_folder)

    def showEvent(self, event):
        super(DlgReportingSDG, self).showEvent(event)
        self.populate_layers_traj()
        self.populate_layers_perf()
        self.populate_layers_state()
        self.populate_layers_lc()

    def populate_layers_traj(self):
        self.layer_traj.clear()
        self.layer_traj_list = get_ld_layers('traj')
        self.layer_traj.addItems([l.name() for l in self.layer_traj_list])

    def populate_layers_perf(self):
        self.layer_perf.clear()
        self.layer_perf_list = get_ld_layers('perf')
        self.layer_perf.addItems([l.name() for l in self.layer_perf_list])

    def populate_layers_state(self):
        self.layer_state.clear()
        self.layer_state_list = get_ld_layers('state')
        self.layer_state.addItems([l.name() for l in self.layer_state_list])

    def populate_layers_lc(self):
        self.layer_lc.clear()
        self.layer_lc_list = get_ld_layers('lc')
        self.layer_lc.addItems([l.name() for l in self.layer_lc_list])

    def select_output_folder(self):
        output_dir = QtGui.QFileDialog.getExistingDirectory(self,
                                                            self.tr("Directory to save files"),
                                                            QSettings().value("LDMP/output_dir", None),
                                                            QtGui.QFileDialog.ShowDirsOnly)
        if output_dir:
            if os.access(output_dir, os.W_OK):
                QSettings().setValue("LDMP/output_dir", output_dir)
                log("Outputing results to {}".format(output_dir))
            else:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Cannot write to {}. Choose a different folder.".format(output_dir), None))
        self.output_folder.setText(output_dir)

    def btn_calculate(self):
        if not self.output_folder.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Choose an output folder where the output will be saved."), None)
            return

        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgReportingSDG, self).btn_calculate()
        if not ret:
            return

        if len(self.layer_traj_list) == 0:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("You must add a productivity trajectory indicator layer to your map before you can use the reporting tool."), None)
            return
        if len(self.layer_state_list) == 0:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("You must add a productivity state indicator layer to your map before you can use the reporting tool."), None)
            return
        if len(self.layer_perf_list) == 0:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("You must add a productivity performance indicator layer to your map before you can use the reporting tool."), None)
            return
        if len(self.layer_lc_list) == 0:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("You must add a land cover indicator layer to your map before you can use the reporting tool."), None)
            return

        if not self.plot_area_deg.isChecked() and not \
                self.plot_area_stable.isChecked() and not \
                self.plot_area_imp.isChecked() and not \
                self.plot_area_water.isChecked() and not \
                self.plot_area_urban.isChecked() and not \
                self.plot_area_nodata.isChecked():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Choose at least one indicator to plot."), None)
            return

        layer_traj = self.layer_traj_list[self.layer_traj.currentIndex()]
        layer_state = self.layer_state_list[self.layer_state.currentIndex()]
        layer_perf = self.layer_perf_list[self.layer_perf.currentIndex()]
        layer_lc = self.layer_lc_list[self.layer_lc.currentIndex()]

        # Check that all of the layers have the same coordinate system and TODO
        # are in 4326.
        if layer_traj.crs() != layer_state.crs():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Coordinate systems of trajectory layer and state layer do not match."), None)
            return
        if layer_traj.crs() != layer_perf.crs():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Coordinate systems of trajectory layer and performance layer do not match."), None)
            return
        # TODO: this shouldn't be referencing layer_lc - it should be
        # referencing the extent of the reprojected land cover layer.
        if layer_traj.crs() != layer_lc.crs():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Coordinate systems of trajectory layer and land cover layer do not match."), None)
            return

        # Check that all of the layers have the same resolution
        def res(layer):
            return (round(layer.rasterUnitsPerPixelX(), 10), round(layer.rasterUnitsPerPixelY(), 10))
        if res(layer_traj) != res(layer_state):
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Resolutions of trajectory layer and state layer do not match."), None)
            return
        if res(layer_traj) != res(layer_perf):
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Resolutions of trajectory layer and performance layer do not match."), None)
            return

        # Check that all of the layers cover the area of interest
        if not self.aoi.within(QgsGeometry.fromRect(layer_traj.extent())):
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Area of interest is not entirely within the trajectory layer."), None)
            return
        if not self.aoi.within(QgsGeometry.fromRect(layer_state.extent())):
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Area of interest is not entirely within the state layer."), None)
            return
        if not self.aoi.within(QgsGeometry.fromRect(layer_perf.extent())):
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Area of interest is not entirely within the performance layer."), None)
            return
        if not self.aoi.within(QgsGeometry.fromRect(layer_lc.extent())):
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Area of interest is not entirely within the land cover layer."), None)
            return

        # If prod layers are lower res than the lc layer, then resample lc 
        # using the mode. Otherwise use nearest neighbor:
        ds_lc = gdal.Open(layer_lc.dataProvider().dataSourceUri())
        ds_traj = gdal.Open(layer_traj.dataProvider().dataSourceUri())
        lc_gt = ds_lc.GetGeoTransform()
        traj_gt = ds_traj.GetGeoTransform()
        if lc_gt[1] < traj_gt[1]:
            log('Resampling with: mode')
            resampleAlg = gdal.GRA_Mode
        else:
            log('Resampling with: nearest neighour')
            resampleAlg = gdal.GRA_NearestNeighbour

        # Select from layer_traj using bandlist since signif is band 2
        traj_f = tempfile.NamedTemporaryFile(suffix='.vrt').name
        gdal.BuildVRT(traj_f, layer_traj.dataProvider().dataSourceUri(), bandList=[2])

        # Combine rasters into a VRT and crop to the AOI
        bb = self.aoi.boundingBox()
        outputBounds = [bb.xMinimum(), bb.yMinimum(), bb.xMaximum(), bb.yMaximum()]
        indic_f = tempfile.NamedTemporaryFile(suffix='.vrt').name
        log('Saving indicator VRT to: {}'.format(indic_f))
        gdal.BuildVRT(indic_f, 
                      [traj_f,
                       layer_perf.dataProvider().dataSourceUri(),
                       layer_state.dataProvider().dataSourceUri(),
                       layer_lc.dataProvider().dataSourceUri()],
                      outputBounds=outputBounds,
                      resolution='highest',
                      resampleAlg=resampleAlg,
                      separate=True)
        self.close()

        ######################################################################
        #  Calculate degradation
        
        log('Calculating degradation...')
        deg_worker = StartWorker(DegradationWorker, 'calculating degradation', 
                                 indic_f)
        if not deg_worker.success:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Error calculating degradation layer."), None)
            return
        else:
            deg_file = deg_worker.get_return()

        ######################################################################
        #  Clip final degradation layer
        
        log('Clipping and masking degradation layers...')
        # Clip a degradation layer for display
        deg_out_file = os.path.join(self.output_folder.text(), 'sdg_15_3_degradation.tif')
        log('Saving degradation file to {}'.format(deg_out_file))
        clip_worker = StartWorker(ClipWorker, 'masking degradation layer',
                                  deg_file, deg_out_file, self.aoi)
        if not clip_worker.success:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Error clipping degradation layer."), None)
            return

        ######################################################################
        # Make a vrt with the lc transition layer and deg layer
        lc_trans_file = re.sub('land_deg', 'lc_change', layer_lc.dataProvider().dataSourceUri())
        deg_lc_f = tempfile.NamedTemporaryFile(suffix='.vrt').name
        log('Saving deg/lc VRT to: {}'.format(deg_lc_f))
        gdal.BuildVRT(deg_lc_f, 
                      [deg_out_file, lc_trans_file],
                      outputBounds=outputBounds,
                      resolution='highest',
                      resampleAlg=resampleAlg,
                      separate=True)
        # Clip and mask the lc/deg layer before calculating crosstab
        lc_clip_tempfile = tempfile.NamedTemporaryFile(suffix='.tif').name
        log('Saving deg/lc clipped file to {}'.format(lc_clip_tempfile))
        deg_lc_clip_worker = StartWorker(ClipWorker, 'masking land cover layer',
                                         deg_lc_f, 
                                         lc_clip_tempfile, self.aoi)
        if not deg_lc_clip_worker.success:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Error clipping land cover layer for area calculation."), None)
            return


        log('Calculating areas and crosstabs...')
        tab_worker = StartWorker(CrosstabWorker, 'calculating areas', lc_clip_tempfile)
        if not tab_worker.success:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Error calculating degraded areas."), None)
            return
        else:
            table = tab_worker.get_return()
        # Convert areas from sq meters to sq km
        table[1] = table[1] * 1e-6

        # TODO: Make sure no data, water areas, and urban areas are symmetric 
        # across LD layer and lc layer
        self.deg = {"Area Degraded": get_area(table, -1, None),
                    "Area Stable": get_area(table, 0, None),
                    "Area Improved": get_area(table, 1, None),
                    "No Data": get_area(table, 9999, None),
                    "Water Area": get_area(table, 2, None),
                    "Urban Area": get_area(table, 3, None)}
        log('SDG 15.3.1 indicator: {}'.format(self.deg))
        log('SDG 15.3.1 indicator total area: {}'.format(get_area(table) - get_area(table, 9999, None)))

        style_sdg_ld(deg_out_file)

        make_reporting_table(table,
                os.path.join(self.output_folder.text(), 'reporting_table.csv'))

        # Plot the output
        x = []
        y = []
        if self.plot_area_deg.isChecked():
            x.append('Area Degraded')
            y.append(self.deg['Area Degraded'])
        if self.plot_area_stable.isChecked():
            x.append('Area Stable')
            y.append(self.deg['Area Stable'])
        if self.plot_area_imp.isChecked():
            x.append('Area Improved')
            y.append(self.deg['Area Improved'])
        if self.plot_area_water.isChecked():
            x.append('Water Area')
            y.append(self.deg['Water Area'])
        if self.plot_area_urban.isChecked():
            x.append('Urban Area')
            y.append(self.deg['Urban Area'])
        if self.plot_area_nodata.isChecked():
            x.append('No Data')
            y.append(self.deg['No Data'])

        dlg_plot = DlgPlotBars()
        labels = {'title': self.plot_title.text(),
                  'bottom': 'Land cover',
                  'left': ['Area', 'km^2']}
        dlg_plot.plot_data(x, y, labels)
        dlg_plot.show()
        dlg_plot.exec_()


def get_report_row(table, name, transition):
    return [name,
            get_area(table, -1, transition),
            get_area(table, 0, transition),
            get_area(table, 1, transition)]


def make_reporting_table(table, out_file):
    rows = []
    rows.append(['', 'Net land productivity dynamics trend (sq km)'])
    rows.append(['Changing Land Use/Cover Category', 'Decline', 'Stable', 'Increase'])
    rows.append(['Bare lands >> Artificial areas', np.nan, np.nan, np.nan])
    rows.append(get_report_row(table, 'Cropland >> Artificial areas', 15))
    rows.append(get_report_row(table, 'Forest >> Artificial areas', 25))
    rows.append(['Forest >> Bare lands', np.nan, np.nan, np.nan])
    rows.append(get_report_row(table, 'Forest >> Cropland', 21))
    rows.append(get_report_row(table, 'Forest >> Grasslands', 23))
    rows.append(get_report_row(table, 'Grasslands >> Artificial areas', 35))
    rows.append(get_report_row(table, 'Grasslands >> Cropland', 31))
    rows.append(get_report_row(table, 'Grasslands >> Forest', 32))
    rows.append(get_report_row(table, 'Wetlands >> Artificial areas', 45))
    rows.append(get_report_row(table, 'Wetlands >> Cropland', 41))
    with open(out_file, 'wb') as fh:
        writer = csv.writer(fh, delimiter=',')
        for row in rows:
            writer.writerow(row)


class DlgReportingUNCCDProd(QtGui.QDialog, Ui_DlgReportingUNCCDProd):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgReportingUNCCDProd, self).__init__(parent)
        self.setupUi(self)


class DlgReportingUNCCDLC(QtGui.QDialog, Ui_DlgReportingUNCCDLC):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgReportingUNCCDLC, self).__init__(parent)
        self.setupUi(self)


class DlgReportingUNCCDSOC(QtGui.QDialog, Ui_DlgReportingUNCCDSOC):
    def __init__(self, parent=None):
        """Constructor."""
        super(DlgReportingUNCCDSOC, self).__init__(parent)
        self.setupUi(self)
