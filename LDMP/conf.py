"""Configuration utilities for Trends.Earth QGIS plugin."""

import os
import json
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
    DEFINITIONS_DIRECTORY = "advanced/definitions_directory"


class SettingsManager:
    _settings: qgis.core.QgsSettings
    _base_path: str = "trends_earth"
    _base_data_path: str = "trends_earth_data"

    DEFAULT_SETTINGS = {
        Setting.UPDATE_FREQUENCY_MILLISECONDS: 10000,
        Setting.LOCAL_POLLING_FREQUENCY: 30,
        Setting.LOCAL_CONTEXT_SEPARATOR: "-*-*-*-local_context-*-*-*-",
        Setting.REMOTE_POLLING_FREQUENCY: 3 * 60,
        Setting.DEBUG: False,
        Setting.BINARIES_ENABLED: False,
        Setting.BINARIES_DIR: str(Path.home()),
        Setting.BASE_DIR: str(Path.home() / _base_data_path),
        Setting.DEFINITIONS_DIRECTORY: str(
            Path.home() / _base_data_path / "definitions"),
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


datasets_file = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    'data',
    'gee_datasets.json'
)
with open(datasets_file) as f:
    REMOTE_DATASETS = json.load(f)


script_file = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    'data',
    'scripts.json'
)
with open(script_file) as f:
    _SCRIPT_CONFIG = json.load(f)

KNOWN_SCRIPTS = _load_script_config(_SCRIPT_CONFIG)

_ALGORITHM_CONFIG = [
    {
        "name": "SDG 15.3.1",
        "name_details": "Land degradation",
        "algorithms": [
            {
                "id": "bdad3786-bc36-46aa-8e3d-d6cede915cef",
                "name": "All SDG 15.3.1 sub-indicators in one step",
                "description": (
                    "Calculate Productivity, Land Cover and Soil Organic carbon "
                    "sub-indicators simultaneously"
                ),
                "scripts": [
                    {
                        "script": KNOWN_SCRIPTS["sdg-15-3-1-sub-indicators"],
                        "parametrization_dialogue": "LDMP.calculate_ldn.DlgCalculateOneStep",
                    }
                ],
            },
            {
                "id": "fe1cffa7-33f7-4148-ac7b-fc726402d59d",
                "name": "Main SDG 15.3.1 indicator",
                "name_details": "Spatial layer and summary table for total boundary",
                "description": (
                    "Proportion of land that is degraded over total land area"
                ),
                "scripts": [
                    {
                        "script": KNOWN_SCRIPTS["sdg-15-3-1-summary"],
                        "parametrization_dialogue": "LDMP.calculate_ldn.DlgCalculateLDNSummaryTableAdmin",
                    }
                ],
            },
            {
                "id": "e25d2a72-2274-45fa-9b69-74e87873054e",
                "name": "Land Productivity",
                "description": (
                    "Land productivity is the biological productive capacity of the "
                    "land, the source of all the food, fiber and fuel that sustains "
                    "humans"
                ),
                "scripts": [
                    {
                        "script": KNOWN_SCRIPTS["productivity"],
                        "parametrization_dialogue": "LDMP.calculate_prod.DlgCalculateProd",
                    }
                ],
            },
            {
                "id": "277f87e6-5362-4533-ab1d-c28251576884",
                "name": "Land Cover",
                "description": (
                    "Land cover is the physical material at the surface of the earth. "
                    "Land covers include grass, asphalt, trees, bare ground, water, "
                    "etc"
                ),
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
                "id": "f32fd29b-2af8-4564-9189-3dd440758be6",
                "name": "Soil Organic Carbon",
                "description": (
                    "Soil organic carbon is a measureable component of soil organic "
                    "matter"
                ),
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
        ]
    },
    {
        "name": "SDG 11.3.1",
        "name_details": "Urban Change and Land Consumption",
        "algorithms": [
            {
                "id": "bdce0a12-c5ab-485b-ac47-278cedbce789",
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
                "id": "748780b4-39bb-4460-b203-0f2367d7c699",
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
                        "id": "96f243a2-c8bd-436a-9775-424f20a1b188",
                        "name": "Carbon change spatial layers",
                        "description": "TODO: Carbon change spatial layers long description",
                        "scripts": [
                            # TODO: enable and tweak this when support for local calculations of total carbon is implemented
                            # {
                            #     "script": KNOWN_SCRIPTS["local-total-carbon"],
                            #     "parametrization_dialogue": "LDMP.calculate_tc.DlgCalculateTCData",
                            # },
                            {
                                "script": KNOWN_SCRIPTS["total-carbon"],
                                "parametrization_dialogue": "LDMP.calculate_tc.DlgCalculateTCData",
                            },
                        ],
                    },
                    {
                        "id": "a753f2c9-be4c-4d97-9e21-09b8882e8899",
                        "name": "Carbon change summary table for boundary",
                        "description": "TODO: Carbon change summary table for boundary long description",
                        "scripts": [
                            {
                                "script": KNOWN_SCRIPTS["total-carbon-summary"],
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
                        "id": "61839d52-0d81-428d-90e6-83ea5ed3c032",
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
                        "id": "cb425356-09cf-4390-89dc-8542cdf0805c",
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
