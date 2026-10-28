"""續頁 token 的編解碼（CD-175d-8）。純函式、零 I/O。

token＝base64url(JSON {"p": provider_id, "k": "entity"|"keyword"|"maker", "r": [[kind, id, pos], …]})，長度 ≤ 512。
前端只存、只送、不解析；伺服器零記憶——續頁所需的一切都在 token 裡。

decode 的契約：任何不合格（亂碼、字元集外、型別錯、p 未註冊、kind／id／pos 不合法、k 與 r 的組合不對、超長）
一律回 None，**絕不拋例外**——呼叫端把 None 當「沒有更多」（空結果、零 provider 呼叫）。
「p 已註冊」在呼叫當下讀 registry（不快取）。
頂層只准 stdlib 與 core.search_providers.*（BE-PY-08）。
"""

from __future__ import annotations

import base64
import json
import re
from typing import NamedTuple

from core.search_providers import registry

MAX_LEN = 512
MAX_REFS = 4
KIND_ENTITY = "entity"
KIND_KEYWORD = "keyword"
KIND_MAKER = "maker"
_TOKEN_KINDS = (KIND_ENTITY, KIND_KEYWORD, KIND_MAKER)
_ENTITY_KINDS = ("actor", "series", "director", "label")  # 只准這四個；不能靠 Kind(value)（會放行 maker／code）
_ID_RE = re.compile(r"^[A-Za-z0-9_\-/]{1,48}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-=]+$")  # urlsafe_b64decode 會默默丟掉字母表外的字元，所以先擋


class Token(NamedTuple):
    """p＝回答的 provider id；k＝token 種類；refs＝((kind, id, pos), …)，只有 k=entity 非空。pos 為 -1 ＝ 該代號已耗盡。"""

    p: str
    k: str
    refs: tuple[tuple[str, str, int], ...] = ()


def encode(token: Token) -> str:
    body: dict = {"p": token.p, "k": token.k}
    if token.refs:
        body["r"] = [list(ref) for ref in token.refs]
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _valid_ref(item) -> tuple[str, str, int] | None:
    if not isinstance(item, list) or len(item) != 3:
        return None
    kind, rid, pos = item
    if not (isinstance(kind, str) and kind in _ENTITY_KINDS):
        return None
    if not (isinstance(rid, str) and _ID_RE.fullmatch(rid)):
        return None
    if type(pos) is not int or pos < -1:  # type(...) is int：擋 True／False（bool 是 int 的子類）與浮點
        return None
    return kind, rid, pos


def _valid_refs(k: str, r) -> tuple[tuple[str, str, int], ...] | None:
    """r 已存在時必須是 list（含 null ⇒ 無效）；省略 r 由呼叫端以 [] 代入。"""
    if not isinstance(r, list):
        return None
    if k != KIND_ENTITY:
        return () if not r else None
    if not 1 <= len(r) <= MAX_REFS:
        return None
    refs = tuple(_valid_ref(item) for item in r)
    return None if None in refs else refs


def _decode(s) -> Token | None:
    if not isinstance(s, str) or not 0 < len(s) <= MAX_LEN or not _TOKEN_RE.fullmatch(s):
        return None
    body = json.loads(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode("utf-8"))
    if not isinstance(body, dict) or not set(body) <= {"p", "k", "r"}:
        return None
    p, k = body.get("p"), body.get("k")
    if not (isinstance(p, str) and p in registry.registered_ids()):
        return None
    if not (isinstance(k, str) and k in _TOKEN_KINDS):
        return None
    refs = _valid_refs(k, body["r"] if "r" in body else [])
    return None if refs is None else Token(p, k, refs)


def decode(s) -> Token | None:
    """合法 ⇒ Token；其餘（含任何例外）⇒ None。"""
    try:
        return _decode(s)
    except Exception:  # 契約：decode 不得拋例外（binascii／Unicode／JSON／Recursion 皆為 Exception 子類）
        return None
