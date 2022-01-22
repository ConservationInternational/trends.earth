"""Reads and validates templates."""

import os
from qgis.PyQt.QtCore import QFile
from qgis.core import Qgis

from ..conf import report_templates_dir
from ..logger import log


class TemplateManager:
    """
    Reads and validates templates in template settings file.
    """
    def __init__(self, load_on_init=True):
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

    def load(self):
        """
        Loads template configuration.
        """
        if not self.contains_settings:
            return


template_manager = TemplateManager()