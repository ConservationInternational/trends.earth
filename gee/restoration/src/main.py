"""
Code for calculating potential carbon gains due to restoration.
"""
# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import random
import json

import ee

from landdegradation.util import TEImage
from landdegradation.schemas.schemas import BandInfo

def restoration_carbon(rest_type, length_yr, crs, geojsons, EXECUTION_ID,
                       logger):
    logger.debug("Entering restoration_carbon function.")
    # biomass
    agb_30m = ee.Image("users/geflanddegradation/toolbox_datasets/forest_agb_30m_woodhole")
    agb_1km = ee.Image("users/geflanddegradation/toolbox_datasets/forest_agb_1km_geocarbon")

    # c sequestration coefficients by intervention from winrock paper
    agfor0020 = ee.Image("users/geflanddegradation/toolbox_datasets/winrock_co2_seq_coeff_adm1").select("b1").divide(100);
    agfor2060 = ee.Image("users/geflanddegradation/toolbox_datasets/winrock_co2_seq_coeff_adm1").select("b2").divide(100);
    mshrr0020 = ee.Image("users/geflanddegradation/toolbox_datasets/winrock_co2_seq_coeff_adm1").select("b3").divide(100);
    mshrr2060 = ee.Image("users/geflanddegradation/toolbox_datasets/winrock_co2_seq_coeff_adm1").select("b4").divide(100);
    mtrer0020 = ee.Image("users/geflanddegradation/toolbox_datasets/winrock_co2_seq_coeff_adm1").select("b5").divide(100);
    mtrer2060 = ee.Image("users/geflanddegradation/toolbox_datasets/winrock_co2_seq_coeff_adm1").select("b6").divide(100);
    natre0020 = ee.Image("users/geflanddegradation/toolbox_datasets/winrock_co2_seq_coeff_adm1").select("b7").divide(100);
    natre2060 = ee.Image("users/geflanddegradation/toolbox_datasets/winrock_co2_seq_coeff_adm1").select("b8").divide(100);
    pwobr0020 = ee.Image("users/geflanddegradation/toolbox_datasets/winrock_co2_seq_coeff_adm1").select("b9").divide(100);
    pweuc0020 = ee.Image("users/geflanddegradation/toolbox_datasets/winrock_co2_seq_coeff_adm1").select("b10").divide(100);
    pwoak0020 = ee.Image("users/geflanddegradation/toolbox_datasets/winrock_co2_seq_coeff_adm1").select("b11").divide(100);
    pwoco0020 = ee.Image("users/geflanddegradation/toolbox_datasets/winrock_co2_seq_coeff_adm1").select("b12").divide(100);
    pwpin0020 = ee.Image("users/geflanddegradation/toolbox_datasets/winrock_co2_seq_coeff_adm1").select("b13").divide(100);
    pwtea0020 = ee.Image("users/geflanddegradation/toolbox_datasets/winrock_co2_seq_coeff_adm1").select("b14").divide(100);

    # combine the global 1km and the pantropical 30m datasets into one layer for analysis
    agb = agb_30m.float().unmask(0).where(ee.Image.pixelLonLat().select('latitude').abs().gte(29.999),agb_1km)

    # calculate below ground biomass following Mokany et al. 2006 = (0.489)*(AGB)^(0.89)
    bgb = agb.expression('0.489 * BIO**(0.89)', {'BIO': agb})

    # calculate total biomass (t/ha) then convert to carbon equilavent (*0.5) to get Total Carbon (t ha-1) = (AGB+BGB)*0.5
    tbc = agb.expression('(bgb + abg ) * 0.5 ', {'bgb': bgb,'abg': agb})

    # convert Total carbon to total CO2 eq (One ton of carbon equals 44/12 = 11/3 = 3.67 tons of carbon dioxide)
    current_co2 = tbc.expression('totalcarbon * 3.67 ', {'totalcarbon': tbc})

    if rest_type == "terrestrial":
        if length_yr <= 20:
            d_natre = natre0020.multiply(length_yr).subtract(current_co2)
            d_natre = d_natre.where(d_natre.lte(0), 0)
            d_agfor = agfor0020.multiply(length_yr).subtract(current_co2)
            d_agfor = d_agfor.where(d_agfor.lte(0), 0)
            d_pwtea = pwtea0020.multiply(length_yr).subtract(current_co2)
            d_pweuc = pweuc0020.multiply(length_yr).subtract(current_co2)
            d_pwoak = pwoak0020.multiply(length_yr).subtract(current_co2)
            d_pwobr = pwobr0020.multiply(length_yr).subtract(current_co2)
            d_pwpin = pwpin0020.multiply(length_yr).subtract(current_co2)
            d_pwoco = pwoco0020.multiply(length_yr).subtract(current_co2)
        if length_yr > 20:
            d_natre = natre0020.multiply(20).add(natre2060.multiply(length_yr-20)).subtract(current_co2)
            d_natre = d_natre.where(d_natre.lte(0), 0)
            d_agfor = agfor0020.multiply(20).add(agfor2060.multiply(length_yr-20)).subtract(current_co2)
            d_agfor = d_agfor.where(d_agfor.lte(0), 0)
            d_pwtea = pwtea0020.multiply(20).subtract(current_co2)
            d_pweuc = pweuc0020.multiply(20).subtract(current_co2)
            d_pwoak = pwoak0020.multiply(20).subtract(current_co2)
            d_pwobr = pwobr0020.multiply(20).subtract(current_co2)
            d_pwpin = pwpin0020.multiply(20).subtract(current_co2)
            d_pwoco = pwoco0020.multiply(20).subtract(current_co2)

        output = current_co2.addBands(d_natre).addBands(d_agfor) \
                    .addBands(d_pwtea).addBands(d_pweuc) \
                    .addBands(d_pwoak).addBands(d_pwobr) \
                    .addBands(d_pwpin).addBands(d_pwoco) \
                    .rename(['current','natreg','agrfor','pwteak','pweuca','pwoaks','pwobro','pwpine','pwocon'])
      
        logger.debug("Setting up output for terrestrial restoration.")
        out = TEImage(output,
                      [BandInfo("Biomass (tonnes CO2e per ha)", add_to_map=True,
                           metadata={'year': 'current'}),
                       BandInfo("Restoration biomass difference (tonnes CO2e per ha)",
                           metadata={'years': length_yr, 'type': 'natural regeneration'}),
                       BandInfo("Restoration biomass difference (tonnes CO2e per ha)",
                           metadata={'years': length_yr, 'type': 'agroforestry'}),
                       BandInfo("Restoration biomass difference (tonnes CO2e per ha)",
                           metadata={'years': length_yr, 'type': 'teak plantation'}),
                       BandInfo("Restoration biomass difference (tonnes CO2e per ha)",
                           metadata={'years': length_yr, 'type': 'eucalyptus plantation'}),
                       BandInfo("Restoration biomass difference (tonnes CO2e per ha)",
                           metadata={'years': length_yr, 'type': 'oak plantation'}),
                       BandInfo("Restoration biomass difference (tonnes CO2e per ha)",
                           metadata={'years': length_yr, 'type': 'other broadleaf plantation'}),
                       BandInfo("Restoration biomass difference (tonnes CO2e per ha)",
                           metadata={'years': length_yr, 'type': 'pine plantation'}),
                       BandInfo("Restoration biomass difference (tonnes CO2e per ha)",
                           metadata={'years': length_yr, 'type': 'conifer plantation'})])
    elif rest_type == "coastal":
        if length_yr <= 20:
            d_mshrr = mshrr0020.multiply(length_yr).subtract(current_co2)
            d_mshrr = d_mshrr.where(d_mshrr.lte(0), 0)
            d_mtrer = mtrer0020.multiply(length_yr).subtract(current_co2)
            d_mtrer = d_mtrer.where(d_mtrer.lte(0), 0)
        if length_yr > 20:
            d_mshrr = mshrr0020.multiply(20).add(mshrr2060.multiply(length_yr-20)).subtract(current_co2)
            d_mshrr = d_mshrr.where(d_mshrr.lte(0), 0)
            d_mtrer = mtrer0020.multiply(20).add(mtrer2060.multiply(length_yr-20)).subtract(current_co2)
            d_mtrer = d_mtrer.where(d_mtrer.lte(0), 0)
      
        logger.debug("Setting up output for coastal restoration.")
        out = TEImage(current_co2.addBands(d_mshrr).addBands(d_mtrer).rename(['current','mshrr','mtrer']),
                [BandInfo("Biomass (tonnes CO2e per ha)", add_to_map=True,
                    metadata={'year': 'current'}),
                 BandInfo("Restoration biomass difference (tonnes CO2e per ha)",
                    metadata={'years': length_yr, 'type': 'mangrove shrub'}),
                 BandInfo("Restoration biomass difference (tonnes CO2e per ha)",
                    metadata={'years': length_yr, 'type': 'mangrove tree'})])
    else:
        raise

    out.image = out.image.reproject(crs=agb_30m.projection())

    return out

def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    rest_type = params.get('rest_type', None)
    assert rest_type in ['terrestrial', 'coastal']
    length_yr = int(params.get('length_yr', None))
    geojsons = json.loads(params.get('geojsons', None))
    crs = params.get('crs', None)
    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)
        
    logger.debug("Running main script.")
    out = restoration_carbon(rest_type, length_yr, crs, geojsons, EXECUTION_ID, logger)
    return out.export(geojsons, 'restoration_carbon', crs, logger, EXECUTION_ID)
