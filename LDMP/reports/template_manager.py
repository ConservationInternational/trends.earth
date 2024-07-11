"""Reads and validates templates."""

import json
import os
import typing
from enum import Enum

from distutils.dir_util import copy_tree
from distutils.errors import DistutilsFileError
from marshmallow.exceptions import ValidationError
from qgis.core import Qgis

from ..conf import Setting
from ..conf import settings_manager
from ..logger import log
from ..utils import FileUtils
from .models import ReportConfiguration


class ConfigurationSource(Enum):
    PLUGIN = 0
    DATA_DIR = 1


class TemplateManager:
    """
    Reads and validates templates in template settings file.
    """

    def __init__(self, load_on_init=True):
        self._configs = []
        self._template_dir = FileUtils.report_templates_dir()
        self._user_temp_search_path = settings_manager.get_value(
            Setting.REPORT_TEMPLATE_SEARCH_PATH
        )
        self._data_report_dir = ""
        base_data_dir = settings_manager.get_value(Setting.BASE_DIR)
        if base_data_dir:
            self._data_report_dir = f"{base_data_dir}/reports/templates"

        # Default path for saving multi-dataset reports
        self._default_output_dir = f"{base_data_dir}/reports/outputs"

        self._use_plugin_report_config = True

        self._template_file_exists = False
        if os.path.exists(self.path):
            self._template_file_exists = True
        else:
            log(f"Report templates file {self.path} not found.", Qgis.Warning)

        if load_on_init:
            self.load()

    @property
    def contains_settings(self) -> bool:
        """
        Indicates if the templates file exists.
        """
        return self._template_file_exists

    @property
    def path(self) -> str:
        """
        Returns the path to the template file.
        """
        if self._use_plugin_report_config:
            rpt_conf_path = f"{self._template_dir}{os.sep}templates.json"
        else:
            rpt_conf_path = f"{self._data_report_dir}{os.sep}templates.json"

        return rpt_conf_path

    @property
    def configurations(self) -> typing.List[ReportConfiguration]:
        """
        Returns a collection of template configuration objects.
        """
        return self._configs

    @property
    def data_report_path(self) -> str:
        """
        Returns the directory containing report configuration and templates
        under the base data directory.
        """
        return self._data_report_dir

    @property
    def default_output_path(self) -> str:
        """
        Returns the default output path for saving multi-dataset reports.
        """
        return self._default_output_dir

    def configs_by_template_name(
        self,
        name: str,
    ) -> typing.List[ReportConfiguration]:
        """
        Returns report config objects with template info objects matching the
        given name.
        """
        return [rc for rc in self._configs if rc.template_info.name == name]

    def configs_by_template_id(self, id: str) -> typing.List[ReportConfiguration]:
        # Returns report configs by template id.
        return [rc for rc in self._configs if rc.template_info.id == id]

    def multi_scope_configs(self) -> typing.List[ReportConfiguration]:
        """
        Returns a list of report configurations with more than one item scope
        defined. These are used in compound reports.
        """
        return [rc for rc in self._configs if rc.template_info.is_multi_scope]

    def single_scope_configs(self) -> typing.List[ReportConfiguration]:
        """
        Returns a list of report configurations with one scope only.
        """
        return [rc for rc in self._configs if not rc.template_info.is_multi_scope]

    @classmethod
    def configs_by_scope_name(
        cls, name: str, configs: typing.List[ReportConfiguration]
    ) -> typing.List[ReportConfiguration]:
        """
        Returns a list of report configurations whose template objects
        contain the given scope name.
        """
        return [rc for rc in configs if rc.template_info.contains_scope(name)]

    def clear(self):
        """Clears collection of config objects."""
        self._configs = []

    def switch_source(self, config_source: ConfigurationSource):
        # Switch report configuration source to either the one in the plugin
        # dir or under the one in the user-defined base directory.
        if config_source == ConfigurationSource.PLUGIN:
            self._use_plugin_report_config = True
            self.load(True)
        else:
            self._use_plugin_report_config = False
            self.copy_configuration()
            self.create_default_output_dir()
            self.load(True)

    def use_plugin_config_source(self):
        # Use configuration and templates in plugin directory.
        self.switch_source(ConfigurationSource.PLUGIN)

    def use_data_dir_config_source(self):
        # Use configuration and templates in plugin directory.
        self.switch_source(ConfigurationSource.DATA_DIR)

    def create_default_output_dir(self):
        """
        Creates a default output path for saving multi-dataset reports.
        """
        try:
            os.mkdir(self._default_output_dir)
        except FileExistsError:
            log(
                f"Default report output directory already exists: "
                f"{self._default_output_dir!r}"
            )

    def copy_configuration(self) -> bool:
        """
        Copies folder containing report configuration and corresponding
        templates to the data base directory. If there is an existing
        directory then the operation will terminate and return False.
        """
        if not self._data_report_dir:
            log(
                "Unable to copy report configuration. Path to the report "
                "directory in the base data folder could not be determined.",
                Qgis.Warning,
            )
            return False

        # Check if the directory exists
        if os.path.exists(self._data_report_dir):
            return False

        try:
            _ = copy_tree(self._template_dir, self._data_report_dir)
        except DistutilsFileError as dfe:
            msg = f"Unable to copy report configuration. {dfe!s}"
            log(msg, Qgis.Warning)
            return False

        return True

    def load(self, clear_first=True):
        """
        Loads template configuration.
        """
        if not self.contains_settings:
            return

        if clear_first:
            self.clear()

        dest_dir = (
            self._template_dir
            if self._use_plugin_report_config
            else self._data_report_dir
        )

        with open(self.path) as tf:
            try:
                configs = json.load(tf)
                for conf in configs:
                    cf = ReportConfiguration.Schema().load(conf)
                    if self._user_temp_search_path:
                        cf.update_paths(dest_dir, self._user_temp_search_path)
                    else:
                        cf.update_paths(dest_dir)
                    self._configs.append(cf)
            except ValidationError as ve:
                err_msg = str(ve.messages)
                log(err_msg, Qgis.Warning)
            except Exception as exc:
                log(str(exc), Qgis.Warning)
            finally:
                tf.close()


template_manager = TemplateManager()
