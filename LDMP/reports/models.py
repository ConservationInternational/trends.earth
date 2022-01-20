"""Data models for the reporting framework."""
from dataclasses import (
    dataclass,
    field
)
from enum import Enum
import typing


class OutputFormat(Enum):
    """Formats for output reports."""
    PDF = 1
    IMAGE = 2


class ReportOutputOptions:
    """Settings for generating output reports.
    """
    output_format: OutputFormat = field(default=OutputFormat.PDF)
    include_qpt: bool = field(default=True)
    format_params: dict = field(default_factory=dict)


class LayoutItemType(Enum):
    """Types of layout items."""
    MAP = 1
    LABEL = 2
    PICTURE = 3


class ItemScopeMapping:
    """Provides a simple mechanism for grouping layout items based on a
    scope, which in most cases refers to an algorithm. This is especially
    useful when a layout contains items linked to different algorithms where
    it becomes important to define how values for each item will be fetched
    from which scope/algorithm.
    """
    # Corresponds to algorithm name
    name: str

    def __init__(self, name: str) -> None:
        self.name = name
        self._type_mapping = dict()

    def add_item_mapping(
            self,
            item_type: LayoutItemType,
            item_id: str
    ) -> None:
        """Group item ids in a list based on their type."""
        if not item_type in self._type_mapping:
            self._type_mapping[item_type] = []
        items = self._type_mapping[item_type]
        items.append(item_id)

    def item_ids_by_type(self, item_type: LayoutItemType) -> list:
        """Get collection of item_ids based on the layout type."""
        if item_type in self._type_mapping:
            return self._type_mapping[item_type]

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
    id: str
    name: str
    description: str
    path: str
    item_scopes: typing.List[ItemScopeMapping]


