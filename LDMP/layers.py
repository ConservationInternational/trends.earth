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
from operator import attrgetter
from math import floor, log10

from marshmallow import ValidationError

from qgis.core import QgsColorRampShader, QgsRasterShader, \
    QgsSingleBandPseudoColorRenderer, QgsMapLayerRegistry, \
    QgsRasterLayer
from qgis.utils import iface
mb = iface.messageBar()

from osgeo import gdal

import numpy as np

from PyQt4 import QtGui
from PyQt4.QtCore import QSettings, Qt, QCoreApplication, pyqtSignal

from LDMP import log

from LDMP.schemas.schemas import LocalRaster, LocalRasterSchema

def tr(t):
    return QCoreApplication.translate('LDMPPlugin', t)


# Store layer titles and label text in a dictionary here so that it can be
# translated - if it were in the syles JSON then gettext would not have access
# to these strings.
style_text_dict = {
    # Shared
    'nodata': tr('No data'),

    # Productivity trajectory
    'prod_traj_trend_title': tr('Productivity trajectory ({year_start} to {year_end}, NDVI x 10000 / yr)'),

    'prod_traj_signif_title': tr('Productivity trajectory degradation ({year_start} to {year_end})'),
    'prod_traj_signif_dec_99': tr('Degradation (significant decrease, p < .01)'),
    'prod_traj_signif_dec_95': tr('Degradation (significant decrease, p < .05)'),
    'prod_traj_signif_dec_90': tr('Stable (significant decrease, p < .1)'),
    'prod_traj_signif_zero': tr('Stable (no significant change)'),
    'prod_traj_signif_inc_90': tr('Stable (significant increase, p < .1)'),
    'prod_traj_signif_inc_95': tr('Improvement (significant increase, p < .05)'),
    'prod_traj_signif_inc_99': tr('Improvement (significant increase, p < .01)'),

    # Productivity performance
    'prod_perf_deg_title': tr('Productivity performance degradation ({year_start} to {year_end})'),
    'prod_perf_deg_potential_deg': tr('Degradation'),
    'prod_perf_deg_not_potential_deg': tr('Not degradation'),

    'prod_perf_ratio_title': tr('Productivity performance ({year_start} to {year_end}, ratio)'),

    'prod_perf_units_title': tr('Productivity performance ({year_start}, units)'),

    # Productivity state
    'prod_state_change_title': tr('Productivity state degradation ({year_bl_start}-{year_bl_end} to {year_tg_start}-{year_tg_end})'),
    'prod_state_change_potential_deg': tr('Degradation'),
    'prod_state_change_stable': tr('Stable'),
    'prod_state_change_potential_improvement': tr('Improvement'),

    'prod_state_classes_title': tr('Productivity state classes ({year_start}-{year_end})'),

    # Land cover
    'lc_deg_title': tr('Land cover degradation ({year_baseline} to {year_target})'),
    'lc_deg_deg': tr('Degradation'),
    'lc_deg_stable': tr('Stable'),
    'lc_deg_imp': tr('Improvement'),

    'lc_7class_title': tr('Land cover ({year}, 7 class)'),
    'lc_esa_title': tr('Land cover ({year}, ESA CCI classes)'),
    'lc_7class_mode_title': tr('Land cover mode ({year_start}-{year_end}, 7 class)'),
    'lc_esa_mode_title': tr('Land cover mode ({year_start}-{year_end}, ESA CCI classes)'),

    'lc_class_nodata': tr('-32768 - No data'),
    'lc_class_forest': tr('1 - Tree-covered'),
    'lc_class_grassland': tr('2 - Grassland'),
    'lc_class_cropland': tr('3 - Cropland'),
    'lc_class_wetland': tr('4 - Wetland'),
    'lc_class_artificial': tr('5 - Artificial'),
    'lc_class_bare': tr('6 - Other land'),
    'lc_class_water': tr('7 - Water body'),

    'lc_tr_title': tr('Land cover (transitions, {year_baseline} to {year_target})'),
    'lc_tr_nochange': tr('No change'),
    'lc_tr_forest_loss': tr('Tree-covered loss'),
    'lc_tr_grassland_loss': tr('Grassland loss'),
    'lc_tr_cropland_loss': tr('Cropland loss'),
    'lc_tr_wetland_loss': tr('Wetland loss'),
    'lc_tr_artificial_loss': tr('Artificial loss'),
    'lc_tr_bare_loss': tr('Other land loss'),
    'lc_tr_water_loss': tr('Water body loss'),

    # Soil organic carbon
    'soc_title': tr('Soil organic carbon ({year}, tons / ha)'),

    'soc_deg_title': tr('Soil organic carbon degradation ({year_start} to {year_end})'),
    'soc_deg_deg': tr('Degradation'),
    'soc_deg_stable': tr('Stable'),
    'soc_deg_imp': tr('Improvement'),

    # Trends.Earth land productivity
    'sdg_prod_combined_title': tr('Land productivity (Trends.Earth)'),
    'sdg_prod_combined_declining': tr('Declining'),
    'sdg_prod_combined_earlysigns': tr('Early signs of decline'),
    'sdg_prod_combined_stabbutstress': tr('Stable but stressed'),
    'sdg_prod_combined_stab': tr('Stable'),
    'sdg_prod_combined_imp': tr('Increasing'),

    # LPD
    'lpd_title': tr('Land productivity dynamics (LPD)'),
    'lpd_declining': tr('Declining'),
    'lpd_earlysigns': tr('Moderate decline'),
    'lpd_stabbutstress': tr('Stressed'),
    'lpd_stab': tr('Stable'),
    'lpd_imp': tr('Increasing'),

    # SDG 15.3.1 indicator layer
    'combined_sdg_title': tr('SDG 15.3.1 degradation indicator'),
    'combined_sdg_deg_deg': tr('Degradation'),
    'combined_sdg_deg_stable': tr('Stable'),
    'combined_sdg_deg_imp': tr('Improvement'),

    # Forest loss
    'f_loss_hansen_title': tr('Forest loss ({year_start} to {year_end})'),
    'f_loss_hansen_water': tr('Water'),
    'f_loss_hansen_nonforest': tr('Non-forest'),
    'f_loss_hansen_noloss': tr('Forest (no loss)'),
    'f_loss_hansen_year_start': tr('Forest loss ({year_start})'),
    'f_loss_hansen_year_end': tr('Forest loss ({year_end})'),

    # Total carbon
    'tc_title': tr('Total carbon ({year_start}, tonnes per ha x 10)'),

    # Root shoot ratio (below to above ground carbon in woody biomass)
    'root_shoot_title': tr('Root/shoot ratio (x 100)'),

    # Urban area series
    'urban_series_title': tr('Urban area change'),
    'urban_series_water': tr('Water'),
    'urban_series_built_up_by_2000': tr('Built-up by 2000'),
    'urban_series_built_up_by_2005': tr('Built-up by 2005'),
    'urban_series_built_up_by_2010': tr('Built-up by 2010'),
    'urban_series_built_up_by_2015': tr('Built-up by 2015'),

    # Urban area
    'urban_title': tr('Urban area {year}'),
    'urban_urban': tr('Urban'),
    'urban_suburban': tr('Suburban'),
    'urban_built_up_rural': tr('Built-up rural'),
    'urban_fringe_open_space': tr('Open space (fringe)'),
    'urban_captured_open_space': tr('Open space (captured)'),
    'urban_rural_open_space': tr('Open space (rural)'),
    'urban_fringe_open_space_water': tr('Open space (fringe, water)'),
    'urban_captured_open_space_water': tr('Open space (captured, water)'),
    'urban_rural_open_space_water': tr('Open space (rural, water)'),

    # Population
    'population_title': tr('Population ({year})')
}


with open(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                       'data', 'styles.json')) as script_file:
    styles = json.load(script_file)


def round_to_n(x, sf=3):
    'Function to round a positive value to n significant figures'
    if np.isnan(x):
        return x
    elif x == 0:
        return 0
    else:
        return round(x, -int(floor(log10(x))) + (sf - 1))


def get_sample(f, band_number, n=1e6):
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
    if (n > xsize * ysize) or ((grid_size * grid_size) > (xsize * ysize)):
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


def get_cutoff(f, band_number, band_info, percentiles):
    if len(percentiles) != 1 and len(percentiles) != 2:
        raise ValueError("Percentiles must have length 1 or 2. Percentiles that were passed: {}".format(percentiles))
    d = get_sample(f, band_number)
    md = np.ma.masked_where(d == band_info['no_data_value'], d)
    if md.size == 0:
        # If all of the values are no data, return 0
        log('All values are no data')
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


def get_file_metadata(json_file):
    try:
        with open(json_file) as f:
            d = json.load(f)
    except (OSError, IOError, ValueError) as e:
        log(u'Error loading {}'.format(json_file))
        return None

    local_raster_schema = LocalRasterSchema()

    try:
        d = local_raster_schema.load(d)
    except ValidationError:
        log(u'Unable to parse {}'.format(json_file))
        return None

    # Below is a fix for older versions of LDMP<0.43 that stored the full path 
    # in the metadata
    f = os.path.join(os.path.dirname(json_file),
                     os.path.basename(os.path.normpath(d['file'])))
    if not os.access(f, os.R_OK):
        log(u'Data file {} is missing'.format(f))
        return None
    else:
        return d


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    raise TypeError("Type {} not serializable".format(type(obj)))


def create_local_json_metadata(json_file, data_file, bands, metadata={}):
    out = LocalRaster(os.path.basename(os.path.normpath(data_file)), bands, metadata)
    local_raster_schema = LocalRasterSchema()
    with open(json_file, 'w') as f:
        json.dump(local_raster_schema.dump(out), f, default=json_serial, 
                  sort_keys=True, indent=4, separators=(',', ': '))


def add_layer(f, band_number, band_info, activated='default'):
    try:
        style = styles[band_info['name']]
    except KeyError:
        QtGui.QMessageBox.information(None,
                                      tr("Information"),
                                      tr(u'Trends.Earth does not have a style assigned for "{}" in {}. To use this layer, manually add it to your map.'.format(styles[band_info['name']], f)))
        log(u'No style found for "{}" in {}'.format(band_info['name'], f))
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
    elif style['ramp']['type'] == 'categorical with dynamic ramp':
        r = []
        for item in style['ramp']['items']:
            r.append(QgsColorRampShader.ColorRampItem(item['value'],
                                                      QtGui.QColor(item['color']),
                                                      tr_style_text(item['label'])))
        # Now add in the continuous ramp with min/max values and labels 
        # determined from the band info min/max
        r.append(QgsColorRampShader.ColorRampItem(band_info['metadata']['ramp_min'],
                                                  QtGui.QColor(style['ramp']['ramp min']['color']),
                                                  tr_style_text(style['ramp']['ramp min']['label'], band_info)))
        r.append(QgsColorRampShader.ColorRampItem(band_info['metadata']['ramp_max'],
                                                  QtGui.QColor(style['ramp']['ramp max']['color']),
                                                  tr_style_text(style['ramp']['ramp max']['label'], band_info)))

    elif style['ramp']['type'] == 'zero-centered stretch':
        # Set a colormap centred on zero, going to the max of the min and max 
        # extreme value significant to three figures.
        cutoff = get_cutoff(f, band_number, band_info, [style['ramp']['percent stretch'], 100 - style['ramp']['percent stretch']])
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
        cutoff = get_cutoff(f, band_number, band_info, [100 - style['ramp']['percent stretch']])
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
        log('Failed to load Trends.Earth style.')
        QtGui.QMessageBox.critical(None,
                                   tr("Error"),
                                   tr(u"Failed to load Trends.Earth style. To use this layer, try manually adding it to your map.".format(f)))
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
                                                      band_number,
                                                      shader)
    l.setRenderer(pseudoRenderer)
    l.triggerRepaint()
    if activated == 'default':
        if band_info.has_key('activated') and not band_info['activated']:
            iface.legendInterface().setLayerVisible(l, False)
    elif activated:
        # The layer is visible by default, so if activated is true, don't need 
        # to change anything in order to make it visible
        pass
    elif not activated:
        iface.legendInterface().setLayerVisible(l, False)
    iface.legendInterface().refreshLayerSymbology(l)

    return True


def tr_style_text(label, band_info=None):
    """If no translation is available, use the original label"""
    val = style_text_dict.get(label, None)
    if val:
        if band_info:
            return val.format(**band_info['metadata'])
        else:
            return val
    else:
        log(u'"{}" not found in translation dictionary'.format(label))
        if isinstance(label, basestring):
            return label
        else:
            return str(label)


def get_band_infos(data_file):
    json_file = os.path.splitext(data_file)[0] + '.json'
    m = get_file_metadata(json_file)
    if m:
        return m['bands']
    else:
        return None


def get_band_title(band_info):
    style = styles.get(band_info['name'], None)
    if style:
        return tr_style_text(style['title']).format(**band_info['metadata'])
    else:
        return band_info['name']
