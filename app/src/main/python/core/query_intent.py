"""查詢分類（175a-T6，CD-175a-2）：一個純函式決定 exact / maker / partial / prefix / actress。

頂層只准 stdlib、core.maker_mapping、core.scrapers.utils、core.logger、core.maker_names；
core.database、core.scraper 一律函式內延後取用（BE-PY-08）。
"""

import unicodedata
from typing import FrozenSet, NamedTuple

from core.maker_mapping import load_prefix_mapping
from core.maker_names import maker_key_of


class Intent(NamedTuple):
    mode: str
    maker_key: str = ""


def _is_other_makers_prefix(q: str, key: str) -> bool:
    """DOC 規則：q 同時是「別家片商」的番號前綴 → 不判片商。"""
    owner = load_prefix_mapping().get(unicodedata.normalize("NFKC", q).upper(), "")
    return owner != "" and maker_key_of(owner) != key


def classify_query(q: str, known_makers: FrozenSet[str] = frozenset(), resolve_makers: bool = False) -> Intent:
    """順序：完整番號 → 片商（僅 resolve_makers）→ 部分番號 → 番號前綴 → 其餘當女優。

    判斷函式在呼叫當下才讀 core.scraper 的模組屬性，讓既有 patch('core.scraper.is_*') 持續生效。
    """
    import core.scraper as _s

    if _s.is_number_format(_s.resolve_route_target(q)):
        return Intent("exact")
    key = maker_key_of(q)
    known_makers = known_makers - {""}  # 空 key（空白／BOM）永遠不是片商
    if resolve_makers and key in known_makers and not _is_other_makers_prefix(q, key):
        return Intent("maker", key)
    if _s.is_partial_number(q):
        return Intent("partial")
    if _s.is_prefix_only(q):
        return Intent("prefix")
    return Intent("actress")
