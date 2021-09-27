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
    openFolder,
    tr,
    utils,
)
from .jobs import (
    manager,
    models,
)
from .logger import log

WidgetDatasetItemDetailsUi, _ = uic.loadUiType(
    str(Path(__file__).parents[0] / "gui/WidgetDatasetItemDetails.ui"))


class DatasetDetailsDialogue(QtWidgets.QDialog, WidgetDatasetItemDetailsUi):
    job: models.Job

    alg_le: QtWidgets.QLineEdit
    created_at_le: QtWidgets.QLineEdit
    delete_btn: QtWidgets.QPushButton
    export_btn: QtWidgets.QPushButton
    load_btn: QtWidgets.QPushButton
    name_le: QtWidgets.QLineEdit
    id_le: QtWidgets.QLineEdit
    state_le: QtWidgets.QLineEdit
    path_le: QtWidgets.QLineEdit

    def __init__(self, job: models.Job, parent=None):
        super(DatasetDetailsDialogue, self).__init__(parent)
        self.setupUi(self)

        self.job = job

        self.name_le.setText(self.job.params.task_name)
        self.id_le.setText(str(self.job.id))
        self.state_le.setText(self.job.status.value)
        self.created_at_le.setText(str(self.job.start_date))
        self.load_btn.clicked.connect(self.load_dataset)
        self.delete_btn.clicked.connect(self.delete_dataset)
        self.open_directory_btn.clicked.connect(self.open_job_directory)
        self.export_btn.clicked.connect(self.export_dataset)
        self.alg_le.setText(self.job.script.name)
        empty_paths_msg = "This dataset does not have local paths"

        data_path_exist = False
        if self.job.results is not None:
            data_path = self.job.results.data_path
            if data_path:
                path_le_text = str(data_path)
                data_path_exist = True
            else:
                path_le_text = empty_paths_msg
        else:
            path_le_text = f"{empty_paths_msg}_yet"
        self.load_btn.setEnabled(data_path_exist)
        self.export_btn.setEnabled(data_path_exist)
        self.path_le.setText(path_le_text)
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
        self.layout().insertWidget(0, self.bar, alignment=QtCore.Qt.AlignTop)

    def load_dataset(self):
        if self.job.results is not None:
            manager.job_manager.display_default_job_results(self.job)
            self.accept()

    def open_job_directory(self):
        log(f"Open directory button clicked for job {self.job.params.task_name!r}")
        job_directory = manager.job_manager.get_job_file_path(self.job).parent
        # NOTE: not using QDesktopServices.openUrl here, since it seems to not be
        # working correctly (as of Jun 2021 on Ubuntu)
        openFolder(str(job_directory))

    def delete_dataset(self):
        result = utils.delete_dataset(self.job)
        if result == QtWidgets.QMessageBox.Yes:
            self.accept()

    def export_dataset(self):
        log(f"Exporting dataset {self.job.params.task_name!r}...")
        self.export_btn.setEnabled(False)
        self.bar.clearWidgets()
        manager.job_manager.exports_dir.mkdir(exist_ok=True)
        current_job_file_path = manager.job_manager.get_job_file_path(self.job)
        target_zip_name = f"{current_job_file_path.stem}.zip"
        target_path = manager.job_manager.exports_dir / target_zip_name
        paths_to_zip = [self.job.results.data_path] + self.job.results.other_paths + [current_job_file_path]
        try:
            with ZipFile(target_path, 'w') as zip:
                for path in paths_to_zip:
                    zip.write(str(path), path.name)
        except RuntimeError:
            message_bar_item = self.bar.createMessage(
                tr(f"Error exporting dataset {self.job}"))
            self.bar.pushWidget(message_bar_item, level=qgis.core.Qgis.Critical)
        else:
            message_bar_item = self.bar.createMessage(
                tr(f"Dataset exported to {target_path!r}"))
            self.bar.pushWidget(message_bar_item, level=qgis.core.Qgis.Info)
        finally:
            self.export_btn.setEnabled(True)
