"""片商名稱正規化與「認得的片商」清單（175a-T6）。

頂層只准 stdlib、core.maker_mapping、core.logger；core.database 一律函式內延後 import（BE-PY-08）。
"""

import unicodedata
from functools import lru_cache
from typing import FrozenSet, List, Set

from core.logger import get_logger
from core.maker_mapping import load_name_mapping, load_prefix_mapping, load_search_aliases

logger = get_logger(__name__)

# ECMAScript WhiteSpace + LineTerminator（與 JS String.prototype.trim 同集；不含 \x1c-\x1f、\x85）
_JS_WHITESPACE = " \t\n\v\f\r" + "".join(chr(c) for c in (
    0x00A0, 0x1680, *range(0x2000, 0x200B), 0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF,
))


def js_trim(text: str) -> str:
    """JS String.prototype.trim 語意（Python str.strip 的空白集不同）。"""
    return text.strip(_JS_WHITESPACE)


def maker_key_of(name) -> str:
    """片商比對鍵；與前端 makerKey()（trim → NFKC → toLowerCase）逐位元相同（BE-DATA-17）。"""
    if name is None:
        return ""
    return unicodedata.normalize("NFKC", js_trim(str(name))).lower()


def library_maker_names() -> Set[str]:
    """片庫現有的 distinct 片商名；讀不到片庫回空集合（只用來「認得」，不影響其他判斷）。"""
    try:
        # 延後 import：core.database 的 __init__ 會 import core.scraper（BE-PY-08）
        from core.database import VideoRepository
        return set(VideoRepository().get_distinct_makers())
    except Exception as e:
        logger.warning("maker_names: 無法讀取片庫片商名，略過（%s）", e)
        return set()


@lru_cache(maxsize=1)
def _static_keys() -> FrozenSet[str]:
    """對照表端（name_mapping 鍵值、prefix_mapping 值、search_aliases 鍵值）的正規化 key。"""
    names = set()
    nm = load_name_mapping()
    names.update(nm.keys())
    names.update(nm.values())
    names.update(load_prefix_mapping().values())
    sa = load_search_aliases()
    names.update(sa.keys())
    names.update(sa.values())
    return frozenset(k for k in (maker_key_of(n) for n in names) if k)


def known_makers() -> FrozenSet[str]:
    """認得的片商 key 集合（靜態半邊快取，片庫半邊每次讀）。"""
    lib = {k for k in (maker_key_of(n) for n in library_maker_names()) if k}
    return _static_keys() | frozenset(lib)


def maker_spellings(name) -> List[str]:
    """候選拼法：[輸入, 正名, 該正名底下全部別名]，以 maker_key_of 去重保序，不設上限（175b-T8c）。"""
    canon_of: dict = {}
    members: dict = {}
    for table in (load_name_mapping(), load_search_aliases()):
        for alias, canon in table.items():
            canon_of[maker_key_of(alias)] = canon
            members.setdefault(maker_key_of(canon), []).append(alias)
    canon = canon_of.get(maker_key_of(name), name)
    out: List[str] = []
    seen: Set[str] = set()
    for n in (name, canon, *members.get(maker_key_of(canon), [])):
        k = maker_key_of(n)
        if k and k not in seen:
            seen.add(k)
            out.append(n)
    return out
