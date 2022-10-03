"""Util functions for report-related functions."""
import os
import typing

from qgis.gui import QgisInterface

from te_schemas.jobs import Job
from te_schemas.results import Band as JobBand

from ..jobs import manager
from ..layers import get_band_title, styles
from .models import ReportOutputOptions, slugify, TemplateType


def job_report_directory(job: Job) -> str:
    """
    Returns the root directory for a job's reports under the datasets
    folder. The caller should assert whether this folder actually exists.
    """
    return f"{manager.job_manager.datasets_dir}/{job.id!s}/reports"


def build_report_paths(
    job: Job, options: ReportOutputOptions, root_dir=None
) -> typing.Tuple[str, dict]:
    """
    Returns a tuple containing the root directory for report files and nested
    dictionary containing inner dictionaries of absolute file path for simple
    and/or full reports.
    -band_index (dict 1):
                |-template_type (dict2 whose keys include 'simple' and/or 'full'):
                (value is a list of paths for each type)
    """
    if root_dir is None:
        root_dir = job_report_directory(job)

    # Check if directory exists and create if it does not.
    if not os.path.exists(root_dir):
        os.mkdir(root_dir)

    formats = options.formats
    temp_types = []

    # Determine if to create paths for one or both template types
    if options.template_type == TemplateType.SIMPLE:
        temp_types.append(options.template_type.SIMPLE.value)
    elif options.template_type == TemplateType.FULL:
        temp_types.append(options.template_type.FULL.value)
    else:
        temp_types.append(options.template_type.SIMPLE.value)
        temp_types.append(options.template_type.FULL.value)

    file_exts = []
    # Remove any duplicate extensions
    for f in formats:
        rpt_ext = f.file_extension()
        if rpt_ext in file_exts:
            continue
        file_exts.append(rpt_ext)

    rpt_band_paths = {}

    area_name = job.local_context.area_of_interest_name

    bands = job.results.get_bands()
    for band_idx, band in enumerate(bands, start=1):
        band_paths = {}
        # Focus on default bands only
        if band.add_to_map:
            band_info = JobBand.Schema().dump(band)

            # Only include those band that have a band style
            band_info_name = band_info["name"]
            band_style = styles.get(band_info_name, None)
            if band_style is None:
                continue

            band_title = get_band_title(band_info)
            for tt in temp_types:
                tt_paths = []
                for ext in file_exts:
                    rpt_name = slugify(f"{tt}_map_figure_{band_title}_{area_name}")
                    abs_rpt_path = os.path.normpath(f"{root_dir}/{rpt_name}.{ext}")
                    tt_paths.append(abs_rpt_path)
                band_paths[tt] = tt_paths

            rpt_band_paths[band_idx] = band_paths

    return root_dir, rpt_band_paths


def job_has_results(job: Job) -> bool:
    # Checks if the given job has results in the file system.
    if job.results is not None:
        if job.results.uri and (
            manager.is_gdal_vsi_path(job.results.uri.uri)
            or (
                job.results.uri.uri.suffix in [".vrt", ".tif"]
                and job.results.uri.uri.exists()
            )
        ):
            return True
        else:
            return False
    else:
        return False


def job_has_report(job: Job, options: ReportOutputOptions) -> bool:
    """
    Checks if there are reports associated with the given job. If there is
    even a single missing file, it will return False.
    """
    _, band_paths = build_report_paths(job, options)
    for band_idx, tt_paths in band_paths.items():
        for template_type, paths in tt_paths.items():
            for rpt_path in paths:
                if not os.path.exists(rpt_path):
                    return False

    return True


def default_report_disclaimer() -> str:
    """
    For use in the plugin settings. Might need to be translatable in the
    future.
    """
    return (
        "The provided boundaries are from Natural Earth, and are in the "
        "public domain. The boundaries, names and designations used in "
        "Trends.Earth  do not imply official endorsement or acceptance by "
        "Conservation International Foundation, or by its partner "
        "organizations and contributors. Map produced from:"
    )
