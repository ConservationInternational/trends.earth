"""Util functions for report-related functions."""
import os
import typing

from te_schemas.jobs import Job

from ..jobs import manager

from .models import ReportOutputOptions


def build_report_name(
        job: Job,
        options: ReportOutputOptions
) -> typing.List[tuple]:
    """
    List of tuples containing report name and path (inclusive of report
    name). Based on the formats specified by the user.
    """
    rpt_name_path = []
    job_dir = f'{manager.job_manager.datasets_dir}/{job.id!s}'
    formats = options.formats
    exts = []
    for f in formats:
        rpt_ext = f.file_extension()
        # Ensure no duplicate extensions
        if rpt_ext in exts:
            continue
        exts.append(rpt_ext)

        rpt_name = f'{manager.job_manager.get_job_basename(job)}' \
               f'_report.{rpt_ext}'
        abs_rpt_path = os.path.normpath(f'{job_dir}/{rpt_name}')
        rpt_name_path.append((rpt_name, abs_rpt_path))

    return rpt_name_path


def build_template_name(
        job: Job
) -> typing.Tuple[str, str]:
    # Tuple containing template name and path (inclusive of template name)
    job_dir = f'{manager.job_manager.datasets_dir}/{job.id!s}'
    template_name = f'{manager.job_manager.get_job_basename(job)}' \
                    f'_template.qpt'
    abs_temp_path = os.path.normpath(f'{job_dir}/{template_name}')

    return template_name, abs_temp_path


def job_has_results(job: Job) -> bool:
    # Checks if the given job has results in the file system.
    if job.results is not None:
        if (
            job.results.uri and (
                manager.is_gdal_vsi_path(job.results.uri.uri) or (
                    job.results.uri.uri.suffix in [".vrt", ".tif"]
                    and job.results.uri.uri.exists()
                )
            )
        ):
            return True
        else:
            return False
    else:
        return False


def job_has_report(job: Job, options: ReportOutputOptions) -> bool:
    # Checks if there is a corresponding report for the given job.
    has_report = True
    name_paths = build_report_name(
        job,
        options
    )
    for np in name_paths:
        _, rpt_path = np
        if not os.path.exists(rpt_path):
            has_report = False
            break

    return has_report


