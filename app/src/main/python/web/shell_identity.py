"""請求所屬殼的身分 key（TASK-168d-T2 / CD-168d-4）。"""
from __future__ import annotations

import hashlib

from fastapi import Request

from core.access_auth import snapshot


def shell_key(request: Request) -> str | None:
    """① 帶 `sid` cookie 或 Bearer → `t:<sha256(ticket)[:16]>`；② 否則本機 → `loopback`；
    ③ 否則 `ip:<host>`；沒有 client 且無票據 → None。

    只看「有沒有帶」，**不驗票據**（驗證是 access_gate 的事）；key 不入 log。
    **PIN 關閉時一律忽略 sid／Bearer**（走 ②③）：關 PIN 會撤銷全部票，殼端 client.json 的舊 token
    已失效、頁面 `?oa_token=` 驗票失敗不種 sid → 頁面端是 ②③，殼端若仍走 ① 兩邊 key 永遠對不上。
    PIN 狀態讀 `snapshot()`（零 I/O，async middleware 內可直接呼叫）；冷快取（None）視同
    PIN 開啟＝看票（與 access_gate 冷載前 fail-closed 的方向一致）。
    """
    from web.app import _bearer_token, _is_loopback_host  # noqa: PLC2701 — 延遲 import 避免循環，同 web/routers/client.py 先例

    snap = snapshot()
    pin_off = snap is not None and not snap.enabled
    ticket = None if pin_off else (request.cookies.get("sid") or _bearer_token(request))
    if ticket:
        return "t:" + hashlib.sha256(ticket.encode("utf-8")).hexdigest()[:16]
    host = request.client.host if request.client else None
    if not host:
        return None
    if _is_loopback_host(host):
        return "loopback"
    return "ip:" + host


def cf_availability_here(request: Request) -> dict:
    """這個請求所屬的殼，CF 來源現在可不可用（SSR 與 `/api/cf/availability` 共用的唯一規則，168d-fix-T2 CD-3）。

    回 `{available, sites, preparing}`：
    - available：`cf_available_here()` 且〔key 為 loopback 或請求自稱桌面殼（oa_shell）〕——同機 localhost
      瀏覽器與本機殼同為 loopback key 不要求 oa_shell；非 loopback 才用 oa_shell 區分同 IP 的殼與區網瀏覽器。
    - sites：`get_cf_available_sites()`，可為 None（transport 判不出，前端 fail-open）；不可用時 `[]`。
    - preparing：殼回報還在準備的站；不可用時一律 `[]`。
    純記憶體讀取，不派工給殼（不得呼叫 is_ready／submit）。
    """
    from core import cf_handoff
    from core.cf_transport import cf_available_here, get_cf_available_sites

    key = cf_handoff.current_key.get()
    available = bool(
        cf_available_here()
        and (key == "loopback" or getattr(request.state, "shell_kind", None) is not None)
    )
    if not available:
        return {"available": False, "sites": [], "preparing": []}
    return {
        "available": True,
        "sites": get_cf_available_sites(),
        "preparing": cf_handoff.get_broker().preparing_for(key),
    }
