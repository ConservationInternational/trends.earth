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
from PyQt4.QtCore import QSettings

from qgis.core import QgsGeometry, QgsProject, QgsLayerTreeLayer, QgsLayerTreeGroup, \
        QgsRasterLayer, QgsColorRampShader, QgsRasterShader, \
        QgsSingleBandPseudoColorRenderer, QgsVectorLayer, QgsFeature, \
        QgsCoordinateReferenceSystem, QgsVectorFileWriter
from qgis.utils import iface

import processing

from LDMP import log
from LDMP.calculate import DlgCalculateBase
from LDMP.gui.DlgReporting import Ui_DlgReporting
from LDMP.gui.DlgReportingSDG import Ui_DlgReportingSDG
from LDMP.gui.DlgReportingUNCCDProd import Ui_DlgReportingUNCCDProd
from LDMP.gui.DlgReportingUNCCDLC import Ui_DlgReportingUNCCDLC
from LDMP.gui.DlgReportingUNCCDSOC import Ui_DlgReportingUNCCDSOC

# Checks the file type (land cover, state, etc...) for a LDMP output file using 
# the JSON accompanying each file
def get_file_type(data_file):
    json_file  = os.path.splitext(data_file)[0] + '.json'
    try:
        with open(json_file) as f:
            d = json.load(f)
    except (OSError, IOError) as e:
        return None
    s = d.get('script_id', None)
    t =  d.get('results', {}).get('type', None)
    if not s or not t:
        return None
    return {'script_id': s, 'type': t}

def reproject_dataset(dataset, pixel_spacing, from_wkt, epsg_to=4326):
    osng = osr.SpatialReference()
    osng.ImportFromEPSG(epsg_to)
    wgs84 = osr.SpatialReference()
    wgs84.ImportFromWkt(from_wkt)
    tx = osr.CoordinateTransformation(wgs84, osng)
    # Up to here, all  the projection have been defined, as well as a 
    # transformation from the from to the  to :)
    # We now open the dataset
    g = gdal.Open(dataset)
    # Get the Geotransform vector
    geo_t = g.GetGeoTransform()
    x_size = g.RasterXSize # Raster xsize
    y_size = g.RasterYSize # Raster ysize
    # Work out the boundaries of the new dataset in the target projection
    (ulx, uly, ulz) = tx.TransformPoint(geo_t[0], geo_t[3])
    (lrx, lry, lrz) = tx.TransformPoint(geo_t[0] + geo_t[1]*x_size,
                                        geo_t[3] + geo_t[5]*y_size)
    # Now, we create an in-memory raster
    mem_drv = gdal.GetDriverByName('MEM')
    # The size of the raster is given the new projection and pixel spacing
    # Using the values we calculated above.
    dest = mem_drv.Create('',
            int((lrx - ulx)/pixel_spacing),
            int((uly - lry)/pixel_spacing), 1, gdal.GDT_Int16)
    # Calculate the new geotransform
    new_geo = (ulx, pixel_spacing, geo_t[2],
               uly, geo_t[4], -pixel_spacing)
    # Set the geotransform
    dest.SetGeoTransform(new_geo)
    dest.SetProjection(osng.ExportToWkt())

    if pixel_spacing > geo_t[1]:
        # If new dataset is a lower resolution than the source, use the MODE
        log('Resampling with: mode')
        resample_alg = gdal.GRA_Mode
    else:
        log('Resampling with: nearest neighour')
        resample_alg = gdal.GRA_NearestNeighbour
    # Perform the projection/resampling 
    res = gdal.ReprojectImage(g, dest,
        wgs84.ExportToWkt(), osng.ExportToWkt(),
        resample_alg)
    return dest

def clip_and_crop(raster_layer, mask_layer, output_file):
    processing.runandload("gdalogr:cliprasterbymasklayer",
	raster_layer,
	mask_layer,
	"none",
	False,
	True,
	True,
	1,
	2,
	75,
	6,
	1,
	False,
	0,
	False,
	"",
	output_file)

def numpy_to_geotiff(values, model_ds, out_file):
    # Setup geotransform
    trans = model_ds.GetGeoTransform()
    # Setup projection system
    srs = osr.SpatialReference()
    srs.SetWellKnownGeogCS("WGS84")

    # Create the file, using the information from the original file
    drv = gdal.GetDriverByName("GTiff")
    [n, bands] = values.shape
    rows = model_ds.RasterXSize
    cols = model_ds.RasterYSize

    dst_ds = drv.Create(str(out_file), rows, cols, bands, gdal.GDT_Int16)
    # Write the array to the file, which is the original array in this example
    for band in range(bands):
        this_band = np.reshape(values[:, band], (cols, rows), order="F")
        dst_ds.GetRasterBand(band + 1).WriteArray(this_band)

    # Georeference the image
    dst_ds.SetGeoTransform(trans)

    # Write projection information
    dst_ds.SetProjection(srs.ExportToWkt())
    dst_ds.FlushCache()
    dst_ds = None

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
                if not '_eme_degr' in f: continue
                layers_filtered.append(l)
        elif layer_type == 'perf':
            if m['script_id'] == "d2dcfb95-b8b7-4802-9bc0-9b72e586fc82":
                layers_filtered.append(l)
        elif layer_type == 'lc':
            if m['script_id'] == "9a6e5eb6-953d-4993-a1da-23169da0382e":
                if not '_land_deg' in f: continue
                layers_filtered.append(l)
    return layers_filtered

def style_sdg_ld(outfile):
    # Significance layer
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

        self.browse_output.clicked.connect(self.select_output_folder)

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
        self.folder_output.setText(output_dir)

    def btn_calculate(self):
        if not self.folder_output.text():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("Choose an output folder where the output will be saved."), None)
            return

        # Note that the super class has several tests in it - if they fail it 
        # returns False, which would mean this function should stop execution 
        # as well.
        ret = super(DlgReportingSDG, self).btn_calculate()
        if not ret:
            return

        layer_traj = [l for l in self.layer_traj_list if l.name() == self.layer_traj.currentText()][0]
        layer_state = [l for l in self.layer_state_list if l.name() == self.layer_state.currentText()][0]
        layer_perf = [l for l in self.layer_perf_list if l.name() == self.layer_perf.currentText()][0]
        layer_lc = [l for l in self.layer_lc_list if l.name() == self.layer_lc.currentText()][0]
        
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
        if layer_traj.crs() != layer_lc.crs():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                    self.tr("Coordinate systems of trajectory layer and land cover layer do not match."), None)
            return

        # Resample the land cover data to match the resolutions of the other 
        # layers:
        log('Reprojecting land cover...')
        ds_lc = reproject_dataset(layer_lc.dataProvider().dataSourceUri(), 
                layer_traj.rasterUnitsPerPixelX(),
                layer_lc.crs().toWkt())
        log('crs: {}'.format(layer_lc.crs().toWkt()))
        temp_lc_file = tempfile.NamedTemporaryFile(suffix='.tif').name
        # ds_lc = gdal.Translate(temp_lc_file, 
        #         layer_lc.dataProvider().dataSourceUri(),
        #         format='GTiff', 
        #         outputType=gdal.GDT_Int16, 
        #         xRes=layer_traj.rasterUnitsPerPixelX, 
        #         yRes=layer_traj.rasterUnitsPerPixelY,
        #         outputSRS=layer_lc.crs().toWkt(),
        #         resampleAlg=gdal.GRA_Mode)
        log('Reprojection of land cover finished.')

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

        log('Combining degradation layers...')
        ds_traj = gdal.Open(layer_traj.dataProvider().dataSourceUri())
        ds_state = gdal.Open(layer_state.dataProvider().dataSourceUri())
        ds_perf = gdal.Open(layer_perf.dataProvider().dataSourceUri())

        # Note trajectory significance is band 2
	traj_band = ds_traj.GetRasterBand(2)
	block_sizes = traj_band.GetBlockSize()
	x_block_size = block_sizes[0]
	y_block_size = block_sizes[1]
	xsize = traj_band.XSize
	ysize = traj_band.YSize

	driver = gdal.GetDriverByName("GTiff")
        temp_deg_file = tempfile.NamedTemporaryFile(suffix='.tif').name
	dst_ds = driver.Create(temp_deg_file, xsize, ysize, 1, gdal.GDT_Int16, ['COMPRESS=LZW'])

        lc_traj = ds_lc.GetGeoTransform()
	dst_ds.SetGeoTransform(lc_traj)
        dst_srs = osr.SpatialReference()
        dst_srs.ImportFromWkt(ds_traj.GetProjectionRef())
	dst_ds.SetProjection(dst_srs.ExportToWkt())

        state_band = ds_state.GetRasterBand(1)
        perf_band = ds_perf.GetRasterBand(1)
        lc_band = ds_lc.GetRasterBand(1)

        xsize = traj_band.XSize
        ysize = traj_band.YSize
        blocks = 0
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
        ds_traj = None
        ds_state = None
        ds_perf = None
        ds_lc = None
        log('Degradation layers combined.')

        # Use 'processing' to clip and crop
        mask_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "mask", "memory")
        mask_pr = mask_layer.dataProvider()
        fet = QgsFeature()
        fet.setGeometry(self.aoi)
        mask_pr.addFeatures([fet])
        mask_layer_file = tempfile.NamedTemporaryFile(suffix='.shp').name
        QgsVectorFileWriter.writeAsVectorFormat(mask_layer, mask_layer_file, "CP1250", None, "ESRI Shapefile")

        out_file = os.path.join(self.folder_output.text(), 'sdg_15_3_degradation.tif')
        gdal.Warp(out_file, temp_deg_file, format='GTiff', cutlineDSName=mask_layer_file, cropToCutline=True, dstNodata=9999)

        # Load the file add it to the map, and style it
        style_sdg_ld(out_file)

        # Calculate area degraded, improved, etc.
        deg_equal_area_tempfile = tempfile.NamedTemporaryFile(suffix='.shp').name
        ds_equal_area = gdal.Warp(deg_equal_area_tempfile, out_file, dstSRS='EPSG:54009')
        deg_gt = ds_equal_area.GetGeoTransform()
        res_x = deg_gt[1]
        res_y = -deg_gt[5]
        deg_array = ds_equal_area.GetRasterBand(1).ReadAsArray()

        area_deg = np.sum(deg_array == -1) * res_x * res_y / 1e6
        area_stable = np.sum(deg_array == 0) * res_x * res_y / 1e6
        area_imp = np.sum(deg_array == 1) * res_x * res_y / 1e6
        area_water = np.sum(deg_array == 2) * res_x * res_y / 1e6
        area_urban = np.sum(deg_array == 3) * res_x * res_y / 1e6


        header = ("Area Degraded", "Area Stable", "Area Improved", "Water Area", "Urban Area")
        values = (area_deg, area_stable, area_imp, area_water, area_urban)
        out_file_csv = os.path.join(self.folder_output.text(), 'sdg_15_3_degradation.csv')
        with open(out_file_csv, 'wb') as fh:
            writer = csv.writer(fh, delimiter=',')
            for row in zip(header, values):
                writer.writerow(row)
        log('Area deg: {}, stable: {}, imp: {}, water: {}, urban: {}'.format(area_deg, area_stable, area_imp, area_water, area_urban))

        self.close()
        
        # Open a table with the output

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
