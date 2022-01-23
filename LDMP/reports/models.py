"""Data models for the reporting framework."""
from dataclasses import field
from enum import Enum
import os
import typing
from uuid import uuid4

from marshmallow import post_load
from marshmallow_dataclass import dataclass

from ..utils import slugify


class OutputFormat(Enum):
    """Formats for output reports."""
    PDF = 'pdf'
    IMAGE = 'image'

    def __str__(self):
        # For marshmallow to serialize the value
        return self.value


class ReportOutputOptions:
    """Settings for generating output reports.
    """
    output_format: OutputFormat = field(default=OutputFormat.PDF)
    include_qpt: bool = field(default=True)
    format_params: dict = field(default_factory=dict)


class LayoutItemType(Enum):
    """Types of layout items."""
    MAP = 'map'
    LABEL = 'label'
    PICTURE = 'picture'

    def __str__(self):
        return self.value


class ItemScopeMapping:
    """Provides a simple mechanism for grouping layout items based on a
    scope, which in most cases refers to an algorithm. This is especially
    useful when a layout contains items linked to different algorithms where
    it becomes important to define how values for each item will be fetched
    from which scope/algorithm.
    """
    # Corresponds to algorithm name
    name: str
    type_id_mapping: typing.Dict[str, str] = field(default_factory=dict)

    def __init__(self, name: str, **kwargs) -> None:
        self.name = name
        self.type_id_mapping = kwargs.pop('type_mapping', dict())

    def add_item_mapping(
            self,
            item_type: LayoutItemType,
            item_id: str
    ) -> None:
        """Group item ids in a list based on their type."""
        if not item_type in self.type_id_mapping:
            self.type_id_mapping[item_type] = []

        items = self.type_id_mapping[item_type]
        items.append(item_id)

    def add_map(self, id: str) -> None:
        # Add map_id to the collection
        self.add_item_mapping(LayoutItemType.MAP, id)

    def add_label(self, id: str) -> None:
        # Add label to the collection
        self.add_item_mapping(LayoutItemType.LABEL, id)

    def add_picture(self, id: str) -> None:
        # Add picture item id to the collection
        self.add_item_mapping(LayoutItemType.PICTURE, id)

    def item_ids_by_type(self, item_type: LayoutItemType) -> list:
        """Get collection of item_ids based on the layout type."""
        if item_type in self.type_id_mapping:
            return self.type_id_mapping[item_type]

        return []

    def map_ids(self) -> list:
        """Map ids defined for the current scope."""
        return self.item_ids_by_type(LayoutItemType.MAP)

    def label_ids(self) -> list:
        """Label ids defined for the current scope."""
        return self.item_ids_by_type(LayoutItemType.LABEL)

    def picture_ids(self) -> list:
        """Picture ids defined for the current scope."""
        return self.item_ids_by_type(LayoutItemType.PICTURE)


class ReportTemplateInfo:
    """Contains information about the QGIS layout associated with one or more
    algorithm scopes.
    """
    id: typing.Optional[str]
    name: typing.Optional[str]
    description: typing.Optional[str]
    portrait_path: typing.Optional[str]
    landscape_path: typing.Optional[str]
    item_scopes: typing.Dict[str, ItemScopeMapping] = field(default_factory=dict)

    def __init__(self, **kwargs) -> None:
        self.id = kwargs.pop('id', str(uuid4()))
        self.name = kwargs.pop('name', '')
        self.description = kwargs.pop('description', '')
        self.portrait_path = kwargs.pop('portrait_path', '')
        self.landscape_path = kwargs.pop('landscape_path', '')
        self.item_scopes = kwargs.pop('scopes', dict())
        self._abs_portrait_path = ''
        self._abs_landscape_path = ''

    def add_scope_mapping(self, item_scope: ItemScopeMapping) -> None:
        self.item_scopes[item_scope.name] = item_scope

    def scope_mapping_by_name(self, name: str) -> ItemScopeMapping:
        return self.item_scopes.get(name, None)

    def update_paths(self, templates_dir) -> None:
        # set absolute paths for portrait and landscape templates
        concat_path = lambda file_name: os.path.normpath(
            '{0}{1}{2}'.format(
                templates_dir,
                os.sep,
                file_name
            )
        )
        self._abs_portrait_path = concat_path(self.portrait_path)
        self._abs_landscape_path = concat_path(self.landscape_path)

    @property
    def absolute_template_paths(self) -> typing.Tuple[str]:
        """Absolute paths for portrait and landscape templates."""
        return self._abs_portrait_path, self._abs_landscape_path

    @property
    def is_multi_scope(self) -> bool:
        """True if the template is for compound reports."""
        return True if len(self.item_scopes) > 1 else False

    def contains_scope(self, name: str) -> bool:
        """
        True if the template contains a scope mapping with the given name.
        """
        return True if name in self.item_scopes else False


@dataclass
class ReportConfiguration:
    """Contains template and output settings for a report.
    """
    name: typing.Optional[str]
    template_info: typing.Optional[ReportTemplateInfo]
    output_options: typing.Optional[ReportOutputOptions]

    class Meta:
        ordered = True

    def __init__(
            self,
            template_info: ReportTemplateInfo,
            output_options: ReportOutputOptions,
            **kwargs
    ) -> None:
        self.template_info = template_info
        self.output_options = output_options
        self.name = self._set_name() or kwargs.pop('name')

    def _set_name(self) -> str:
        if self.template_info:
            return slugify(self.template_info.name)

        return ''

    def update_paths(self, template_dir):
        # Convenience function for updating absolute paths for template files.
        self.template_info.update_paths(template_dir)




