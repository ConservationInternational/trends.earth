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
from math import floor, log10
from operator import attrgetter

import json

from PyQt4 import QtGui
from PyQt4.QtCore import QSettings, Qt, QCoreApplication

from qgis.core import QgsColorRampShader, QgsRasterShader, QgsSingleBandPseudoColorRenderer, QgsRasterBandStats
from qgis.utils import iface
mb = iface.messageBar()

import numpy as np

from osgeo import gdal

from LDMP import log
from LDMP.gui.DlgLoadData import Ui_DlgLoadData


def tr(t):
    return QCoreApplication.translate('LDMPPlugin', t)


# Store layer titles and label text in a dictionary here so that it can be
# translated - if it were in the syles JSON then gettext would not have access
# to these strings.
style_text_dict = {
    # Productivity trajectory
    'prod_traj_trend_title': tr('Productivity trajectory (NDVI x 10000 / yr)'),
    'prod_traj_trend_min': tr('{}'),
    'prod_traj_trend_zero': tr('0'),
    'prod_traj_trend_max': tr('{}'),
    'prod_traj_trend_nodata': tr('No data'),

    'prod_traj_signif_title': tr('Productivity trajectory significance'),
    'prod_traj_signif_dec_99': tr('Significant decrease (p < .01)'),
    'prod_traj_signif_dec_95': tr('Significant decrease (p < .05)'),
    'prod_traj_signif_dec_90': tr('Significant decrease (p < .1)'),
    'prod_traj_signif_zero': tr('No significant change'),
    'prod_traj_signif_inc_90': tr('Significant increase (p < .1)'),
    'prod_traj_signif_inc_95': tr('Significant increase (p < .05)'),
    'prod_traj_signif_inc_99': tr('Significant increase (p < .01)'),
    'prod_traj_signif_nodata': tr('No data'),

    # Productivity performance
    'prod_perf_deg_title': tr('Productivity performance'),
    'prod_perf_deg_potential_deg': tr('Potentially degraded'),
    'prod_perf_deg_not_potential_deg': tr('Not potentially degraded'),
    'prod_perf_deg_nodata': tr('No data'),

    # Productivity state
    'prod_state_change_title': tr('Productivity state'),
    'prod_state_change_potential_deg': tr('Potentially degraded'),
    'prod_state_change_stable': tr('Stable'),
    'prod_state_change_potential_improvement': tr('Potentially improved'),
    'prod_state_change_nodata': tr('No data'),


    'prod_state_classes_bl_title': tr('Productivity state baseline classes'),
    'prod_state_classes_bl_nodata': tr('No data'),

    'prod_state_classes_tg_title': tr('Productivity state target classes'),
    'prod_state_classes_tg_nodata': tr('No data'),

    # Land cover
    'lc_bl_title': tr('Land cover (baseline)'),
    'lc_tg_title': tr('Land cover (target)'),
    'lc_tr_title': tr('Land cover (transitions)'),

    'lc_esa_bl_title': tr('Land cover (baseline, ESA CCI classes)'),
    'lc_esa_tg_title': tr('Land cover (target, ESA CCI classes)'),

    'lc_class_forest': tr('Forest'),
    'lc_class_grassland': tr('Grassland'),
    'lc_class_cropland': tr('Cropland'),
    'lc_class_wetland': tr('Wetland'),
    'lc_class_artificial': tr('Artificial area'),
    'lc_class_bare': tr('Bare land'),
    'lc_class_water': tr('Water body'),
    'lc_class_nodata': tr('No data'),

    'lc_tr_forest_persist': tr('Forest persistence'),
    'lc_tr_forest_loss': tr('Forest loss'),
    'lc_tr_grassland_persist': tr('Grassland persistence'),
    'lc_tr_grassland_loss': tr('Grassland loss'),
    'lc_tr_cropland_persist': tr('Cropland persistence'),
    'lc_tr_cropland_loss': tr('Cropland loss'),
    'lc_tr_wetland_persist': tr('Wetland persistence'),
    'lc_tr_wetland_loss': tr('Wetland loss'),
    'lc_tr_artificial_persist': tr('Artificial area persistence'),
    'lc_tr_artificial_loss': tr('Artificial area loss'),
    'lc_tr_bare_persist': tr('Bare land persistence'),
    'lc_tr_bare_loss': tr('Bare land loss'),
    'lc_tr_water_persist': tr('Water body persistence'),
    'lc_tr_water_loss': tr('Water body loss'),
    'lc_tr_nodata': tr('No data'),

    'lc_deg_title': tr('Land cover degradation'),
    'lc_deg_deg': tr('Degradation'),
    'lc_deg_stable': tr('Stable'),
    'lc_deg_imp': tr('Improvement'),
    'lc_deg_nodata': tr('No data'),


    # Soil organic carbon
    'soc_bl_title': tr('Soil organic carbon (baseline, tons / ha)'),
    'soc_bl_nodata': tr('No data'),
    'soc_tg_title': tr('Soil organic carbon (target, tons / ha)'),
    'soc_tg_nodata': tr('No data'),

    'soc_deg_title': tr('Soil organic carbon degradation'),
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


#TODO: Figure out how to do block by block percentile
def get_percentile(f, band_info, p):
    '''Get percentiles of a raster dataset by block'''
    ds = gdal.Open(outfile)
    b = ds.GetRasterBand(band_info['band number'])

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
            d = np.array(b.ReadAsArray(x, y, cols, rows)).astype(np.float)
            for nodata_value in band_info['no data value']:
                d[d == nodata_value] = np.nan
            cutoffs = np.nanpercentile(d, p)
            # get rounded extreme value
            extreme = max([round_to_n(abs(cutoffs[0]), sf), round_to_n(abs(cutoffs[1]), sf)])


def add_layer(f, layer_type, band_info):
    with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                           'data', 'styles.json')) as script_file:
        styles = json.load(script_file)

    try:
        style = styles[layer_type][band_info['name']]
    except KeyError:
        log('No style found for {} (layer type: {})'.format(band_info['name'], layer_type))
        return False

    l = iface.addRasterLayer(f, style_text_dict.get(style['title'], style['title']))
    if not l.isValid():
        log('Failed to add layer')
        return False

    if style['ramp']['type'] == 'categorical':
        r = []
        for item in style['ramp']['items']:
            r.append(QgsColorRampShader.ColorRampItem(item['value'],
                                                      QtGui.QColor(item['color']),
                                                      style_text_dict.get(item['label'], item['label'])))

    elif style['ramp']['type'] == 'zero-centered 2 percent stretch':
        # TODO: This should be done block by block to prevent running out of
        # memory on large rasters - and it should be done in GEE for GEE loaded
        # rasters.
        # Set a colormap centred on zero, going to the extreme value
        # significant to three figures (after a 2 percent stretch)
        ds = gdal.Open(f)
        d = np.array(ds.GetRasterBand(band_info['band_number']).ReadAsArray()).astype(np.float)
        d[d == band_info['no_data_value']] = np.nan
        ds = None
        cutoffs = np.nanpercentile(d, [2, 98])
        log('Cutoffs for 2 percent stretch: {}'.format(cutoffs))
        extreme = max([round_to_n(abs(cutoffs[0]), 2),
                       round_to_n(abs(cutoffs[1]), 2)])
        r = []
        r.append(QgsColorRampShader.ColorRampItem(-extreme,
                                                  QtGui.QColor(style['ramp']['min']['color']),
                                                  '{}'.format(-extreme)))
        r.append(QgsColorRampShader.ColorRampItem(0,
                                                  QtGui.QColor(style['ramp']['zero']['color']),
                                                  '0'))
        r.append(QgsColorRampShader.ColorRampItem(extreme,
                                                  QtGui.QColor(style['ramp']['max']['color']),
                                                  '{}'.format(extreme)))
        r.append(QgsColorRampShader.ColorRampItem(style['ramp']['no data']['value'],
                                                  QtGui.QColor(style['ramp']['no data']['color']),
                                                  style_text_dict.get(style['ramp']['no data']['label'], style['ramp']['no data']['label'])))

    elif style['ramp']['type'] == 'min zero max 98 percent stretch':
        # TODO: This should be done block by block to prevent running out of
        # memory on large rasters - and it should be done in GEE for GEE loaded
        # rasters.
        # Set a colormap from zero to 98th percentile significant to
        # three figures (after a 2 percent stretch)
        ds = gdal.Open(f)
        d = np.array(ds.GetRasterBand(band_info['band_number']).ReadAsArray()).astype(np.float)
        d[d == band_info['no_data_value']] = np.nan
        ds = None
        cutoff = round_to_n(np.nanpercentile(d, [98]), 3)
        log('Cutoff for min zero max 98 stretch: {}'.format(cutoff))
        r = []
        r.append(QgsColorRampShader.ColorRampItem(0,
                                                  QtGui.QColor(style['ramp']['zero']['color']),
                                                  '0'))
        r.append(QgsColorRampShader.ColorRampItem(cutoff,
                                                  QtGui.QColor(style['ramp']['max']['color']),
                                                  '{}'.format(cutoff)))
        r.append(QgsColorRampShader.ColorRampItem(style['ramp']['no data']['value'],
                                                  QtGui.QColor(style['ramp']['no data']['color']),
                                                  style_text_dict.get(style['ramp']['no data']['label'], style['ramp']['no data']['label'])))

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



class DlgLoadData(QtGui.QDialog, Ui_DlgLoadData):
    def __init__(self, parent=None):
        super(DlgLoadData, self).__init__(parent)

        self.setupUi(self)

        self.layers_model = QtGui.QStringListModel()
        self.layers_view.setModel(self.layers_model)
        self.layers_model.setStringList([])

        self.file_browse_btn.clicked.connect(self.browse_file)

        self.file_lineedit.textChanged.connect(self.update_details)

        self.buttonBox.accepted.connect(self.ok_clicked)
        self.buttonBox.rejected.connect(self.cancel_clicked)

    def showEvent(self, e):
        super(DlgLoadData, self).showEvent(e)

        self.file_lineedit.clear()

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

            res = get_results(f)
            if not res:
                QtGui.QMessageBox.critical(None, self.tr("Error"),
                                           self.tr("{} does not appear to be a trends.earth output file".format(f)))
                self.file_lineedit.clear()
                return None
            else:
                self.file_lineedit.setText(f)

    def cancel_clicked(self):
        self.close()

    def ok_clicked(self):
        self.close()
        layers = []
        for i in self.layers_view.selectionModel().selectedIndexes():
            layers.append(i.data())
        if len(layers) > 0:
            results = get_results(self.file_lineedit.text())
            if results:
                for layer in layers:
                    if results.get('local_format', None) == 'tif':
                        f = os.path.splitext(self.file_lineedit.text())[0] + '.tif'
                    elif results.get('local_format', None) == 'vrt':
                        f = os.path.splitext(self.file_lineedit.text())[0] + '.vrt'
                    else:
                        raise ValueError("Unrecognized local file format in download results: {}".format(results.get('local_format', None)))
                    # This only works if there is only one band with this name, 
                    # but this should always be the case by definition, and we 
                    # don't want to fail if multiple bands with the same name 
                    # were added somewhere upstream
                    band_info = [band for band in results['bands'] if band['name'] == layer][0]
                    resp = add_layer(f, results['name'], band_info)
                    if not resp:
                        mb.pushMessage(tr("Error"),
                                       self.tr('Unable to automatically add "{}". No style is defined for this type of layer.'.format(layer)),
                                       level=1, duration=5)
                else:
                    log('Error loading "{}" results from {}'.format(layer, self.file_lineedit.text()))
        else:
            QtGui.QMessageBox.critical(None, self.tr("Error"), self.tr("Select a layer to load."))

    def update_details(self):
        if self.file_lineedit.text():
            results = get_results(self.file_lineedit.text())
            if results:
                self.layers_model.setStringList([band['name'] for band in results['bands']])
                self.layers_view.setEditTriggers(QtGui.QAbstractItemView.NoEditTriggers)
                self.layers_view.selectAll()
            else:
                self.layers_model.setStringList([])

            params = get_params(self.file_lineedit.text())
            if params:
                self.task_name.setText(params.get('task_name', ''))
                self.input.setText(json.dumps(params, indent=4, sort_keys=True))
                self.output.setText(json.dumps(results, indent=4, sort_keys=True))
                self.comments.setText(params.get('task_notes', ''))
            else:
                self.task_name.clear()
                self.input.clear()
                self.output.clear()
                self.comments.clear()
        else:
            self.layers_model.setStringList([])
            self.task_name.clear()
            self.input.clear()
            self.output.clear()
            self.comments.clear()
            return None
