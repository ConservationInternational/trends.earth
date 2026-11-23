"""Tests for the owner API and private multipart transfer contract."""

import http.client
import http.server
import importlib.util
import os
import select
import shutil
import socket
import socketserver
import ssl
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import ANY, Mock, patch

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

    def test_owner_api_and_one_time_link(self):
        self.client._api_session.request.return_value = response(
            data={"link": "https://viewer.test/#secret"}
        )
        self.assertEqual(
            self.client.publish(SHARE)["link"], "https://viewer.test/#secret"
        )
        args, kwargs = self.client._api_session.request.call_args
        self.assertEqual(
            args, ("POST", f"https://api.test/api/v1/shares/{SHARE}/publish")
        )
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer owner-token")
        self.assertFalse(kwargs["allow_redirects"])

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
            self.assertFalse(kwargs["allow_redirects"])
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
        self.client._upload_session.put.side_effect = http.client.HTTPException(
            "https://s3.test/?secret"
        )
        with self.assertRaises(sharing.ShareError) as error:
            self.client.upload(SHARE, LAYER, self.file)
        self.assertNotIn("secret", str(error.exception))

    def test_signed_upload_uses_bounded_stream_without_http_debugging(self):
        source = Mock()
        source.read.side_effect = [b"abc", b""]
        connection = Mock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.getheader.return_value = '"etag"'
        with patch.object(
            sharing.http.client, "HTTPSConnection", return_value=connection
        ):
            result = sharing._UploadSession().put(
                "https://s3.test/part?signature=secret",
                data=source,
                headers={"Content-Length": "3"},
                timeout=30,
                allow_redirects=False,
            )
        connection.set_debuglevel.assert_called_once_with(0)
        connection.putrequest.assert_called_once_with(
            "PUT", "/part?signature=secret", skip_accept_encoding=True
        )
        connection.send.assert_called_once_with(b"abc")
        connection.close.assert_called_once()
        self.assertEqual(result.headers["ETag"], '"etag"')

    def test_signed_upload_uses_authenticated_http_connect(self):
        source = Mock()
        source.read.side_effect = [b"abc", b""]
        connection = Mock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.getheader.return_value = '"etag"'
        with (
            patch.object(
                sharing, "_proxy_for_url", return_value="http://user:p%40ss@proxy:3128"
            ),
            patch.object(
                sharing.http.client, "HTTPSConnection", return_value=connection
            ) as factory,
        ):
            sharing._UploadSession().put(
                "https://s3.test/part?signature=secret",
                data=source,
                headers={"Content-Length": "3"},
                timeout=30,
                allow_redirects=False,
            )
        factory.assert_called_once_with("proxy", 3128, timeout=30, context=ANY)
        connection.set_tunnel.assert_called_once_with(
            "s3.test",
            443,
            headers={"Proxy-Authorization": "Basic dXNlcjpwQHNz"},
        )
        connection.putrequest.assert_called_once_with(
            "PUT", "/part?signature=secret", skip_accept_encoding=True
        )
        connection.putheader.assert_called_once_with("Content-Length", "3")

    def test_socks_proxy_uses_remote_dns_and_credentials(self):
        source = Mock()
        source.read.return_value = b""
        connection = Mock()
        connection.getresponse.return_value.status = 200
        with (
            patch.object(
                sharing, "_proxy_for_url", return_value="socks5h://user:pass@proxy:1080"
            ),
            patch.object(
                sharing.http.client, "HTTPSConnection", return_value=connection
            ),
            patch.object(sharing.socks, "create_connection") as connect,
        ):
            sharing._UploadSession().put(
                "https://s3.test/part?signature=secret",
                data=source,
                headers={"Content-Length": "0"},
                timeout=30,
                allow_redirects=False,
            )
            connection._create_connection(("s3.test", 443), 30)
        connect.assert_called_once_with(
            ("s3.test", 443),
            timeout=30,
            source_address=None,
            proxy_type=sharing.socks.SOCKS5,
            proxy_addr="proxy",
            proxy_port=1080,
            proxy_rdns=True,
            proxy_username="user",
            proxy_password="pass",
        )

    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL is required for TLS fixture")
    def test_signed_upload_through_proxies_to_tls_server(self):
        requests_seen = []
        connects = []
        socks_requests = []

        def relay(local, remote):
            while True:
                ready, _, _ = select.select([local, remote], [], [], 5)
                if not ready:
                    return
                for source in ready:
                    data = source.recv(65536)
                    if not data:
                        return
                    (remote if source is local else local).sendall(data)

        class Target(http.server.BaseHTTPRequestHandler):
            def do_PUT(self):
                requests_seen.append(
                    (self.path, self.rfile.read(int(self.headers["Content-Length"])))
                )
                self.send_response(200)
                self.send_header("ETag", '"etag"')
                self.send_header("Connection", "close")
                self.end_headers()

            def log_message(self, *_args):
                pass

        class Proxy(socketserver.StreamRequestHandler):
            def handle(self):
                first = self.rfile.readline().decode("ascii").strip()
                headers = []
                while True:
                    line = self.rfile.readline()
                    if line in (b"\r\n", b""):
                        break
                    headers.append(line.decode("ascii").strip())
                connects.append((first, headers))
                with socket.create_connection(target.server_address) as remote:
                    self.wfile.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                    self.wfile.flush()
                    relay(self.connection, remote)

        class SocksProxy(socketserver.StreamRequestHandler):
            def handle(self):
                version, count = self.rfile.read(2)
                methods = self.rfile.read(count)
                if version != 5 or 2 not in methods:
                    return
                self.wfile.write(b"\x05\x02")
                self.wfile.flush()
                version, length = self.rfile.read(2)
                username = self.rfile.read(length)
                length = self.rfile.read(1)[0]
                password = self.rfile.read(length)
                if version != 1:
                    return
                self.wfile.write(b"\x01\x00")
                self.wfile.flush()
                version, command, _, address_type = self.rfile.read(4)
                if version != 5 or command != 1 or address_type != 1:
                    return
                address = socket.inet_ntoa(self.rfile.read(4))
                port = int.from_bytes(self.rfile.read(2), "big")
                socks_requests.append((username, password, address, port))
                with socket.create_connection(target.server_address) as remote:
                    self.wfile.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
                    self.wfile.flush()
                    relay(self.connection, remote)

        key = Path(self.directory.name) / "key.pem"
        certificate = Path(self.directory.name) / "certificate.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(certificate),
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=IP:127.0.0.1",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        target = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Target)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certificate, key)
        target.socket = context.wrap_socket(target.socket, server_side=True)
        proxy = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Proxy)
        proxy.daemon_threads = True
        socks_proxy = socketserver.ThreadingTCPServer(("127.0.0.1", 0), SocksProxy)
        socks_proxy.daemon_threads = True
        for server in (target, proxy, socks_proxy):
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
        reader = sharing._PartReader(
            self.file.open("rb"), 3, lambda: False, lambda _count: None, 0
        )
        self.addCleanup(reader.source.close)
        with (
            patch.object(
                sharing,
                "_proxy_for_url",
                return_value=f"http://user:pass@127.0.0.1:{proxy.server_address[1]}",
            ),
            patch.dict(os.environ, {"REQUESTS_CA_BUNDLE": str(certificate)}),
        ):
            result = sharing._UploadSession().put(
                f"https://127.0.0.1:{target.server_address[1]}/part?signature=secret",
                data=reader,
                headers={"Content-Length": "3"},
                timeout=5,
                allow_redirects=False,
            )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers["ETag"], '"etag"')
        self.assertEqual(requests_seen, [("/part?signature=secret", b"abc")])
        self.assertTrue(
            connects[0][0].startswith(f"CONNECT 127.0.0.1:{target.server_address[1]} ")
        )
        self.assertIn("Proxy-Authorization: Basic dXNlcjpwYXNz", connects[0][1])
        self.assertNotIn("signature", str(connects))
        reader.source.seek(0)
        reader.remaining = 3
        with (
            patch.object(
                sharing,
                "_proxy_for_url",
                return_value=f"socks5h://user:pass@127.0.0.1:{socks_proxy.server_address[1]}",
            ),
            patch.dict(os.environ, {"REQUESTS_CA_BUNDLE": str(certificate)}),
        ):
            result = sharing._UploadSession().put(
                f"https://127.0.0.1:{target.server_address[1]}/part?signature=secret",
                data=reader,
                headers={"Content-Length": "3"},
                timeout=5,
                allow_redirects=False,
            )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(requests_seen[-1], ("/part?signature=secret", b"abc"))
        self.assertEqual(
            socks_requests, [(b"user", b"pass", "127.0.0.1", target.server_address[1])]
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
