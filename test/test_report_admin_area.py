"""Regression tests for the administrative mask used by report maps."""

import unittest
from unittest.mock import patch

from qgis.core import (
    QgsApplication,
    QgsFeature,
    QgsGeometry,
    QgsRectangle,
    QgsVectorLayer,
)
from qgis.testing import start_app

if QgsApplication.instance() is None:
    QGIS_APP = start_app()

from LDMP import conf
from LDMP.visualization import ExtractAdministrativeArea


def polygon_layer(fields, features):
    layer = QgsVectorLayer(
        "Polygon?crs=EPSG:4326" + "".join(f"&field={field}:string" for field in fields),
        "boundaries",
        "memory",
    )
    for attributes, rectangle in features:
        feature = QgsFeature(layer.fields())
        feature.setAttributes(attributes)
        feature.setGeometry(QgsGeometry.fromRect(QgsRectangle(*rectangle)))
        layer.dataProvider().addFeatures([feature])
    layer.updateExtents()
    return layer


class TestReportAdministrativeArea(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from processing.core.Processing import Processing

        Processing.initialize()

    def extract(self, extent, countries, regions):
        national = polygon_layer(["ISO_A3"], countries)
        subnational = polygon_layer(["adm0_a3", "adm1_code"], regions)
        extent_layer = polygon_layer([], [([], extent)])
        with patch.object(ExtractAdministrativeArea, "_create_layers"):
            extractor = ExtractAdministrativeArea(QgsRectangle(*extent))
        extractor._national_layer = national
        extractor._sub_nat_layer = subnational
        extractor._extent_layer = extent_layer
        names = {"GRC": "Greece", "ALB": "Albania", "TUR": "Turkey"}
        with (
            patch("LDMP.visualization.country_name_from_code", side_effect=names.get),
            patch("LDMP.visualization.admin_one_name_from_code", return_value="Attica"),
        ):
            return extractor.get_admin_area()

    def test_enclosed_neighbour_does_not_override_dominant_country(self):
        # A raster extent can enclose Albania while differing slightly from
        # Greece's national bounds due to pixel alignment/boundary datasets.
        countries = [
            (["ALB"], (1, 7, 3, 9)),
            (["GRC"], (3, -0.01, 9, 10.01)),
            (["TUR"], (9, 0, 100, 10)),
        ]
        regions = [
            (["ALB", "ALB-1"], (1, 7, 3, 9)),
            (["GRC", "GRC-1"], (3, 0, 9, 5)),
            (["GRC", "GRC-2"], (3, 5, 9, 10)),
        ]
        self.assertEqual(
            self.extract((0, 0, 10, 10), countries, regions),
            ("Greece", conf.TR_ALL_REGIONS),
        )

    def test_overlap_not_total_country_area_determines_mask(self):
        self.assertEqual(
            self.extract(
                (0, 0, 10, 10),
                [
                    (["ALB"], (0, 0, 1, 1)),
                    (["GRC"], (1, -1, 9, 11)),
                    (["TUR"], (9, 0, 100, 10)),
                ],
                [],
            ),
            ("Greece", conf.TR_ALL_REGIONS),
        )

    def test_clipped_albania_does_not_win_subregion_fallback(self):
        countries = [
            (["ALB"], (1, 7, 3, 11)),
            (["GRC"], (3, -0.01, 9, 10.01)),
        ]
        for greek_regions in (
            [
                (["GRC", "GRC-1"], (3, 0, 9, 5)),
                (["GRC", "GRC-2"], (3, 5, 9, 10)),
            ],
            [
                (["GRC", "GRC-1"], (3, -0.01, 9, 5)),
                (["GRC", "GRC-2"], (3, 5, 9, 10.01)),
            ],
        ):
            with self.subTest(greek_regions=greek_regions):
                self.assertEqual(
                    self.extract(
                        (0, 0, 10, 10),
                        countries,
                        [
                            (["ALB", "ALB-1"], (1, 7, 3, 8)),
                            (["ALB", "ALB-2"], (1, 8, 3, 9)),
                            (["ALB", "ALB-3"], (1, 9, 3, 11)),
                            *greek_regions,
                        ],
                    ),
                    ("Greece", conf.TR_ALL_REGIONS),
                )

    def test_single_subregion_mask_is_preserved(self):
        self.assertEqual(
            self.extract(
                (2, 2, 4, 4),
                [(["GRC"], (0, 0, 10, 10))],
                [(["GRC", "GRC-1"], (2, 2, 4, 4))],
            ),
            ("Greece", "Attica"),
        )

    def test_subregion_lookup_ignores_enclosed_neighbour(self):
        self.assertEqual(
            self.extract(
                (0, 0, 10, 10),
                [
                    (["ALB"], (0, 0, 1, 1)),
                    (["GRC"], (1, -1, 9, 11)),
                ],
                [
                    (["ALB", "ALB-1"], (0, 0, 1, 1)),
                    (["GRC", "GRC-1"], (1, -1, 9, 5)),
                    (["GRC", "GRC-2"], (1, 5, 9, 11)),
                ],
            ),
            ("Greece", conf.TR_ALL_REGIONS),
        )

    def test_extent_without_land_has_no_mask(self):
        self.assertEqual(
            self.extract(
                (20, 20, 30, 30),
                [(["GRC"], (0, 0, 10, 10))],
                [(["GRC", "GRC-1"], (2, 2, 4, 4))],
            ),
            ("", ""),
        )
