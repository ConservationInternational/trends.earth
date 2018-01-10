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
import json
import tempfile

import numpy as np

from osgeo import ogr, osr, gdal

import xlsxwriter

from PyQt4 import QtGui, uic, QtXml
from PyQt4.QtCore import QSettings, QEventLoop

from qgis.core import QgsGeometry, QgsProject, QgsLayerTreeLayer, QgsLayerTreeGroup, \
    QgsRasterLayer, QgsColorRampShader, QgsRasterShader, \
    QgsSingleBandPseudoColorRenderer, QgsVectorLayer, QgsFeature, \
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, \
    QgsVectorFileWriter, QgsMapLayerRegistry, QgsMapSettings, QgsComposition
from qgis.gui import QgsComposerView
from qgis.utils import iface
mb = iface.messageBar()

from LDMP import log
from LDMP.calculate import DlgCalculateBase
from LDMP.load_data import get_results
from LDMP.plot import DlgPlotBars
from LDMP.gui.DlgReporting import Ui_DlgReporting
from LDMP.gui.DlgReportingSDG import Ui_DlgReportingSDG
from LDMP.gui.DlgReportingUNCCD import Ui_DlgReportingUNCCD
from LDMP.gui.DlgCreateMap import Ui_DlgCreateMap
from LDMP.worker import AbstractWorker, start_worker

# Checks the file type (land cover, state, etc...) for a LDMP output file using
# the JSON accompanying each file


def get_band_info(data_file):
    json_file = os.path.splitext(data_file)[0] + '.json'
    res = get_results(json_file)
    if res:
        return res['bands']
    else:
        return None


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
    b = 6356752.3142 # in meters,
    e = np.sqrt(1 - np.square(b / a))
    zp = 1 + e * np.sin(f)
    zm = 1 - e * np.sin(f)
    return np.pi * np.square(b) * ((2 * np.arctanh(e * np.sin(f))) / (2 * e) + np.sin(f) / (zp * zm))


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


# Get a list of layers of a particular type, out of those in the TOC that were
# produced by trends.earth
def get_ld_layers(layer_type=None):
    root = QgsProject.instance().layerTreeRoot()
    layers_filtered = []
    layers = _get_layers(root)
    if len(layers) > 0:
        for l in layers:
            if not isinstance(l, QgsRasterLayer):
                # Allows skipping other layer types, like OpenLayers layers, that
                # are irrelevant for the toolbox
                continue
            band_infos = get_band_info(l.dataProvider().dataSourceUri())
            # Layers not produced by trends.earth won't have bandinfo, and 
            # aren't of interest, so skip if there is no bandinfo.
            if band_infos:
                band_number = l.renderer().usesBands()
                # Note the below is true so long as none of the needed layers use more 
                # than one band.
                if len(band_number) == 1:
                    band_number = band_number[0]
                    name = [band_info['name'] for band_info in band_infos if band_info['band_number'] == band_number]
                    name = name[0]
                    if layer_type == 'traj_sig' and name == 'Productivity trajectory (significance)':
                        layers_filtered.append((l, band_number))
                    elif layer_type == 'state_deg' and name == 'Productivity state (degradation)':
                        layers_filtered.append((l, band_number))
                    elif layer_type == 'perf_deg' and name == 'Productivity performance (degradation)':
                        layers_filtered.append((l, band_number))
                    elif layer_type == 'lc_tr' and name == 'Land cover transitions':
                        layers_filtered.append((l, band_number))
                    elif layer_type == 'lc_deg' and name == 'Land cover degradation':
                        layers_filtered.append((l, band_number))
                    elif layer_type == 'soc_deg' and name == 'Soil organic carbon (degradation)':
                        layers_filtered.append((l, band_number))
                    elif layer_type == 'soc_annual' and name == 'Soil organic carbon':
                        layers_filtered.append((l, band_number))
                    elif layer_type == 'lc_mode' and name == 'Land cover mode (7 class)':
                        layers_filtered.append((l, band_number))
                    elif layer_type == 'lc_annual' and name == 'Land cover (7 class)':
                        layers_filtered.append((l, band_number))
                    elif layer_type == 'lc_transitions' and name == 'Land cover transitions':
                        layers_filtered.append((l, band_number))
    return layers_filtered


def style_sdg_ld(outfile, title):
    # Significance layer
    log('Loading layers onto map.')
    layer = iface.addRasterLayer(outfile, title)
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


class DegradationWorkerSDG(AbstractWorker):
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
        soc_band = src_ds.GetRasterBand(5)

        block_sizes = traj_band.GetBlockSize()
        x_block_size = block_sizes[0]
        y_block_size = block_sizes[1]
        xsize = traj_band.XSize
        ysize = traj_band.YSize

        driver = gdal.GetDriverByName("GTiff")
        temp_deg_file = tempfile.NamedTemporaryFile(suffix='.tif').name
        dst_ds_deg = driver.Create(temp_deg_file, xsize, ysize, 1, gdal.GDT_Int16, ['COMPRESS=LZW'])
        # Save the combined productivity indicator as well
        temp_prod_file = tempfile.NamedTemporaryFile(suffix='.tif').name
        dst_ds_prod = driver.Create(temp_prod_file, xsize, ysize, 1, gdal.GDT_Int16, ['COMPRESS=LZW'])

        src_gt = src_ds.GetGeoTransform()
        dst_ds_deg.SetGeoTransform(src_gt)
        dst_ds_prod.SetGeoTransform(src_gt)
        dst_srs = osr.SpatialReference()
        dst_srs.ImportFromWkt(src_ds.GetProjectionRef())
        dst_ds_deg.SetProjection(dst_srs.ExportToWkt())
        dst_ds_prod.SetProjection(dst_srs.ExportToWkt())

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
                traj_array = traj_band.ReadAsArray(x, y, cols, rows)
                state_array = state_band.ReadAsArray(x, y, cols, rows)
                perf_array = perf_band.ReadAsArray(x, y, cols, rows)
                lc_array = lc_band.ReadAsArray(x, y, cols, rows)
                soc_array = soc_band.ReadAsArray(x, y, cols, rows)

                ##############
                # Productivity
                
                # Capture trends that are at least 95% significant
                deg = traj_array
                deg[deg == -1] = 0 # not signif at 95%
                deg[deg == 1] = 0 # not signif at 95%
                deg[np.logical_and(deg >= -3, deg <= -2)] = -1
                deg[np.logical_and(deg >= 2, deg <= 3)] = 1

                # Handle state and performance. Note that state array is the 
                # number of changes in class, so  <= -2 is a decline.
                deg[np.logical_and(np.logical_and(state_array <= -2, state_array >= -10), perf_array == -1)] = -1

                # Ensure NAs carry over to productivity indicator layer
                deg[traj_array == -9999] = -9999
                deg[perf_array == -9999] = -9999
                deg[state_array == -9999] = -9999

                # Save combined productivity indicator for later visualization
                dst_ds_prod.GetRasterBand(1).WriteArray(deg, x, y)

                #############
                # Land cover
                deg[lc_array == -1] = -1

                ##############
                # Soil carbon
                
                # Note SOC array is coded in percent change, so change of 
                # greater than 10% is improvement or decline.
                deg[np.logical_and(soc_array <= -10, soc_array >= -100)] = -1

                #############
                # Improvement
                
                # Allow improvements by lc or soc, only where one of the other 
                # two indicators doesn't indicate a decline
                deg[np.logical_and(deg == 0, lc_array == 1)] = 1
                deg[np.logical_and(deg == 0, np.logical_and(soc_array >= 10, soc_array <= 100))] = 1

                ##############
                # Missing data
                
                # Ensure all NAs are carried over - note this was already done 
                # above for the productivity layers
                
                deg[lc_array == -9999] = -9999
                deg[soc_array == -9999] = -9999

                dst_ds_deg.GetRasterBand(1).WriteArray(deg, x, y)
                del deg
                blocks += 1
        self.progress.emit(100)
        src_ds = None
        dst_ds = None

        if self.killed:
            os.remove(temp_deg_file)
            os.remove(temp_prod_file)
            return None
        else:
            return temp_deg_file, temp_prod_file


def xtab(*cols):
    # Based on https://gist.github.com/alexland/d6d64d3f634895b9dc8e, but
    # modified to ignore np.nan
    if not all(len(col) == len(cols[0]) for col in cols[1:]):
        raise ValueError("all arguments must be same size")

    if len(cols) == 0:
        raise TypeError("xtab() requires at least one argument")

    def fnx1(q): return len(q.squeeze().shape)
    if not all([fnx1(col) == 1 for col in cols]):
        raise ValueError("all input arrays must be 1D")

    # Filter na values out of all columns
    nafilter = ~np.any(np.isnan(cols), 0)

    headers, idx = zip(*(np.unique(col[nafilter], return_inverse=True) for col in cols))
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
        band_trans = ds.GetRasterBand(2)
        band_soc = ds.GetRasterBand(3)

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
                #
                # Since the transitions are coded with the initial class in the 
                # tens place, and final in ones place, floor_divide and 
                # remainder can be used to extract initial and final classes 
                # from the transition matrix. HOWEVER - the pixels that persist 
                # are coded as 1-7 so they can be more easily visualized in 
                # QGIS. Therefore these pixels need to be multiplied by 11 to 
                # get them back into the numbering system needed for remainder 
                # and floor_divide to work.
                a_trans = band_trans.ReadAsArray(x, y, cols, rows)
                persist_pixels = np.logical_and(a_trans >= 1, a_trans <= 7)
                a_trans[persist_pixels] = a_trans[persist_pixels] * 11
                a_deg = band_deg.ReadAsArray(x, y, cols, rows)

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
                #
                # Only work with valid pixels as floor_divide and remainder can 
                # otherwise give unexpected results when applied to negative 
                # missing value codes, etc.
                valid_pixels = np.logical_and(a_trans >= 11, a_trans <= 77)
                class_bl = np.array(a_trans, copy=True)
                class_bl[valid_pixels] = np.floor_divide(class_bl[valid_pixels], 10)
                area_table_base = calc_area_table(class_bl, area_table_base, cell_area)

                class_tg = np.array(a_trans, copy=True)
                class_tg[valid_pixels] = np.remainder(class_tg[valid_pixels], 10)
                area_table_target = calc_area_table(class_tg, area_table_target, cell_area)

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
    def __init__(self, in_file, out_file, mask_layer):
        AbstractWorker.__init__(self)

        self.in_file = in_file
        self.out_file = out_file

        self.mask_layer = mask_layer

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        mask_layer_file = tempfile.NamedTemporaryFile(suffix='.shp').name
        QgsVectorFileWriter.writeAsVectorFormat(self.mask_layer, mask_layer_file,
                                                "CP1250", None, "ESRI Shapefile")

        res = gdal.Warp(self.out_file, self.in_file, format='GTiff',
                        cutlineDSName=mask_layer_file,
                        dstNodata=-9999, dstSRS="epsg:4326",
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
        super(DlgReporting, self).__init__(parent)
        self.setupUi(self)

        self.dlg_sdg = DlgReportingSDG()
        self.dlg_unncd = DlgReportingUNCCD()
        self.dlg_create_map = DlgCreateMap()

        self.btn_unccd.clicked.connect(self.clicked_unccd)
        self.btn_sdg.clicked.connect(self.clicked_sdg)
        self.btn_create_map.clicked.connect(self.clicked_create_map)

    def clicked_create_map(self):
        self.close()
        self.dlg_create_map.exec_()

    def clicked_sdg(self):
        self.close()
        self.dlg_sdg.exec_()

    def clicked_unccd(self):
        self.close()
        self.dlg_unncd.exec_()


class DlgReportingBase(DlgCalculateBase):
    '''Class to be shared across SDG and UNCCD reporting dialogs'''

    def __init__(self, parent=None):
        super(DlgReportingBase, self).__init__(parent)
        self.setupUi(self)

        self.browse_output_folder.clicked.connect(self.select_output_folder)

    def showEvent(self, event):
        super(DlgReportingBase, self).showEvent(event)
        self.populate_layers_traj()

    def populate_layers_traj(self):
        self.combo_layer_traj.clear()
        self.layer_traj_list = get_ld_layers('traj_sig')
        self.combo_layer_traj.addItems([l[0].name() for l in self.layer_traj_list])

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

    def get_resample_alg(self, lc_f, traj_f):
        ds_lc = gdal.Open(lc_f)
        ds_traj = gdal.Open(traj_f)
        # If prod layers are lower res than the lc layer, then resample lc
        # using the mode. Otherwise use nearest neighbor:
        lc_gt = ds_lc.GetGeoTransform()
        traj_gt = ds_traj.GetGeoTransform()
        if lc_gt[1] < traj_gt[1]:
            # If the land cover is finer than the trajectory res, use mode to
            # match the lc to the lower res productivity data
            log('Resampling with: mode, lowest')
            return('lowest', gdal.GRA_Mode)
        else:
            # If the land cover is coarser than the trajectory res, use nearest
            # neighbor and match the lc to the higher res productivity data
            log('Resampling with: nearest neighour, highest')
            return('highest', gdal.GRA_NearestNeighbour)

    def btn_calculate(self):
        if not self.output_folder.text():
            QtGui.QMessageBox.information(None, self.tr("Error"),
                                          self.tr("Choose an output folder where the output will be saved."), None)
            return

        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgReportingBase, self).btn_calculate()
        if not ret:
            return

        if len(self.layer_traj_list) == 0:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("You must add a productivity trajectory indicator layer to your map before you can use the reporting tool."), None)
            return

        self.layer_traj = self.layer_traj_list[self.combo_layer_traj.currentIndex()][0]
        self.layer_traj_bandnumber = self.layer_traj_list[self.combo_layer_traj.currentIndex()][1]

        self.traj_f = tempfile.NamedTemporaryFile(suffix='.vrt').name
        gdal.BuildVRT(self.traj_f, self.layer_traj.dataProvider().dataSourceUri(), bandList=[self.layer_traj_bandnumber], VRTNodata=-9999)

        # Compute the pixel-aligned bounding box (slightly larger than aoi).
        # Use this instead of croptocutline in gdal.Warp in order to keep the
        # pixels aligned.
        bb = self.aoi.bounding_box_geom.boundingBox()
        minx = bb.xMinimum()
        miny = bb.yMinimum()
        maxx = bb.xMaximum()
        maxy = bb.yMaximum()
        traj_gt = gdal.Open(self.traj_f).GetGeoTransform()
        left = minx - (minx - traj_gt[0]) % traj_gt[1]
        right = maxx + (traj_gt[1] - ((maxx - traj_gt[0]) % traj_gt[1]))
        bottom = miny + (traj_gt[5] - ((miny - traj_gt[3]) % traj_gt[5]))
        top = maxy - (maxy - traj_gt[3]) % traj_gt[5]
        self.outputBounds = [left, bottom, right, top]

        return True

    def plot_degradation(self, x, y):
        dlg_plot = DlgPlotBars()
        labels = {'title': self.plot_title.text(),
                  'bottom': self.tr('Land cover'),
                  'left': [self.tr('Area'), self.tr('km<sup>2</sup>')]}
        dlg_plot.plot_data(x, y, labels)
        dlg_plot.show()
        dlg_plot.exec_()


class DlgReportingSDG(DlgReportingBase, Ui_DlgReportingSDG):
    def showEvent(self, event):
        super(DlgReportingSDG, self).showEvent(event)
        self.populate_layers_perf()
        self.populate_layers_state()
        self.populate_layers_lc()
        self.populate_layers_soc()

    def populate_layers_lc(self):
        self.combo_layer_lc.clear()
        self.layer_lc_list = get_ld_layers('lc_deg')
        self.combo_layer_lc.addItems([l[0].name() for l in self.layer_lc_list])

    def populate_layers_soc(self):
        self.combo_layer_soc.clear()
        self.layer_soc_list = get_ld_layers('soc_deg')
        self.combo_layer_soc.addItems([l[0].name() for l in self.layer_soc_list])

    def populate_layers_perf(self):
        self.combo_layer_perf.clear()
        self.layer_perf_list = get_ld_layers('perf_deg')
        self.combo_layer_perf.addItems([l[0].name() for l in self.layer_perf_list])

    def populate_layers_state(self):
        self.combo_layer_state.clear()
        self.layer_state_list = get_ld_layers('state_deg')
        self.combo_layer_state.addItems([l[0].name() for l in self.layer_state_list])

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgReportingSDG, self).btn_calculate()
        if not ret:
            return

        self.layer_state = self.layer_state_list[self.combo_layer_state.currentIndex()][0]
        self.layer_state_bandnumber = self.layer_state_list[self.combo_layer_state.currentIndex()][1]

        self.layer_perf = self.layer_perf_list[self.combo_layer_perf.currentIndex()][0]
        self.layer_perf_bandnumber = self.layer_perf_list[self.combo_layer_perf.currentIndex()][1]

        self.layer_lc = self.layer_lc_list[self.combo_layer_lc.currentIndex()][0]
        self.layer_lc_bandnumber = self.layer_lc_list[self.combo_layer_lc.currentIndex()][1]

        self.layer_soc = self.layer_soc_list[self.combo_layer_soc.currentIndex()][0]
        self.layer_soc_bandnumber = self.layer_soc_list[self.combo_layer_soc.currentIndex()][1]

        if len(self.layer_state_list) == 0:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("You must add a productivity state indicator layer to your map before you can use the reporting tool."), None)
            return
        if len(self.layer_perf_list) == 0:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("You must add a productivity performance indicator layer to your map before you can use the reporting tool."), None)
            return

        # Check that all of the productivity layers have the same resolution
        def res(layer):
            return (round(layer.rasterUnitsPerPixelX(), 10), round(layer.rasterUnitsPerPixelY(), 10))
        if res(self.layer_traj) != res(self.layer_state):
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Resolutions of trajectory layer and state layer do not match."), None)
            return
        if res(self.layer_traj) != res(self.layer_perf):
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Resolutions of trajectory layer and performance layer do not match."), None)
            return

        if self.layer_traj.crs() != self.layer_state.crs():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Coordinate systems of trajectory layer and state layer do not match."), None)
            return
        if self.layer_traj.crs() != self.layer_perf.crs():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Coordinate systems of trajectory layer and performance layer do not match."), None)
            return

        # Check that the layers cover the full extent needed
        if not self.aoi.bounding_box_geom.within(QgsGeometry.fromRect(self.layer_state.extent())):
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Area of interest is not entirely within the state layer."), None)
            return
        if not self.aoi.bounding_box_geom.within(QgsGeometry.fromRect(self.layer_perf.extent())):
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Area of interest is not entirely within the performance layer."), None)
            return

        self.perf_f = tempfile.NamedTemporaryFile(suffix='.vrt').name
        gdal.BuildVRT(self.perf_f, self.layer_perf.dataProvider().dataSourceUri(),
                      bandList=[self.layer_perf_bandnumber], VRTNodata=-9999)

        self.state_f = tempfile.NamedTemporaryFile(suffix='.vrt').name
        gdal.BuildVRT(self.state_f, self.layer_state.dataProvider().dataSourceUri(),
                      bandList=[self.layer_state_bandnumber], VRTNodata=-9999)

        self.lc_deg_f = tempfile.NamedTemporaryFile(suffix='.vrt').name
        gdal.BuildVRT(self.lc_deg_f, self.layer_lc.dataProvider().dataSourceUri(),
                bandList=[self.layer_lc_bandnumber], VRTNodata=-9999)

        self.soc_deg_f = tempfile.NamedTemporaryFile(suffix='.vrt').name
        gdal.BuildVRT(self.soc_deg_f, self.layer_soc.dataProvider().dataSourceUri(),
                      bandList=[self.layer_soc_bandnumber], srcNodata=-32768, VRTNodata=-9999)

        ######################################################################
        # Combine rasters into a VRT and crop to the AOI
        self.indic_f = tempfile.NamedTemporaryFile(suffix='.vrt').name
        log('Saving indicator VRT to: {}'.format(self.indic_f))
        resample_alg = self.get_resample_alg(self.lc_deg_f, self.traj_f)
        gdal.BuildVRT(self.indic_f,
                      [self.traj_f,
                       self.perf_f,
                       self.state_f,
                       self.lc_deg_f,
                       self.soc_deg_f],
                      outputBounds=self.outputBounds,
                      resolution=resample_alg[0],
                      resampleAlg=resample_alg[1],
                      separate=True,
                      VRTNodata=-9999)
        self.close()

        lc_clip_tempfile = tempfile.NamedTemporaryFile(suffix='.tif').name
        log('Saving deg/lc clipped file to {}'.format(lc_clip_tempfile))
        deg_lc_clip_worker = StartWorker(ClipWorker, 'masking land cover layers',
                                         self.indic_f,
                                         lc_clip_tempfile, self.aoi.layer)
        if not deg_lc_clip_worker.success:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Error clipping land cover layer for area calculation."), None)
            return

        ######################################################################
        #  Calculate degradation
        log('Calculating degradation...')
        deg_worker = StartWorker(DegradationWorkerSDG, 'calculating degradation',
                                 lc_clip_tempfile)
        if not deg_worker.success:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Error calculating degradation layer."), None)
            return
        else:
            # Note the DegradationWorker also returns a file with the combined
            # productivity indicator.
            deg_file, prod_file = deg_worker.get_return()

        style_sdg_ld(prod_file, QtGui.QApplication.translate('LDMPPlugin', 'SDG 15.3.1 productivity sub-indicator'))
        style_sdg_ld(deg_file, QtGui.QApplication.translate('LDMPPlugin', 'Degradation (SDG 15.3.1 indicator)'))


class DlgReportingUNCCD(DlgReportingBase, Ui_DlgReportingUNCCD):
    def showEvent(self, event):
        super(DlgReportingUNCCD, self).showEvent(event)
        self.populate_layers_lc_transitions()
        self.populate_layers_soc()

    def populate_layers_lc_transitions(self):
        self.combo_layer_lc_tr.clear()
        self.layer_lc_tr_list = get_ld_layers('lc_transitions')
        self.combo_layer_lc_tr.addItems([l[0].name() for l in self.layer_lc_tr_list])

    def populate_layers_soc(self):
        self.combo_layer_soc.clear()
        self.layer_soc_list = get_ld_layers('soc_annual')
        self.combo_layer_soc.addItems([l[0].name() for l in self.layer_soc_list])

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.
        ret = super(DlgReportingUNCCD, self).btn_calculate()
        if not ret:
            return

        if len(self.layer_lc_tr_list) == 0:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("You must add a land cover transitions layer to your map before you can use the reporting tool."), None)
            return
        if len(self.layer_soc_list) == 0:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("You must add a soil organic carbon indicator layer to your map before you can use the reporting tool."), None)
            return

        self.close()

        self.layer_lc_tr = self.layer_lc_tr_list[self.combo_layer_lc_tr.currentIndex()][0]
        self.layer_lc_tr_bandnumber = self.layer_lc_tr_list[self.combo_layer_lc_tr.currentIndex()][1]

        self.layer_soc = self.layer_soc_list[self.combo_layer_soc.currentIndex()][0]
        self.layer_soc_bandnumber = self.layer_soc_list[self.combo_layer_soc.currentIndex()][1]

        ######################################################################
        # Combine rasters into a VRT and crop to the AOI

        indic_f = tempfile.NamedTemporaryFile(suffix='.vrt').name
        log('Saving deg/lc/soc VRT to: {}'.format(indic_f))

        # Select lc bands using bandlist since BuildVrt will otherwise only use
        # the first band of the file
        self.lc_tr_f = tempfile.NamedTemporaryFile(suffix='.vrt').name
        gdal.BuildVRT(self.lc_tr_f, self.layer_lc_tr.dataProvider().dataSourceUri(),
                      bandList=[self.layer_lc_tr_bandnumber], VRTNodata=-9999)

        # Select soc layer using bandlist since that layer has problematic
        # missing value coding
        self.soc_init_f = tempfile.NamedTemporaryFile(suffix='.vrt').name
        gdal.BuildVRT(self.soc_init_f, self.layer_soc.dataProvider().dataSourceUri(),
                      bandList=[self.layer_soc_bandnumber], srcNodata=-32768, VRTNodata=-9999)

        resample_alg = self.get_resample_alg(self.lc_tr_f, self.traj_f)
        gdal.BuildVRT(indic_f,
                      [self.traj_f,
                       self.lc_tr_f,
                       self.soc_init_f],
                      outputBounds=self.outputBounds,
                      resolution=resample_alg[0],
                      resampleAlg=resample_alg[1],
                      separate=True,
                      VRTNodata=-9999)
        # Clip and mask the lc/deg layer before calculating crosstab
        lc_clip_tempfile = tempfile.NamedTemporaryFile(suffix='.tif').name
        log('Saving deg/lc clipped file to {}'.format(lc_clip_tempfile))
        deg_lc_clip_worker = StartWorker(ClipWorker, 'masking land cover layers',
                                         indic_f,
                                         lc_clip_tempfile, self.aoi.layer)
        if not deg_lc_clip_worker.success:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Error clipping land cover layer for area calculation."), None)
            return

        ######################################################################
        # Calculate area crosstabs

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
        log('UNCCD reporting total area: {}'.format(get_xtab_area(trans_lpd_xtab) - get_xtab_area(trans_lpd_xtab, 9999, None)))
        log('UNCCD reporting areas (deg, stable, imp, no data): {}'.format(y))

        make_unccd_table(base_areas, target_areas, soc_totals,
                         trans_lpd_xtab,
                         os.path.join(self.output_folder.text(),
                                      'reporting_table.xlsx'))

        self.plot_degradation(x, y)


def get_lc_area(table, code):
    ind = np.where(table[0] == code)[0]
    if ind.size == 0:
        return 0
    else:
        return float(table[1][ind])


def get_lpd_row(table, transition):
    # Remember that lpd is coded as:
    # -3: 99% signif decline
    # -2: 95% signif decline
    # -1: 90% signif decline
    #  0: stable
    #  1: 90% signif increase
    #  2: 95% signif increase
    #  3: 99% signif increase
    return [get_xtab_area(table, -3, transition) + get_xtab_area(table, -2, transition),
            get_xtab_area(table, -1, transition) + get_xtab_area(table, 0, transition) + get_xtab_area(table, 1, transition),
            get_xtab_area(table, 2, transition), get_xtab_area(table, 3, transition)]


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


def make_unccd_table(base_areas, target_areas, soc_totals, trans_lpd_xtab,
                     out_file):
    def tr(s):
        return QtGui.QApplication.translate("LDMP", s)

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
    worksheet.write('A2', "DRAFT - DATA UNDER REVIEW - DO NOT QUOTE", warning_format)
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

    worksheet.write('D6', '=C6-B6', num_format)
    worksheet.write('D7', '=C7-B7', num_format)
    worksheet.write('D8', '=C8-B8', num_format)
    worksheet.write('D9', '=C9-B9', num_format)
    worksheet.write('D10', '=C10-B10', num_format)
    worksheet.write('D11', '=C11-B11', num_format)
    worksheet.write('D12', '=C12-B12', num_format_bb)

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
        # QtGui.QMessageBox.information(None, QtGui.QApplication.translate("LDMP", "Success"),
        #         QtGui.QApplication.translate("LDMP", 'Indicator table saved to <a href="file://{}">{}</a>'.format(out_file, out_file)))
        QtGui.QMessageBox.information(None, QtGui.QApplication.translate("LDMP", "Success"),
                                      QtGui.QApplication.translate("LDMP", 'Indicator table saved to {}'.format(out_file)))

    except IOError:
        log('Error saving {}'.format(out_file))
        QtGui.QMessageBox.critical(None, QtGui.QApplication.translate("LDMP", "Error"),
                                   QtGui.QApplication.translate("LDMP", "Error saving output table - check that {} is accessible and not already open.".format(out_file)), None)


class DlgCreateMap(DlgCalculateBase, Ui_DlgCreateMap):
    '''Class to be shared across SDG and UNCCD reporting dialogs'''

    def __init__(self, parent=None):
        super(DlgCreateMap, self).__init__(parent)
        self.setupUi(self)

    def firstShow(self):
        #TODO: Remove the combo page for now...
        self.combo_layers.hide()
        self.layer_combo_label.hide()
        self.TabBox.removeTab(1)

        super(DlgCreateMap, self).firstShow()

    def showEvent(self, event):
        super(DlgCreateMap, self).showEvent(event)

        QtGui.QMessageBox.warning(None, QtGui.QApplication.translate("LDMP", "Warning"),
                                  QtGui.QApplication.translate("LDMP", "The create map tool is still experimental - the functionality of this tool is likely to change in the future."), None)

        self.populate_layers()

    def populate_layers(self):
        self.combo_layers.clear()
        self.layers_list = get_ld_layers()
        self.combo_layers.addItems([l[0].name() for l in self.layers_list])

    def btn_calculate(self):
        # Note that the super class has several tests in it - if they fail it
        # returns False, which would mean this function should stop execution
        # as well.

        #TODO Will need to reenable this if the area combo selector is used in the future
        # ret = super(DlgCreateMap, self).btn_calculate()
        # if not ret:
        #     return

        self.close()

        if self.portrait_layout.isChecked():
            orientation = 'portrait'
        else:
            orientation = 'landscape'

        template = os.path.join(os.path.dirname(__file__), 'data',
                                'map_template_{}.qpt'.format(orientation))

        f = file(template, 'rt')
        new_composer_content = f.read()
        f.close()
        document = QtXml.QDomDocument()
        document.setContent(new_composer_content)

        if self.title.text():
            title = self.title.text()
        else:
            title = 'trends.earth map'
        comp_window = iface.createNewComposer(title)
        composition = comp_window.composition()
        composition.loadFromTemplate(document)

        canvas = iface.mapCanvas()
        map_item = composition.getComposerItemById('te_map')
        map_item.setMapCanvas(canvas)
        map_item.zoomToExtent(canvas.extent())

        # Add area of interest
        # layerset = []
        # aoi_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Area of interest", "memory")
        # mask_pr = aoi_layer.dataProvider()
        # fet = QgsFeature()
        # fet.setGeometry(self.aoi)
        # mask_pr.addFeatures([fet])
        # QgsMapLayerRegistry.instance().addMapLayer(aoi_layer)
        # layerset.append(aoi_layer.id())
        # map_item.setLayerSet(layerset)
        # map_item.setKeepLayerSet(True)

        map_item.renderModeUpdateCachedImage()

        datasets = composition.getComposerItemById('te_datasets')
        datasets.setText('Created using <a href="http://trends.earth">trends.earth</a>. Projection: decimal degrees, WGS84. Datasets derived from {{COMING SOON}}.')
        datasets.setHtmlState(True)
        author = composition.getComposerItemById('te_authors')
        author.setText(self.authors.text())
        logo = composition.getComposerItemById('te_logo')
        logo_path = os.path.join(os.path.dirname(__file__), 'data', 'trends_earth_logo_bl_600width.png')
        logo.setPicturePath(logo_path)
        legend = composition.getComposerItemById('te_legend')
        legend.setAutoUpdateModel(True)
