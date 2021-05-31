"""Configuration utilities for Trends.Earth QGIS plugin."""

import enum
import typing
from pathlib import Path

import qgis.core

from . import download
from .algorithms import models as algorithm_models


class AreaSetting(enum.Enum):
    COUNTRY_REGION = "country_region"
    COUNTRY_CITY = "country_city"
    POINT = "point"
    VECTOR_LAYER = "vector_layer"


class Setting(enum.Enum):
    LOCAL_CONTEXT_SEPARATOR = "private/local_context_separator"
    LOCAL_POLLING_FREQUENCY = "private/local_polling_frequency_seconds"
    UPDATE_FREQUENCY_MILLISECONDS = "private/update_frequency_milliseconds"

    DEBUG = "advanced/debug"
    BINARIES_ENABLED = "advanced/binaries_enabled"
    BINARIES_DIR = "advanced/binaries_folder"
    BASE_DIR = "advanced/base_data_directory"
    CUSTOM_CRS_ENABLED = "region_of_interest/custom_crs_enabled"
    CUSTOM_CRS = "region_of_interest/custom_crs"
    POLL_REMOTE = "advanced/poll_remote_server"
    REMOTE_POLLING_FREQUENCY = "advanced/remote_polling_frequency_seconds"
    DOWNLOAD_RESULTS = "advanced/download_remote_results_automatically"
    BUFFER_CHECKED = "region_of_interest/buffer_checked"
    AREA_FROM_OPTION = "region_of_interest/chosen_method"
    POINT_X = "region_of_interest/point/x"
    POINT_Y = "region_of_interest/point/y"
    VECTOR_FILE_PATH = "region_of_interest/vector_file"
    VECTOR_FILE_DIR = "region_of_interest/vector_file_dir"
    COUNTRY_NAME = "region_of_interest/country/country_name"
    REGION_NAME = "region_of_interest/country/region_name"
    CITY_NAME = "region_of_interest/country/city_name"
    CITY_KEY = "region_of_interest/current_cities_key"
    BUFFER_SIZE = "region_of_interest/buffer_size"
    AREA_NAME = "region_of_interest/area_settings_name"
    JOB_FILE_AGE_LIMIT_DAYS = "advanced/deleted_datasets_age_limit"


class SettingsManager:
    _settings: qgis.core.QgsSettings
    _base_path: str = "trends_earth"

    DEFAULT_SETTINGS = {
        Setting.UPDATE_FREQUENCY_MILLISECONDS: 10000,
        Setting.LOCAL_POLLING_FREQUENCY: 30,
        Setting.LOCAL_CONTEXT_SEPARATOR: "-*-*-*-local_context-*-*-*-",
        Setting.REMOTE_POLLING_FREQUENCY: 3 * 60,
        Setting.DEBUG: False,
        Setting.BINARIES_ENABLED: False,
        Setting.BINARIES_DIR: str(Path.home()),
        Setting.BASE_DIR: str(Path.home() / "trends_earth_data"),
        Setting.CUSTOM_CRS_ENABLED: False,
        Setting.CUSTOM_CRS: "epsg:4326",
        Setting.POLL_REMOTE: True,
        Setting.DOWNLOAD_RESULTS: True,
        Setting.BUFFER_CHECKED: False,
        Setting.AREA_FROM_OPTION: AreaSetting.COUNTRY_REGION.value,
        Setting.POINT_X: 0.0,
        Setting.POINT_Y: 0.0,
        Setting.VECTOR_FILE_PATH: "",
        Setting.VECTOR_FILE_DIR: "",
        Setting.COUNTRY_NAME: "",
        Setting.REGION_NAME: "",
        Setting.CITY_NAME: "",
        Setting.CITY_KEY: 0,
        Setting.BUFFER_SIZE: 0.0,
        Setting.AREA_NAME: "",
        Setting.JOB_FILE_AGE_LIMIT_DAYS: 15,
    }

    def __init__(self):
        self._settings = qgis.core.QgsSettings()
        self._initialize_settings()

    @property
    def base_path(self):
        return self._base_path

    def get_value(self, key: Setting):
        if key == Setting.LOCAL_POLLING_FREQUENCY:
            result = self.DEFAULT_SETTINGS[key]
        elif key == Setting.UPDATE_FREQUENCY_MILLISECONDS:
            result = self.DEFAULT_SETTINGS[key]
        elif key == Setting.LOCAL_CONTEXT_SEPARATOR:
            result = self.DEFAULT_SETTINGS[key]
        else:
            type_ = type(self.DEFAULT_SETTINGS[key])
            result = self._settings.value(
                f"{self.base_path}/{key.value}", self.DEFAULT_SETTINGS[key], type=type_)
        return result

    def write_value(self, key: Setting, value: typing.Any):
        return self._settings.setValue(f"{self.base_path}/{key.value}", value)

    def _initialize_settings(self):
        for setting, default_value in self.DEFAULT_SETTINGS.items():
            current_value = self._settings.value(f"{self.base_path}/{setting.value}")
            if current_value is None:
                self.write_value(setting, self.DEFAULT_SETTINGS[setting])


def _load_script_config(
        script_config: typing.Dict
) -> typing.Dict[str, algorithm_models.ExecutionScript]:
    result = {}
    for name, raw_config in script_config.items():
        script = algorithm_models.ExecutionScript.deserialize(name, raw_config)
        result[script.name] = script
    return result


def _load_algorithm_config(
        algorithm_config: typing.List[typing.Dict],
) -> algorithm_models.AlgorithmGroup:
    top_level_groups = []
    for raw_top_level_group in algorithm_config:
        group = algorithm_models.AlgorithmGroup.deserialize(
            raw_top_level_group)
        top_level_groups.append(group)
    return algorithm_models.AlgorithmGroup(
        name="root",
        name_details="root_details",
        parent=None,
        groups=top_level_groups
    )


REMOTE_DATASETS = {
    "Trends.Earth Global Results": {
        "Land cover (degradation)": {
            "Data source": "",
            "Start year": "NA",
            "End year": "NA",
            "Spatial Resolution": "250 m",
            "Temporal resolution": "one time",
            "Min Latitude": "-90",
            "Max Latitude": "90",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Description": "",
            "Units": "",
            "Link to Dataset": "",
            "GEE Dataset": "users/geflanddegradation/global_ld_analysis/lc_traj_globe_2001-2001_to_2015",
            "Source code": "",
            "Status": "",
            "License": "",
            "License URL": "",
            "Source": "",
            "Comments": "",
            "Admin only": True
        },
        "Soil organic carbon (degradation)": {
            "Data source": "",
            "Start year": "NA",
            "End year": "NA",
            "Spatial Resolution": "250 m",
            "Temporal resolution": "one time",
            "Min Latitude": "-90",
            "Max Latitude": "90",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Description": "",
            "Units": "",
            "Link to Dataset": "",
            "GEE Dataset": "users/geflanddegradation/global_ld_analysis/soc_globe_2001-2015_deg",
            "Source code": "",
            "Status": "",
            "License": "",
            "License URL": "",
            "Source": "",
            "Comments": "",
            "Admin only": True
        },
        "SDG 15.3.1 Indicator (LPD)": {
            "Data source": "",
            "Start year": "NA",
            "End year": "NA",
            "Spatial Resolution": "250 m",
            "Temporal resolution": "one time",
            "Min Latitude": "-90",
            "Max Latitude": "90",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Description": "",
            "Units": "",
            "Link to Dataset": "",
            "GEE Dataset": "users/geflanddegradation/global_ld_analysis/sdg1531_lpd_globe_2001_2015_modis",
            "Source code": "",
            "Status": "",
            "License": "",
            "License URL": "",
            "Source": "",
            "Comments": "",
            "Admin only": True
        },
        "SDG 15.3.1 Indicator (Trends.Earth)": {
            "Data source": "",
            "Start year": "NA",
            "End year": "NA",
            "Spatial Resolution": "250 m",
            "Temporal resolution": "one time",
            "Min Latitude": "-90",
            "Max Latitude": "90",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Description": "",
            "Units": "",
            "Link to Dataset": "",
            "GEE Dataset": "users/geflanddegradation/global_ld_analysis/sdg1531_gpg_globe_2001_2015_modis",
            "Source code": "",
            "Status": "",
            "License": "",
            "License URL": "",
            "Source": "",
            "Comments": "",
            "Admin only": True
        },
        "SDG 15.3.1 Productivity Indicator (Trends.Earth)": {
            "Data source": "",
            "Start year": "NA",
            "End year": "NA",
            "Spatial Resolution": "250 m",
            "Temporal resolution": "one time",
            "Min Latitude": "-90",
            "Max Latitude": "90",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Description": "",
            "Units": "",
            "Link to Dataset": "",
            "GEE Dataset": "users/geflanddegradation/global_ld_analysis/lp5cl_globe_2001_2015_modis",
            "Source code": "",
            "Status": "",
            "License": "",
            "License URL": "",
            "Source": "",
            "Comments": "",
            "Admin only": True
        }
    },
    "Global Zoning": {
        "Climatic Zones": {
            "Data source": "The European Commission",
            "Start year": "NA",
            "End year": "NA",
            "Spatial Resolution": "8 km",
            "Temporal resolution": "one time",
            "Min Latitude": "-90",
            "Max Latitude": "90",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Description": "The Climatic Zone layer is defined based on the classification of IPCC (IPCC, 2006). The zones are defined by a set of rules based on: annual mean daily temperature, total annual precipitation, total annual potential evapo-transpiration (PET) and elevation. The classification presented as Figure 3A.5.1 Classification scheme for default climate regions” (IPCC, 2006) could not be accessed in electronic form and generated from an independently developed set of base data layers. Climatic information on temperature and precipitation was provided by the 5 arc min. dataset Version 1.4 from the WorldClim project (Hijmans et al., 2005). PET was computed according to the temperature-based formula investigated by Oudin et al. (2005) and used by Kay & Davis (2008). The computation of the extraterrestrial radiation was based on Duffie & Beckman (1991) and Allen et al. (1994). The formulas were supplemented by the information provided by the “Solar Radiation Basis” Web-page of the University of Oregon: http://solardat.uoregon.edu/SolarRadiationBasics.html.",
            "Units": "",
            "Link to Dataset": "http://eusoils.jrc.ec.europa.eu/projects/RenewableEnergy/",
            "GEE Dataset": "users/geflanddegradation/toolbox_datasets/ipcc_climate_zones",
            "Source code": "Imported as assets",
            "Status": "Stored as assets",
            "License": "Reuse is authorised, provided the source is acknowledged.",
            "License URL": "http://eur-lex.europa.eu/LexUriServ/LexUriServ.do?uri=OJ:L:2011:330:0039:0042:EN:PDF",
            "Source": "European Commission Soil Projects - Support to Renewable Energy Directive",
            "Comments": ""
        },
        "Agro Ecological Zones V3.0": {
            "Data source": "FAO - IIASA",
            "Start year": "NA",
            "End year": "NA",
            "Spatial Resolution": "8 km",
            "Temporal resolution": "one time",
            "Min Latitude": "-90",
            "Max Latitude": "90",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Description": "Agroecological zones (AEZs) are geographical areas exhibiting similar climatic conditions that determine their ability to support rained agriculture. At a regional scale, AEZs are influenced by latitude, elevation, and temperature, as well as seasonality, and rainfall amounts and distribution during the growing season.",
            "Units": "",
            "Link to Dataset": "http://www.fao.org/nr/gaez/en/",
            "GEE Dataset": "users/geflanddegradation/toolbox_datasets/gaez_iiasa",
            "Source code": "Imported as assets",
            "Status": "Stored as assets",
            "License": "Public Domain",
            "License URL": "https://creativecommons.org/publicdomain/zero/1.0/",
            "Source": "Made with Natural Earth. Free vector and raster map data @ naturalearthdata.com.",
            "Comments": ""
        }
    },
    "Evapotranspiration": {
        "MOD16A2": {
            "Data source": "GEE",
            "Start year": 2000,
            "End year": 2019,
            "Spatial Resolution": "1 km",
            "Temporal resolution": "annual",
            "Min Latitude": "-90",
            "Max Latitude": "90",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Description": "The MOD16A2 Version 6 Evapotranspiration/Latent Heat Flux product is an 8-day composite product produced at 500 meter pixel resolution. The algorithm used for the MOD16 data product collection is based on the logic of the Penman-Monteith equation, which includes inputs of daily meteorological reanalysis data along with MODIS remotely sensed data products such as vegetation property dynamics, albedo, and land cover.",
            "Units": "Annual ET km/m2 (=mm) * 10",
            "Link to Dataset": "http://files.ntsg.umt.edu/data/NTSG_Products/MOD16/",
            "GEE Dataset": "users/geflanddegradation/toolbox_datasets/et_modis_2000_2019",
            "Source code": "c03_et_modis_int_global_assets",
            "Status": "Stored as assets",
            "License": "Public Domain",
            "License URL": "https://creativecommons.org/publicdomain/zero/1.0/",
            "Source": "Steve Running, Qiaozhen Mu - University of Montana and MODAPS SIPS - NASA. (2015). MOD16A2 MODIS/Terra Evapotranspiration 8-day L4 Global 500m SIN Grid. NASA LP DAAC. http://doi.org/10.5067/MODIS/MOD16A2.00",
            "Comments": ""
        }
    },
    "Land cover": {
        "ESA CCI": {
            "Data source": "ESA",
            "Start year": 1992,
            "End year": 2019,
            "Spatial Resolution": "300 m",
            "Temporal resolution": "annual",
            "Min Latitude": "-90",
            "Max Latitude": "90",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Units": "Land cover classes",
            "Description": "The CCI-LC project delivers consistent global LC maps at 300 m spatial resolution on an annual basis from 1992 to 2018. The Coordinate Reference System used for the global land cover database is a geographic coordinate system (GCS) based on the World Geodetic System 84 (WGS84) reference ellipsoid.",
            "Link to Dataset": "http://maps.elie.ucl.ac.be/CCI/viewer/index.php",
            "GEE Dataset": "users/geflanddegradation/toolbox_datasets/lcov_esacc_1992_2019",
            "Source code": "c04_esa_cci_landcover_global_assets",
            "Status": "Stored as assets",
            "License": "CC by-SA 3.0",
            "License URL": "https://creativecommons.org/licenses/by-sa/3.0/igo/",
            "Source": "ESA Land Cover CCI project team; Defourny, P. (2016): ESA Land Cover Climate Change Initiative (Land_Cover_cci): MERIS Surface Reflectance. Centre for Environmental Data Analysis, 12/15/2017. http://catalogue.ceda.ac.uk/uuid/e80f28ccb0504c32b403eee654a8a5b3",
            "Comments": ""
        }
    },
    "NDVI": {
        "AVHRR (GIMMS3g.v1, annual)": {
            "Data source": "https://ecocast.arc.nasa.gov/data/pub/gimms/3g.v1/",
            "Start year": 1982,
            "End year": 2015,
            "Spatial Resolution": "8 km",
            "Temporal resolution": "annual",
            "Min Latitude": "-90",
            "Max Latitude": "90",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Units": "Mean anual NDVI * 10000",
            "Description": "Vegetation indices are radiometric measures of photosynthetically active radiation absorbed by chlorophyll in the green leaves of vegetation canopies and are therefore good surrogate measures of the physiologically functioning surface greenness level of a region. In a series of articles during the early 1980s, Compton J. Tucker, demonstrated how the Normalized Difference Vegetation Index (NDVI) generated from NOAA’s Advanced Very High Resolution Radiometer (AVHRR) data can be used to map land cover and monitor vegetation changes and desertification at continental and global scales. A simple search on the Web of Science reveals over 5000 articles containing NDVI either in the title or in the abstract. Compton J. Tucker continued to generate the NDVI time series over the past 30 years, in the framework of the Global Inventory Monitoring and Modeling System (GIMMS) project, carefully assembling it from different AVHRR sensors and accounting for various deleterious effects, such as calibration loss, orbital drift, volcanic eruptions, etc. The latest version of the GIMMS NDVI data set spans the period July 1981 to December 2011 and is termed NDVI3g (third generation GIMMS NDVI from AVHRR sensors).",
            "Link to Dataset": "ecocast.arc.nasa.gov",
            "GEE Dataset": "users/geflanddegradation/toolbox_datasets/ndvi_avhrr_1982_2015",
            "Source code": "c01_ndvi_avhrr_nasa_int_global_assets",
            "Status": "Stored as assets",
            "License": "Public Domain",
            "License URL": "https://creativecommons.org/publicdomain/zero/1.0/",
            "Source": "Pinzon, J., M. E. Brown and C. J. Tucker. 2004. Satellite time series correction of orbital drift artifacts using empirical mode decomposition. In Hilbert-Huang Transform: Introduction and Applications, eds. N. Huang, pp. Chapter 10, Part II. Applications (to appear).",
            "Comments": ""
        },
        "MODIS (MOD13Q1, annual)": {
            "Data source": "GEE",
            "Start year": 2001,
            "End year": 2020,
            "Spatial Resolution": "250 m",
            "Temporal resolution": "annual",
            "Min Latitude": "-90",
            "Max Latitude": "90",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Units": "Mean anual NDVI * 10000",
            "Description": "The MOD13Q1 Version 6 product provides a Vegetation Index (VI) value at a per pixel basis. There are two primary vegetation layers. The first is the Normalized Difference Vegetation Index (NDVI) which is referred to as the continuity index to the existing National Oceanic and Atmospheric Administration-Advanced Very High Resolution Radiometer (NOAA-AVHRR) derived NDVI. The second vegetation layer is the Enhanced Vegetation Index (EVI), which has improved sensitivity over high biomass regions.",
            "Link to Dataset": "https://explorer.earthengine.google.com/#detail/MODIS%2FMOD13Q1",
            "GEE Dataset": "users/geflanddegradation/toolbox_datasets/ndvi_modis_2001_2020",
            "Source code": "c02_ndvi_modis_int_global_assets",
            "Status": "Stored as assets",
            "License": "Public Domain",
            "License URL": "https://creativecommons.org/publicdomain/zero/1.0/",
            "Source": "NASA LP DAAC, 2016, MOD13Q1, Version 6. NASA EOSDIS Land Processes DAAC, USGS Earth Resources Observation and Science (EROS) Center, Sioux Falls, South Dakota (https://lpdaac.usgs.gov), accessed [12 15, 2017], at http://dx.doi.org/10.5067/MODIS/MOD13Q1.006",
            "Comments": ""
        },
        "MODIS (MOD13Q1, 16 day)": {
            "Data source": "GEE",
            "Start year": 2001,
            "End year": 2016,
            "Spatial resolution": "250 m",
            "Temporal resolution": "16 day",
            "Min Latitude": "-90",
            "Max Latitude": "90",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Units": "NDVI * 10000",
            "Description": "The MOD13Q1 Version 6 product provides a Vegetation Index (VI) value at a per pixel basis. There are two primary vegetation layers. The first is the Normalized Difference Vegetation Index (NDVI) which is referred to as the continuity index to the existing National Oceanic and Atmospheric Administration-Advanced Very High Resolution Radiometer (NOAA-AVHRR) derived NDVI. The second vegetation layer is the Enhanced Vegetation Index (EVI), which has improved sensitivity over high biomass regions.",
            "Link to Dataset": "https://explorer.earthengine.google.com/#detail/MODIS%2FMOD13Q1",
            "GEE Dataset": "users/geflanddegradation/toolbox_datasets/ndvi_mod13q1_16d_20010101_20161218_globe",
            "Status": "Stored as assets",
            "License": "Public Domain",
            "License URL": "https://creativecommons.org/publicdomain/zero/1.0/",
            "Source": "NASA LP DAAC, 2016, MOD13Q1, Version 6. NASA EOSDIS Land Processes DAAC, USGS Earth Resources Observation and Science (EROS) Center, Sioux Falls, South Dakota (https://lpdaac.usgs.gov), accessed [12 15, 2017], at http://dx.doi.org/10.5067/MODIS/MOD13Q1.006",
            "Comments": ""
        }
    },
    "Land productivity": {
        "Land Productivity Dynamics (LPD)": {
            "Data source": "Joint Research Commission (JRC)",
            "Start year": "NA",
            "End year": "NA",
            "Spatial resolution": "1 km",
            "Temporal resolution": "one time",
            "Min Latitude": "-90",
            "Max Latitude": "90",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Units": "",
            "Description": "The Land Productivity Dynamics (LPD) dataset is produced by the Joint research Ommission. The land-productivity dynamics dataset is calculated from vegetation indices derived from long-term low-resolution satellite time series such as the GIMMS3g dataset combined with productivity efficiency measurements derived from short, recent, medium resolution data such as those from the SPOT VEGETATION sensor. The limited set of NDVI variables is extended by a number of phenological and productivity relevant variables. Keeping statistical solidity, qualitative approaches have been selected to classify, interpret and integrate these several variables. Intermediate products are produced that are then combined into a Land-productivity Dynamics data layer. Land-productivity dynamics can indicate levels of sustained land-quality and is therefore used as first step in the land degradation assessment.",
            "Link to Dataset": "None availab.e",
            "GEE Dataset": "users/geflanddegradation/toolbox_datasets/lpd_300m_longlat",
            "Source code": "None available.",
            "Status": "Stored as assets",
            "License": "",
            "License URL": "",
            "Source": "United Nations Convention to Combat Desertification, 2017. The Global Land Outlook, first edition. Bonn, Germany. Available from: http://www2.unccd.int/actions/global-land-outlook-glo",
            "Comments": ""
        }
    },
    "Precipitation": {
        "CHIRPS": {
            "Data source": "GEE",
            "Start year": 1981,
            "End year": 2020,
            "Spatial resolution": "5 km",
            "Temporal resolution": "annual",
            "Min Latitude": "-50",
            "Max Latitude": "50",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Units": "mm/year",
            "Description": "Climate Hazards Group InfraRed Precipitation with Station data (CHIRPS) is a 30+ year quasi-global rainfall dataset. Spanning 50°S-50°N (and all longitudes), starting in 1981 to near-present, CHIRPS incorporates 0.05° resolution satellite imagery with in-situ station data to create gridded rainfall time series for trend analysis and seasonal drought monitoring.",
            "Link to Dataset": "http://chg.geog.ucsb.edu/data/chirps/",
            "GEE Dataset": "users/geflanddegradation/toolbox_datasets/prec_chirps_1981_2020",
            "Source code": "c05_precip_chirps_int_global_assets",
            "Status": "Stored as assets",
            "License": "Public Domain",
            "License URL": "https://creativecommons.org/publicdomain/zero/1.0/",
            "Source": "Funk, Chris, Pete Peterson, Martin Landsfeld, Diego Pedreros, James Verdin, Shraddhanand Shukla, Gregory Husak, James Rowland, Laura Harrison, Andrew Hoell & Joel Michaelsen.The climate hazards infrared precipitation with stations—a new environmental record for monitoring extremes. Scientific Data 2, 150066. doi:10.1038/sdata.2015.66 2015.",
            "Comments": ""
        },
        "GPCC V6 (Global Precipitation Climatology Centre)": {
            "Data source": "https://www.esrl.noaa.gov/psd/data/gridded/data.gpcc.html",
            "Start year": 1891,
            "End year": 2019,
            "Spatial resolution": "5 km",
            "Temporal resolution": "annual",
            "Min Latitude": "-90",
            "Max Latitude": "90",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Units": "mm/year",
            "Description": "The GPCC provides gridded gauge-analysis products derived from quality controlled station data. Two products are for climate: (a) the Full Data Reanalysis Product  (1901-2010) is recommended for global and regional water balance studies, calibration/validation of remote sensing based rainfall estimations and verification of numerical models, and (b) the VASClimO 50-Year Data Set which is for climate variability and trend studies. The products are not bias corrected for systematic gauge measuring errors. However, the GPCC provides estimates for that error as well as the number of gauges used on the grid.",
            "Link to Dataset": "http://apps.ecmwf.int/datasets/data/interim-full-moda/levtype=sfc/",
            "GEE Dataset": "users/geflanddegradation/toolbox_datasets/prec_gpcc_1891_2019",
            "Source code": "c08_gpcc",
            "Status": "Stored as assets",
            "License": "Public Domain",
            "License URL": "https://creativecommons.org/publicdomain/zero/1.0/",
            "Source": "Ziese, Markus; Becker, Andreas; Finger, Peter; Meyer-Christoffer, Anja; Rudolf, Bruno; Schneider, Udo (2011): GPCC First Guess Product at 1.0°: Near Real-Time First Guess monthly Land Surface Precipitation from Rain-Gauges based on SYNOP Data. DOI: 10.5676/DWD_GPCC/FG_M_100 ",
            "Comments": "Full V7 until Jan 2013; V4 monitoring after."
        },
        "GPCP v2.3 1 month (Global Precipitation Climatology Project)": {
            "Data source": "https://www.esrl.noaa.gov/psd/data/gridded/data.gpcp.html",
            "Start year": 1979,
            "End year": 2019,
            "Spatial resolution": "5 km",
            "Temporal resolution": "monthly",
            "Min Latitude": "-90",
            "Max Latitude": "90",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Units": "mm/year",
            "Description": "Data from rain gauge stations, satellites, and sounding observations have been merged to estimate monthly rainfall on a 2.5-degree global grid from 1979 to the present. The careful combination of satellite-based rainfall estimates provides the most complete analysis of rainfall available to date over the global oceans, and adds necessary spatial detail to the rainfall analyses over land. In addition to the combination of these data sets, estimates of the uncertainties in the rainfall analysis are provided as a part of the GPCP products. The August 2012 GPCP v2.2 uses upgraded emission and scattering algorithms, the GPCC precipitation gauge analysis, and inclusion of the DMSP F17 SSMIS. The December 2012 update contains \"recomputed\" October 2012 values. NOTE: Due to a hardware failure, GPCP SG V2.2 and 1DD V1.2 have ceased production. The last processed month is October 2015. The follow-on GPCP V2.3 and 1DD V1.3 will soon become available, reprocessed back to January 1979 and October 1996, respectively. These new versions will be produced by at ESSIC in conjunction with NCEI (formerly NCDC).",
            "Link to Dataset": "http://gpcp.umd.edu/",
            "GEE Dataset": "users/geflanddegradation/toolbox_datasets/prec_gpcp23_1979_2019",
            "Source code": "c07_precip_gpcp_v2.3_1m",
            "Status": "Stored as assets",
            "License": "Public Domain",
            "License URL": "https://creativecommons.org/publicdomain/zero/1.0/",
            "Source": "Adler, R.F., G.J. Huffman, A. Chang, R. Ferraro, P. Xie, J. Janowiak, B. Rudolf, U. Schneider, S. Curtis, D. Bolvin, A. Gruber, J. Susskind, and P. Arkin, 2003: The Version 2 Global Precipitation Climatology Project (GPCP) Monthly Precipitation Analysis (1979-Present). J. Hydrometeor., 4,1147-1167.",
            "Comments": ""
        },
        "PERSIANN-CDR": {
            "Data source": "GEE",
            "Start year": 1983,
            "End year": 2018,
            "Spatial resolution": "25 km",
            "Temporal resolution": "annual",
            "Min Latitude": "-60",
            "Max Latitude": "60",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Units": "mm/year",
            "Description": "The Precipitation Estimation from Remotely Sensed Information using Artificial Neural Networks- Climate Data Record (PERSIANN-CDR) provides daily rainfall estimates at a spatial resolution of 0.25 degrees in the latitude band 60S - 60N from 1983 to the near-present. The precipitation estimate is produced using the PERSIANN algorithm on GridSat-B1 infrared satellite data, and the training of the artificial neural network is done using the National Centers for Environmental Prediction (NCEP) stage IV hourly precipitation data. The PERSIANN-CDR is adjusted using the Global Precipitation Climatology Project (GPCP) monthly product version 2.2 (GPCPv2.2), so that the PERSIANN-CDR monthly means degraded to 2.5 degree resolution match GPCPv2.2. PERSIANN CDR is a Climate Data Record, which the National Research Council (NRC) defines as a time series of measurements of sufficient length, consistency, and continuity to determine climate variability and change. ",
            "Link to Dataset": "https://climatedataguide.ucar.edu/climate-data/persiann-cdr-precipitation-estimation-remotely-sensed-information-using-artificial",
            "GEE Dataset": "users/geflanddegradation/toolbox_datasets/prec_persian_1983_2018",
            "Source code": "c05_precip_presian_int_global_assets",
            "Status": "Stored as assets",
            "License": "Public Domain",
            "License URL": "https://creativecommons.org/publicdomain/zero/1.0/",
            "Source": "Sorooshian, Soroosh; Hsu, Kuolin; Braithwaite, Dan; Ashouri, Hamed; and NOAA CDR Program (2014): NOAA Climate Data Record (CDR) of Precipitation Estimation from Remotely Sensed Information using Artificial Neural Networks (PERSIANN-CDR), Version 1 Revision 1. [indicate subset used]. NOAA National Centers for Environmental Information. doi:10.7289/V51V5BWQ [access date].Publications using this dataset should also cite the following journal article: Ashouri H., K. Hsu, S. Sorooshian, D. K. Braithwaite, K. R. Knapp, L. D. Cecil, B. R. Nelson, and O. P. Prat, 2015: PERSIANN-CDR: Daily Precipitation Climate Data Record from Multi-Satellite Observations for Hydrological and Climate Studies. Bull. Amer. Meteor. Soc., doi: https://doi.org/10.1175/BAMS-D-13-00068.1.",
            "Comments": "Pre 1999 there are some gaps in the satellite coverage (South America and Russia)."
        }
    },
    "Soil moisture": {
        "ERA I": {
            "Data source": "http://apps.ecmwf.int/datasets/data/interim-full-moda/levtype=sfc/",
            "Start year": 1979,
            "End year": 2016,
            "Spatial resolution": "5 km",
            "Temporal resolution": "annual",
            "Min Latitude": "-90",
            "Max Latitude": "90",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Units": "Volumetric Soil Water layer m3m-3 (0-7 cm)",
            "Description": "The data assimilation system used to produce ERA-Interim is based on a 2006 release of the IFS (Cy31r2). The system includes a 4-dimensional variational analysis (4D-Var) with a 12-hour analysis window. The spatial resolution of the data set is approximately 80 km (T255 spectral) on 60 vertical levels from the surface up to 0.1 hPa. ",
            "Link to Dataset": "http://apps.ecmwf.int/datasets/data/interim-full-moda/levtype=sfc/",
            "GEE Dataset": "users/geflanddegradation/toolbox_datasets/soilm_erai_1979_2016",
            "Source code": "c06_soilm_erai",
            "Status": "Stored as assets",
            "License": "CC by NC ND 4.0",
            "License URL": "https://creativecommons.org/licenses/by-nc-nd/4.0/legalcode",
            "Source": "Dee, D. P., Uppala, S. M., Simmons, A. J., Berrisford, P., Poli, P., Kobayashi, S., Andrae, U., Balmaseda, M. A., Balsamo, G., Bauer, P., Bechtold, P., Beljaars, A. C. M., van de Berg, L., Bidlot, J., Bormann, N., Delsol, C., Dragani, R., Fuentes, M., Geer, A. J., Haimberger, L., Healy, S. B., Hersbach, H., Hólm, E. V., Isaksen, L., Kållberg, P., Köhler, M., Matricardi, M., McNally, A. P., Monge-Sanz, B. M., Morcrette, J.-J., Park, B.-K., Peubey, C., de Rosnay, P., Tavolato, C., Thépaut, J.-N. and Vitart, F. (2011), The ERA-Interim reanalysis: configuration and performance of the data assimilation system. Q.J.R. Meteorol. Soc., 137: 553–597. doi:10.1002/qj.828",
            "Comments": "Does not cover small islands"
        },
        "MERRA 2": {
            "Data source": "https://disc.sci.gsfc.nasa.gov/datasets?page=1&keywords=M2TMNXLND_5.12.4",
            "Start year": 1980,
            "End year": 2016,
            "Spatial resolution": "5 km",
            "Temporal resolution": "annual",
            "Min Latitude": "-90",
            "Max Latitude": "90",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Units": "Water root zone m3m-3 * 10000",
            "Description": "The Modern-Era Retrospective analysis for Research and Applications, Version 2 (MERRA-2) provides data beginning in 1980. It was introduced to replace the original MERRA dataset because of the advances made in the assimilation system that enable assimilation of modern hyperspectral radiance and microwave observations, along with GPS-Radio Occultation datasets. It also uses NASA's ozone profile observations that began in late 2004. Additional advances in both the GEOS model and the GSI assimilation system are included in MERRA-2. Spatial resolution remains about the same (about 50 km in the latitudinal direction) as in MERRA.",
            "Link to Dataset": "https://disc.sci.gsfc.nasa.gov/datasets?page=1&keywords=M2TMNXLND_5.12.4",
            "GEE Dataset": "users/geflanddegradation/toolbox_datasets/soilm_merra2_1980_2019",
            "Source code": "c06_soilm_merra2",
            "Status": "Stored as assets",
            "License": "Public Domain",
            "License URL": "https://creativecommons.org/publicdomain/zero/1.0/",
            "Source": "Gelaro, Ronald et. al. 2017. The Modern-Era Retrospective Analysis for Research and Applications, Version 2 (MERRA-2). J. Clim., DOI: 10.1175/JCLI-D-16-0758.1 http://journals.ametsoc.org/doi/abs/10.1175/JCLI-D-16-0758.1",
            "Comments": ""
        }
    },
    "Soil organic C": {
        "Soil Grids 250": {
            "Data source": "https://www.soilgrids.org",
            "Start year": "NA",
            "Temporal resolution": "one time",
            "End year": "NA",
            "Spatial resolution": "250 m",
            "Min Latitude": "-90",
            "Max Latitude": "90",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Units": "Tons C/ha (0-30 cm depth)",
            "Description": "SoilGrids1km and SoilGrids250m are outputs of a system for automated global soil mapping developed within ISRIC's GSIF framework. This system is intended to facilitate global soil data initiatives and to serve as a bridge between global and local soil mapping.",
            "Link to Dataset": "ftp://ftp.soilgrids.org/data/recent/",
            "GEE Dataset": "users/geflanddegradation/toolbox_datasets/soc_sgrid_30cm",
            "Source code": "Imported as assets",
            "Status": "Stored as assets",
            "License": "CC by-SA 4.0",
            "License URL": "https://creativecommons.org/licenses/by-sa/4.0/",
            "Source": "Hengl, T., Mendes de Jesus, J., Heuvelink, G. B.M., Ruiperez Gonzalez, M., Kilibarda, M. et al. (2017) SoilGrids250m: global gridded soil information based on Machine Learning. PLOS One: http://journals.plos.org/plosone/article?id=10.1371/journal.pone.0169748",
            "Comments": ""
        }
    },
    "Soil type - USDA": {
        "USDA Soil Type": {
            "Data source": "USDA",
            "Start year": "NA",
            "End year": "NA",
            "Spatial resolution": "250 m",
            "Temporal resolution": "one time",
            "Min Latitude": "-90",
            "Max Latitude": "90",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Units": "USDA Soil Taxonomy suborders - 67 soil classes",
            "Description": "",
            "Link to Dataset": "",
            "GEE Dataset": "users/geflanddegradation/toolbox_datasets/stax_sgrid_usda",
            "Source code": "Imported as assets",
            "Status": "Stored as assets",
            "License": "Public Domain",
            "License URL": "https://creativecommons.org/publicdomain/zero/1.0/",
            "Source": "",
            "Comments": ""
        }
    },
    "Soil type - WRB": {
        "Soil Grids 250": {
            "Data source": "https://www.soilgrids.org",
            "Start year": "NA",
            "End year": "NA",
            "Spatial resolution": "250 m",
            "Temporal resolution": "one time",
            "Min Latitude": "-90",
            "Max Latitude": "90",
            "Min Longitude": "-180",
            "Max Longitude": "180",
            "Units": "World Reference Base (WRB) class - 118 unique soil classes",
            "Description": "SoilGrids1km and SoilGrids250m are outputs of a system for automated global soil mapping developed within ISRIC's GSIF framework. This system is intended to facilitate global soil data initiatives and to serve as a bridge between global and local soil mapping.",
            "Link to Dataset": "ftp://ftp.soilgrids.org/data/recent/",
            "GEE Dataset": "users/geflanddegradation/toolbox_datasets/stax_sgrid_wrba",
            "Source code": "Imported as assets",
            "Status": "Stored as assets",
            "License": "CC by-SA 4.0",
            "License URL": "https://creativecommons.org/licenses/by-sa/4.0/",
            "Source": "Hengl, T., Mendes de Jesus, J., Heuvelink, G. B.M., Ruiperez Gonzalez, M., Kilibarda, M. et al. (2017) SoilGrids250m: global gridded soil information based on Machine Learning. PLOS One: http://journals.plos.org/plosone/article?id=10.1371/journal.pone.0169748",
            "Comments": ""
        }
    },
    "Forest cover": {
        "Hansen": {
            "Data source": "http://earthenginepartners.appspot.com/science-2013-global-forest",
            "Start year": 2000,
            "End year": 2019,
            "Spatial resolution": "30 m",
            "Temporal resolution": "annual",
            "Min Latitude": -57,
            "Max Latitude": 80,
            "Min Longitude": -180,
            "Max Longitude": 180,
            "Units": "Percent tree cover",
            "Description": "Results from time-series analysis of Landsat images characterizing forest extent and change.Trees are defined as vegetation taller than 5m in height and are expressed as a percentage per output grid cell as ‘2000 Percent Tree Cover’. ‘Forest Cover Loss’ is defined as a stand-replacement disturbance, or a change from a forest to non-forest state, during the period 2000–2019. ‘Forest Cover Gain’ is defined as the inverse of loss, or a non-forest to forest change entirely within the period 2000–2012. ‘Forest Loss Year’ is a disaggregation of total ‘Forest Loss’ to annual time scales. Reference 2000 and 2019 imagery are median observations from a set of quality assessment-passed growing season observations.",
            "Link to Dataset": "http://earthenginepartners.appspot.com/science-2013-global-forest/download_v1.7.html",
            "GEE Dataset": "UMD/hansen/global_forest_change_2019_v1_7",
            "License": "CC by-SA 4.0",
            "License URL": "https://creativecommons.org/licenses/by/4.0/",
            "Source": "Hansen, M. C., P. V. Potapov, R. Moore, M. Hancher, S. A. Turubanova, A. Tyukavina, D. Thau, S. V. Stehman, S. J. Goetz, T. R. Loveland, A. Kommareddy, A. Egorov, L. Chini, C. O. Justice, and J. R. G. Townshend. 2013. “High-Resolution Global Maps of 21st-Century Forest Cover Change.” Science 342 (15 November): 850–53",
            "Comments": ""
        }
    },
    "Woods Hole Research Center": {
        "Total Carbon": {
            "Data source": "https://data.globalforestwatch.org/datasets/aboveground-live-woody-biomass-density?selectedAttribute=shape_Length",
            "Start year": "NA",
            "End year": "NA",
            "Spatial resolution": "30 m",
            "Temporal resolution": "one time",
            "Min Latitude": -90,
            "Max Latitude": 90,
            "Min Longitude": -180,
            "Max Longitude": 180,
            "Units": "Mg ha-1",
            "Description": "This work generated a global-scale, wall-to-wall map of aboveground biomass (AGB) at approximately 30-meter resolution. This data product expands on the methodology presented in Baccini et al. (2012) to generate a global map of aboveground live woody biomass density (megagrams biomass ha-1) at 0.00025-degree (approximately 30-meter) resolution for the year 2000",
            "Link to Dataset": "",
            "GEE Dataset": "users/geflanddegradation/toolbox_datasets/forest_agb_30m_woodhole",
            "License": "Creative Commons CC BY 4.0",
            "License URL": "https://creativecommons.org/licenses/by/4.0/",
            "Source": "https://data.globalforestwatch.org/datasets/aboveground-live-woody-biomass-density",
            "Comments": ""
        }
    },
    "GEOCARBON": {
        "Forest Above Ground Biomass": {
            "Data source": "https://www.wur.nl/en/Research-Results/Chair-groups/Environmental-Sciences/Laboratory-of-Geo-information-Science-and-Remote-Sensing/Research/Integrated-land-monitoring/Forest_Biomass.htm",
            "Start year": "NA",
            "End year": "NA",
            "Spatial resolution": "1 km",
            "Temporal resolution": "one time",
            "Min Latitude": -23.4,
            "Max Latitude": 23.4,
            "Min Longitude": -180,
            "Max Longitude": 180,
            "Units": "Mg ha-1",
            "Description": "An integrated pan‐tropical biomass map using multiple reference datasets",
            "Link to Dataset": "",
            "GEE Dataset": "users/geflanddegradation/toolbox_datasets/forest_agb_1km_geocarbon",
            "License": "The LUCID data is free to download and available for your use as long as the proper references, as specified in the metadata, are applied",
            "License URL": "http://lucid.wur.nl/about",
            "Source": "Avitabile V, Herold M, Heuvelink G, Lewis SL, Phillips OL, Asner GP et al. (2016). An integrated pan-tropical biomass maps using multiple reference datasets. Global Change Biology, 22: 1406–1420. doi:10.1111/gcb.13139",
            "Comments": ""
        }
    },
    "Drivers": {
        "Drivers of Deforestation": {
            "Data source": "",
            "Start year": "NA",
            "End year": "NA",
            "Spatial resolution": "1 km",
            "Temporal resolution": "one time",
            "Min Latitude": -90,
            "Max Latitude": 90,
            "Min Longitude": -180,
            "Max Longitude": 180,
            "Description": "",
            "Link to Dataset": "",
            "GEE Dataset": "projects/ci_geospatial_assets/agric/deforestation_drivers",
            "License": "",
            "License URL": "",
            "Source": ""
        }
    }

}


_SCRIPT_CONFIG = {
    "final-sdg-15-3-1": {
        "run_mode": "local",
        "execution_callable": "LDMP.localexecution.ldn.compute_ldn",
    },
    "urban-change-summary-table": {
        "run_mode": "local",
    },
    "change-biomass-summary-table": {
        "run_mode": "local",
    },
    "local-land-cover": {
        "run_mode": "local",
    },
    "local-total-carbon": {
        "run_mode": "local",
    },
    "local-soil-organic-carbon": {
        "run_mode": "local",
    },
    "time-series": {
        "id": "2a051dcb-b102-44c3-b383-60aa1063ab86",
        "description": "Calculate time series.",
        "run_mode": "remote",
    },
    "land-cover": {
        "id": "92aa0759-ef83-4bc5-9395-bc5609b4780d",
        "description": "Calculate land cover change indicator.",
        "run_mode": "remote",
    },
    "productivity": {
        "id": "5b713a51-f91d-4094-a7fb-67e5992f8b62",
        "description": "Calculate productivity state, performance, and/or trajectory indicators.",
        "run_mode": "remote",
        "trajectory functions": {
            "NDVI trends": {
                "params": {"trajectory_method": "ndvi_trend"},
                "climate types": [],
                "description": "Calculate trend of annually integrated NDVI."
            },
            "Pixel RESTREND": {
                "params": {"trajectory_method": "p_restrend"},
                "climate types": ["Precipitation", "Soil moisture", "Evapotranspiration"],
                "description": "Calculate pixel residual trend (RESTREND of annually integrated NDVI, after removing trend associated with a climate indicator."
            },
            "Water Use Efficiency (WUE)": {
                "params": {"trajectory_method": "ue"},
                "climate types": ["Evapotranspiration"],
                "description": "Calculate water use efficiency (evapotranspiration divided by NDVI)."
            },
            "Rain Use Efficiency (RUE)": {
                "params": {"trajectory_method": "ue"},
                "climate types": ["Precipitation"],
                "description": "Calculate rain use efficiency (precipitation divided by NDVI)."
            }
        }
    },
    "soil-organic-carbon": {
        "id": "d2ce447e-5f15-4577-9230-e4b379870229",
        "description": "Calculate soil organic carbon.",
        "run_mode": "remote",
    },
    "three-sdg-15-3-1-sub-indicators": {
        "id": "4e9e106f-bdc5-4153-afc5-b8378a98670a",
        "description": "Calculate all three SDG sub-indicators in one step.",
        "run_mode": "remote",
    },
    "download-data": {
        "id": "a06c8f97-ffa1-4d4e-ac86-ecf33f1023aa",
        "description": "Download data from Google Earth Engine assets.",
        "run_mode": "remote"
    },
    "total-carbon": {
        "id": "3045dfee-247e-4fe9-bd74-769a1f57aee0",
        "description": "Calculate total carbon in biomass (above and below ground).",
        "run_mode": "remote"
    },
    "urban-area": {
        "id": "88f78043-512d-4b24-9f44-80029d02e294",
        "description": "Calculate urban area.",
        "run_mode": "remote"
    },
    "restoration-biomass": {
        "id": "4bfcc39c-b7df-4e2e-8f08-97be0a48a445",
        "description": "Calculate potential change in biomass with restoration.",
        "run_mode": "remote"
    },
}

KNOWN_SCRIPTS = _load_script_config(_SCRIPT_CONFIG)

_ALGORITHM_CONFIG = [
    {
        "name": "SDG 15.3.1",
        "name_details": "Land degradation",
        "algorithms": [
            {
                "name": "Land Productivity",
                "description": "TODO: Land Productivity long description",
                "scripts": [
                    {
                        "script": KNOWN_SCRIPTS["productivity"],
                        "parametrization_dialogue": "LDMP.calculate_prod.DlgCalculateProd",
                    }
                ],
            },
            {
                "name": "Land Cover",
                "description": "TODO: Land Cover long description",
                "scripts": [
                    {
                        "script": KNOWN_SCRIPTS["local-land-cover"],
                        "parametrization_dialogue": "LDMP.calculate_lc.DlgCalculateLC",
                    },
                    {
                        "script": KNOWN_SCRIPTS["land-cover"],
                        "parametrization_dialogue": "LDMP.calculate_lc.DlgCalculateLC",
                    },
                ],
            },
            {
                "name": "Soil Organic Carbon",
                "description": "TODO: Soil Organic Carbon long description",
                "scripts": [
                    {
                        "script": KNOWN_SCRIPTS["local-soil-organic-carbon"],
                        "parametrization_dialogue": "LDMP.calculate_soc.DlgCalculateSOC",
                    },
                    {
                        "script": KNOWN_SCRIPTS["soil-organic-carbon"],
                        "parametrization_dialogue": "LDMP.calculate_soc.DlgCalculateSOC",
                    },
                ],
            },
            {
                "name": "All SDG 15.3.1 sub-indicators in one step",
                "description": "TODO: All SDG 15.3.1 sub-indicators in one step long description",
                "scripts": [
                    {
                        "script": KNOWN_SCRIPTS["three-sdg-15-3-1-sub-indicators"],
                        "parametrization_dialogue": "LDMP.calculate_ldn.DlgCalculateOneStep",
                    }
                ],
            },
            {
                "name": "Main SDG 15.3.1 indicator",
                "name_details": "Spatial layer and summary table for total boundary",
                "description": "TODO: Main SDG 15.3.1 indicator long description",
                "scripts": [
                    {
                        "script": KNOWN_SCRIPTS["final-sdg-15-3-1"],
                        "parametrization_dialogue": "LDMP.calculate_ldn.DlgCalculateLDNSummaryTableAdmin",
                    }
                ],
            },
        ]
    },
    {
        "name": "SDG 11.3.1",
        "name_details": "Urban Change and Land Consumption",
        "algorithms": [
            {
                "name": "Urban change spatial layer",
                "description": "TODO: Urban change spatial layer long description",
                "scripts": [
                    {
                        "script": KNOWN_SCRIPTS["urban-area"],
                        "parametrization_dialogue": "LDMP.calculate_urban.DlgCalculateUrbanData",
                    },
                ],
            },
            {
                "name": "Urban change summary table for city",
                "description": "TODO: Urban change summary table for city long description",
                "scripts": [
                    {
                        "script": KNOWN_SCRIPTS["urban-change-summary-table"],
                        "parametrization_dialogue": "LDMP.calculate_urban.DlgCalculateUrbanSummaryTable",
                    },
                ],
            },
        ]
    },
    {
        "name": "Experimental",
        "groups": [
            {
                "name": "Total carbon",
                "name_details": "Above and below ground, emissions and deforestation",
                "algorithms": [
                    {
                        "name": "Carbon change spatial layers",
                        "description": "TODO: Carbon change spatial layers long description",
                        "scripts": [
                            {
                                "script": KNOWN_SCRIPTS["local-total-carbon"],
                                "parametrization_dialogue": "LDMP.calculate_tc.DlgCalculateTCData",
                            },
                            {
                                "script": KNOWN_SCRIPTS["total-carbon"],
                                "parametrization_dialogue": "LDMP.calculate_tc.DlgCalculateTCData",
                            },
                        ],
                    },
                    {
                        "name": "Carbon change summary table for boundary",
                        "description": "TODO: Carbon change summary table for boundary long description",
                        "scripts": [
                            {
                                "script": KNOWN_SCRIPTS["total-carbon"],
                                "parametrization_dialogue": "LDMP.calculate_tc.DlgCalculateTCSummaryTable",
                            }
                        ],
                    },
                ]
            },
            {
                "name": "Potential change in biomass due to restoration",
                "name_details": "Above and below ground woody",
                "algorithms": [
                    {
                        "name": "Estimate biomass change",
                        "description": "TODO: Estimate biomass change long description",
                        "scripts": [
                            {
                                "script": KNOWN_SCRIPTS["restoration-biomass"],
                                "parametrization_dialogue": "LDMP.calculate_rest_biomass.DlgCalculateRestBiomassData",
                            }
                        ],
                    },
                    {
                        "name": "Table summarizing likely changes in biomass",
                        "description": "TODO: Table summarizing likely changes in biomass long description",
                        "scripts": [
                            {
                                "script": KNOWN_SCRIPTS["change-biomass-summary-table"],
                                "parametrization_dialogue": "LDMP.calculate_rest_biomass.DlgCalculateRestBiomassSummaryTable",
                            }
                        ],
                    },
                ]
            }
        ]
    },
]


ALGORITHM_TREE = _load_algorithm_config(_ALGORITHM_CONFIG)
settings_manager = SettingsManager()
ADMIN_BOUNDS_KEY = download.get_admin_bounds()
CITIES = download.get_cities()