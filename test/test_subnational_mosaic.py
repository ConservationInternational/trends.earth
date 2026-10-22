import os
import tempfile
import unittest

import numpy as np
from osgeo import gdal, osr
from qgis.core import QgsGeometry

from LDMP.calculate_ldn import build_subnational_mosaic, write_cutline_geojson

NODATA = -32768


def _box(x_min, x_max, y_min=0, y_max=10):
    return QgsGeometry.fromWkt(
        f"POLYGON(({x_min} {y_min}, {x_max} {y_min}, {x_max} {y_max}, "
        f"{x_min} {y_max}, {x_min} {y_min}))"
    )


class SubnationalMosaicTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _raster(self, name, x_min, x_max, value, n_bands=1):
        """Constant-valued raster on a 1-degree grid covering x_min..x_max."""
        path = os.path.join(self.tmp_dir.name, f"{name}.tif")
        width = x_max - x_min
        ds = gdal.GetDriverByName("GTiff").Create(
            path, width, 10, n_bands, gdal.GDT_Int16
        )
        ds.SetGeoTransform((x_min, 1, 0, 10, 0, -1))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        ds.SetProjection(srs.ExportToWkt())
        for n in range(1, n_bands + 1):
            band = ds.GetRasterBand(n)
            band.SetNoDataValue(NODATA)
            band.WriteArray(np.full((10, width), value * n, dtype=np.int16))
        ds = None
        return path

    def _mosaic(self, unit_rasters):
        vrt_path = os.path.join(self.tmp_dir.name, "mosaic.vrt")
        self.assertIsNone(build_subnational_mosaic(vrt_path, unit_rasters))
        ds = gdal.Open(vrt_path)
        self.assertEqual(ds.GetGeoTransform(), (0, 1, 0, 10, 0, -1))
        return ds

    def test_each_pixel_comes_from_its_own_unit(self):
        # Unit rasters cover their bounding boxes, which overlap in x=4..10,
        # while the unit polygons meet at x=6. B is listed last, so without
        # masking it would win the whole overlap.
        unit_rasters = [
            ("A", self._raster("a", 0, 10, 1), write_cutline_geojson(_box(0, 6))),
            ("B", self._raster("b", 4, 14, 2), write_cutline_geojson(_box(6, 14))),
        ]

        ds = self._mosaic(unit_rasters)
        row = ds.GetRasterBand(1).ReadAsArray()[5]

        np.testing.assert_array_equal(row[:6], [1] * 6)
        np.testing.assert_array_equal(row[6:], [2] * 8)

    def test_pixels_outside_all_units_are_nodata(self):
        unit_rasters = [
            ("A", self._raster("a", 0, 10, 1), write_cutline_geojson(_box(0, 4))),
            ("B", self._raster("b", 4, 14, 2), write_cutline_geojson(_box(8, 14))),
        ]

        ds = self._mosaic(unit_rasters)
        row = ds.GetRasterBand(1).ReadAsArray()[5]

        np.testing.assert_array_equal(row[:4], [1] * 4)
        np.testing.assert_array_equal(row[4:8], [NODATA] * 4)
        np.testing.assert_array_equal(row[8:], [2] * 6)

    def test_all_bands_are_masked(self):
        unit_rasters = [
            (
                "A",
                self._raster("a", 0, 10, 1, n_bands=3),
                write_cutline_geojson(_box(0, 6)),
            ),
            (
                "B",
                self._raster("b", 4, 14, 10, n_bands=3),
                write_cutline_geojson(_box(6, 14)),
            ),
        ]

        ds = self._mosaic(unit_rasters)

        self.assertEqual(ds.RasterCount, 3)
        for n in range(1, 4):
            row = ds.GetRasterBand(n).ReadAsArray()[5]
            self.assertEqual(row[5], 1 * n)
            self.assertEqual(row[6], 10 * n)

    def test_unreadable_raster_reports_unit(self):
        missing = os.path.join(self.tmp_dir.name, "missing.tif")
        unit_rasters = [
            ("A", self._raster("a", 0, 10, 1), write_cutline_geojson(_box(0, 6))),
            ("B", missing, write_cutline_geojson(_box(6, 14))),
        ]

        failed = build_subnational_mosaic(
            os.path.join(self.tmp_dir.name, "mosaic.vrt"), unit_rasters
        )

        self.assertEqual(failed, "B")


if __name__ == "__main__":
    unittest.main()
