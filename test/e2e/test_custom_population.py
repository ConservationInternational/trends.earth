"""Offline E2E coverage of custom imports and population-aware summaries."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from osgeo import gdal, osr
from qgis.core import QgsApplication
from qgis.gui import QgsMessageBar
from qgis.PyQt import QtWidgets
from te_algorithms.gdal import drought
from te_algorithms.gdal.land_deg import config as ld
from te_algorithms.gdal.land_deg.land_deg import summarise_land_degradation
from te_algorithms.gdal.land_deg.land_deg_numba import calc_lc_trans
from te_algorithms.gdal.population import COUNTS, DENSITY_HA, DENSITY_KM2
from te_algorithms.gdal.util_numba import calc_cell_area
from te_schemas.aoi import AOI
from te_schemas.land_cover import LCLegendNesting
from te_schemas.productivity import ProductivityMode
from te_schemas.results import Band, DataType, RasterResults

from LDMP import conf, data_io, lc_setup, worker
from LDMP.jobs.manager import job_manager
from LDMP.summary import calc_cell_area as plugin_cell_area

from .harness import ModalGuard, isolated_plugin_state, job_output_path
from .subindicators import check_population_bands
from .summary_checks import check_drought_summary, check_sdg_summary

COUNTS_BY_CELL = np.array([[500.25, 1000.5, 250.125, ld.NODATA_VALUE]])
SHAPE = (10, 40)
FINE_GRID = (0, 0.001, 0, 2, 0, -0.001)
COARSE_GRID = (0, 0.01, 0, 2, 0, -0.01)
YEARS = {"year_initial": 2000, "year_final": 2015}


def write_raster(path, arrays, transform=FINE_GRID, datatype=gdal.GDT_Int16):
    arrays = np.asarray(arrays)
    dataset = gdal.GetDriverByName("GTiff").Create(
        str(path), arrays.shape[-1], arrays.shape[-2], len(arrays), datatype
    )
    crs = osr.SpatialReference()
    crs.ImportFromEPSG(4326)
    dataset.SetProjection(crs.ExportToWkt())
    dataset.SetGeoTransform(transform)
    for index, values in enumerate(arrays, start=1):
        band = dataset.GetRasterBand(index)
        band.SetNoDataValue(int(ld.NODATA_VALUE))
        band.WriteArray(values)
    dataset = None
    return path


class CustomPopulationE2ETest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QgsApplication.instance() is None:
            cls.app = QgsApplication([], False)
            cls.app.initQgis()

    def setUp(self):
        self.window = QtWidgets.QWidget()
        self.message_bar = QgsMessageBar(self.window)
        interface = SimpleNamespace(
            mainWindow=lambda: self.window, messageBar=lambda: self.message_bar
        )
        self.enterContext(patch.object(worker, "iface", interface))
        self.addCleanup(self.window.deleteLater)
        self.directory = tempfile.TemporaryDirectory(prefix="te_custom_population_e2e_")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.state = isolated_plugin_state()
        self.state.__enter__()
        self.addCleanup(self.state.__exit__, None, None, None)
        settings = (
            conf.Setting.LC_IPCC_NESTING,
            conf.Setting.LC_CUSTOM_IMPORT_NESTING,
        )
        for setting in settings:
            saved = conf.settings_manager.get_value(setting)
            self.addCleanup(conf.settings_manager.write_value, setting, saved)
        esa = LCLegendNesting.Schema().loads(
            (
                Path(lc_setup.__file__).parent
                / "data/land_cover_nesting_unccd_esa.json"
            ).read_text()
        )
        self.nesting = LCLegendNesting(
            parent=esa.parent,
            child=copy.deepcopy(esa.parent),
            nesting={
                **{c.code: [c.code] for c in esa.parent.key},
                esa.parent.nodata.code: [esa.parent.nodata.code],
            },
        )
        lc_setup.ipcc_lc_nesting_to_settings(self.nesting)
        self.aoi = AOI(
            {
                "type": "Polygon",
                "coordinates": [
                    [[0, 1.99], [0.04, 1.99], [0.04, 2], [0, 2], [0, 1.99]]
                ],
            }
        )

    def import_raster(self, dialog_class, source, year, configure):
        imported = []

        def record(job):
            if all(existing.id != job.id for existing in imported):
                imported.append(job)

        job_manager.imported_job.connect(record)
        dialog = dialog_class()
        try:
            with ModalGuard() as guard:
                dialog.checkbox_clip_to_region.setChecked(False)
                widget = dialog.input_widget
                widget.radio_raster_input.setChecked(True)
                widget.lineEdit_raster_file.setText(str(source))
                widget.comboBox_bandnumber.clear()
                widget.comboBox_bandnumber.addItem("1")
                widget.spinBox_data_year.setValue(year)
                widget.lineEdit_nodata.setText(str(int(ld.NODATA_VALUE)))
                widget.groupBox_output_resolution.setChecked(False)
                configure(dialog)
                # Use the real validation/import slot, not a mocked worker.
                dialog.done(QtWidgets.QDialog.Accepted)
                self.assertEqual(guard.errors, [])
            self.assertEqual(len(imported), 1)
            job = imported[0]
            self.assertTrue(job_output_path(job).exists())
            # Read metadata back from disk, rather than only checking the dialog.
            persisted = json.loads(job_manager.get_job_file_path(job).read_text())
            self.assertEqual(
                persisted["results"]["rasters"],
                json.loads(job.results.Schema().dumps(job.results))["rasters"],
            )
            return job
        finally:
            job_manager.imported_job.disconnect(record)
            dialog.close()
            dialog.deleteLater()
            Path(dialog._output_raster_path).unlink(missing_ok=True)
            QgsApplication.processEvents()

    def population_inputs(self, units, by_sex, legacy=False, custom=True):
        jobs = []
        for pop_type, share in (
            (("male", 0.4), ("female", 0.6)) if by_sex else (("total", 1),)
        ):
            values = COUNTS_BY_CELL.copy()
            values[values != ld.NODATA_VALUE] *= share
            area_ha = calc_cell_area(2, 1.99, 0.01) / 10000
            if units == DENSITY_HA:
                values[values != ld.NODATA_VALUE] /= area_ha
            elif units == DENSITY_KM2:
                values[values != ld.NODATA_VALUE] /= area_ha / 100
            source = write_raster(
                self.root / f"{pop_type}.tif", [values], COARSE_GRID, gdal.GDT_Float32
            )
            if not custom:
                self.assertEqual(units, DENSITY_HA)
                jobs.append(
                    job_manager.create_job_from_dataset(
                        source,
                        ld.POPULATION_BAND_NAME,
                        {
                            "year": 2015,
                            "type": pop_type,
                            "units": DENSITY_HA,
                            "source": "WorldPop",
                        },
                        "Generated downloaded-population fixture",
                    )
                )
                continue

            def configure(dialog, pop_type=pop_type):
                dialog.combo_population_units.setCurrentIndex(
                    (COUNTS, DENSITY_HA, DENSITY_KM2).index(units)
                )
                getattr(dialog, f"radio_population_{pop_type}").setChecked(True)

            job = self.import_raster(
                data_io.DlgDataIOImportPopulation, source, 2015, configure
            )
            metadata = job.results.get_bands()[0].metadata
            self.assertEqual(metadata["units"], DENSITY_HA)
            self.assertEqual(metadata["input_units"], units)
            self.assertEqual(
                next(iter(job.results.rasters.values())).datatype, DataType.FLOAT32
            )
            dataset = gdal.Open(str(job_output_path(job)))
            self.assertEqual(dataset.GetRasterBand(1).DataType, gdal.GDT_Float32)
            dataset = None
            if legacy:
                # Older imports stored counts and lacked units metadata.
                job.results.uri.uri = source
                for raster in job.results.rasters.values():
                    raster.uri.uri = source
                metadata.pop("units")
                metadata.pop("input_units")
            jobs.append(job)
        return jobs

    def land_cover_inputs(self, resolution=0.001):
        width = round(0.04 / resolution)
        height = round(0.01 / resolution)
        stripe = width // 4
        transform = (0, resolution, 0, 2, 0, -resolution)
        initial = np.full((height, width), 1, dtype=np.int16)
        initial[:, stripe : 2 * stripe] = 3
        initial[:, 2 * stripe : 3 * stripe] = 6
        initial[-1, -1] = ld.NODATA_VALUE
        final = initial.copy()
        final[:, :stripe] = 5
        final[:, 2 * stripe : 3 * stripe] = 1
        final[:, 3 * stripe :] = 5
        final[-1, -1] = ld.NODATA_VALUE
        imported = []
        for year, values in ((2000, initial), (2015, final)):
            source = write_raster(
                self.root / f"land_cover_{year}.tif", [values], transform
            )
            job = self.import_raster(
                lc_setup.DlgDataIOImportLC,
                source,
                year,
                lambda dialog: setattr(dialog, "saved_nesting", self.nesting),
            )
            dataset = gdal.Open(str(job_output_path(job)))
            np.testing.assert_array_equal(dataset.ReadAsArray(), values)
            self.assertAlmostEqual(dataset.GetGeoTransform()[1], resolution)
            imported.append(dataset.ReadAsArray())
            dataset = None
        matrix = lc_setup.get_trans_matrix(get_default=True, save_settings=False)
        transitions = calc_lc_trans(*imported, matrix.legend.get_multiplier())
        from_codes, to_codes = matrix.get_list()
        degradation = np.full(initial.shape, ld.NODATA_VALUE, dtype=np.int16)
        for code, result in zip(from_codes, to_codes):
            degradation[transitions == code] = result
        np.testing.assert_array_equal(
            degradation[0, : 3 * stripe], [-1] * stripe + [0] * stripe + [1] * stripe
        )
        metadata = {
            **YEARS,
            "nesting": LCLegendNesting.Schema().dumps(self.nesting),
            "trans_matrix": matrix.Schema().dumps(matrix),
        }
        bands = [
            Band(ld.LC_DEG_BAND_NAME, metadata=metadata),
            Band("Land cover", metadata={"year": 2000}),
            Band("Land cover", metadata={"year": 2015}),
            Band(ld.LC_TRANS_BAND_NAME, metadata=YEARS.copy()),
        ]
        path = write_raster(
            self.root / "land_cover_indicators.tif",
            [degradation, *imported, transitions],
            transform,
        )
        return path, bands

    def run_summaries(
        self, units, by_sex, legacy=False, lc_resolution=0.001, custom_population=True
    ):
        population_jobs = self.population_inputs(
            units, by_sex, legacy, custom=custom_population
        )
        lc_path, lc_bands = self.land_cover_inputs(lc_resolution)
        soc = write_raster(
            self.root / "soc.tif",
            [np.zeros(SHAPE), np.full(SHAPE, 100), np.full(SHAPE, 100)],
        )
        lpd = write_raster(self.root / "lpd.tif", [np.full(SHAPE, 4)])
        dump = Band.Schema().dump
        params = {
            "prod_mode": ProductivityMode.CUSTOM_5_CLASS_LPD.value,
            "layer_lc_path": str(lc_path),
            "layer_lc_deg_band": dump(lc_bands[0]),
            "layer_lc_deg_band_index": 1,
            "layer_lc_deg_years": YEARS.copy(),
            "layer_lc_aux_bands": [dump(b) for b in lc_bands[1:3]],
            "layer_lc_aux_band_indexes": [2, 3],
            "layer_lc_years": [2000, 2015],
            "layer_lc_trans_path": str(lc_path),
            "layer_lc_trans_band": dump(lc_bands[3]),
            "layer_lc_trans_band_index": 4,
            "layer_soc_path": str(soc),
            "layer_soc_deg_band": dump(
                Band(ld.SOC_DEG_BAND_NAME, metadata=YEARS.copy())
            ),
            "layer_soc_deg_band_index": 1,
            "layer_soc_deg_years": YEARS.copy(),
            "layer_soc_aux_bands": [
                dump(Band(ld.SOC_BAND_NAME, metadata={"year": y})) for y in (2000, 2015)
            ],
            "layer_soc_aux_band_indexes": [2, 3],
            "layer_soc_years": [2000, 2015],
            "layer_lpd_path": str(lpd),
            "layer_lpd_band": dump(
                Band(ld.CUSTOM_LPD_BAND_NAME, metadata=YEARS.copy())
            ),
            "layer_lpd_band_index": 1,
            "layer_lpd_years": YEARS.copy(),
            "layer_population_paths": [
                str(job_output_path(j)) for j in population_jobs
            ],
            "layer_population_bands": [
                dump(j.results.get_bands()[0]) for j in population_jobs
            ],
            "layer_population_band_indexes": [1] * len(population_jobs),
        }
        job = copy.deepcopy(population_jobs[0])
        job.params = {"periods": [{"name": "baseline", "params": params}]}
        results = summarise_land_degradation(
            job, self.aoi, self.root / "sdg.json", n_cpus=1, parallel_backend="thread"
        )
        # SDG selects the productivity reference grid; drought selects the finest
        # input grid, including the native land-cover-derived water mask.
        self.check_results(results, "sdg", by_sex, 0.001)
        spi = np.zeros(SHAPE, dtype=np.int16)
        spi[:, :10] = -1500
        spi[:, 20:30] = -2000
        lc_dataset = gdal.Open(str(lc_path))
        water = (lc_dataset.GetRasterBand(3).ReadAsArray() == 7).astype(np.int16)
        water_transform = lc_dataset.GetGeoTransform()
        lc_dataset = None
        water_path = write_raster(self.root / "water.tif", [water], water_transform)
        indicators = write_raster(
            self.root / "drought_indicators.tif",
            [spi, np.full(SHAPE, 42)],
        )
        source_paths = [str(job_output_path(j)) for j in population_jobs]
        # Do not stack counts here: select native population bands separately.
        drought_bands = [dump(j.results.get_bands()[0]) for j in population_jobs]
        if by_sex:
            population_vrt = self.root / "population_by_sex.vrt"
            vrt = gdal.BuildVRT(str(population_vrt), source_paths, separate=True)
            vrt.FlushCache()
            vrt = None
            population_path = population_vrt
        else:
            population_path = Path(source_paths[0])
        job.params = {
            "layer_spi_path": str(indicators),
            "layer_spi_bands": [
                dump(Band(drought.SPI_BAND_NAME, metadata={"year": 2015, "lag": 12}))
            ],
            "layer_spi_band_indices": [1],
            "layer_spi_years": [2015],
            "layer_spi_lag": 12,
            "layer_population_path": str(population_path),
            "layer_population_bands": drought_bands,
            "layer_population_band_indices": list(range(1, len(population_jobs) + 1)),
            "layer_jrc_path": str(indicators),
            "layer_jrc_band": dump(Band(drought.JRC_BAND_NAME, metadata={})),
            "layer_jrc_band_index": 2,
            "layer_water_path": str(water_path),
            "layer_water_band": dump(Band(drought.WATER_MASK_BAND_NAME, metadata={})),
            "layer_water_band_index": 1,
        }
        results = drought.summarise_drought_vulnerability(
            job,
            self.aoi,
            self.root / "drought.json",
            n_cpus=1,
            parallel_backend="thread",
        )
        self.check_results(results, "drought", by_sex, min(lc_resolution, 0.001))

    def check_results(self, results, kind, by_sex, resolution=0.001):
        results = RasterResults.Schema().load(RasterResults.Schema().dump(results))
        data = json.loads((self.root / f"{kind}_summary.json").read_text())
        checker = check_sdg_summary if kind == "sdg" else check_drought_summary
        report = checker(data)
        self.assertEqual(report.errors, [], report.errors)
        population = (
            data["affected_population"]["baseline"]["summary"]
            if kind == "sdg"
            else data["drought"]["tier_two"]["2015"]
        )
        expected = {"Total population": 1750.875}
        if by_sex:
            expected.update({"Male population": 700.35, "Female population": 1050.525})
        for pop_type, total in expected.items():
            values = {
                v["name"]: v["population"] for v in population[pop_type]["values"]
            }
            # Reports serialize whole people per class; rasters retain fractions.
            self.assertAlmostEqual(sum(values.values()), total, delta=3)
            affected_class = "Degraded" if kind == "sdg" else "Moderate drought"
            self.assertAlmostEqual(
                values[affected_class], total * 500.25 / 1750.875, delta=1
            )
        dataset = gdal.Open(str(results.uri.uri))
        self.assertAlmostEqual(dataset.GetGeoTransform()[1], resolution)
        width = round(0.04 / resolution)
        height = round(0.01 / resolution)
        stripe = width // 4
        population_name = (
            ld.POP_AFFECTED_BAND_NAME
            if kind == "sdg"
            else drought.POP_AT_MAX_DROUGHT_BAND_NAME
        )
        for index, band in enumerate(results.get_bands(), start=1):
            if band.name != population_name:
                continue
            actual = dataset.GetRasterBand(index)
            self.assertEqual(actual.DataType, gdal.GDT_Float32)
            cropped = gdal.Translate(
                "", dataset, format="MEM", bandList=[index], projWin=[0, 2, 0.04, 1.99]
            )
            values = cropped.ReadAsArray()
            cropped = None
            self.assertEqual(values.shape, (height, width))
            np.testing.assert_array_equal(values[:, 3 * stripe :], ld.NODATA_VALUE)
            share = {"total": 1, "male": 0.4, "female": 0.6}[band.metadata["type"]]
            self.assertAlmostEqual(
                float(np.abs(values[:, : 3 * stripe]).sum()),
                1750.875 * share,
                delta=0.02,
            )
            self.assertTrue(np.all(values[:, :stripe] < 0))
            self.assertTrue(np.all(values[:, stripe : 2 * stripe] > 0))
        dataset = None
        self.assertTrue(list(self.root.glob(f"{kind}*.xlsx")))

    def test_custom_population_and_land_cover_summaries(self):
        for units in (COUNTS, DENSITY_HA, DENSITY_KM2):
            for by_sex in (False, True):
                with self.subTest(units=units, by_sex=by_sex):
                    self.run_summaries(units, by_sex)

    def test_legacy_count_population_and_custom_land_cover_summaries(self):
        for by_sex in (False, True):
            with self.subTest(by_sex=by_sex):
                self.run_summaries(COUNTS, by_sex, legacy=True)

    def test_custom_land_cover_resolution_with_custom_and_default_population(self):
        for resolution in (0.0005, 0.001, 0.002):
            for custom in (False, True):
                for by_sex in (False, True):
                    with self.subTest(
                        resolution=resolution, custom_population=custom, by_sex=by_sex
                    ):
                        self.run_summaries(
                            COUNTS if custom else DENSITY_HA,
                            by_sex,
                            lc_resolution=resolution,
                            custom_population=custom,
                        )

    def test_fast_import_worker_records_success_before_returning(self):
        class FastWorker(worker.AbstractWorker):
            def work(self):
                return True

        for _ in range(20):
            result = worker.StartWorker(FastWorker, "E2E fast import")
            self.assertTrue(result.success)
            self.assertIs(result.get_return(), True)
            QgsApplication.processEvents()

    def test_import_worker_propagates_failure_and_cancellation(self):
        class FailingWorker(worker.AbstractWorker):
            def work(self):
                raise ValueError("Invalid population")

        class CancelledWorker(worker.AbstractWorker):
            def work(self):
                raise worker.UserAbortedNotification()

        with self.assertRaisesRegex(ValueError, "Invalid population"):
            worker.StartWorker(FailingWorker, "E2E failed import")
        result = worker.StartWorker(CancelledWorker, "E2E cancelled import")
        self.assertIsNone(result.success)
        QgsApplication.processEvents()


class PopulationMetadataTest(unittest.TestCase):
    def test_plugin_and_algorithms_use_same_cell_area_math(self):
        for latitude in (-70, -34, 0, 34, 70):
            with self.subTest(latitude=latitude):
                self.assertAlmostEqual(
                    calc_cell_area(latitude, latitude + 0.003, 0.003),
                    plugin_cell_area(latitude, latitude + 0.003, 0.003),
                    delta=1e-4,
                )

    def band(self, pop_type="total", units=COUNTS):
        return Band(
            ld.POPULATION_BAND_NAME,
            metadata={"type": pop_type, "year": 2015, "units": units},
        )

    def test_supported_units_and_legacy_counts(self):
        for units in (COUNTS, DENSITY_HA, DENSITY_KM2):
            with self.subTest(units=units):
                check_population_bands([self.band(units=units)])
                check_population_bands(
                    [self.band("male", units), self.band("female", units)]
                )
        legacy = self.band()
        legacy.metadata.pop("units")
        check_population_bands([legacy])

    def test_invalid_or_missing_population_metadata(self):
        for bands, error in (
            ([], "no population"),
            ([self.band(units="unknown")], "Unsupported population units"),
            ([self.band("male")], "incomplete male/female"),
            ([self.band("unknown")], "Unsupported population type"),
        ):
            with (
                self.subTest(error=error),
                self.assertRaisesRegex(AssertionError, error),
            ):
                check_population_bands(bands)
        band = self.band()
        band.metadata.pop("year")
        with self.assertRaisesRegex(AssertionError, "missing its year"):
            check_population_bands([band])
