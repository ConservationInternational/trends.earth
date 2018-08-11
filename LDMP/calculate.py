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

from osgeo import gdal, ogr

from PyQt4 import QtGui
from PyQt4.QtCore import QTextCodec, QSettings, pyqtSignal, QCoreApplication

from qgis.core import QgsPoint, QgsGeometry, QgsJSONUtils, QgsVectorLayer, \
        QgsCoordinateTransform, QgsCoordinateReferenceSystem, \
        QGis, QgsMapLayerRegistry, QgsProject, \
        QgsLayerTreeGroup, QgsLayerTreeLayer, QgsVectorFileWriter
from qgis.utils import iface
from qgis.gui import QgsMapToolEmitPoint, QgsMapToolPan

from LDMP import log
from LDMP.gui.DlgCalculate import Ui_DlgCalculate
from LDMP.gui.DlgCalculateLD import Ui_DlgCalculateLD
from LDMP.gui.DlgCalculateTC import Ui_DlgCalculateTC
from LDMP.gui.WidgetSelectArea import Ui_WidgetSelectArea
from LDMP.gui.WidgetCalculationOptions import Ui_WidgetCalculationOptions
from LDMP.download import read_json, get_admin_bounds
from LDMP.worker import AbstractWorker


def tr(t):
    return QCoreApplication.translate('LDMPPlugin', t)


# Make a function to get a script slug from a script name, including the script 
# version string
with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                       'data', 'scripts.json')) as script_file:
    scripts = json.load(script_file)
def get_script_slug(script_name):
    # Note that dots and underscores can't be used in the slugs, so they are 
    # replaced with dashesk
    return script_name + '-' + scripts[script_name]['script version'].replace('.', '-')

# Transform CRS of a layer while optionally wrapping geometries
# across the 180th meridian
def transform_layer(l, crs_dst, datatype='polygon', wrap=False):
    log('Transforming layer from "{}" to "{}". Wrap is {}. Datatype is {}.'.format(l.crs().toProj4(), crs_dst.toProj4(), wrap, datatype))

    crs_src_string = l.crs().toProj4()
    if wrap:
        if not l.crs().geographicFlag():
            QtGui.QMessageBox.critical(None, tr("Error"),
                    tr("Error - layer is not in a geographic coordinate system. Cannot wrap layer across 180th meridian."))
            log('Can\'t wrap layer in non-geographic coordinate system: "{}"'.format(crs_src_string))
            return None
        crs_src_string = crs_src_string + ' +lon_wrap=180'
    crs_src = QgsCoordinateReferenceSystem()
    crs_src.createFromProj4(crs_src_string)
    t = QgsCoordinateTransform(crs_src, crs_dst)

    l_w = QgsVectorLayer("{datatype}?crs=proj4:{crs}".format(datatype=datatype, 
                         crs=crs_dst.toProj4()), "calculation boundary (transformed)",  
                         "memory")
    feats = []
    for f in l.getFeatures():
        geom = f.geometry()
        if wrap:
            n = 0
            p = geom.vertexAt(n)
            # Note vertexAt returns QgsPoint(0, 0) on error
            while p != QgsPoint(0, 0):
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
        log('Error transforming layer from "{}" to "{}" (wrap is {})'.format(crs_src_string, crs_dst.toProj4(), wrap))
        return None
    else:
        return l_w


def get_ogr_geom_extent(geom):
    (minX, maxX, minY, maxY) = geom.GetEnvelope()

    # Create ring
    ring = ogr.Geometry(ogr.wkbLinearRing)
    ring.AddPoint(minX, minY)
    ring.AddPoint(maxX, minY)
    ring.AddPoint(maxX, maxY)
    ring.AddPoint(minX, maxY)
    ring.AddPoint(minX, minY)

    # Create polygon
    poly_envelope = ogr.Geometry(ogr.wkbPolygon)
    poly_envelope.AddGeometry(ring)
    poly_envelope.FlattenTo2D()

    return poly_envelope

hemi_w = ogr.CreateGeometryFromWkt('POLYGON ((-180 -90, -180 90, 0 90, 0 -90, -180 -90))')
hemi_e = ogr.CreateGeometryFromWkt('POLYGON ((0 -90, 0 90, 180 90, 180 -90, 0 -90))')

class AOI(object):
    def __init__(self, crs_dst):
        self.crs_dst = crs_dst

    def get_crs_dst_wkt(self):
        return self.crs_dst.toWkt()

    def update_from_file(self, f, wrap=False):
        log(u'Setting up AOI from file at {}"'.format(f))
        l = QgsVectorLayer(f, "calculation boundary", "ogr")
        if not l.isValid():
            QtGui.QMessageBox.critical(None, tr("Error"),
                    tr(u"Unable to load area of interest from {}. There may be a problem with the file or coordinate system. Try manually loading this file into QGIS to verify that it displays properly. If you continue to have problems with this file, send us a message at trends.earth@conservation.org.".format(f)))
            log("Unable to load area of interest.")
            return
        if l.geometryType() == QGis.Polygon:
            self.datatype = "polygon"
        elif l.geometryType() == QGis.Point:
            self.datatype = "point"
        else:
            QtGui.QMessageBox.critical(None, tr("Error"),
                    tr("Failed to process area of interest - unknown geometry type: {}".format(l.geometryType())))
            log("Failed to process area of interest - unknown geometry type.")
            return

        self.l = transform_layer(l, self.crs_dst, datatype=self.datatype, wrap=wrap)

    def update_from_geojson(self, geojson, crs_src='epsg:4326', datatype='polygon', wrap=False):
        log('Setting up AOI with geojson. Wrap is {}.'.format(wrap))
        self.datatype = datatype
        # Note geojson is assumed to be in 4326
        l = QgsVectorLayer("{datatype}?crs={crs}".format(datatype=self.datatype, crs=crs_src), "calculation boundary", "memory")
        fields = QgsJSONUtils.stringToFields(json.dumps(geojson), QTextCodec.codecForName('UTF8'))
        features = QgsJSONUtils.stringToFeatureList(json.dumps(geojson), fields, QTextCodec.codecForName('UTF8'))
        l.dataProvider().addFeatures(features)
        l.commitChanges()
        if not l.isValid():
            QtGui.QMessageBox.critical(None, tr("Error"),
                                       tr("Failed to add geojson to temporary layer."))
            log("Failed to add geojson to temporary layer.")
            return

        self.l = transform_layer(l, self.crs_dst, datatype=self.datatype, wrap=wrap)

    def meridian_split(self, out_type='extent', out_format='geojson', warn=True):
        """
        Return list of bounding boxes in WGS84 as geojson for GEE

        Returns multiple geometries as needed to avoid having an extent 
        crossing the 180th meridian
        """

        #QgsMapLayerRegistry.instance().addMapLayer(self.get_layer_wgs84())

        # Calculate a single feature that is the union of all the features in 
        # this layer - that way there is a single feature to intersect with 
        # each hemisphere.
        log('Merging features')
        n = 0
        for f in self.get_layer_wgs84().getFeatures():
            # Get an OGR geometry from the QGIS geometry
            geom = ogr.CreateGeometryFromWkt(f.geometry().exportToWkt())

            if geom is None or not geom.IsValid():
                log(u'Invalid feature with attributes: {}.'.format(f.attributes()))
                raise
            else:
                if n == 0:
                    new_union = geom
                else:
                    new_union = union.Union(geom)
                union = new_union
                n += 1

        log(u'Calculating east and west intersection.')
        e_intersection = hemi_e.Intersection(union)
        w_intersection = hemi_w.Intersection(union)

        e_intersection_extent = get_ogr_geom_extent(e_intersection)
        w_intersection_extent = get_ogr_geom_extent(w_intersection)
        union_extent = get_ogr_geom_extent(union)

        # Should the output be the extent of each piece? Or the actual geometry 
        # itself (if out_type == 'layer')?
        if out_type == 'extent':
            e_intersection_out = e_intersection_extent
            w_intersection_out = w_intersection_extent
            union_out = union_extent
        elif out_type == 'layer':
            e_intersection_out = e_intersection
            w_intersection_out = w_intersection
            union_out = union
        else:
            raise ValueError('Unrecognized out_type "{}"'.format(out_type))

        log(u'Getting split in chosen format.')
        if out_format == 'geojson':
            e_intersection_out = json.loads(e_intersection_out.ExportToJson())
            w_intersection_out = json.loads(w_intersection_out.ExportToJson())
            union_out = json.loads(union_out.ExportToJson())
        elif out_format == 'wkt':
            e_intersection_out = e_intersection_out.ExportToWkt()
            w_intersection_out = w_intersection_out.ExportToWkt()
            union_out = union_out.ExportToWkt()
        else:
            raise ValueError(u'Unrecognized out_format "{}"'.format(out_format))

        if e_intersection_extent.IsEmpty() or w_intersection_extent.IsEmpty():
            # If there is no area in one of the hemispheres, return the
            # original layer, or extent of the original layer
            return (False, [union_out])
        elif (w_intersection_extent.GetArea() + e_intersection_extent.GetArea()) > (union_extent.GetArea() / 2):
            # If the extent of the combined extents from both hemispheres is 
            # not significantly smaller than that of the original layer, then 
            # return the original layer
            return (False, [union_out])
        else:
            log("AOI crosses 180th meridian - splitting AOI into two geojsons.")
            if warn:
                QtGui.QMessageBox.information(None, tr("Warning"),
                        tr('The chosen area crosses the 180th meridian. It is recommended that you set the project coordinate system to a local coordinate system (see the "CRS" tab of the "Project Properties" window from the "Project" menu.)'))
            return (True, [e_intersection_out, w_intersection_out])

    def get_aligned_output_bounds(self, f):
        wkts = self.meridian_split(out_format='wkt', warn=False)[1]
        out = []
        for wkt in wkts:
            # Compute the pixel-aligned bounding box (slightly larger than 
            # aoi).
            # Use this to set bounds in vrt files in order to keep the
            # pixels aligned with the chosen layer
            geom = ogr.CreateGeometryFromWkt(wkt)
            (minx, maxx, miny, maxy) = geom.GetEnvelope()
            gt = gdal.Open(f).GetGeoTransform()
            left = minx - (minx - gt[0]) % gt[1]
            right = maxx + (gt[1] - ((maxx - gt[0]) % gt[1]))
            bottom = miny + (gt[5] - ((miny - gt[3]) % gt[5]))
            top = maxy - (maxy - gt[3]) % gt[5]
            out.append([left, bottom, right, top])
        return out

    def get_aligned_output_bounds_deprecated(self, f):
        # Compute the pixel-aligned bounding box (slightly larger than aoi).
        # Use this to set bounds in vrt files in order to keep the
        # pixels aligned with the chosen layer
        bb = self.bounding_box_geom().boundingBox()
        minx = bb.xMinimum()
        miny = bb.yMinimum()
        maxx = bb.xMaximum()
        maxy = bb.yMaximum()
        gt = gdal.Open(f).GetGeoTransform()
        left = minx - (minx - gt[0]) % gt[1]
        right = maxx + (gt[1] - ((maxx - gt[0]) % gt[1]))
        bottom = miny + (gt[5] - ((miny - gt[3]) % gt[5]))
        top = maxy - (maxy - gt[3]) % gt[5]
        return [left, bottom, right, top]

    def get_layer(self):
        """
        Return layer
        """
        return self.l

    def get_layer_wgs84(self):
        """
        Return layer in WGS84 (WPGS:4326)
        """
        # Setup settings for AOI provided to GEE:
        wgs84_crs = QgsCoordinateReferenceSystem()
        wgs84_crs.createFromProj4('+proj=longlat +datum=WGS84 +no_defs')
        return transform_layer(self.l, wgs84_crs, datatype=self.datatype, wrap=False)

    def bounding_box_geom(self):
        'Returns bounding box in chosen destination coordinate system'
        return QgsGeometry.fromRect(self.l.extent())

    def bounding_box_gee_geojson(self):
        '''
        Returns two values - first is an indicator of whether this geojson 
        includes two geometries due to crossing of the 180th meridian, and the 
        second is the list of bounding box geojsons.
        '''
        if self.datatype == 'polygon':
            return self.meridian_split()
        elif self.datatype == 'point':
            # If there is only on point, don't calculate an extent (extent of 
            # one point is a box with sides equal to zero)
            n = 0
            for f in self.l.getFeatures():
                n += 1
                if n == 1:
                    # Save the first geometry in case it is needed later 
                    # for a layer that only has one point in it
                    geom = f.geometry()
            if n == 1:
                log('Layer only has one point')
                return (False, [json.loads(geom.exportToGeoJSON())])
            else:
                log('Layer has many points ({})'.format(n))
                return self.meridian_split()
        else:
            QtGui.QMessageBox.critical(None, tr("Error"),
                    tr("Failed to process area of interest - unknown geometry type: {}".format(self.datatype)))
            log("Failed to process area of interest - unknown geometry type.")


    def isValid(self):
        return self.l.isValid()

    def calc_frac_overlap(self, geom):
        """
        Returns fraction of AOI that is overlapped by geom (where geom is a QgsGeometry)

        Used to calculate "within" with a tolerance
        """
        aoi_geom = ogr.CreateGeometryFromWkt(self.bounding_box_geom().exportToWkt())
        in_geom = ogr.CreateGeometryFromWkt(geom.exportToWkt())

        area_inter = aoi_geom.Intersection(in_geom).GetArea()
        frac = area_inter / aoi_geom.GetArea()
        log('Fractional area of overlap: {}'.format(frac))
        return frac

class DlgCalculate(QtGui.QDialog, Ui_DlgCalculate):
    def __init__(self, parent=None):
        super(DlgCalculate, self).__init__(parent)

        self.setupUi(self)

        self.dlg_calculate_ld = DlgCalculateLD()
        self.dlg_calculate_tc = DlgCalculateTC()
        #self.dlg_calculate_urban = DlgCalculateUrban()

        self.pushButton_ld.clicked.connect(self.btn_ld_clicked)
        self.pushButton_tc.clicked.connect(self.btn_tc_clicked)
        self.pushButton_urban.clicked.connect(self.btn_urban_clicked)

    def btn_ld_clicked(self):
        self.close()
        result = self.dlg_calculate_ld.exec_()

    def btn_tc_clicked(self):
        self.close()
        result = self.dlg_calculate_tc.exec_()

    def btn_urban_clicked(self):
        self.close()
        result = self.dlg_calculate_urban.exec_()


class DlgCalculateLD(QtGui.QDialog, Ui_DlgCalculateLD):
    def __init__(self, parent=None):
        super(DlgCalculateLD, self).__init__(parent)

        self.setupUi(self)

        # TODO: Bad style - fix when refactoring
        from LDMP.calculate_prod import DlgCalculateProd
        from LDMP.calculate_lc import DlgCalculateLC
        from LDMP.calculate_soc import DlgCalculateSOC
        from LDMP.calculate_sdg import DlgCalculateOneStep, DlgCalculateSummaryTableAdmin
        self.dlg_calculate_prod = DlgCalculateProd()
        self.dlg_calculate_lc = DlgCalculateLC()
        self.dlg_calculate_soc = DlgCalculateSOC()
        self.dlg_calculate_sdg_onestep = DlgCalculateOneStep()
        self.dlg_calculate_sdg_advanced = DlgCalculateSummaryTableAdmin()

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
        result = self.dlg_calculate_sdg_onestep.exec_()

    def btn_summary_single_polygon_clicked(self):
        self.close()
        result = self.dlg_calculate_sdg_advanced.exec_()

    def btn_summary_multi_polygons_clicked(self):
        QtGui.QMessageBox.information(None, self.tr("Coming soon!"),
                                      self.tr("Multiple polygon summary table calculation coming soon!"), None)


class DlgCalculateTC(QtGui.QDialog, Ui_DlgCalculateTC):
    def __init__(self, parent=None):
        super(DlgCalculateTC, self).__init__(parent)

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


class CalculationOptionsWidget(QtGui.QWidget, Ui_WidgetCalculationOptions):
    def __init__(self, parent=None):
        super(CalculationOptionsWidget, self).__init__(parent)

        self.setupUi(self)

        self.radioButton_run_in_cloud.toggled.connect(self.radioButton_run_in_cloud_changed)
        self.btn_local_data_folder_browse.clicked.connect(self.open_folder_browse)

    def radioButton_run_in_cloud_changed(self):
        if self.radioButton_run_in_cloud.isChecked():
            self.lineEdit_local_data_folder.setEnabled(False)
            self.btn_local_data_folder_browse.setEnabled(False)
        else:
            self.lineEdit_local_data_folder.setEnabled(True)
            self.btn_local_data_folder_browse.setEnabled(True)

    def open_folder_browse(self):
        self.lineEdit_local_data_folder.clear()

        folder = QtGui.QFileDialog.getExistingDirectory(self,
                                                        self.tr('Select folder containing data'),
                                                        QSettings().value("LDMP/localdata_dir", None))
        if folder:
            if os.access(folder, os.R_OK):
                QSettings().setValue("LDMP/localdata_dir", os.path.dirname(folder))
                self.lineEdit_local_data_folder.setText(folder)
                return True
            else:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
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
                

class AreaWidget(QtGui.QWidget, Ui_WidgetSelectArea):
    def __init__(self, parent=None):
        super(AreaWidget, self).__init__(parent)

        self.setupUi(self)

        self.canvas = iface.mapCanvas()

        self.admin_bounds_key = get_admin_bounds()
        if not self.admin_bounds_key:
            raise ValueError('Admin boundaries not available')

        self.area_admin_0.addItems(sorted(self.admin_bounds_key.keys()))
        self.populate_admin_1()

        self.area_admin_0.currentIndexChanged.connect(self.populate_admin_1)

        self.area_fromfile_browse.clicked.connect(self.open_vector_browse)
        self.area_fromadmin.toggled.connect(self.area_fromadmin_toggle)
        self.area_fromfile.toggled.connect(self.area_fromfile_toggle)

        icon = QtGui.QIcon(QtGui.QPixmap(':/plugins/LDMP/icons/map-marker.svg'))
        self.area_frompoint_choose_point.setIcon(icon)
        self.area_frompoint_choose_point.clicked.connect(self.point_chooser)
        #TODO: Set range to only accept valid coordinates for current map coordinate system
        self.area_frompoint_point_x.setValidator(QtGui.QDoubleValidator())
        #TODO: Set range to only accept valid coordinates for current map coordinate system
        self.area_frompoint_point_y.setValidator(QtGui.QDoubleValidator())
        self.area_frompoint.toggled.connect(self.area_frompoint_toggle)
        self.area_frompoint_toggle()

        # Setup point chooser
        self.choose_point_tool = QgsMapToolEmitPoint(self.canvas)
        self.choose_point_tool.canvasClicked.connect(self.set_point_coords)

        proj_crs = QgsCoordinateReferenceSystem(self.canvas.mapRenderer().destinationCrs().authid())
        self.mQgsProjectionSelectionWidget.setCrs(QgsCoordinateReferenceSystem('epsg:4326'))

    def showEvent(self, event):
        super(AreaWidget, self).showEvent(event)

    def populate_admin_1(self):
        self.area_admin_1.clear()
        self.area_admin_1.addItems(['All regions'])
        self.area_admin_1.addItems(sorted(self.admin_bounds_key[self.area_admin_0.currentText()]['admin1'].keys()))

    def area_frompoint_toggle(self):
        if self.area_frompoint.isChecked():
            self.area_frompoint_point_x.setEnabled(True)
            self.area_frompoint_point_y.setEnabled(True)
            self.area_frompoint_choose_point.setEnabled(True)
        else:
            self.area_frompoint_point_x.setEnabled(False)
            self.area_frompoint_point_y.setEnabled(False)
            self.area_frompoint_choose_point.setEnabled(False)

    def area_fromadmin_toggle(self):
        if self.area_fromadmin.isChecked():
            self.area_admin_0.setEnabled(True)
            self.area_admin_1.setEnabled(True)
        else:
            self.area_admin_0.setEnabled(False)
            self.area_admin_1.setEnabled(False)

    def area_fromfile_toggle(self):
        if self.area_fromfile.isChecked():
            self.area_fromfile_file.setEnabled(True)
            self.area_fromfile_browse.setEnabled(True)
        else:
            self.area_fromfile_file.setEnabled(False)
            self.area_fromfile_browse.setEnabled(False)

    def show_areafrom_point_toggle(self, enable):
        if enable:
            self.area_frompoint_enabled = True
            self.area_frompoint.show()
            self.area_frompoint_label_x.show()
            self.area_frompoint_point_x.show()
            self.area_frompoint_label_y.show()
            self.area_frompoint_point_y.show()
            self.area_frompoint_choose_point.show()
        else:
            self.area_frompoint_enabled = False
            self.area_frompoint.hide()
            self.area_frompoint_label_x.hide()
            self.area_frompoint_point_x.hide()
            self.area_frompoint_label_y.hide()
            self.area_frompoint_point_y.hide()
            self.area_frompoint_choose_point.hide()

    def point_chooser(self):
        log("Choosing point from canvas...")
        self.canvas.setMapTool(self.choose_point_tool)
        self.window().hide()
        QtGui.QMessageBox.critical(None, self.tr("Point chooser"), self.tr("Click the map to choose a point."))

    def set_point_coords(self, point, button):
        log("Set point coords")
        #TODO: Show a messagebar while tool is active, and then remove the bar when a point is chosen.
        self.point = point
        # Disable the choose point tool
        self.canvas.setMapTool(QgsMapToolPan(self.canvas))
        # Don't reset_tab_on_show as it would lead to return to first tab after
        # using the point chooser
        self.window().reset_tab_on_showEvent = False
        self.window().show()
        self.window().reset_tab_on_showEvent = True
        self.point = self.canvas.getCoordinateTransform().toMapCoordinates(self.canvas.mouseLastXY())
        log("Chose point: {}, {}.".format(self.point.x(), self.point.y()))
        self.area_frompoint_point_x.setText("{:.8f}".format(self.point.x()))
        self.area_frompoint_point_y.setText("{:.8f}".format(self.point.y()))

    def open_vector_browse(self):
        self.area_fromfile_file.clear()

        vector_file = QtGui.QFileDialog.getOpenFileName(self,
                                                        self.tr('Select a file defining the area of interest'),
                                                        QSettings().value("LDMP/input_dir", None),
                                                        self.tr('Vector file (*.shp *.kml *.kmz *.geojson)'))
        if vector_file:
            if os.access(vector_file, os.R_OK):
                QSettings().setValue("LDMP/input_dir", os.path.dirname(vector_file))
                self.area_fromfile_file.setText(vector_file)
                return True
            else:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr(u"Cannot read {}. Choose a different file.".format(vector_file)))
                return False
        else:
            return False
                

# Widgets shared across dialogs
area_widget = AreaWidget()
options_widget = CalculationOptionsWidget()


class DlgCalculateBase(QtGui.QDialog):
    """Base class for individual indicator calculate dialogs"""
    firstShowEvent = pyqtSignal()

    def __init__(self, parent=None):
        super(DlgCalculateBase, self).__init__(parent)

        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                               'data', 'scripts.json')) as script_file:
            self.scripts = json.load(script_file)

        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                               'data', 'gee_datasets.json')) as datasets_file:
            self.datasets = json.load(datasets_file)

        self._firstShowEvent = True
        self.reset_tab_on_showEvent = True

        self.firstShowEvent.connect(self.firstShow)
        
    def showEvent(self, event):
        super(DlgCalculateBase, self).showEvent(event)

        area_widget.setParent(self)
        self.area_tab = area_widget
        self.TabBox.addTab(self.area_tab, self.tr('Area'))

        self.options_tab = options_widget
        self.TabBox.addTab(self.options_tab, self.tr('Options'))

        # By default show the local or cloud option
        #self.options_tab.toggle_show_where_to_run(True)
        self.options_tab.toggle_show_where_to_run(False)

        # By default hide the custom crs box
        self.area_tab.groupBox_custom_crs.hide()

        if self._firstShowEvent:
            self._firstShowEvent = False
            self.firstShowEvent.emit()

        if self.reset_tab_on_showEvent:
            self.TabBox.setCurrentIndex(0)

        # By default, don't show area from point selector
        self.area_tab.show_areafrom_point_toggle(False)

    def firstShow(self):
        self.button_calculate.clicked.connect(self.btn_calculate)
        self.button_prev.clicked.connect(self.tab_back)
        self.button_next.clicked.connect(self.tab_forward)

        # Start on first tab so button_prev and calculate should be disabled
        self.button_prev.setEnabled(False)
        self.button_calculate.setEnabled(False)
        self.TabBox.currentChanged.connect(self.tab_changed)

    def tab_back(self):
        if self.TabBox.currentIndex() - 1 >= 0:
            self.TabBox.setCurrentIndex(self.TabBox.currentIndex() - 1)

    def tab_forward(self):
        if self.TabBox.currentIndex() + 1 < self.TabBox.count():
            self.TabBox.setCurrentIndex(self.TabBox.currentIndex() + 1)

    def tab_changed(self):
        if self.TabBox.currentIndex() > 0:
            self.button_prev.setEnabled(True)
        else:
            self.button_prev.setEnabled(False)

        if self.TabBox.currentIndex() < (self.TabBox.count() - 1):
            self.button_next.setEnabled(True)
        else:
            self.button_next.setEnabled(False)

        if self.TabBox.currentIndex() == (self.TabBox.count() - 1):
            self.button_calculate.setEnabled(True)
        else:
            self.button_calculate.setEnabled(False)

    def btn_cancel(self):
        self.close()

    def load_admin_polys(self):
        adm0_a3 = self.area_tab.admin_bounds_key[self.area_tab.area_admin_0.currentText()]['code']
        admin_polys = read_json(u'admin_bounds_polys_{}.json.gz'.format(adm0_a3), verify=False)
        if not admin_polys:
            return None
        if not self.area_tab.area_admin_1.currentText() or self.area_tab.area_admin_1.currentText() == 'All regions':
            return (admin_polys['geojson'])
        else:
            admin_1_code = self.area_tab.admin_bounds_key[self.area_tab.area_admin_0.currentText()]['admin1'][self.area_tab.area_admin_1.currentText()]['code']
            return (admin_polys['admin1'][admin_1_code]['geojson'])

    def btn_calculate(self):
        if self.area_tab.groupBox_custom_crs.isChecked():
            crs_dst = self.area_tab.mQgsProjectionSelectionWidget.crs()
        else:
            crs_dst = QgsCoordinateReferenceSystem('epsg:4326')

        self.aoi = AOI(crs_dst)

        if self.area_tab.area_fromadmin.isChecked():
            if not self.area_tab.area_admin_0.currentText():
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Choose a first level administrative boundary."), None)
                return False
            self.button_calculate.setEnabled(False)
            geojson = self.load_admin_polys()
            self.button_calculate.setEnabled(True)
            if not geojson:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Unable to load administrative boundaries."), None)
                return False
            self.aoi.update_from_geojson(geojson=geojson, 
                                         wrap=self.area_tab.checkBox_custom_crs_wrap.isChecked())
        elif self.area_tab.area_fromfile.isChecked():
            if not self.area_tab.area_fromfile_file.text():
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Choose a file to define the area of interest."), None)
                return False
            self.aoi.update_from_file(f=self.area_tab.area_fromfile_file.text(),
                                      wrap=self.area_tab.checkBox_custom_crs_wrap.isChecked())
        elif self.area_tab.area_frompoint_enabled and self.area_tab.area_frompoint.isChecked():
            # Area from point
            if not self.area_tab.area_frompoint_point_x.text() or not self.area_tab.area_frompoint_point_y.text():
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Choose a point to define the area of interest."), None)
                return False
            point = QgsPoint(float(self.area_tab.area_frompoint_point_x.text()), float(self.area_tab.area_frompoint_point_y.text()))
            crs_src = QgsCoordinateReferenceSystem(self.area_tab.canvas.mapRenderer().destinationCrs().authid())
            point = QgsCoordinateTransform(crs_src, crs_dst).transform(point)
            geojson = json.loads(QgsGeometry.fromPoint(point).exportToGeoJSON())
            self.aoi.update_from_geojson(geojson=geojson, 
                                         wrap=self.area_tab.checkBox_custom_crs_wrap.isChecked(),
                                         datatype='point')
        else:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Choose an area of interest."), None)
            return False

        if self.aoi and not self.aoi.isValid():
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Unable to read area of interest."), None)
            return False
        else:
            return True


class ClipWorker(AbstractWorker):
    def __init__(self, in_file, out_file, geojson, output_bounds=None):
        AbstractWorker.__init__(self)

        self.in_file = in_file
        self.out_file = out_file
        self.output_bounds = output_bounds

        self.geojson = geojson

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)

        json_file = tempfile.NamedTemporaryFile(suffix='.json').name
        with open(json_file, 'w') as f:
            json.dump(self.geojson, f, separators=(',', ': '))

        res = gdal.Warp(self.out_file, self.in_file, format='GTiff',
                        cutlineDSName=json_file, srcNodata=-32768, 
                        outputBounds=self.output_bounds,
                        dstNodata=-32767,
                        dstSRS="epsg:4326",
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
