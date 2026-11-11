"""Android 內嵌 WebView 的 CF transport 工作端點。

Python 程序持有 job broker；Android 原生端長輪詢此端點，使用 WebView
完成 Cloudflare 驗證與頁面抓取。端點只接受 loopback 上的內嵌工作端。
"""
from __future__ import annotations

import asyncio
from typing import Literal, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, StrictBool

from core import cf_handoff
from core.loopback import is_loopback_host
from web.shell_identity import shell_key

router = APIRouter(prefix="/api/cf/mobile", tags=["cf_mobile"])

_POLL_INTERVAL_S = 0.25


def _reject_browser_request(request: Request) -> None:
    if "origin" in request.headers or "sec-fetch-site" in request.headers:
        raise HTTPException(status_code=403, detail="Forbidden")


def _require_key(request: Request) -> str:
    host = request.client.host if request.client else None
    if not is_loopback_host(host):
        raise HTTPException(status_code=403, detail="Forbidden")
    key = shell_key(request)
    if key is None:
        raise HTTPException(status_code=403, detail="Forbidden")
    return key


class PollBody(BaseModel):
    sites: list[str] = Field(default_factory=list)
    preparing: list[str] = Field(default_factory=list)
    hold: int = Field(0, ge=0, le=20)


class ResultBody(BaseModel):
    id: str
    ok: bool
    value: Optional[Union[StrictBool, str]] = None
    error: Optional[Literal["challenge", "unavailable", "timeout", "error"]] = None
    message: str = ""


@router.post("/poll", dependencies=[Depends(_reject_browser_request)])
async def poll(body: PollBody, request: Request) -> dict:
    key = _require_key(request)
    broker = cf_handoff.get_broker()
    sites = [s for s in body.sites if s in cf_handoff.CF_SITE_ORIGINS]
    preparing = [s for s in body.preparing if s in cf_handoff.CF_SITE_ORIGINS]
    broker.register_shell(
        key,
        sites,
        applied_proxy=None,
        shell="mobile",
        server_remote=False,
        preparing=preparing,
    )
    if body.hold <= 0:
        return {"ok": True, "job": None}

    loop = asyncio.get_running_loop()
    deadline = loop.time() + body.hold
    while True:
        job = broker.claim(key)
        if job is not None:
            return {"ok": True, "job": job}
        if loop.time() >= deadline or await request.is_disconnected():
            return {"ok": True, "job": None}
        await asyncio.sleep(_POLL_INTERVAL_S)


@router.post("/result", dependencies=[Depends(_reject_browser_request)])
async def result(body: ResultBody, request: Request) -> dict:
    key = _require_key(request)
    accepted = cf_handoff.get_broker().complete(
        key,
        body.id,
        body.ok,
        value=body.value,
        error=body.error,
        message=body.message,
    )
    return {"ok": True, "accepted": accepted}
