"""桌面殼領 CF 工作的端點（TASK-168d-T2 / CD-168d-3、4）。

殼（Windows／Mac 桌面 client 或本機殼）背景呼叫：
  POST /api/cf/shell/poll   登記／刷新殼，並（hold>0 時）長輪詢領取屬於自己的工作
  POST /api/cf/shell/result 回報工作結果

殼內部管線，**不對外揭露**（同 CD-168b-1 先例）。身分一律由 `shell_key(request)`
推出；只看「有沒有帶」票據，不驗票據（閘門是 access_gate 的事）。
"""
from __future__ import annotations

import asyncio
from typing import Literal, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, StrictBool

from core import cf_handoff
from web.shell_identity import shell_key

router = APIRouter(prefix="/api/cf/shell", tags=["cf_shell"])

# 輪詢間隔：呼叫時才解析（模組屬性），測試可縮短（BE-TEST-01/18/38/39）。
_POLL_INTERVAL_S = 0.25


def _reject_browser_request(request: Request) -> None:
    """殼的 httpx 不帶 Origin／Sec-Fetch-Site，瀏覽器一定帶 ⇒ 帶了就是網頁在冒充殼（CD-168d-4）。"""
    if "origin" in request.headers or "sec-fetch-site" in request.headers:
        raise HTTPException(status_code=403, detail="Forbidden")


def _require_key(request: Request) -> str:
    key = shell_key(request)
    if key is None:
        raise HTTPException(status_code=403, detail="Forbidden")
    return key


class PollBody(BaseModel):
    shell: Literal["windows", "mac"] = "windows"
    sites: list[str] = Field(default_factory=list)
    applied_proxy: Optional[str] = None
    server_remote: bool = False
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
    """登記／刷新殼；hold=0 只登記（job 恆 null），hold>0 才輪詢領工作。

    async body 內只有記憶體操作、`asyncio.sleep`、`request.is_disconnected()`（BE-ASYNC-01）。
    """
    key = _require_key(request)
    broker = cf_handoff.get_broker()  # 請求當下解析，不在 module level 綁定
    sites = [s for s in body.sites if s in cf_handoff.CF_SITE_ORIGINS]
    preparing = [s for s in body.preparing if s in cf_handoff.CF_SITE_ORIGINS]
    broker.register_shell(key, sites, body.applied_proxy, body.shell, body.server_remote, preparing=preparing)
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
        key, body.id, body.ok, value=body.value, error=body.error, message=body.message,
    )
    return {"ok": True, "accepted": accepted}
