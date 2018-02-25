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
from math import floor, log10
from operator import attrgetter

import json

from PyQt4 import QtGui
from PyQt4.QtCore import QSettings, Qt, QCoreApplication, pyqtSignal

from qgis.core import QgsColorRampShader, QgsRasterShader, \
    QgsSingleBandPseudoColorRenderer, QgsRasterBandStats, QgsVectorLayer, \
    QgsRasterLayer
from qgis.utils import iface
mb = iface.messageBar()

import numpy as np

from osgeo import gdal

from LDMP import log
from LDMP.calculate_lc import DlgCalculateLCSetAggregation
from LDMP.gui.DlgLoadData import Ui_DlgLoadData
from LDMP.gui.DlgLoadDataTE import Ui_DlgLoadDataTE
from LDMP.gui.DlgLoadDataLC import Ui_DlgLoadDataLC
from LDMP.gui.DlgLoadDataSOC import Ui_DlgLoadDataSOC
from LDMP.gui.DlgJobsDetails import Ui_DlgJobsDetails
from LDMP.gui.WidgetLoadDataSelectFileInput import Ui_WidgetLoadDataSelectFileInput
from LDMP.gui.WidgetLoadDataSelectRasterOutput import Ui_WidgetLoadDataSelectRasterOutput


with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                       'data', 'styles.json')) as script_file:
    styles = json.load(script_file)


def tr(t):
    return QCoreApplication.translate('LDMPPlugin', t)


def tr_style_text(label):
    """If no translation is available, use the original label"""
    val = style_text_dict.get(label, None)
    if val:
        return val
    else:
        if isinstance(label, basestring):
            return label
        else:
            return str(label)

def get_band_title(band_info):
    style = styles[band_info['name']]
    return tr_style_text(style['title']).format(**band_info['metadata'])

# Store layer titles and label text in a dictionary here so that it can be
# translated - if it were in the syles JSON then gettext would not have access
# to these strings.
style_text_dict = {
    # Productivity trajectory
    'prod_traj_trend_title': tr('Productivity trajectory ({year_start} to {year_end}, NDVI x 10000 / yr)'),
    'prod_traj_trend_nodata': tr('No data'),

    'prod_traj_signif_title': tr('Productivity trajectory degradation ({year_start} to {year_end})'),
    'prod_traj_signif_dec_99': tr('Degradation (significant decrease, p < .01)'),
    'prod_traj_signif_dec_95': tr('Degradation (significant decrease, p < .05)'),
    'prod_traj_signif_dec_90': tr('Stable (significant decrease, p < .1)'),
    'prod_traj_signif_zero': tr('Stable (no significant change)'),
    'prod_traj_signif_inc_90': tr('Stable (significant increase, p < .1)'),
    'prod_traj_signif_inc_95': tr('Improvement (significant increase, p < .05)'),
    'prod_traj_signif_inc_99': tr('Improvement (significant increase, p < .01)'),
    'prod_traj_signif_nodata': tr('No data'),

    # Productivity performance
    'prod_perf_deg_title': tr('Productivity performance degradation ({year_start} to {year_end})'),
    'prod_perf_deg_potential_deg': tr('Degradation'),
    'prod_perf_deg_not_potential_deg': tr('Not degradation'),
    'prod_perf_deg_nodata': tr('No data'),

    'prod_perf_ratio_title': tr('Productivity performance ({year_start} to {year_end}, ratio)'),
    'prod_perf_ratio_nodata': tr('No data'),

    'prod_perf_units_title': tr('Productivity performance ({year_start}, units)'),
    'prod_perf_units_nodata': tr('No data'),

    # Productivity state
    'prod_state_change_title': tr('Productivity state degradation ({year_bl_start}-{year_bl_end} to {year_tg_start}-{year_tg_end})'),
    'prod_state_change_potential_deg': tr('Degradation'),
    'prod_state_change_stable': tr('Stable'),
    'prod_state_change_potential_improvement': tr('Improvement'),
    'prod_state_change_nodata': tr('No data'),

    'prod_state_classes_title': tr('Productivity state classes ({year_start}-{year_end})'),
    'prod_state_classes_nodata': tr('No data'),

    # Land cover
    'lc_deg_title': tr('Land cover degradation ({year_baseline} to {year_target})'),
    'lc_deg_deg': tr('Degradation'),
    'lc_deg_stable': tr('Stable'),
    'lc_deg_imp': tr('Improvement'),
    'lc_deg_nodata': tr('No data'),

    'lc_7class_title': tr('Land cover ({year}, 7 class)'),
    'lc_esa_title': tr('Land cover ({year}, ESA CCI classes)'),
    'lc_7class_mode_title': tr('Land cover mode ({year_start}-{year_end}, 7 class)'),
    'lc_esa_mode_title': tr('Land cover mode ({year_start}-{year_end}, ESA CCI classes)'),

    'lc_class_nodata': tr('-32768 - No data'),
    'lc_class_forest': tr('1 - Forest'),
    'lc_class_grassland': tr('2 - Grassland'),
    'lc_class_cropland': tr('3 - Cropland'),
    'lc_class_wetland': tr('4 - Wetland'),
    'lc_class_artificial': tr('5 - Artificial area'),
    'lc_class_bare': tr('6 - Bare land'),
    'lc_class_water': tr('7 - Water body'),

    'lc_tr_title': tr('Land cover (transitions, {year_baseline} to {year_target})'),
    'lc_tr_nochange': tr('No change'),
    'lc_tr_forest_loss': tr('Forest loss'),
    'lc_tr_grassland_loss': tr('Grassland loss'),
    'lc_tr_cropland_loss': tr('Cropland loss'),
    'lc_tr_wetland_loss': tr('Wetland loss'),
    'lc_tr_artificial_loss': tr('Artificial area loss'),
    'lc_tr_bare_loss': tr('Bare land loss'),
    'lc_tr_water_loss': tr('Water body loss'),
    'lc_tr_nodata': tr('No data'),

    # Soil organic carbon
    'soc_title': tr('Soil organic carbon ({year}, tons / ha)'),
    'soc_nodata': tr('No data'),

    'soc_deg_title': tr('Soil organic carbon degradation ({year_start} to {year_end})'),
    'soc_deg_deg': tr('Degradation'),
    'soc_deg_stable': tr('Stable'),
    'soc_deg_imp': tr('Improvement'),
    'soc_deg_nodata': tr('No data'),

    # Degradation SDG final layer
    'sdg_prod_combined_title': tr('Productivity degradation (combined - SDG 15.3.1)'),
    'sdg_prod_combined_deg_deg': tr('Degradation'),
    'sdg_prod_combined_deg_stable': tr('Stable'),
    'sdg_prod_combined_deg_imp': tr('Improvement'),
    'sdg_prod_combined_deg_nodata': tr('No data'),

    'combined_sdg_title': tr('Degradation (combined - SDG 15.3.1)'),
    'combined_sdg_deg_deg': tr('Degradation'),
    'combined_sdg_deg_stable': tr('Stable'),
    'combined_sdg_deg_imp': tr('Improvement'),
    'combined_sdg_deg_nodata': tr('No data'),
}


def get_params(json_file):
    try:
        with open(json_file) as f:
            d = json.load(f)
    except (OSError, IOError, ValueError) as e:
        log('Error loading {}'.format(json_file))
        return None

    try:
        params = d.get('params', None)
        if not params:
            log('Missing key in {}'.format(json_file))
            return None
        else:
            return params
    except AttributeError:
        log('Unable to parse {}'.format(json_file))
        return None


def get_results(json_file):
    try:
        with open(json_file) as f:
            d = json.load(f)
    except (OSError, IOError, ValueError) as e:
        log('Error loading {}'.format(json_file))
        return None

    try:
        results = d.get('results', None)
        if not results \
                or not results.has_key('type') \
                or not results.has_key('name') \
                or not results.has_key('bands') \
                or not results.has_key('urls'):
            log('Missing key in {}'.format(json_file))
            return None
    except AttributeError:
        log('Unable to parse {}'.format(json_file))
        return None

    # Check accompanying tif file(s) are there:
    if len(results['urls']['files']) > 1:
        # If more than one file is returned by GEE, then trends.earth will
        # write a virtual raster table listing these files
        data_file = os.path.splitext(json_file)[0] + '.vrt'
    else:
        data_file = os.path.splitext(json_file)[0] + '.tif'
    if not os.access(data_file, os.R_OK):
        log('Data file {} is missing'.format(data_file))
        return None
    else:
        return results


def round_to_n(x, sf=3):
    'Function to round a positive value to n significant figures'
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


def get_cutoff(f, band_info, percentiles):
    if len(percentiles) != 1 and len(percentiles) != 2:
        raise ValueError("Percentiles must have length 1 or 2. Percentiles that were passed: {}".format(percentiles))
    d = get_sample(f, band_info['band_number'])
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

def add_layer(f, band_info):
    try:
        style = styles[band_info['name']]
    except KeyError:
        log('No style found for {}'.format(band_info['name'] ))
        return False

    title = get_band_title(band_info)

    l = iface.addRasterLayer(f, title)
    if not l.isValid():
        log('Failed to add layer')
        return False

    if style['ramp']['type'] == 'categorical':
        r = []
        for item in style['ramp']['items']:
            r.append(QgsColorRampShader.ColorRampItem(item['value'],
                                                      QtGui.QColor(item['color']),
                                                      tr_style_text(item['label'])))

    elif style['ramp']['type'] == 'zero-centered stretch':
        # Set a colormap centred on zero, going to the max of the min and max 
        # extreme value significant to three figures.
        cutoff = get_cutoff(f, band_info, [style['ramp']['percent stretch'], 100 - style['ramp']['percent stretch']])
        log('Cutoff for {} percent stretch: {}'.format(style['ramp']['percent stretch'], cutoff))
        r = []
        r.append(QgsColorRampShader.ColorRampItem(-cutoff,
                                                  QtGui.QColor(style['ramp']['min']['color']),
                                                  '{}'.format(-cutoff)))
        r.append(QgsColorRampShader.ColorRampItem(0,
                                                  QtGui.QColor(style['ramp']['zero']['color']),
                                                  '0'))
        r.append(QgsColorRampShader.ColorRampItem(cutoff,
                                                  QtGui.QColor(style['ramp']['max']['color']),
                                                  '{}'.format(cutoff)))
        r.append(QgsColorRampShader.ColorRampItem(style['ramp']['no data']['value'],
                                                  QtGui.QColor(style['ramp']['no data']['color']),
                                                  tr_style_text(style['ramp']['no data']['label'])))

    elif style['ramp']['type'] == 'min zero stretch':
        # Set a colormap from zero to percent stretch significant to
        # three figures.
        cutoff = get_cutoff(f, band_info, [100 - style['ramp']['percent stretch']])
        log('Cutoff for min zero max {} percent stretch: {}'.format(100 - style['ramp']['percent stretch'], cutoff))
        r = []
        r.append(QgsColorRampShader.ColorRampItem(0,
                                                  QtGui.QColor(style['ramp']['zero']['color']),
                                                  '0'))
        if style['ramp'].has_key('mid'):
            r.append(QgsColorRampShader.ColorRampItem(cutoff/2,
                                                      QtGui.QColor(style['ramp']['mid']['color']),
                                                      str(cutoff/2)))
        r.append(QgsColorRampShader.ColorRampItem(cutoff,
                                                  QtGui.QColor(style['ramp']['max']['color']),
                                                  '{}'.format(cutoff)))
        r.append(QgsColorRampShader.ColorRampItem(style['ramp']['no data']['value'],
                                                  QtGui.QColor(style['ramp']['no data']['color']),
                                                  tr_style_text(style['ramp']['no data']['label'])))

    else:
        log('Failed to load trends.earth style. Adding layer using QGIS defaults.')
        QtGui.QMessageBox.critical(None,
                                   tr("Error"),
                                   tr("Failed to load trends.earth style. Adding layer using QGIS defaults."))
        return False

    fcn = QgsColorRampShader()
    if style['ramp']['shader'] == 'exact':
        fcn.setColorRampType("EXACT")
    elif style['ramp']['shader'] == 'discrete':
        fcn.setColorRampType("DISCRETE")
    elif style['ramp']['shader'] == 'interpolated':
        fcn.setColorRampType("INTERPOLATED")
    else:
        raise TypeError("Unrecognized color ramp type: {}".format(style['ramp']['shader']))
    # Make sure the items in the color ramp are sorted by value (weird display 
    # errors will otherwise result)
    r = sorted(r, key=attrgetter('value'))
    fcn.setColorRampItemList(r)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(fcn)
    pseudoRenderer = QgsSingleBandPseudoColorRenderer(l.dataProvider(),
                                                      band_info['band_number'],
                                                      shader)
    l.setRenderer(pseudoRenderer)
    l.triggerRepaint()
    iface.legendInterface().refreshLayerSymbology(l)

    return True


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

        self.btn_te.clicked.connect(self.run_te)
        self.btn_lc.clicked.connect(self.run_lc)
        self.btn_soc.clicked.connect(self.run_soc)

    def run_te(self):
        self.dlg_loaddata_te.show()
        self.close()

    def run_lc(self):
        self.dlg_loaddata_lc.show()
        self.close()

    def run_soc(self):
        self.dlg_loaddata_soc.show()
        self.close()

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
        params = get_params(self.file_lineedit.text())
        results = get_results(self.file_lineedit.text())
        if params and results:
            details_dlg.task_name.setText(params.get('task_name', ''))
            details_dlg.comments.setText(params.get('task_notes', ''))
            details_dlg.input.setText(json.dumps(params, indent=4, sort_keys=True))
            details_dlg.output.setText(json.dumps(results, indent=4, sort_keys=True))
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
        self.close()
        rows = []
        for i in self.layers_view.selectionModel().selectedRows():
            rows.append(i.row())
        if len(rows) > 0:
            results = get_results(self.file_lineedit.text())
            if results:
                for row in rows:
                    if results.get('local_format', None) == 'tif':
                        f = os.path.splitext(self.file_lineedit.text())[0] + '.tif'
                    elif results.get('local_format', None) == 'vrt':
                        f = os.path.splitext(self.file_lineedit.text())[0] + '.vrt'
                    else:
                        raise ValueError("Unrecognized local file format in download results: {}".format(results.get('local_format', None)))
                    resp = add_layer(f, results['bands'][row])
                    if not resp:
                        mb.pushMessage(tr("Error"),
                                       self.tr('Unable to automatically add "{}". No style is defined for this type of layer.'.format(results['bands'][row]['name'])),
                                       level=1, duration=5)
            else:
                log('Error loading "{}" results from {}'.format(layer, self.file_lineedit.text()))
        else:
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Select a layer to load."))

    def update_layer_list(self, f=None):
        if not f:
            f = self.file_lineedit.text()
        if f:
            results = get_results(f)
            if results:
                self.layers_model.setStringList([get_band_title(band) for band in results['bands']])
                self.layers_view.setEditTriggers(QtGui.QAbstractItemView.NoEditTriggers)
                for n in range(len(results['bands'])):
                    if results['bands'][n]['add_to_map']:
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

    def __init__(self, parent=None):
        super(LoadDataSelectFileInputWidget, self).__init__(parent)
        self.setupUi(self)

        self.radio_raster_input.toggled.connect(self.radio_raster_input_toggled)

        self.btn_raster_dataset_browse.clicked.connect(self.open_raster_browse)
        self.btn_polygon_dataset_browse.clicked.connect(self.open_vector_browse)

    def radio_raster_input_toggled(self):
        if self.radio_raster_input.isChecked():
            self.btn_raster_dataset_browse.setEnabled(True)
            self.lineEdit_raster_file.setEnabled(True)
            self.comboBox_bandnumber.setEnabled(True)
            self.label_bandnumber.setEnabled(True)
            self.btn_polygon_dataset_browse.setEnabled(False)
            self.lineEdit_polygon_file.setEnabled(False)
            self.label_fieldname.setEnabled(False)
            self.comboBox_fieldname.setEnabled(False)
        else:
            self.btn_raster_dataset_browse.setEnabled(False)
            self.lineEdit_raster_file.setEnabled(False)
            self.comboBox_bandnumber.setEnabled(False)
            self.label_bandnumber.setEnabled(False)
            self.btn_polygon_dataset_browse.setEnabled(True)
            self.lineEdit_polygon_file.setEnabled(True)
            self.label_fieldname.setEnabled(True)
            self.comboBox_fieldname.setEnabled(True)

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
                                                        self.tr('Raster file (*.tif *.dat *.img)'))
        if os.access(raster_file, os.W_OK):
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


class DlgLoadDataLC(DlgLoadDataBase, Ui_DlgLoadDataLC):
    def __init__(self, parent=None):
        super(DlgLoadDataLC, self).__init__(parent)

        # This needs to be inserted after the lc definition widget but before 
        # the button box with ok/cancel
        self.output_widget = LoadDataSelectRasterOutput()
        self.verticalLayout.insertWidget(2, self.output_widget)

        self.input_widget.inputFileChanged.connect(self.input_file_changed)

        self.btn_agg_edit_def.clicked.connect(self.agg_edit)
        self.btn_agg_edit_def.setEnabled(False)

    def input_file_changed(self, valid):
        if valid:
            self.btn_agg_edit_def.setEnabled(True)
        else:
            self.btn_agg_edit_def.setEnabled(False)

    def agg_edit(self):
        if self.input_widget.radio_raster_input.isChecked():
            f = self.input_widget.lineEdit_raster_file.text()
            #TODO: Need to display a progress bar onscreen while this is happening
            values = get_unique_values(f, int(self.input_widget.comboBox_bandnumber.currentText()))
        else:
            f = self.input_widget.lineEdit_polygon_file.text()
            l = self.input_widget.get_vector_layer(f)
            idx = l.fieldNameIndex(self.input_widget.comboBox_fieldname.currentText())
            values = l.uniqueValues(idx)
            if len(values) > 50:
                values = None
        if values:
            # Set all of the classes to no data by default
            classes = [{'Initial_Code':str(value), 'Initial_Label':str(value), 'Final_Label':'No data', 'Final_Code':'-32768'} for value in sorted(values)]
            self.dlg_agg = DlgCalculateLCSetAggregation(classes, parent=self)
            self.dlg_agg.exec_()
        else:
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Error reading data. Trends.Earth supports a maximum of 50 different land cover classes".format(), None))


class DlgLoadDataSOC(DlgLoadDataBase, Ui_DlgLoadDataSOC):
    def __init__(self, parent=None):
        super(DlgLoadDataSOC, self).__init__(parent)

        # This needs to be inserted after the input widget but before the 
        # button box with ok/cancel
        self.output_widget = LoadDataSelectRasterOutput()
        self.verticalLayout.insertWidget(1, self.output_widget)
