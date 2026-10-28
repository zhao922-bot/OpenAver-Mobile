"""多來源結果 merger（pure function）— epic §5.1.1 / CD-61-9.

職責：把多個 scraper 回傳的 `Video` 合併成單一 `Video`。

合併契約（§5.1.1）：
1. **文字/meta 整包贏**：依 `user_order` 找第一個存在於 candidates 的來源作為
   text_source，整包採用其 title / actresses / tags / series / maker / director
   與 meta（date / duration / rating / votes）。text_source 為空的欄位才往
   `user_order` 後續來源 fallback（避免主來源缺欄時整片清空）。
2. **封面跟 user_order**：`cover_url` / `sample_images` 改依 `user_order` 找第一個
   該欄非空的來源；cover_url 與 sample_images 各自獨立解析（可來自不同來源）。

本模組是 PURE：不 import config、不認識任何來源偏好設定、不做 to_legacy_dict /
maker-prefix fallback / _source 注入（那些由 caller `search_jav()` 負責）。
caller 透過 user_order 的排序編碼來源偏好。
"""
from __future__ import annotations

from typing import Optional

from core.scrapers.models import Video

# 文字欄位（整包來自 text_source，空值往後 fallback）
_TEXT_FIELDS = ('title', 'actresses', 'tags', 'series', 'maker', 'director')
# meta 欄位（同樣整包來自 text_source，空值往後 fallback）
# 注意：`label` 不在 §5.1.1 表列，但既有 merge 會 backfill（feeds NFO），保留 parity（61a-6 review B1）
_STR_META_FIELDS = ('date', 'label', 'summary')
# None-sentinel meta 欄位（0 / 0.0 視為有值）
_OPTIONAL_META_FIELDS = ('duration', 'rating', 'votes')


def _is_empty(value: object, none_sentinel: bool) -> bool:
    """欄位空值判定。none_sentinel=True 用 `is None`（保 0 / 0.0），否則 falsy。"""
    if none_sentinel:
        return value is None
    return not value


def _ordered_candidates(
    candidates: dict[str, Video], order: list[str]
) -> list[Video]:
    """依 order 排出 candidates 中存在的來源，order 未涵蓋的接在後面（insertion order）。"""
    seen: set[str] = set()
    result: list[Video] = []
    for sid in order:
        if sid in candidates and sid not in seen:
            result.append(candidates[sid])
            seen.add(sid)
    for sid, video in candidates.items():
        if sid not in seen:
            result.append(video)
            seen.add(sid)
    return result


def _first_non_empty(videos: list[Video], field: str, none_sentinel: bool):
    """從已排序的 videos 中取第一個該欄非空的值；全空回 None（caller 自處理）。"""
    for video in videos:
        value = getattr(video, field)
        if not _is_empty(value, none_sentinel):
            return value
    return None


def _first_non_empty_video(videos: list[Video], field: str, none_sentinel: bool) -> Optional[Video]:
    """從已排序的 videos 中取第一個該欄非空的 **Video 物件本身**；全空回 None。

    CD-113c-12：preview_cover_url 必須跟著 cover_url 的勝出候選走，不能各自
    `_first_non_empty` ——那會讓 cover 取候選 A、preview 取候選 B，畫面上顯示
    別片的預覽圖卻看不出來。本函式回傳「決勝的那個候選物件」，caller 再從
    同一個候選一次複製 cover_url 與 preview_cover_url 兩個欄位。
    """
    for video in videos:
        value = getattr(video, field)
        if not _is_empty(value, none_sentinel):
            return video
    return None


def merge_results(
    candidates: dict[str, Video],
    user_order: list[str],
) -> Optional[Video]:
    """合併多來源結果為單一 `Video`。

    Args:
        candidates: `source_id -> Video`（即 search_jav 的 all_data 原形）。
        user_order: 文字/meta 與封面欄位的偏好順序（caller 已把 primary 排到最前）。

    Returns:
        合併後的 `Video`；`candidates` 為空時回 `None`（防禦性，caller 應已 guard）。
    """
    if not candidates:
        return None

    # text/meta：依 user_order 排序的 candidate 序列
    text_ordered = _ordered_candidates(candidates, user_order)
    text_source = text_ordered[0]  # 第一個存在來源 = base（整包贏）

    updates: dict[str, object] = {}

    # 文字 + str-meta：text_source 為空才往後 fallback
    for field in (*_TEXT_FIELDS, *_STR_META_FIELDS):
        if _is_empty(getattr(text_source, field), none_sentinel=False):
            fallback = _first_non_empty(text_ordered, field, none_sentinel=False)
            if fallback is not None:
                updates[field] = fallback

    # None-sentinel meta：duration / rating / votes
    for field in _OPTIONAL_META_FIELDS:
        if _is_empty(getattr(text_source, field), none_sentinel=True):
            fallback = _first_non_empty(text_ordered, field, none_sentinel=True)
            if fallback is not None:
                updates[field] = fallback

    # 封面欄位：cover_url 依 user_order 找第一個該欄非空的候選（=「勝出候選」）。
    # preview_cover_url 必須從**同一個**勝出候選複製，不可各自 _first_non_empty
    # （CD-113c-12，同源綁定；否則 cover 取候選 A、preview 取候選 B＝顯示別片預覽圖）。
    # 勝出候選沒有 preview 時明確覆寫為空字串，不得沿用 text_source 或其他候選的值。
    cover_ordered = _ordered_candidates(candidates, user_order)
    cover_winner = _first_non_empty_video(cover_ordered, 'cover_url', none_sentinel=False)
    if cover_winner is not None:
        updates['cover_url'] = cover_winner.cover_url
        updates['preview_cover_url'] = cover_winner.preview_cover_url
    elif text_source.preview_cover_url:
        # 沒有任何候選有 cover_url ⇒ 沒有封面可預覽。**明確清空**，不讓 preview
        # 從 text_source 漏過來。今天漏不出來只因為 mapper 的
        # `_build_preview_cover_url()` 在 cover 空時回 ''——但那是**別的模組**的
        # 不變式，merger 不該隱性依賴它（那正是 CD-113c-12 要消滅的形狀）。
        updates['preview_cover_url'] = ''

    # 劇照欄位：sample_images 依 user_order 找第一個該欄非空的候選（=「勝出候選」）。
    # preview_sample_images 必須從**同一個**勝出候選複製，不可各自 _first_non_empty
    # （CD-126-2／CD-113c-12 同源綁定；否則 sample 取候選 A、preview 取候選 B＝燈箱顯示別片劇照）。
    # 勝出候選沒有 preview 時明確覆寫為空 list，不得沿用 text_source 或其他候選的值。
    sample_winner = _first_non_empty_video(cover_ordered, 'sample_images', none_sentinel=False)
    if sample_winner is not None:
        updates['sample_images'] = sample_winner.sample_images
        updates['preview_sample_images'] = sample_winner.preview_sample_images
    elif text_source.preview_sample_images:
        # 沒有任何候選有 sample_images ⇒ 沒有劇照可預覽。**明確清空**，不讓 preview
        # 從 text_source 漏過來（同封面分支的防漏形狀）。
        updates['preview_sample_images'] = []

    return text_source.model_copy(update=updates) if updates else text_source
