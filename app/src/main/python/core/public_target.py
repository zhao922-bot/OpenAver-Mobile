"""公網目標判準：只放行公網 http(s) 位址（fail-closed）。

自訂來源守衛與圖片代理共用同一份判斷；本模組不依賴 core.custom_source 或 core.image_host_policy。
"""

import ipaddress
import socket
from typing import NamedTuple, Optional
from urllib.parse import urlparse

from urllib3.util import parse_url

_BLOCKED_NAME_SUFFIXES = (".localhost", ".local", ".internal")

# Clash／Surge TUN fake-ip 預設網段（RFC 2544）：流量由代理轉送到真網站，不是區網；只放行這一段
_FAKE_IP_NET = ipaddress.ip_network("198.18.0.0/15")


class Violation(NamedTuple):
    """違規結果：reason 為固定代碼；detail 區分 bad_host 的兩種成因，其餘 None。不含使用者輸入。"""

    reason: str
    detail: Optional[str] = None


def resolve_host(host):
    """主機名 → 位址字串列表（去 %scope、去重、保序）；任何解析失敗回 []。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return []
    seen = []
    for info in infos:
        text = str(info[4][0]).split("%", 1)[0]
        if text not in seen:
            seen.append(text)
    return seen


def _is_public(addr):
    addr = getattr(addr, "ipv4_mapped", None) or addr
    if addr.version == 4 and addr in _FAKE_IP_NET:
        return True
    return addr.is_global and not addr.is_multicast


def _blocked_name(host):
    name = host.rstrip(".").lower()
    return name == "localhost" or name.endswith(_BLOCKED_NAME_SUFFIXES)


def _authority(url):
    rest = url.split("://", 1)[-1]
    for i, ch in enumerate(rest):
        if ch in "/?#":
            return rest[:i]
    return rest


def _connect_host_differs(url, host):
    """守衛判斷的 host 必須與 urllib3（requests 實際連線者）讀到的一致；解析例外視為不一致。"""
    try:
        other = parse_url(url).host
    except Exception:
        return True
    return (other or "").strip("[]").lower() != host.strip("[]").lower()


def check_public(url):
    """通過回 None；違規回 Violation（不 raise、不含 URL 任何部分）。"""
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        parsed.port  # noqa: B018 - 存取時才驗證範圍
    except (ValueError, AttributeError, TypeError):
        return Violation("bad_url")
    if scheme not in ("http", "https"):
        return Violation("bad_scheme")
    if not host:
        return Violation("bad_host", "missing_host")
    if not host.isascii():
        return Violation("non_ascii_host")
    if "\\" in _authority(url) or _connect_host_differs(url, host):
        return Violation("bad_authority")
    if _blocked_name(host):
        return Violation("bad_host", "blocked_name")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _is_public(literal):
            return Violation("non_public")
        return None
    resolved = resolve_host(host)
    if not resolved:
        return Violation("unresolvable")
    for text in resolved:
        try:
            addr = ipaddress.ip_address(text)
        except ValueError:
            return Violation("unresolvable")
        if not _is_public(addr):
            return Violation("non_public")
    return None
