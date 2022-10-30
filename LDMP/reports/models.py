"""Data models for the reporting framework."""
import hashlib
import json
import os
import re
import typing
import unicodedata
from dataclasses import field
from enum import Enum
from uuid import uuid4

from marshmallow import post_load
from marshmallow_dataclass import dataclass

from ..jobs.models import Job


def slugify(value, allow_unicode=False):
    """
    Taken from https://github.com/django/django/blob/master/django/utils/text.py
    Convert to ASCII if 'allow_unicode' is False. Convert spaces or repeated
    dashes to single dashes. Remove characters that aren't alphanumerics,
    underscores, or hyphens. Convert to lowercase. Also strip leading and
    trailing whitespace, dashes, and underscores.
    """
    value = str(value)

    if allow_unicode:
        value = unicodedata.normalize("NFKC", value)
    else:
        value = (
            unicodedata.normalize("NFKD", value)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
    value = re.sub(r"[^\w\s-]", "", value.lower())

    return re.sub(r"[-\s]+", "-", value).strip("-_")


class OutputFormatType(Enum):
    """Formats for output reports."""

    PDF = "pdf"
    IMAGE = "image"

    def __str__(self):
        # For marshmallow to serialize the value
        return self.value


class TemplateType(Enum):
    """Whether to print simple, full or both."""

    SIMPLE = "simple"
    FULL = "full"
    ALL = "all"

    def __str__(self):
        return self.value


@dataclass
class ReportOutputFormat:
    """
    Format information for the report output.
    For:
        - PDF output: specify "format_type":"PDF"
        - Image output: specify "format_type":"IMAGE" and
            "format_params":{
                "image_type":"jpg" or "jpeg" or "png" or "bmp"
         }
    Please note that the 'format_type' should be in uppercase.
    """

    format_type: OutputFormatType = field(default=OutputFormatType.PDF)
    params: dict = field(default_factory=dict)

    def file_extension(self) -> str:
        """
        If output format is IMAGE and its type is not defined, it will
        default to PNG.
        """
        if self.format_type == OutputFormatType.PDF:
            return "pdf"
        else:
            img_type = self.params.get("image_type", "PNG")
            return img_type.lower()


@dataclass
class ReportOutputOptions:
    """
    Output options for the report export with support for more than one
    format. If 'view_format' is not specified, then the first output format
    (in the configuration) is used.
    """

    formats: typing.List[ReportOutputFormat]
    template_type: TemplateType = field(default=TemplateType.ALL)
    # This will search for the matching type in 'formats'
    view_format_type: OutputFormatType = field(default=OutputFormatType.PDF)

    def view_format(self) -> ReportOutputFormat:
        """
        Uses the 'view_format_type' to search for a matching output format.
        This is used by the UI to determine the file format that should be
        used for viewing the output report. If there is no matching format,
        then the first item in 'formats' is used.
        """
        if len(self.formats) == 0:
            return None

        matching_formats = [
            f for f in self.formats if f.format_type == self.view_format_type
        ]
        if len(matching_formats) == 0:
            return self.formats[0]

        return matching_formats[0]


class LayoutItemType(Enum):
    """Types of layout items."""

    MAP = "map"
    LABEL = "label"
    PICTURE = "picture"

    def __str__(self):
        return self.value


@dataclass
class ItemScopeMapping:
    """Provides a simple mechanism for grouping layout items based on a
    scope, which in most cases refers to an algorithm. This is especially
    useful when a layout contains items linked to different algorithms where
    it becomes important to define how values for each item will be fetched
    from which scope/algorithm.
    """

    # Corresponds to algorithm name
    name: str
    type_id_mapping: typing.Dict[str, list] = field(default_factory=dict)

    def __init__(self, name: str, **kwargs) -> None:
        self.name = name
        self.type_id_mapping = kwargs.pop("type_id_mapping", dict())

    def __hash__(self):
        return hash(self.name + json.dumps(self.type_id_mapping, sort_keys=True))

    def add_item_mapping(self, item_type: str, item_id: str) -> None:
        """Group item ids in a list based on their type."""
        str_item_type = str(item_type)
        if str_item_type not in self.type_id_mapping:
            self.type_id_mapping[str_item_type] = []

        items = self.type_id_mapping[str_item_type]
        items.append(item_id)

    def add_map(self, item_id: str) -> None:
        # Add map_id to the collection
        self.add_item_mapping(LayoutItemType.MAP, item_id)

    def add_label(self, item_id: str) -> None:
        # Add label to the collection
        self.add_item_mapping(LayoutItemType.LABEL, item_id)

    def add_picture(self, item_id: str) -> None:
        # Add picture item id to the collection
        self.add_item_mapping(LayoutItemType.PICTURE, item_id)

    def item_ids_by_type(self, item_type: str) -> list:
        """Get collection of item_ids based on the layout type."""
        str_item_type = str(item_type)
        if str_item_type in self.type_id_mapping:
            return self.type_id_mapping[str_item_type]

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


@dataclass
class AbsolutePaths:
    # Paths for report templates or outputs.
    simple_portrait: typing.Optional[str]
    simple_landscape: typing.Optional[str]
    full_portrait: typing.Optional[str]
    full_landscape: typing.Optional[str]

    def _paths_to_list(self):
        paths = []
        if self.simple_landscape:
            paths.append(self.simple_landscape)
        if self.simple_portrait:
            paths.append(self.simple_portrait)
        if self.full_portrait:
            paths.append(self.full_portrait)
        if self.full_landscape:
            paths.append(self.full_landscape)

        return paths

    def __len__(self):
        return len(self._paths_to_list())

    def __iter__(self):
        return iter(self._paths_to_list())

    def simple_portrait_exists(self) -> bool:
        return os.path.exists(self.simple_portrait)

    def simple_landscape_exists(self) -> bool:
        return os.path.exists(self.simple_landscape)

    def full_portrait_exists(self) -> bool:
        return os.path.exists(self.full_portrait)

    def full_landscape_exists(self) -> bool:
        return os.path.exists(self.full_landscape)


@dataclass
class ReportTemplateInfo:
    """Contains information about the QGIS layout associated with one or more
    algorithm scopes.
    """

    id: typing.Optional[str]
    name: typing.Optional[str]
    description: typing.Optional[str]
    simple_portrait_path: typing.Optional[str]
    simple_landscape_path: typing.Optional[str]
    full_portrait_path: typing.Optional[str]
    full_landscape_path: typing.Optional[str]
    item_scopes: typing.List[ItemScopeMapping] = field(default_factory=list)

    def __init__(self, **kwargs) -> None:
        self.id = kwargs.pop("id", str(uuid4()))
        self.name = kwargs.pop("name", "")
        self.description = kwargs.pop("description", "")
        self.simple_portrait_path = kwargs.pop("simple_portrait_path", "")
        self.simple_landscape_path = kwargs.pop("simple_landscape_path", "")
        self.full_portrait_path = kwargs.pop("full_portrait_path", "")
        self.full_landscape_path = kwargs.pop("full_landscape_path", "")
        self.item_scopes = kwargs.pop("item_scopes", list())
        self._abs_simple_portrait_path = ""
        self._abs_simple_landscape_path = ""
        self._abs_full_portrait_path = ""
        self._abs_full_landscape_path = ""
        self._absolute_paths = None

    def __hash__(self):
        return hash([self.id, self.item_scopes])

    def add_scope_mapping(self, item_scope: ItemScopeMapping) -> None:
        self.item_scopes.append(item_scope)

    def scope_mappings_by_name(self, name: str) -> typing.List[ItemScopeMapping]:
        return [sm for sm in self.item_scopes if sm.name == name]

    def update_paths(self, root_templates_dir, user_templates_dir=None) -> None:
        # set absolute paths for portrait and landscape templates
        # Prioritize matching paths in the user folder, if not found then
        # revert to the plugin one.
        concat_path = lambda template_dir, file_name: os.path.normpath(
            f"{template_dir}{os.sep}{file_name}"
        )

        # First check user-defined directory
        if user_templates_dir is not None:
            # Simple templates
            simple_portrait_path = concat_path(
                user_templates_dir, self.simple_portrait_path
            )
            if os.path.exists(simple_portrait_path):
                self._abs_simple_portrait_path = simple_portrait_path

            simple_landscape_path = concat_path(
                user_templates_dir, self.simple_landscape_path
            )
            if os.path.exists(simple_landscape_path):
                self._abs_simple_landscape_path = simple_landscape_path

            # Full templates
            full_portrait_path = concat_path(
                user_templates_dir, self.full_portrait_path
            )
            if os.path.exists(full_portrait_path):
                self._abs_full_portrait_path = full_portrait_path

            full_landscape_path = concat_path(
                user_templates_dir, self.full_landscape_path
            )
            if os.path.exists(full_landscape_path):
                self._abs_full_landscape_path = full_landscape_path

        # Fallback to root template directory in the plugin. Will still need
        # to be validated during report generation process.
        # Simple templates
        if not self._abs_simple_portrait_path:
            self._abs_simple_portrait_path = concat_path(
                root_templates_dir, self.simple_portrait_path
            )

        if not self._abs_simple_landscape_path:
            self._abs_simple_landscape_path = concat_path(
                root_templates_dir, self.simple_landscape_path
            )

        # Full templates
        if not self._abs_full_portrait_path:
            self._abs_full_portrait_path = concat_path(
                root_templates_dir, self.full_portrait_path
            )

        if not self._abs_full_landscape_path:
            self._abs_full_landscape_path = concat_path(
                root_templates_dir, self.full_landscape_path
            )

    @property
    def absolute_template_paths(self) -> AbsolutePaths:
        """Absolute paths for portrait and landscape templates."""
        return AbsolutePaths(
            self._abs_simple_portrait_path,
            self._abs_simple_landscape_path,
            self._abs_full_portrait_path,
            self._abs_full_landscape_path,
        )

    @property
    def is_multi_scope(self) -> bool:
        """True if the template is for compound reports."""
        return True if len(self.item_scopes) > 1 else False

    def contains_scope(self, name: str) -> bool:
        """
        True if the template contains a scope mapping with the given name.
        """
        return True if len(self.scope_mappings_by_name(name)) > 0 else False


@dataclass
class ReportConfiguration:
    """Contains template and output settings for a report."""

    template_info: typing.Optional[ReportTemplateInfo]
    output_options: typing.Optional[ReportOutputOptions]

    class Meta:
        ordered = True

    def __init__(
        self, template_info: ReportTemplateInfo, output_options: ReportOutputOptions
    ) -> None:
        self.template_info = template_info
        self.output_options = output_options

    def __hash__(self):
        return hash([self.template_info, self.output_options])

    def update_paths(self, root_template_dir, user_template_dir=None):
        # Convenience function for updating absolute paths for template files.
        self.template_info.update_paths(root_template_dir, user_template_dir)


@dataclass
class ReportTaskContext:
    """
    Provides context information for generating reports.
    """

    report_configuration: ReportConfiguration
    jobs: typing.List[Job] = field(default_factory=list)
    root_report_dir: typing.Optional[str] = None

    def __init__(
        self,
        report_configuration: ReportConfiguration,
        jobs: typing.List[Job] = None,
        root_report_dir: str = None,
    ):
        self.report_configuration = report_configuration
        self.jobs = jobs or []
        self.root_report_dir = root_report_dir or None

    def __hash__(self):
        return hash([[job.id for job in self.jobs], hash(self.report_configuration)])

    def display_name(self) -> str:
        # Friendly name for the task that can be used in the UI.
        jobs_num = len(self.jobs)
        if jobs_num == 0:
            return self.report_configuration.template_info.name
        else:
            job_names = [j.get_display_name() for j in self.jobs]
            return "_".join(job_names)

    def id(self) -> str:
        # Use job ids for creating a unique identifier.
        attrs = [str(j.id) for j in self.jobs]
        attrs_bytes = bytes("*".join(attrs), "utf-8")
        attrs_hash = hashlib.md5()
        attrs_hash.update(attrs_bytes)

        return attrs_hash.hexdigest()

    def __hash__(self) -> int:
        return hash(self.id())
