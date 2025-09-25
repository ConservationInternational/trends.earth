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

import json
import math
import os
import re
import typing
from math import floor, log10
from operator import attrgetter
from pathlib import Path

import numpy as np
from osgeo import gdal
from qgis.core import (
    Qgis,
    QgsColorRampShader,
    QgsDefaultValue,
    QgsProcessingFeedback,
    QgsProject,
    QgsProviderRegistry,
    QgsProviderSublayerDetails,
    QgsRasterLayer,
    QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
    QgsVectorLayer,
)
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QColor
from qgis.utils import iface
from te_schemas.land_cover import LCLegendNesting

from .logger import log


class tr_layers:
    def tr(message):
        return QCoreApplication.translate("tr_layers", message)


# Store layer titles and label text in a dictionary here so that it can be
# translated - if it were in the syles JSON then gettext would not have access
# to these strings.
style_text_dict = {
    # Shared
    "nodata": tr_layers.tr("No data"),
    # Land productivity trend
    "prod_traj_trend_title": tr_layers.tr(
        "Land productivity trend ({year_initial} to {year_final}, NDVI x 10000 / yr)"
    ),
    "prod_traj_signif_title": tr_layers.tr(
        "Land productivity trend degradation ({year_initial} to {year_final})"
    ),
    "prod_traj_signif_dec_95": tr_layers.tr(
        "Degradation (significant decrease, p < .05)"
    ),
    "prod_traj_signif_zero": tr_layers.tr("Stable (no significant change)"),
    "prod_traj_signif_inc_95": tr_layers.tr(
        "Improvement (significant increase, p < .05)"
    ),
    # Land productivity performance
    "prod_perf_deg_title": tr_layers.tr(
        "Land productivity performance degradation ({year_initial} to {year_final})"
    ),
    "prod_perf_deg_potential_deg": tr_layers.tr("Degradation"),
    "prod_perf_deg_not_potential_deg": tr_layers.tr("Not degradation"),
    "prod_perf_ratio_title": tr_layers.tr(
        "Land productivity performance ({year_initial} to {year_final}, ratio)"
    ),
    "prod_perf_units_title": tr_layers.tr(
        "Land productivity performance ({year_initial}, units)"
    ),
    # Land productivity state
    "prod_state_change_title": tr_layers.tr(
        "Land productivity state degradation ({year_bl_start}-{year_bl_end} vs {year_tg_start}-{year_tg_end})"
    ),
    "prod_state_change_potential_deg": tr_layers.tr("Degradation"),
    "prod_state_change_stable": tr_layers.tr("Stable"),
    "prod_state_change_potential_improvement": tr_layers.tr("Improvement"),
    "prod_state_classes_title": tr_layers.tr(
        "Land productivity state classes ({year_initial}-{year_final})"
    ),
    # Land productivity progress comparison (not the real progress taking into
    # account magnitude)
    "prod_deg_comp_title": tr_layers.tr(
        "Land productivity degradation comparison ({baseline_year_initial}-{baseline_year_final} vs {progress_year_initial}-{progress_year_final})"
    ),
    "prod_deg_comp_deg": tr_layers.tr("Degradation"),
    "prod_deg_comp_stable": tr_layers.tr("Stable"),
    "prod_deg_comp_imp": tr_layers.tr("Improvement"),
    # Land cover degradation comparison (not the real progress taking into
    # account magnitude)
    "lc_deg_comp_title": tr_layers.tr(
        "Land cover degradation comparison ({baseline_year_initial}-{baseline_year_final} vs {progress_year_initial}-{progress_year_final})"
    ),
    "lc_deg_comp_deg": tr_layers.tr("Degradation"),
    "lc_deg_comp_stable": tr_layers.tr("Stable"),
    "lc_deg_comp_imp": tr_layers.tr("Improvement"),
    # Land cover
    "lc_deg_title": tr_layers.tr(
        "Land cover degradation ({year_initial} to {year_final})"
    ),
    "lc_deg_deg": tr_layers.tr("Degradation"),
    "lc_deg_stable": tr_layers.tr("Stable"),
    "lc_deg_imp": tr_layers.tr("Improvement"),
    "lc_title": tr_layers.tr("Land cover ({year})"),
    "lc_7class_title": tr_layers.tr("Land cover ({year}, 7 class)"),
    "lc_esa_title": tr_layers.tr("Land cover ({year}, ESA CCI classes)"),
    "lc_7class_mode_title": tr_layers.tr(
        "Land cover mode ({year_initial}-{year_final}, 7 class)"
    ),
    "lc_esa_mode_title": tr_layers.tr(
        "Land cover mode ({year_initial}-{year_final}, ESA CCI classes)"
    ),
    "lc_class_nodata": tr_layers.tr("-32768 - No data"),
    "lc_class_forest": tr_layers.tr("1 - Tree-covered"),
    "lc_class_grassland": tr_layers.tr("2 - Grassland"),
    "lc_class_cropland": tr_layers.tr("3 - Cropland"),
    "lc_class_wetland": tr_layers.tr("4 - Wetland"),
    "lc_class_artificial": tr_layers.tr("5 - Artificial"),
    "lc_class_bare": tr_layers.tr("6 - Other land"),
    "lc_class_water": tr_layers.tr("7 - Water body"),
    # Below are so that layer names will translate for the dialog that shows
    # how to aggregate from ESA to IPCC classes
    "No data": tr_layers.tr("No data"),
    "Tree-covered": tr_layers.tr("Tree-covered"),
    "Grassland": tr_layers.tr("Grassland"),
    "Cropland": tr_layers.tr("Cropland"),
    "Wetland": tr_layers.tr("Wetland"),
    "Artificial": tr_layers.tr("Artificial"),
    "Other land": tr_layers.tr("Other land"),
    "Water body": tr_layers.tr("Water body"),
    "lc_tr_title": tr_layers.tr(
        "Land cover (transitions, {year_initial} to {year_final})"
    ),
    "lc_tr_nochange": tr_layers.tr("No change"),
    "lc_tr_forest_loss": tr_layers.tr("Tree-covered loss"),
    "lc_tr_grassland_loss": tr_layers.tr("Grassland loss"),
    "lc_tr_cropland_loss": tr_layers.tr("Cropland loss"),
    "lc_tr_wetland_loss": tr_layers.tr("Wetland loss"),
    "lc_tr_artificial_loss": tr_layers.tr("Artificial loss"),
    "lc_tr_bare_loss": tr_layers.tr("Other land loss"),
    "lc_tr_water_loss": tr_layers.tr("Water body loss"),
    # Soil organic carbon
    "soc_title": tr_layers.tr("Soil organic carbon ({year}, tons / ha)"),
    "soc_deg_title": tr_layers.tr(
        "Soil organic carbon degradation ({year_initial} to {year_final})"
    ),
    "soc_deg_deg": tr_layers.tr("Degradation"),
    "soc_deg_stable": tr_layers.tr("Stable"),
    "soc_deg_imp": tr_layers.tr("Improvement"),
    # Trends.Earth land productivity
    "sdg_prod_combined_title": tr_layers.tr(
        "Land productivity (Trends.Earth, {year_initial}-{year_final})"
    ),
    "sdg_prod_combined_declining": tr_layers.tr("Declining"),
    "sdg_prod_combined_earlysigns": tr_layers.tr("Early signs of decline"),
    "sdg_prod_combined_stabbutstress": tr_layers.tr("Stable but stressed"),
    "sdg_prod_combined_stab": tr_layers.tr("Stable"),
    "sdg_prod_combined_imp": tr_layers.tr("Increasing"),
    # LPD
    "lpd_jrc_title": tr_layers.tr(
        "Land productivity dynamics (JRC, {year_initial}-{year_final})"
    ),
    "lpd_fao_wocat_title": tr_layers.tr(
        "Land productivity dynamics (FAO-WOCAT, {year_initial}-{year_final})"
    ),
    "lpd_fao_wocat": tr_layers.tr("Land productivity dynamics (from FAO-WOCAT)"),
    "lpd_from_fao_wocat": tr_layers.tr("Land Productivity Dynamics (from FAO-WOCAT)"),
    "lpd_declining": tr_layers.tr("Declining"),
    "lpd_earlysigns": tr_layers.tr("Moderate decline"),
    "lpd_stabbutstress": tr_layers.tr("Stable but stressed"),
    "lpd_stab": tr_layers.tr("Stable"),
    "lpd_imp": tr_layers.tr("Increasing"),
    # SDG Indicator 15.3.1 layer
    "combined_sdg_title": tr_layers.tr(
        "SDG Indicator 15.3.1 ({year_initial}-{year_final})"
    ),
    "combined_sdg_deg_deg": tr_layers.tr("Degradation"),
    "combined_sdg_deg_stable": tr_layers.tr("Stable"),
    "combined_sdg_deg_imp": tr_layers.tr("Improvement"),
    "status_sdg_title": tr_layers.tr(
        "SDG Indicator 15.3.1 (status, {reporting_year_initial}-{reporting_year_final} relative to {baseline_year_initial}-{baseline_year_final})"
    ),
    "status_prod_title": tr_layers.tr(
        "Land productivity degradation (status, {reporting_year_initial}-{reporting_year_final} relative to {baseline_year_initial}-{baseline_year_final})"
    ),
    "status_lc_title": tr_layers.tr(
        "Land cover degradation (status, {reporting_year_initial}-{reporting_year_final} relative to {baseline_year_initial}-{baseline_year_final})"
    ),
    "status_soc_title": tr_layers.tr(
        "Soil organic carbon degradation (status, {reporting_year_initial}-{reporting_year_final} relative to {baseline_year_initial}-{baseline_year_final})"
    ),
    "status_sdg_deg_persistent": tr_layers.tr("Degradation (persistent)"),
    "status_sdg_deg_recent": tr_layers.tr("Degradation (recent)"),
    "status_sdg_deg_baseline": tr_layers.tr("Degradation (baseline)"),
    "status_sdg_stability": tr_layers.tr("Stability"),
    "status_sdg_imp_baseline": tr_layers.tr("Improvement (baseline)"),
    "status_sdg_imp_recent": tr_layers.tr("Improvement (recent)"),
    "status_sdg_imp_persistent": tr_layers.tr("Improvement (persistent)"),
    "sdg_progress_title": tr_layers.tr(
        "SDG 15.3.1 Progress ({baseline_year_initial}-{baseline_year_final} vs {progress_year_initial}-{progress_year_final})"
    ),
    # Forest loss
    "f_loss_hansen_title": tr_layers.tr("Forest loss ({year_initial} to {year_final})"),
    "f_loss_hansen_water": tr_layers.tr("Water"),
    "f_loss_hansen_nonforest": tr_layers.tr("Non-forest"),
    "f_loss_hansen_noloss": tr_layers.tr("Forest (no loss)"),
    "f_loss_hansen_year_start": tr_layers.tr("Forest loss ({year_initial})"),
    "f_loss_hansen_year_end": tr_layers.tr("Forest loss ({year_final})"),
    # Total carbon
    "tc_title": tr_layers.tr("Total carbon ({year_initial}, tonnes per ha x 10)"),
    # Root shoot ratio (below to above ground carbon in woody biomass)
    "root_shoot_title": tr_layers.tr("Root/shoot ratio (x 100)"),
    # Urban area series
    "urban_series_title": tr_layers.tr("Urban area change"),
    "urban_series_water": tr_layers.tr("Water"),
    "urban_series_built_up_by_2000": tr_layers.tr("Built-up by 2000"),
    "urban_series_built_up_by_2005": tr_layers.tr("Built-up by 2005"),
    "urban_series_built_up_by_2010": tr_layers.tr("Built-up by 2010"),
    "urban_series_built_up_by_2015": tr_layers.tr("Built-up by 2015"),
    # Urban area
    "urban_title": tr_layers.tr("Urban area {year}"),
    "urban_urban": tr_layers.tr("Urban"),
    "urban_suburban": tr_layers.tr("Suburban"),
    "urban_built_up_rural": tr_layers.tr("Built-up rural"),
    "urban_fringe_open_space": tr_layers.tr("Open space (fringe)"),
    "urban_captured_open_space": tr_layers.tr("Open space (captured)"),
    "urban_rural_open_space": tr_layers.tr("Open space (rural)"),
    "urban_fringe_open_space_water": tr_layers.tr("Open space (fringe, water)"),
    "urban_captured_open_space_water": tr_layers.tr("Open space (captured, water)"),
    "urban_rural_open_space_water": tr_layers.tr("Open space (rural, water)"),
    # Population titles
    "population_title": tr_layers.tr("Population ({year})"),
    "population_number_of_people": tr_layers.tr("Population ({type}, {year})"),
    "population_density_title": tr_layers.tr(
        "Population density ({year}, per sq km / 10)"
    ),
    "population_density_affected_by_degradation_title": tr_layers.tr(
        "Population exposed to degradation (population in {population_year}, per sq km / 10, degradation period {deg_year_initial}-{deg_year_final})"
    ),
    "population_affected_by_degradation_title": tr_layers.tr(
        "Population exposed to degradation ({type} population in {population_year}, degradation period {deg_year_initial}-{deg_year_final})"
    ),
    "population_density_at_maximum_drought_title": tr_layers.tr(
        "Population density at maximum drought (density per sq km / 10, {year_initial}-{year_final} period)"
    ),
    "population_at_maximum_drought_title": tr_layers.tr(
        "Population at maximum drought ({type}, {year_initial}-{year_final} period)"
    ),
    # SPI
    "spi_title": tr_layers.tr(
        "Standardized Precipitation Index (SPI, {year}, {lag} month lag, * 1000)"
    ),
    "spi_at_maximum_drought_title": tr_layers.tr(
        "SPI at maximum drought during {year_initial}-{year_final} ({lag} month lag, * 1000)"
    ),
    "jrc_drought_vulnerability_title": tr_layers.tr(
        "Drought Vulnerability (JRC, {year}, * 1000)"
    ),
    "spi_extreme_drought": tr_layers.tr("Extreme drought"),
    "spi_severe_drought": tr_layers.tr("Severe drought"),
    "spi_moderate_drought": tr_layers.tr("Moderate drought"),
    "spi_mild_drought": tr_layers.tr("Mild drought"),
    "spi_normal": tr_layers.tr("Normal"),
    "spi_mild_wet": tr_layers.tr("Mildly wet"),
    "spi_moderate_wet": tr_layers.tr("Moderately wet"),
    "spi_severe_wet": tr_layers.tr("Severely wet"),
    "spi_extreme_wet": tr_layers.tr("Extremely wet"),
    # Biomass
    "biomass_title": tr_layers.tr("Biomass (tonnes CO2e per ha, {year})"),
    "biomass_difference_title": tr_layers.tr(
        "Change in biomass (tonnes CO2e per ha, {type} after {years} years)"
    ),
    # Global Zoning
    "agro_eco_zones": tr_layers.tr("Agro Ecological Zones V3.0"),
    "climatic_zones": tr_layers.tr("Climatic Zones"),
    # Forest Cover
    "forest_cover_hansen": tr_layers.tr("Hansen"),
    # Evapotranspiration
    "mod16a2": tr_layers.tr("MOD16A2"),
    # Precipitation
    "chirps": tr_layers.tr("CHIRPS"),
    "gpcc_v7": tr_layers.tr("GPCC V7 (Global Precipitation Climatology Centre)"),
    "gpcp_v231": tr_layers.tr(
        "GPCP v2.3 1 month (Global Precipitation Climatology Project)"
    ),
    "persiann_cdr": tr_layers.tr("PERSIANN-CDR"),
    # Soil Moisture
    "era_1": tr_layers.tr("ERA I"),
    "merra_2": tr_layers.tr("MERRA 2"),
    # NDVI
    "mod13q1_annual": tr_layers.tr("MODIS (MOD13Q1, annual)"),
    "avhrr_gimms3_annual": tr_layers.tr("AVHRR (GIMMS3g.v1, annual)"),
    "mod13q1_16day": tr_layers.tr("MODIS (MOD13Q1, 16 day)"),
    # Soil Type
    "soil_grids_250_wrb": tr_layers.tr("Soil Grids 250"),
    "usda_soil_type": tr_layers.tr("USDA Soil Type"),
    # Soil Organic C
    "soil_grids_250_soc": tr_layers.tr("Soil Grids 250"),
}

with open(
    os.path.join(os.path.dirname(os.path.realpath(__file__)), "data", "styles.json")
) as style_file:
    styles = json.load(style_file)


def round_to_n(x, sf=3):
    "Function to round a positive value to n significant figures"

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
    """Get a gridded sample of a raster dataset"""
    ds = gdal.Open(f)
    b = ds.GetRasterBand(band_number)

    xsize = b.XSize
    ysize = b.YSize

    samp_frac = (n / (xsize * ysize)) * 2

    ratio = xsize / ysize
    ysize_new = math.ceil(math.sqrt(n / ratio))
    xsize_new = math.ceil(ysize_new * ratio)

    if (
        (n > xsize * ysize)
        or (samp_frac > 0.75)
        or (xsize_new > xsize)
        or (ysize_new > ysize)
    ):
        log(
            f"Skipping resampling from a ({xsize}, {ysize}) array "
            f"to a ({xsize_new}, {ysize_new}) array"
        )

        return b.ReadAsArray().astype(float)
    else:
        log(
            f"Resampling from a ({xsize}, {ysize}) array "
            f"to a ({xsize_new}, {ysize_new}) array"
        )
        log(
            "Resampling to "
            f"/vsimem/resample_{Path(f).with_suffix('.tif').name}, from {f}"
        )
        ds_resamp = gdal.Translate(
            f"/vsimem/{Path(f).with_suffix('.tif').name}",
            f,
            bandList=[band_number],
            width=xsize_new,
            height=ysize_new,
        )

        return ds_resamp.ReadAsArray().astype(float)


# def _set_statistics(
#     band_number: int,
#     no_data_value: typing.Union[int, float],
#     f: str,
# ):
#     ds = gdal.Open(f)
#     b = ds.GetRasterBand(band_number)
#     b.SetNoDataValue(no_data_value)
#     return b.GetStatistics(True, True)


def _get_cutoff(
    data_sample: np.ndarray,
    no_data_value: typing.Union[int, float],
    percentiles,
    mask_zeros=False,
):
    if len(percentiles) != 1 and len(percentiles) != 2:
        raise ValueError(
            "Percentiles must have length 1 or 2. Percentiles that were passed: {}".format(
                percentiles
            )
        )
    md = np.ma.masked_where(data_sample == no_data_value, data_sample)
    md = np.ma.masked_where(md == 0, md)

    if md.size == 0:
        # If all of the values are no data, return 0
        log("All values are no data")

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
            raise ValueError(
                "Stretch calculation returned cutoffs array of size {} ({})".format(
                    cutoffs.size, cutoffs
                )
            )


def create_categorical_color_ramp(ramp_items):
    result = []

    for item in ramp_items:
        result.append(
            QgsColorRampShader.ColorRampItem(
                item["value"], QColor(item["color"]), tr_style_text(item["label"])
            )
        )

    return result


def create_categorical_color_ramp_from_legend(nesting):
    nesting = LCLegendNesting.Schema().loads(nesting)
    return create_categorical_color_ramp(nesting.child.get_ramp_items())


def create_categorical_transitions_color_ramp_from_legend(nesting):
    nesting = LCLegendNesting.Schema().loads(nesting)
    return create_categorical_color_ramp(nesting.child.get_transitions_ramp_items())


def create_categorical_with_dynamic_ramp_color_ramp(style_config, band_info):
    ramp_items = style_config["ramp"]["items"]
    result = []

    for item in ramp_items:
        result.append(
            QgsColorRampShader.ColorRampItem(
                item["value"], QColor(item["color"]), tr_style_text(item["label"])
            )
        )
    # Now add in the continuous ramp with min/max values and labels
    # determined from the band info min/max
    result.append(
        QgsColorRampShader.ColorRampItem(
            band_info["metadata"]["ramp_min"],
            QColor(style_config["ramp"]["ramp min"]["color"]),
            tr_style_text(style_config["ramp"]["ramp min"]["label"], band_info),
        )
    )
    result.append(
        QgsColorRampShader.ColorRampItem(
            band_info["metadata"]["ramp_max"],
            QColor(style_config["ramp"]["ramp max"]["color"]),
            tr_style_text(style_config["ramp"]["ramp max"]["label"], band_info),
        )
    )

    return result


def _create_zero_centered_stretch_color_ramp(
    style_config: typing.Dict, data_sample, no_data_value
):
    # Set a colormap centred on zero, going to the max of the min and max
    # extreme value significant to three figures.
    cutoff = _get_cutoff(
        data_sample,
        no_data_value,
        [
            style_config["ramp"]["percent stretch"],
            100 - style_config["ramp"]["percent stretch"],
        ],
        mask_zeros=True,
    )
    log(
        "Cutoff for {} percent stretch: {}".format(
            style_config["ramp"]["percent stretch"], cutoff
        )
    )
    result = [
        QgsColorRampShader.ColorRampItem(
            -cutoff, QColor(style_config["ramp"]["min"]["color"]), "{}".format(-cutoff)
        ),
        QgsColorRampShader.ColorRampItem(
            0, QColor(style_config["ramp"]["zero"]["color"]), "0"
        ),
        QgsColorRampShader.ColorRampItem(
            cutoff, QColor(style_config["ramp"]["max"]["color"]), "{}".format(cutoff)
        ),
        QgsColorRampShader.ColorRampItem(
            style_config["ramp"]["no data"]["value"],
            QColor(style_config["ramp"]["no data"]["color"]),
            tr_style_text(style_config["ramp"]["no data"]["label"]),
        ),
    ]

    return result


def _create_min_zero_stretch_color_ramp(
    style_config: typing.Dict, data_sample, no_data_value
):
    # Set a colormap from zero to percent stretch significant to
    # three figures.
    cutoff = _get_cutoff(
        data_sample,
        no_data_value,
        [100 - style_config["ramp"]["percent stretch"]],
        mask_zeros=True,
    )
    log(
        "Cutoff for min zero max {} percent stretch: {}".format(
            100 - style_config["ramp"]["percent stretch"], cutoff
        )
    )
    result = [
        QgsColorRampShader.ColorRampItem(
            0, QColor(style_config["ramp"]["zero"]["color"]), "0"
        )
    ]

    if "mid" in style_config["ramp"]:
        result.append(
            QgsColorRampShader.ColorRampItem(
                cutoff / 2,
                QColor(style_config["ramp"]["mid"]["color"]),
                str(cutoff / 2),
            )
        )
    result.append(
        QgsColorRampShader.ColorRampItem(
            cutoff, QColor(style_config["ramp"]["max"]["color"]), "{}".format(cutoff)
        )
    )
    result.append(
        QgsColorRampShader.ColorRampItem(
            style_config["ramp"]["no data"]["value"],
            QColor(style_config["ramp"]["no data"]["color"]),
            tr_style_text(style_config["ramp"]["no data"]["label"]),
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

    if ramp_type == "categorical":
        result = create_categorical_color_ramp(style_config["ramp"]["items"])
    elif ramp_type == "categorical from legend":
        result = create_categorical_color_ramp_from_legend(
            band_info["metadata"]["nesting"]
        )
    elif ramp_type == "categorical transitions from legend":
        result = create_categorical_transitions_color_ramp_from_legend(
            band_info["metadata"]["nesting"]
        )
    elif ramp_type == "categorical with dynamic ramp":
        result = create_categorical_with_dynamic_ramp_color_ramp(
            style_config, band_info
        )
    elif ramp_type == "zero-centered stretch":
        # Set a colormap centred on zero, going to the max of the min and max
        # extreme value significant to three figures.
        data_sample = get_sample(layer_path, band_number)
        result = _create_zero_centered_stretch_color_ramp(
            style_config, data_sample, band_info["no_data_value"]
        )
    elif ramp_type == "min zero stretch":
        # Set a colormap from zero to percent stretch significant to
        # three figures.
        data_sample = get_sample(layer_path, band_number)
        result = _create_min_zero_stretch_color_ramp(
            style_config, data_sample, band_info["no_data_value"]
        )
    else:
        raise RuntimeError("Failed to load Trends.Earth style.")

    return result


def _get_qgis_version():
    qgis_version_match = re.match(r"(^[0-9]*)\.([0-9]*)", Qgis.QGIS_VERSION)

    return int(qgis_version_match[1]), int(qgis_version_match[2])


def add_layer(
    layer_path: str,
    band_number: int,
    band_info: typing.Dict,
    activated: str = "default",
):
    # You can use an existing raster layer and call this function for styling
    try:
        style = styles[band_info["name"]]
    except KeyError:
        QtWidgets.QMessageBox.information(
            None,
            tr_layers.tr("Information"),
            tr_layers.tr(
                'Trends.Earth does not have a style assigned for "{}" (band {} '
                "in {}). To use this layer, manually add it to your map.".format(
                    band_info["name"], band_number, layer_path
                )
            ),
        )
        log(
            'No style found for "{}" (band {} in {})'.format(
                band_info["name"], band_number, layer_path
            )
        )

        return False

    title = get_band_title(band_info)
    layer = iface.addRasterLayer(layer_path, title)
    # # Initialize statistics for this layer
    # _set_statistics(band_number, band_info["no_data_value"], layer_path)

    if not layer or not layer.isValid():
        log(f"Failed to add layer {layer_path}, band number {band_number}")

        return False

    return style_layer(layer_path, layer, band_number, style, band_info, activated)


def style_layer(
    layer_path: str,
    layer: QgsRasterLayer,
    band_number: int,
    style: typing.Dict,
    band_info: typing.Dict,
    activated: str = "default",
    in_process_alg: bool = False,
    processing_feedback: QgsProcessingFeedback = None,
) -> bool:
    """
    Styles a raster layer. Has been extracted from 'add_layer' so that
    styling can be performed in non-GUI operations i.e. in a
    processing algorithm.
    """
    try:
        color_ramp = _create_color_ramp(layer_path, band_number, style, band_info)
    except RuntimeError as exc:
        msg = f"Could not create color ramp: {str(exc)}"
        if in_process_alg and processing_feedback is not None:
            processing_feedback.pushConsoleInfo(msg)
        else:
            log(msg)

        return False

    else:
        fcn = QgsColorRampShader()
        ramp_shader = style["ramp"]["shader"]

        if ramp_shader == "exact":
            fcn.setColorRampType("EXACT")
        elif ramp_shader == "discrete":
            fcn.setColorRampType("DISCRETE")
        elif ramp_shader == "interpolated":
            fcn.setColorRampType("INTERPOLATED")
        else:
            msg = f"Unrecognized color ramp type: {ramp_shader}"
            if in_process_alg and processing_feedback is not None:
                processing_feedback.pushConsoleInfo(msg)
            else:
                raise TypeError(msg)

        # In QGIS 3.18 need to set legend settings
        v_major, v_minor = _get_qgis_version()

        if v_major >= 3 and v_minor >= 18:
            legend_settings = fcn.legendSettings()
            legend_settings.setUseContinuousLegend(False)

        # Make sure the items in the color ramp are sorted by value (weird
        # display errors will otherwise result)
        color_ramp.sort(key=attrgetter("value"))
        fcn.setColorRampItemList(color_ramp)
        shader = QgsRasterShader()
        shader.setRasterShaderFunction(fcn)
        renderer = QgsSingleBandPseudoColorRenderer(
            layer.dataProvider(), band_number, shader
        )
        layer.setRenderer(renderer)
        layer.triggerRepaint()

        if activated == "default":
            if "activated" in band_info and not band_info["activated"]:
                QgsProject.instance().layerTreeRoot().findLayer(
                    layer.id()
                ).setItemVisibilityChecked(False)
        elif activated:
            # The layer is visible by default, so if activated is true, don't need
            # to change anything in order to make it visible
            pass
        elif not activated:
            QgsProject.instance().layerTreeRoot().findLayer(
                layer.id()
            ).setItemVisibilityChecked(False)

        if not in_process_alg:
            iface.layerTreeView().refreshLayerSymbology(layer.id())

        return True


def tr_style_text(label, band_info=None):
    """If no translation is available, use the original label"""
    val = style_text_dict.get(label, None)

    if val:
        if band_info:
            return val.format(**band_info["metadata"])
        else:
            return val
    else:
        log('"{}" not found in translation dictionary'.format(label))

        if isinstance(label, str):
            return label
        else:
            return str(label)


def get_band_title(band_info):
    style = styles.get(band_info["name"], None)
    result = band_info["name"]

    if style:
        title_pattern = tr_style_text(style["title"])
        try:
            result = title_pattern.format(**band_info["metadata"])
        except KeyError as exc:
            log(
                f"Unable to find a proper name for {band_info['name']} because "
                f"of the following exception: {str(exc)}"
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


def add_vector_layer(layer_path: str, name: str) -> "QgsVectorLayer":
    sublayers = (
        QgsProviderRegistry.instance()
        .providerMetadata("ogr")
        .querySublayers(layer_path)
    )

    layer = None
    if len(sublayers) > 0:
        options = QgsProviderSublayerDetails.LayerOptions(
            QgsProject.instance().transformContext()
        )
        options.loadDefaultStyle = True
        layer = sublayers[0].toLayer(options)
        if layer.isValid():
            found = False
            layers = QgsProject.instance().mapLayers()
            for lyr in layers.values():
                if lyr.source().split("|")[0] == layer.source().split("|")[0]:
                    found = True
            if not found:
                layer.setName(name)
                QgsProject.instance().addMapLayer(layer)
    else:
        found = False
        layers = QgsProject.instance().mapLayers()
        for lyr in layers.values():
            if lyr.source().split("|")[0] == layer_path:
                found = True
        if not found:
            layer = iface.addVectorLayer(layer_path, name, "ogr")

    return layer


def set_default_stats_value(v_path, band_datas):
    log("setting default stats value function")
    layer = None
    for lyr in QgsProject.instance().mapLayers().values():
        if lyr.source().split("|")[0] == v_path:
            layer = lyr
            break
    if layer is None:
        return
    idx = layer.fields().lookupField("stats")
    layer.setDefaultValueDefinition(
        idx,
        QgsDefaultValue(f"calculate_error_recode_stats('{json.dumps(band_datas)}')"),
    )
    res = layer.listStylesInDatabase()
    if res[0] > 0:
        for i in res[1]:
            layer.deleteStyleFromDatabase(i)
    layer.saveStyleToDatabase("error_recode", "", True, "")


def edit(layer):
    layers = QgsProject.instance().mapLayers()
    for lyr in layers.values():
        if lyr.source().split("|")[0] == layer:
            if lyr.isEditable():
                lyr.commitChanges()
            else:
                lyr.startEditing()
