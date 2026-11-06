import unittest
from pathlib import Path
from unittest import mock

from osgeo import gdal
from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer
from utilities_for_testing import get_qgis_app

from LDMP.reports.ecosystem_restoration import spatial_validation
from LDMP.reports.ecosystem_restoration.spatial_validation import (
    MAX_SITE_ERRORS,
    LayerValidation,
)

QGIS_APP = get_qgis_app()

DATA_DIR = Path(__file__).parent / "data" / "ecosystem_restoration"
LAYER_NAME = "IND_V20261231"
LAYER_EXTENSIONS = (".geojson", ".kml", ".shp", ".gpkg")

INDICATOR_1 = "1. Under improved management"
INDICATOR_3 = "3. Under restoration"


def open_layer(case: str, extension: str | None = None) -> QgsVectorLayer:
    """Layer of the case folder, named after its file, e.g. IND_V20261231."""
    paths = [
        path
        for path in sorted((DATA_DIR / case).iterdir())
        if path.suffix in LAYER_EXTENSIONS
        and (extension is None or path.suffix == extension)
    ]
    assert len(paths) == 1, f"No layer file, or more than one, in {case}"
    layer = QgsVectorLayer(str(paths[0]), paths[0].stem, "ogr")
    assert layer.isValid(), f"{paths[0]} cannot be opened"
    return layer


def validate(case: str, extension: str | None = None) -> list[str]:
    """Errors of LayerValidation of the layer of the case folder."""
    return LayerValidation(open_layer(case, extension)).run()


class TestValidLayers(unittest.TestCase):
    """A layer of valid sites."""

    def test_valid(self):
        self.assertEqual(validate("valid"), [])


class TestFileValidation(unittest.TestCase):
    """The layer is a GeoJSON, KML or Shapefile file in EPSG:4326."""

    def test_not_a_file(self):
        layer = QgsVectorLayer("Polygon?crs=EPSG:4326", LAYER_NAME, "memory")
        self.assertIn(
            f"Layer {LAYER_NAME} is not a file.", LayerValidation(layer).run()
        )

    def test_error_crs(self):
        self.assertEqual(
            validate("error_crs"),
            [f"Layer {LAYER_NAME} is not in EPSG:4326: EPSG:3857"],
        )


class TestFieldsValidation(unittest.TestCase):
    """The layer has all the fields of the restoration sites, the optional
    fields too."""

    def test_missing_fields(self):
        self.assertEqual(
            validate("error_missing_fields"),
            [
                f"Layer {LAYER_NAME} has no field: Sub_Indic, Area_Type, Activity, Source"
            ],
        )


class TestAttributesValidation(unittest.TestCase):
    """Every site has valid attributes."""

    def test_error_attributes(self):
        with mock.patch.object(spatial_validation, "MAX_SITE_ERRORS", 100):
            errors = validate("error_attributes")
        self.assertEqual(
            errors,
            [
                "Site IND_0001: no value for GEF_CP_ID.",
                "Site IND_0002: no value for Country.",
                "Feature 2: no value for Site_ID.",
                "Site IND_0004: no value for Date.",
                "Site IND_0005: no value for Indicator.",
                "Site IND_0006: no value for Sub_Indic.",
                "Site IND_0007: no value for Indicator.",
                "Site IND_0008: no value for GEF_CP_ID, Date.",
                "Site IND_0009: Date is not a date.",
                "Site IND_0010: GEF_CP_ID 1113 is not five numbers.",
                "Site IND_0011: GEF_CP_ID 111300 is not five numbers.",
                "Site IND_0012: GEF_CP_ID 11a30 is not five numbers.",
                "Site IND_0013: GEF_CP_ID GEF01 is not five numbers.",
                "Site ZAF_0014: Country ZAF is not IND, the country of layer "
                f"{LAYER_NAME}.",
                "Site ZAF_0015: Site_ID does not start with Country IND.",
                "Site IND_0016: Site_ID is not unique.",
            ]
            # Site_IDs that are not [ISO3 Code]_[SiteNumber]
            + [
                f"Site {site_id}: Site_ID is not [ISO3 Code]_[SiteNumber], "
                "e.g. HTI_0023."
                for site_id in (
                    "SITE_001",
                    "IND_001",
                    "IND_00001",
                    "ind_0001",
                    "IND0001",
                )
            ]
            # A site with several errors
            + [
                "Site IND_0023: Date is not a date.",
                "Site IND_0023: GEF_CP_ID 1113 is not five numbers.",
                "Site IND_0023: Country ZAF is not IND, the country of layer "
                f"{LAYER_NAME}.",
                "Site IND_0023: Site_ID does not start with Country ZAF.",
            ],
        )

    def test_most_errors(self):
        errors = validate("error_attributes")
        self.assertEqual(len(errors), MAX_SITE_ERRORS + 1)
        self.assertEqual(
            errors[:2],
            [
                "Site IND_0001: no value for GEF_CP_ID.",
                "Site IND_0002: no value for Country.",
            ],
        )
        self.assertEqual(errors[-1], "...")


class TestClosedPolygonValidation(unittest.TestCase):
    """The boundary of every site is closed polygons."""

    def test_error_boundary(self):
        self.assertEqual(
            validate("error_boundary", ".geojson"),
            [
                "Site IND_0003: no boundary, or the boundary is not closed.",
                "Site IND_0004: boundary is not valid: Self-intersection",
                # Spike, a dangling vertex going out of the polygon and back
                "Site IND_0005: boundary is not valid: Ring self-intersection",
                "Site IND_0006: boundary is not valid: Hole lies outside shell",
                "Site IND_0007: boundary is a Line, not a closed polygon.",
                "Site IND_0008: boundary is a Point, not a closed polygon.",
            ],
        )

    def test_unclosed_ring_option_is_restored(self):
        option = "OGR_GEOMETRY_ACCEPT_UNCLOSED_RING"
        before = gdal.GetThreadLocalConfigOption(option, None)
        validate("error_boundary", ".geojson")
        self.assertEqual(gdal.GetThreadLocalConfigOption(option, None), before)

    def test_memory_layer_geometries(self):
        layer = QgsVectorLayer("Polygon?crs=EPSG:4326", LAYER_NAME, "memory")
        for wkt in (
            "POLYGON((0 0,1 0,1 1,0 1,0 0))",
            "POLYGON((0 0,1 0,1 1,0 1))",
            "POLYGON((0 0,1 0,0 0))",
            "POLYGON((0 0,1 1,1 0,0 1,0 0))",
            "POLYGON EMPTY",
            None,
        ):
            feature = QgsFeature()
            feature.setGeometry(QgsGeometry.fromWkt(wkt) if wkt else QgsGeometry())
            layer.dataProvider().addFeature(feature)
        self.assertEqual(
            LayerValidation(layer)._validate_closed_polygon(),
            {
                2: ["boundary is not closed."],
                3: ["boundary is not closed."],
                4: ["boundary is not valid: Self-intersection"],
                5: ["no boundary, or the boundary is not closed."],
                6: ["no boundary, or the boundary is not closed."],
            },
        )


class TestOverlappingValidation(unittest.TestCase):
    """Test overlapping sites."""

    def overlap(self, site: str, other_site: str, indicator: str = INDICATOR_3) -> str:
        return (
            f"Site {site}: boundary overlaps Site {other_site} of the same "
            f"Indicator {indicator}."
        )

    def test_overlap(self):
        self.assertEqual(
            validate("error_overlapping"),
            [
                self.overlap("IND_0002", "IND_0001"),
                self.overlap("IND_0004", "IND_0003", INDICATOR_1),
                self.overlap("IND_0008", "IND_0007"),
                self.overlap("IND_0010", "IND_0009"),
                self.overlap("IND_0016", "IND_0014"),
                self.overlap("IND_0016", "IND_0015"),
                "Site IND_0018: boundary is not valid: Self-intersection",
            ],
        )


if __name__ == "__main__":
    unittest.main()
