from __future__ import annotations

import json
import socket
import sys
import time
import types
import urllib.error
import urllib.request

from fastapi import FastAPI
import pytest

import openaver_boot


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _stop_server() -> None:
    server = openaver_boot._server
    thread = openaver_boot._thread
    if server is not None:
        server.should_exit = True
    if thread is not None:
        thread.join(timeout=10)
    listener = openaver_boot._server_socket
    if listener is not None:
        listener.close()


def test_bind_server_socket_falls_back_when_preferred_port_is_busy():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        preferred = occupied.getsockname()[1]

        listener, actual = openaver_boot._bind_server_socket(
            "127.0.0.1", preferred
        )
        try:
            assert actual != preferred
            assert actual == listener.getsockname()[1]
            assert preferred < actual <= preferred + 20
        finally:
            listener.close()


def test_start_server_serves_mobile_health(monkeypatch, tmp_path):
    app = FastAPI()
    web_module = types.ModuleType("web")
    web_module.__path__ = []
    web_app_module = types.ModuleType("web.app")
    web_app_module.app = app
    monkeypatch.setitem(sys.modules, "web", web_module)
    monkeypatch.setitem(sys.modules, "web.app", web_app_module)

    port = openaver_boot.start_server(
        "127.0.0.1",
        0,
        str(tmp_path / "openaver_data"),
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + 10
        response_body = None
        while time.monotonic() < deadline:
            try:
                with opener.open(
                    f"http://127.0.0.1:{port}/api/mobile/health",
                    timeout=1,
                ) as response:
                    assert response.status == 200
                    response_body = json.loads(response.read().decode("utf-8"))
                    break
            except OSError:
                time.sleep(0.05)

        assert response_body is not None
        assert response_body["status"] == "ok"
        assert response_body["service"] == "OpenAver Mobile"
    finally:
        _stop_server()


def test_start_server_reuses_running_instance(monkeypatch, tmp_path):
    app = FastAPI()
    web_module = types.ModuleType("web")
    web_module.__path__ = []
    web_app_module = types.ModuleType("web.app")
    web_app_module.app = app
    monkeypatch.setitem(sys.modules, "web", web_module)
    monkeypatch.setitem(sys.modules, "web.app", web_app_module)

    first = openaver_boot.start_server(
        "127.0.0.1",
        0,
        str(tmp_path / "openaver_data"),
    )
    try:
        second = openaver_boot.start_server(
            "127.0.0.1",
            0,
            str(tmp_path / "openaver_data"),
        )
        assert second == first
    finally:
        _stop_server()


def test_loopback_routes_require_in_memory_token(monkeypatch, tmp_path):
    app = FastAPI()

    @app.get("/protected")
    def protected():
        return {"protected": True}

    web_module = types.ModuleType("web")
    web_module.__path__ = []
    web_app_module = types.ModuleType("web.app")
    web_app_module.app = app
    monkeypatch.setitem(sys.modules, "web", web_module)
    monkeypatch.setitem(sys.modules, "web.app", web_app_module)

    port = openaver_boot.start_server(
        "127.0.0.1",
        0,
        str(tmp_path / "openaver_data"),
    )
    token = openaver_boot.server_token()
    cookie_name = openaver_boot.auth_cookie_name()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    endpoint = f"http://127.0.0.1:{port}/protected"

    try:
        assert len(token) >= 32

        with pytest.raises(urllib.error.HTTPError) as denied:
            opener.open(endpoint, timeout=2)
        assert denied.value.code == 403

        invalid = urllib.request.Request(
            endpoint,
            headers={"Authorization": "Bearer invalid-token"},
        )
        with pytest.raises(urllib.error.HTTPError) as denied:
            opener.open(invalid, timeout=2)
        assert denied.value.code == 403

        query_token = f"{endpoint}?openaver_loopback={token}"
        with pytest.raises(urllib.error.HTTPError) as denied:
            opener.open(query_token, timeout=2)
        assert denied.value.code == 403

        bearer = urllib.request.Request(
            endpoint,
            headers={"Authorization": f"Bearer {token}"},
        )
        with opener.open(bearer, timeout=2) as response:
            assert response.status == 200
            assert json.loads(response.read().decode("utf-8")) == {"protected": True}

        cookie = urllib.request.Request(
            endpoint,
            headers={"Cookie": f"{cookie_name}={token}"},
        )
        with opener.open(cookie, timeout=2) as response:
            assert response.status == 200
            assert json.loads(response.read().decode("utf-8")) == {"protected": True}
    finally:
        _stop_server()
