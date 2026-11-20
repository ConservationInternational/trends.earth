import os
import tempfile
import unittest

from osgeo import gdal, osr

from LDMP.calculate_ldn import check_subnational_rasters_consistent

BANDS = ["Land cover (degradation)", "Soil organic carbon (degradation)"]


class SubnationalRasterConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _raster(self, name, origin_x=100.0, pixel_size=0.001, epsg=4326):
        path = os.path.join(self.tmp_dir.name, f"{name}.tif")
        ds = gdal.GetDriverByName("GTiff").Create(path, 10, 10, 1, gdal.GDT_Int16)
        ds.SetGeoTransform((origin_x, pixel_size, 0, -10.0, 0, -pixel_size))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(epsg)
        ds.SetProjection(srs.ExportToWkt())
        ds = None
        return path

    def test_matching_rasters_pass(self):
        rasters = [
            ("North", self._raster("north"), BANDS),
            ("South", self._raster("south", origin_x=100.01), BANDS),
        ]

        self.assertIsNone(check_subnational_rasters_consistent(rasters))

    def test_single_raster_passes(self):
        rasters = [("North", self._raster("north"), BANDS)]

        self.assertIsNone(check_subnational_rasters_consistent(rasters))

    def test_different_pixel_size_fails(self):
        rasters = [
            ("North", self._raster("north"), BANDS),
            ("South", self._raster("south", pixel_size=0.00025), BANDS),
        ]

        message = check_subnational_rasters_consistent(rasters)

        self.assertIn("South", message)
        self.assertIn("pixel size", message)

    def test_different_crs_fails(self):
        rasters = [
            ("North", self._raster("north"), BANDS),
            ("South", self._raster("south", epsg=4674), BANDS),
        ]

        message = check_subnational_rasters_consistent(rasters)

        self.assertIn("coordinate system", message)

    def test_misaligned_grid_fails(self):
        rasters = [
            ("North", self._raster("north"), BANDS),
            ("South", self._raster("south", origin_x=100.0005), BANDS),
        ]

        message = check_subnational_rasters_consistent(rasters)

        self.assertIn("pixel grid", message)

    def test_different_bands_fail(self):
        rasters = [
            ("North", self._raster("north"), BANDS),
            ("South", self._raster("south"), BANDS[:1]),
        ]

        message = check_subnational_rasters_consistent(rasters)

        self.assertIn("different bands", message)

    def test_reports_every_mismatched_unit(self):
        rasters = [
            ("North", self._raster("north"), BANDS),
            ("South", self._raster("south", pixel_size=0.00025), BANDS),
            ("East", self._raster("east"), BANDS[:1]),
        ]

        message = check_subnational_rasters_consistent(rasters)

        self.assertIn("South", message)
        self.assertIn("East", message)


if __name__ == "__main__":
    unittest.main()
