import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from osgeo import gdal, osr
from qgis.PyQt import QtWidgets
from te_algorithms.gdal.population import COUNTS, DENSITY_HA, DENSITY_KM2
from te_algorithms.gdal.util_numba import calc_cell_area

from LDMP.data_io import (
    DlgDataIOImportBase,
    DlgDataIOImportPopulation,
    Ui_DlgDataIOImportPopulation,
)


class ImportPopulationTests(unittest.TestCase):
    def test_population_type_defaults_to_total(self):
        dialog = Mock()
        dialog.radio_population_male.isChecked.return_value = False
        dialog.radio_population_female.isChecked.return_value = False

        population_type = DlgDataIOImportPopulation._population_type(dialog)

        self.assertEqual(population_type, "total")

    def test_population_type_returns_male(self):
        dialog = Mock()
        dialog.radio_population_male.isChecked.return_value = True

        population_type = DlgDataIOImportPopulation._population_type(dialog)

        self.assertEqual(population_type, "male")

    def test_population_type_returns_female(self):
        dialog = Mock()
        dialog.radio_population_male.isChecked.return_value = False
        dialog.radio_population_female.isChecked.return_value = True

        population_type = DlgDataIOImportPopulation._population_type(dialog)

        self.assertEqual(population_type, "female")

    def test_population_band_metadata_records_normalized_and_input_units(self):
        dialog = Mock()
        dialog.input_widget.spinBox_data_year.text.return_value = "2020"
        dialog._population_units.return_value = COUNTS

        metadata = DlgDataIOImportPopulation._population_band_metadata(dialog, "total")

        self.assertEqual(
            metadata,
            {
                "year": 2020,
                "source": "custom data",
                "type": "total",
                "units": DENSITY_HA,
                "input_units": COUNTS,
            },
        )

    def test_population_unit_options_in_gui(self):
        dialog = QtWidgets.QDialog()
        ui = Ui_DlgDataIOImportPopulation()
        ui.setupUi(dialog)
        self.assertEqual(ui.combo_population_units.count(), 3)
        for index, units in enumerate((COUNTS, DENSITY_HA, DENSITY_KM2)):
            ui.combo_population_units.setCurrentIndex(index)
            self.assertEqual(DlgDataIOImportPopulation._population_units(ui), units)

    def test_population_dialog_stores_float32_and_shows_units_in_settings(self):
        dialog = DlgDataIOImportPopulation()
        try:
            self.assertEqual(dialog.warp_data_type, gdal.GDT_Float32)
            self.assertEqual(dialog.datatype, "continuous")
            self.assertEqual(dialog._population_units(), COUNTS)
            self.assertGreaterEqual(
                dialog.tab_settings_layout.indexOf(dialog.groupBox_population_units),
                0,
            )
        finally:
            dialog.close()
            Path(dialog._output_raster_path).unlink(missing_ok=True)

    @patch("LDMP.data_io.normalize_population_raster")
    def test_population_is_normalized_before_warping(self, normalize):
        dialog = Mock()
        dialog._population_units.return_value = DENSITY_KM2
        DlgDataIOImportPopulation._prepare_import_raster(
            dialog, "input.tif", "density.tif", 2
        )
        normalize.assert_called_once_with("input.tif", "density.tif", DENSITY_KM2, 2)

    @patch("LDMP.data_io.QtWidgets.QMessageBox.critical")
    def test_vector_polygon_counts_are_rejected(self, message):
        dialog = Mock()
        dialog.input_widget.radio_raster_input.isChecked.return_value = False
        dialog._population_units.return_value = COUNTS
        DlgDataIOImportPopulation.validate_input(dialog, QtWidgets.QDialog.Accepted)
        message.assert_called_once()
        dialog._validate_base_input.assert_not_called()
        dialog.ok_clicked.assert_not_called()

    @patch("LDMP.data_io.QtWidgets.QMessageBox.critical")
    def test_population_import_error_is_reported(self, message):
        dialog = Mock()
        dialog._import_population.side_effect = ValueError("Invalid population units")
        self.assertFalse(DlgDataIOImportPopulation.ok_clicked(dialog))
        message.assert_called_once()
        dialog.finalize_import.assert_not_called()

    def test_count_grid_warning_tracks_file_units_and_input_type(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for name, epsg, rotation in (
                ("projected", 3857, 0),
                ("rotated", 4326, 0.001),
                ("wgs84", 4326, 0),
                ("missing_crs", None, 0),
            ):
                path = Path(directory) / f"{name}.tif"
                source = gdal.GetDriverByName("GTiff").Create(
                    str(path), 1, 1, 1, gdal.GDT_Float32
                )
                if epsg is not None:
                    projection = osr.SpatialReference()
                    projection.ImportFromEPSG(epsg)
                    source.SetProjection(projection.ExportToWkt())
                source.SetGeoTransform((73, 0.003, rotation, 34, 0, -0.003))
                source = None
                paths.append(path)
            dialog = DlgDataIOImportPopulation()
            try:
                dialog.input_widget.radio_raster_input.setChecked(True)
                for index, path in enumerate(paths):
                    dialog.input_widget.lineEdit_raster_file.setText(str(path))
                    self.assertEqual(
                        bool(dialog.population_grid_warning.text()), index != 2
                    )
                dialog.input_widget.lineEdit_raster_file.setText(str(paths[0]))
                for index in (1, 2):
                    dialog.combo_population_units.setCurrentIndex(index)
                    self.assertEqual(dialog.population_grid_warning.text(), "")
                dialog.combo_population_units.setCurrentIndex(0)
                self.assertIn("EPSG:4326", dialog.population_grid_warning.text())
                dialog.input_widget.radio_polygon_input.setChecked(True)
                self.assertEqual(dialog.population_grid_warning.text(), "")
            finally:
                dialog.close()
                Path(dialog._output_raster_path).unlink(missing_ok=True)

    @patch("LDMP.data_io.get_raster_stats")
    @patch("LDMP.data_io.QtWidgets.QMessageBox.warning")
    def test_incompatible_count_grid_blocks_import_before_statistics(
        self, message, stats
    ):
        dialog = Mock()
        dialog.input_widget.radio_raster_input.isChecked.return_value = True
        dialog.input_widget.spinBox_data_year.text.return_value = "2020"
        dialog.input_widget.spinBox_data_year.specialValueText.return_value = ""
        dialog._validate_base_input.return_value = True
        dialog._update_population_grid_warning.return_value = "Incompatible grid"
        DlgDataIOImportPopulation.validate_input(dialog, QtWidgets.QDialog.Accepted)
        message.assert_called_once()
        stats.assert_not_called()
        dialog.ok_clicked.assert_not_called()

    def test_actual_population_import_normalization_preserves_fractions(self):
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.tif"
            output_path = Path(directory) / "density.tif"
            source = gdal.GetDriverByName("GTiff").Create(
                str(source_path), 2, 1, 1, gdal.GDT_Float32
            )
            projection = osr.SpatialReference()
            projection.ImportFromEPSG(4326)
            source.SetProjection(projection.ExportToWkt())
            source.SetGeoTransform((73, 0.003, 0, 34, 0, -0.003))
            source.GetRasterBand(1).SetNoDataValue(-9999)
            source.GetRasterBand(1).WriteArray(np.array([[125.5, -9999]]))
            source = None
            dialog = Mock()
            dialog._population_units.return_value = DENSITY_KM2
            DlgDataIOImportPopulation._prepare_import_raster(
                dialog, str(source_path), str(output_path), 1
            )
            result = gdal.Open(str(output_path))
            self.assertEqual(result.GetRasterBand(1).DataType, gdal.GDT_Float32)
            self.assertAlmostEqual(result.ReadAsArray()[0, 0], 1.255, places=6)
            self.assertEqual(result.ReadAsArray()[0, 1], -32768)
            result = None

    @patch("LDMP.data_io.worker.StartWorker")
    def test_count_import_resampling_does_not_duplicate_people(self, start_worker):
        def work(worker_class, _message, *args):
            return SimpleNamespace(success=worker_class(*args).work())

        start_worker.side_effect = work
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.tif"
            output_path = Path(directory) / "resampled.tif"
            source = gdal.GetDriverByName("GTiff").Create(
                str(source_path), 1, 1, 1, gdal.GDT_Float32
            )
            projection = osr.SpatialReference()
            projection.ImportFromEPSG(4326)
            source.SetProjection(projection.ExportToWkt())
            source.SetGeoTransform((73, 0.003, 0, 34, 0, -0.003))
            source.GetRasterBand(1).WriteArray(np.array([[500.25]]))
            source = None
            dialog = Mock()
            dialog.warp_data_type = gdal.GDT_Float32
            dialog.input_widget.lineEdit_raster_file.text.return_value = str(
                source_path
            )
            dialog.input_widget.comboBox_bandnumber.currentText.return_value = "1"
            dialog.input_widget.groupBox_output_resolution.isChecked.return_value = True
            dialog.extent_as_list.return_value = []
            dialog.get_out_res_wgs84.return_value = 0.0003
            dialog.get_resample_mode.return_value = gdal.GRA_NearestNeighbour
            dialog._population_units.return_value = COUNTS
            dialog._prepare_import_raster.side_effect = lambda *args: (
                DlgDataIOImportPopulation._prepare_import_raster(dialog, *args)
            )
            self.assertTrue(DlgDataIOImportBase.warp_raster(dialog, str(output_path)))
            result = gdal.Open(str(output_path))
            values = result.ReadAsArray()
            self.assertEqual(values.shape, (10, 10))
            transform = result.GetGeoTransform()
            areas_ha = np.array(
                [
                    calc_cell_area(
                        transform[3] + row * transform[5],
                        transform[3] + (row + 1) * transform[5],
                        transform[1],
                    )
                    / 10000
                    for row in range(10)
                ]
            )[:, None]
            self.assertAlmostEqual(float((values * areas_ha).sum()), 500.25, places=3)
            result = None
