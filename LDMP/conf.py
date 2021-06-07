"""Configuration utilities for Trends.Earth QGIS plugin."""

import enum
import typing
from pathlib import Path

import qgis.core

from .algorithms import models as algorithm_models


class AreaSetting(enum.Enum):
    COUNTRY_REGION = "country_region"
    COUNTRY_CITY = "country_city"
    POINT = "point"
    VECTOR_LAYER = "vector_layer"


class Setting(enum.Enum):
    DEBUG = "advanced/debug"
    BINARIES_ENABLED = "advanced/binaries_enabled"
    BINARIES_DIR = "advanced/binaries_folder"
    BASE_DIR = "advanced/base_data_directory"
    POLL_REMOTE = "advanced/poll_remote_server"
    LOCAL_POLLING_FREQUENCY = "advanced/local_polling_frequency_seconds"
    REMOTE_POLLING_FREQUENCY = "advanced/remote_polling_frequency_seconds"
    DOWNLOAD_RESULTS = "advanced/download_remote_results_automatically"
    UPDATE_FREQUENCY_MILLISECONDS = "update_frequency_milliseconds"
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
        Setting.UPDATE_FREQUENCY_MILLISECONDS: 5000,
        Setting.LOCAL_POLLING_FREQUENCY: 10,
        Setting.REMOTE_POLLING_FREQUENCY: 30,
        Setting.DEBUG: False,
        Setting.BINARIES_ENABLED: True,
        Setting.BINARIES_DIR: str(Path.home()),
        Setting.BASE_DIR: str(Path.home() / "trends_earth_data"),
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


settings_manager = SettingsManager()

_ALGORITHM_CONFIG = [
    {
        "type": "group",
        "name": "SDG 15.3.1",
        "name_details": "Land degradation",
        "algorithms": [
            {
                "type": "algorithm",
                "name": "Land Productivity",
                "description": "TODO: Land Productivity long description",
                "run_modes": {
                    "remote": "calculate_prod.DlgCalculateProd",
                }
            },
            {
                "type": "algorithm",
                "name": "Land Cover",
                "description": "TODO: Land Cover long description",
                "run_modes": {
                    "remote": "calculate_lc.DlgCalculateLC",
                }
            },
            {
                "type": "algorithm",
                "name": "Soil Organic Carbon",
                "description": "TODO: Soil Organic Carbon long description",
                "run_modes": {
                    "remote": "calculate_soc.DlgCalculateSOC",
                }
            },
            {
                "type": "algorithm",
                "name": "All SDG 15.3.1 sub-indicators in one step",
                "description": "TODO: All SDG 15.3.1 sub-indicators in one step long description",
                "run_modes": {
                    "remote": "calculate_ldn.DlgCalculateOneStep",
                }
            },
            {
                "type": "algorithm",
                "name": "Main SDG 15.3.1 indicator",
                "name_details": "Spatial layer and summary table for total boundary",
                "description": "TODO: Main SDG 15.3.1 indicator long description",
                "run_modes": {
                    "local": "calculate_ldn.DlgCalculateLDNSummaryTableAdmin",
                }
            },
        ]
    },
    {
        "type": "group",
        "name": "SDG 11.3.1",
        "name_details": "Urban Change and Land Consumption",
        "algorithms": [
            {
                "type": "algorithm",
                "name": "Urban change spatial layer",
                "description": "TODO: Urban change spatial layer long description",
                "run_modes": {
                    "local": "calculate_urban.DlgCalculateUrbanData",
                }
            },
            {
                "type": "algorithm",
                "name": "Urban change summary table for city",
                "description": "TODO: Urban change summary table for city long description",
                "run_modes": {
                    "local": "calculate_urban.DlgCalculateUrbanSummaryTable",
                }
            },
        ]
    },
    {
        "type": "group",
        "name": "Experimental",
        "groups": [
            {
                "type": "group",
                "name": "Total carbon",
                "name_details": "Above and below ground, emissions and deforestation",
                "algorithms": [
                    {
                        "type": "algorithm",
                        "name": "Carbon change spatial layers",
                        "description": "TODO: Carbon change spatial layers long description",
                        "run_modes": {
                            "remote": "calculate_tc.DlgCalculateTCData",
                        }
                    },
                    {
                        "type": "algorithm",
                        "name": "Carbon change summary table for boundary",
                        "description": "TODO: Carbon change summary table for boundary long description",
                        "run_modes": {
                            "remote": "calculate_tc.DlgCalculateTCSummaryTable",
                        }
                    },
                ]
            },
            {
                "type": "group",
                "name": "Potential change in biomass due to restoration",
                "name_details": "Above and below ground woody",
                "algorithms": [
                    {
                        "type": "algorithm",
                        "name": "Estimate biomass change",
                        "description": "TODO: Estimate biomass change long description",
                        "run_modes": {
                            "remote": "calculate_rest_biomass.DlgCalculateRestBiomassData",
                        }
                    },
                    {
                        "type": "algorithm",
                        "name": "Table summarizing likely changes in biomass",
                        "description": "TODO: Table summarizing likely changes in biomass long description",
                        "run_modes": {
                            "remote": "calculate_rest_biomass.DlgCalculateRestBiomassSummaryTable",
                        }
                    },
                ]
            }
        ]
    },
]


def _load_algorithm_config(
        algorithm_config: typing.List[typing.Dict]) -> algorithm_models.AlgorithmGroup:
    top_level_groups = []
    for raw_top_level_group in algorithm_config:
        group = algorithm_models.AlgorithmGroup.deserialize(raw_top_level_group)
        top_level_groups.append(group)
    return algorithm_models.AlgorithmGroup(
        name="root",
        name_details="root_details",
        parent=None,
        groups=top_level_groups
    )


ALGORITHM_TREE = _load_algorithm_config(_ALGORITHM_CONFIG)
