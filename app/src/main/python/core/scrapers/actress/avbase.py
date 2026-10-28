"""avbase.net actress profile scraper.

公開女優頁 `https://www.avbase.net/talents/<name>`，資料在 `__NEXT_DATA__` JSON 裡。
一般 `requests` 對該站會得 403，所以用 `curl_cffi`（偽 Chrome TLS 指紋）。

契約：`scrape_avbase(name)` 成功回 dict、查無或任何失敗回 `None`，永不丟例外。
純函式（`_normalize_basic_info`／`_extract_talent`／`_build_result`）不連網，可獨立測試。
"""

import importlib.metadata
import json
import re
import unicodedata
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from core.logger import get_logger
from core.proxy_policy import proxy_kwargs


logger = get_logger(__name__)

_BASE_URL = "https://www.avbase.net/talents/"
_TIMEOUT_S = 5
_FIRST_INT_RE = re.compile(r"\d+")
_CUP_RE = re.compile(r"[A-Z]{1,2}")
_BIRTH_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_SIZE_KEYS = ("height", "bust", "waist", "hip")


def _text(value) -> str:
    """字串去空白；數字轉字串；其餘（None、list、dict…）當空。"""
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    return ""


def _nfkc(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def _cm(value) -> str:
    """第一段數字、小數點以下捨去、須 > 0；輸出 `<n>cm`，否則空字串。"""
    match = _FIRST_INT_RE.search(_text(value))
    if not match:
        return ""
    number = int(match.group())
    return f"{number}cm" if number > 0 else ""


def _birth(value) -> str:
    """必須是完整且合法的 YYYY-MM-DD，否則空字串。"""
    text = _text(value)
    if not _BIRTH_RE.fullmatch(text):
        return ""
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return ""
    return text


def _cup(value) -> str:
    text = _text(value)
    return text if _CUP_RE.fullmatch(text) else ""


def _normalize_basic_info(basic_info) -> Dict[str, str]:
    """avbase `basic_info` → orchestrator 認得的鍵；只回有值的鍵。"""
    if not isinstance(basic_info, dict):
        return {}
    fields = {
        "birth": _birth(basic_info.get("birthday")),
        "cup": _cup(basic_info.get("cup")),
        "hometown": _text(basic_info.get("prefectures")),
        "hobby": _text(basic_info.get("hobby")),
    }
    for key in _SIZE_KEYS:
        fields[key] = _cm(basic_info.get(key))
    return {key: value for key, value in fields.items() if value}


def _extract_talent(html: str) -> Optional[dict]:
    """取 `props.pageProps.talent`；找不到、JSON 壞或缺任何一層 → None（warning）。"""
    try:
        tag = BeautifulSoup(html, "html.parser").find("script", id="__NEXT_DATA__")
        data = json.loads(tag.get_text()) if tag is not None else None
        talent = data["props"]["pageProps"]["talent"]
    except (ValueError, KeyError, TypeError):
        talent = None
    if not isinstance(talent, dict):
        logger.warning("[avbase] __NEXT_DATA__ talent not found (site changed or blocked?)")
        return None
    return talent


def _all_names(talent: dict) -> List[str]:
    """`actors[].name` 在前，`primary.name` 不在其中才附加；去空白與空字串、保序、去重。"""
    raw: List = []
    actors = talent.get("actors")
    if isinstance(actors, list):
        raw.extend(a.get("name") for a in actors if isinstance(a, dict))
    primary = talent.get("primary")
    if isinstance(primary, dict):
        raw.append(primary.get("name"))
    names: List[str] = []
    for item in raw:
        text = item.strip() if isinstance(item, str) else ""
        if text and text not in names:
            names.append(text)
    return names


def _name_matches(names: List[str], name: str) -> bool:
    known = {_nfkc(n) for n in names}
    return _nfkc(name) in known


def _build_result(talent: dict, name: str) -> Optional[dict]:
    """名字比對＋空頁判定＋欄位映射。查無或空殼 → None；只有別名也算查到。"""
    names = _all_names(talent)
    if not _name_matches(names, name):
        return None
    meta = talent.get("meta")
    basic = meta.get("basic_info") if isinstance(meta, dict) else None
    fields = _normalize_basic_info(basic)
    # 空頁判定不把 @ 開頭的社群帳號當別名（輸出的 other_names 仍不過濾，CD-174-1）
    others = [n for n in names if _nfkc(n) != _nfkc(name) and not _nfkc(n).startswith("@")]
    if not any(fields.values()) and not others:
        return None
    result: dict = dict(fields)
    result["other_names"] = names
    return result


def _handle_response(resp, name: str) -> Optional[dict]:
    if resp.status_code == 404:
        logger.debug("[avbase] %s: 404 (not found)", name)
        return None
    if resp.status_code != 200:
        logger.warning("[avbase] %s: HTTP %s", name, resp.status_code)
        return None
    talent = _extract_talent(resp.text)
    return _build_result(talent, name) if talent is not None else None


def _request_kwargs(url: str) -> dict:
    """給 `session.get()` 的代理參數，對齊 javdb.py 既有前例（重用其函式，不複製）。

    設定頁選中女優連線就用它；否則退回系統代理——curl_cffi 只讀環境變數、
    不讀 Windows 註冊表，與 requests 路徑不同，沒補就會在 Clash 系統代理下直連。
    """
    from core.scrapers.javdb import _resolve_proxies

    configured = proxy_kwargs('actress')
    proxies = configured.get('proxies') or _resolve_proxies(url)
    return {'proxies': proxies} if proxies else {}


def _session_kwargs() -> dict:
    """給 `Session(...)` 建構子的參數。CAINFO 屬於建構子（`Session.get()` 不收 curl_options）：
    Windows 非 ASCII 安裝路徑需把 certifi 路徑以 ACP bytes 交給 libcurl。"""
    from curl_cffi import CurlOpt
    from core.scrapers.javdb import _cainfo_override_bytes

    ca_bytes = _cainfo_override_bytes()
    return {'curl_options': {CurlOpt.CAINFO: ca_bytes}} if ca_bytes is not None else {}


def scrape_avbase(name: str) -> Optional[dict]:
    """Fetch one actress profile. Any failure → None (never raises)."""
    if not isinstance(name, str) or not name.strip():
        return None
    try:
        from curl_cffi import requests as cffi_requests
    except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
        logger.warning(
            "[avbase] curl_cffi unavailable, trying requests fallback: %s", exc
        )
        return _scrape_avbase_plain(name)

    url = _BASE_URL + quote(name, safe="")
    try:
        request_kw = _request_kwargs(url)
        with cffi_requests.Session(impersonate="chrome", **_session_kwargs()) as session:
            resp = session.get(url, timeout=_TIMEOUT_S, **request_kw)
            return _handle_response(resp, name)
    except Exception as exc:
        logger.warning("[avbase] request failed for %s: %s", name, type(exc).__name__)
        return None


def _scrape_avbase_plain(name: str) -> Optional[dict]:
    """Android fallback for environments without curl_cffi."""
    url = _BASE_URL + quote(name, safe="")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en;q=0.8,zh-TW;q=0.6",
    }
    proxies = proxy_kwargs("actress").get("proxies")
    session = requests.Session()
    try:
        resp = session.get(
            url,
            headers=headers,
            timeout=_TIMEOUT_S,
            **({"proxies": proxies} if proxies else {}),
        )
        # AVBase declares UTF-8 but some requests/urllib3 combinations guess a
        # legacy encoding when the response is proxied.  Keep the JSON names
        # comparable to the user-entered Japanese name.
        if resp.status_code == 200:
            resp.encoding = "utf-8"
        logger.debug(
            "[avbase] fallback response status=%s bytes=%s encoding=%s",
            resp.status_code,
            len(resp.content),
            resp.encoding,
        )
        return _handle_response(resp, name)
    except Exception as exc:
        logger.warning(
            "[avbase] requests fallback failed for %s: %s",
            name,
            type(exc).__name__,
        )
        return None
    finally:
        session.close()
