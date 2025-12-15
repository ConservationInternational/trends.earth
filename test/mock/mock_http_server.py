import time
from threading import Thread

import requests
from flask import request

from .trends_api_server_app import app


class MockApiServer(Thread):
    """Mock a live API server with health check support"""

    def __init__(self, port=5000):
        super().__init__()
        self.port = port
        self.app = app
        self.url = "http://localhost:%s" % self.port

        try:
            self.app.add_url_rule("/shutdown", view_func=self._shutdown_server)
        except AssertionError:
            pass

        try:
            self.app.add_url_rule("/health", view_func=self._health_check)
        except AssertionError:
            pass

    def _health_check(self):
        """Health check endpoint for server readiness"""
        return {"status": "ok"}, 200

    def _shutdown_server(self):
        if "werkzeug.server.shutdown" not in request.environ:
            raise RuntimeError("Error shutting down server")
        request.environ["werkzeug.server.shutdown"]()
        return "Shutting down"

    def shutdown_server(self):
        requests.get("http://localhost:%s/shutdown" % self.port)
        self.join()

    def wait_until_ready(self, timeout=10):
        """Wait for the server to be ready to accept connections

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            bool: True if server is ready, False if timeout
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(f"{self.url}/health", timeout=1)
                if response.status_code == 200:
                    return True
            except (requests.ConnectionError, requests.Timeout):
                # Server not ready yet, wait a bit
                time.sleep(0.1)
        return False

    def run(self):
        self.app.run(port=self.port)
