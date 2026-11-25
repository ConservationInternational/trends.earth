"""Tests for the owner API and private multipart transfer contract."""

import http.server
import importlib.util
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from qgis.PyQt import QtCore, QtNetwork
from qgis.PyQt.QtNetwork import QNetworkProxy

spec = importlib.util.spec_from_file_location(
    "webmap_sharing", Path(__file__).resolve().parents[1] / "LDMP/webmap_sharing.py"
)
sharing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sharing)

SHARE = "bd729388-17b4-4083-b761-f9de911b026a"
LAYER = "17170ee0-1623-456f-8bf6-3e57f7a5042d"


def response(status=200, data=None, headers=None):
    result = Mock(status_code=status, headers=headers or {})
    result.json.return_value = {"data": data}
    return result


def part_list(suffix="first"):
    return {
        "layer_id": LAYER,
        "parts": [
            {"part_number": 1, "size_bytes": 3, "url": f"https://s3.test/{suffix}1"},
            {"part_number": 2, "size_bytes": 2, "url": f"https://s3.test/{suffix}2"},
        ],
    }


class TestWebmapSharing(unittest.TestCase):
    def setUp(self):
        proxy = patch.object(sharing, "_proxy_for_url", return_value=None)
        proxy.start()
        self.addCleanup(proxy.stop)
        self.client = sharing.ShareClient("https://api.test", "owner-token")
        self.client._api_session = Mock()
        self.client._upload_session = Mock()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.file = Path(self.directory.name) / "snapshot"
        self.file.write_bytes(b"abcde")

    def tearDown(self):
        self.client.close()

    def test_append_layers_uses_owner_api_route(self):
        declarations = [{"name": "new output", "kind": "raster"}]
        self.client._api_session.request.return_value = response(data={"id": SHARE})

        self.assertEqual(self.client.add_layers(SHARE, declarations), {"id": SHARE})
        args, kwargs = self.client._api_session.request.call_args
        self.assertEqual(
            args, ("POST", f"https://api.test/api/v1/shares/{SHARE}/layers")
        )
        self.assertEqual(kwargs["json"], {"layers": declarations})
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer owner-token")

    def test_owner_api_and_one_time_link(self):
        self.client._api_session.request.return_value = response(
            data={"link": "https://viewer.test/share/s/public-token"}
        )
        self.assertEqual(
            self.client.publish(SHARE)["link"],
            "https://viewer.test/share/s/public-token",
        )
        args, kwargs = self.client._api_session.request.call_args
        self.assertEqual(
            args, ("POST", f"https://api.test/api/v1/shares/{SHARE}/publish")
        )
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer owner-token")
        self.assertFalse(kwargs["allow_redirects"])

    def test_owner_can_retrieve_current_link(self):
        self.client._api_session.request.return_value = response(
            data={"link": "https://viewer.test/share/s/public-token"}
        )
        self.assertEqual(
            self.client.link(SHARE)["link"], "https://viewer.test/share/s/public-token"
        )
        args, _ = self.client._api_session.request.call_args
        self.assertEqual(args, ("GET", f"https://api.test/api/v1/shares/{SHARE}/link"))

    def test_api_503_explains_server_configuration_is_required(self):
        self.client._api_session.request.return_value = response(status=503)

        with self.assertRaises(sharing.ShareError) as context:
            self.client.create("Test map", 7, [])

        self.assertIn("configured API returned HTTP 503", str(context.exception))
        self.assertIn("Contact the API administrator", str(context.exception))
        self.assertEqual(
            self.client._api_session.request.call_args.args[1],
            "https://api.test/api/v1/shares",
        )

    def test_upload_refreshes_expired_urls_and_sends_only_part_bytes(self):
        self.client._api_session.request.side_effect = [
            response(data=part_list()),
            response(data=part_list("renewed")),
        ]
        sent = []

        def put(url, **kwargs):
            body = kwargs["data"]
            sent.append((url, body.read(), kwargs))
            if len(sent) == 1:
                return response(status=403)
            return response(headers={"ETag": f'"etag{len(sent)}"'})

        self.client._upload_session.put.side_effect = put
        progress = []
        result = self.client.upload(SHARE, LAYER, self.file, progress=progress.append)
        self.assertEqual([entry[1] for entry in sent], [b"abc", b"abc", b"de"])
        self.assertEqual(sent[1][0], "https://s3.test/renewed1")
        self.assertEqual(
            result["parts"],
            [
                {"part_number": 1, "etag": '"etag2"'},
                {"part_number": 2, "etag": '"etag3"'},
            ],
        )
        self.assertEqual(progress[-1], 5)
        for _, _, kwargs in sent:
            self.assertNotIn("Authorization", kwargs["headers"])

    def test_invalid_upload_description_never_contacts_storage(self):
        bad = part_list()
        bad["parts"][0]["url"] = "http://s3.test/secret"
        self.client._api_session.request.return_value = response(data=bad)
        with self.assertRaises(sharing.ShareError):
            self.client.upload(SHARE, LAYER, self.file)
        self.client._upload_session.put.assert_not_called()

    def test_cancel_during_stream_does_not_complete_upload(self):
        self.client._api_session.request.return_value = response(data=part_list())
        checks = iter([False, True])

        def put(url, **kwargs):
            kwargs["data"].read()

        self.client._upload_session.put.side_effect = put
        with self.assertRaises(sharing.ShareCancelled):
            self.client.upload(SHARE, LAYER, self.file, cancelled=lambda: next(checks))

    def test_error_does_not_include_signed_url(self):
        self.client._api_session.request.return_value = response(data=part_list())
        self.client._upload_session.put.side_effect = sharing.ShareError(
            "Could not contact upload storage"
        )
        with self.assertRaises(sharing.ShareError) as error:
            self.client.upload(SHARE, LAYER, self.file)
        self.assertNotIn("secret", str(error.exception))

    def test_signed_upload_uses_qgis_network_manager_and_bounded_stream(self):
        manager = Mock()
        reply = Mock()
        reply.isFinished.return_value = True
        reply.attribute.return_value = 200
        reply.rawHeader.return_value = QtCore.QByteArray(b'"etag"')
        reply.uploadProgress.connect.side_effect = lambda callback: callback(3, 3)
        sent = []

        def put(request, device):
            sent.append(bytes(device.read(3)))
            return reply

        manager.put.side_effect = put
        source = self.file.open("rb")
        self.addCleanup(source.close)
        reader = sharing._PartReader(source, 3, lambda: False, lambda _count: None, 0)
        with patch.object(
            sharing.QgsNetworkAccessManager, "instance", return_value=manager
        ):
            result = sharing._UploadSession().put(
                "https://s3.test/part?signature=secret",
                data=reader,
                headers={"Content-Length": "3"},
                timeout=30,
            )

        request = manager.put.call_args.args[0]
        self.assertEqual(
            request.url().toString(), "https://s3.test/part?signature=secret"
        )
        self.assertEqual(
            bytes(request.rawHeader(QtCore.QByteArray(b"Content-Length"))), b"3"
        )
        self.assertFalse(request.rawHeader(QtCore.QByteArray(b"Authorization")))
        try:
            redirect_attribute = (
                QtNetwork.QNetworkRequest.Attribute.RedirectPolicyAttribute
            )
            manual_redirect = (
                QtNetwork.QNetworkRequest.RedirectPolicy.ManualRedirectPolicy
            )
        except AttributeError:
            redirect_attribute = QtNetwork.QNetworkRequest.RedirectPolicyAttribute
            manual_redirect = QtNetwork.QNetworkRequest.ManualRedirectPolicy
        self.assertEqual(request.attribute(redirect_attribute), manual_redirect)
        self.assertEqual(sent, [b"abc"])
        self.assertEqual(reader.remaining, 0)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers["ETag"], '"etag"')

    def test_qgis_network_manager_streams_upload_to_local_server(self):
        requests_seen = []

        class Target(http.server.BaseHTTPRequestHandler):
            def do_PUT(self):
                if self.headers.get("Transfer-Encoding") == "chunked":
                    chunks = []
                    while length := int(self.rfile.readline().strip(), 16):
                        chunks.append(self.rfile.read(length))
                        self.rfile.read(2)
                    self.rfile.readline()
                    body = b"".join(chunks)
                else:
                    body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                requests_seen.append(
                    (
                        self.path,
                        body,
                        self.headers.get("Content-Length"),
                        self.headers.get("Authorization"),
                    )
                )
                self.send_response(200)
                self.send_header("ETag", '"etag"')
                self.end_headers()

            def log_message(self, *_args):
                pass

        manager = sharing.QgsNetworkAccessManager.instance()
        original = QNetworkProxy(manager.fallbackProxy())
        excludes = manager.excludeList()
        no_proxy = manager.noProxyList()
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Target)
        server.daemon_threads = True
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        source = self.file.open("rb")
        progress = []
        reader = sharing._PartReader(source, 3, lambda: False, progress.append, 0)
        try:
            manager.setFallbackProxyAndExcludes(
                QNetworkProxy(QNetworkProxy.ProxyType.NoProxy), [], []
            )
            result = sharing._UploadSession().put(
                f"http://127.0.0.1:{server.server_address[1]}/part?signature=secret",
                data=reader,
                headers={"Content-Length": "3"},
                timeout=5,
            )
        finally:
            source.close()
            server.shutdown()
            server.server_close()
            worker.join()
            manager.setFallbackProxyAndExcludes(original, excludes, no_proxy)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers["ETag"], '"etag"')
        self.assertEqual(reader.remaining, 0)
        self.assertEqual(requests_seen, [("/part?signature=secret", b"abc", "3", None)])

    def test_qgis_network_manager_uploads_each_multipart_part_exactly(self):
        part_size = 6 * 1024**2
        content = os.urandom(2 * part_size)
        self.file.write_bytes(content)
        bodies = []

        class Target(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_PUT(self):
                bodies.append(self.rfile.read(int(self.headers["Content-Length"])))
                self.send_response(200)
                self.send_header("ETag", f'"etag{len(bodies)}"')
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *_args):
                pass

        manager = sharing.QgsNetworkAccessManager.instance()
        original = QNetworkProxy(manager.fallbackProxy())
        excludes = manager.excludeList()
        no_proxy = manager.noProxyList()
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Target)
        server.daemon_threads = True
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        parts = [
            {"part_number": n, "size_bytes": part_size, "url": f"{base}/{n}"}
            for n in (1, 2)
        ]
        self.client._upload_session = sharing._UploadSession()
        try:
            manager.setFallbackProxyAndExcludes(
                QNetworkProxy(QNetworkProxy.ProxyType.NoProxy), [], []
            )
            with patch.object(self.client, "_parts", return_value=parts):
                result = self.client.upload(SHARE, LAYER, self.file)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
            manager.setFallbackProxyAndExcludes(original, excludes, no_proxy)
        self.assertEqual(bodies, [content[:part_size], content[part_size:]])
        self.assertEqual(
            result["parts"],
            [
                {"part_number": 1, "etag": '"etag1"'},
                {"part_number": 2, "etag": '"etag2"'},
            ],
        )

    def test_owner_api_uses_resolved_proxy_and_explicit_ca_bundle(self):
        self.client._api_session.request.return_value = response(data=[])
        with (
            patch.object(sharing, "_proxy_for_url", return_value="http://proxy:3128"),
            patch.dict(os.environ, {"REQUESTS_CA_BUNDLE": "/trusted-ca.pem"}),
        ):
            self.client.list()
        kwargs = self.client._api_session.request.call_args.kwargs
        self.assertEqual(kwargs["proxies"], {"https": "http://proxy:3128"})
        self.assertEqual(kwargs["verify"], "/trusted-ca.pem")

    def test_rejects_bad_ids_and_unsafe_api_url(self):
        with self.assertRaises(sharing.ShareError):
            self.client.status("../storage")
        with self.assertRaises(sharing.ShareError):
            sharing.ShareClient("https://user:password@api.test", "token")
        with self.assertRaises(sharing.ShareError):
            sharing.ShareClient("https://[bad", "token")


class TestWebmapProxyResolution(unittest.TestCase):
    def setUp(self):
        manager = Mock()
        self.factory = manager.proxyFactory.return_value
        proxy_manager = patch("qgis.core.QgsNetworkAccessManager")
        proxy_manager.start().instance.return_value = manager
        self.addCleanup(proxy_manager.stop)

    def test_qgis_http_proxy_receives_no_signature(self):
        self.factory.queryProxy.return_value = [
            QNetworkProxy(QNetworkProxy.ProxyType.HttpProxy, "proxy", 3128, "u", "p@ss")
        ]
        result = sharing._proxy_for_url("https://s3.test/part?signature=secret")
        self.assertEqual(result, "http://u:p%40ss@proxy:3128")
        query = self.factory.queryProxy.call_args.args[0]
        self.assertEqual(query.url().toString(), "https://s3.test/part")

    def test_qgis_no_proxy_overrides_environment(self):
        self.factory.queryProxy.return_value = [
            QNetworkProxy(QNetworkProxy.ProxyType.NoProxy)
        ]
        with patch.dict("os.environ", {"https_proxy": "http://proxy:3128"}):
            self.assertIsNone(sharing._proxy_for_url("https://s3.test/part?secret"))

    def test_default_proxy_honors_environment_bypass(self):
        self.factory.queryProxy.return_value = [
            QNetworkProxy(QNetworkProxy.ProxyType.DefaultProxy)
        ]
        with patch.dict(
            "os.environ",
            {"https_proxy": "http://proxy:3128", "no_proxy": "s3.test"},
            clear=True,
        ):
            self.assertIsNone(sharing._proxy_for_url("https://s3.test/part?secret"))
            self.assertEqual(
                sharing._proxy_for_url("https://other.test/part?secret"),
                "http://proxy:3128",
            )

    def test_unsupported_proxy_is_reported_without_credentials(self):
        self.factory.queryProxy.return_value = [
            QNetworkProxy(QNetworkProxy.ProxyType.DefaultProxy)
        ]
        with (
            patch.dict(
                "os.environ",
                {"https_proxy": "https://user:secret@proxy:443"},
                clear=True,
            ),
            self.assertRaises(sharing.ShareError) as error,
        ):
            sharing._proxy_for_url("https://s3.test/part?signature=secret")
        self.assertNotIn("secret", str(error.exception))


class TestWebmapQgisProxy(unittest.TestCase):
    def test_real_qgis_proxy_factory_and_exclusion(self):
        from qgis.core import QgsNetworkAccessManager

        manager = QgsNetworkAccessManager.instance()
        original = QNetworkProxy(manager.fallbackProxy())
        excludes = manager.excludeList()
        no_proxy = manager.noProxyList()
        self.addCleanup(
            manager.setFallbackProxyAndExcludes, original, excludes, no_proxy
        )
        manager.setFallbackProxyAndExcludes(
            QNetworkProxy(QNetworkProxy.ProxyType.HttpProxy, "proxy.test", 3128),
            [],
            ["https://excluded.test/"],
        )
        self.assertEqual(
            sharing._proxy_for_url("https://s3.test/part?signature=secret"),
            "http://proxy.test:3128",
        )
        self.assertIsNone(
            sharing._proxy_for_url("https://excluded.test/part?signature=secret")
        )


if __name__ == "__main__":
    unittest.main()
