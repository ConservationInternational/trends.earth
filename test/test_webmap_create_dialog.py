"""Creation workflow tests."""

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from osgeo import gdal, ogr, osr
from qgis.core import (
    QgsApplication,
    QgsColorRampShader,
    QgsRasterLayer,
    QgsVectorLayer,
)
from qgis.PyQt import QtCore, QtGui

from LDMP.webmap_create_dialog import (
    CreateWebmapDialog,
    _LayerOptions,
    _PrepareTask,
    _PublishTask,
    _validate_style,
)
from LDMP.webmap_sharing import ShareError


class TestWebmapPublication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance() or QgsApplication([], False)

    def snapshots(self):
        return [
            {
                "path": "/snapshot.tif",
                "declaration": {"name": "raster", "size_bytes": 3},
            },
            {
                "path": "/snapshot.pmtiles",
                "declaration": {"name": "vector", "size_bytes": 2},
            },
        ]

    def draft(self):
        return {
            "id": "share",
            "state": "draft",
            "layers": [
                {"id": "r", "name": "raster", "upload_completed": False},
                {"id": "v", "name": "vector", "upload_completed": False},
            ],
        }

    @patch("LDMP.webmap_create_dialog.time.sleep")
    @patch("LDMP.webmap_create_dialog.ShareClient")
    def test_create_upload_validate_publish_and_retry_discovery(self, client, _sleep):
        owner = client.return_value
        owner.create.return_value = self.draft()
        owner.upload.side_effect = [
            {"layer_id": "r", "parts": [{"part_number": 1, "etag": "r"}]},
            {"layer_id": "v", "parts": [{"part_number": 1, "etag": "v"}]},
        ]
        owner.complete.return_value = {"state": "validating"}
        owner.status.return_value = {"state": "ready", "ready_at": None}
        owner.publish.side_effect = [
            ShareError("Not ready", 503),
            {"link": "https://viewer/#secret", "share": {"expires_at": "utc"}},
        ]
        task = _PublishTask(
            "https://api.test", "token", "Title", 7, self.snapshots(), None, Mock()
        )
        self.assertTrue(task.run(), task.error)
        self.assertEqual(task.share_id, "share")
        self.assertEqual(task.result["share"]["expires_at"], "utc")
        self.assertEqual(owner.upload.call_count, 2)
        self.assertEqual(owner.publish.call_count, 2)
        owner.complete.assert_called_once_with(
            "share",
            [
                {"layer_id": "r", "parts": [{"part_number": 1, "etag": "r"}]},
                {"layer_id": "v", "parts": [{"part_number": 1, "etag": "v"}]},
            ],
        )
        owner.close.assert_called_once()
        self.assertIsNone(task.token)

    @patch("LDMP.webmap_create_dialog.ShareClient")
    def test_retry_skips_completed_uploads(self, client):
        owner = client.return_value
        draft = self.draft()
        draft["state"] = "uploading"
        draft["layers"][0]["upload_completed"] = True
        owner.status.return_value = draft
        owner.upload.return_value = {
            "layer_id": "v",
            "parts": [{"part_number": 1, "etag": "v"}],
        }
        owner.complete.return_value = {"state": "ready", "ready_at": None}
        owner.publish.return_value = {
            "link": "https://viewer/#secret",
            "share": {"expires_at": "utc"},
        }
        task = _PublishTask(
            "https://api.test", "token", "Title", 7, self.snapshots(), "share", Mock()
        )
        self.assertTrue(task.run(), task.error)
        self.assertEqual(owner.upload.call_count, 1)
        self.assertEqual(
            owner.complete.call_args.args[1][0], {"layer_id": "r", "parts": []}
        )

    @patch("LDMP.webmap_create_dialog.time.sleep")
    @patch("LDMP.webmap_create_dialog.ShareClient")
    def test_retry_reenqueues_interrupted_validation(self, client, _sleep):
        owner = client.return_value
        draft = self.draft()
        draft["state"] = "validating"
        owner.status.side_effect = [draft, {"state": "ready", "ready_at": None}]
        owner.complete.return_value = {"state": "validating"}
        owner.publish.return_value = {
            "link": "https://viewer/#secret",
            "share": {"expires_at": "utc"},
        }
        task = _PublishTask(
            "https://api.test", "token", "Title", 7, self.snapshots(), "share", Mock()
        )
        self.assertTrue(task.run(), task.error)
        owner.complete.assert_called_once_with(
            "share",
            [{"layer_id": "r", "parts": []}, {"layer_id": "v", "parts": []}],
        )

    @patch("LDMP.webmap_create_dialog.ShareClient")
    def test_failed_validation_never_publishes(self, client):
        owner = client.return_value
        draft = self.draft()
        draft["state"] = "failed"
        draft["validation_errors"] = [{"layer_id": "r", "error": "Invalid COG"}]
        owner.status.return_value = draft
        task = _PublishTask(
            "https://api.test", "token", "Title", 7, self.snapshots(), "share", Mock()
        )
        self.assertFalse(task.run())
        self.assertIn("Invalid COG", task.error)
        owner.publish.assert_not_called()
        owner.upload.assert_not_called()

    @patch("LDMP.webmap_create_dialog.ShareClient")
    def test_cancel_before_start_does_not_create_draft(self, client):
        task = _PublishTask(
            "https://api.test", "token", "Title", 7, self.snapshots(), None, Mock()
        )
        task.cancel()
        self.assertFalse(task.run())
        client.assert_not_called()

    @patch("LDMP.webmap_create_dialog.ShareClient")
    def test_invalid_publication_response_is_not_reported_as_success(self, client):
        owner = client.return_value
        draft = self.draft()
        draft["state"] = "ready"
        draft["ready_at"] = None
        owner.status.return_value = draft
        owner.publish.return_value = {"link": "https://viewer/#secret"}
        callback = Mock()
        task = _PublishTask(
            "https://api.test", "token", "Title", 7, self.snapshots(), "share", callback
        )
        self.assertFalse(task.run())
        task.finished(False)
        self.assertFalse(callback.call_args.args[0])

    @patch("LDMP.webmap_create_dialog.time.sleep")
    @patch("LDMP.webmap_create_dialog.ShareClient")
    def test_add_layers_to_published_share_preserves_link(self, client, _sleep):
        owner = client.return_value
        snapshot = self.snapshots()[0]
        snapshot["declaration"].update(
            kind="raster",
            band=1,
            sha256=hashlib.sha256(b"raster").hexdigest(),
            style={"kind": "categorical", "values": {"1": "#ff0000"}},
            attribution="",
        )
        current = {
            "id": "share",
            "state": "ready",
            "update_state": "idle",
            "ready_at": "published",
            "layers": [{"id": "old", "name": "old", "published": True}],
        }
        added = {
            **current,
            "update_state": "uploading",
            "layers": current["layers"]
            + [
                {
                    "id": "new",
                    "name": "raster",
                    "published": False,
                    "upload_completed": False,
                }
            ],
        }
        owner.status.side_effect = [
            current,
            {**added, "update_state": "validating"},
            {**added, "update_state": "idle"},
        ]
        owner.add_layers.return_value = added
        owner.upload.return_value = {"layer_id": "new", "parts": []}
        owner.complete.return_value = {**added, "update_state": "validating"}
        task = _PublishTask(
            "https://api.test",
            "token",
            "",
            7,
            [snapshot],
            "share",
            Mock(),
            update_existing=True,
        )

        self.assertTrue(task.run(), task.error)
        self.assertTrue(task.updated)
        owner.publish.assert_not_called()
        owner.add_layers.assert_called_once()
        owner.complete.assert_called_once_with(
            "share", [{"layer_id": "new", "parts": []}]
        )

    @patch("LDMP.webmap_create_dialog.time.sleep")
    def test_real_client_runs_multipart_contract(self, _sleep):
        share_id = "bd729388-17b4-4083-b761-f9de911b026a"
        layer_id = "17170ee0-1623-456f-8bf6-3e57f7a5042d"
        state = {}

        def response(status, data=None, headers=None):
            obj = Mock(status_code=status, headers=headers or {})
            obj.json.return_value = {"data": data}
            return obj

        class Session:
            def __init__(self):
                self.auth = None
                self.trust_env = True

            def request(self, method, url, **kwargs):
                self_test.assertEqual(
                    kwargs["headers"]["Authorization"], "Bearer token"
                )
                self_test.assertFalse(kwargs["allow_redirects"])
                if url.endswith("/shares"):
                    state["declaration"] = kwargs["json"]["layers"][0]
                    return response(
                        201,
                        {
                            "id": share_id,
                            "state": "draft",
                            "layers": [
                                {
                                    "id": layer_id,
                                    "name": "raster",
                                    "upload_completed": False,
                                }
                            ],
                        },
                    )
                if url.endswith("/uploads"):
                    return response(
                        201,
                        {
                            "layer_id": layer_id,
                            "parts": [
                                {
                                    "part_number": 1,
                                    "size_bytes": 4,
                                    "url": "https://s3.test/part",
                                }
                            ],
                        },
                    )
                if url.endswith("/complete"):
                    self_test.assertEqual(
                        hashlib.sha256(state["bytes"]).hexdigest(),
                        state["declaration"]["sha256"],
                    )
                    self_test.assertEqual(
                        kwargs["json"]["layers"][0]["parts"][0]["etag"], '"etag"'
                    )
                    return response(202, {"state": "validating"})
                if url.endswith("/publish"):
                    return response(
                        200,
                        {
                            "link": "https://viewer.test/share#secret",
                            "share": {"expires_at": "2026-01-08T00:00:00Z"},
                        },
                    )
                return response(200, {"state": "ready", "ready_at": None})

            def put(self, _url, **kwargs):
                self_test.assertFalse(self.trust_env)
                self_test.assertNotIn("Authorization", kwargs["headers"])
                body = kwargs["data"]
                chunks = []
                while chunk := body.read(2):
                    chunks.append(chunk)
                state["bytes"] = b"".join(chunks)
                return response(200, headers={"ETag": '"etag"'})

            def close(self):
                pass

        class UploadSession(Session):
            def __init__(self):
                super().__init__()
                self.trust_env = False

        self_test = self
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.tif"
            path.write_bytes(b"data")
            snapshots = [
                {
                    "path": path,
                    "declaration": {
                        "name": "raster",
                        "size_bytes": 4,
                        "sha256": hashlib.sha256(b"data").hexdigest(),
                    },
                }
            ]
            with (
                patch("LDMP.webmap_sharing.requests.Session", Session),
                patch("LDMP.webmap_sharing._UploadSession", UploadSession),
            ):
                task = _PublishTask(
                    "https://api.test", "token", "Title", 7, snapshots, None, Mock()
                )
                self.assertTrue(task.run(), task.error)
            self.assertEqual(task.result["share"]["expires_at"], "2026-01-08T00:00:00Z")


class TestWebmapCreationUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QgsApplication.instance()
        if cls.app is None:
            cls.app = QgsApplication([], False)
            QgsApplication.initQgis()

    @patch("LDMP.webmap_create_dialog.api.APIClient")
    def test_select_and_configure_local_raster(self, _client):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "layer.tif"
            data = gdal.GetDriverByName("GTiff").Create(str(path), 4, 4, 1)
            crs = osr.SpatialReference()
            crs.ImportFromEPSG(4326)
            data.SetProjection(crs.ExportToWkt())
            data.SetGeoTransform((10, 0.1, 0, 20, 0, -0.1))
            data = None
            layer = QgsRasterLayer(str(path), "Local raster")
            self.assertTrue(layer.isValid())
            layer.setAttribution("Test attribution")
            band_info = {
                "name": "Test band",
                "no_data_value": -9999,
                "metadata": {},
            }
            style_config = {
                "ramp": {
                    "type": "categorical",
                    "no data": {"value": -9999},
                }
            }
            ramp_items = [
                QgsColorRampShader.ColorRampItem(
                    -9999, QtGui.QColor("#000000"), "No data"
                ),
                QgsColorRampShader.ColorRampItem(
                    1, QtGui.QColor("#ff0000"), "One"
                ),
            ]
            with (
                patch(
                    "LDMP.webmap_create_dialog.default_raster_styles",
                    {"Test band": style_config},
                ),
                patch(
                    "LDMP.webmap_create_dialog._create_color_ramp",
                    return_value=ramp_items,
                ),
                patch("LDMP.webmap_create_dialog._get_band_scale", return_value=1),
            ):
                options = _LayerOptions(layer, 1, band_info)
            self.assertEqual(options.attribution.text(), "Test attribution")
            self.assertEqual(
                options.default_style,
                {"kind": "categorical", "values": {"1": "#ff0000"}},
            )
            options._accept()
            self.assertEqual(options.configuration["path"], str(path))
            self.assertEqual(options.configuration["band"], 1)
            task = _PrepareTask([options.configuration], directory, Mock())
            self.assertTrue(task.run(), task.error)
            self.assertEqual(task.snapshots[0]["declaration"]["band"], 1)
            self.assertTrue(task.snapshots[0]["path"].exists())
            task.snapshots[0]["path"].unlink()
            loop = QtCore.QEventLoop()
            completed = []
            asynchronous = _PrepareTask(
                [options.configuration],
                directory,
                lambda result, _snapshots, error: (
                    completed.append((result, error)),
                    loop.quit(),
                ),
            )
            timer = QtCore.QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(10000)
            QgsApplication.taskManager().addTask(asynchronous)
            loop.exec()
            timer.stop()
            self.assertEqual(completed, [(True, None)])
            dialog = CreateWebmapDialog()
            dialog.configurations = [options.configuration]
            dialog.title.setText("Test map")
            self.assertEqual(dialog.retention.currentData(), 7)
            self.assertTrue(hasattr(dialog, "output_choice"))
            dialog.reject()
            options.deleteLater()
            layer = None

    def test_select_vector_fields_explicitly(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "layer.gpkg"
            data = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
            crs = osr.SpatialReference()
            crs.ImportFromEPSG(4326)
            layer = data.CreateLayer("result", crs, ogr.wkbPoint)
            layer.CreateField(ogr.FieldDefn("public", ogr.OFTString))
            layer.CreateField(ogr.FieldDefn("secret", ogr.OFTString))
            data = None
            vector = QgsVectorLayer(f"{path}|layername=result", "Result", "ogr")
            self.assertTrue(vector.isValid())
            options = _LayerOptions(vector)
            for index in range(options.fields.count()):
                item = options.fields.item(index)
                self.assertEqual(item.checkState(), QtCore.Qt.Unchecked)
                if item.text() == "public":
                    item.setCheckState(QtCore.Qt.Checked)
            options._accept()
            self.assertEqual(options.configuration["source_layer_name"], "result")
            self.assertEqual(options.configuration["fields"], ["public"])

    def test_rejects_vector_style_category_without_public_field(self):
        style = {
            "kind": "vector",
            "stroke": "#000000",
            "fill": "#ffffff",
            "width": 1,
            "fill_opacity": 0.5,
            "radius": 4,
            "category": {"field": "secret", "values": {"x": "#ffffff"}},
        }
        with self.assertRaises(ShareError):
            _validate_style(style, "vector", [])


if __name__ == "__main__":
    unittest.main()
