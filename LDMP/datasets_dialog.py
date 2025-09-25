"""Datasets details dialog for Trends.Earth QGIS plugin."""

import os
from pathlib import Path
from zipfile import ZipFile

import qgis.core
import qgis.gui
from qgis.PyQt import QtCore, QtGui, QtWidgets, uic
from te_schemas.jobs import JobStatus

from . import metadata, openFolder, utils
from .jobs import manager
from .jobs.models import Job
from .json_viewer import JsonViewerWidget
from .logger import log

WidgetDatasetItemDetailsUi, _ = uic.loadUiType(
    str(Path(__file__).parents[0] / "gui/WidgetDatasetItemDetails.ui")
)

ICON_PATH = os.path.join(os.path.dirname(__file__), "icons")


class DatasetDetailsDialogue(QtWidgets.QDialog, WidgetDatasetItemDetailsUi):
    job: Job

    alg_le: QtWidgets.QLineEdit
    created_at_le: QtWidgets.QLineEdit
    delete_btn: QtWidgets.QPushButton
    export_btn: QtWidgets.QPushButton
    name_le: QtWidgets.QLineEdit
    id_le: QtWidgets.QLineEdit
    state_le: QtWidgets.QLineEdit
    path_le: QtWidgets.QLineEdit
    input: JsonViewerWidget
    output: JsonViewerWidget

    def __init__(self, job: Job, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.job = job

        self.name_le.setText(self.job.task_name)
        self.id_le.setText(str(self.job.id))
        self.state_le.setText(self.job.status.value)
        self.created_at_le.setText(
            str(utils.utc_to_local(self.job.start_date).strftime("%Y-%m-%d %H:%M"))
        )
        self.delete_btn.clicked.connect(self.delete_dataset)
        self.open_directory_btn.clicked.connect(self.open_job_directory)
        self.export_btn.clicked.connect(self.export_dataset)
        self.alg_le.setText(self.job.script.name)
        empty_paths_msg = "This dataset does not have local paths"

        main_uri_exist = False

        if self.job.results is not None:
            try:
                if self.job.results.uri is not None:
                    path_le_text = str(self.job.results.uri.uri)
                    main_uri_exist = True
                else:
                    path_le_text = empty_paths_msg
            except AttributeError:
                # Catch case of a result without uri defined yet
                path_le_text = f"{empty_paths_msg} yet"
        else:
            path_le_text = f"{empty_paths_msg} yet"
        self.export_btn.setEnabled(main_uri_exist)
        self.path_le.setText(path_le_text)
        self.open_directory_btn.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, "mActionFileOpen.svg"))
        )
        self.export_btn.setIcon(QtGui.QIcon(os.path.join(ICON_PATH, "export_zip.svg")))
        self.delete_btn.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, "mActionDeleteSelected.svg"))
        )

        # Hide inappropriate buttons for failed and cancelled jobs
        # Failed or cancelled jobs should only show the open folder and info buttons
        if self.job.status in (
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.EXPIRED,
        ):
            self.export_btn.hide()
            # Keep open_directory_btn (folder icon) and delete_btn (info/delete icon) visible

        self.comments.setText(self.job.task_notes)
        self.input.set_json_data(self.job.params, collapse_level=1)

        if self.job.results is not None:
            results_data = Job.Schema(only=["results"]).dump(self.job)["results"]
            self.output.set_json_data(results_data, collapse_level=1)

        self.bar = qgis.gui.QgsMessageBar()
        self.bar.setSizePolicy(
            QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed
        )
        self.layout().insertWidget(0, self.bar, alignment=QtCore.Qt.AlignTop)

    def open_job_directory(self):
        log(f"Open directory button clicked for job {self.job.task_name!r}")
        job_directory = manager.job_manager.get_job_file_path(self.job).parent
        # NOTE: not using QDesktopServices.openUrl here, since it seems to not be
        # working correctly (as of Jun 2021 on Ubuntu)
        openFolder(str(job_directory))

    def delete_dataset(self):
        result = utils.delete_dataset(self.job)

        if result == QtWidgets.QMessageBox.Yes:
            self.accept()

    def export_dataset(self):
        log(f"Exporting dataset {self.job.task_name!r}...")
        self.export_btn.setEnabled(False)
        self.bar.clearWidgets()
        manager.job_manager.exports_dir.mkdir(exist_ok=True)
        current_job_file_path = manager.job_manager.get_job_file_path(self.job)
        target_zip_name = f"{current_job_file_path.stem}.zip"
        target_path = manager.job_manager.exports_dir / target_zip_name
        metadata_paths = metadata.export_dataset_metadata(self.job)
        paths_to_zip = (
            [uri.uri for uri in self.job.results.get_all_uris()]
            + [current_job_file_path]
            + metadata_paths
        )
        try:
            with ZipFile(target_path, "w") as zip:
                for path in paths_to_zip:
                    zip.write(str(path), path.name)
        except RuntimeError:
            message_bar_item = self.bar.createMessage(
                self.tr(f"Error exporting dataset {self.job}")
            )
            self.bar.pushWidget(message_bar_item, level=qgis.core.Qgis.Critical)
        else:
            message_bar_item = self.bar.createMessage(
                self.tr(f"Dataset exported to {target_path!r}")
            )
            self.bar.pushWidget(message_bar_item, level=qgis.core.Qgis.Info)
        finally:
            self.export_btn.setEnabled(True)
