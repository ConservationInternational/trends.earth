"""Tests for region-based web-map masks."""

import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from qgis.core import QgsApplication, QgsGeometry, QgsPointXY
from qgis.PyQt import QtCore, QtWidgets

from LDMP import conf
from LDMP.webmap_dialog import WebmapSharesDialog, _OwnerTask
from LDMP.webmap_mask import MaskSelector
from LDMP.webmap_sharing import ShareError


class TestWebmapMask(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], False)

    @patch("LDMP.webmap_mask.areaofinterest.prepare_area_of_interest")
    @patch("LDMP.webmap_mask.conf.settings_manager")
    def test_selected_region_becomes_a_polygon_snapshot(self, settings, prepare):
        settings.get_value.side_effect = lambda key: (
            conf.AreaSetting.COUNTRY_REGION.value
            if key == conf.Setting.AREA_FROM_OPTION
            else "Region"
        )
        aoi = Mock(datatype="polygon")
        aoi.get_unary_geometry.return_value = QgsGeometry.fromWkt(
            "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"
        )
        prepare.return_value = aoi
        selector = MaskSelector()
        self.addCleanup(selector.deleteLater)
        self.assertIsNone(selector.geometry())
        selector.setChecked(True)
        self.assertEqual(selector.geometry()["type"], "Polygon")
        prepare.assert_called_once_with(show_errors=False)

    @patch("LDMP.webmap_mask.conf.settings_manager")
    def test_point_setting_is_rejected(self, settings):
        settings.get_value.side_effect = lambda key: (
            conf.AreaSetting.POINT.value if key == conf.Setting.AREA_FROM_OPTION else ""
        )
        selector = MaskSelector()
        self.addCleanup(selector.deleteLater)
        selector.setChecked(True)
        with self.assertRaises(ShareError):
            selector.geometry()

    def test_admin_and_custom_region_settings_use_actual_geometry(self):
        geometry = {
            "type": "Polygon",
            "coordinates": [[[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]],
        }
        feature = {"type": "Feature", "properties": {}, "geometry": geometry}
        collection = {"type": "FeatureCollection", "features": [feature]}
        country = SimpleNamespace(code="KEN", level1_regions={"Region": "region-1"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "region.geojson"
            path.write_text(json.dumps(collection))
            for method, region_id in (
                (conf.AreaSetting.COUNTRY_REGION.value, None),
                (conf.AreaSetting.COUNTRY_REGION.value, "region-1"),
                (conf.AreaSetting.VECTOR_LAYER.value, None),
            ):
                values = {
                    conf.Setting.AREA_FROM_OPTION: method,
                    conf.Setting.COUNTRY_ID: "KEN",
                    conf.Setting.REGION_ID: region_id,
                    conf.Setting.VECTOR_FILE_PATH: str(path),
                    conf.Setting.AREA_NAME: "Region",
                }
                with (
                    self.subTest(method=method, region_id=region_id),
                    patch("LDMP.webmap_mask.conf.settings_manager") as settings,
                    patch(
                        "LDMP.areaofinterest.download.get_admin_bounds",
                        return_value={"Kenya": country},
                    ),
                    patch(
                        "LDMP.areaofinterest.download.download_boundary_geojson",
                        return_value=collection,
                    ) as download,
                ):
                    settings.get_value.side_effect = lambda key, values=values: (
                        values.get(key)
                    )
                    selector = MaskSelector()
                    selector.setChecked(True)
                    result = selector.geometry()
                    self.assertEqual(result["type"], "Polygon")
                    self.assertEqual(
                        {tuple(point) for point in result["coordinates"][0]},
                        {(10, 10), (11, 10), (11, 11), (10, 11)},
                    )
                    if method == conf.AreaSetting.COUNTRY_REGION.value:
                        if region_id:
                            download.assert_called_once_with(
                                "KEN", admin_level=1, shape_id=region_id
                            )
                        else:
                            download.assert_called_once_with("KEN", admin_level=0)
                    else:
                        download.assert_not_called()
                    selector.deleteLater()

    @patch("LDMP.webmap_dialog.ShareClient")
    def test_owner_task_updates_mask_with_version(self, client):
        client.return_value.update_mask.return_value = {
            "mask_version": 2,
            "has_mask": False,
        }
        task = _OwnerTask(
            "https://api.test",
            "token",
            "update_mask",
            "share",
            Mock(),
            mask=None,
            mask_version=1,
        )
        self.assertTrue(task.run())
        client.return_value.update_mask.assert_called_once_with("share", None, 1)

    def test_custom_polygon_is_reprojected_to_wgs84(self):
        collection = {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [[0, 0], [111319.49, 0], [111319.49, 111325.14], [0, 0]]
                        ],
                    },
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "projected.geojson"
            path.write_text(json.dumps(collection))
            values = {
                conf.Setting.AREA_FROM_OPTION: conf.AreaSetting.VECTOR_LAYER.value,
                conf.Setting.VECTOR_FILE_PATH: str(path),
            }
            with patch("LDMP.webmap_mask.conf.settings_manager") as settings:
                settings.get_value.side_effect = lambda key: values.get(key)
                selector = MaskSelector()
                selector.setChecked(True)
                result = selector.geometry()
                coordinates = result["coordinates"][0]
                self.assertAlmostEqual(
                    max(point[0] for point in coordinates), 1, places=5
                )
                self.assertAlmostEqual(
                    max(point[1] for point in coordinates), 1, places=5
                )
                selector.deleteLater()

    def test_detailed_region_is_simplified_only_when_enabled(self):
        count = 40000
        ring = [
            [
                30 + 2 * math.cos(2 * math.pi * index / count),
                -1 + 2 * math.sin(2 * math.pi * index / count),
            ]
            for index in range(count)
        ]
        ring.append(ring[0])
        collection = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "detailed.geojson"
            path.write_text(json.dumps(collection))
            values = {
                conf.Setting.AREA_FROM_OPTION: conf.AreaSetting.VECTOR_LAYER.value,
                conf.Setting.VECTOR_FILE_PATH: str(path),
            }
            with patch("LDMP.webmap_mask.conf.settings_manager") as settings:
                settings.get_value.side_effect = lambda key: values.get(key)
                selector = MaskSelector()
                self.addCleanup(selector.deleteLater)
                selector.setChecked(True)
                self.assertTrue(selector.simplify.isChecked())
                result = selector.geometry()
                size = len(json.dumps(result, separators=(",", ":")).encode())
                self.assertLessEqual(size, 512 * 1024)
                self.assertLessEqual(len(result["coordinates"][0]), 30000)
                simplified = QgsGeometry.fromPolygonXY(
                    [[QgsPointXY(x, y) for x, y in result["coordinates"][0]]]
                )
                self.assertTrue(simplified.isGeosValid())
                self.assertAlmostEqual(simplified.area(), 4 * math.pi, places=2)

                selector.simplify.setChecked(False)
                with self.assertRaisesRegex(ShareError, "too detailed"):
                    selector.geometry()

    def test_owner_dialog_can_remove_mask(self):
        with (
            patch.object(QtCore.QTimer, "singleShot"),
            patch("LDMP.webmap_dialog.api.APIClient"),
            patch.object(QtWidgets.QDialog, "exec", return_value=1),
            patch.object(
                QtWidgets.QMessageBox,
                "question",
                return_value=QtWidgets.QMessageBox.Yes,
            ),
            patch.object(MaskSelector, "geometry", return_value=None),
        ):
            dialog = WebmapSharesDialog()
            self.addCleanup(dialog.deleteLater)
            with (
                patch.object(
                    dialog,
                    "_selected",
                    return_value={"mask_version": 1, "has_mask": True},
                ),
                patch.object(dialog, "_start") as start,
            ):
                dialog._change_mask()
                start.assert_called_once_with("update_mask", None, 1)
