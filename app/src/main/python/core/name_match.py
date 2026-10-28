"""名稱比對的共用小工具（175c-T3）。

頂層只准 stdlib（`re`、`unicodedata`）：scrapers 與 search_providers 兩層都要用它，
所以它必須在兩者之下，不得 import 任何 `core.*`（BE-PY-08）。
"""

import re
import unicodedata

_STRIP = set("・·-_")

# 結尾的一段全形括號（舊名）；含括號前的空白。與 DMM 原 `_TRAILING_PAREN` 同一個正規式（外加捕獲舊名）。
_TRAILING_PAREN = re.compile(r"\s*（([^（）]*)）\s*$")


def fold(s) -> str:
    """NFKC → casefold → 去空白與 ・·-_（不做漢字字形對照，CD-175b-1）。"""
    t = unicodedata.normalize("NFKC", s if isinstance(s, str) else "").casefold()
    return "".join(ch for ch in t if not ch.isspace() and ch not in _STRIP)


def split_paren_name(name):
    """結尾一段全形括號拆成 (主名, 括號內舊名|None)；沒有括號、或拆完主名為空 → (name, None)。

    `あかね麗（二階堂麗）`→`("あかね麗","二階堂麗")`；`A（B）（C）`→`("A（B）","C")`（只拆最後一段）；
    `（二階堂麗）`→`("（二階堂麗）",None)`；`""`→`("",None)`；`None`→`(None,None)`。
    """
    if not name:
        return name, None
    m = _TRAILING_PAREN.search(name)
    if m is None:
        return name, None
    main = name[: m.start()]
    if not main:
        return name, None
    return main, m.group(1).strip() or None
