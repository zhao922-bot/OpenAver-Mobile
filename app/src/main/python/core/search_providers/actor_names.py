"""女優名稱組純函式（175d-T1）：別名展開、換名候選過濾、羅馬字判斷、唯讀載入別名組。

頂層只依賴 stdlib＋core.name_match＋core.logger（BE-PY-08：不得在頂層碰 core.database／core.scraper）。
每次呼叫都重讀別名，不做行程快取。
"""

from __future__ import annotations

import unicodedata

from core.logger import get_logger
from core.name_match import fold

logger = get_logger(__name__)

_MAX_NAMES = 4


def _dedup_cap(names: list) -> list[str]:
    """以 fold 去重保序（同組內 fold 相撞只留先出現者；fold 為空者略過），截斷到上限。"""
    out: list[str] = []
    seen: set[str] = set()
    for n in names:
        k = fold(n)
        if k and k not in seen:
            seen.add(k)
            out.append(n)
    return out[:_MAX_NAMES]


def expand_actor_names(q: str, groups: list[tuple[str, list[str]]]) -> list[str]:
    """q 命中某別名組（fold 比對正名與全部別名）⇒ 該組固定順序的名字（最多 4 個）；否則 [q]。

    不把 q 排第一：同一組不論從哪個名字進來，都得到同一個 list。
    """
    key = fold(q)
    if not key:
        return [q]
    for primary, aliases in groups:
        names = [primary, *aliases]
        if any(fold(n) == key for n in names):
            return _dedup_cap(names)
    return [q]


def needs_swap_first(q: str) -> bool:
    """q 是否為羅馬字（只含拉丁字母／數字／空白，且至少一個 ASCII 字母；先 NFKC）。"""
    t = unicodedata.normalize("NFKC", q if isinstance(q, str) else "")
    if not any(ch.isascii() and ch.isalpha() for ch in t):
        return False
    return all(ch.isascii() and (ch.isalnum() or ch.isspace()) for ch in t)


def swap_candidates(names_from_javdb, tried, limit: int = 3) -> list[str]:
    """換名候選過濾：丟掉與 tried 任一名 fold 相同者、候選間 fold 去重保序、最多 limit 個。"""
    skip = {fold(t) for t in tried if isinstance(t, str)}
    skip.discard("")
    out: list[str] = []
    for n in names_from_javdb:
        if not isinstance(n, str):
            continue
        k = fold(n)
        if not k or k in skip:
            continue
        skip.add(k)
        out.append(n)
    return out[:limit]


def load_alias_groups() -> list[tuple[str, list[str]]]:
    """唯讀載入本機女優別名組 [(primary, [aliases…])…]；檔不存在不建檔，任何例外 ⇒ warning＋[]。"""
    try:
        from core.database import connection
        from core.database.alias import AliasRepository

        db_path = connection.get_db_path()
        if not db_path.exists():
            return []
        return [(r.primary_name, list(r.aliases)) for r in AliasRepository(db_path).get_all()]
    except Exception as e:
        logger.warning("載入女優別名組失敗，退回無別名：%s", e)
        return []
