from threading import Thread

import requests
from flask import request

from .trends_api_server_app import app


class MockApiServer(Thread):
    """Mock a live"""

    def __init__(self, port=5000):
        super().__init__()
        self.port = port
        self.app = app
        self.url = "http://localhost:%s" % self.port

        try:
            self.app.add_url_rule("/shutdown", view_func=self._shutdown_server)
        except AssertionError:
            pass

    def _shutdown_server(self):
        if "werkzeug.server.shutdown" not in request.environ:
            raise RuntimeError("Error shutting down server")
        request.environ["werkzeug.server.shutdown"]()
        return "Shutting down"

    def shutdown_server(self):
        requests.get("http://localhost:%s/shutdown" % self.port)
        self.join()

    def run(self):
        self.app.run(port=self.port)
