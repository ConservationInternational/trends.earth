import unittest
from unittest import mock

from qgis.core import QgsGeometry

from LDMP import areaofinterest


def _square(x0, y0, x1, y1):
    return QgsGeometry.fromWkt(
        f"POLYGON(({x0} {y0},{x1} {y0},{x1} {y1},{x0} {y1},{x0} {y0}))"
    )


class PercentInsideRegionTests(unittest.TestCase):
    def setUp(self):
        self.key = ("region-1",)
        self.region = _square(0, 0, 10, 10)
        for patcher in (
            mock.patch.object(
                areaofinterest, "try_get_aoi_geometry", lambda: self.region
            ),
            mock.patch.object(
                areaofinterest, "_current_aoi_settings_key", lambda: self.key
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_unit_fully_inside_is_100(self):
        pct = areaofinterest.percent_inside_region(_square(1, 1, 3, 3))

        self.assertAlmostEqual(pct, 100.0, places=3)

    def test_unit_half_inside(self):
        pct = areaofinterest.percent_inside_region(_square(8, 1, 12, 3))

        self.assertAlmostEqual(pct, 50.0, delta=0.5)

    def test_unit_fully_outside_is_0(self):
        pct = areaofinterest.percent_inside_region(_square(20, 20, 22, 22))

        self.assertEqual(pct, 0.0)

    def test_multipart_unit_counts_each_part(self):
        unit = QgsGeometry.fromWkt(
            "MULTIPOLYGON(((1 1,2 1,2 2,1 2,1 1)),((3 1,4 1,4 2,3 2,3 1)),"
            "((5 1,6 1,6 2,5 2,5 1)),((20 1,21 1,21 2,20 2,20 1)))"
        )

        self.assertAlmostEqual(areaofinterest.percent_inside_region(unit), 75.0, 1)

    def test_uses_region_shape_not_its_bounding_box(self):
        # L-shaped region: the unit sits in the notch, inside the bounding box
        # of the region but outside the region itself
        self.region = QgsGeometry.fromWkt("POLYGON((0 0,10 0,10 4,4 4,4 10,0 10,0 0))")
        self.key = ("l-shape",)

        pct = areaofinterest.percent_inside_region(_square(6, 6, 8, 8))

        self.assertEqual(pct, 0.0)

    def test_region_change_is_picked_up(self):
        unit = _square(1, 1, 3, 3)
        self.assertAlmostEqual(areaofinterest.percent_inside_region(unit), 100.0, 3)

        self.region = _square(100, 100, 110, 110)
        self.key = ("region-2",)

        self.assertEqual(areaofinterest.percent_inside_region(unit), 0.0)

    def test_signature_follows_region_settings(self):
        first = areaofinterest.region_signature()
        self.key = ("region-2",)

        self.assertNotEqual(first, areaofinterest.region_signature())

    def test_none_without_region_or_unit_area(self):
        self.region = None
        self.key = ("no-region",)

        self.assertIsNone(areaofinterest.percent_inside_region(_square(1, 1, 3, 3)))
        self.assertIsNone(areaofinterest.percent_inside_region(QgsGeometry()))

    def test_invalid_unit_geometry_is_repaired(self):
        bowtie = QgsGeometry.fromWkt("POLYGON((1 1,3 3,3 1,1 3,1 1))")

        pct = areaofinterest.percent_inside_region(bowtie)

        self.assertAlmostEqual(pct, 100.0, places=3)


if __name__ == "__main__":
    unittest.main()
