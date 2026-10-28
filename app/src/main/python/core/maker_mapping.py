"""
maker_mapping.json shared loader

供 models.py / scraper.py / gallery_scanner.py / search.py 共用。
模組層僅 import stdlib + core.logger（無 core/ 業務模組），避免循環依賴。
"""

import json
import re
from pathlib import Path
from typing import Dict, Optional

from core.logger import get_logger

logger = get_logger(__name__)

# 片商對照表檔案路徑（專案根目錄 / maker_mapping.json）
MAKER_MAPPING_FILE: Path = Path(__file__).parent.parent / "maker_mapping.json"

# module-level cache（None = 尚未載入；dict = 已載入的完整 JSON）
_cache: Optional[dict] = None


def _load_raw() -> dict:
    """載入並 cache 整個 JSON（失敗/不存在回傳空 dict）"""
    global _cache
    if _cache is not None:
        return _cache

    if not MAKER_MAPPING_FILE.exists():
        _cache = {}
        return _cache

    try:
        with open(MAKER_MAPPING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
        _cache = data
    except (json.JSONDecodeError, IOError, OSError) as e:
        logger.warning("maker_mapping: 無法載入 %s，回傳空 dict（%s）", MAKER_MAPPING_FILE, e)
        _cache = {}

    return _cache


def load_name_mapping() -> Dict[str, str]:
    """
    回傳 name_mapping 層。

    - 新格式（有 _meta + name_mapping + prefix_mapping）→ 回傳 name_mapping dict
    - 舊格式（無 _meta，純平坦 prefix dict）→ 回傳 {}
    - 檔案不存在或 JSON 損毀 → 回傳 {}
    """
    raw = _load_raw()
    if "_meta" in raw and "name_mapping" in raw:
        nm = raw["name_mapping"]
        if isinstance(nm, dict):
            # 過濾掉 _meta 等非 mapping key（防禦）
            return {k: v for k, v in nm.items() if k != "_meta"}
        return {}
    return {}


def load_search_aliases() -> Dict[str, str]:
    """
    回傳 search_aliases 節（只認不寫的搜尋別名 {別名: 正名}；175a 起，內容由 175b 填）。

    - 缺節、非 dict、檔案不存在或損毀 → {}
    - 鍵或值不是字串的項目濾掉
    """
    sa = _load_raw().get("search_aliases")
    if isinstance(sa, dict):
        return {k: v for k, v in sa.items() if isinstance(k, str) and isinstance(v, str)}
    return {}


def load_prefix_mapping() -> Dict[str, str]:
    """
    回傳 prefix_mapping 層。

    - 新格式（有 _meta + prefix_mapping）→ 回傳 prefix_mapping dict
    - 舊格式（無 _meta，純平坦 prefix dict）→ 回傳整個 dict（向下相容）
    - 檔案不存在或 JSON 損毀 → 回傳 {}
    """
    raw = _load_raw()
    if "_meta" in raw and "prefix_mapping" in raw:
        pm = raw["prefix_mapping"]
        if isinstance(pm, dict):
            return {k: v for k, v in pm.items() if k != "_meta"}
        return {}
    # 舊格式：整個 dict，跳過 _meta（萬一有的話）
    return {k: v for k, v in raw.items() if k != "_meta"}


def normalize_maker_name(maker) -> str:
    """
    從 name_mapping 查表；無對照 → 原值。

    - 空字串 → 回傳 ""
    - None → 回傳 ""（型別防禦）
    """
    if not maker:
        return ""
    nm = load_name_mapping()
    return nm.get(maker, maker)


def get_maker_by_prefix(number: str) -> str:
    """
    從 prefix_mapping 查片商名；miss（含無字母前綴）一律回傳空字串，不再有 runtime fallback 或寫回。

    - 無字母前綴（如 "123"、""）→ 回傳 ""
    """
    mapping = load_prefix_mapping()
    match = re.match(r"^([A-Za-z]+)", number)
    if not match:
        return ""

    prefix = match.group(1).upper()
    return mapping.get(prefix, "")
