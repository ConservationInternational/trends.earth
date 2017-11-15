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

from PyQt4 import QtGui, uic
from PyQt4.QtCore import QSettings, QEventLoop

from qgis.core import QgsGeometry, QgsProject, QgsLayerTreeLayer, QgsLayerTreeGroup, \
    QgsRasterLayer, QgsColorRampShader, QgsRasterShader, \
    QgsSingleBandPseudoColorRenderer, QgsVectorLayer, QgsFeature, \
    QgsCoordinateReferenceSystem, QgsVectorFileWriter
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
    def __init__(self, src_dataset, ref_dataset):
        AbstractWorker.__init__(self)

        self.src_dataset = src_dataset
        self.ref_dataset = ref_dataset

    def work(self):
        self.toggle_show_progress.emit(False)
        self.toggle_show_cancel.emit(False)

        ds_ref = gdal.Open(self.ref_dataset)
        sr_dest = osr.SpatialReference()
        sr_dest.ImportFromWkt(ds_ref.GetProjectionRef())

        ds_src = gdal.Open(self.src_dataset)
        sr_src = osr.SpatialReference()
        sr_src.ImportFromWkt(ds_src.GetProjectionRef())

        driver = gdal.GetDriverByName("GTiff")
        temp_file = tempfile.NamedTemporaryFile(suffix='.tif').name
        ds_dest = driver.Create(temp_file, ds_ref.RasterXSize, 
                                ds_ref.RasterYSize, 1, gdal.GDT_Int16, 
                                ['COMPRESS=LZW'])

        gt_ref = ds_ref.GetGeoTransform()
        ds_dest.SetGeoTransform(gt_ref)
        ds_dest.SetProjection(sr_dest.ExportToWkt())

        gt_src = ds_src.GetGeoTransform()
        if gt_ref[1] > gt_src[1]:
            # If new dataset is a lower resolution than the source, use the MODE
            log('Resampling with: mode')
            resample_alg = gdal.GRA_Mode
        else:
            log('Resampling with: nearest neighour')
            resample_alg = gdal.GRA_NearestNeighbour
        # Perform the projection/resampling
        res = gdal.ReprojectImage(ds_src,
                                  ds_dest,
                                  sr_src.ExportToWkt(),
                                  sr_dest.ExportToWkt(),
                                  resample_alg)

        return ds_dest


class DegradationWorker(AbstractWorker):
    def __init__(self, ds_traj, ds_state, ds_perf, ds_lc):
        AbstractWorker.__init__(self)

        self.ds_traj = ds_traj
        self.ds_state = ds_state
        self.ds_perf = ds_perf
        self.ds_lc = ds_lc

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        # Note trajectory significance is band 2
        traj_band = self.ds_traj.GetRasterBand(2)
        block_sizes = traj_band.GetBlockSize()
        x_block_size = block_sizes[0]
        y_block_size = block_sizes[1]
        xsize = traj_band.XSize
        ysize = traj_band.YSize

        driver = gdal.GetDriverByName("GTiff")
        temp_deg_file = tempfile.NamedTemporaryFile(suffix='.tif').name
        dst_ds = driver.Create(temp_deg_file, xsize, ysize, 1, gdal.GDT_Int16, ['COMPRESS=LZW'])

        lc_gt = self.ds_lc.GetGeoTransform()
        dst_ds.SetGeoTransform(lc_gt)
        dst_srs = osr.SpatialReference()
        dst_srs.ImportFromWkt(self.ds_traj.GetProjectionRef())
        dst_ds.SetProjection(dst_srs.ExportToWkt())

        state_band = self.ds_state.GetRasterBand(1)
        perf_band = self.ds_perf.GetRasterBand(1)
        lc_band = self.ds_lc.GetRasterBand(1)

        xsize = traj_band.XSize
        ysize = traj_band.YSize
        blocks = 0
        for y in xrange(0, ysize, y_block_size):
            self.progress.emit(100 * float(y) / ysize)
            if y + y_block_size < ysize:
                rows = y_block_size
            else:
                rows = ysize - y
            for x in xrange(0, xsize, x_block_size):
                if self.killed:
                    log("Processing of {} killed by user after processing {} out of {} blocks.".format(temp_deg_file, y, ysize))
                    break

                if x + x_block_size < xsize:
                    cols = x_block_size
                else:
                    cols = xsize - x
                deg = traj_band.ReadAsArray(x, y, cols, rows)
                state_array = state_band.ReadAsArray(x, y, cols, rows)
                perf_array = perf_band.ReadAsArray(x, y, cols, rows)
                lc_array = lc_band.ReadAsArray(x, y, cols, rows)

                deg[lc_array == -1] = -1
                deg[(state_array == -1) & (perf_array == -1)] = -1

                dst_ds.GetRasterBand(1).WriteArray(deg, x, y)
                del deg
                blocks += 1
        dst_ds = None
        self.ds_traj = None
        self.ds_state = None
        self.ds_perf = None
        self.ds_lc = None

        if self.killed:
            os.remove(temp_deg_file)
            return None
        else:
            return temp_deg_file


class ClipWorker(AbstractWorker):
    def __init__(self, in_file, out_file, aoi):
        AbstractWorker.__init__(self)

        self.in_file = in_file
        self.out_file = out_file
        self.aoi = aoi

    def work(self):
        self.toggle_show_progress.emit(False)
        self.toggle_show_cancel.emit(False)

        # Use 'processing' to clip and crop
        mask_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "mask", "memory")
        mask_pr = mask_layer.dataProvider()
        fet = QgsFeature()
        fet.setGeometry(self.aoi)
        mask_pr.addFeatures([fet])
        mask_layer_file = tempfile.NamedTemporaryFile(suffix='.shp').name
        QgsVectorFileWriter.writeAsVectorFormat(mask_layer, mask_layer_file,
                                                "CP1250", None, "ESRI Shapefile")

        gdal.Warp(self.out_file, self.in_file, format='GTiff',
                  cutlineDSName=mask_layer_file, cropToCutline=True,
                  dstNodata=9999)

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

        ds_traj = gdal.Open(layer_traj.dataProvider().dataSourceUri())
        ds_state = gdal.Open(layer_state.dataProvider().dataSourceUri())
        ds_perf = gdal.Open(layer_perf.dataProvider().dataSourceUri())

        self.close()

        # Need to resample the 300m land cover data to match the resolutions of 
        # the other layers:
        log('Reprojecting land cover...')
        reproj_worker = StartWorker(ReprojectionWorker, 'reprojecting land cover', 
                                    layer_lc.dataProvider().dataSourceUri(),
                                    layer_traj.dataProvider().dataSourceUri())
        if not reproj_worker.success:
            return
        else:
            ds_lc = reproj_worker.get_return()

        log('Calculating degradation...')
        deg_worker = StartWorker(DegradationWorker, 'calculating degradation',
                                 ds_traj, ds_state, ds_perf, 
                                 ds_lc)
        if not deg_worker.success:
            return
        else:
            deg_file = deg_worker.get_return()

        log('Clipping and masking degradation layers...')
        out_file = os.path.join(self.output_folder.text(), 'sdg_15_3_degradation.tif')
        clip_worker = StartWorker(ClipWorker, 'clipping and masking output',
                                  deg_file, out_file, self.aoi)
        log('Clipping and masking degradation layers COMPLETE, returning: {}'.format(clip_worker.success))
        if not clip_worker.success:
            return

        style_sdg_ld(out_file)

        # Calculate area degraded, improved, etc.
        deg_equal_area_tempfile = tempfile.NamedTemporaryFile(suffix='.tif').name
        ds_equal_area = gdal.Warp(deg_equal_area_tempfile, out_file, dstSRS='EPSG:54009')
        deg_gt = ds_equal_area.GetGeoTransform()
        res_x = deg_gt[1]
        res_y = -deg_gt[5]
        deg_array = ds_equal_area.GetRasterBand(1).ReadAsArray()

        self.deg = {"Area Degraded": np.sum(deg_array == -1) * res_x * res_y / 1e6,
                    "Area Stable": np.sum(deg_array == 0) * res_x * res_y / 1e6,
                    "Area Improved": np.sum(deg_array == 1) * res_x * res_y / 1e6,
                    "No Data": np.sum(deg_array == 9997) * res_x * res_y / 1e6,
                    "Water Area": np.sum(deg_array == 9998) * res_x * res_y / 1e6,
                    "Urban Area": np.sum(deg_array == 9999) * res_x * res_y / 1e6}
        log('SDG 15.3.1 indicator: {}'.format(self.deg))

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
        dlg_plot.plot_data(x, y, self.plot_title.text())
        dlg_plot.show()
        dlg_plot.exec_()

        out_file_csv = os.path.join(self.output_folder.text(), 'sdg_15_3_degradation.csv')
        with open(out_file_csv, 'wb') as fh:
            writer = csv.writer(fh, delimiter=',')
            for item in self.deg.items():
                writer.writerow(item)


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
