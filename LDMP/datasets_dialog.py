"""Datasets details dialog for Trends.Earth QGIS plugin."""

import json
from pathlib import Path
from zipfile import ZipFile

import qgis.core
import qgis.gui

from PyQt5 import (
    QtCore,
    QtGui,
    QtWidgets,
    uic,
)

from . import (
    layers,
    log,
    openFolder,
    tr,
)
from .jobs import (
    manager,
    models,
)

WidgetDatasetItemDetailsUi, _ = uic.loadUiType(
    str(Path(__file__).parents[0] / "gui/WidgetDatasetItemDetails.ui"))


class DatasetDetailsDialogue(QtWidgets.QDialog, WidgetDatasetItemDetailsUi):
    job: models.Job

    def __init__(self, job: models.Job, parent=None):
        super(DatasetDetailsDialogue, self).__init__(parent)
        self.setupUi(self)

        self.job = job

        self.name_le.setText(self.job.params.task_name)
        self.state_le.setText(self.job.status.value)
        self.created_at_le.setText(str(self.job.start_date))

        self.load_btn.clicked.connect(self.load_dataset)
        self.delete_btn.clicked.connect(self.delete_dataset)
        self.open_directory_btn.clicked.connect(self.open_job_directory)
        self.export_btn.clicked.connect(self.export_dataset)
        self.delete_btn.setEnabled(
            self.job.status == models.JobStatus.DOWNLOADED
        )

        self.alg_le.setText(self.job.script.name)
        self.raster_file_path = None

        if self.job.results is not None:
            for path in self.job.results.local_paths:
                if 'tif' in str(path):
                    self.raster_file_path = path
        self.path_le.setText(str(self.raster_file_path))

        self.load_btn.setIcon(
            QtGui.QIcon(':/plugins/LDMP/icons/mActionAddRasterLayer.svg'))
        self.open_directory_btn.setIcon(
            QtGui.QIcon(':/images/themes/default/mActionFileOpen.svg'))
        self.export_btn.setIcon(
            QtGui.QIcon(':/plugins/LDMP/icons/export_zip.svg'))
        self.delete_btn.setIcon(
            QtGui.QIcon(':/plugins/LDMP/icons/mActionDeleteSelected.svg'))

        self.comments.setText(self.job.params.task_notes.user_notes)
        self.input.setText(
            json.dumps(
                self.job.params.params,
                indent=4,
                sort_keys=True)
        )
        if self.job.results is not None:
            self.output.setText(
                json.dumps(
                    self.job.results.serialize(),
                    indent=4,
                    sort_keys=True)
            )

        self.bar = qgis.gui.QgsMessageBar()
        self.bar.setSizePolicy(
            QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed
        )
        self.layout().addWidget(self.bar, 0, 0, alignment=QtCore.Qt.AlignTop)

    def load_dataset(self):
        manager.job_manager.display_job_results(self.job)

    def open_job_directory(self):
        log(f"Open directory button clicked for job {self.job.params.task_name!r}")
        job_directory = manager.job_manager.get_job_file_path(self.job).parent
        # NOTE: not using QDesktopServices.openUrl here, since it seems to not be
        # working correctly (as of Jun 2021 on Ubuntu)
        openFolder(str(job_directory))

    def delete_dataset(self):
        message_box = QtWidgets.QMessageBox()
        message_box.setText(
            f"You are about to delete job {self.job.params.task_name!r}")
        message_box.setInformativeText("Confirm?")
        message_box.setStandardButtons(
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel)
        message_box.setDefaultButton(QtWidgets.QMessageBox.Cancel)
        message_box.setIcon(QtWidgets.QMessageBox.Information)
        result = QtWidgets.QMessageBox.Res = message_box.exec_()
        if result == QtWidgets.QMessageBox.Yes:
            log("About to delete the dataset")
            for path in self.job.results.local_paths:
                layers.delete_layer_by_filename(str(path))
            manager.job_manager.delete_job(self.job)
            self.accept()

    def export_dataset(self):
        log(f"Exporting dataset {self.job.params.task_name!r}")
        self.export_btn.setEnabled(False)
        self.bar.clearWidgets()

        if self.raster_file_path is not None:
            # collect all files related to the dataset and compress them
            # into one zip file.
            dataset_base_dir = self.raster_file_path.parents[0]
            folder_contents = dataset_base_dir.glob(f"{self.raster_file_path.stem}.*")
            files = [content for content in folder_contents if content.is_file()]

            manager.job_manager.exports_dir.mkdir(exist_ok=True)

            try:
                zipped_file = f"{str(manager.job_manager.exports_dir)}/" \
                              f"{self.job.params.task_name}.zip"
                with ZipFile(zipped_file, 'w') as zip:
                    for file in files:
                        zip.write(file, Path(file).name)
            except RuntimeError:
                message_bar_item = self.bar.createMessage(
                    tr(f"Error exporting dataset {zipped_file}"))
                self.bar.pushWidget(message_bar_item, level=qgis.core.Qgis.Critical)

            message_bar_item = self.bar.createMessage(
                tr(f"Dataset exported to {zipped_file}"))
            self.bar.pushWidget(message_bar_item, level=qgis.core.Qgis.Info)

        else:
            message_bar_item = self.bar.createMessage(
                tr(f"Couldn't export dataset {self.job.params.task_name},"
                   f" it has no data files."))
            self.bar.pushWidget(message_bar_item, level=qgis.core.Qgis.Info)

        self.export_btn.setEnabled(True)
