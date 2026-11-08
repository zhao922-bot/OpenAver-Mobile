from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core.proxy_policy import ProxySettings, new_session


class _Server(ThreadingHTTPServer):
    daemon_threads = True


def _serve(responses: list[int], retry_after: str):
    class Handler(BaseHTTPRequestHandler):
        request_count = 0

        def do_GET(self):
            Handler.request_count += 1
            index = min(Handler.request_count - 1, len(responses) - 1)
            status = responses[index]
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.send_header("Retry-After", retry_after)
            self.end_headers()

        def log_message(self, format, *args):
            pass

    server = _Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, Handler


def _get(responses: list[int], *, retry_after: str = "0"):
    server, thread, handler = _serve(responses, retry_after)
    try:
        session = new_session(None, settings=ProxySettings())
        session.trust_env = False
        response = session.get(
            f"http://127.0.0.1:{server.server_port}/probe",
            timeout=3,
        )
        return response.status_code, handler.request_count
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_retry_policy_does_not_retry_404():
    status, requests = _get([404])

    assert status == 404
    assert requests == 1


def test_retry_policy_stops_after_two_status_retries():
    status, requests = _get([503])

    assert status == 503
    assert requests == 3


def test_retry_policy_honors_retry_after_and_recovers():
    status, requests = _get([429, 200])

    assert status == 200
    assert requests == 2


def test_retry_policy_caps_retry_after(monkeypatch):
    sleeps: list[int] = []
    monkeypatch.setattr("urllib3.util.retry.time.sleep", sleeps.append)

    status, requests = _get([429, 200], retry_after="3600")

    assert status == 200
    assert requests == 2
    assert sleeps == [15]
