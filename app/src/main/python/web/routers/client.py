"""桌面 client 連線用端點（TASK-168b-T2 / CD-168b-1）。

`hello`、`token` 是握手端點（`web.app._CLIENT_HANDSHAKE_ALLOWLIST`，未登入可達，
只洩漏版本／種類／是否需要密碼）；`sources` 走一般閘門。不揭露進 capabilities。
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.access_auth import attempt_pin, ensure_schema, snapshot, verify_ticket
from core.client_sources import list_sources
from core.config import load_config
from core.logger import get_logger
from core.platform_info import server_kind
from core.version import VERSION
from web.routers import access as access_router

logger = get_logger(__name__)

router = APIRouter(prefix="/api/client", tags=["client"])

_BAD_PIN = {"success": False, "reason": "bad_pin"}


async def _auth_snapshot():
    """取認證快取；冷時照 access_gate 寫法 to_thread 載入（BE-ASYNC-01），失敗回 None。"""
    snap = snapshot()
    if snap is not None:
        return snap
    try:
        await asyncio.to_thread(ensure_schema)
    except Exception:
        logger.exception("client: cold-load ensure_schema() failed")
        return None
    return snapshot()


@router.get("/hello")
async def hello(request: Request) -> dict:
    from web.app import _bearer_token  # noqa: PLC2701 — 延遲 import 避免循環，與 access router 同先例

    snap = await _auth_snapshot()
    if snap is None:
        auth_required, authed = True, False
    elif not snap.enabled:
        auth_required, authed = False, True
    else:
        auth_required, authed = True, verify_ticket(_bearer_token(request))
    return {
        "success": True,
        "app": "openaver",
        "version": VERSION,
        "kind": server_kind(),
        "auth_required": auth_required,
        "authed": authed,
    }


@router.post("/token")
async def token(request: Request):
    await access_router._fixed_delay()

    snap = await _auth_snapshot()
    if snap is None:
        return JSONResponse(_BAD_PIN, status_code=401)
    if not snap.enabled:
        return {"success": True, "token": None, "auth_required": False}

    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "application/json":
        return JSONResponse(_BAD_PIN, status_code=401)
    try:
        data = await request.json()
    except Exception:
        data = None
    candidate = data.get("pin") if isinstance(data, dict) else None

    try:
        ticket = await asyncio.to_thread(attempt_pin, candidate)
    except Exception:
        logger.exception("client token: attempt_pin failed, fail-closed")
        ticket = None
    if ticket is None:
        return JSONResponse(_BAD_PIN, status_code=401)
    return {"success": True, "token": ticket}


@router.get("/sources")
def sources() -> dict:
    return {"success": True, "sources": list_sources(load_config())}
