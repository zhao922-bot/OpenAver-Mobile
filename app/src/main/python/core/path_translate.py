"""client 模式路徑對照表換算（feature/168a T1b，純函式模組）。

伺服器路徑 <-> 這台電腦的本機路徑，依使用者設定的對照表（PathMap）換算。

設計約束：
- 純字串、無 I/O；不 import web／webview／core.database，也不依當前環境。
- 對不到任何規則回 Uncovered，絕不回原字串（否則伺服器路徑會被當本機路徑開出去）。
- 只收純路徑；URI 剝離不在這層。
"""
import re
from dataclasses import dataclass
from typing import Union

from core.logger import get_logger

logger = get_logger(__name__)

_DRIVE_RE = re.compile(r"^[A-Za-z]:(/|$)")


@dataclass(frozen=True)
class Mapped:
    path: str
    rule_index: int


@dataclass(frozen=True)
class Uncovered:
    pass


Translation = Union[Mapped, Uncovered]


@dataclass(frozen=True)
class PathMap:
    rules: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_rules(cls, rules) -> "PathMap":
        kept = []
        for raw in rules or ():
            server = raw.get("server") if isinstance(raw, dict) else None
            local = raw.get("local") if isinstance(raw, dict) else None
            if isinstance(local, str):
                local = strip_wrapping_quotes(local)
            if isinstance(server, str) and isinstance(local, str) and server and local:
                kept.append((server, local))
            else:
                logger.warning("path_translate: skip incomplete rule %r", raw)
        return cls(rules=tuple(kept))


def strip_wrapping_quotes(value):
    """去頭尾空白；頭尾為成對的雙引號就去掉那一對（Win11「複製為路徑」會帶引號）。"""
    s = value.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].strip()
    return s


def _norm(value: str) -> str:
    """收斂成比對形：正斜線、去尾分隔符。"""
    return value.replace("\\", "/").rstrip("/")


def _is_windows_style(norm: str) -> bool:
    """比對形是否為 Windows 風格（磁碟機 X: 或 UNC //）。"""
    return bool(_DRIVE_RE.match(norm)) or norm.startswith("//")


def _match_tail(value_n: str, prefix_n: str):
    """命中回前綴之後的剩餘（可為空字串），否則 None。"""
    fold = _is_windows_style(prefix_n)
    head = value_n[: len(prefix_n)]
    same = head.casefold() == prefix_n.casefold() if fold else head == prefix_n
    if not same:
        return None
    tail = value_n[len(prefix_n):]
    if tail and not tail.startswith("/"):
        return None
    return tail


def _build(dest: str, tail: str) -> str:
    """目的前綴（去尾分隔符）＋剩餘；分隔符依目的前綴風格。"""
    dest_n = _norm(dest)
    out = dest_n + tail
    if _is_windows_style(dest_n):
        out = out.replace("/", "\\")
        if _DRIVE_RE.match(out) and len(out) == 2:
            out += "\\"
    elif not out:
        out = "/"
    return out


def _translate(value, pmap: PathMap, src: int, dst: int) -> Translation:
    pairs = enumerate(pmap.rules) if isinstance(value, str) and value else ()
    value_n = _norm(value) if isinstance(value, str) else ""
    best = None
    best_len = -1
    for index, rule in pairs:
        prefix_n = _norm(rule[src])
        tail = _match_tail(value_n, prefix_n)
        if tail is None:
            continue
        if best is None or len(prefix_n) > best_len:
            best = Mapped(_build(rule[dst], tail), index)
            best_len = len(prefix_n)
    if best is not None:
        return best
    return Uncovered()


def to_local(value: str, pmap: PathMap) -> Translation:
    """伺服器路徑 -> 本機路徑。"""
    return _translate(value, pmap, 0, 1)


def to_server(value: str, pmap: PathMap) -> Translation:
    """本機路徑 -> 伺服器路徑。"""
    return _translate(value, pmap, 1, 0)
