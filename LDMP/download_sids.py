"""
/***************************************************************************
 LDMP - A QGIS plugin
 This plugin supports monitoring and reporting of land degradation to the UNCCD
 and in support of the SDG Land Degradation Neutrality (LDN) target.
                             -------------------
       begin                : 2017-05-23
       git sha              : $Format:%H$
       copyright            : (C) 2017 by Conservation International
       email                : trends.earth@conservation.org
 ***************************************************************************/

Dialog for downloading 30m Land Productivity Dynamics data for Small Island
Developing States (SIDS) from Zenodo.
"""

import json
import re
import uuid
import zipfile
from pathlib import Path

import qgis.gui
import te_algorithms.gdal.land_deg.config as ld_conf
from qgis.core import Qgis, QgsFileDownloader
from qgis.PyQt import QtCore, QtWidgets, uic
from te_schemas.algorithms import ExecutionScript

from . import conf
from .jobs.manager import job_manager
from .logger import log

DlgDownloadSIDSUi, _ = uic.loadUiType(
    str(Path(__file__).parent / "gui/DlgDownloadSIDS.ui")
)

ZENODO_DATA_FILE = Path(__file__).parent / "data" / "zenodo_datasets.json"


def get_current_country_name() -> str:
    country_id = conf.settings_manager.get_value(conf.Setting.COUNTRY_ID)
    if not country_id:
        return ""
    for name, country in conf.ADMIN_BOUNDS_KEY.items():
        if country.code == country_id:
            return name
    return ""


class DlgDownloadSIDS(QtWidgets.QDialog, DlgDownloadSIDSUi):
    """Dialog to download 30m LPD data for SIDS from Zenodo."""

    def __init__(
        self,
        iface: qgis.gui.QgisInterface,
        script: ExecutionScript,
        parent: QtWidgets.QWidget = None,
    ):
        super().__init__(parent)
        self.iface = iface
        self.script = script
        self._cancelled = False
        self._current_downloader = None

        self.setupUi(self)
        with open(ZENODO_DATA_FILE) as f:
            self._zenodo_data = json.load(f)
        self._zenodo_data = self._zenodo_data["sids_lpd_30m"]
        self.country_entry = None
        self._setup_ui()

    def _setup_ui(self):
        country_name = get_current_country_name()

        if country_name:
            for entry in self._zenodo_data["countries"]:
                if entry["name"].lower() == country_name.lower():
                    self.country_entry = entry
                    break

        if self.country_entry:
            self.lbl_country.setText(
                self.tr(f"Country: <b>{self.country_entry['name']}</b>")
            )
            self.lbl_status.setVisible(False)
        elif country_name:
            self.lbl_country.setText(self.tr(f"Country: <b>{country_name}</b>"))
            self.lbl_status.setText(
                self.tr(
                    f"<b>{country_name}</b> is not in the SIDS 30m LPD dataset. "
                    "Change your region of interest to a SIDS country to download data."
                )
            )
            self.lbl_status.setVisible(True)
        else:
            self.lbl_country.setText(self.tr("Country: <i>Not set</i>"))
            self.lbl_status.setText(
                self.tr(
                    "No country configured. Please set a region of interest in "
                    "the plugin settings."
                )
            )
            self.lbl_status.setVisible(True)

        ok_btn = self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok)
        ok_btn.setText(self.tr("Download"))
        ok_btn.setEnabled(self.country_entry is not None)

        self.buttonBox.accepted.connect(self._on_download)
        self.buttonBox.rejected.connect(self._on_cancel)

    def _on_download(self):
        if self.country_entry is None:
            return
        self._run_download(self.country_entry)

    def _on_cancel(self):
        self._cancelled = True
        if self._current_downloader is not None:
            try:
                self._current_downloader.cancelDownload()
            except Exception:
                pass
        self.reject()

    def _run_download(self, country):
        self._cancelled = False
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.lbl_status.setVisible(True)

        ok_btn = self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok)
        ok_btn.setEnabled(False)

        job_id = uuid.uuid4()
        job_dir = job_manager.datasets_dir / str(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)

        filename = country["filename"]
        base_url = self._zenodo_data["base_download_url"]
        url = base_url.format(filename=filename)
        zip_path = job_dir / filename

        self.lbl_status.setText(self.tr(f"Downloading {country['name']}..."))
        QtWidgets.QApplication.processEvents()

        success = self._qgs_download(url, zip_path)

        if not success:
            self.lbl_status.setText(self.tr("Download failed. Please try again."))
            ok_btn.setEnabled(True)
            return

        self.progress_bar.setValue(50)
        QtWidgets.QApplication.processEvents()

        self.lbl_status.setText(self.tr("Extracting files..."))
        QtWidgets.QApplication.processEvents()

        tif_paths = self._extract_zip(zip_path, job_dir)

        if not tif_paths:
            self.lbl_status.setText(
                self.tr("No raster files found in the downloaded archive.")
            )
            ok_btn.setEnabled(True)
            return

        self.progress_bar.setValue(75)
        QtWidgets.QApplication.processEvents()

        registered = 0
        for tif_path in tif_paths:
            try:
                self.register_dataset(tif_path, country["name"])
                registered += 1
            except Exception as e:
                log(f"Failed to register {tif_path.name}: {e}", level=Qgis.Warning)

        self.progress_bar.setValue(100)

        if registered:
            self.lbl_status.setText(
                self.tr(
                    f"Download complete. {registered} dataset(s) added to "
                    "the Datasets panel."
                )
            )
            log(
                f"Downloaded and registered {registered} raster(s) for "
                f"{country['name']}"
            )
            self.accept()
        else:
            self.lbl_status.setText(
                self.tr("Download complete but datasets could not be registered.")
            )
            ok_btn.setEnabled(True)

    def _parse_years_from_stem(self, stem: str):
        """Extract year_initial and year_final from a TIF filename stem."""
        match = re.search(r"(\d{4})[_\-](\d{4})", stem)
        if match:
            return int(match.group(1)), int(match.group(2))
        return None, None

    def register_dataset(self, tif_path: Path, country_name: str):
        band_name = ld_conf.FAO_WOCAT_LPD_BAND_NAME

        year_initial, year_final = self._parse_years_from_stem(tif_path.stem)

        # Fall back to dataset-wide range if no years found in filename
        if year_initial is None:
            year_initial = 2000
        if year_final is None:
            year_final = 2023

        period_label = f"{year_initial}\u2013{year_final}"
        task_name = self.tr(f"LPD {country_name} {period_label} (Zenodo 30m)")

        band_metadata = {
            "year_initial": year_initial,
            "year_final": year_final,
            "source": "Zenodo SIDS 30m LPD (FAO-WOCAT v2)",
            "country": country_name,
        }

        job = job_manager.create_job_from_dataset(
            dataset_path=tif_path,
            band_name=band_name,
            band_metadata=band_metadata,
            task_name=task_name,
            task_notes=(
                f"30m Land Productivity Dynamics for {country_name}, "
                f"reporting period {period_label}. "
                f"Algorithm: {self._zenodo_data['algorithm']}. "
                f"Downloaded from Zenodo DOI: {self._zenodo_data['zenodo_doi']}. "
                f"License: {self._zenodo_data['license']}."
            ),
        )

        job_manager.import_job(job, tif_path)
        job_manager.move_job_results(job)

    def _qgs_download(self, url: str, output_path: Path) -> bool:
        """Download a file using QgsFileDownloader with a local QEventLoop."""
        loop = QtCore.QEventLoop()
        state = {"success": False, "error": None}

        downloader = QgsFileDownloader(QtCore.QUrl(url), str(output_path))
        self._current_downloader = downloader

        def _on_completed():
            state["success"] = True
            loop.quit()

        def _on_error(errors):
            state["error"] = str(errors)
            loop.quit()

        downloader.downloadCompleted.connect(_on_completed)
        downloader.downloadError.connect(_on_error)
        downloader.downloadExited.connect(loop.quit)
        downloader.downloadCanceled.connect(loop.quit)
        downloader.startDownload()
        loop.exec()

        self._current_downloader = None

        if state["error"]:
            log(
                f"Download error for {output_path.name}: {state['error']}",
                level=Qgis.Warning,
            )
            output_path.unlink(missing_ok=True)
            return False

        return state["success"]

    def _extract_zip(self, zip_path: Path, output_dir: Path) -> list:
        """Extract a ZIP file and return paths of all extracted GeoTIFF files."""
        tif_paths = []
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                for name in zf.namelist():
                    zf.extract(name, output_dir)
                    extracted = (output_dir / name).resolve()
                    if extracted.suffix.lower() in (".tif", ".tiff"):
                        tif_paths.append(extracted)
        except zipfile.BadZipFile as e:
            log(f"Bad ZIP file {zip_path.name}: {e}", level=Qgis.Warning)
            zip_path.unlink(missing_ok=True)
        return tif_paths
