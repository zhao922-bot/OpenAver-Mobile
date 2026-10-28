"""OpenAver Android embedded server bootstrap."""

from __future__ import annotations

import os
import threading

import uvicorn


_server = None
_thread = None


def start_server(host: str, port: int, data_dir: str) -> int:
    global _server, _thread
    if _server is not None and _thread is not None and _thread.is_alive():
        return port

    os.makedirs(data_dir, exist_ok=True)
    runtime_home = os.path.join(os.path.dirname(data_dir), "openaver_home")
    os.makedirs(runtime_home, exist_ok=True)
    os.environ["OPENAVER_DATA_DIR"] = data_dir
    os.environ["HOME"] = runtime_home
    os.environ["OPENAVER_MOBILE"] = "1"
    os.environ.pop("OPENAVER_STANDALONE", None)

    from pydantic_v1_compat import install as install_pydantic_v1_compat

    install_pydantic_v1_compat()

    from fastapi.responses import JSONResponse
    from core.version import VERSION
    from web.app import app

    @app.get("/api/mobile/health")
    def mobile_health():
        return JSONResponse(
            {
                "status": "ok",
                "service": "OpenAver Mobile",
                "version": VERSION,
                "data_dir": data_dir,
            }
        )

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
        lifespan="on",
    )
    _server = uvicorn.Server(config)
    _server.install_signal_handlers = lambda: None
    _thread = threading.Thread(
        target=_server.run,
        name="openaver-uvicorn",
        daemon=True,
    )
    _thread.start()
    return port
