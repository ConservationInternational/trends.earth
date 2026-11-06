import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

import numpy as np
from osgeo import gdal, osr
from qgis.core import QgsApplication, QgsRectangle
from qgis.PyQt import QtWidgets
from te_algorithms.gdal.population import COUNTS, DENSITY_HA
from te_algorithms.gdal.util_numba import calc_cell_area
from te_schemas.results import Band

from LDMP import data_io
from LDMP.calculate import DlgCalculateBase
from LDMP.calculate_drought_vulnerability import DlgCalculateDroughtSummary
from LDMP.jobs.manager import job_manager
from LDMP.localexecution import drought


class DroughtPopulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QgsApplication.instance() is None:
            cls.app = QgsApplication([], False)
            cls.app.initQgis()

    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(directory)
        with (
            patch.object(
                DlgCalculateBase,
                "__init__",
                lambda self, *args: QtWidgets.QDialog.__init__(self),
            ),
            patch.object(DlgCalculateBase, "_finish_initialization"),
        ):
            self.dialog = DlgCalculateDroughtSummary(None, None)
        self.addCleanup(self.dialog.close)
        self.addCleanup(data_io.invalidate_usable_data_caches)
        self.aoi = Mock()
        self.aoi.bounding_box_gee_geojson.return_value = (False, [])
        self.aoi.get_crs_dst_wkt.return_value = "EPSG:4326"

    def population_band(self, pop_type, year=2020, index=1, resolution=0.01):
        path = self.root / f"{pop_type}.tif"
        dataset = gdal.GetDriverByName("GTiff").Create(
            str(path), round(0.02 / resolution), 1, index, gdal.GDT_Float32
        )
        crs = osr.SpatialReference()
        crs.ImportFromEPSG(4326)
        dataset.SetProjection(crs.ExportToWkt())
        dataset.SetGeoTransform((0, resolution, 0, 2, 0, -0.01))
        dataset.GetRasterBand(index).Fill(100)
        dataset = None
        return data_io.Band(
            job=Mock(),
            path=path,
            band_index=index,
            band_info=Band(
                drought.POPULATION_BAND_NAME,
                metadata={"year": year, "type": pop_type, "units": COUNTS},
            ),
        )

    def params(self, population_bands=None):
        self.dataset = Mock()
        self.dataset.get_current_data_file.return_value = self.root / "drought.tif"
        spi = [
            SimpleNamespace(
                band_index=index,
                band_info=Band(
                    drought.SPI_BAND_NAME, metadata={"year": year, "lag": 12}
                ),
            )
            for index, year in enumerate((2015, 2016), start=1)
        ]
        annual = [
            SimpleNamespace(
                band_index=index,
                band_info=Band(
                    drought.POPULATION_BAND_NAME,
                    metadata={"year": year, "type": "total", "units": DENSITY_HA},
                ),
            )
            for index, year in enumerate((2015, 2016), start=3)
        ]
        self.dataset.get_bands.side_effect = lambda name: (
            spi if name == drought.SPI_SPEI_BAND_NAMES else annual
        )
        vulnerability = Mock()
        vulnerability.get_current_band.return_value = SimpleNamespace(
            path=self.root / "jrc.tif",
            band_index=1,
            band_info=Band("Drought Vulnerability (JRC)", metadata={}),
        )
        self.vulnerability = vulnerability
        return drought.get_main_drought_summary_job_params(
            "Test drought",
            self.aoi,
            self.dataset,
            vulnerability,
            population_bands=population_bands,
        )

    def test_default_and_fixed_population_radio_options(self):
        dialog = self.dialog
        self.assertTrue(dialog.radio_population_dataset.isChecked())
        self.assertEqual(dialog.combo_boxes.selected_population_widgets(), [])
        for name in ("total", "male", "female"):
            self.assertFalse(
                getattr(dialog, f"combo_layer_population_{name}").isEnabled()
            )
        dialog.radio_population_total.setChecked(True)
        self.assertEqual(
            dialog.combo_boxes.selected_population_widgets(),
            [dialog.combo_layer_population_total],
        )
        self.assertTrue(dialog.combo_layer_population_total.isEnabled())
        self.assertFalse(dialog.combo_layer_population_male.isEnabled())
        dialog.radio_population_bysex.setChecked(True)
        self.assertFalse(dialog.radio_population_total.isChecked())
        self.assertFalse(dialog.combo_layer_population_total.isEnabled())
        self.assertTrue(dialog.combo_layer_population_male.isEnabled())
        self.assertTrue(dialog.combo_layer_population_female.isEnabled())
        dialog.radio_population_dataset.setChecked(True)
        self.assertEqual(dialog.combo_boxes.selected_population_widgets(), [])

    def test_dropdowns_filter_imported_population_by_type(self):
        imported_jobs = []
        for pop_type in ("total", "male", "female"):
            band = self.population_band(pop_type)
            imported_jobs.append(
                job_manager.create_job_from_dataset(
                    band.path,
                    band.band_info.name,
                    band.band_info.metadata,
                    f"Imported {pop_type}",
                )
            )
        jobs = []
        with (
            patch.object(
                type(job_manager),
                "relevant_jobs",
                new_callable=PropertyMock,
                return_value=jobs,
            ),
            patch("LDMP.data_io.try_prepare_area_of_interest", return_value=self.aoi),
            patch("LDMP.data_io._check_dataset_overlap_raster", return_value=True),
        ):
            for pop_type in ("total", "male", "female"):
                widget = getattr(self.dialog, f"combo_layer_population_{pop_type}")
                widget.populate()
                self.assertEqual(widget.layer_list, [])
            jobs.extend(imported_jobs)
            job_manager.imported_job.emit(imported_jobs[-1])
            for pop_type, job in zip(("total", "male", "female"), imported_jobs):
                widget = getattr(self.dialog, f"combo_layer_population_{pop_type}")
                widget.populate()
                self.assertEqual(len(widget.layer_list), 1)
                self.assertEqual(widget.get_current_band().job.id, job.id)
                self.assertIn(f"Imported {pop_type}", widget.currentText())
                self.assertIn("2020", widget.currentText())
                self.assertIn(pop_type, widget.currentText())

    def test_dialog_submits_selected_population_or_original_annual_series(self):
        self.params()
        dialog = self.dialog
        dialog.aoi = self.aoi
        dialog.script = SimpleNamespace(
            name="drought-vulnerability-summary", name_readable=None
        )
        dialog.combo_boxes.combo_dataset_drought = self.dataset
        dialog.combo_boxes.combo_layer_so3_vulnerability = self.vulnerability
        for pop_type in ("total", "male", "female"):
            widget = getattr(dialog, f"combo_layer_population_{pop_type}")
            widget.layer_list = [self.population_band(pop_type)]
            widget.comboBox_layers.addItem(pop_type)
        for mode in ("dataset", "total", "bysex"):
            with (
                self.subTest(mode=mode),
                patch.object(DlgCalculateBase, "btn_calculate", return_value=True),
                patch.object(dialog, "validate_dataset_selections", return_value=True),
                patch.object(dialog, "validate_layer_extents", return_value=True),
                patch.object(job_manager, "submit_local_job_as_qgstask") as submit,
            ):
                getattr(dialog, f"radio_population_{mode}").setChecked(True)
                dialog.btn_calculate()
                params = submit.call_args.args[0]
                if mode == "dataset":
                    self.assertNotIn("population_mode", params)
                    self.assertEqual(params["layer_population_band_indices"], [3, 4])
                else:
                    types = ["total"] if mode == "total" else ["male", "female"]
                    self.assertEqual(params["population_mode"], "fixed")
                    self.assertEqual(
                        params["layer_population_paths"],
                        [str(self.root / f"{pop_type}.tif") for pop_type in types],
                    )
                    self.assertEqual(
                        [
                            band["metadata"]["type"]
                            for band in params["layer_population_bands"]
                        ],
                        types,
                    )

    def test_bundled_population_parameters_are_unchanged(self):
        params = self.params()
        self.assertEqual(
            params["layer_population_path"], str(self.root / "drought.tif")
        )
        self.assertEqual(params["layer_population_band_indices"], [3, 4])
        self.assertEqual(params["layer_population_years"], [2015, 2016])
        self.assertNotIn("population_mode", params)
        self.assertNotIn("layer_population_paths", params)

    def test_fixed_total_repeats_only_selected_band_for_each_drought_year(self):
        band = self.population_band("total", index=2)
        params = self.params([band])
        self.assertEqual(params["layer_population_paths"], [str(band.path)])
        self.assertEqual(params["layer_population_band_indices"], [2])
        self.assertEqual(params["layer_population_years"], [2020])
        with tempfile.TemporaryDirectory() as directory:
            prepared = drought._prepare_population_override(params, Path(directory))
            self.assertEqual(prepared["layer_population_band_indices"], [1, 1])
            self.assertEqual(prepared["layer_population_years"], [2020, 2020])
            self.assertEqual(len(prepared["layer_population_bands"]), 2)
            self.assertEqual(
                params["layer_population_bands"][0]["metadata"]["units"], COUNTS
            )
            raster = gdal.Open(prepared["layer_population_path"])
            area_ha = calc_cell_area(2, 1.99, 0.01) / 10000
            np.testing.assert_allclose(raster.ReadAsArray() * area_ha, 100, rtol=1e-6)
            raster = None
        self.assertEqual(params["layer_population_band_indices"], [2])

    def test_male_female_counts_are_normalized_before_combining_grids(self):
        bands = [
            self.population_band("male", resolution=0.02),
            self.population_band("female", resolution=0.01),
        ]
        params = self.params(bands)
        with tempfile.TemporaryDirectory() as directory:
            prepared = drought._prepare_population_override(params, Path(directory))
            self.assertEqual(prepared["layer_population_band_indices"], [1, 2, 1, 2])
            self.assertEqual(
                [
                    band["metadata"]["type"]
                    for band in prepared["layer_population_bands"]
                ],
                ["male", "female", "male", "female"],
            )
            raster = gdal.Open(prepared["layer_population_path"])
            area_ha = calc_cell_area(2, 1.99, 0.01) / 10000
            counts = raster.ReadAsArray() * area_ha
            np.testing.assert_allclose(counts[0].sum(), 100, rtol=1e-6)
            np.testing.assert_allclose(counts[1].sum(), 200, rtol=1e-6)
            raster = None

    @patch("LDMP.calculate_drought_vulnerability.QtWidgets.QMessageBox.critical")
    def test_missing_population_and_mismatched_years_block_submission(self, message):
        dialog = self.dialog
        dialog.combo_dataset_drought.dataset_list = [Mock()]
        dialog.combo_layer_so3_vulnerability.layer_list = [Mock()]
        dialog.radio_population_total.setChecked(True)
        self.assertFalse(dialog.validate_dataset_selections(dialog.combo_boxes))
        self.assertEqual(message.call_count, 1)
        dialog.radio_population_bysex.setChecked(True)
        dialog.combo_layer_population_male.layer_list = [self.population_band("male")]
        dialog.combo_layer_population_female.layer_list = [
            self.population_band("female", year=2019)
        ]
        for name in ("male", "female"):
            getattr(dialog, f"combo_layer_population_{name}").comboBox_layers.addItem(
                name
            )
        self.assertFalse(dialog.validate_dataset_selections(dialog.combo_boxes))
        self.assertIn("same year", message.call_args.args[2])

    @patch("LDMP.calculate_drought_vulnerability.QtWidgets.QMessageBox.critical")
    def test_population_extent_is_validated_only_for_fixed_scenarios(self, message):
        dialog = self.dialog
        dialog.aoi = self.aoi
        with (
            patch.object(
                dialog.combo_dataset_drought,
                "get_current_extent",
                return_value=QgsRectangle(0, 0, 1, 1),
            ),
            patch.object(
                dialog.combo_layer_population_total,
                "get_current_extent",
                return_value=QgsRectangle(0, 0, 0.5, 0.5),
            ),
        ):
            self.aoi.calc_frac_overlap.return_value = 1
            self.assertTrue(dialog.validate_layer_extents(dialog.combo_boxes))
            dialog.radio_population_total.setChecked(True)
            self.aoi.calc_frac_overlap.side_effect = [1, 0.5]
            self.assertFalse(dialog.validate_layer_extents(dialog.combo_boxes))
            self.assertIn("population layer", message.call_args.args[2])

    def test_execution_preserves_source_parameters_and_cleans_temporary_files(self):
        for fixed in (False, True):
            with self.subTest(fixed=fixed):
                params = self.params([self.population_band("total")] if fixed else None)
                original = copy.deepcopy(params)
                job = SimpleNamespace(params=params)
                temporary_paths = []

                def summarize(
                    execution_job,
                    *_args,
                    fixed=fixed,
                    job=job,
                    temporary_paths=temporary_paths,
                    **_kwargs,
                ):
                    if fixed:
                        path = Path(execution_job.params["layer_population_path"])
                        self.assertTrue(path.exists())
                        temporary_paths.append(path)
                    else:
                        self.assertIs(execution_job, job)
                    return "summary result"

                with (
                    patch.object(
                        drought,
                        "summarise_drought_vulnerability",
                        side_effect=summarize,
                    ),
                    patch.object(drought, "AOI"),
                ):
                    result = drought.compute_drought_vulnerability(
                        job,
                        self.aoi,
                        self.root / "job.json",
                        self.root / "out.tif",
                        None,
                        None,
                    )
                self.assertEqual(result, "summary result")
                self.assertEqual(job.params, original)
                self.assertTrue(all(not path.exists() for path in temporary_paths))
                json.dumps(job.params)

    def test_invalid_fixed_population_inputs_are_rejected(self):
        params = self.params([self.population_band("total")])
        for field, value in (
            ("layer_population_paths", []),
            ("layer_population_band_indices", [1, 2]),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                drought._prepare_population_override(
                    {**params, field: value}, self.root
                )
        with self.assertRaises(ValueError):
            self.params([])
