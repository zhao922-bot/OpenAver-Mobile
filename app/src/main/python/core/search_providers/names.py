"""片商名稱展開（175c-T3；自 javdb.py 的 `_maker_names` 搬入，行為逐字相同）。

頂層只依賴 core.maker_mapping／core.maker_names（BE-PY-08：不得在頂層碰 core.scraper／core.database）。
"""

from __future__ import annotations

from core.maker_mapping import load_name_mapping, load_search_aliases
from core.maker_names import maker_key_of

_MAKER_MAX_NAMES = 4


def maker_names(q: str, *, name_mapping: dict | None = None, search_aliases: dict | None = None) -> list[str]:
    """候選名集合 S：[輸入、正名、該正名底下全部別名]，以 maker_key_of 去重保序，最多 4 個。

    對照表預設自己載入；呼叫端（javdb 的薄包裝）可傳入以保留既有測試對 `javdb.load_*` 的 patch 點。
    """
    if name_mapping is None:
        name_mapping = load_name_mapping()
    if search_aliases is None:
        search_aliases = load_search_aliases()
    canon_of: dict[str, str] = {}
    members: dict[str, list[str]] = {}
    for table in (name_mapping, search_aliases):
        for alias, canon in table.items():
            canon_of[maker_key_of(alias)] = canon
            members.setdefault(maker_key_of(canon), []).append(alias)
    canon = canon_of.get(maker_key_of(q), q)
    out: list[str] = []
    seen: set[str] = set()
    for n in (q, canon, *members.get(maker_key_of(canon), [])):
        k = maker_key_of(n)
        if k and k not in seen:
            seen.add(k)
            out.append(n)
    return out[:_MAKER_MAX_NAMES]
