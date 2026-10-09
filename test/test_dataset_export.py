"""Tests for packaging datasets with their VRT dependency chains."""

import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from osgeo import gdal

from LDMP.dataset_export import collect_dataset_files, write_dataset_archive

gdal.UseExceptions()


def _write_tif(path: Path, value: int) -> Path:
    ds = gdal.GetDriverByName("GTiff").Create(str(path), 4, 3, 1, gdal.GDT_Int16)
    ds.SetGeoTransform((0, 1, 0, 3, 0, -1))
    ds.GetRasterBand(1).WriteArray(np.full((3, 4), value, dtype=np.int16))
    ds = None
    return path


def _write_vrt(path: Path, sources) -> Path:
    ds = gdal.BuildVRT(str(path), [str(source) for source in sources], separate=True)
    ds.FlushCache()
    ds = None
    return path


def _band_values(path: Path) -> list[int]:
    ds = gdal.Open(str(path))
    try:
        return [
            int(ds.GetRasterBand(band).ReadAsArray()[0, 0])
            for band in range(1, ds.RasterCount + 1)
        ]
    finally:
        ds = None


class TestDatasetExport(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.dataset_dir = self.root / "dataset"
        self.dataset_dir.mkdir()
        self.job_json = self.dataset_dir / "job.json"
        self.job_json.write_text("{}", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _export_and_extract(self, data_paths):
        archive = self.root / "export.zip"
        summary = write_dataset_archive(archive, data_paths, [self.job_json])
        extracted = self.root / "extracted"
        with ZipFile(archive) as zip_file:
            names = zip_file.namelist()
            zip_file.extractall(extracted)
        return summary, names, extracted

    def test_exports_nested_vrt_chain(self):
        first = _write_tif(self.dataset_dir / "first.tif", 1)
        second = _write_tif(self.dataset_dir / "second.tif", 2)
        Path(f"{first}.aux.xml").write_text("<PAMDataset/>", encoding="utf-8")
        inner = _write_vrt(self.dataset_dir / "inner.vrt", [first, second])
        top = _write_vrt(self.dataset_dir / "top.vrt", [inner])

        summary, names, extracted = self._export_and_extract([top])

        self.assertEqual(
            sorted(names),
            sorted(
                [
                    "job.json",
                    "top.vrt",
                    "inner.vrt",
                    "first.tif",
                    "first.tif.aux.xml",
                    "second.tif",
                ]
            ),
        )
        self.assertEqual(summary.missing_files, [])
        self.assertEqual(summary.rewritten_vrts, [])
        self.assertEqual(_band_values(extracted / "top.vrt"), [1, 2])
        self.assertEqual(_band_values(extracted / "inner.vrt"), [1, 2])

    def test_exports_external_absolute_dependencies(self):
        external_dir = self.root / "system-temp"
        external_dir.mkdir()
        source = _write_tif(external_dir / "source.tif", 7)
        external_vrt = _write_vrt(external_dir / "tmpselection.vrt", [source])
        top = _write_vrt(self.dataset_dir / "top.vrt", [external_vrt])
        self.assertIn(str(external_dir), top.read_text(encoding="utf-8"))

        summary, names, extracted = self._export_and_extract([top])

        self.assertIn("tmpselection.vrt", names)
        self.assertIn("source.tif", names)
        self.assertEqual(summary.missing_files, [])
        self.assertEqual(summary.rewritten_vrts, [top.resolve()])
        self.assertNotIn(str(external_dir), (extracted / "top.vrt").read_text())
        self.assertEqual(_band_values(extracted / "top.vrt"), [7])

    def test_renames_colliding_dependency_names(self):
        first_dir = self.dataset_dir / "a"
        second_dir = self.dataset_dir / "b"
        first_dir.mkdir()
        second_dir.mkdir()
        first = _write_tif(first_dir / "band.tif", 3)
        second = _write_tif(second_dir / "band.tif", 4)
        top = _write_vrt(self.dataset_dir / "top.vrt", [first, second])

        summary, names, extracted = self._export_and_extract([top])

        self.assertIn("band.tif", names)
        self.assertIn("band_1.tif", names)
        self.assertEqual(summary.rewritten_vrts, [top.resolve()])
        self.assertEqual(_band_values(extracted / "top.vrt"), [3, 4])

    def test_reports_missing_dependencies(self):
        source = _write_tif(self.dataset_dir / "source.tif", 5)
        top = _write_vrt(self.dataset_dir / "top.vrt", [source])
        source.unlink()
        broken = self.dataset_dir / "broken.vrt"
        broken.write_text(
            top.read_text(encoding="utf-8").replace(
                'relativeToVRT="1">source.tif',
                r'relativeToVRT="1">C:\Users\me\AppData\Local\Temp\tmpgone.vrt',
            ),
            encoding="utf-8",
        )

        files, missing = collect_dataset_files([top, broken])

        self.assertEqual(files, [top.resolve(), broken.resolve()])
        self.assertEqual(len(missing), 2)
        self.assertTrue(any("tmpgone.vrt" in path for path in missing))

    def test_does_not_expand_xml_entities(self):
        secret = self.root / "secret.txt"
        secret.write_text("do-not-export", encoding="utf-8")
        top = self.dataset_dir / "top.vrt"
        top.write_text(
            '<?xml version="1.0"?>\n'
            f'<!DOCTYPE VRTDataset [<!ENTITY ext SYSTEM "{secret.as_uri()}">]>\n'
            "<VRTDataset rasterXSize='1' rasterYSize='1'>"
            "<VRTRasterBand dataType='Byte' band='1'><SimpleSource>"
            "<SourceFilename relativeToVRT='1'>&ext;</SourceFilename>"
            "<SourceBand>1</SourceBand></SimpleSource>"
            "</VRTRasterBand></VRTDataset>",
            encoding="utf-8",
        )

        files, missing = collect_dataset_files([top])

        self.assertEqual(files, [top.resolve()])
        self.assertEqual(missing, [])

    def test_rewrites_vrt_with_xml_declaration(self):
        external_dir = self.root / "elsewhere"
        external_dir.mkdir()
        source = _write_tif(external_dir / "source.tif", 9)
        generated = _write_vrt(self.root / "generated.vrt", [source])
        top = self.dataset_dir / "top.vrt"
        top.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            + generated.read_text(encoding="utf-8").replace(
                'relativeToVRT="1">elsewhere/source.tif',
                f'relativeToVRT="0">{source}',
            ),
            encoding="utf-8",
        )

        summary, names, extracted = self._export_and_extract([top])

        self.assertIn("source.tif", names)
        self.assertEqual(summary.rewritten_vrts, [top.resolve()])
        rewritten = (extracted / "top.vrt").read_text(encoding="utf-8")
        self.assertNotIn(str(external_dir), rewritten)
        self.assertEqual(_band_values(extracted / "top.vrt"), [9])

    def test_ignores_vsi_sources(self):
        top = self.dataset_dir / "top.vrt"
        top.write_text(
            "<VRTDataset rasterXSize='1' rasterYSize='1'>"
            "<VRTRasterBand dataType='Byte' band='1'><SimpleSource>"
            "<SourceFilename relativeToVRT='0'>/vsis3/bucket/data.tif"
            "</SourceFilename><SourceBand>1</SourceBand></SimpleSource>"
            "</VRTRasterBand></VRTDataset>",
            encoding="utf-8",
        )

        files, missing = collect_dataset_files([top])

        self.assertEqual(files, [top.resolve()])
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
