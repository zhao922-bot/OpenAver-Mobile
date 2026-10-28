"""
女優爬蟲 Orchestrator — 五來源並行抓取（Phase 42b T3）

Routes:
    C1 text  : per-field Wikipedia → XCity → Graphis → AVBase merge
    C2 parallel: xcity + wiki + graphis + gfriends + avbase (max_workers=5, 5s budget)
    C3 photo : Graphis prof_url → gfriends URL → Wiki photo_url → XCity photo_url → None
    C4 return: nested new fields + legacy flat shortcuts
    TD-1     : current_age computed from text.birth, never read from source
"""

import unicodedata
from collections import namedtuple
from datetime import datetime
from typing import Optional, Dict

from core.logger import get_logger

ProfileResult = namedtuple("ProfileResult", ["data", "timed_out"])

logger = get_logger(__name__)

# Fields that count as meaningful source text for callers inspecting raw results.
_MEANINGFUL_TEXT_FIELDS = (
    # Physical + biographical
    "birth", "height", "bust", "waist", "hip", "cup", "blood",
    "hometown", "hobby",
    # Wiki-specific, including alias-only infoboxes
    "nickname", "exclusive_makers", "debut_year", "other_names",
)

_FIELD_MERGE_PRIORITY = ("wiki", "xcity", "graphis", "avbase")  # 依序找第一個非空值
_COMMON_FIELDS = ("name_en", "birth", "height", "bust", "waist", "hip", "cup",
                  "hometown", "hobby")  # 不含 blood，見下方說明
_WIKI_ONLY_FIELDS = ("nickname",)  # 不含 exclusive_makers/debut_year，見下方說明


_ALIAS_SOURCE_PRIORITY = ("wiki", "avbase")  # 別名來源鏈：前面的過濾後非空就用


def _clean_aliases(names, own_name: str) -> list:
    """別名過濾（CD-174-5）：丟空白／非字串／`@` 開頭帳號／等於查詢名；原字串去重、保序。"""
    if not isinstance(names, list):
        return []
    own = unicodedata.normalize("NFKC", own_name or "").strip()
    cleaned, seen = [], set()
    for raw in names:
        if not isinstance(raw, str):
            continue
        norm = unicodedata.normalize("NFKC", raw).strip()
        if not norm or norm.startswith("@") or norm == own:
            continue
        if raw.strip() not in seen:
            seen.add(raw.strip())
            cleaned.append(raw.strip())
    return cleaned


def _pick_aliases(sources: dict, own_name: str) -> list:
    """依 _ALIAS_SOURCE_PRIORITY 取第一個「過濾後非空」的來源別名；都空回 []。"""
    for src in _ALIAS_SOURCE_PRIORITY:
        cleaned = _clean_aliases((sources.get(src) or {}).get("other_names"), own_name)
        if cleaned:
            return cleaned
    return []


def _merge_text_fields(sources: dict, name: str) -> dict:
    merged = {}
    for field in _COMMON_FIELDS:
        for src in _FIELD_MERGE_PRIORITY:
            val = (sources.get(src) or {}).get(field)
            if val:  # 空字串/None 都視為沒有值，往下一個來源找
                merged[field] = val
                break
    for field in _WIKI_ONLY_FIELDS:
        val = (sources.get("wiki") or {}).get(field)
        if val:
            merged[field] = val
    # aliases 例外：與其他欄位來源互不影響，走 _ALIAS_SOURCE_PRIORITY（維基 → avbase）
    aliases = _pick_aliases(sources, name)
    if aliases:
        merged["aliases"] = aliases
    return merged


class _FetchedSources(dict):
    """Five source values plus timeout state for the legacy ProfileResult."""

    def __init__(self, *args, timed_out=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.timed_out = timed_out


def _has_meaningful_text(result: Optional[Dict]) -> bool:
    """True if source dict has at least one non-empty text profile field.
    name_ja / photo_url / photo_license alone do NOT count — those can come from
    the input arg or a shell parse on a non-AV page. Python truthiness handles
    both string fields ('' → False) and list fields ([] → False) uniformly."""
    if not result:
        return False
    return any(result.get(k) for k in _MEANINGFUL_TEXT_FIELDS)

# Cache 結構（模組層級變數）
_cache = {}          # key: str (正規化女優名), value: dict (profile + timestamp)
_CACHE_TTL = 3600    # 1 小時
_FETCH_BUDGET_S = 5  # 五路並行抓取的共享預算（秒）；於 _fetch_all_sources 函式體內讀取


def _normalize_name(name: str) -> str:
    """正規化女優名稱（用於 cache key）"""
    import unicodedata
    name = name.strip()
    # 全形 → 半形
    name = unicodedata.normalize('NFKC', name)
    # 統一空白符
    name = ' '.join(name.split())
    return name


def _compute_age_from_birth(birth: Optional[str]) -> Optional[int]:
    """Compute current age from birth 'YYYY-MM-DD'. Returns None if birth missing/invalid."""
    if not birth:
        return None
    try:
        birth_date = datetime.strptime(birth, '%Y-%m-%d')
    except (ValueError, TypeError):
        return None
    today = datetime.now()
    age = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def get_cached_profile(name: str) -> Optional[dict]:
    """公開 cache 讀取 — 回傳 cached profile dict 或 None（不觸發 scrape）"""
    import time
    key = _normalize_name(name)
    entry = _cache.get(key)
    if entry and (time.time() - entry["timestamp"]) < _CACHE_TTL:
        return entry["data"]
    return None


def _fetch_all_sources(name: str, makers: list = None) -> dict:
    """Fetch five raw sources in parallel within a shared five-second budget."""
    import time
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
    from core.scrapers.actress.xcity import scrape_xcity
    from core.scrapers.actress.wiki_ja import scrape_wiki_ja
    from core.scrapers.actress.graphis import scrape_graphis_photo
    from core.scrapers.actress.gfriends import lookup_gfriends
    from core.scrapers.actress.avbase import scrape_avbase

    # 並行抓取（5 routes，嚴格 5s 上限，shutdown 不等待背景執行緒）
    executor = ThreadPoolExecutor(max_workers=5)
    xcity_future    = executor.submit(scrape_xcity, name)
    wiki_future     = executor.submit(scrape_wiki_ja, name)
    graphis_future  = executor.submit(scrape_graphis_photo, name)
    gfriends_future = executor.submit(lookup_gfriends, name, makers)
    avbase_future   = executor.submit(scrape_avbase, name)

    start = time.time()
    any_timed_out = False

    try:
        xcity_result = xcity_future.result(timeout=_FETCH_BUDGET_S)
    except FuturesTimeoutError:
        xcity_result = None
        any_timed_out = True
    except Exception:
        xcity_result = None

    remaining = max(0, _FETCH_BUDGET_S - (time.time() - start))
    try:
        wiki_result = wiki_future.result(timeout=remaining)
    except FuturesTimeoutError:
        wiki_result = None
        any_timed_out = True
    except Exception:
        wiki_result = None

    remaining = max(0, _FETCH_BUDGET_S - (time.time() - start))
    try:
        graphis_result = graphis_future.result(timeout=remaining)
    except FuturesTimeoutError:
        graphis_result = None
        any_timed_out = True
    except Exception:
        graphis_result = None

    remaining = max(0, _FETCH_BUDGET_S - (time.time() - start))
    try:
        gfriends_url = gfriends_future.result(timeout=remaining)
    except FuturesTimeoutError:
        gfriends_url = None
        any_timed_out = True
    except Exception:
        gfriends_url = None

    remaining = max(0, _FETCH_BUDGET_S - (time.time() - start))
    try:
        avbase_result = avbase_future.result(timeout=remaining)
    except FuturesTimeoutError:
        avbase_result = None
        any_timed_out = True
    except Exception as exc:
        logger.warning("[avbase] fetch failed for %s: %s", name, type(exc).__name__)
        avbase_result = None

    executor.shutdown(wait=False)

    return _FetchedSources({
        "xcity": xcity_result or None,
        "wiki": wiki_result or None,
        "graphis": graphis_result or None,
        "gfriends": gfriends_url or None,
        "avbase": avbase_result or None,
    }, timed_out=any_timed_out)


def get_actress_profile_preview(name: str, makers: list = None) -> dict:
    sources = _fetch_all_sources(name, makers)
    return {"name": name, "sources": sources}


def _sources_to_photo_candidates(sources: dict) -> list:
    candidates = []
    if (sources.get("graphis") or {}).get("prof_url"):
        candidates.append({"source": "graphis", "url": sources["graphis"]["prof_url"]})
    if (sources.get("wiki") or {}).get("photo_url"):
        candidates.append({"source": "wiki", "url": sources["wiki"]["photo_url"]})
    xcity_url = (sources.get("xcity") or {}).get("photo_url")
    if xcity_url:
        candidates.append({"source": "xcity", "url": xcity_url})
    if sources.get("gfriends"):
        candidates.append({"source": "gfriends", "url": sources["gfriends"]})
    return candidates


def get_actress_profile(name: str, makers: list = None) -> ProfileResult:
    """Return a merged actress profile and preserve the legacy return shape."""
    import time

    # Cache 檢查
    cache_key = _normalize_name(name)
    if cache_key in _cache:
        cached = _cache[cache_key]
        if time.time() - cached['timestamp'] < _CACHE_TTL:
            return ProfileResult(data=cached['data'], timed_out=False)
        else:
            del _cache[cache_key]  # 過期清理

    sources = _fetch_all_sources(name, makers)
    xcity_result = sources["xcity"]
    wiki_result = sources["wiki"]
    graphis_result = sources["graphis"]
    gfriends_url = sources["gfriends"]

    # Edge case: all routes returned nothing
    if not any(sources.values()):
        return ProfileResult(data=None, timed_out=sources.timed_out)

    # C1 — each field takes the first non-empty value in source priority order.
    merged = _merge_text_fields(sources, name)
    text = merged or None
    primary_text_source = None
    for src in _FIELD_MERGE_PRIORITY:
        raw = sources.get(src) or {}
        if any(raw.get(field) for field in _COMMON_FIELDS) or (
            src == "wiki" and (any(raw.get(field) for field in _WIKI_ONLY_FIELDS)
                               or _clean_aliases(raw.get("other_names"), name))
        ):
            primary_text_source = src
            break

    # Photo cascade (decoupled from text):
    # Graphis prof_url → gfriends URL → Wiki photo_url → XCity photo_url → None
    if graphis_result and graphis_result.get("prof_url"):
        photo_url, photo_source = graphis_result["prof_url"], "graphis"
    elif gfriends_url:
        photo_url, photo_source = gfriends_url, "gfriends"
    elif wiki_result and wiki_result.get("photo_url"):
        photo_url, photo_source = wiki_result["photo_url"], "wiki"
    elif xcity_result and xcity_result.get("photo_url"):
        photo_url, photo_source = xcity_result["photo_url"], "xcity"
    else:
        photo_url, photo_source = None, None

    # Backdrop: Graphis only
    backdrop_url = (graphis_result or {}).get("backdrop_url")

    # TD-1: compute current age from birth — never read stale age from any source
    current_age = _compute_age_from_birth((text or {}).get("birth"))

    # C4 — mixed return shape: new nested fields + legacy flat shortcuts
    result = {
        # === NEW nested fields (Phase 43 consumers) ===
        "primary_text_source": primary_text_source,   # "wiki"|"xcity"|"graphis"|"avbase"|None
        "text": text,                                  # merged text fields, or None
        "photo_url": photo_url,                        # winner of photo cascade, or None
        "photo_source": photo_source,                  # "graphis"|"gfriends"|"wiki"|"xcity"|None
        "backdrop_url": backdrop_url,                  # Graphis-only, or None
        "current_age": current_age,                    # int or None (TD-1 fix)
        "all_sources": dict(sources),                  # five unmerged dict/dict/dict/str/dict values

        # === LEGACY flat shortcuts (derived) ===
        # Existing template/JS/test assertions depend on these keys.
        # Phase 43 can hard-cut these later.
        "name":     (text or {}).get("name_ja") or (text or {}).get("name") or name,
        "name_en":  (text or {}).get("name_romaji") or (text or {}).get("name_en"),
        "img":      photo_url,                          # template: actress_profile.img
        "backdrop": backdrop_url,                       # template: actress_profile.backdrop
        "birth":    (text or {}).get("birth"),
        "age":      current_age,                        # TD-1: from text.birth
        "height":   (text or {}).get("height"),
        "cup":      (text or {}).get("cup"),
        "bust":     (text or {}).get("bust"),
        "waist":    (text or {}).get("waist"),
        "hip":      (text or {}).get("hip"),
        "hometown": (text or {}).get("hometown"),
        "hobby":    (text or {}).get("hobby"),
    }

    # Cache 寫入
    _cache[cache_key] = {
        'data': result,
        'timestamp': time.time()
    }

    return ProfileResult(data=result, timed_out=False)
