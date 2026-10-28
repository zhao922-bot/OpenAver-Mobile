"""core/client_connect.py — 桌面殼「連線頁」的遠端 I/O（握手探測／登入／來源／相容判定）。

httpx 同步、純 Python；不 import web／windows／webview。
token 只回呼叫端；log 只寫 ``token=<set>``／``<none>``，PIN 不進 log。
"""
import re
import ssl
from typing import NamedTuple, Optional

import httpx

from core import client_settings
from core.logger import get_logger
from core.proxy_policy import settings_from_config
from core.version import VERSION as LOCAL_VERSION
from core.video_extensions import normalize_extensions

logger = get_logger(__name__)

_VERSION_RE = re.compile(r"^\s*(\d+)\.(\d+)\.(\d+)")
_CONNECTABLE = ("ok", "patch_diff")


class Compat(NamedTuple):
    status: str
    hint: str


class Preflight(NamedTuple):
    status: str
    reason: Optional[str]
    probe: dict


def _new_client(transport=None, timeout=3.0) -> httpx.Client:
    # trust_env=False：主機在區網，系統／環境代理對它沒有意義（168e CD-1）
    return httpx.Client(timeout=httpx.Timeout(timeout), transport=transport, trust_env=False)


def _parse_version(v):
    m = _VERSION_RE.match(v) if isinstance(v, str) else None
    return tuple(int(x) for x in m.groups()) if m else None


def check_compat(local: str, server: str) -> Compat:
    lv, sv = _parse_version(local), _parse_version(server)
    if lv is None or sv is None:
        return Compat("unparseable", "")
    if sv[:2] != lv[:2]:
        return Compat("server_old", "upgrade_server") if sv[:2] < lv[:2] else Compat("client_old", "upgrade_client")
    if sv[:2] == lv[:2] and sv < client_settings.MIN_SERVER_VERSION:
        return Compat("server_old", "upgrade_server")
    if sv[2] != lv[2]:
        return Compat("patch_diff", "")
    return Compat("ok", "")


def is_connectable(compat: Compat) -> bool:
    return compat.status in _CONNECTABLE


def _origin(url):
    return client_settings.canonical_server_url(url)


def _exc_reason(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    cause = exc
    while cause is not None:
        if isinstance(cause, ssl.SSLError):
            return "tls"
        cause = cause.__cause__ or cause.__context__
    return "unreachable"


def _result(ok=False, reason=None, version="", kind="", auth_required=False, authed=False, compat=None) -> dict:
    return {"ok": ok, "reason": reason, "version": version, "kind": kind,
            "auth_required": auth_required, "authed": authed,
            "compat": compat or Compat("unparseable", "")}


def _json(resp):
    try:
        data = resp.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _legacy_health_version(client, origin):
    try:
        data = _json(client.get(f"{origin}/api/health"))
    except httpx.HTTPError:
        return None
    version = data.get("version") if data else None
    return version if _parse_version(version) else None


def probe(url, token=None) -> dict:
    origin = _origin(url)
    if origin is None:
        return _result(reason="unreachable")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    logger.debug(f"[client_connect] probe {origin} token={'<set>' if token else '<none>'}")
    with _new_client() as client:
        try:
            resp = client.get(f"{origin}/api/client/hello", headers=headers)
        except httpx.HTTPError as e:
            return _result(reason=_exc_reason(e))
        data = _json(resp)
        if resp.status_code == 403 and data is None:
            return _result(reason="lan_forbidden")
        if data is None or data.get("app") != "openaver":
            legacy = _legacy_health_version(client, origin)
            if legacy is None:
                return _result(reason="not_openaver")
            # 沒有 hello 端點＝一定是舊伺服器，不論 health 版本多少都固定提示升級伺服器
            return _result(version=legacy, compat=Compat("server_old", "upgrade_server"))
    version = str(data.get("version") or "")
    return _result(ok=True, version=version, kind=str(data.get("kind") or ""),
                   auth_required=bool(data.get("auth_required")), authed=bool(data.get("authed")),
                   compat=check_compat(LOCAL_VERSION, version))


def login(url, pin) -> dict:
    origin = _origin(url)
    if origin is None:
        return {"ok": False, "reason": "unreachable", "token": None}
    with _new_client() as client:
        try:
            resp = client.post(f"{origin}/api/client/token", json={"pin": pin})
        except httpx.HTTPError as e:
            return {"ok": False, "reason": _exc_reason(e), "token": None}
    data = _json(resp) or {}
    if resp.status_code == 200 and data.get("success"):
        logger.debug(f"[client_connect] login ok token={'<set>' if data.get('token') else '<none>'}")
        return {"ok": True, "reason": None, "token": data.get("token")}
    if resp.status_code == 403:
        return {"ok": False, "reason": "lan_forbidden", "token": None}
    return {"ok": False, "reason": str(data.get("reason") or "bad_pin"), "token": None}


def fetch_sources(url, token) -> dict:
    origin = _origin(url)
    if origin is None:
        return {"ok": False, "reason": "unreachable", "sources": []}
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with _new_client(timeout=10.0) as client:
        try:
            resp = client.get(f"{origin}/api/client/sources", headers=headers)
        except httpx.HTTPError as e:
            return {"ok": False, "reason": _exc_reason(e), "sources": []}
    data = _json(resp)
    if resp.status_code == 200 and data and data.get("success") and isinstance(data.get("sources"), list):
        return {"ok": True, "reason": None, "sources": data["sources"]}
    return {"ok": False, "reason": "unauthorized" if resp.status_code in (401, 403) else "bad_response",
            "sources": []}


def fetch_video_extensions(url, token) -> dict:
    """從伺服器 ``/api/config`` 抓副檔名清單；任何失敗 ``ok:False``，絕不回預設清單。

    空清單 ``[]`` 是合法回應（伺服器存空 ＝ 用預設），回 ``ok:True, extensions:[]``。
    """
    origin = _origin(url)
    if origin is None:
        return {"ok": False, "reason": "unreachable", "extensions": []}
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    logger.debug(f"[client_connect] fetch_video_extensions {origin} token={'<set>' if token else '<none>'}")
    with _new_client() as client:
        try:
            resp = client.get(f"{origin}/api/config", headers=headers)
        except httpx.HTTPError as e:
            return {"ok": False, "reason": _exc_reason(e), "extensions": []}
    if resp.status_code in (401, 403):
        return {"ok": False, "reason": "unauthorized", "extensions": []}
    data = _json(resp)
    inner = data.get("data") if data is not None and resp.status_code == 200 else None
    scraper = inner.get("scraper") if isinstance(inner, dict) else None
    exts = scraper.get("video_extensions") if isinstance(scraper, dict) else None
    if not isinstance(exts, list) or not all(isinstance(e, str) for e in exts):
        return {"ok": False, "reason": "bad_response", "extensions": []}
    return {"ok": True, "reason": None, "extensions": sorted(normalize_extensions(exts))}


def fetch_proxy_settings(url, token) -> dict:
    """從伺服器 ``/api/config`` 抓代理設定；任何失敗 ``ok:False``、``settings=None``，絕不回預設設定。"""
    origin = _origin(url)
    if origin is None:
        return {"ok": False, "reason": "unreachable", "settings": None}
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    logger.debug(f"[client_connect] fetch_proxy_settings {origin} token={'<set>' if token else '<none>'}")
    with _new_client() as client:
        try:
            resp = client.get(f"{origin}/api/config", headers=headers)
        except httpx.HTTPError as e:
            return {"ok": False, "reason": _exc_reason(e), "settings": None}
    if resp.status_code in (401, 403):
        return {"ok": False, "reason": "unauthorized", "settings": None}
    data = _json(resp)
    inner = data.get("data") if data is not None and resp.status_code == 200 else None
    if not isinstance(inner, dict):
        return {"ok": False, "reason": "bad_response", "settings": None}
    return {"ok": True, "reason": None, "settings": settings_from_config(inner)}


def preflight(url, token) -> Preflight:
    """啟動前檢查：至多一次 hello（帶 Bearer），不碰 token／sources 端點（I-B）。"""
    p = probe(url, token or None)
    reason = p["reason"]
    if reason in ("timeout", "tls", "unreachable"):
        return Preflight("offline", "unreachable", p)
    if reason == "lan_forbidden":
        return Preflight("offline", "lan_forbidden", p)
    if reason == "not_openaver" or not p["ok"] or not is_connectable(p["compat"]):
        return Preflight("offline", "incompatible", p)
    if p["auth_required"] and (not token or not p["authed"]):
        return Preflight("offline", "relogin", p)
    return Preflight("ok", None, p)
