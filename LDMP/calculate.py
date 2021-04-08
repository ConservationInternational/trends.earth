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

from builtins import object
import os
from pathlib import Path
import json
import tempfile

from osgeo import gdal, ogr, osr

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtGui import QIcon, QPixmap, QDoubleValidator
from qgis.PyQt.QtCore import (QTextCodec, QSettings, pyqtSignal,
    QCoreApplication)

from qgis.core import (QgsFeature, QgsPointXY, QgsGeometry, QgsJsonUtils,
    QgsVectorLayer, QgsCoordinateTransform, QgsCoordinateReferenceSystem,
    Qgis, QgsProject, QgsLayerTreeGroup, QgsLayerTreeLayer,
    QgsVectorFileWriter, QgsFields, QgsWkbTypes,
    QgsSettings)
from qgis.utils import iface
from qgis.gui import QgsMapToolEmitPoint, QgsMapToolPan

from LDMP import log, GetTempFilename
from LDMP.api import run_script
from LDMP.gui.DlgCalculate import Ui_DlgCalculate
from LDMP.gui.DlgCalculateLD import Ui_DlgCalculateLD
from LDMP.gui.DlgCalculateTC import Ui_DlgCalculateTC
from LDMP.gui.DlgCalculateRestBiomass import Ui_DlgCalculateRestBiomass
from LDMP.gui.DlgCalculateUrban import Ui_DlgCalculateUrban
from LDMP.gui.WidgetSelectArea import Ui_WidgetSelectArea
from LDMP.gui.WidgetCalculationOptions import Ui_WidgetCalculationOptions
from LDMP.gui.WidgetCalculationOutput import Ui_WidgetCalculationOutput
from LDMP.download import read_json, get_admin_bounds, get_cities
from LDMP.worker import AbstractWorker

mb = iface.messageBar()


if QSettings().value("LDMP/binaries_enabled", False) == 'True':
    try:
        from trends_earth_binaries.calculate_numba import *
        log("Using numba-compiled version of calculate_numba.")
    except (ModuleNotFoundError, ImportError) as e:
        from LDMP.calculate_numba import *
        log("Failed import of numba-compiled code, falling back to python version of calculate_numba.")
else:
    from LDMP.calculate_numba import *
    log("Using python version of calculate_numba.")


class tr_calculate(object):
    def tr(message):
        return QCoreApplication.translate("tr_calculate", message)


# Make a function to get a script slug from a script name, including the script 
# version string
with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                       'data', 'scripts.json')) as script_file:
    scripts = json.load(script_file)
def get_script_slug(script_name):
    # Note that dots and underscores can't be used in the slugs, so they are 
    # replaced with dashesk
    return (script_name, script_name + '-' + scripts[script_name]['script version'].replace('.', '-'))

# Transform CRS of a layer while optionally wrapping geometries
# across the 180th meridian
def transform_layer(l, crs_dst, datatype='polygon', wrap=False):
    log('Transforming layer from "{}" to "{}". Wrap is {}. Datatype is {}.'.format(l.crs().toProj(), crs_dst.toProj(), wrap, datatype))

    crs_src_string = l.crs().toProj()
    if wrap:
        if not l.crs().isGeographic():
            QtWidgets.QMessageBox.critical(None,tr_calculate.tr("Error"),
                   tr_calculate.tr("Error - layer is not in a geographic coordinate system. Cannot wrap layer across 180th meridian."))
            log('Can\'t wrap layer in non-geographic coordinate system: "{}"'.format(crs_src_string))
            return None
        crs_src_string = crs_src_string + ' +lon_wrap=180'
    crs_src = QgsCoordinateReferenceSystem()
    crs_src.createFromProj(crs_src_string)
    t = QgsCoordinateTransform(crs_src, crs_dst, QgsProject.instance())

    l_w = QgsVectorLayer("{datatype}?crs=proj4:{crs}".format(datatype=datatype, 
                         crs=crs_dst.toProj()), "calculation boundary (transformed)",  
                         "memory")
    feats = []
    for f in l.getFeatures():
        geom = f.geometry()
        if wrap:
            n = 0
            p = geom.vertexAt(n)
            # Note vertexAt returns QgsPointXY(0, 0) on error
            while p != QgsPointXY(0, 0):
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
        log('Error transforming layer from "{}" to "{}" (wrap is {})'.format(crs_src_string, crs_dst.toProj(), wrap))
        return None
    else:
        return l_w


def json_geom_to_geojson(txt):
    d = {'type': 'FeatureCollection',
         'features': [{'type': 'Feature',
                       'geometry': json.loads(txt)}]
         }
    return d


class AOI(object):
    def __init__(self, crs_dst):
        self.crs_dst = crs_dst

    def get_crs_dst_wkt(self):
        return self.crs_dst.toWkt()

    def update_from_file(self, f, wrap=False):
        log(u'Setting up AOI from file at {}"'.format(f))
        l = QgsVectorLayer(f, "calculation boundary", "ogr")
        if not l.isValid():
            QtWidgets.QMessageBox.critical(None,
                    tr_calculate.tr("Error"),
                    tr_calculate.tr(u"Unable to load area of interest from {}. There may be a problem with the file or coordinate system. Try manually loading this file into QGIS to verify that it displays properly. If you continue to have problems with this file, send us a message at trends.earth@conservation.org.".format(f)))
            log("Unable to load area of interest.")
            return
        if l.wkbType() == QgsWkbTypes.Polygon \
                or l.wkbType() == QgsWkbTypes.PolygonZ \
                or l.wkbType() == QgsWkbTypes.MultiPolygon \
                or l.wkbType() == QgsWkbTypes.MultiPolygonZ:
            self.datatype = "polygon"
        elif l.wkbType() == QgsWkbTypes.Point \
                or l.wkbType() == QgsWkbTypes.PointZ \
                or l.wkbType() == QgsWkbTypes.MultiPoint \
                or l.wkbType() == QgsWkbTypes.MultiPointZ:
            self.datatype = "point"
        else:
            QtWidgets.QMessageBox.critical(None,
                    tr_calculate.tr("Error"),
                    tr_calculate.tr("Failed to process area of interest - unknown geometry type: {}".format(l.wkbType())))
            log("Failed to process area of interest - unknown geometry type.")
            self.datatype = "unknown"
            return

        self.l = transform_layer(l, self.crs_dst, datatype=self.datatype, wrap=wrap)

    def update_from_geojson(self, geojson, crs_src='epsg:4326', datatype='polygon', wrap=False):
        log('Setting up AOI with geojson. Wrap is {}.'.format(wrap))
        self.datatype = datatype
        # Note geojson is assumed to be in 4326
        l = QgsVectorLayer("{datatype}?crs={crs}".format(datatype=self.datatype, crs=crs_src), "calculation boundary", "memory")
        ds = ogr.Open(json.dumps(geojson))
        layer_in = ds.GetLayer()
        feats_out = []
        for i in range(0, layer_in.GetFeatureCount()):
            feat_in = layer_in.GetFeature(i)
            feat = QgsFeature(l.fields())
            geom = QgsGeometry()
            geom.fromWkb(feat_in.geometry().ExportToWkb())
            feat.setGeometry(geom)
            feats_out.append(feat)
        l.dataProvider().addFeatures(feats_out)
        l.commitChanges()
        if not l.isValid():
            QtWidgets.QMessageBox.critical(None,tr_calculate.tr("Error"),
                                      tr_calculate.tr("Failed to add geojson to temporary layer."))
            log("Failed to add geojson to temporary layer.")
            return
        self.l = transform_layer(l, self.crs_dst, datatype=self.datatype, wrap=wrap)

    def meridian_split(self, out_type='extent', out_format='geojson', warn=True):
        """
        Return list of bounding boxes in WGS84 as geojson for GEE

        Returns multiple geometries as needed to avoid having an extent 
        crossing the 180th meridian
        """

        if out_type not in ['extent', 'layer']:
            raise ValueError('Unrecognized out_type "{}"'.format(out_type))
        if out_format not in ['geojson', 'wkt']:
            raise ValueError(u'Unrecognized out_format "{}"'.format(out_format))

        # Calculate a single feature that is the union of all the features in 
        # this layer - that way there is a single feature to intersect with 
        # each hemisphere.
        geometries = []
        n = 1
        for f in self.get_layer_wgs84().getFeatures():
            # Get an OGR geometry from the QGIS geometry
            geom = f.geometry()
            if not geom.isGeosValid():
                log(u'Invalid feature in row {}.'.format(n))
                QtWidgets.QMessageBox.critical(None,
                                               tr_calculate.tr("Error"),
                                               tr_calculate.tr('Invalid geometry in row {}. Check that all input geometries are valid before processing. Try using the check validity tool on the "Vector" menu on the toolbar for more information on which features are invalid (Under "Vector" - "Geometry Tools" - "Check Validity").'.format(n)))
                return None
            geometries.append(geom)
            n += 1
        union = QgsGeometry.unaryUnion(geometries)

        log(u'Calculating east and west intersections to test if AOI crosses 180th meridian.')
        hemi_e = QgsGeometry.fromWkt('POLYGON ((0 -90, 0 90, 180 90, 180 -90, 0 -90))')
        hemi_w = QgsGeometry.fromWkt('POLYGON ((-180 -90, -180 90, 0 90, 0 -90, -180 -90))')
        intersections = [hemi.intersection(union) for hemi in [hemi_e, hemi_w]]

        if out_type == 'extent':
            pieces = [QgsGeometry.fromRect(i.boundingBox()) for i in intersections if not i.isEmpty()]
        elif out_type == 'layer':
            pieces = [i for i in intersections if not i.isEmpty()]
        pieces_union = QgsGeometry.unaryUnion(pieces)

        if out_format == 'geojson':
            pieces_txt = [json.loads(piece.asJson()) for piece in pieces]
            pieces_union_txt = json.loads(pieces_union.asJson())
        elif out_format == 'wkt':
            pieces_txt = [piece.asWkt() for piece in pieces]
            pieces_union_txt = pieces_union.asWkt()

        if (len(pieces) == 0) or (sum([piece.area() for piece in pieces]) > (pieces_union.area() / 2)):
            # If there is no area in one of the hemispheres, return the
            # original layer, or extent of the original layer. Also return the 
            # original layer (or extent) if the area of the combined pieces
            # from both hemispheres is not significantly smaller than that of 
            # the original polygon.
            log("AOI being processed in one piece (does not cross 180th meridian)")
            return (False, [pieces_union_txt])
        else:
            log("AOI crosses 180th meridian - splitting AOI into two geojsons.")
            if warn:
                QtWidgets.QMessageBox.information(None,tr_calculate.tr("Warning"),
                       tr_calculate.tr('The chosen area crosses the 180th meridian. It is recommended that you set the project coordinate system to a local coordinate system (see the "CRS" tab of the "Project Properties" window from the "Project" menu.)'))
            return (True, pieces_txt)

    def get_aligned_output_bounds(self, f):
        wkts = self.meridian_split(out_format='wkt', warn=False)[1]
        if not wkts:
            return None
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

    def get_area(self):
        wgs84_crs = QgsCoordinateReferenceSystem('EPSG:4326')
        
        # Returns area of aoi components in sq m
        wkts = self.meridian_split(out_format='wkt', warn=False)[1]
        if not wkts:
            return None
        area = 0.
        for wkt in wkts:
            geom = QgsGeometry.fromWkt(wkt)
            # Lambert azimuthal equal area centered on polygon centroid
            centroid = geom.centroid().asPoint()
            laea_crs = QgsCoordinateReferenceSystem.fromProj('+proj=laea +lat_0={} +lon_0={}'.format(centroid.y(), centroid.x()))
            to_laea = QgsCoordinateTransform(wgs84_crs, laea_crs, QgsProject.instance())

            try:
                ret = geom.transform(to_laea)
            except:
                log('Error buffering layer while transforming to laea')
                QtWidgets.QMessageBox.critical(None,tr_calculate.tr("Error"),
                                          tr_calculate.tr("Error transforming coordinates. Check that the input geometry is valid."))
                return None
            this_area = geom.area()
            area += this_area
        return area

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
        wgs84_crs.createFromProj('+proj=longlat +datum=WGS84 +no_defs')
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
                return (False, [json.loads(geom.asJson())])
            else:
                log('Layer has many points ({})'.format(n))
                return self.meridian_split()
        else:
            QtWidgets.QMessageBox.critical(None,tr_calculate.tr("Error"),
                   tr_calculate.tr("Failed to process area of interest - unknown geometry type: {}".format(self.datatype)))
            log("Failed to process area of interest - unknown geometry type.")


    def buffer(self, d):
        log('Buffering layer by {} km.'.format(d))

        feats = []
        for f in self.l.getFeatures():
            geom = f.geometry()
            # Setup an azimuthal equidistant projection centered on the polygon 
            # centroid
            centroid = geom.centroid().asPoint()
            geom.centroid()
            wgs84_crs = QgsCoordinateReferenceSystem('EPSG:4326')
            aeqd_crs = QgsCoordinateReferenceSystem.fromProj('+proj=aeqd +lat_0={} +lon_0={}'.format(centroid.y(), centroid.x()))
            to_aeqd = QgsCoordinateTransform(wgs84_crs, aeqd_crs, QgsProject.instance())

            try:
                ret = geom.transform(to_aeqd)
            except:
                log('Error buffering layer while transforming to aeqd')
                QtWidgets.QMessageBox.critical(None,tr_calculate.tr("Error"),
                                          tr_calculate.tr("Error transforming coordinates. Check that the input geometry is valid."))
                return None
            # Need to convert from km to meters
            geom_buffered = geom.buffer(d * 1000, 100)
            log('Feature area in sq km after buffering (and in aeqd) is: {}'.format(geom_buffered.area()/(1000 * 1000)))
            geom_buffered.transform(to_aeqd, QgsCoordinateTransform.TransformDirection.ReverseTransform)
            f.setGeometry(geom_buffered)
            feats.append(f)
            log('Feature area after buffering (and in WGS84) is: {}'.format(geom_buffered.area()))

        l_buffered = QgsVectorLayer("polygon?crs=proj4:{crs}".format(crs=self.l.crs().toProj()),
                                    "calculation boundary (transformed)",  
                                    "memory")
        l_buffered.dataProvider().addFeatures(feats)
        l_buffered.commitChanges()


        if not l_buffered.isValid():
            log('Error buffering layer')
            raise
        else:
            self.l = l_buffered
            self.datatype = 'polygon'
        return True

    def isValid(self):
        return self.l.isValid()

    def calc_frac_overlap(self, geom):
        """
        Returns fraction of AOI that is overlapped by geom (where geom is a QgsGeometry)

        Used to calculate "within" with a tolerance
        """
        aoi_geom = ogr.CreateGeometryFromWkt(self.bounding_box_geom().asWkt())
        in_geom = ogr.CreateGeometryFromWkt(geom.asWkt())

        geom_area = aoi_geom.GetArea()
        if geom_area == 0:
            # Handle case of a point with zero area
            frac = aoi_geom.Within(in_geom)
        else:
            frac = aoi_geom.Intersection(in_geom).GetArea() / geom_area
            log('Fractional area of overlap: {}'.format(frac))
        return frac


class DlgCalculate(QtWidgets.QDialog, Ui_DlgCalculate):
    def __init__(self, parent=None):
        super(DlgCalculate, self).__init__(parent)

        self.setupUi(self)

        self.dlg_calculate_ld = DlgCalculateLD()
        self.dlg_calculate_tc = DlgCalculateTC()
        self.dlg_calculate_rest_biomass = DlgCalculateRestBiomass()
        self.dlg_calculate_urban = DlgCalculateUrban()

        self.pushButton_ld.clicked.connect(self.btn_ld_clicked)
        self.pushButton_tc.clicked.connect(self.btn_tc_clicked)
        self.pushButton_rest_biomass.clicked.connect(self.btn_rest_biomass_clicked)
        self.pushButton_urban.clicked.connect(self.btn_urban_clicked)

    def btn_ld_clicked(self):
        self.close()
        result = self.dlg_calculate_ld.exec_()

    def btn_tc_clicked(self):
        self.close()
        result = self.dlg_calculate_tc.exec_()

    def btn_rest_biomass_clicked(self):
        self.close()
        result = self.dlg_calculate_rest_biomass.exec_()

    def btn_urban_clicked(self):
        self.close()
        result = self.dlg_calculate_urban.exec_()


class DlgCalculateLD(QtWidgets.QDialog, Ui_DlgCalculateLD):
    def __init__(self, parent=None):
        super(DlgCalculateLD, self).__init__(parent)

        self.setupUi(self)

        # TODO: Bad style - fix when refactoring
        from LDMP.calculate_prod import DlgCalculateProd
        from LDMP.calculate_lc import DlgCalculateLC
        from LDMP.calculate_soc import DlgCalculateSOC
        from LDMP.calculate_ldn import DlgCalculateOneStep, DlgCalculateLDNSummaryTableAdmin
        self.dlg_calculate_prod = DlgCalculateProd()
        self.dlg_calculate_lc = DlgCalculateLC()
        self.dlg_calculate_soc = DlgCalculateSOC()
        self.dlg_calculate_ldn_onestep = DlgCalculateOneStep()
        self.dlg_calculate_ldn_advanced = DlgCalculateLDNSummaryTableAdmin()

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
        result = self.dlg_calculate_ldn_onestep.exec_()

    def btn_summary_single_polygon_clicked(self):
        self.close()
        result = self.dlg_calculate_ldn_advanced.exec_()

    def btn_summary_multi_polygons_clicked(self):
        QtWidgets.QMessageBox.information(None, self.tr("Coming soon!"),
                                      self.tr("Multiple polygon summary table calculation coming soon!"))


class DlgCalculateTC(QtWidgets.QDialog, Ui_DlgCalculateTC):
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


class DlgCalculateRestBiomass(QtWidgets.QDialog, Ui_DlgCalculateRestBiomass):
    def __init__(self, parent=None):
        super(DlgCalculateRestBiomass, self).__init__(parent)

        self.setupUi(self)

        # TODO: Bad style - fix when refactoring
        from LDMP.calculate_rest_biomass import DlgCalculateRestBiomassData
        from LDMP.calculate_rest_biomass import DlgCalculateRestBiomassSummaryTable
        self.dlg_calculate_rest_biomass_data = DlgCalculateRestBiomassData()
        self.dlg_calculate_rest_biomass_summary = DlgCalculateRestBiomassSummaryTable()

        self.btn_calculate_rest_biomass_change.clicked.connect(self.btn_calculate_rest_biomass_change_clicked)
        self.btn_summary_single_polygon.clicked.connect(self.btn_summary_single_polygon_clicked)

    def btn_calculate_rest_biomass_change_clicked(self):
        self.close()
        result = self.dlg_calculate_rest_biomass_data.exec_()

    def btn_summary_single_polygon_clicked(self):
        self.close()
        result = self.dlg_calculate_rest_biomass_summary.exec_()


class DlgCalculateUrban(QtWidgets.QDialog, Ui_DlgCalculateUrban):
    def __init__(self, parent=None):
        super(DlgCalculateUrban, self).__init__(parent)

        self.setupUi(self)

        # TODO: Bad style - fix when refactoring
        from LDMP.calculate_urban import DlgCalculateUrbanData
        from LDMP.calculate_urban import DlgCalculateUrbanSummaryTable
        self.dlg_calculate_urban_data = DlgCalculateUrbanData()
        self.dlg_calculate_urban_summary = DlgCalculateUrbanSummaryTable()

        self.btn_calculate_urban_change.clicked.connect(self.btn_calculate_urban_change_clicked)
        self.btn_summary_single_polygon.clicked.connect(self.btn_summary_single_polygon_clicked)

    def btn_calculate_urban_change_clicked(self):
        self.close()
        result = self.dlg_calculate_urban_data.exec_()

    def btn_summary_single_polygon_clicked(self):
        self.close()
        result = self.dlg_calculate_urban_summary.exec_()


class CalculationOptionsWidget(QtWidgets.QWidget, Ui_WidgetCalculationOptions):
    def __init__(self, parent=None):
        super(CalculationOptionsWidget, self).__init__(parent)

        self.setupUi(self)

        self.radioButton_run_in_cloud.toggled.connect(self.radioButton_run_in_cloud_changed)
        self.btn_local_data_folder_browse.clicked.connect(self.open_folder_browse)

        self.task_name.textChanged.connect(self.task_name_changed)
        self.task_notes.textChanged.connect(self.task_notes_changed)

    def showEvent(self, event):
        super(CalculationOptionsWidget, self).showEvent(event)

        local_data_folder = QSettings().value("LDMP/localdata_dir", None)
        if local_data_folder and os.access(local_data_folder, os.R_OK):
            self.lineEdit_local_data_folder.setText(local_data_folder)
        else:
            self.lineEdit_local_data_folder.setText(None)
        self.task_name.setText(QSettings().value("LDMP/CalculationOptionsWidget/task_name", None))
        self.task_notes.setHtml(QSettings().value("LDMP/CalculationOptionsWidget/task_notes", None))

    def task_name_changed(self, value=None):
        QSettings().setValue("LDMP/CalculationOptionsWidget/task_name", value)

    def task_notes_changed(self):
        QSettings().setValue("LDMP/CalculationOptionsWidget/task_notes", self.task_notes.toHtml())

    def radioButton_run_in_cloud_changed(self):
        if self.radioButton_run_in_cloud.isChecked():
            self.lineEdit_local_data_folder.setEnabled(False)
            self.btn_local_data_folder_browse.setEnabled(False)
        else:
            self.lineEdit_local_data_folder.setEnabled(True)
            self.btn_local_data_folder_browse.setEnabled(True)

    def open_folder_browse(self):
        self.lineEdit_local_data_folder.clear()

        folder = QtWidgets.QFileDialog.getExistingDirectory(self,
                                                        self.tr('Select folder containing data'),
                                                        QSettings().value("LDMP/localdata_dir", None))
        if folder:
            if os.access(folder, os.R_OK):
                QSettings().setValue("LDMP/localdata_dir", os.path.dirname(folder))
                self.lineEdit_local_data_folder.setText(folder)
                return True
            else:
                QtWidgets.QMessageBox.critical(None, self.tr("Error"),
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


class CalculationOutputWidget(QtWidgets.QWidget, Ui_WidgetCalculationOutput):
    def __init__(self, suffixes, subclass_name, parent=None):
        super(CalculationOutputWidget, self).__init__(parent)

        self.output_suffixes = suffixes
        self.subclass_name = subclass_name

        self.setupUi(self)

        self.browse_output_basename.clicked.connect(self.select_output_basename)

    def select_output_basename(self):
        local_name = QSettings().value("LDMP/output_basename_{}".format(self.subclass_name), None)
        if local_name:
            initial_path = local_name
        else:
            initial_path = QSettings().value("LDMP/output_dir", None)


        f, _ = QtWidgets.QFileDialog.getSaveFileName(self,
                self.tr('Choose a prefix to be used when naming output files'),
                initial_path,
                self.tr('Base name (*)'))

        if f:
            if os.access(os.path.dirname(f), os.W_OK):
                QSettings().setValue("LDMP/output_dir", os.path.dirname(f))
                QSettings().setValue("LDMP/output_basename_{}".format(self.subclass_name), f)
                self.output_basename.setText(f)
                self.set_output_summary(f)
            else:
                QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr(u"Cannot write to {}. Choose a different file.".format(f)))

    def set_output_summary(self, f):
        out_files = [f + suffix for suffix in self.output_suffixes]
        self.output_summary.setText("\n".join(["{}"]*len(out_files)).format(*out_files))

    def check_overwrites(self):
        overwrites = []
        for suffix in self.output_suffixes: 
            if os.path.exists(self.output_basename.text() + suffix):
                overwrites.append(os.path.basename(self.output_basename.text() + suffix))

        if len(overwrites) > 0:
            resp = QtWidgets.QMessageBox.question(self,
                    self.tr('Overwrite file?'),
                    self.tr('Using the prefix "{}" would lead to overwriting existing file(s) {}. Do you want to overwrite these file(s)?'.format(
                        self.output_basename.text(),
                        ", ".join(["{}"]*len(overwrites)).format(*overwrites))),
                    QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No)
            if resp == QtWidgets.QMessageBox.No:
                QtWidgets.QMessageBox.information(None, self.tr("Information"),
                                           self.tr(u"Choose a different output prefix and try again."))
                return False

        return True


class DlgCalculateBase(QtWidgets.QDialog):
    """Base class for individual indicator calculate dialogs"""
    firstShowEvent = pyqtSignal()

    @classmethod
    def get_subclass_name(cls):
        return cls.__name__

    def __init__(self, parent=None):
        super(DlgCalculateBase, self).__init__(parent)

        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                               'data', 'scripts.json')) as script_file:
            self.scripts = json.load(script_file)

        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                               'data', 'gee_datasets.json')) as datasets_file:
            self.datasets = json.load(datasets_file)

        self._has_output = False
        self._firstShowEvent = True
        self.reset_tab_on_showEvent = True
        self._max_area = 5e7 # maximum size task the tool supports
        self.settings = QgsSettings()

        self.canvas = iface.mapCanvas()

        self.admin_bounds_key = get_admin_bounds()
        if not self.admin_bounds_key:
            raise ValueError('Admin boundaries not available')

        self.cities = get_cities()
        if not self.cities:
            raise ValueError('Cities list not available')

        self.firstShowEvent.connect(self.firstShow)

    def add_output_tab(self, suffixes=['.json', '.tif']):
        self._has_output = True
        self.output_suffixes = suffixes

    def showEvent(self, event):
        super(DlgCalculateBase, self).showEvent(event)

        if self._firstShowEvent:
            self._firstShowEvent = False
            self.firstShowEvent.emit()

        if self.reset_tab_on_showEvent:
            self.TabBox.setCurrentIndex(0)
        
        # If this dialog has an output_basename widget then set it up with any 
        # saved values in QSettings
        if self._has_output:
            f = QSettings().value("LDMP/output_basename_{}".format(self.get_subclass_name()), None)
            if f:
                self.output_tab.output_basename.setText(f)
                self.output_tab.set_output_summary(f)

    def firstShow(self):

        if self._has_output:
            self.output_tab = CalculationOutputWidget(self.output_suffixes, self.get_subclass_name())
            self.output_tab.setParent(self)
            self.TabBox.addTab(self.output_tab, self.tr('Output'))

        self.options_tab = CalculationOptionsWidget()
        self.options_tab.setParent(self)
        self.TabBox.addTab(self.options_tab, self.tr('Options'))

        # By default show the local or cloud option
        #self.options_tab.toggle_show_where_to_run(True)
        self.options_tab.toggle_show_where_to_run(False)
        
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

    def get_city_geojson(self):
        adm0_a3 = self.admin_bounds_key[self.settings.value(
            "trends_earth/region_of_interest/country/country_name")]['code']
        wof_id = self.settings.value("trends_earth/region_of_interest/current_cities_key")[
            self.settings.value("trends_earth/region_of_interest/country/city_name")
        ]
        return (self.cities[adm0_a3][wof_id]['geojson'])

    def get_admin_poly_geojson(self):
        adm0_a3 = self.admin_bounds_key[self.settings.value(
            "trends_earth/region_of_interest/country/country_name")]['code']
        admin_polys = read_json(u'admin_bounds_polys_{}.json.gz'.format(adm0_a3), verify=False)
        if not admin_polys:
            return None
        if not self.settings.value("trends_earth/region_of_interest/country/region_name") or \
                self.settings.value("trends_earth/region_of_interest/country/region_name") == 'All regions':
            return (admin_polys['geojson'])
        else:
            admin_1_code = self.admin_bounds_key[self.settings.value(
                "trends_earth/region_of_interest/country/country_name")][
                'admin1'][self.settings.value("trends_earth/region_of_interest/country/region_name")]['code']
            return (admin_polys['admin1'][admin_1_code]['geojson'])

    def btn_calculate(self):
        if self.settings.value("trends_earth/region_of_interest/custom_crs_enabled"):
            crs_dst = QgsCoordinateReferenceSystem(
                self.settings.value("trends_earth/region_of_interest/custom_crs")
            )
        else:
            crs_dst = QgsCoordinateReferenceSystem('epsg:4326')

        self.aoi = AOI(crs_dst)

        if self.settings.value("trends_earth/region_of_interest/chosen_method") == 'country_region' or \
                self.settings.value("trends_earth/region_of_interest/chosen_method") == 'country_city':
            if self.settings.value("trends_earth/region_of_interest/chosen_method") == 'country_city':
                if self.settings.value("trends_earth/region_of_interest/buffer_checked") != 'True':
                    QtWidgets.QMessageBox.critical(None,tr_calculate.tr("Error"),
                           tr_calculate.tr("You have chosen to run calculations for a city."
                                            "You must select a buffer distance to define the "
                                           "calculation area when you are processing a city."))
                    return False
                geojson = self.get_city_geojson()
                self.aoi.update_from_geojson(geojson=geojson, 
                                             wrap=self.settings.value(
                                                 "trends_earth/region_of_interest/custom_crs_wrap"),
                                             datatype='point')
            else:
                if not self.settings.value("trends_earth/region_of_interest/country/country_name"):
                    QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                               self.tr("Choose a first level administrative boundary."))
                    return False
                self.button_calculate.setEnabled(False)
                geojson = self.get_admin_poly_geojson()
                self.button_calculate.setEnabled(True)
                if not geojson:
                    QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                               self.tr("Unable to load administrative boundaries."))
                    return False
                self.aoi.update_from_geojson(geojson=geojson, 
                                             wrap=self.settings.value(
                                                 "trends_earth/region_of_interest/custom_crs_wrap"))
        elif self.settings.value("trends_earth/region_of_interest/chosen_method") == 'vector_layer':
            if not self.settings.value("trends_earth/region_of_interest/vector_layer"):
                QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Choose a file to define the area of interest."))
                return False
            if not os.access(self.settings.value("trends_earth/region_of_interest/vector_layer"), os.R_OK):
                QtWidgets.QMessageBox.critical(None,
                                               self.tr("Error"),
                                               self.tr("Unable to read {}.".format(
                                                   self.settings.value(
                                                       "trends_earth/region_of_interest/vector_layer")
                                               )))
                return False
            self.aoi.update_from_file(f=self.settings.value("trends_earth/region_of_interest/area_vector_layer"),
                                      wrap=self.settings.value(
                                                 "trends_earth/region_of_interest/custom_crs_wrap"))
        elif self.settings.value("trends_earth/region_of_interest/chosen_method") == 'point':
            # Area from point
            if not self.settings.value("trends_earth/region_of_interest/point/x") or not \
                    self.settings.value("trends_earth/region_of_interest/point/y"):
                QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Choose a point to define the area of interest."))
                return False
            point = QgsPointXY(float(self.settings.value("trends_earth/region_of_interest/point/x")),
                               float(self.settings.value("trends_earth/region_of_interest/point/y")))
            crs_src = QgsCoordinateReferenceSystem(self.canvas.mapSettings().destinationCrs().authid())
            point = QgsCoordinateTransform(crs_src, crs_dst, QgsProject.instance()).transform(point)
            geojson = json.loads(QgsGeometry.fromPointXY(point).asJson())
            self.aoi.update_from_geojson(geojson=geojson, 
                                         wrap=self.settings.value(
                                                 "trends_earth/region_of_interest/custom_crs_wrap"),
                                         datatype='point')
        else:
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Choose an area of interest."))
            return False

        if self.aoi and (self.aoi.datatype == "unknown" or not self.aoi.isValid()):
            QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Unable to read area of interest."))
            return False

        if self.settings.value("trends_earth/region_of_interest/buffer_checked"):
            ret = self.aoi.buffer(float(self.settings.value("trends_earth/region_of_interest/buffer_size")))
            if not ret:
                QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                        self.tr("Error buffering polygon"))
                return False

        # Check that a bounding box can be created successfully from this aoi
        ret = self.aoi.bounding_box_gee_geojson()
        if not ret:
            QtWidgets.QMessageBox.critical(None,
                                           self.tr("Error"),
                                           self.tr("Unable to calculate bounding box."))
            return False
        else:
            self.gee_bounding_box = ret

        # Limit processing area to be no greater than 10^7 sq km if using a 
        # custom shapefile
        if self.settings.value("trends_earth/region_of_interest/chosen_method") != 'country_city' and \
                self.settings.value("trends_earth/region_of_interest/chosen_method") != 'country_region':
            aoi_area = self.aoi.get_area() / (1000 * 1000)
            if aoi_area > self._max_area:
                QtWidgets.QMessageBox.critical(None, self.tr("Error"),
                        self.tr("The bounding box for the requested area (approximately {:.6n}) sq km "
                                "is too large. Choose a smaller area to process.".format(aoi_area)))
                return False

        if self._has_output:
            if not self.output_tab.output_basename.text():
                QtWidgets.QMessageBox.information(None, self.tr("Error"),
                                              self.tr("Choose an output base name."))
                return False

            # Check if the chosen basename would lead to an  overwrite(s):
            ret = self.output_tab.check_overwrites()
            if not ret:
                return False

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

        json_file = GetTempFilename('.geojson')
        with open(json_file, 'w') as f:
            json.dump(self.geojson, f, separators=(',', ': '))

        gdal.UseExceptions()
        res = gdal.Warp(self.out_file, self.in_file, format='GTiff',
                        cutlineDSName=json_file, srcNodata=-32768, 
                        outputBounds=self.output_bounds,
                        dstNodata=-32767,
                        dstSRS="epsg:4326",
                        outputType=gdal.GDT_Int16,
                        resampleAlg=gdal.GRA_NearestNeighbour,
                        creationOptions=['COMPRESS=LZW'],
                        callback=self.progress_callback)
        os.remove(json_file)

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


class MaskWorker(AbstractWorker):
    def __init__(self, out_file, geojson, model_file=None):
        AbstractWorker.__init__(self)

        self.out_file = out_file
        self.geojson = geojson
        self.model_file = model_file

    def work(self):
        self.toggle_show_progress.emit(True)
        self.toggle_show_cancel.emit(True)


        json_file = GetTempFilename('.geojson')
        with open(json_file, 'w') as f:
            json.dump(self.geojson, f, separators=(',', ': '))

        gdal.UseExceptions()

        if self.model_file:
            # Assumes an image with no rotation
            gt = gdal.Info(self.model_file, format='json')['geoTransform']
            x_size, y_size= gdal.Info(self.model_file, format='json')['size']
            x_min = min(gt[0], gt[0] + x_size * gt[1])
            x_max = max(gt[0], gt[0] + x_size * gt[1])
            y_min = min(gt[3], gt[3] + y_size * gt[5])
            y_max = max(gt[3], gt[3] + y_size * gt[5])
            output_bounds = [x_min, y_min, x_max, y_max]
            x_res = gt[1]
            y_res = gt[5]
        else:
            output_bounds = None
            x_res = None
            y_res = None

        res = gdal.Rasterize(self.out_file, json_file, format='GTiff',
                             outputBounds=output_bounds,
                             initValues=-32767, # Areas that are masked out
                             burnValues=1, # Areas that are NOT masked out
                             xRes=x_res,
                             yRes=y_res,
                             outputSRS="epsg:4326",
                             outputType=gdal.GDT_Int16,
                             creationOptions=['COMPRESS=LZW'],
                             callback=self.progress_callback)
        os.remove(json_file)

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
