"""Managed prioritization inputs and reusable scoring profiles for LDN planning.

Planning inputs are imported once through the normal Trends.Earth dataset
workflow, keeping their raw values and provenance. Scoring profiles describe
how one band or numeric field is turned into a 0-1 priority score; they are
stored with the input and reused across plans, so users never retype dataset
properties or handwrite field names and category JSON.
"""

import json
import typing
import uuid
from pathlib import Path

import numpy as np
from qgis.PyQt import QtCore, QtWidgets
from te_algorithms.gdal.util import (
    MAX_DISCOVERED_CATEGORIES,
    discover_categories,
    inspect_source,
    observed_band_stats,
    observed_field_stats,
    sampled_field_values,
    sampled_raster_values,
)

from .jobs.manager import job_manager

CLASSES = ("avoid", "reduce", "reverse")
PROFILE_VERSION = 1


def input_kind(job) -> str:
    return job.params.get("input_kind", "raster")


def input_path(job) -> str:
    """Resolve the current managed file for a planning input through the job store."""
    job_manager.ensure_results_loaded(job)
    result = job.results
    uri = getattr(result, "uri", None)
    if uri is None or uri.uri is None:
        raise ValueError("The planning input has no managed file.")
    path = Path(uri.uri)
    if not path.is_file():
        raise ValueError(
            f"The managed file for input '{job.task_name}' is missing: {path}. "
            "Re-import or relink the dataset."
        )
    return str(path)


def input_display_name(job) -> str:
    provenance = job.params.get("provenance", {})
    kind = input_kind(job)
    return f"{job.task_name} ({kind}; {provenance.get('source', '?')})"


HISTOGRAM_BLOCKS = " ▁▂▃▄▅▆▇█"


def histogram_text(values: np.ndarray, bins: int = 24) -> str:
    """Render a compact unicode histogram of the sampled value distribution."""
    values = values[np.isfinite(values)]
    if values.size == 0:
        return ""
    minimum = float(values.min())
    maximum = float(values.max())
    if maximum <= minimum:
        return f"{minimum:g} (constant)"
    counts, _ = np.histogram(values, bins=bins, range=(minimum, maximum))
    peak = counts.max()
    bars = "".join(
        HISTOGRAM_BLOCKS[int(round(count / peak * (len(HISTOGRAM_BLOCKS) - 1)))]
        for count in counts
    )
    return f"{minimum:g} |{bars}| {maximum:g}"


def save_scoring_profile(job, profile: dict) -> dict:
    """Store a scoring profile on the input dataset as a new revision."""
    profiles = list(job.params.get("scoring_profiles", []))
    profile = dict(profile)
    profile.setdefault("id", str(uuid.uuid4()))
    profile["version"] = PROFILE_VERSION
    existing = [
        p.get("revision", 0) for p in profiles if p.get("name") == profile.get("name")
    ]
    profile["revision"] = max(existing, default=0) + 1
    profiles.append(profile)
    job_manager.save_planning_input_profiles(job, profiles)
    return profile


def build_criterion(job, profile: dict, arr_class: str, weight: float) -> dict:
    """Build an algorithm criterion from a managed input and a scoring profile.

    The path is resolved live through the job store; the scoring settings come
    from the profile snapshot, and provenance from the dataset. Extra keys
    identify the source for run provenance and are preserved by validation.
    """
    provenance = job.params.get("provenance", {})
    not_specified = "Not specified"
    criterion = {
        "name": f"{job.task_name}: {profile['name']}",
        "path": input_path(job),
        "field": profile.get("field", "") or "",
        "band_index": int(profile.get("band_index", 1) or 1),
        "arr_class": arr_class,
        "weight": weight,
        "direction": profile.get("direction", "higher"),
        "minimum": profile.get("minimum"),
        "maximum": profile.get("maximum"),
        "categories": profile.get("categories") or None,
        "resampling": profile.get("resampling", "nearest"),
        # Metadata is optional at import; reports record missing entries
        # explicitly rather than requiring users to invent values.
        "source": provenance.get("source") or not_specified,
        "date": provenance.get("date") or not_specified,
        "units": provenance.get("units") or not_specified,
        "license": provenance.get("license") or not_specified,
        "input_job_id": str(job.id),
        "profile_id": profile.get("id"),
        "profile_name": profile.get("name"),
        "profile_revision": profile.get("revision"),
    }
    return criterion


def drafts_dir() -> Path:
    from . import conf

    base = conf.settings_manager.get_value(conf.Setting.BASE_DIR)
    if not base:
        raise OSError("No Trends.Earth base data directory is configured.")
    directory = Path(base) / "planning_drafts"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_draft(name: str, draft: dict):
    draft = dict(draft)
    draft["draft_version"] = 1
    with open(drafts_dir() / f"{name}.json", "w", encoding="utf-8") as target:
        json.dump(draft, target, indent=2, allow_nan=False)


def load_draft(name: str) -> typing.Optional[dict]:
    try:
        path = drafts_dir() / f"{name}.json"
    except OSError:
        return None
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as source:
            draft = json.load(source)
    except (OSError, ValueError):
        return None
    if draft.get("draft_version") != 1:
        return None
    return draft


class DlgImportPlanningInput(QtWidgets.QDialog):
    """Import a prioritization input once, with discovered structure and provenance."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Import prioritization input"))
        self.job = None
        self._info = None
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()

        file_row = QtWidgets.QHBoxLayout()
        self.file_edit = QtWidgets.QLineEdit()
        self.file_edit.setReadOnly(True)
        browse = QtWidgets.QPushButton(self.tr("Browse..."))
        browse.clicked.connect(self._browse)
        file_row.addWidget(self.file_edit)
        file_row.addWidget(browse)
        form.addRow(self.tr("Raster or polygon file"), file_row)

        self.structure_label = QtWidgets.QLabel(
            self.tr("Choose a file to discover its bands or layers.")
        )
        self.structure_label.setWordWrap(True)
        form.addRow(self.tr("Detected structure"), self.structure_label)

        self.layer_combo = QtWidgets.QComboBox()
        self.layer_combo.setVisible(False)
        self.layer_label = QtWidgets.QLabel(self.tr("Vector layer to import"))
        self.layer_label.setVisible(False)
        form.addRow(self.layer_label, self.layer_combo)

        self.name_edit = QtWidgets.QLineEdit()
        form.addRow(self.tr("Dataset name"), self.name_edit)
        self.notes_edit = QtWidgets.QLineEdit()
        form.addRow(self.tr("Notes"), self.notes_edit)

        # Metadata follows the same approach as the other import tools: an
        # optional, preset-structured editor rather than required free fields.
        self.metadata = None
        metadata_button = QtWidgets.QPushButton(self.tr("Metadata..."))
        metadata_button.clicked.connect(self._edit_metadata)
        form.addRow(self.tr("Metadata (optional)"), metadata_button)

        layout.addLayout(form)
        note = QtWidgets.QLabel(
            self.tr(
                "The input is copied into managed Trends.Earth storage with its "
                "original values, bands and nodata preserved. Metadata entered "
                "in the shared editor is saved with the dataset and inherited "
                "by every scoring profile and plan that references it; missing "
                "entries are recorded as 'Not specified' in reports."
            )
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(620, 420)

    def _browse(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            self.tr("Prioritization input"),
            "",
            self.tr("Spatial files (*.tif *.tiff *.vrt *.gpkg *.geojson *.shp)"),
        )
        if not path:
            return
        try:
            info = inspect_source(path)
            if info["raster"] is None and info["vector"] is None:
                raise ValueError(
                    self.tr("The file is not a readable raster or vector.")
                )
        except ValueError as exc:
            QtWidgets.QMessageBox.critical(self, self.tr("Cannot read file"), str(exc))
            return
        self._info = info
        self.file_edit.setText(path)
        if not self.name_edit.text().strip():
            self.name_edit.setText(Path(path).stem)
        if info["raster"] is not None:
            bands = info["raster"]["bands"]
            self.structure_label.setText(
                self.tr("Raster with %d band(s): %s")
                % (
                    len(bands),
                    "; ".join(
                        f"{b['band_index']}: {b['description']} ({b['data_type']})"
                        for b in bands
                    ),
                )
            )
            self.layer_combo.setVisible(False)
            self.layer_label.setVisible(False)
        else:
            layers = info["vector"]["layers"]
            self.layer_combo.clear()
            for layer in layers:
                fields = ", ".join(
                    f["label"] for f in layer["numeric_fields"]
                ) or self.tr("no numeric fields")
                self.layer_combo.addItem(
                    f"{layer['name']} ({layer['feature_count']} features; {fields})",
                    layer["name"],
                )
            self.layer_combo.setVisible(True)
            self.layer_label.setVisible(True)
            self.structure_label.setText(
                self.tr("Vector source with %d layer(s).") % len(layers)
            )

    def _edit_metadata(self):
        from .metadata_dialog import DlgDatasetMetadata

        dialog = DlgDatasetMetadata(self)
        if self.metadata is not None:
            dialog.set_metadata(self.metadata)
        dialog.exec()
        self.metadata = dialog.get_metadata()

    def _accept(self):
        try:
            if self._info is None or not self.file_edit.text():
                raise ValueError(self.tr("Choose a raster or polygon file."))
            # Derive optional provenance from the shared metadata editor; the
            # registration records missing entries as empty and reports show
            # them as "Not specified".
            provenance = {}
            if self.metadata is not None:
                provenance["source"] = self.metadata.identifier() or ""
                licenses = self.metadata.licenses() or []
                provenance["license"] = "; ".join(line for line in licenses if line)
            kind = "raster" if self._info["raster"] is not None else "vector"
            layer_name = self.layer_combo.currentData() if kind == "vector" else None
            if kind == "vector":
                layers = self._info["vector"]["layers"]
                selected = next(
                    (lyr for lyr in layers if lyr["name"] == layer_name), None
                )
                if selected is None or not selected["numeric_fields"]:
                    raise ValueError(
                        self.tr(
                            "The selected layer has no numeric fields usable "
                            "as prioritization criteria."
                        )
                    )
            self.job = job_manager.register_planning_input_job(
                source_path=self.file_edit.text(),
                task_name=self.name_edit.text().strip(),
                task_notes=self.notes_edit.text().strip(),
                provenance=provenance,
                input_kind=kind,
                vector_layer_name=layer_name,
                qgis_metadata=self.metadata,
            )
        except (ValueError, OSError) as exc:
            QtWidgets.QMessageBox.critical(self, self.tr("Cannot import"), str(exc))
            return
        self.accept()


class DlgScoringProfile(QtWidgets.QDialog):
    """Configure how one band or field becomes a 0-1 priority score.

    Bands and numeric fields are looked up from the managed input; categories
    are discovered from the data and scored through a table, never JSON.
    """

    def __init__(self, job, parent=None, profile=None):
        super().__init__(parent)
        self.job = job
        self.profile = None
        self.setWindowTitle(
            self.tr("Scoring profile — %s") % (job.task_name or str(job.id))
        )
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.name_edit = QtWidgets.QLineEdit()
        form.addRow(self.tr("Profile name"), self.name_edit)

        self.kind = input_kind(job)
        self.band_combo = QtWidgets.QComboBox()
        self.field_combo = QtWidgets.QComboBox()
        if self.kind == "raster":
            for band in job.params.get("band_info", []):
                self.band_combo.addItem(
                    self.tr("Band %d — %s (%s)")
                    % (band["band_index"], band["description"], band["data_type"]),
                    band["band_index"],
                )
            form.addRow(self.tr("Raster band"), self.band_combo)
        else:
            for field in job.params.get("numeric_fields", []):
                label = field["name"] + (
                    f" ({field['alias']})" if field.get("alias") else ""
                )
                self.field_combo.addItem(label, field["name"])
            form.addRow(self.tr("Numeric field"), self.field_combo)

        self.continuous_radio = QtWidgets.QRadioButton(self.tr("Continuous values"))
        self.categorical_radio = QtWidgets.QRadioButton(self.tr("Categories / classes"))
        self.continuous_radio.setChecked(True)
        kind_row = QtWidgets.QHBoxLayout()
        kind_row.addWidget(self.continuous_radio)
        kind_row.addWidget(self.categorical_radio)
        form.addRow(self.tr("Value type"), kind_row)
        layout.addLayout(form)

        # --- Continuous controls ---
        self.continuous_box = QtWidgets.QGroupBox(self.tr("Continuous scoring"))
        continuous_form = QtWidgets.QFormLayout(self.continuous_box)
        self.direction_combo = QtWidgets.QComboBox()
        self.direction_combo.addItem(
            self.tr("Higher values receive higher priority"), "higher"
        )
        self.direction_combo.addItem(
            self.tr("Lower values receive higher priority"), "lower"
        )
        continuous_form.addRow(self.tr("Direction"), self.direction_combo)
        self.minimum = QtWidgets.QDoubleSpinBox()
        self.maximum = QtWidgets.QDoubleSpinBox()
        for widget in (self.minimum, self.maximum):
            widget.setRange(-1e12, 1e12)
            widget.setDecimals(6)
        self.maximum.setValue(1)
        continuous_form.addRow(self.tr("Normalization minimum"), self.minimum)
        continuous_form.addRow(self.tr("Normalization maximum"), self.maximum)
        observed = QtWidgets.QPushButton(self.tr("Use observed range..."))
        observed.clicked.connect(self._use_observed_range)
        continuous_form.addRow("", observed)
        self.stats_label = QtWidgets.QLabel(
            self.tr("Values outside the range are clamped; missing data stay unscored.")
        )
        self.stats_label.setWordWrap(True)
        continuous_form.addRow(self.stats_label)
        self.histogram_label = QtWidgets.QLabel("")
        font = self.histogram_label.font()
        font.setFamily("monospace")
        self.histogram_label.setFont(font)
        continuous_form.addRow(self.histogram_label)
        self.resampling_combo = QtWidgets.QComboBox()
        self.resampling_combo.addItem(
            self.tr("Bilinear (smooth continuous data)"), "bilinear"
        )
        self.resampling_combo.addItem(
            self.tr("Average (aggregating finer data)"), "average"
        )
        self.resampling_combo.addItem(self.tr("Nearest (exact values)"), "nearest")
        continuous_form.addRow(self.tr("Alignment resampling"), self.resampling_combo)
        layout.addWidget(self.continuous_box)

        # --- Categorical controls ---
        self.categorical_box = QtWidgets.QGroupBox(self.tr("Category scores"))
        categorical_layout = QtWidgets.QVBoxLayout(self.categorical_box)
        discover = QtWidgets.QPushButton(self.tr("Discover categories from data"))
        discover.clicked.connect(self._discover_categories)
        categorical_layout.addWidget(discover)
        self.category_table = QtWidgets.QTableWidget(0, 4)
        self.category_table.setHorizontalHeaderLabels(
            [
                self.tr("Code"),
                self.tr("Count"),
                self.tr("Score (0-1)"),
                self.tr("Score it"),
            ]
        )
        self.category_table.horizontalHeader().setStretchLastSection(True)
        categorical_layout.addWidget(self.category_table)
        self.category_note = QtWidgets.QLabel(
            self.tr(
                "Unchecked categories stay unscored (they are not zero). "
                "Categorical data always use nearest-neighbour alignment."
            )
        )
        self.category_note.setWordWrap(True)
        categorical_layout.addWidget(self.category_note)
        layout.addWidget(self.categorical_box)

        self.continuous_radio.toggled.connect(self._update_kind)
        self._update_kind()

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(640, 560)
        if profile:
            self._load(profile)

    def _update_kind(self):
        continuous = self.continuous_radio.isChecked()
        self.continuous_box.setVisible(continuous)
        self.categorical_box.setVisible(not continuous)

    def _selected_band(self) -> int:
        return int(self.band_combo.currentData() or 1)

    def _selected_field(self) -> str:
        return str(self.field_combo.currentData() or "")

    def _use_observed_range(self):
        try:
            path = input_path(self.job)
            if self.kind == "raster":
                stats = observed_band_stats(path, self._selected_band())
                sample = sampled_raster_values(path, self._selected_band())
            else:
                stats = observed_field_stats(path, self._selected_field())
                sample = sampled_field_values(path, self._selected_field())
            if stats["maximum"] <= stats["minimum"]:
                raise ValueError(
                    self.tr(
                        "This input has a constant value; it cannot produce a "
                        "useful priority gradient."
                    )
                )
        except (ValueError, OSError) as exc:
            QtWidgets.QMessageBox.critical(
                self, self.tr("Cannot read values"), str(exc)
            )
            return
        self.minimum.setValue(stats["minimum"])
        self.maximum.setValue(stats["maximum"])
        sampled = (
            self.tr("sampled statistics")
            if stats.get("sampled")
            else self.tr("exact statistics")
        )
        self.stats_label.setText(
            self.tr(
                "Observed range %g to %g (mean %g; %s, managed file footprint). "
                "Values outside the saved range are clamped."
            )
            % (stats["minimum"], stats["maximum"], stats["mean"], sampled)
        )
        bars = histogram_text(sample["values"])
        prefix = (
            self.tr("Distribution (sampled): ")
            if sample.get("sampled")
            else self.tr("Distribution: ")
        )
        self.histogram_label.setText(prefix + bars if bars else "")

    def _discover_categories(self):
        try:
            discovered = discover_categories(
                input_path(self.job),
                self.kind,
                band_index=self._selected_band(),
                field=self._selected_field(),
            )
        except (ValueError, OSError) as exc:
            QtWidgets.QMessageBox.critical(
                self, self.tr("Cannot discover categories"), str(exc)
            )
            return
        self._populate_categories(
            {code: None for code in discovered["counts"]}, discovered["counts"]
        )
        notes = []
        if discovered["sampled"]:
            notes.append(self.tr("counts are sampled"))
        if discovered["truncated"]:
            notes.append(
                self.tr(
                    "only the %d most frequent codes are shown — this input may "
                    "be unsuitable for category scoring"
                )
                % MAX_DISCOVERED_CATEGORIES
            )
        if notes:
            self.category_note.setText(
                self.tr("Note: %s. Unchecked categories stay unscored.")
                % "; ".join(notes)
            )

    def _populate_categories(self, scores: dict, counts: typing.Optional[dict] = None):
        self.category_table.setRowCount(0)
        for code in sorted(scores, key=float):
            row = self.category_table.rowCount()
            self.category_table.insertRow(row)
            code_item = QtWidgets.QTableWidgetItem(str(code))
            code_item.setFlags(QtCore.Qt.ItemIsEnabled)
            self.category_table.setItem(row, 0, code_item)
            count = (counts or {}).get(code, "")
            count_item = QtWidgets.QTableWidgetItem(str(count))
            count_item.setFlags(QtCore.Qt.ItemIsEnabled)
            self.category_table.setItem(row, 1, count_item)
            spin = QtWidgets.QDoubleSpinBox()
            spin.setRange(0, 1)
            spin.setDecimals(3)
            spin.setSingleStep(0.1)
            include = QtWidgets.QCheckBox()
            score = scores.get(code)
            if score is not None:
                spin.setValue(float(score))
                include.setChecked(True)
            self.category_table.setCellWidget(row, 2, spin)
            self.category_table.setCellWidget(row, 3, include)

    def _category_scores(self) -> dict:
        scores = {}
        for row in range(self.category_table.rowCount()):
            include = self.category_table.cellWidget(row, 3)
            if include is not None and include.isChecked():
                code = self.category_table.item(row, 0).text()
                scores[code] = self.category_table.cellWidget(row, 2).value()
        return scores

    def _load(self, profile: dict):
        self.name_edit.setText(profile.get("name", ""))
        if self.kind == "raster":
            index = self.band_combo.findData(profile.get("band_index", 1))
            if index >= 0:
                self.band_combo.setCurrentIndex(index)
        else:
            index = self.field_combo.findData(profile.get("field", ""))
            if index >= 0:
                self.field_combo.setCurrentIndex(index)
        if profile.get("categories"):
            self.categorical_radio.setChecked(True)
            self._populate_categories(profile["categories"])
        else:
            self.continuous_radio.setChecked(True)
            self.minimum.setValue(profile.get("minimum", 0))
            self.maximum.setValue(profile.get("maximum", 1))
            index = self.direction_combo.findData(profile.get("direction", "higher"))
            if index >= 0:
                self.direction_combo.setCurrentIndex(index)
            index = self.resampling_combo.findData(
                profile.get("resampling", "bilinear")
            )
            if index >= 0:
                self.resampling_combo.setCurrentIndex(index)

    def _accept(self):
        try:
            name = self.name_edit.text().strip()
            if not name:
                raise ValueError(self.tr("Give the scoring profile a name."))
            profile: dict = {"name": name}
            if self.kind == "raster":
                profile["band_index"] = self._selected_band()
                profile["field"] = ""
            else:
                field = self._selected_field()
                if not field:
                    raise ValueError(self.tr("Choose a numeric field."))
                profile["field"] = field
                profile["band_index"] = 1
            if self.continuous_radio.isChecked():
                if self.maximum.value() <= self.minimum.value():
                    raise ValueError(
                        self.tr("Normalization maximum must exceed minimum.")
                    )
                profile.update(
                    direction=self.direction_combo.currentData(),
                    minimum=self.minimum.value(),
                    maximum=self.maximum.value(),
                    categories=None,
                    resampling=self.resampling_combo.currentData(),
                )
            else:
                categories = self._category_scores()
                if not categories:
                    raise ValueError(
                        self.tr("Score at least one category, or discover them first.")
                    )
                profile.update(
                    direction="higher",
                    minimum=None,
                    maximum=None,
                    categories=categories,
                    resampling="nearest",
                )
        except ValueError as exc:
            QtWidgets.QMessageBox.critical(self, self.tr("Invalid profile"), str(exc))
            return
        self.profile = save_scoring_profile(self.job, profile)
        self.accept()
