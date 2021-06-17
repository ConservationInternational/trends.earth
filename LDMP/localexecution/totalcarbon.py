import datetime as dt
import qgis.core
from PyQt5 import QtCore

from .. import (
    areaofinterest,
    calculate_tc,
    log,
    utils,
)
from ..jobs import models


def compute_total_carbon_summary_table(
        tc_job: models.Job, area_of_interest: areaofinterest.AOI) -> models.Job:
    # Load all datasets to VRTs (to select only the needed bands)
    f_loss_vrt = utils.save_vrt(
        tc_job.params.params["f_loss_path"], tc_job.params.params["f_loss_band_index"])
    tc_vrt = utils.save_vrt(
        tc_job.params.params["tc_path"], tc_job.params.params["tc_band_index"])

    job_output_path, _ = utils.get_local_job_output_paths(tc_job)
    summary_table_output_path = job_output_path.parent / f"{job_output_path.stem}.xlsx"
    summary_task = calculate_tc.SummaryTask(
        area_of_interest,
        tc_job.params.params["year_start"],
        tc_job.params.params["year_end"],
        f_loss_vrt,
        tc_vrt,
        str(summary_table_output_path)
    )
    log("Adding task to task manager...")
    qgis.core.QgsApplication.taskManager().addTask(summary_task)
    terminal_statuses = [
        qgis.core.QgsTask.Complete,
        qgis.core.QgsTask.Terminated
    ]
    if summary_task.status() not in terminal_statuses:
        QtCore.QCoreApplication.processEvents()

    tc_job.end_date = dt.datetime.now(dt.timezone.utc)
    tc_job.progress = 100
    bands = []
    tc_job.results.bands = bands
    tc_job.results.local_paths = [summary_table_output_path]
    return tc_job