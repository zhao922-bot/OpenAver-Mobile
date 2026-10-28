"""邏輯片單 helper（173-T1）— 「設定片庫目錄內、分集片算一部」的唯一定義。

純函式、不 import web。分析頁快照與片商膠囊端點共用。
"""

from __future__ import annotations

import re

from core.multipart_group import group_rows
from core.path_utils import is_path_under_dir, uri_to_local_fs_path

_RELEASE_RE = re.compile(r"^(19\d{2}|20\d{2}|21\d{2})(?:-(\d{2})(?:-(\d{2}))?)?")


def release_parts(raw: object) -> tuple[int | None, str | None, str | None]:
    """從 release_date 抽出 (year, month='YYYY-MM', date='YYYY-MM-DD')。"""
    match = _RELEASE_RE.match(str(raw or "").strip())
    if not match:
        return None, None, None
    year = int(match.group(1))
    month_num = match.group(2)
    day_num = match.group(3)
    month = None
    if month_num and 1 <= int(month_num) <= 12:
        month = f"{year}-{month_num}"
    date = None
    if month and day_num and 1 <= int(day_num) <= 31:
        date = f"{year}-{month_num}-{day_num}"
    return year, month, date


def rows_in_library_dirs(rows, configured_dir_uris):
    """只留設定的片庫目錄底下的列。"""
    return [r for r in rows if any(is_path_under_dir(r.path, uri) for uri in configured_dir_uris)]


def first_members(rows_in_dir, path_mappings):
    """分集片合併成一組，每組取 members[0]（part-1）。"""
    groups = group_rows(
        rows_in_dir,
        fs_path_of=lambda v: uri_to_local_fs_path(v.path, path_mappings),
    )
    return [g.members[0] for g in groups]


def logical_title_firsts(rows, configured_dir_uris, path_mappings):
    """邏輯片單：片庫目錄內的列、分集合併後每部取 part-1。"""
    return first_members(rows_in_library_dirs(rows, configured_dir_uris), path_mappings)
