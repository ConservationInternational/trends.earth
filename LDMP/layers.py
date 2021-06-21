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

from builtins import str
from builtins import range
import typing
import os
import json
from operator import attrgetter
from pathlib import Path
from math import floor, log10

from qgis.core import (
    QgsColorRampShader,
    QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
    QgsRasterLayer,
    QgsProject
)
from qgis.utils import iface
mb = iface.messageBar()

from osgeo import gdal

import numpy as np

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtCore import QCoreApplication

from .logger import log



class tr_layers(object):
    def tr(message):
        return QCoreApplication.translate("tr_layers", message)


# Store layer titles and label text in a dictionary here so that it can be
# translated - if it were in the syles JSON then gettext would not have access
# to these strings.
style_text_dict = {
    # Shared
    'nodata': tr_layers.tr(u'No data'),

    # Productivity trajectory
    'prod_traj_trend_title': tr_layers.tr(u'Productivity trajectory ({year_start} to {year_end}, NDVI x 10000 / yr)'),

    'prod_traj_signif_title': tr_layers.tr(u'Productivity trajectory degradation ({year_start} to {year_end})'),
    'prod_traj_signif_dec_95': tr_layers.tr(u'Degradation (significant decrease, p < .05)'),
    'prod_traj_signif_zero': tr_layers.tr(u'Stable (no significant change)'),
    'prod_traj_signif_inc_95': tr_layers.tr(u'Improvement (significant increase, p < .05)'),

    # Productivity performance
    'prod_perf_deg_title': tr_layers.tr(u'Productivity performance degradation ({year_start} to {year_end})'),
    'prod_perf_deg_potential_deg': tr_layers.tr(u'Degradation'),
    'prod_perf_deg_not_potential_deg': tr_layers.tr(u'Not degradation'),

    'prod_perf_ratio_title': tr_layers.tr(u'Productivity performance ({year_start} to {year_end}, ratio)'),

    'prod_perf_units_title': tr_layers.tr(u'Productivity performance ({year_start}, units)'),

    # Productivity state
    'prod_state_change_title': tr_layers.tr(u'Productivity state degradation ({year_bl_start}-{year_bl_end} vs {year_tg_start}-{year_tg_end})'),
    'prod_state_change_potential_deg': tr_layers.tr(u'Degradation'),
    'prod_state_change_stable': tr_layers.tr(u'Stable'),
    'prod_state_change_potential_improvement': tr_layers.tr(u'Improvement'),

    'prod_state_classes_title': tr_layers.tr(u'Productivity state classes ({year_start}-{year_end})'),

    # Land cover
    'lc_deg_title': tr_layers.tr(u'Land cover degradation ({year_baseline} to {year_target})'),
    'lc_deg_deg': tr_layers.tr(u'Degradation'),
    'lc_deg_stable': tr_layers.tr(u'Stable'),
    'lc_deg_imp': tr_layers.tr(u'Improvement'),

    'lc_7class_title': tr_layers.tr(u'Land cover ({year}, 7 class)'),
    'lc_esa_title': tr_layers.tr(u'Land cover ({year}, ESA CCI classes)'),
    'lc_7class_mode_title': tr_layers.tr(u'Land cover mode ({year_start}-{year_end}, 7 class)'),
    'lc_esa_mode_title': tr_layers.tr(u'Land cover mode ({year_start}-{year_end}, ESA CCI classes)'),

    'lc_class_nodata': tr_layers.tr(u'-32768 - No data'),
    'lc_class_forest': tr_layers.tr(u'1 - Tree-covered'),
    'lc_class_grassland': tr_layers.tr(u'2 - Grassland'),
    'lc_class_cropland': tr_layers.tr(u'3 - Cropland'),
    'lc_class_wetland': tr_layers.tr(u'4 - Wetland'),
    'lc_class_artificial': tr_layers.tr(u'5 - Artificial'),
    'lc_class_bare': tr_layers.tr(u'6 - Other land'),
    'lc_class_water': tr_layers.tr(u'7 - Water body'),

    # Below are so that layer names will translate for the dialog that shows 
    # how to aggregate from ESA to IPCC classes
    'No data': tr_layers.tr(u'No data'),
    'Tree-covered': tr_layers.tr(u'Tree-covered'),
    'Grassland': tr_layers.tr(u'Grassland'),
    'Cropland': tr_layers.tr(u'Cropland'),
    'Wetland': tr_layers.tr(u'Wetland'),
    'Artificial': tr_layers.tr(u'Artificial'),
    'Other land': tr_layers.tr(u'Other land'),
    'Water body': tr_layers.tr(u'Water body'),

    'lc_tr_title': tr_layers.tr(u'Land cover (transitions, {year_baseline} to {year_target})'),
    'lc_tr_nochange': tr_layers.tr(u'No change'),
    'lc_tr_forest_loss': tr_layers.tr(u'Tree-covered loss'),
    'lc_tr_grassland_loss': tr_layers.tr(u'Grassland loss'),
    'lc_tr_cropland_loss': tr_layers.tr(u'Cropland loss'),
    'lc_tr_wetland_loss': tr_layers.tr(u'Wetland loss'),
    'lc_tr_artificial_loss': tr_layers.tr(u'Artificial loss'),
    'lc_tr_bare_loss': tr_layers.tr(u'Other land loss'),
    'lc_tr_water_loss': tr_layers.tr(u'Water body loss'),

    # Soil organic carbon
    'soc_title': tr_layers.tr(u'Soil organic carbon ({year}, tons / ha)'),

    'soc_deg_title': tr_layers.tr(u'Soil organic carbon degradation ({year_start} to {year_end})'),
    'soc_deg_deg': tr_layers.tr(u'Degradation'),
    'soc_deg_stable': tr_layers.tr(u'Stable'),
    'soc_deg_imp': tr_layers.tr(u'Improvement'),

    # Trends.Earth land productivity
    'sdg_prod_combined_title': tr_layers.tr(u'Land productivity (Trends.Earth)'),
    'sdg_prod_combined_declining': tr_layers.tr(u'Declining'),
    'sdg_prod_combined_earlysigns': tr_layers.tr(u'Early signs of decline'),
    'sdg_prod_combined_stabbutstress': tr_layers.tr(u'Stable but stressed'),
    'sdg_prod_combined_stab': tr_layers.tr(u'Stable'),
    'sdg_prod_combined_imp': tr_layers.tr(u'Increasing'),

    # LPD
    'lpd_title': tr_layers.tr(u'Land productivity dynamics (LPD)'),
    'lpd_declining': tr_layers.tr(u'Declining'),
    'lpd_earlysigns': tr_layers.tr(u'Moderate decline'),
    'lpd_stabbutstress': tr_layers.tr(u'Stressed'),
    'lpd_stab': tr_layers.tr(u'Stable'),
    'lpd_imp': tr_layers.tr(u'Increasing'),

    # SDG 15.3.1 indicator layer
    'combined_sdg_title': tr_layers.tr(u'SDG 15.3.1 Indicator (Trends.Earth)'),
    'combined_sdg_deg_deg': tr_layers.tr(u'Degradation'),
    'combined_sdg_deg_stable': tr_layers.tr(u'Stable'),
    'combined_sdg_deg_imp': tr_layers.tr(u'Improvement'),

    # Forest loss
    'f_loss_hansen_title': tr_layers.tr(u'Forest loss ({year_start} to {year_end})'),
    'f_loss_hansen_water': tr_layers.tr(u'Water'),
    'f_loss_hansen_nonforest': tr_layers.tr(u'Non-forest'),
    'f_loss_hansen_noloss': tr_layers.tr(u'Forest (no loss)'),
    'f_loss_hansen_year_start': tr_layers.tr(u'Forest loss ({year_start})'),
    'f_loss_hansen_year_end': tr_layers.tr(u'Forest loss ({year_end})'),

    # Total carbon
    'tc_title': tr_layers.tr(u'Total carbon ({year_start}, tonnes per ha x 10)'),

    # Root shoot ratio (below to above ground carbon in woody biomass)
    'root_shoot_title': tr_layers.tr(u'Root/shoot ratio (x 100)'),

    # Urban area series
    'urban_series_title': tr_layers.tr(u'Urban area change'),
    'urban_series_water': tr_layers.tr(u'Water'),
    'urban_series_built_up_by_2000': tr_layers.tr(u'Built-up by 2000'),
    'urban_series_built_up_by_2005': tr_layers.tr(u'Built-up by 2005'),
    'urban_series_built_up_by_2010': tr_layers.tr(u'Built-up by 2010'),
    'urban_series_built_up_by_2015': tr_layers.tr(u'Built-up by 2015'),

    # Urban area
    'urban_title': tr_layers.tr(u'Urban area {year}'),
    'urban_urban': tr_layers.tr(u'Urban'),
    'urban_suburban': tr_layers.tr(u'Suburban'),
    'urban_built_up_rural': tr_layers.tr(u'Built-up rural'),
    'urban_fringe_open_space': tr_layers.tr(u'Open space (fringe)'),
    'urban_captured_open_space': tr_layers.tr(u'Open space (captured)'),
    'urban_rural_open_space': tr_layers.tr(u'Open space (rural)'),
    'urban_fringe_open_space_water': tr_layers.tr(u'Open space (fringe, water)'),
    'urban_captured_open_space_water': tr_layers.tr(u'Open space (captured, water)'),
    'urban_rural_open_space_water': tr_layers.tr(u'Open space (rural, water)'),

    # Population
    'population_title': tr_layers.tr(u'Population ({year})'),

    # Biomass
    'biomass_title': tr_layers.tr(u'Biomass (tonnes CO2e per ha, {year})'),
    'biomass_difference_title': tr_layers.tr(u'Change in biomass\n(tonnes CO2e per ha, {type} after {years} years)'),

    # Global Zoning
    'agro_eco_zones': tr_layers.tr('Agro Ecological Zones V3.0'),
    'climatic_zones': tr_layers.tr('Climatic Zones'),
    
    # Forest Cover
    'forest_cover_hansen': tr_layers.tr('Hansen'),

    # Evapotranspiration
    'mod16a2': tr_layers.tr('MOD16A2'),

    # Precipitation
    'chirps': tr_layers.tr('CHIRPS'),
    'gpcc_v7': tr_layers.tr('GPCC V7 (Global Precipitation Climatology Centre)'),
    'gpcp_v231': tr_layers.tr('GPCP v2.3 1 month (Global Precipitation Climatology Project)'),
    'persiann_cdr': tr_layers.tr('PERSIANN-CDR'),

    # Soil Moisture
    'era_1': tr_layers.tr('ERA I'),
    'merra_2': tr_layers.tr('MERRA 2'),

    # NDVI
    'mod13q1_annual': tr_layers.tr('MODIS (MOD13Q1, annual)'),
    'avhrr_gimms3_annual': tr_layers.tr('AVHRR (GIMMS3g.v1, annual)'),
    'mod13q1_16day': tr_layers.tr('MODIS (MOD13Q1, 16 day)'),
    
    # Soil Type
    'soil_grids_250_wrb': tr_layers.tr('Soil Grids 250'),
    'usda_soil_type': tr_layers.tr('USDA Soil Type'),
    
    # Soil Organic C
    'soil_grids_250_soc': tr_layers.tr('Soil Grids 250')
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
        if x.size == 1:
            return np.round(x, -int(floor(log10(x))) + (sf - 1))
        else:
            return np.around(x, -int(floor(log10(x))) + (sf - 1))


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

        out = np.zeros((rows.shape[0], cols.shape[0]), np.float32)
        log("Sampling from a ({}, {}) array to a {} array (grid size: {}, samples: {})".format(ysize, xsize, out.shape, grid_size, out.shape[0] * out.shape[1]))

        for n in range(rows.shape[0]):
            out[n, :] = b.ReadAsArray(0, int(rows[n]), xsize, 1)[:, cols]

        return out


def _get_cutoff(
        data_sample: np.ndarray,
        no_data_value: typing.Union[int, float],
        percentiles
):
    if len(percentiles) != 1 and len(percentiles) != 2:
        raise ValueError("Percentiles must have length 1 or 2. Percentiles that were passed: {}".format(percentiles))
    md = np.ma.masked_where(data_sample == no_data_value, data_sample)
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


def _create_categorical_color_ramp(style_config: typing.Dict):
    ramp_items = style_config["ramp"]["items"]
    result = []
    for item in ramp_items:
        result.append(
            QgsColorRampShader.ColorRampItem(
                item['value'],
                QColor(item['color']),
                tr_style_text(item['label'])
            )
        )
    return result


def _create_categorical_with_dynamic_ramp_color_ramp(
        style_config: typing.Dict, band_info):
    ramp_items = style_config["ramp"]["items"]
    result = []
    for item in ramp_items:
        result.append(
            QgsColorRampShader.ColorRampItem(
                item['value'],
                QColor(item['color']),
                tr_style_text(item['label'])
            )
        )
    # Now add in the continuous ramp with min/max values and labels
    # determined from the band info min/max
    result.append(
        QgsColorRampShader.ColorRampItem(
            band_info['metadata']['ramp_min'],
            QColor(style_config['ramp']['ramp min']['color']),
            tr_style_text(style_config['ramp']['ramp min']['label'], band_info)
        )
    )
    result.append(
        QgsColorRampShader.ColorRampItem(
            band_info['metadata']['ramp_max'],
            QColor(style_config['ramp']['ramp max']['color']),
            tr_style_text(style_config['ramp']['ramp max']['label'], band_info)
        )
    )
    return result


def _create_zero_centered_stretch_color_ramp(
        style_config: typing.Dict, data_sample, no_data_value):
    # Set a colormap centred on zero, going to the max of the min and max
    # extreme value significant to three figures.
    cutoff = _get_cutoff(
        data_sample,
        no_data_value,
        [
            style_config['ramp']['percent stretch'],
            100 - style_config['ramp']['percent stretch']
        ]
    )
    log('Cutoff for {} percent stretch: {}'.format(
        style_config['ramp']['percent stretch'], cutoff))
    result = [
        QgsColorRampShader.ColorRampItem(
            -cutoff,
            QColor(style_config['ramp']['min']['color']),
            '{}'.format(-cutoff)
        ),
        QgsColorRampShader.ColorRampItem(
            0,
            QColor(style_config['ramp']['zero']['color']),
            '0'
        ),
        QgsColorRampShader.ColorRampItem(
            cutoff,
            QColor(style_config['ramp']['max']['color']),
            '{}'.format(cutoff)
        ),
        QgsColorRampShader.ColorRampItem(
            style_config['ramp']['no data']['value'],
            QColor(style_config['ramp']['no data']['color']),
            tr_style_text(style_config['ramp']['no data']['label'])
        )
    ]
    return result


def _create_min_zero_stretch_color_ramp(style_config: typing.Dict, data_sample, no_data_value):
    # Set a colormap from zero to percent stretch significant to
    # three figures.
    cutoff = _get_cutoff(
        data_sample,
        no_data_value,
        [100 - style_config['ramp']['percent stretch']]
    )
    log('Cutoff for min zero max {} percent stretch: {}'.format(
        100 - style_config['ramp']['percent stretch'], cutoff))
    result = [
        QgsColorRampShader.ColorRampItem(
            0,
            QColor(style_config['ramp']['zero']['color']),
            '0'
        )
    ]
    if 'mid' in style_config['ramp']:
        result.append(
            QgsColorRampShader.ColorRampItem(
                cutoff / 2,
                QColor(style_config['ramp']['mid']['color']),
                str(cutoff / 2)
            )
        )
    result.append(
        QgsColorRampShader.ColorRampItem(
            cutoff,
            QColor(style_config['ramp']['max']['color']),
            '{}'.format(cutoff)
        )
    )
    result.append(
        QgsColorRampShader.ColorRampItem(
            style_config['ramp']['no data']['value'],
            QColor(style_config['ramp']['no data']['color']),
            tr_style_text(style_config['ramp']['no data']['label'])
        )
    )
    return result


def _create_color_ramp(
        layer_path: str,
        band_number: int,
        style_config: typing.Dict,
        band_info: typing.Dict,
):
    ramp_type = style_config["ramp"]["type"]
    if ramp_type == 'categorical':
        result = _create_categorical_color_ramp(style_config)
    elif ramp_type == 'categorical with dynamic ramp':
        result = _create_categorical_with_dynamic_ramp_color_ramp(style_config, band_info)
    elif ramp_type == 'zero-centered stretch':
        # Set a colormap centred on zero, going to the max of the min and max
        # extreme value significant to three figures.
        data_sample = get_sample(layer_path, band_number)
        result = _create_zero_centered_stretch_color_ramp(
            style_config, data_sample, band_info["no_data_value"])
    elif ramp_type == 'min zero stretch':
        # Set a colormap from zero to percent stretch significant to
        # three figures.
        data_sample = get_sample(layer_path, band_number)
        result = _create_min_zero_stretch_color_ramp(
            style_config, data_sample, band_info["no_data_value"])
    else:
        raise RuntimeError("Failed to load Trends.Earth style.")
    return result


def add_layer(
        layer_path: str,
        band_number: int,
        band_info: typing.Dict,
        activated: str ='default'
):
    try:
        style = styles[band_info['name']]
    except KeyError:
        QtWidgets.QMessageBox.information(
            None,
            tr_layers.tr("Information"),
            tr_layers.tr(
                u'Trends.Earth does not have a style assigned for "{}" (band {} '
                u'in {}). To use this layer, manually add it to your map.'.format(
                    band_info['name'], band_number, layer_path)
            )
        )
        log(u'No style found for "{}" in {}'.format(band_info['name'], band_number, layer_path))
        return False

    title = get_band_title(band_info)
    layer = iface.addRasterLayer(layer_path, title)
    if not layer.isValid():
        log('Failed to add layer')
        return False
    try:
        color_ramp = _create_color_ramp(layer_path, band_number, style, band_info)
        log(f"color_ramp: {color_ramp}")
        log(f"color_ramp is None: {color_ramp is None}")
    except RuntimeError as exc:
        log(f"Could not create color ramp: {str(exc)}")
        return False
    else:
        fcn = QgsColorRampShader()
        ramp_shader = style["ramp"]["shader"]
        if ramp_shader == 'exact':
            fcn.setColorRampType("EXACT")
        elif ramp_shader == 'discrete':
            fcn.setColorRampType("DISCRETE")
        elif ramp_shader == 'interpolated':
            fcn.setColorRampType("INTERPOLATED")
        else:
            raise TypeError("Unrecognized color ramp type: {}".format(ramp_shader))
        # Make sure the items in the color ramp are sorted by value (weird display
        # errors will otherwise result)
        color_ramp.sort(key=attrgetter('value'))
        fcn.setColorRampItemList(color_ramp)
        shader = QgsRasterShader()
        shader.setRasterShaderFunction(fcn)
        renderer = QgsSingleBandPseudoColorRenderer(
            layer.dataProvider(), band_number, shader)
        layer.setRenderer(renderer)
        layer.triggerRepaint()
        if activated == 'default':
            if 'activated' in band_info and not band_info['activated']:
                QgsProject.instance().layerTreeRoot().findLayer(layer.id()).setItemVisibilityChecked(False)
        elif activated:
            # The layer is visible by default, so if activated is true, don't need
            # to change anything in order to make it visible
            pass
        elif not activated:
            QgsProject.instance().layerTreeRoot().findLayer(layer.id()).setItemVisibilityChecked(False)
        iface.layerTreeView().refreshLayerSymbology(layer.id())
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
        if isinstance(label, str):
            return label
        else:
            return str(label)


def get_band_title(band_info):
    style = styles.get(band_info['name'], None)
    result = band_info["name"]
    if style:
        title_pattern = tr_style_text(style["title"])
        try:
            result = title_pattern.format(**band_info['metadata'])
        except KeyError as exc:
            log(
                f"Unable to find a proper name for this layer because of the following "
                f"exception: {str(exc)}"
            )
    return result



def find_loaded_layer_id(layer_path: Path) -> typing.Optional[str]:
    project = QgsProject.instance()
    for layer_id in project.mapLayers():
        layer = project.mapLayer(layer_id)
        layer_source = os.path.abspath(layer.source())
        if layer_source == str(layer_path):
            result = layer_id
            break
    else:
        result = None
    return result


def delete_layer_by_filename(f: str) -> bool:
    path = Path(os.path.abspath(f))
    project = QgsProject.instance()
    layer_id = find_loaded_layer_id(path)
    if layer_id is not None:
        project.removeMapLayer(layer_id)
    else:
        log(f"Path {path} is not currently loaded on QGIS")
    result = False
    try:
        path.unlink()
        result = True
    except FileNotFoundError:  # file already deleted
        pass
    return result
