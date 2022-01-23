"""Reads and validates templates."""

import json
import os
import typing

from marshmallow.exceptions import ValidationError
from qgis.PyQt.QtCore import QFile
from qgis.core import Qgis

from ..conf import report_templates_dir
from ..logger import log
from .models import ReportConfiguration


class TemplateManager:
    """
    Reads and validates templates in template settings file.
    """
    def __init__(self, load_on_init=True):
        self._configs = []
        self._template_dir = report_templates_dir
        self._template_file_exists = False
        if QFile.exists(self.path):
            self._template_file_exists = True
        else:
            log(
                'Report templates file \'{0}\' not found.'.format(
                    self.path
                ),
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
        return '{0}{1}templates.json'.format(self._template_dir, os.sep)

    @property
    def configurations(self) -> typing.List[ReportConfiguration]:
        """
        Returns a collection of template configuration objects.
        """
        return self._configs

    def configs_by_template_name(
            self,
            name
    ) -> typing.List[ReportConfiguration]:
        """
        Returns report config objects with template info objects matching the
        given name.
        """
        return [rc for rc in self._configs if rc.template_info.name == name]

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
                err_msg = ', '.join(ve.messages['_schema'])
                log(err_msg)
            except Exception as exc:
                log(str(exc))
            finally:
                tf.close()


template_manager = TemplateManager()