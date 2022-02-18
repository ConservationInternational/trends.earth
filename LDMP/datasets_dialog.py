"""Datasets details dialog for Trends.Earth QGIS plugin."""

import json
import os
from pathlib import Path
from zipfile import ZipFile

import qgis.core
import qgis.gui
from qgis.PyQt import QtCore
from qgis.PyQt import QtGui
from qgis.PyQt import QtWidgets
from qgis.PyQt import uic

from . import openFolder
from . import tr
from . import utils
from . import metadata_dialog
from . import metadata
from . import layers
from .jobs import manager
from .jobs.models import Job
from .logger import log
from te_schemas.results import Band as JobBand

WidgetDatasetItemDetailsUi, _ = uic.loadUiType(
    str(Path(__file__).parents[0] / "gui/WidgetDatasetItemDetails.ui")
)

ICON_PATH = os.path.join(os.path.dirname(__file__), 'icons')


class DatasetDetailsDialogue(QtWidgets.QDialog, WidgetDatasetItemDetailsUi):
    job: Job

    alg_le: QtWidgets.QLineEdit
    created_at_le: QtWidgets.QLineEdit
    delete_btn: QtWidgets.QPushButton
    export_btn: QtWidgets.QPushButton
    metadata_btn: QtWidgets.QPushButton
    load_btn: QtWidgets.QPushButton
    name_le: QtWidgets.QLineEdit
    id_le: QtWidgets.QLineEdit
    state_le: QtWidgets.QLineEdit
    path_le: QtWidgets.QLineEdit

    def __init__(self, job: Job, parent=None):
        super(DatasetDetailsDialogue, self).__init__(parent)
        self.setupUi(self)

        self.metadata_menu = QtWidgets.QMenu()
        self.metadata_menu.aboutToShow.connect(self.prepare_metadata_menu)
        self.metadata_btn.setMenu(self.metadata_menu)

        self.job = job

        self.name_le.setText(self.job.task_name)
        self.id_le.setText(str(self.job.id))
        self.state_le.setText(self.job.status.value)
        self.created_at_le.setText(
            str(
                utils.utc_to_local(self.job.start_date
                                   ).strftime("%Y-%m-%d %H:%M")
            )
        )
        self.load_btn.clicked.connect(self.load_dataset)
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
        self.load_btn.setEnabled(main_uri_exist)
        self.export_btn.setEnabled(main_uri_exist)
        self.path_le.setText(path_le_text)
        self.load_btn.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, 'mActionAddRasterLayer.svg'))
        )
        self.open_directory_btn.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, 'mActionFileOpen.svg'))
        )
        self.export_btn.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, 'export_zip.svg'))
        )
        self.metadata_btn.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, 'editmetadata.svg'))
        )
        self.delete_btn.setIcon(
            QtGui.QIcon(os.path.join(ICON_PATH, 'mActionDeleteSelected.svg'))
        )

        self.comments.setText(self.job.task_notes)
        self.input.setText(
            json.dumps(self.job.params, indent=4, sort_keys=True)
        )

        if self.job.results is not None:
            self.output.setText(
                json.dumps(
                    Job.Schema(only=['results']).dump(self.job)['results'],
                    indent=4,
                    sort_keys=True
                )
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
        paths_to_zip = [uri.uri for uri in self.job.results.get_all_uris()
                        ] + [current_job_file_path] + metadata_paths
        try:
            with ZipFile(target_path, 'w') as zip:
                for path in paths_to_zip:
                    zip.write(str(path), path.name)
        except RuntimeError:
            message_bar_item = self.bar.createMessage(
                tr(f"Error exporting dataset {self.job}")
            )
            self.bar.pushWidget(
                message_bar_item, level=qgis.core.Qgis.Critical
            )
        else:
            message_bar_item = self.bar.createMessage(
                tr(f"Dataset exported to {target_path!r}")
            )
            self.bar.pushWidget(message_bar_item, level=qgis.core.Qgis.Info)
        finally:
            self.export_btn.setEnabled(True)

    def show_metadata(self, file_path):
        ds_metadata = metadata.read_qmd(file_path)
        dlg = metadata_dialog.DlgDatasetMetadata(self)
        dlg.set_metadata(ds_metadata)
        dlg.exec_()
        ds_metadata = dlg.get_metadata()
        metadata.save_qmd(file_path, ds_metadata)

    def prepare_metadata_menu(self):
        self.metadata_menu.clear()

        file_path = os.path.splitext(manager.job_manager.get_job_file_path(self.job))[0] + '.qmd'
        action = self.metadata_menu.addAction(self.tr("Dataset metadata"))
        action.triggered.connect(lambda _, x=file_path: self.show_metadata(x))
        self.metadata_menu.addSeparator()

        if self.job.results.uri.uri.suffix in [".tif", ".vrt"]:
            for n, band in enumerate(self.job.results.get_bands()):
                t = f'Band {n}: {layers.get_band_title(JobBand.Schema().dump(band))}'
                fp = os.path.splitext(file_path)[0] + '_{}.qmd'.format(n)
                action = self.metadata_menu.addAction(self.tr("{} metadata").format(t))
                action.triggered.connect(lambda _, x=fp: self.show_metadata(x))
