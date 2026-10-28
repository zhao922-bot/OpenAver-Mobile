"""伺服器掃描來源清單（TASK-168b-T2 / CD-168b-10），給桌面版「連線」頁的對照表左欄。

I-L：`path` 逐字是設定裡的字串（不 lower、不翻譯、不 expand）；`sample` 若非 None，
必在 `path` 之下。
"""
from __future__ import annotations

import os
import time
from collections import deque

from core.config import iter_gallery_sources
from core.path_utils import file_uri_to_server_path
from core.video_extensions import get_video_extensions

_MAX_ENTRIES = 200
_MAX_DEPTH = 3
_MAX_SECONDS = 1.5


def _is_video_file(entry, exts: set) -> bool:
    if os.path.splitext(entry.name)[1].lower() not in exts:
        return False
    return entry.is_file()


def _is_under(candidate: str, root: str) -> bool:
    """candidate 是否在 root 之下（前綴邊界）。兩邊的 `\\` 先視為 `/`、root 尾端分隔符去掉再比
    （Windows 路徑兩種都合法）；不改回傳的 path 字串。"""
    stem = root.replace("\\", "/").rstrip("/")
    cand = candidate.replace("\\", "/")
    return cand[: len(stem)] == stem and cand[len(stem):len(stem) + 1] == "/"


def _find_sample(root: str, exts: set) -> str | None:
    """有界掃描取第一個影片檔絕對路徑；找不到或任何失敗＝None。"""
    deadline = time.monotonic() + _MAX_SECONDS
    budget = _MAX_ENTRIES
    queue = deque([(root, 0)])
    while queue:
        current, depth = queue.popleft()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    budget -= 1
                    found = _inspect_entry(entry, exts, depth, queue)
                    if found is not None and _is_under(found, root):
                        return found
                    if budget <= 0 or time.monotonic() > deadline:
                        return None
        except OSError:
            continue
    return None


def _inspect_entry(entry, exts: set, depth: int, queue: deque) -> str | None:
    """單一 entry 處理；壞 symlink 等拋 OSError 一律當作略過（BE-ENV-07）。"""
    try:
        if entry.is_dir(follow_symlinks=False):
            if depth < _MAX_DEPTH:
                queue.append((entry.path, depth + 1))
            return None
        if _is_video_file(entry, exts):
            os.stat(entry.path)
            return entry.path
    except OSError:
        return None
    return None


def list_sources(config: dict) -> list[dict]:
    """directories（含 readonly）＋ favorite_folder，去重（保留 directory）。"""
    exts = get_video_extensions(config)
    out: list[dict] = []
    seen: set[str] = set()
    for src in iter_gallery_sources(config.get("gallery")):
        # file:/// URI 來源轉成伺服器裸路徑（與 client to_local 收到的 sample 同形）；
        # 一般路徑 file_uri_to_server_path 逐字原樣返回（I-L）。
        path = file_uri_to_server_path(src.path)
        if path in seen:
            continue
        seen.add(path)
        out.append({
            "path": path,
            "kind": "directory",
            "readonly": bool(src.readonly),
            "sample": _find_sample(path, exts),
        })
    fav = (config.get("search") or {}).get("favorite_folder")
    fav = file_uri_to_server_path(fav.strip()) if isinstance(fav, str) else ""
    if fav and fav not in seen:
        out.append({"path": fav, "kind": "favorite", "readonly": False, "sample": _find_sample(fav, exts)})
    return out
