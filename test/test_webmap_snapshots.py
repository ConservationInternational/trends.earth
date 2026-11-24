"""Raster snapshot checks using real GDAL datasets."""

import hashlib
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from osgeo import gdal, ogr, osr

from LDMP.webmap_sharing import ShareCancelled, ShareError
from LDMP.webmap_snapshots import export_raster, export_vector


class TestWebmapRasterSnapshots(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.raster = self.root / "source.tif"
        ds = gdal.GetDriverByName("GTiff").Create(
            str(self.raster), 4, 4, 2, gdal.GDT_Int16
        )
        spatial_reference = osr.SpatialReference()
        spatial_reference.ImportFromEPSG(4326)
        ds.SetProjection(spatial_reference.ExportToWkt())
        ds.SetGeoTransform((10, 0.1, 0, 20, 0, -0.1))
        ds.GetRasterBand(1).Fill(3)
        ds.GetRasterBand(2).Fill(7)
        ds.GetRasterBand(1).SetNoDataValue(-9999)
        ds.GetRasterBand(2).SetNoDataValue(-9999)
        ds = None

    def test_vrt_is_materialized_with_selected_band_and_nodata(self):
        vrt = self.root / "input.vrt"
        gdal.Translate(str(vrt), str(self.raster), format="VRT")
        output = self.root / "snapshot.tif"
        result = export_raster(str(vrt), output, 2)
        self.raster.unlink()
        data = gdal.Open(str(output))
        self.assertEqual(data.RasterCount, 1)
        pixel = data.GetRasterBand(1).ReadRaster(0, 0, 1, 1, buf_type=gdal.GDT_Int16)
        self.assertEqual(struct.unpack("h", pixel)[0], 7)
        self.assertEqual(data.GetRasterBand(1).GetNoDataValue(), -9999)
        self.assertTrue(data.GetProjection())
        self.assertEqual(data.GetMetadata("IMAGE_STRUCTURE").get("LAYOUT"), "COG")
        self.assertEqual(result["size_bytes"], output.stat().st_size)
        self.assertEqual(
            result["sha256"], hashlib.sha256(output.read_bytes()).hexdigest()
        )

    def test_missing_vrt_dependency_fails(self):
        vrt = self.root / "input.vrt"
        gdal.Translate(str(vrt), str(self.raster), format="VRT")
        self.raster.unlink()
        with self.assertRaises(ShareError):
            export_raster(str(vrt), self.root / "snapshot.tif", 1)

    def test_cancel_before_conversion(self):
        with self.assertRaises(ShareCancelled):
            export_raster(str(self.raster), self.root / "snapshot.tif", 1, lambda: True)

    def test_refuses_remote_vrt_source_before_opening(self):
        vrt = self.root / "remote.vrt"
        vrt.write_text(
            '<VRTDataset rasterXSize="4" rasterYSize="4">'
            '<VRTRasterBand dataType="Byte" band="1"><SimpleSource>'
            "<SourceFilename>/vsicurl/https://example.test/secret</SourceFilename>"
            "</SimpleSource></VRTRasterBand></VRTDataset>"
        )
        with self.assertRaisesRegex(ShareError, "local files"):
            export_raster(str(vrt), self.root / "snapshot.tif", 1)

    def test_refuses_to_overwrite_source(self):
        with self.assertRaisesRegex(ShareError, "overwrite"):
            export_raster(str(self.raster), self.raster, 1)

    def test_refuses_to_overwrite_an_existing_snapshot(self):
        output = self.root / "snapshot.tif"
        output.write_bytes(b"existing")
        with self.assertRaisesRegex(ShareError, "already exists"):
            export_raster(str(self.raster), output, 1)
        self.assertEqual(output.read_bytes(), b"existing")

    def test_cancellation_removes_incomplete_snapshot(self):
        output = self.root / "snapshot.tif"
        checks = iter([False, False, True])

        def fake_translate(path, *_args, **_kwargs):
            Path(path).write_bytes(b"partial")
            return Mock()

        with (
            patch.object(gdal, "Translate", side_effect=fake_translate),
            self.assertRaises(ShareCancelled),
        ):
            export_raster(str(self.raster), output, 1, lambda: next(checks))
        self.assertFalse(output.exists())


class TestWebmapVectorSnapshots(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "source.gpkg"
        dataset = ogr.GetDriverByName("GPKG").CreateDataSource(str(self.source))
        crs = osr.SpatialReference()
        crs.ImportFromEPSG(4326)
        layer = dataset.CreateLayer("original", crs, ogr.wkbPoint)
        layer.CreateField(ogr.FieldDefn("public", ogr.OFTString))
        layer.CreateField(ogr.FieldDefn("private", ogr.OFTString))
        for index in range(2):
            feature = ogr.Feature(layer.GetLayerDefn())
            feature.SetField("public", f"class{index}")
            feature.SetField("private", "do-not-share")
            geometry = ogr.Geometry(ogr.wkbPoint)
            geometry.AddPoint_2D(10 + index, 10)
            feature.SetGeometry(geometry)
            layer.CreateFeature(feature)
        dataset = None

    def test_pmtiles_contains_only_selected_fields_and_features(self):
        output = self.root / "output.pmtiles"
        result = export_vector(str(self.source), "original", output, ["public"], 1, 2)
        self.assertEqual(result["size_bytes"], output.stat().st_size)
        data = gdal.OpenEx(str(output), gdal.OF_VECTOR)
        layer = data.GetLayerByName("analysis")
        self.assertIsNotNone(layer)
        fields = [field.GetName() for field in layer.schema]
        self.assertIn("public", fields)
        self.assertNotIn("private", fields)
        self.assertEqual(
            {feature.GetField("public") for feature in layer}, {"class0", "class1"}
        )

    def test_rejects_unsafe_field_names(self):
        with self.assertRaises(ShareError):
            export_vector(
                str(self.source),
                "original",
                self.root / "out.pmtiles",
                ["private name"],
                1,
                2,
            )

    def test_tiny_polygon_dropped_by_tiling_is_reported(self):
        source = self.root / "tiny.gpkg"
        data = ogr.GetDriverByName("GPKG").CreateDataSource(str(source))
        crs = osr.SpatialReference()
        crs.ImportFromEPSG(4326)
        layer = data.CreateLayer("tiny", crs, ogr.wkbPolygon)
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetGeometry(
            ogr.CreateGeometryFromWkt(
                "POLYGON ((10 10, 10.000001 10, 10.000001 10.000001, "
                "10 10.000001, 10 10))"
            )
        )
        layer.CreateFeature(feature)
        data = None
        output = self.root / "tiny.pmtiles"
        with self.assertRaises(ShareError):
            export_vector(str(source), "tiny", output, [], 0, 0)
        self.assertFalse(output.exists())

    def test_line_and_polygon_features_survive_all_zooms(self):
        examples = (
            ("line", ogr.wkbLineString, "LINESTRING (-20 10, 20 20)"),
            (
                "polygon",
                ogr.wkbPolygon,
                "POLYGON ((-20 10, 20 10, 20 30, -20 30, -20 10))",
            ),
        )
        for name, geometry_type, wkt in examples:
            with self.subTest(name=name):
                source = self.root / f"{name}.gpkg"
                data = ogr.GetDriverByName("GPKG").CreateDataSource(str(source))
                crs = osr.SpatialReference()
                crs.ImportFromEPSG(4326)
                layer = data.CreateLayer(name, crs, geometry_type)
                layer.CreateField(ogr.FieldDefn("category", ogr.OFTString))
                feature = ogr.Feature(layer.GetLayerDefn())
                feature.SetField("category", "class-a")
                feature.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
                layer.CreateFeature(feature)
                data = None
                output = self.root / f"{name}.pmtiles"
                export_vector(str(source), name, output, ["category"], 1, 2)
                self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
