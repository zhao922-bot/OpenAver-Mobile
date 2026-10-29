"""OpenAver Android embedded server bootstrap."""

from __future__ import annotations

import os
import socket
import sys
import threading
import traceback

import uvicorn


_server = None
_thread = None
_server_socket = None
_server_port = 0
_server_error = ""
_startup_status = "python_loaded"


def is_server_alive() -> bool:
    return _thread is not None and _thread.is_alive()


def server_error() -> str:
    return _server_error


def server_port() -> int:
    return _server_port


def set_startup_status(status: str) -> None:
    global _startup_status
    _startup_status = status


def startup_status() -> str:
    return _startup_status


def server_stack() -> str:
    if _thread is None or _thread.ident is None:
        return "server thread is not running"
    frame = sys._current_frames().get(_thread.ident)
    if frame is None:
        return "server thread stack is unavailable"
    return "".join(traceback.format_stack(frame, limit=8))


def _bind_server_socket(host: str, preferred_port: int):
    """Bind before Uvicorn starts so a busy port is a normal retry, not exit(1)."""
    last_error = None
    for port in range(preferred_port, preferred_port + 21):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((host, port))
            listener.listen(128)
            listener.setblocking(False)
            return listener, port
        except OSError as exc:
            last_error = exc
            listener.close()
    if last_error is None:
        raise OSError("no local port was available")
    raise OSError(
        f"no free loopback port in {preferred_port}-{preferred_port + 20}: "
        f"{last_error}"
    ) from last_error


def _run_server(listener) -> None:
    global _server_error
    try:
        set_startup_status("uvicorn_running")
        _server.run(sockets=[listener])
    except BaseException as exc:
        _server_error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"


def start_server(
    host: str,
    port: int,
    data_dir: str,
    native_lib_path: str = "",
    cascade_path: str = "",
) -> int:
    global _server, _thread, _server_socket, _server_port, _server_error
    if _server is not None and _thread is not None and _thread.is_alive():
        return _server_port or port

    os.makedirs(data_dir, exist_ok=True)
    runtime_home = os.path.join(os.path.dirname(data_dir), "openaver_home")
    os.makedirs(runtime_home, exist_ok=True)
    os.environ["OPENAVER_DATA_DIR"] = data_dir
    os.environ["HOME"] = runtime_home
    os.environ["OPENAVER_MOBILE"] = "1"
    if native_lib_path:
        os.environ["OPENAVER_NATIVE_LIB"] = native_lib_path
    if cascade_path:
        os.environ["OPENAVER_CASCADE_PATH"] = cascade_path
    os.environ["OPENAVER_FOCAL_NATIVE"] = "1"
    os.environ.pop("OPENAVER_STANDALONE", None)

    from pydantic_v1_compat import install as install_pydantic_v1_compat

    install_pydantic_v1_compat()

    from fastapi.responses import JSONResponse
    from core.version import VERSION
    from web.app import app


    def _native_focal_status():
        try:
            from core.focal.detector import native_focal_status

            return native_focal_status()
        except Exception:
            return "unavailable"

    set_startup_status("app_imported")

    @app.get("/api/mobile/health")
    def mobile_health():
        return JSONResponse(
            {
                "status": "ok",
                "service": "OpenAver Mobile",
                "version": VERSION,
                "data_dir": data_dir,
                "native_focal": _native_focal_status(),
            }
        )

    listener, actual_port = _bind_server_socket(host, port)
    _server_socket = listener
    _server_port = actual_port
    _server_error = ""

    config = uvicorn.Config(
        app,
        host=host,
        port=actual_port,
        log_level="info",
        access_log=False,
        lifespan="on",
    )
    _server = uvicorn.Server(config)
    _server.install_signal_handlers = lambda: None
    _thread = threading.Thread(
        target=_run_server,
        args=(listener,),
        name="openaver-uvicorn",
        daemon=True,
    )
    _thread.start()
    return actual_port





