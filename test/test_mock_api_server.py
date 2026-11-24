import multiprocessing
import socket
import unittest

import requests
from mock.mock_http_server import MockApiServer, run_mock_api_server


class TestMockApiServer(unittest.TestCase):
    def test_server_starts_with_serialized_process_contexts(self):
        methods = [
            method
            for method in ("spawn", "forkserver")
            if method in multiprocessing.get_all_start_methods()
        ]
        for method in methods:
            with self.subTest(method=method):
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]

                server = MockApiServer(port)
                process = multiprocessing.get_context(method).Process(
                    target=run_mock_api_server, args=(port,)
                )
                process.start()
                try:
                    self.assertTrue(server.wait_until_ready(timeout=10))
                    response = requests.get(f"{server.url}/api/v1", timeout=5)
                    self.assertEqual(response.status_code, 200)
                finally:
                    process.terminate()
                    process.join(timeout=10)
                    self.assertFalse(process.is_alive())
