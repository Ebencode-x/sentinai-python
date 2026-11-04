import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sentinai.config import build_config
from sentinai.sender import Sender


class FakeIngest:
    """A real HTTP server in a thread. responses is a list of (status, headers), in order."""

    def __init__(self, responses=None, delay=0.0):
        self.responses = list(responses or [])
        self.delay = delay
        self.requests = []
        self.seen = threading.Event()
        self._lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                with owner._lock:
                    owner.requests.append(
                        {
                            "path": self.path,
                            "auth": self.headers.get("Authorization"),
                            "body": body,
                        }
                    )
                    status, headers = owner.responses.pop(0) if owner.responses else (202, {})
                owner.seen.set()
                if owner.delay:
                    time.sleep(owner.delay)
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self._server.server_port}"

    def events(self):
        return [event for request in self.requests for event in request["body"]["events"]]

    def stop(self):
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def ingest():
    servers = []

    def make(responses=None, delay=0.0):
        server = FakeIngest(responses, delay)
        servers.append(server)
        return server

    yield make
    for server in servers:
        server.stop()


@pytest.fixture
def make_config():
    def make(server):
        return build_config(url=server.url, key="snl_testkey", env={})

    return make


@pytest.fixture
def make_sender():
    senders = []

    def make(config, **options):
        options.setdefault("retry_delays", (0.01, 0.01))
        options.setdefault("batch_wait", 5.0)
        sender = Sender(config, **options)
        senders.append(sender)
        return sender

    yield make
    for sender in senders:
        sender.close(0.5)
