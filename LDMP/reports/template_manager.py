"""Reads and validates templates."""

import json
import os
import typing

from marshmallow.exceptions import ValidationError
from qgis.core import Qgis

from ..logger import log
from .models import ReportConfiguration
from ..utils import FileUtils


class TemplateManager:
    """
    Reads and validates templates in template settings file.
    """
    def __init__(self, load_on_init=True):
        self._configs = []
        self._template_dir = FileUtils.report_templates_dir()
        self._template_file_exists = False
        if os.path.exists(self.path):
            self._template_file_exists = True
        else:
            log(
                f'Report templates file {self.path} not found.',
                Qgis.Warning
            )

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
        return f'{self._template_dir}{os.sep}templates.json'

    @property
    def configurations(self) -> typing.List[ReportConfiguration]:
        """
        Returns a collection of template configuration objects.
        """
        return self._configs

    def configs_by_template_name(
            self,
            name: str,
    ) -> typing.List[ReportConfiguration]:
        """
        Returns report config objects with template info objects matching the
        given name.
        """
        return [rc for rc in self._configs if rc.template_info.name == name]

    def configs_by_template_id(
            self,
            id: str
    ) -> typing.List[ReportConfiguration]:
        # Returns report configs by template id.
        return [rc for rc in self._configs if rc.template_info.id == id]

    def multi_scope_configs(self) -> typing.List[ReportConfiguration]:
        """
        Returns a list of report configurations with more than one item scope
        defined. These are used in compound reports.
        """
        return [
            rc for rc in self._configs
            if rc.template_info.is_multi_scope
        ]

    def single_scope_configs(self) -> typing.List[ReportConfiguration]:
        """
        Returns a list of report configurations with one scope only.
        """
        return [
            rc for rc in self._configs
            if not rc.template_info.is_multi_scope
        ]

    @classmethod
    def configs_by_scope_name(
            cls,
            name: str,
            configs: typing.List[ReportConfiguration]
    ) -> typing.List[ReportConfiguration]:
        """
        Returns a list of report configurations whose template objects
        contain the given scope name.
        """
        return [
            rc for rc in configs
            if rc.template_info.contains_scope(name)
        ]

    def clear(self):
        """Clears collection of config objects."""
        self._configs = []

    def load(self, clear_first=True):
        """
        Loads template configuration.
        """
        if not self.contains_settings:
            return

        if clear_first:
            self.clear()

        with open(self.path) as tf:
            try:
                configs = json.load(tf)
                for conf in configs:
                    cf = ReportConfiguration.Schema().load(conf)
                    cf.update_paths(self._template_dir)
                    self._configs.append(cf)
            except ValidationError as ve:
                err_msg = str(ve.messages)
                log(err_msg, Qgis.Warning)
            except Exception as exc:
                log(str(exc), Qgis.Warning)
            finally:
                tf.close()


template_manager = TemplateManager()