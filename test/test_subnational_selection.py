import os
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np
from osgeo import gdal, ogr, osr
from qgis.core import QgsApplication

from LDMP.calculate_ldn import (
    DlgCalculateLDNSummaryTableAdmin,
    plan_subnational_mosaics,
    subnational_mosaic_key,
)
from LDMP.data_io import SubnationalBand

# Two units side by side. Every unit result covers the whole area, as when each
# unit is exported for a bounding box that overlaps its neighbours.
UNITS = [
    {"id": "left", "name": "Left"},
    {"id": "right", "name": "Right"},
]
WIDTH, HEIGHT = 20, 10


def _write_unit_polygon(path, x0, x1):
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    layer = ds.CreateLayer("unit", srs, ogr.wkbMultiPolygon)
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetGeometry(
        ogr.CreateGeometryFromWkt(
            f"MULTIPOLYGON((({x0} 0,{x1} 0,{x1} {HEIGHT},{x0} {HEIGHT},{x0} 0)))"
        )
    )
    layer.CreateFeature(feature)
    ds = None


def _write_raster(path, value):
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds = gdal.GetDriverByName("GTiff").Create(path, WIDTH, HEIGHT, 1, gdal.GDT_Int16)
    ds.SetGeoTransform((0, 1, 0, HEIGHT, 0, -1))
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-32768)
    band.WriteArray(np.full((HEIGHT, WIDTH), value, dtype=np.int16))
    ds.FlushCache()
    ds = None


def _read(path):
    ds = gdal.Open(path)
    array = ds.GetRasterBand(1).ReadAsArray()
    ds = None
    return array


class SubnationalSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QgsApplication.instance() is None:
            cls.app = QgsApplication([], False)
            cls.app.initQgis()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for unit, (x0, x1) in zip(UNITS, [(0, 10), (10, 20)]):
            unit["stored_geometry_path"] = os.path.join(
                self.tmp.name, unit["id"] + ".gpkg"
            )
            _write_unit_polygon(unit["stored_geometry_path"], x0, x1)

        # run A: left=1 right=2, run B: left=10 right=20
        self.run_a = self._band({"left": 1, "right": 2}, "a")
        self.run_b = self._band({"left": 10, "right": 20}, "b")

        self.dialog = SimpleNamespace(
            tr=lambda text: text,
            SUBNATIONAL_PATH_KEYS=DlgCalculateLDNSummaryTableAdmin.SUBNATIONAL_PATH_KEYS,
        )

    def _band(self, values, name, complete=True):
        # te_schemas is only importable once LDMP has added ext-libs to the path
        from te_schemas.results import RasterResults

        job = SimpleNamespace(
            get_first_result_by_type=lambda kind: (
                SimpleNamespace(get_bands=lambda: [SimpleNamespace(name="band")])
                if kind is RasterResults
                else None
            )
        )
        unit_bands = {}
        for unit_id, value in values.items():
            path = os.path.join(self.tmp.name, f"{name}_{unit_id}.tif")
            _write_raster(path, value)
            unit_bands[unit_id] = SimpleNamespace(path=path, job=job)
        return SubnationalBand(
            job=job,
            path=next(iter(unit_bands.values())).path,
            band_index=1,
            band_info=SimpleNamespace(name="band"),
            unit_bands=unit_bands,
            period_name="baseline",
            n_units=len(UNITS),
            missing_units=[] if complete else ["Right"],
        )

    def _periods(self):
        return [
            {
                "name": "baseline",
                "params": {
                    "layer_lc_path": "orig.tif",
                    "layer_lc_trans_path": "orig.tif",
                    "layer_soc_path": "orig.tif",
                    "layer_traj_path": "orig.tif",
                    "layer_perf_path": "orig.tif",
                    "layer_state_path": "orig.tif",
                    "layer_population_paths": ["orig.tif", "orig.tif"],
                },
            }
        ]

    def _selection(self, **overrides):
        selection = {
            "layer_lc_path": [self.run_a],
            "layer_lc_trans_path": [self.run_a],
            "layer_soc_path": [self.run_a],
            "layer_traj_path": [self.run_a],
            "layer_perf_path": [self.run_b],
            "layer_state_path": [self.run_a],
            "layer_population_paths": [self.run_a, self.run_b],
        }
        selection.update(overrides)
        return {"baseline": selection}

    def _build(self, selections):
        return DlgCalculateLDNSummaryTableAdmin._build_subnational_summary(
            self.dialog, self._periods(), UNITS, selections
        )

    def test_each_layer_reads_the_run_selected_for_it(self):
        _, periods, error = self._build(self._selection())

        self.assertIsNone(error)
        params = periods[0]["params"]
        trend = _read(params["layer_traj_path"])
        performance = _read(params["layer_perf_path"])

        # Run A: left 1, right 2. Run B: left 10, right 20.
        self.assertEqual((trend[5, 2], trend[5, 17]), (1, 2))
        self.assertEqual((performance[5, 2], performance[5, 17]), (10, 20))

    def test_population_entries_follow_their_own_selection(self):
        _, periods, _ = self._build(self._selection())

        male, female = periods[0]["params"]["layer_population_paths"]

        self.assertEqual(_read(male)[5, 2], 1)
        self.assertEqual(_read(female)[5, 2], 10)

    def test_land_cover_transition_layer_follows_land_cover(self):
        selection = self._selection(
            layer_lc_path=[self.run_b], layer_lc_trans_path=[self.run_b]
        )

        _, periods, _ = self._build(selection)

        params = periods[0]["params"]
        self.assertEqual(_read(params["layer_lc_trans_path"])[5, 2], 10)
        self.assertEqual(params["layer_lc_path"], params["layer_lc_trans_path"])

    def test_layers_that_chose_the_same_run_share_one_mosaic(self):
        _, periods, _ = self._build(self._selection())

        params = periods[0]["params"]

        self.assertEqual(params["layer_traj_path"], params["layer_soc_path"])
        self.assertNotEqual(params["layer_traj_path"], params["layer_perf_path"])
        self.assertEqual(params["layer_population_paths"][0], params["layer_traj_path"])
        self.assertEqual(params["layer_population_paths"][1], params["layer_perf_path"])

    def test_incomplete_run_is_refused(self):
        incomplete = self._band({"left": 5}, "c", complete=False)

        _, periods, error = self._build(self._selection(layer_traj_path=[incomplete]))

        self.assertIsNone(periods)
        self.assertIn("incomplete", error)
        self.assertIn("Right", error)

    def test_result_of_a_single_unit_is_refused(self):
        single_unit = SimpleNamespace(path="x.tif", band_index=1)

        _, periods, error = self._build(self._selection(layer_traj_path=[single_unit]))

        self.assertIsNone(periods)
        self.assertIn("single unit", error)

    def test_missing_selection_is_an_error(self):
        selection = self._selection()
        del selection["baseline"]["layer_state_path"]

        _, periods, error = self._build(selection)

        self.assertIsNone(periods)
        self.assertIn("layer_state_path", error)

    def test_keys_not_in_the_period_params_are_not_required(self):
        # e.g. a productivity layer the chosen productivity mode does not use
        periods = self._periods()
        del periods[0]["params"]["layer_state_path"]
        selections = self._selection()
        del selections["baseline"]["layer_state_path"]

        _, patched, error = DlgCalculateLDNSummaryTableAdmin._build_subnational_summary(
            self.dialog, periods, UNITS, selections
        )

        self.assertIsNone(error)
        self.assertNotIn("layer_state_path", patched[0]["params"])


class PlanSubnationalMosaicsTests(unittest.TestCase):
    def _band(self, paths):
        return SimpleNamespace(
            unit_bands={
                unit_id: SimpleNamespace(path=path) for unit_id, path in paths.items()
            }
        )

    def test_same_run_gives_same_key_and_other_run_gives_another(self):
        run_a = self._band({"left": "a_left.tif", "right": "a_right.tif"})
        run_b = self._band({"left": "b_left.tif", "right": "b_right.tif"})

        plan = plan_subnational_mosaics(
            {"trend": [run_a], "perf": [run_b], "soc": [run_a]}, UNITS
        )

        self.assertEqual(plan["trend"], plan["soc"])
        self.assertNotEqual(plan["trend"], plan["perf"])
        self.assertEqual(len({key for keys in plan.values() for key in keys}), 2)

    def test_key_follows_the_unit_order(self):
        band = self._band({"right": "r.tif", "left": "l.tif"})

        self.assertEqual(
            subnational_mosaic_key(band, UNITS),
            (("left", "l.tif"), ("right", "r.tif")),
        )


if __name__ == "__main__":
    unittest.main()
