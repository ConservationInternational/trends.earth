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

from PyQt4 import QtGui
from PyQt4.QtCore import QTextCodec, QSettings, pyqtSignal, QCoreApplication

from qgis.core import QgsPoint, QgsGeometry, QgsJSONUtils, QgsVectorLayer, \
        QgsCoordinateTransform, QgsCoordinateReferenceSystem, \
        QGis, QgsMapLayerRegistry, QgsDataProvider
from qgis.utils import iface
from qgis.gui import QgsMapToolEmitPoint, QgsMapToolPan

from LDMP import log
from LDMP.gui.DlgCalculate import Ui_DlgCalculate
from LDMP.gui.WidgetSelectArea import Ui_WidgetSelectArea
from LDMP.gui.WidgetCalculationOptions import Ui_WidgetCalculationOptions
from LDMP.download import read_json, get_admin_bounds


def tr(t):
    return QCoreApplication.translate('LDMPPlugin', t)


class AOI(object):
    def __init__(self, f=None, geojson=None, datatype='polygon', 
                 out_crs='epsg:4326', wrap=False):
        """
        Can initialize with either a file, or a geojson. Note datatype is 
        ignored unless geojson is used.
        """
        self.isValid = False

        log('Setting up AOI with CRS {} and wrap set to {}'.format(out_crs, wrap))

        if f and not geojson:
            l = QgsVectorLayer(f, "calculation boundary", "ogr")
            if not l.isValid():
                return
            if l.geometryType() == QGis.Polygon:
                datatype = "polygon"
            elif l.geometryType() == QGis.Point:
                datatype = "point"
            else:
                QtGui.QMessageBox.critical(None, tr("Error"),
                        tr("Failed to process area of interest - unknown geometry type:{}".format(l.geometryType())))
                log("Failed to process area of interest - unknown geometry type.")
                return
        elif not f and geojson:
            # Note geojson is assumed to be in 4326
            l = QgsVectorLayer("{datatype}?crs=epsg:4326".format(datatype=datatype), "calculation boundary", "memory")
            fields = QgsJSONUtils.stringToFields(json.dumps(geojson), QTextCodec.codecForName('UTF8'))
            features = QgsJSONUtils.stringToFeatureList(json.dumps(geojson), fields, QTextCodec.codecForName('UTF8'))
            ret = l.dataProvider().addFeatures(features)
            l.commitChanges()
            if not ret:
                QtGui.QMessageBox.critical(None, tr("Error"),
                                           tr("Failed to add geojson to temporary layer."))
                log("Failed to add geojson to temporary layer.")
                return
        else:
            raise ValueError("Must specify file or geojson")

        crs_source = l.crs()
        #crs_dest = QgsCoordinateReferenceSystem('+init=epsg:4326 +lon_wrap=180')
        crs_dest = QgsCoordinateReferenceSystem('+init=epsg:4326')
        t = QgsCoordinateTransform(crs_source, crs_dest)

        # Transform layer
        #l_trans = QgsVectorLayer("{datatype}?crs=proj4:+proj=longlat +datum=WGS84 +lon_wrap=180".format(datatype=datatype), "calculation boundary (transformed)",  "memory")
        l_trans = QgsVectorLayer("{datatype}?crs=proj4:+proj=longlat +datum=WGS84".format(datatype=datatype), "calculation boundary (transformed)",  "memory")
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
            #geom.transform(t)
            f.setGeometry(geom)
            feats.append(f)
        l_trans.dataProvider().addFeatures(feats)
        l_trans.commitChanges()
        if not l_trans.isValid():
            self.layer = None
            log("Error transforming AOI coordinates to trans")
            return
        else:
            self.layer = l_trans

        #QgsMapLayerRegistry.instance().addMapLayer(l_trans)

        # Transform bounding box
        self.bounding_box_geom = QgsGeometry.fromRect(l_trans.extent())
        # Save a geometry of the bounding box
        #self.bounding_box_geom.transform(t)
        # Also save a geojson of the bounding box (needed for shipping to GEE)
        self.bounding_box_geojson = json.loads(self.bounding_box_geom.exportToGeoJSON())

        # # Check the coordinates of the bounding box are now in WGS84 (in case 
        # # no transformation was available for the chosen coordinate systems)
        # bbox = self.bounding_box_geom.boundingBox()
        # log("Bounding box: {}, {}, {}, {}".format(bbox.xMinimum(), bbox.xMaximum(), bbox.yMinimum(), bbox.yMaximum()))
        # if (bbox.xMinimum() < -180) or \
        #    (bbox.xMaximum() > 180) or \
        #    (bbox.yMinimum() < -90) or \
        #    (bbox.yMaximum() > 90):
        #     QtGui.QMessageBox.critical(None, tr("Error"),
        #                                tr("Coordinates of area of interest could not be transformed to WGS84. Check that the projection system is defined."), None)
        #     log("Error transforming AOI coordinates to WGS84")
        # else:
        #     self.isValid = True

        self.isValid = True


class DlgCalculate(QtGui.QDialog, Ui_DlgCalculate):
    def __init__(self, parent=None):
        super(DlgCalculate, self).__init__(parent)

        self.setupUi(self)

        self.dlg_calculate_prod = DlgCalculateProd()
        self.dlg_calculate_lc = DlgCalculateLC()
        self.dlg_calculate_soc = DlgCalculateSOC()
        self.dlg_calculate_sdg_onestep = DlgCalculateSDGOneStep()
        self.dlg_calculate_sdg_advanced = DlgCalculateSDGAdvanced()

        self.btn_prod.clicked.connect(self.btn_prod_clicked)
        self.btn_lc.clicked.connect(self.btn_lc_clicked)
        self.btn_soc.clicked.connect(self.btn_soc_clicked)
        self.btn_sdg_onestep.clicked.connect(self.btn_sdg_onestep_clicked)
        self.btn_sdg_advanced.clicked.connect(self.btn_sdg_advanced_clicked)

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

    def btn_sdg_advanced_clicked(self):
        self.close()
        result = self.dlg_calculate_sdg_advanced.exec_()

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
                                           self.tr("Cannot read {}. Choose a different folder.".format(folder)))
                return False
        else:
            return False
                

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

    #     self.area_fromadmin.toggled.connect(self.options_save)
    #     self.groupBox_custom_crs.toggled.connect(self.options_save)
    #     self.area_admin_0.currentIndexChanged.connect(self.options_save)
    #     self.area_admin_1.currentIndexChanged.connect(self.options_save)
    #
    # def showEvent(self, event):
    #     "Load preferences on show"
    #     super(AreaWidget, self).showEvent(event)
    #
    #     if QSettings().value("LDMP/area_admin", True, type=bool):
    #         self.area_fromadmin.setChecked(True)
    #     else:
    #         self.area_fromfile.setChecked(True)
    #     self.groupBox_custom_crs.setChecked(QSettings().value("LDMP/custom_crs", False, type=bool))
    #
    #     self.area_admin_0.setCurrentIndex(QSettings().value("LDMP/admin_0_index", 0))
    #     self.area_admin_1.setCurrentIndex(QSettings().value("LDMP/admin_1_index", 0))
    #
    # def options_save(self):
    #     QSettings().setValue("LDMP/area_admin", self.area_fromadmin.isChecked())
    #     QSettings().setValue("LDMP/custom_crs", self.groupBox_custom_crs.isChecked())
    #     QSettings().setValue("LDMP/admin_0_index", self.area_admin_0.currentIndex())
    #     QSettings().setValue("LDMP/admin_1_index", self.area_admin_1.currentIndex())

    def showEvent(self, event):
        super(AreaWidget, self).showEvent(event)
        proj_crs = QgsCoordinateReferenceSystem(self.canvas.mapRenderer().destinationCrs().authid())
        self.mQgsProjectionSelectionWidget.setCrs(proj_crs)

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
            self.area_frompoint.show()
            self.area_frompoint_label_x.show()
            self.area_frompoint_point_x.show()
            self.area_frompoint_label_y.show()
            self.area_frompoint_point_y.show()
            self.area_frompoint_choose_point.show()
        else:
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
                                           self.tr("Cannot read {}. Choose a different file.".format(vector_file)))
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

        if self._firstShowEvent:
            self._firstShowEvent = False
            self.firstShowEvent.emit()

        if self.reset_tab_on_showEvent:
            self.TabBox.setCurrentIndex(0)

        # By default, don't show area from point selector
        self.area_tab.show_areafrom_point_toggle(False)
        # By default, show custom crs groupBox
        self.area_tab.groupBox_custom_crs.show()

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
        # What CRS should be used for this country?
        crs = self.area_tab.admin_bounds_key[self.area_tab.area_admin_0.currentText()]['crs']
        # Does this country need to be wrapped across the 180 degree meridian?
        wrap = self.area_tab.admin_bounds_key[self.area_tab.area_admin_0.currentText()]['wrap']
        admin_polys = read_json('admin_bounds_polys_{}.json.gz'.format(adm0_a3), verify=False)
        if not admin_polys:
            return None
        if not self.area_tab.area_admin_1.currentText() or self.area_tab.area_admin_1.currentText() == 'All regions':
            return (admin_polys['geojson'], crs, wrap)
        else:
            admin_1_code = self.area_tab.admin_bounds_key[self.area_tab.area_admin_0.currentText()]['admin1'][self.area_tab.area_admin_1.currentText()]['code']
            return (admin_polys['admin1'][admin_1_code]['geojson'], crs, wrap)

    def btn_calculate(self):
        if self.area_tab.area_fromadmin.isChecked():
            if not self.area_tab.area_admin_0.currentText():
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Choose a first level administrative boundary."), None)
                return False
            self.button_calculate.setEnabled(False)
            geojson, crs, wrap = self.load_admin_polys()
            self.button_calculate.setEnabled(True)
            if not geojson:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Unable to load administrative boundaries."), None)
                return False
            self.aoi = AOI(geojson=geojson, out_crs=crs, wrap=wrap)
        elif self.area_tab.area_fromfile.isChecked():
            if not self.area_tab.area_fromfile_file.text():
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Choose a file to define the area of interest."), None)
                return False
            self.aoi = AOI(f=self.area_tab.area_fromfile_file.text())
        elif self.area_tab.area_frompoint.isVisible() and self.area_tab.area_frompoint:
            # Area from point
            if not self.self.area_tab.area_frompoint_point_x.text() or not self.self.area_tab.area_frompoint_point_y.text():
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("Choose a point to define the area of interest."), None)
                return False
            point = QgsPoint(float(self.self.area_tab.area_frompoint_point_x.text()), float(self.self.area_tab.area_frompoint_point_y.text()))
            crs_source = QgsCoordinateReferenceSystem(self.canvas.mapRenderer().destinationCrs().authid())
            crs_dest = QgsCoordinateReferenceSystem(4326)
            point = QgsCoordinateTransform(crs_source, crs_dest).transform(point)
            geojson = QgsGeometry.fromPoint(point).exportToGeoJSON()
            self.aoi = AOI(geojson=geojson, datatype='point')
            self.aoi.bounding_box_geojson = json.loads(geojson)
        else:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Choose an area of interest."), None)
            return False

        if self.aoi and not self.aoi.isValid:
            QtGui.QMessageBox.critical(None, self.tr("Error"),
                                       self.tr("Unable to read area of interest."), None)
            return False

        return True


from LDMP.calculate_prod import DlgCalculateProd
from LDMP.calculate_lc import DlgCalculateLC
from LDMP.calculate_soc import DlgCalculateSOC
from LDMP.calculate_sdg import DlgCalculateSDGOneStep, DlgCalculateSDGAdvanced
