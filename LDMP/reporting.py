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
import csv
import json
import tempfile

import numpy as np

from osgeo import ogr, osr, gdal

import xlsxwriter

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


# Formula to calculate area of a raster cell, following
# https://gis.stackexchange.com/questions/127165/more-accurate-way-to-calculate-area-of-rasters
def calc_cell_area(ymin, ymax, x_width):
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
                layers_filtered.append(l)
        elif layer_type == 'perf':
            if m['script_id'] == "d2dcfb95-b8b7-4802-9bc0-9b72e586fc82":
                layers_filtered.append(l)
        elif layer_type == 'lc':
            if m['script_id'] == "9a6e5eb6-953d-4993-a1da-23169da0382e":
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
           QgsColorRampShader.ColorRampItem(9999, QtGui.QColor(0, 0, 0), QtGui.QApplication.translate('LDMPPlugin', 'No data'))]
    fcn.setColorRampItemList(lst)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(fcn)
    pseudoRenderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
    layer.setRenderer(pseudoRenderer)
    layer.triggerRepaint()
    iface.legendInterface().refreshLayerSymbology(layer)


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

                # Capture trends that are at least 95% significant
                deg[deg == -1] = 0 # not signif at 95%
                deg[deg == 1] = 0 # not signif at 95%
                deg[np.logical_and(deg >= -3, deg <= -2)] = -1
                deg[np.logical_and(deg >= 2, deg <= 3)] = 1
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
    """Mergies two crosstabs - allows for block-by-block crosstabs"""
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


def calc_total_table(a_trans, a_soc, total_table, cell_area):
    """Calculates an total table for an array"""
    if total_table:
        # Add in totals for past total_table if one is provided
        transitions = np.unique(np.concatenate([a_trans.ravel(), total_table[0]]))
        ind = np.concatenate(tuple(np.where(transitions == item)[0] for item in total_table[0]))
        totals = np.zeros(transitions.shape)
        np.add.at(totals, ind, total_table[1])
    else:
        transitions = np.unique(np.concatenate(a_trans))
        totals = np.zeros(transitions.shape)

    for transition in transitions:
        ind = np.where(transitions == transition)
        # Only sum values for this transition, and where soc has a valid value 
        # (negative values are missing data flags)
        vals = a_soc[np.logical_and(a_trans == transition, a_soc > 0)]
        totals[ind] += np.sum(vals * cell_area)

    return list((transitions, totals))

def calc_area_table(a, area_table, cell_area):
    """Calculates an area table for an array"""
    a_min = np.min(a)
    if a_min < 0:
        # Correction to add as bincount can only handle positive integers
        correction = np.abs(a_min)
    else:
        correction = 0

    n = np.bincount(a.ravel() + correction)
    this_vals = np.nonzero(n)[0]
    # Subtract correction from this_vals so area table has correct values
    this_area_table = list([this_vals - correction, n[this_vals]])

    # Don't use this_area_table if it is empty
    if this_area_table[0].size != 0:
        this_area_table[1] = this_area_table[1] * cell_area
        if area_table == None:
            area_table = this_area_table
        else:
            area_table = merge_area_tables(area_table, this_area_table)
    return area_table


def merge_area_tables(table1, table2):
    vals = np.unique(np.concatenate([table1[0], table2[0]]))
    count = np.zeros(vals.shape)
    def add_area_table(table):
        ind = np.concatenate(tuple(np.where(vals == item)[0] for item in table[0]))
        np.add.at(count, ind, table[1])
    add_area_table(table1)
    add_area_table(table2)
    return list((vals, count))


class AreaWorker(AbstractWorker):
    def __init__(self, in_file):
        AbstractWorker.__init__(self)
        self.in_file = in_file

    def work(self):
        ds = gdal.Open(self.in_file)
        band_deg = ds.GetRasterBand(1)
        band_base = ds.GetRasterBand(2)
        band_target = ds.GetRasterBand(3)
        band_trans = ds.GetRasterBand(4)
        band_soc = ds.GetRasterBand(5)

        block_sizes = band_deg.GetBlockSize()
        x_block_size = block_sizes[0]
        # Need to process y line by line so that pixel area calculation can be 
        # done based on latitude, which varies by line
        y_block_size = 1
        xsize = band_deg.XSize
        ysize = band_deg.YSize

        gt = ds.GetGeoTransform()
        # Width of cells in longitude
        long_width = gt[1]
        
        # Set initial lat ot the top left corner latitude
        lat = gt[3]
        # Width of cells in latitude
        pixel_height = gt[5]

        blocks = 0
        trans_xtab = None
        area_table_base = None
        area_table_target = None
        soc_totals_table = None
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

                cell_area = calc_cell_area(lat, lat + pixel_height, long_width)

                ################################
                # Calculate transition crosstabs
                a_deg = band_deg.ReadAsArray(x, y, cols, rows)
                a_trans = band_trans.ReadAsArray(x, y, cols, rows)

                # Flatten the arrays before passing to xtab
                this_trans_xtab = xtab(a_deg.ravel(), a_trans.ravel())

                # Don't use this_trans_xtab if it is empty (could happen if take a 
                # crosstab where all of the values are nan's)
                if this_trans_xtab[0][0].size != 0:
                    this_trans_xtab[1] = this_trans_xtab[1] * cell_area
                    if trans_xtab == None:
                        trans_xtab = this_trans_xtab
                    else:
                        trans_xtab = merge_xtabs(trans_xtab, this_trans_xtab)

                #################################
                # Calculate base and target areas
                area_table_base = calc_area_table(band_base.ReadAsArray(x, y, cols, rows),
                                                  area_table_base, cell_area)
                area_table_target = calc_area_table(band_target.ReadAsArray(x, y, cols, rows),
                                                    area_table_target, cell_area)

                #################################
                # Calculate SOC totals (converting soilgrids data from per ha 
                # to per m)
                a_soc = band_soc.ReadAsArray(x, y, cols, rows) * 1e-4
                # Note final units of soc_totals_table are tons C (summed over 
                # the total area of each class)
                soc_totals_table = calc_total_table(a_trans, a_soc,
                                                    soc_totals_table, cell_area)

                blocks += 1
            lat += pixel_height
        self.progress.emit(100)
        self.ds = None

        # Convert all area tables from meters into square kilometers
        area_table_base[1] = area_table_base[1] * 1e-6
        area_table_target[1] = area_table_target[1] * 1e-6
        trans_xtab[1] = trans_xtab[1] * 1e-6

        if self.killed:
            return None
        else:
            return list((area_table_base, area_table_target, soc_totals_table, 
                         trans_xtab))


# Returns value from crosstab table for particular deg/lc class combination
def get_xtab_area(table, deg_class=None, lc_class=None):
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
                        cutlineDSName=mask_layer_file, 
                        dstNodata=-9999, dstSRS="epsg:{}".format(self.dstSRS),
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
            # If the land cover is finer than the trajectory res, use mode to 
            # match the lc to the lower res productivity data
            log('Resampling with: mode, lowest')
            resampleAlg = gdal.GRA_Mode
            resample_to = 'lowest'
        else:
            # If the land cover is coarser than the trajectory res, use nearest 
            # neighbor and match the lc to the higher res productivity data
            log('Resampling with: nearest neighour, highest')
            resampleAlg = gdal.GRA_NearestNeighbour
            resample_to = 'highest'

        # Select from layer_traj using bandlist since signif is band 2
        traj_f = tempfile.NamedTemporaryFile(suffix='.vrt').name
        gdal.BuildVRT(traj_f, layer_traj.dataProvider().dataSourceUri(), bandList=[2], VRTNodata=-9999)
        # Select lc deg layer using bandlist since that layer is band 4
        lc_deg_f = tempfile.NamedTemporaryFile(suffix='.vrt').name
        gdal.BuildVRT(lc_deg_f, layer_lc.dataProvider().dataSourceUri(), bandList=[4], VRTNodata=-9999)

        ######################################################################
        # Combine rasters into a VRT and crop to the AOI
        
        # Compute the pixel-aligned bounding box (slightly larger than aoi). 
        # Use this instead of croptocutline in gdal.Warp in order to keep the 
        # pixels aligned.
        bb = self.aoi.boundingBox()
        minx = bb.xMinimum()
        miny = bb.yMinimum()
        maxx = bb.xMaximum()
        maxy = bb.yMaximum()
        left = minx - (minx - traj_gt[0]) % traj_gt[1]
        right = maxx + (traj_gt[1] - ((maxx - traj_gt[0]) % traj_gt[1]))
        bottom = miny + (traj_gt[5] - ((miny - traj_gt[3]) % traj_gt[5]))
        top = maxy - (maxy - traj_gt[3]) % traj_gt[5]
        outputBounds = [left, bottom, right, top]

        indic_f = tempfile.NamedTemporaryFile(suffix='.vrt').name
        log('Saving indicator VRT to: {}'.format(indic_f))
        gdal.BuildVRT(indic_f, 
                      [traj_f,
                       layer_perf.dataProvider().dataSourceUri(),
                       layer_state.dataProvider().dataSourceUri(),
                       lc_deg_f],
                      outputBounds=outputBounds,
                      resolution=resample_to,
                      resampleAlg=resampleAlg,
                      separate=True,
                      VRTNodata=-9999)
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
        # TODO: Fix these to refer to the proper bands in the lc file
        deg_lc_f = tempfile.NamedTemporaryFile(suffix='.vrt').name
        log('Saving deg/lc VRT to: {}'.format(deg_lc_f))

        # Select lc bands using bandlist since BuildVrt will otherwise only use 
        # the first band of the file
        lc_bl_f = tempfile.NamedTemporaryFile(suffix='.vrt').name
        gdal.BuildVRT(lc_bl_f, layer_lc.dataProvider().dataSourceUri(), 
                      bandList=[1], VRTNodata=-9999)
        lc_tg_f = tempfile.NamedTemporaryFile(suffix='.vrt').name
        gdal.BuildVRT(lc_tg_f, layer_lc.dataProvider().dataSourceUri(), 
                      bandList=[2], VRTNodata=-9999)
        lc_tr_f = tempfile.NamedTemporaryFile(suffix='.vrt').name
        gdal.BuildVRT(lc_tr_f, layer_lc.dataProvider().dataSourceUri(), 
                      bandList=[3], VRTNodata=-9999)
        lc_soc_f = tempfile.NamedTemporaryFile(suffix='.vrt').name
        gdal.BuildVRT(lc_soc_f, layer_lc.dataProvider().dataSourceUri(), 
                      bandList=[5], srcNodata=-32768, VRTNodata=-9999)

        gdal.BuildVRT(deg_lc_f, 
                      [deg_out_file,
                       lc_bl_f,
                       lc_tg_f,
                       lc_tr_f,
                       lc_soc_f],
                      outputBounds=outputBounds,
                      resolution=resample_to,
                      resampleAlg=resampleAlg,
                      separate=True, VRTNodata=-9999)
        # Clip and mask the lc/deg layer before calculating crosstab
        lc_clip_tempfile = tempfile.NamedTemporaryFile(suffix='.tif').name
        log('Saving deg/lc clipped file to {}'.format(lc_clip_tempfile))
        deg_lc_clip_worker = StartWorker(ClipWorker, 'masking land cover layers',
                                         deg_lc_f, 
                                         lc_clip_tempfile, self.aoi)
        if not deg_lc_clip_worker.success:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Error clipping land cover layer for area calculation."), None)
            return

        log('Calculating land cover crosstabulation...')
        area_worker = StartWorker(AreaWorker, 'calculating areas', lc_clip_tempfile)
        if not area_worker.success:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Error calculating degraded areas."), None)
            return
        else:
            base_areas, target_areas, soc_totals, trans_lpd_xtab = area_worker.get_return()

        x = [self.tr('Area Degraded'), self.tr('Area Stable'), self.tr('Area Improved'), self.tr('No Data')]
        y = [get_xtab_area(trans_lpd_xtab, -1, None),
             get_xtab_area(trans_lpd_xtab, 0, None),
             get_xtab_area(trans_lpd_xtab, -1, None),
             get_xtab_area(trans_lpd_xtab, 9999, None)]
        log('SDG 15.3.1 indicator total area: {}'.format(get_xtab_area(trans_lpd_xtab) - get_xtab_area(trans_lpd_xtab, 9999, None)))
        log('SDG 15.3.1 indicator areas (deg, stable, imp, no data): {}'.format(y))

        style_sdg_ld(deg_out_file)

        make_reporting_table(base_areas, target_areas, soc_totals, 
                             trans_lpd_xtab, 
                             os.path.join(self.output_folder.text(), 
                                          'reporting_table.xlsx'))

        dlg_plot = DlgPlotBars()
        labels = {'title': self.plot_title.text(),
                  'bottom': self.tr('Land cover'),
                  'left': [self.tr('Area'), self.tr('km<sup>2</sup>')]}
        dlg_plot.plot_data(x, y, labels)
        dlg_plot.show()
        dlg_plot.exec_()


def get_lc_area(table, code):
    ind = np.where(table[0] == code)[0]
    if ind.size == 0:
        return 0
    else:
        return float(table[1][ind])


def get_lpd_row(table, transition):
    return [get_xtab_area(table, -1, transition),
            get_xtab_area(table, 0, transition),
            get_xtab_area(table, 1, transition)]


def get_soc_per_ha(soc_table, xtab_areas, transition):
    # The "None" value below is used to return total area across all classes of 
    # degradation - this is just using the trans_lpd_xtab table as a shortcut 
    # to get the area of each transition class.
    area = get_xtab_area(xtab_areas, None, transition)
    ind = np.where(soc_table[0] == transition)[0]
    if ind.size == 0 or area == 0:
        return 0
    else:
        # The 1e2 is convert area from sq km to ha
        return float(soc_table[1][ind]) / (area * 1e2)


def make_reporting_table(base_areas, target_areas, soc_totals, trans_lpd_xtab, 
                         out_file):
    def tr(s):
        return QtGui.QApplication.translate("make_reporting_table", s)

    workbook = xlsxwriter.Workbook(out_file, {'nan_inf_to_errors': True})
    worksheet = workbook.add_worksheet()

    ########
    # Formats
    
    title_format = workbook.add_format({'bold': 1,
                                        'font_size': 18,
                                        'font_color': '#2F75B5'})
    subtitle_format = workbook.add_format({'bold': 1,
                                           'font_size': 16})
    warning_format = workbook.add_format({'bold': 1,
                                          'font_color': 'red',
                                          'font_size': 16})
    header_format = workbook.add_format({'bold': 1,
                                         'border': 1,
                                         'align': 'center',
                                         'valign': 'vcenter',
                                         'fg_color': 'F2F2F2',
                                         'text_wrap': 1})
    note_format = workbook.add_format({'italic': 1,
                                       'text_wrap': 1})
    total_header_format = workbook.add_format({'bold': 1, 'align': 'right'})
    total_number_format = workbook.add_format({'bold': 1, 'align': 'right', 'num_format': '0.0'})
    total_percent_format = workbook.add_format({'bold': 1, 'align': 'right', 'num_format': '0.0%'})
    num_format = workbook.add_format({'num_format': '0.0'})
    num_format_rb = workbook.add_format({'num_format': '0.0', 'right': 1})
    num_format_bb = workbook.add_format({'num_format': '0.0', 'bottom': 1})
    num_format_bb_rb = workbook.add_format({'num_format': '0.0', 'bottom': 1, 'right': 1})

    ########
    # Header
    worksheet.write('A1', tr("trends.earth reporting table"), title_format)
    worksheet.write('A2',"DRAFT - DATA UNDER REVIEW - DO NOT QUOTE", warning_format)
    #worksheet.write('A1', "LDN Target Setting Programme", title_format)
    #worksheet.write('A2',"Table 1 - Presentation of national basic data using the LDN indicators framework", subtitle_format)

    ##########
    # LC Table
    worksheet.merge_range('A4:A5', tr('Land Use/Cover Category'), header_format)
    worksheet.merge_range('E4:H4', tr('Net land productivity dynamics** (sq km)'),
                          header_format)
    worksheet.write_row('B4', [tr('Area (2000)'),
                               tr('Area (2015)'),
                               tr('Net area change (2000-2015)')],
                               header_format)
    worksheet.write_row('B5', [tr('sq km*'),
                               tr('sq km'),
                               tr('sq km'),
                               tr('Declining'),
                               tr('Stable'),
                               tr('Increasing'),
                               tr('No Data***'),
                               tr('ton/ha')],
                               header_format)
    worksheet.write('I4', tr('Soil organic carbon (2000)**'), header_format)

    worksheet.write_row('A6', [tr('Forest'), get_lc_area(base_areas, 1), get_lc_area(target_areas, 1)], num_format)
    worksheet.write_row('A7', [tr('Grasslands'), get_lc_area(base_areas, 2), get_lc_area(target_areas, 2)], num_format)
    worksheet.write_row('A8', [tr('Croplands'), get_lc_area(base_areas, 3), get_lc_area(target_areas, 3)], num_format)
    worksheet.write_row('A9', [tr('Wetlands'), get_lc_area(base_areas, 4), get_lc_area(target_areas, 4)], num_format)
    worksheet.write_row('A10', [tr('Artificial areas'), get_lc_area(base_areas, 5), get_lc_area(target_areas, 5)], num_format)
    worksheet.write_row('A11', [tr('Bare lands'), get_lc_area(base_areas, 6), get_lc_area(target_areas, 6)], num_format)
    worksheet.write_row('A12', [tr('Water bodies'), get_lc_area(base_areas, 7), get_lc_area(target_areas, 7)], num_format_bb)

    worksheet.write('D6', '=B6-C6', num_format)
    worksheet.write('D7', '=B7-C7', num_format)
    worksheet.write('D8', '=B8-C8', num_format)
    worksheet.write('D9', '=B9-C9', num_format)
    worksheet.write('D10', '=B10-C10', num_format)
    worksheet.write('D11', '=B11-C11', num_format)
    worksheet.write('D12', '=B12-C12', num_format_bb)

    worksheet.write_row('E6', get_lpd_row(trans_lpd_xtab, 11), num_format)
    worksheet.write_row('E7', get_lpd_row(trans_lpd_xtab, 22), num_format)
    worksheet.write_row('E8', get_lpd_row(trans_lpd_xtab, 33), num_format)
    worksheet.write_row('E9', get_lpd_row(trans_lpd_xtab, 44), num_format)
    worksheet.write_row('E10', get_lpd_row(trans_lpd_xtab, 55), num_format)
    worksheet.write_row('E11', get_lpd_row(trans_lpd_xtab, 66), num_format)
    worksheet.write_row('E12', ['', '', ''], num_format_bb)

    worksheet.write('H6', '=B6-SUM(E6:G6)', num_format)
    worksheet.write('H7', '=B7-SUM(E7:G7)', num_format)
    worksheet.write('H8', '=B8-SUM(E8:G8)', num_format)
    worksheet.write('H9', '=B9-SUM(E9:G9)', num_format)
    worksheet.write('H10', '=B10-SUM(E10:G10)', num_format)
    worksheet.write('H11', '=B11-SUM(E11:G11)', num_format)
    worksheet.write('H12', '', num_format_bb)

    worksheet.write('I6', get_soc_per_ha(soc_totals, trans_lpd_xtab, 11), num_format_rb)
    worksheet.write('I7', get_soc_per_ha(soc_totals, trans_lpd_xtab, 22), num_format_rb)
    worksheet.write('I8', get_soc_per_ha(soc_totals, trans_lpd_xtab, 33), num_format_rb)
    worksheet.write('I9', get_soc_per_ha(soc_totals, trans_lpd_xtab, 44), num_format_rb)
    worksheet.write('I10', get_soc_per_ha(soc_totals, trans_lpd_xtab, 55), num_format_rb)
    worksheet.write('I11', get_soc_per_ha(soc_totals, trans_lpd_xtab, 66), num_format_rb)
    worksheet.write('I12', '', num_format_bb_rb)

    worksheet.write('A13', tr('SOC average (ton/ha)'), total_header_format)
    worksheet.write('A14', tr('Percent of total land area'), total_header_format)
    worksheet.write('A15', tr('Total (sq km)*****'), total_header_format)
    worksheet.write('A15', tr('Total (sq km)*****'), total_header_format)

    worksheet.write('B15', '=SUM(B6:B12)', total_number_format)
    worksheet.write('C15', '=SUM(C6:C12)', total_number_format)
    worksheet.write('D15', '=SUM(D6:D12)', total_number_format)
    worksheet.write('E15', '=SUM(E6:E12)', total_number_format)
    worksheet.write('F15', '=SUM(F6:F12)', total_number_format)
    worksheet.write('G15', '=SUM(G6:G12)', total_number_format)
    worksheet.write('H15', '=SUM(H6:H12)', total_number_format)

    worksheet.write('I13', '=(B6*I6 + B7*I7 + B8*I8 + B9*I9 + B10*I10 + B11*I11 + B12*I12) / B15', total_number_format)
    worksheet.write('E14', '=E15/C15', total_percent_format)
    worksheet.write('F14', '=F15/C15', total_percent_format)
    worksheet.write('G14', '=G15/C15', total_percent_format)
    worksheet.write('H14', '=H15/C15', total_percent_format)

    ###########
    # LPD Table
    worksheet.merge_range('A18:A19', tr('Changing Land Use/Cover Category'), header_format)
    worksheet.merge_range('B18:E18', tr('Net land productivity dynamics trend (sq km)'), header_format)
    worksheet.write_row('B19', [tr('Declining'), tr('Stable'), tr('Increasing'), tr('Total^')], header_format)
    worksheet.write_row('A20', [tr('Bare lands >> Artificial areas')] + get_lpd_row(trans_lpd_xtab, 65), num_format)
    worksheet.write_row('A21', [tr('Cropland >> Artificial areas')] + get_lpd_row(trans_lpd_xtab, 35), num_format)
    worksheet.write_row('A22', [tr('Forest >> Artificial areas')] + get_lpd_row(trans_lpd_xtab, 15), num_format)
    worksheet.write_row('A23', [tr('Forest >> Bare lands')] + get_lpd_row(trans_lpd_xtab, 16), num_format)
    worksheet.write_row('A24', [tr('Forest >> Cropland')] + get_lpd_row(trans_lpd_xtab, 13), num_format)
    worksheet.write_row('A25', [tr('Forest >> Grasslands')] + get_lpd_row(trans_lpd_xtab, 12), num_format)
    worksheet.write_row('A26', [tr('Grasslands >> Artificial areas')] + get_lpd_row(trans_lpd_xtab, 25), num_format)
    worksheet.write_row('A27', [tr('Grasslands >> Cropland')] + get_lpd_row(trans_lpd_xtab, 23), num_format)
    worksheet.write_row('A28', [tr('Grasslands >> Forest')] + get_lpd_row(trans_lpd_xtab, 21), num_format)
    worksheet.write_row('A29', [tr('Wetlands >> Artificial areas')] + get_lpd_row(trans_lpd_xtab, 45), num_format)
    worksheet.write_row('A30', [tr('Wetlands >> Cropland')] + get_lpd_row(trans_lpd_xtab, 43), num_format_bb)

    worksheet.write('E20', '=sum(B20:D20)', num_format_rb)
    worksheet.write('E21', '=sum(B21:D21)', num_format_rb)
    worksheet.write('E22', '=sum(B22:D22)', num_format_rb)
    worksheet.write('E23', '=sum(B23:D23)', num_format_rb)
    worksheet.write('E24', '=sum(B24:D24)', num_format_rb)
    worksheet.write('E25', '=sum(B25:D25)', num_format_rb)
    worksheet.write('E26', '=sum(B26:D26)', num_format_rb)
    worksheet.write('E27', '=sum(B27:D27)', num_format_rb)
    worksheet.write('E28', '=sum(B28:D28)', num_format_rb)
    worksheet.write('E29', '=sum(B29:D29)', num_format_rb)
    worksheet.write('E30', '=sum(B30:D30)', num_format_bb_rb)

    ############
    # SOC Table
    worksheet.merge_range('A33:A34', tr('Changing Land Use/Cover Category'), header_format)
    worksheet.merge_range('C33:G33', tr('Soil organic carbon 0 - 30 cm (2000-2015)'), header_format)
    worksheet.write('B33', tr('Net area change^ (2000-2015)'), header_format)
    worksheet.write_row('B34', [tr('sq km'),
                                tr('2000 ton/ha'),
                                tr('2015 ton/ha'),
                                tr('2000 total (ton)'),
                                tr('2015 total (ton)****'),
                                tr('2000-2015 loss (ton)')], header_format)
    # The "None" values below are used to return total areas across all classes 
    # of degradation - this is just using the trans_lpd_xtab table as a 
    # shortcut to get the areas of each transition class.
    worksheet.write_row('A35', [tr('Bare lands >> Artificial areas'), get_xtab_area(trans_lpd_xtab, None, 65)], num_format)
    worksheet.write_row('A36', [tr('Cropland >> Artificial areas'), get_xtab_area(trans_lpd_xtab, None, 35)], num_format)
    worksheet.write_row('A37', [tr('Forest >> Artificial areas'), get_xtab_area(trans_lpd_xtab, None, 15)], num_format)
    worksheet.write_row('A38', [tr('Forest >> Bare lands'), get_xtab_area(trans_lpd_xtab, None, 16)], num_format)
    worksheet.write_row('A39', [tr('Forest >> Cropland'), get_xtab_area(trans_lpd_xtab, None, 13)], num_format)
    worksheet.write_row('A40', [tr('Forest >> Grasslands'), get_xtab_area(trans_lpd_xtab, None, 12)], num_format)
    worksheet.write_row('A41', [tr('Grasslands >> Artificial areas'), get_xtab_area(trans_lpd_xtab, None, 25)], num_format)
    worksheet.write_row('A42', [tr('Grasslands >> Cropland'), get_xtab_area(trans_lpd_xtab, None, 23)], num_format)
    worksheet.write_row('A43', [tr('Grasslands >> Forest'), get_xtab_area(trans_lpd_xtab, None, 21)], num_format)
    worksheet.write_row('A44', [tr('Wetlands >> Artificial areas'), get_xtab_area(trans_lpd_xtab, None, 45)], num_format)
    worksheet.write_row('A45', [tr('Wetlands >> Cropland'), get_xtab_area(trans_lpd_xtab, None, 43)], num_format_bb)
    worksheet.write('A46', tr('Total'), total_header_format)
    worksheet.write('A47', tr('Percent change total SOC stock (country)'), total_header_format)

    worksheet.write('C35', get_soc_per_ha(soc_totals, trans_lpd_xtab, 65), num_format)
    worksheet.write('C36', get_soc_per_ha(soc_totals, trans_lpd_xtab, 35), num_format)
    worksheet.write('C37', get_soc_per_ha(soc_totals, trans_lpd_xtab, 15), num_format)
    worksheet.write('C38', get_soc_per_ha(soc_totals, trans_lpd_xtab, 16), num_format)
    worksheet.write('C39', get_soc_per_ha(soc_totals, trans_lpd_xtab, 13), num_format)
    worksheet.write('C40', get_soc_per_ha(soc_totals, trans_lpd_xtab, 12), num_format)
    worksheet.write('C41', get_soc_per_ha(soc_totals, trans_lpd_xtab, 25), num_format)
    worksheet.write('C42', get_soc_per_ha(soc_totals, trans_lpd_xtab, 23), num_format)
    worksheet.write('C43', get_soc_per_ha(soc_totals, trans_lpd_xtab, 21), num_format)
    worksheet.write('C44', get_soc_per_ha(soc_totals, trans_lpd_xtab, 45), num_format)
    worksheet.write('C45', get_soc_per_ha(soc_totals, trans_lpd_xtab, 43), num_format_bb)

    worksheet.write('D35', '=C35', num_format)
    worksheet.write('D36', '=C36-((((C36-(0.1*C36))/20)*7.5))', num_format)
    worksheet.write('D37', '=C37-((((C37-(0.1*C37))/20)*7.5))', num_format)
    worksheet.write('D38', '=C38-((((C38-(0.1*C38))/20)*7.5))', num_format)
    worksheet.write('D39', '=C39-((((C39-(0.57*C39))/20)*7.5)+(((C39-(0.91*C39))/20)*7.5))', num_format)
    worksheet.write('D40', '=C40', num_format)
    worksheet.write('D41', '=C41-((((C41-(0.1*C41))/20)*7.5))', num_format)
    worksheet.write('D42', '=C42-((((C42-(0.57*C42))/20)*7.5)+(((C42-(0.91*C42))/20)*7.5))', num_format)
    worksheet.write('D43', '=C43', num_format)
    worksheet.write('D44', '=C44-((((C44-(0.1*C44))/20)*7.5))', num_format)
    worksheet.write('D45', '=C45-((((C45-(0.1*C45))/20)*7.5))', num_format_bb)

    worksheet.write('E35', '=B35*100*C35', num_format)
    worksheet.write('E36', '=B36*100*C36', num_format)
    worksheet.write('E37', '=B37*100*C37', num_format)
    worksheet.write('E38', '=B38*100*C38', num_format)
    worksheet.write('E39', '=B39*100*C39', num_format)
    worksheet.write('E40', '=B40*100*C40', num_format)
    worksheet.write('E41', '=B41*100*C41', num_format)
    worksheet.write('E42', '=B42*100*C42', num_format)
    worksheet.write('E43', '=B43*100*C43', num_format)
    worksheet.write('E44', '=B44*100*C44', num_format)
    worksheet.write('E45', '=B45*100*C45', num_format_bb)

    worksheet.write('F35', '=B35*100*D35', num_format)
    worksheet.write('F36', '=B36*100*D36', num_format)
    worksheet.write('F37', '=B37*100*D37', num_format)
    worksheet.write('F38', '=B38*100*D38', num_format)
    worksheet.write('F39', '=B39*100*D39', num_format)
    worksheet.write('F40', '=B40*100*D40', num_format)
    worksheet.write('F41', '=B41*100*D41', num_format)
    worksheet.write('F42', '=B42*100*D42', num_format)
    worksheet.write('F43', '=B43*100*D43', num_format)
    worksheet.write('F44', '=B44*100*D44', num_format)
    worksheet.write('F45', '=B45*100*D45', num_format_bb)

    worksheet.write('G35', '=F35-E35', num_format_rb)
    worksheet.write('G36', '=F36-E36', num_format_rb)
    worksheet.write('G37', '=F37-E37', num_format_rb)
    worksheet.write('G38', '=F38-E38', num_format_rb)
    worksheet.write('G39', '=F39-E39', num_format_rb)
    worksheet.write('G40', '=F40-E40', num_format_rb)
    worksheet.write('G41', '=F41-E41', num_format_rb)
    worksheet.write('G42', '=F42-E42', num_format_rb)
    worksheet.write('G43', '=F43-E43', num_format_rb)
    worksheet.write('G44', '=F44-E44', num_format_rb)
    worksheet.write('G45', '=F45-E45', num_format_bb_rb)

    worksheet.write('B46', '=SUM(B35:B45)', total_number_format)
    worksheet.write('E46', '=SUM(E35:E45)', total_number_format)
    worksheet.write('F46', '=SUM(F35:F45)', total_number_format)
    worksheet.write('G46', '=SUM(G35:G45)', total_number_format)
    worksheet.write('G47', '=G46/(I13*B15*100)', total_percent_format)

    worksheet.merge_range('A50:G50', tr("The boundaries, names, and designations used in this report do not imply official endorsement or acceptance by Conservation International Foundation, or its partner organizations and contributors.  This report is available under the terms of Creative Commons Attribution 4.0 International License (CC BY 4.0)."), note_format)


    ################################
    # Set col widths and row heights
    worksheet.set_column('A:A', 40)
    worksheet.set_column('B:I', 17)
    worksheet.set_row(3, 72)
    worksheet.set_row(4, 30)
    worksheet.set_row(17, 72)
    worksheet.set_row(18, 30)
    worksheet.set_row(32, 72)
    worksheet.set_row(33, 30)
    worksheet.set_row(49, 30)

    try:
        workbook.close()
        log('Indicator table saved to {}'.format(out_file))
        QtGui.QMessageBox.information(None, QtGui.QApplication.translate("LDMP", "Success"),
                               QtGui.QApplication.translate("LDMP", "Indicator table saved to {}.".format(out_file)), None)
    except IOError:
        log('Error saving {}'.format(out_file))
        QtGui.QMessageBox.critical(None, QtGui.QApplication.translate("LDMP", "Error"),
                                   QtGui.QApplication.translate("LDMP", "Error saving output table - check that {} is accessible and not already open.".format(out_file)), None)

    # with open(out_file, 'wb') as fh:
    #     writer = csv.writer(fh, delimiter=',')
    #     for row in rows:
    #         writer.writerow(row)


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
