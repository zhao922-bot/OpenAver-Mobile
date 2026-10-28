"""片商代號解析器（173-T4，plan CD-173-5／CD-173-6）。

使用者第一次點某家片商膠囊 → 用片庫裡這家的幾部片問 JavBus，認出作品頁代號並寫表。
逾時、被擋、看不懂的頁面是 Unreachable，絕不寫成 not_found（BE-PY-03）。
"""

from __future__ import annotations

import datetime
from typing import NamedTuple

from core.library_titles import release_parts
from core.logger import get_logger
from core.scrapers.javbus import STUDIO_MISS, STUDIO_UNREACHABLE, JavBusScraper, StudioVote
from core.scrapers.utils import normalize_number_impl

logger = get_logger(__name__)

SAMPLE_K = 5
MIN_AGE_DAYS = 30
VOTES_TO_STOP = 2


class Resolution(NamedTuple):
    status: str  # found / absent / unreachable / no_sample
    kind: str = ""
    studio_id: str = ""


NO_SAMPLE = Resolution("no_sample")
ABSENT = Resolution("absent")
UNREACHABLE = Resolution("unreachable")


def _parse_date(raw):
    """合法的 YYYY-MM-DD → date；其餘（含 2026-09、2026-02-31）回 None。"""
    date_str = release_parts(raw)[2]
    if not date_str:
        return None
    try:
        return datetime.date.fromisoformat(date_str)
    except ValueError:
        return None


def pick_samples(titles, today, k=SAMPLE_K, *, spellings=None, validate=None):
    """從邏輯片單挑 k 部樣本：回 [(number, release_date)]。

    spellings 給了就只取 strip(maker) 在其內者；validate 給了就只取通過者；同番號只留一部。
    先取發行日距今 >= 30 天（新到舊），不足以 < 30 天（新到舊）補，無合法發行日殿後。
    """
    seen = set()
    dated, undated = [], []
    for t in titles:
        if spellings is not None and (t.maker or "").strip() not in spellings:
            continue
        if not (t.number or "").strip():
            continue  # 掃描器認不出番號的檔 number=None
        number = normalize_number_impl(t.number)
        if number in seen:
            continue
        if validate is not None and not validate(number):
            continue
        seen.add(number)
        d = _parse_date(t.release_date)
        (dated if d else undated).append((d, number, t.release_date))
    old = [s for s in dated if (today - s[0]).days >= MIN_AGE_DAYS]
    recent = [s for s in dated if (today - s[0]).days < MIN_AGE_DAYS]
    old.sort(key=lambda s: s[0], reverse=True)
    recent.sort(key=lambda s: s[0], reverse=True)
    ordered = old + recent + undated
    return [(n, raw) for _, n, raw in ordered[:k]]


def decide(samples):
    """samples: [(outcome, release_date)] → Resolution（純函式）。

    有 Vote → Found（多數勝，平手取發行日較新樣本所投）；無 Vote 有 Unreachable →
    Unreachable；僅有 Miss → Absent；無樣本 → NoSample。
    """
    votes = [(o, d) for o, d in samples if isinstance(o, StudioVote)]
    if votes:
        tally = {}
        for o, d in votes:
            n, newest = tally.get((o.kind, o.studio_id), (0, datetime.date.min))
            tally[(o.kind, o.studio_id)] = (n + 1, max(newest, _parse_date(d) or datetime.date.min))
        (kind, studio_id), _ = max(tally.items(), key=lambda kv: kv[1])
        return Resolution("found", kind, studio_id)
    has_unreachable = any(o is STUDIO_UNREACHABLE for o, _ in samples)
    if has_unreachable:
        return UNREACHABLE
    if any(o is STUDIO_MISS for o, _ in samples):
        return ABSENT
    return NO_SAMPLE


def _reached_quorum(samples):
    counts = {}
    for o, _ in samples:
        if isinstance(o, StudioVote):
            counts[o] = counts.get(o, 0) + 1
            if counts[o] >= VOTES_TO_STOP:
                return True
    return False


def _from_mapping(m):
    if m["status"] == "found":
        return Resolution("found", m["kind"], m["studio_id"])
    return ABSENT


def resolve_maker_studio(maker_key, label, spellings, titles, *, today,
                         fetch_sample=None, db_path=None):
    """解析一家片商在 JavBus 的作品頁代號；found／absent 才寫表。"""
    # 延後 import：core.database 的 __init__ 會 import core.scraper，頂層 import 會與 core.scraper 成環
    from core.database import maker_javbus_map
    mapped = maker_javbus_map.get_mapping(maker_key, db_path=db_path)
    if mapped is not None:
        return _from_mapping(mapped)
    scraper = JavBusScraper()
    if fetch_sample is None:
        fetch_sample = scraper.fetch_studio_sample
    picked = pick_samples(titles, today, spellings=set(spellings), validate=scraper.validate_number)
    if not picked:
        return NO_SAMPLE
    samples = []
    for number, release_date in picked:
        samples.append((fetch_sample(number), release_date))
        if _reached_quorum(samples):
            break
    result = decide(samples)
    if result.status == "found":
        maker_javbus_map.record_found(maker_key, result.kind, result.studio_id, label, db_path=db_path)
    elif result.status == "absent":
        maker_javbus_map.record_not_found(maker_key, label, db_path=db_path)
    logger.info("maker %s -> %s (%d samples)", maker_key, result.status, len(samples))
    return result
