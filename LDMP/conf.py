"""Configuration utilities for Trends.Earth QGIS plugin."""
import enum
import json
import os
import typing
from pathlib import Path

import qgis.core
from qgis.PyQt import QtCore
from te_schemas.algorithms import ExecutionScript

from . import download
from .algorithms import models as algorithm_models
from .reports.utils import default_report_disclaimer
from .utils import FileUtils


class tr_conf(QtCore.QObject):
    def tr(self, txt):
        return QtCore.QCoreApplication.translate(self.__class__.__name__, txt)


tr_conf = tr_conf()


TR_ALL_REGIONS = tr_conf.tr("All regions")


class AreaSetting(enum.Enum):
    COUNTRY_REGION = "country_region"
    COUNTRY_CITY = "country_city"
    POINT = "point"
    VECTOR_LAYER = "vector_layer"


class Setting(enum.Enum):
    LOCAL_POLLING_FREQUENCY = "private/local_polling_frequency_seconds"
    UPDATE_FREQUENCY_MILLISECONDS = "private/update_frequency_milliseconds"
    UNKNOWN_AREA_OF_INTEREST = "private/unknown_area_of_interest"
    PRIOR_LOCALE = "private/prior_locale"

    DEBUG = "advanced/debug"
    BINARIES_ENABLED = "advanced/binaries_enabled"
    BINARIES_DIR = "advanced/binaries_folder"
    FILTER_JOBS_BY_BASE_DIR = "advanced/FILTER_JOBS_BY_BASE_DIR"
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
    REPORT_TEMPLATE_SEARCH_PATH = "report/template_search_path"
    REPORT_ORG_LOGO_PATH = "report/org_logo_path"
    REPORT_ORG_NAME = "report/org_name"
    REPORT_FOOTER = "report/footer"
    REPORT_DISCLAIMER = "report/disclaimer"
    REPORT_LOG_WARNING = "report/log_warning"
    LC_CLASSES = "land_cover/user_classes"
    LC_MAX_CLASSES = "land_cover/max_classes"
    LC_LAST_DIR = "land_cover/last_dir"
    LC_IPCC_NESTING = "land_cover/ipcc_nesting"
    LC_ESA_NESTING = "land_cover/esa_nesting"


class SettingsManager:
    _settings: qgis.core.QgsSettings
    _base_path: str = "trends_earth"
    _base_data_path: str = "trends_earth_data"

    DEFAULT_SETTINGS = {
        Setting.UPDATE_FREQUENCY_MILLISECONDS: 10000,
        Setting.LOCAL_POLLING_FREQUENCY: 30,
        Setting.UNKNOWN_AREA_OF_INTEREST: "unknown-area",
        Setting.PRIOR_LOCALE: "unknown",
        Setting.REMOTE_POLLING_FREQUENCY: 3 * 60,
        Setting.DEBUG: False,
        Setting.FILTER_JOBS_BY_BASE_DIR: True,
        Setting.BINARIES_ENABLED: False,
        Setting.BINARIES_DIR: str(Path.home()),
        Setting.BASE_DIR: str(Path.home() / _base_data_path),
        Setting.DEFINITIONS_DIRECTORY: str(
            Path.home() / _base_data_path / "definitions"
        ),
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
        Setting.REPORT_TEMPLATE_SEARCH_PATH: "",
        Setting.REPORT_ORG_LOGO_PATH: FileUtils.te_logo_path(),
        Setting.REPORT_ORG_NAME: "",
        Setting.REPORT_FOOTER: "",
        Setting.REPORT_DISCLAIMER: default_report_disclaimer(),
        Setting.REPORT_LOG_WARNING: False,
        Setting.LC_CLASSES: "",
        Setting.LC_MAX_CLASSES: 38,
        Setting.LC_LAST_DIR: "",
        Setting.LC_IPCC_NESTING: "",
        Setting.LC_ESA_NESTING: "",
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
                f"{self.base_path}/{key.value}", self.DEFAULT_SETTINGS[key], type=type_
            )

        return result

    def write_value(self, key: Setting, value: typing.Any):
        return self._settings.setValue(f"{self.base_path}/{key.value}", value)

    def _initialize_settings(self):
        for setting, default_value in self.DEFAULT_SETTINGS.items():
            current_value = self._settings.value(f"{self.base_path}/{setting.value}")

            if current_value is None:
                self.write_value(setting, self.DEFAULT_SETTINGS[setting])


def _load_script_config(
    script_config: typing.Dict,
) -> typing.Dict[str, ExecutionScript]:
    result = {}

    for raw_config in script_config:
        script = ExecutionScript.Schema().load(raw_config)
        result[script.name] = script

    return result


def _load_algorithm_config(
    algorithm_config: typing.List[typing.Dict],
) -> algorithm_models.AlgorithmGroup:
    top_level_groups = []

    for raw_top_level_group in algorithm_config:
        group = algorithm_models.AlgorithmGroup.deserialize(raw_top_level_group)
        top_level_groups.append(group)

    return algorithm_models.AlgorithmGroup(
        name="root", name_details="root_details", parent=None, groups=top_level_groups
    )


datasets_file = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), "data", "gee_datasets.json"
)
with open(datasets_file) as f:
    REMOTE_DATASETS = json.load(f)


script_file = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), "data", "scripts.json"
)
with open(script_file) as f:
    _SCRIPT_CONFIG = json.load(f)

KNOWN_SCRIPTS = _load_script_config(_SCRIPT_CONFIG)

_ALGORITHM_CONFIG = [
    {
        "name": "SDG 15.3.1",
        "name_details": tr_conf.tr("Land degradation"),
        "algorithms": [
            {
                "id": "bdad3786-bc36-46aa-8e3d-d6cede915cef",
                "name": tr_conf.tr("Sub-indicators for SDG 15.3.1"),
                "description": tr_conf.tr(
                    "Calculate SDG 15.3.1 sub-indicators (required prior to "
                    "15.3.1 indicator calculation)"
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
                "name": tr_conf.tr("Indicator for SDG 15.3.1"),
                "name_details": tr_conf.tr(
                    "Spatial layer and summary table for total boundary"
                ),
                "description": tr_conf.tr(
                    "Calculate SDG 15.3.1 indicator from productivity, land "
                    "cover, and soil organic carbon sub-indicators"
                ),
                "scripts": [
                    {
                        "script": KNOWN_SCRIPTS["sdg-15-3-1-summary"],
                        "parametrization_dialogue": "LDMP.calculate_ldn.DlgCalculateLDNSummaryTableAdmin",
                    }
                ],
            },
            # {
            #     "id": "7f7df50d-6069-4028-9252-878fcc5d86d7",
            #     "name": tr_conf.tr("SDG 15.3.1 error recode (false positive/negative)"),
            #     "description": (
            #         tr_conf.tr(
            #             "Correct any known errors (false positives or negatives) "
            #             "in an SDG 15.3.1 Indicator layer. This can be used to correct "
            #             "misclassifications using expert knowledge or field data."
            #         )
            #     ),
            #     "scripts": [
            #         {
            #             "script": KNOWN_SCRIPTS["unccd-report"],
            #             "parametrization_dialogue": "LDMP.calculate_ldn.DlgCalculateLDNErrorRecode",
            #         },
            #     ],
            # },
            {
                "id": "e25d2a72-2274-45fa-9b69-74e87873054e",
                "name": tr_conf.tr("Land productivity"),
                "description": (
                    tr_conf.tr(
                        "Land productivity is the biological productive "
                        "capacity of land"
                    )
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
                "name": tr_conf.tr("Land cover change"),
                "description": tr_conf.tr(
                    "Land cover is the physical material at the surface of "
                    "the earth. "
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
                "name": tr_conf.tr("Soil Organic Carbon"),
                "description": (
                    tr_conf.tr(
                        "Soil organic carbon is a measure of soil organic " "matter"
                    )
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
        ],
    },
    {
        "name": tr_conf.tr("Drought"),
        "name_details": tr_conf.tr("Vulnerability and exposure"),
        "algorithms": [
            {
                "id": "afb8d95a-20a5-11ec-9621-0242ac130002",
                "name": tr_conf.tr("Drought vulnerability"),
                "description": tr_conf.tr(
                    "Calculate indicators of drought vulnerability "
                    "consistent with UNCCD SO3 Good Practice Guidance"
                ),
                "scripts": [
                    {
                        "script": KNOWN_SCRIPTS["drought-vulnerability"],
                        "parametrization_dialogue": "LDMP.calculate_drought_vulnerability.DlgCalculateDrought",
                    },
                ],
            },
            {
                "id": "bb5df452-20a5-11ec-9621-0242ac130002",
                "name": tr_conf.tr("Drought vulnerability summary table"),
                "description": tr_conf.tr(
                    "Summarize drought indicators in alignment with UNCCD "
                    "SO3 reporting requirements"
                ),
                "scripts": [
                    {
                        "script": KNOWN_SCRIPTS["drought-vulnerability-summary"],
                        "parametrization_dialogue": "LDMP.calculate_drought_vulnerability.DlgCalculateDroughtSummary",
                    },
                ],
            },
        ],
    },
    {
        "name": tr_conf.tr("UNCCD Reporting"),
        "name_details": tr_conf.tr("Summarize data for reporting"),
        "algorithms": [
            # {
            #     "id": "052b3fbc-20a7-11ec-9621-0242ac130002",
            #     "name": "Default data for UNCCD reporting",
            #     "description": (
            #         "Generate default datasets used in the UNCCD "
            #         "2021 reporting cycle"
            #     ),
            #     "scripts": [
            #         {
            #             "script": KNOWN_SCRIPTS["unccd-default-data"],
            #             "parametrization_dialogue": "LDMP.calculate_unccd.DlgCalculateUNCCD",
            #         },
            #     ],
            # },
            {
                "id": "5293b2b2-d90f-4f1f-9556-4b0fe1c6ba91",
                "name": tr_conf.tr("Generate data package for UNCCD reporting"),
                "description": tr_conf.tr(
                    "Summarize Strategic Objective (SO) 1, SO2, and SO3 "
                    "datasets in proper format for submission to UNCCD for "
                    "2021 reporting cycle"
                ),
                "scripts": [
                    {
                        "script": KNOWN_SCRIPTS["unccd-report"],
                        "parametrization_dialogue": "LDMP.calculate_unccd.DlgCalculateUNCCDReport",
                    },
                ],
            },
        ],
    },
    {
        "name": tr_conf.tr("SDG 11.3.1"),
        "name_details": tr_conf.tr("Urban change and land consumption"),
        "algorithms": [
            {
                "id": "bdce0a12-c5ab-485b-ac47-278cedbce789",
                "name": tr_conf.tr("Urban change spatial layer"),
                "description": tr_conf.tr(
                    "Calculate indicators of change in urban extent "
                    "(SDG 11.3.1 indicator)"
                ),
                "scripts": [
                    {
                        "script": KNOWN_SCRIPTS["urban-area"],
                        "parametrization_dialogue": "LDMP.calculate_urban.DlgCalculateUrbanData",
                    },
                ],
            },
            {
                "id": "748780b4-39bb-4460-b203-0f2367d7c699",
                "name": tr_conf.tr("Urban change summary table for city"),
                "description": tr_conf.tr(
                    "Calculate table summarizing SDG indicator 11.3.1"
                ),
                "scripts": [
                    {
                        "script": KNOWN_SCRIPTS["urban-change-summary-table"],
                        "parametrization_dialogue": "LDMP.calculate_urban.DlgCalculateUrbanSummaryTable",
                    },
                ],
            },
        ],
    },
    {
        "name": tr_conf.tr("Experimental"),
        "groups": [
            {
                "name": tr_conf.tr("Calculate change in total carbon"),
                "name_details": tr_conf.tr(
                    "Above and below ground, emissions and deforestation"
                ),
                "algorithms": [
                    {
                        "id": "96f243a2-c8bd-436a-9775-424f20a1b188",
                        "name": tr_conf.tr("Calculate change in carbon"),
                        "description": tr_conf.tr(
                            "Calculate total carbon (above and below-ground) "
                            "and emissions from deforestation"
                        ),
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
                        "name": tr_conf.tr("Change in carbon summary table"),
                        "description": tr_conf.tr(
                            "Calculate table summarizing change in " "total carbon"
                        ),
                        "scripts": [
                            {
                                "script": KNOWN_SCRIPTS["total-carbon-summary"],
                                "parametrization_dialogue": "LDMP.calculate_tc.DlgCalculateTCSummaryTable",
                            }
                        ],
                    },
                ],
            },
            {
                "name": tr_conf.tr("Potential change in biomass due to restoration"),
                "name_details": tr_conf.tr("Above and below ground woody"),
                "algorithms": [
                    {
                        "id": "61839d52-0d81-428d-90e6-83ea5ed3c032",
                        "name": tr_conf.tr("Estimate potential impacts of restoration"),
                        "description": tr_conf.tr(
                            "Estimate potential change in biomass due to " "restoration"
                        ),
                        "scripts": [
                            {
                                "script": KNOWN_SCRIPTS["restoration-biomass"],
                                "parametrization_dialogue": "LDMP.calculate_rest_biomass.DlgCalculateRestBiomassData",
                            }
                        ],
                    },
                    {
                        "id": "cb425356-09cf-4390-89dc-8542cdf0805c",
                        "name": tr_conf.tr(
                            "Table summarizing likely changes in biomass"
                        ),
                        "description": tr_conf.tr(
                            "Generate table summarizing potential change "
                            "in biomass due to restoration"
                        ),
                        "scripts": [
                            {
                                "script": KNOWN_SCRIPTS["change-biomass-summary-table"],
                                "parametrization_dialogue": "LDMP.calculate_rest_biomass.DlgCalculateRestBiomassSummaryTable",
                            }
                        ],
                    },
                ],
            },
        ],
    },
]


ALGORITHM_TREE = _load_algorithm_config(_ALGORITHM_CONFIG)
settings_manager = SettingsManager()
ADMIN_BOUNDS_KEY = download.get_admin_bounds()
CITIES = download.get_cities()
