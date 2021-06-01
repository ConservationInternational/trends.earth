import enum
import typing
from pathlib import Path

import qgis.core


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
    }

    def __init__(self):
        self._settings = qgis.core.QgsSettings()
        self._initialize_settings()

    @property
    def base_path(self):
        return self._base_path

    def get_value(self, key: Setting):
        type_ = type(self.DEFAULT_SETTINGS[key])
        return self._settings.value(
            f"{self.base_path}/{key.value}", self.DEFAULT_SETTINGS[key], type=type_)

    def write_value(self, key: Setting, value: typing.Any):
        return self._settings.setValue(f"{self.base_path}/{key.value}", value)

    def _initialize_settings(self):
        for setting, default_value in self.DEFAULT_SETTINGS.items():
            current_value = self._settings.value(f"{self.base_path}/{setting.value}")
            if current_value is None:
                self.write_value(setting, self.DEFAULT_SETTINGS[setting])


settings_manager = SettingsManager()