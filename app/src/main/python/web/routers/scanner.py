"""
Scanner API 路由 - 影片列表生成

端點：
- GET  /api/gallery/generate              — 掃描資料夾並產生影片列表（SSE 串流）
- GET  /api/gallery/stats                 — 取得 Scanner 統計資訊（影片總數）
- DELETE /api/gallery/cache               — 清除所有影片快取（清空 SQLite）
- GET  /api/gallery/update-check          — 檢查需要補全 NFO 的影片數量
- GET  /api/gallery/update                — 執行 NFO 補全更新（SSE 串流）
- GET  /api/gallery/view                  — 取得產生的 HTML 列表頁面
- GET  /api/gallery/actress-stats         — 查詢指定女優名稱的片數
- GET  /api/gallery/jellyfin-check        — 檢查多少影片缺少 Jellyfin poster/fanart
- GET  /api/gallery/jellyfin-update       — 批次產生 Jellyfin poster + fanart（SSE 串流）
- GET  /api/gallery/missing-check         — 檢查缺少 NFO/封面的影片清單
- GET  /api/gallery/browse-dir            — 列舉資料夾目錄與影片檔案清單
"""

import asyncio
import base64
import json
import os
import queue
import re
import sys
import threading
import time
import requests
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait as futures_wait
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from starlette.background import BackgroundTask

from core.gallery_scanner import VideoScanner, fast_scan_directory, scan_entry_needs_refresh, VideoInfo, _run_sample_images_cleanup_pass, is_nas_system_dir_name  # noqa: PLC2701 — scanner 的 rescan 端點需要在特定時機主動觸發 gallery_scanner 內部的樣本圖清理 pass（該 pass 平常只在 scanner 自身流程內被呼叫），避免把整段清理邏輯複製一份到 router 層
from core.cover_layout import cover_base_stem
from core.cover_attributes import effective_tags
from core.video_extensions import get_video_extensions
from core.gallery_generator import HTMLGenerator
from core.path_utils import to_file_uri, is_path_under_dir, uri_to_fs_path, coerce_to_file_uri, uri_to_local_fs_path
from core.nfo_updater import (
    backup_nfo_file,
    check_cache_needs_update,
    get_nfo_path_from_video,
    read_nfo_tags,
    replace_nfo_tags,
    update_videos_generator,
)
from core.plot_backfill import (
    clean_summary_text,
    find_missing_plot_candidates,
)
from core.plot_writeback import fill_empty_nfo_plot
from core.android_storage import AndroidStoragePermissionError
from core.database import VideoRepository, Video, init_db, get_db_path, migrate_json_to_sqlite
from core.focal import requires_face_detection
from core.focal_trigger import maybe_submit_video_focal
from core.organizer import (
    find_subtitle_files,
    generate_jellyfin_images,
    HEADERS as _EMBED_HEADERS,
)
from core.config import load_config, iter_gallery_sources, get_gallery_source_paths, STEM_IMAGE_MODES
from core.data_root import resolve_gallery_output_path
from core.readonly_producer import produce_source
from core.rename_normalizer import (
    build_combined_rename_plan,
    build_folder_rename_plan,
    build_rename_plan,
    canonicalize_source_stem,
    execute_combined_rename_plan,
    execute_folder_rename_plan,
    execute_rename_plan,
    multipart_token,
    validate_combined_rename_plan,
)
from web.routers.gallery_media import safe_realpath
from core.readonly_source import is_path_readonly, readonly_source_prefixes, writable_source_prefixes
from core.generate_state import try_mark_generate_active, mark_generate_done
from core import thumbnail_cache
from core.multipart_group import (
    group_rows,
    logical_video_count,
    logical_video_groups,
    resolve_groups_bulk,
    resolve_logical_video_groups,
)
from core.scraper import (
    get_javbus_lang,
    search_jav,
    smart_search,
    source_display_name,
)
from core import cf_handoff
from core.cf_transport import (
    CfChallengeRequired,
    CfTransportUnavailable,
    get_cf_transport,
)
from core.source_settings import is_uncensored_mode_effective
from core.scrapers.utils import check_subtitle, extract_number
from core.cloud_translate import TranslateError, build_error
from core.title_language import (
    normalize_translation_text,
    plot_needs_translation,
    title_needs_translation,
    translation_result_issue,
)
from core.title_writeback import NfoNotFoundError, NfoParseError
from core.source_config import get_manual_only_sources, validate_source_id
from pydantic import BaseModel
from core.logger import get_logger
from core.i18n import get_config_locale, t as i18n_t
from core.platform_info import DSM_PERMISSION_HINT, is_synology
from core.proxy_policy import proxy_kwargs
from web.routers.notifications import emit_notification as _emit_notif
from core.wishlist_reconcile import reconcile_wishlist, format_wishlist_removed_message
from core.ai_services import faces_state, similar_index, tags_backfill

logger = get_logger(__name__)

router = APIRouter(prefix="/api/gallery", tags=["gallery"])

# T3(40c): Jellyfin check TTL 快取（60 秒）
_jellyfin_cache_result: dict | None = None
_jellyfin_cache_time: float = 0
_rename_execute_lock = threading.Lock()
_rename_plan_cache: dict[str, tuple[float, dict]] = {}
_RENAME_PLAN_TTL_SECONDS = 30 * 60
_MAINTENANCE_MANUAL_SOURCES = frozenset({'javlibrary', 'fc-javten', 'jable'})
_TAG_SOURCE_MANUAL_ALLOWLIST = _MAINTENANCE_MANUAL_SOURCES
_TAG_SOURCE_CF_WAIT_SECONDS = 300.0
_TAG_SOURCE_CF_POLL_SECONDS = 0.5


def _schedule_ai_incremental() -> None:
    """After a completed scan, queue embeddings and AI tagging."""
    try:
        similar_index.schedule_incremental()
    except Exception:
        logger.exception("圖片相似增量排程失敗（掃描完成收尾）")
    try:
        faces_state.new_round()
    except Exception:
        logger.exception("人臉通知輪次重置失敗（掃描完成收尾）")
    try:
        tags_backfill.schedule_incremental()
    except Exception:
        logger.exception("AI 標籤增量排程失敗（掃描完成收尾）")


class RenameExecuteRequest(BaseModel):
    plan_id: str
    scope: str = "files"


def _sse_event(data: dict) -> str:
    """將 dict 編碼為 SSE 格式的單條 message。"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _runtime_text(section: str, key: str, locale: str, **params) -> str:
    """Translate a runtime/SSE message using the active UI locale."""
    return i18n_t(f"runtime.{section}.{key}", locale=locale, **params)


def _active_locale(config: dict | None = None) -> str:
    """Best-effort UI locale lookup for runtime messages."""
    try:
        return get_config_locale(config)
    except Exception:
        return "zh-CN"


def _collect_long_paths(
    all_files: List[Dict[str, Any]],
    threshold: int = 260,
) -> List[str]:
    """a5: 從 fast_scan_directory 結果收集超過 threshold 的 path（純函數）。

    呼叫端負責 platform gate（sys.platform == 'win32'）。
    此 helper 不檢查平台，方便單元測試。
    """
    return [f['path'] for f in all_files if len(f['path']) > threshold]


def _emit_long_path_warnings(logger_, long_paths: List[str]) -> None:
    """a5: 把長路徑清單寫到 debug.log（空 list 時不輸出）。"""
    if not long_paths:
        return
    logger_.warning(f"[a5] 發現 {len(long_paths)} 個路徑超過 260 字元：")
    for p in long_paths:
        logger_.warning(f"  {p}")


# ---------------------------------------------------------------------------
# TASK-88c-T2: readonly 來源分流 + SSE thread/queue 橋接 + 四數摘要
# ---------------------------------------------------------------------------

def _outcome_to_sse(o, locale: str) -> dict:
    """把 ProduceOutcome 轉一條 SSE log 行 dict（純函式）。

    producer 的 error 是固定的內部哨兵；對外一律換成目前介面語言的
    「生成失敗」，不轉發 server-side 細節。failed → warn，其餘 info。
    """
    label_key = {
        "created": "outcome_created",
        "skipped": "outcome_skipped",
        "no_scrape": "outcome_no_scrape",
        "failed": "outcome_failed",
    }.get(o.status)
    label = (
        _runtime_text("scanner", label_key, locale)
        if label_key else o.status
    )
    msg = _runtime_text(
        "scanner",
        "outcome_line",
        locale,
        label=label,
        item=o.number or o.source_uri,
    )
    if o.status == "failed":
        msg += _runtime_text(
            "scanner",
            "outcome_error_suffix",
            locale,
            error=_runtime_text("scanner", "generate_failed", locale),
        )
    return {"type": "log", "level": "warn" if o.status == "failed" else "info", "message": msg}


def _accumulate_readonly(summary: dict, result) -> None:
    """跨來源累計四數 + no_output/unreachable/partial/pruned（純函式，CD-88c-3 / TASK-89b-T6）。

    no_output_path → 只 no_output+1；unreachable → 只 unreachable+1（Finding-2 修復，
    須插在通用 aborted_reason 分支之前，否則會被通用分支吃掉）；其他非空 aborted_reason
    （not_readonly 防呆）→ 記 log 不計數；正常 → sources+1 並累加
    created/skipped/no_scrape/failed/pruned，skipped_paths 非空另計 partial+1。
    """
    if result.aborted_reason == "no_output_path":
        summary["no_output"] += 1
        return
    if result.aborted_reason == "unreachable":
        summary["unreachable"] += 1
        return
    if result.aborted_reason:
        logger.info("唯讀來源略過（%s）: %s", result.aborted_reason, result.source_path)
        return
    summary["sources"] += 1
    summary["created"] += result.created
    summary["skipped"] += result.skipped
    summary["no_scrape"] += result.no_scrape
    summary["failed"] += result.failed
    summary["pruned"] += result.pruned
    if result.skipped_paths:
        summary["partial"] += 1


def _yield_source_summary(result, locale: str) -> Generator[str, None, None]:
    """該來源小結（產生器）。

    no_output_path → 「請先設定輸出夾」提示（Acceptance #11）。
    unreachable → 「來源無法連線」warn 提示（TASK-89b-T6，Finding-2 修復）。
    正常小結後，skipped_paths 非空時追加「已略過刪除偵測」warn（比照非 readonly
    分支 :428-433 文案風格）。
    """
    if result.aborted_reason == "no_output_path":
        yield _sse_event({
            "type": "log", "level": "warn",
            "message": _runtime_text(
                "scanner", "readonly_output_missing", locale,
                path=result.source_path,
            ),
        })
    elif result.aborted_reason == "unreachable":
        yield _sse_event({
            "type": "log", "level": "warn",
            "message": _runtime_text(
                "scanner", "readonly_unreachable", locale,
                path=result.source_path,
            ),
        })
    elif not result.aborted_reason:
        yield _sse_event({
            "type": "log", "level": "info",
            "message": _runtime_text(
                "scanner", "readonly_summary", locale,
                path=result.source_path,
                created=result.created,
                skipped=result.skipped,
                no_scrape=result.no_scrape,
                failed=result.failed,
            ),
        })
        if result.skipped_paths:
            yield _sse_event({
                "type": "log", "level": "warn",
                "message": _runtime_text(
                    "scanner", "readonly_partial", locale,
                    path=result.source_path,
                    count=len(result.skipped_paths),
                ),
            })


def _run_readonly_source(src, config, repo, summary, reachable: bool = True, should_abort: Optional[Callable[[], bool]] = None, strm_mappings_getter: Optional[Callable[[], dict]] = None) -> Generator[str, None, None]:
    """在 daemon worker thread 跑 produce_source，drain 無界 queue 逐片 yield SSE。

    worker 例外（含 produce_source 迴圈前的 normalize/列檔/DB 拋錯，未被 producer
    內 try 包覆）顯式接手（CD-88c-1 / Codex P1），不靜默吞：box['error'] → 產生器
    emit error SSE + source_errors+1 + 續下一來源。

    strm_mappings_getter（PR #93 五審四次 P2, option C）：注入 produce_source，讓 media-server
    模式每片重讀 fresh strm 映射，封死斷線尾巴那片用凍結舊映射落檔的殘留。
    """
    q: "queue.Queue" = queue.Queue()  # 無界：worker 永不阻塞於 put，client 斷線 daemon 自然退出
    _SENTINEL = object()
    box: dict = {}
    locale = get_config_locale(config)

    def _work():
        try:
            box['result'] = produce_source(
                src, config, repo,
                on_progress=q.put,
                should_abort=should_abort,
                reachable=reachable,
                strm_mappings_getter=strm_mappings_getter,
            )
        except Exception:
            logger.exception("唯讀生成來源失敗: %s", src.path)
            box['error'] = True
        finally:
            q.put(_SENTINEL)

    t = threading.Thread(target=_work, daemon=True)
    t.start()
    yield _sse_event({
        "type": "log",
        "level": "info",
        "message": _runtime_text(
            "scanner", "readonly_start", locale, path=src.path
        ),
    })
    while True:
        item = q.get()
        if item is _SENTINEL:
            break
        yield _sse_event(_outcome_to_sse(item, locale))
    t.join()
    if box.get('error'):
        summary["source_errors"] += 1
        yield _sse_event({
            "type": "log", "level": "error",
            "message": _runtime_text(
                "scanner", "readonly_failed", locale, path=src.path
            ),
        })
        return
    result = box.get('result')
    if result is not None:
        _accumulate_readonly(summary, result)
        yield from _yield_source_summary(result, locale)


def _permission_denied_warning(directory: str, locale: str) -> str:
    """權限不足時共用的掃描警告（Synology 附 DSM 指引）。"""
    if is_synology():
        return _runtime_text(
            "scanner",
            "permission_denied_dsm",
            locale,
            path=directory,
            hint=DSM_PERMISSION_HINT,
        )
    return _runtime_text(
        "scanner", "permission_denied", locale, path=directory
    )


# Windows 網路類 winerror：BAD_NETPATH／NETNAME_DELETED／NETWORK_UNREACHABLE 類（67 刻意不列、3 走「不存在」）
_NETWORK_WINERRORS = frozenset({53, 64, 1222, 1231})


def _scan_root_skip_message(
    directory: str,
    normalized_dir: str,
    locale: str,
) -> Optional[str]:
    """根目錄不可存取時回傳警告；可存取時回傳 None。

    白名單：只有明確的「不存在」才說資料夾不存在，其餘 OSError 一律「無法存取」（NAS 斷線不誤導成打錯字）。
    """
    try:
        os.stat(normalized_dir)
    except PermissionError:
        return _permission_denied_warning(directory, locale)
    except OSError as exc:
        if isinstance(exc, (FileNotFoundError, NotADirectoryError)) and getattr(exc, "winerror", None) not in _NETWORK_WINERRORS:
            return _runtime_text(
                "scanner", "folder_missing", locale, path=directory
            )
        return _runtime_text(
            "scanner", "path_unreachable", locale, path=directory
        )
    except ValueError:  # 與 os.path.exists 一致：畸形路徑也只跳過這個來源
        return _runtime_text(
            "scanner", "folder_missing", locale, path=directory
        )
    return None


def _skipped_scan_warning(
    directory: str,
    root: str,
    skipped_paths: dict[str, OSError],
    locale: str,
) -> str:
    """掃描有路徑被跳過時的 SSE 警告：根目錄本身沒權限 → 講「沒有權限」（Synology 附 DSM 指引）；其餘維持泛用句（159-T10a）"""
    if isinstance(skipped_paths.get(root), PermissionError):
        return _permission_denied_warning(directory, locale)
    return _runtime_text(
        "scanner",
        "paths_skipped",
        locale,
        path=directory,
        count=len(skipped_paths),
    )


def _empty_source_scan_stats() -> dict[str, Any]:
    return {
        "inserted": 0,
        "updated": 0,
        "deleted": 0,
        "scan_errors": 0,
        "session_added_paths": [],
        "long_paths": [],
    }


def _collect_scan_refresh_sets(
    all_files: list[dict[str, Any]],
    db_index: dict,
    path_mappings: dict,
) -> tuple[list[dict[str, Any]], set[str], set[str]]:
    """Classify scanned files without mutating the database."""
    needs_scan = []
    current_paths = set()
    nfo_unchanged_paths = set()
    for file_info in all_files:
        path = file_info['path']
        file_uri = to_file_uri(path, path_mappings)
        current_paths.add(file_uri)

        db_entry = db_index.get(file_uri)
        if scan_entry_needs_refresh(db_entry, file_info, path_mappings):
            # 新檔案、mtime/NFO/劇照變更，或 DB 仍缺基本資料／可服務封面。
            needs_scan.append(file_info)
            if (
                db_entry is not None
                and db_entry[1] == file_info.get('nfo_mtime', 0)
            ):
                nfo_unchanged_paths.add(file_uri)
    return needs_scan, current_paths, nfo_unchanged_paths


def _scan_changed_files(
    needs_scan: list[dict[str, Any]],
    scanner: VideoScanner,
    existing_by_uri: dict,
    nfo_unchanged_paths: set[str],
    should_abort: Optional[Callable[[], bool]],
    locale: str,
) -> Generator[str, None, tuple[list[Video], list[str], int, int, list[str]]]:
    """Scan changed files and return videos plus per-source counters."""
    videos_to_upsert: list[Video] = []
    session_added_paths: list[str] = []
    cache_misses = 0
    scan_error_count = 0
    scan_error_paths: list[str] = []

    for index, file_info in enumerate(needs_scan, 1):
        # TASK-90b-T4: 逐檔中止檢查（每檔處理之前）。單一資料夾內
        # 檔案量大時，逐來源層檢查粒度太粗，需要在此內層迴圈頂端
        # 再插一次，讓中止在「下一個可偵測的時間點」生效（不中斷
        # 正在進行中的單一 scan_file() 呼叫）。
        if should_abort and should_abort():
            break

        video_name = os.path.basename(file_info['path'])
        yield _sse_event({
            "type": "log",
            "level": "info",
            "message": f"  [{index}/{len(needs_scan)}] {video_name}",
        })

        try:
            video_info = scanner.scan_file(file_info['path'], None)
            video = Video.from_video_info(video_info)
            existing = existing_by_uri.get(video.path)
            if existing is not None:
                if video.path in nfo_unchanged_paths:
                    video.preserve_existing_metadata(existing)
                else:
                    video.preserve_missing_metadata(existing)
            video.mtime = file_info['mtime']
            video.nfo_mtime = file_info.get('nfo_mtime', 0)
            videos_to_upsert.append(video)
            session_added_paths.append(video.path)
            cache_misses += 1
        except Exception:
            logger.exception("掃描檔案失敗: %s", file_info.get('path', ''))
            scan_error_paths.append(file_info['path'])
            yield _sse_event({
                "type": "log",
                "level": "warn",
                "message": _runtime_text(
                    "scanner", "file_scan_failed", locale, index=index
                ),
            })
            scan_error_count += 1

    return (
        videos_to_upsert,
        session_added_paths,
        cache_misses,
        scan_error_count,
        scan_error_paths,
    )


def _submit_focal_candidates(
    repo: VideoRepository,
    current_paths: set[str],
    path_mappings: dict,
    should_abort: Optional[Callable[[], bool]],
) -> None:
    """Queue eligible empty-focal candidates from the current source."""
    # TASK-98b-T2 / Codex PR#105 P2：涵蓋本次掃描 in-scope 的所有空焦點無碼片，
    # 不只 upsert batch（needs_scan）——既有、未變動、auto_focal='' 的列也要補。
    if not current_paths or (should_abort and should_abort()):
        return

    focal_candidates = repo.get_empty_focal_candidates(list(current_paths))
    for candidate_path, number, maker, cover_path in focal_candidates:
        # 候選數可達數千；取消可能落在迴圈中途，因此每圈 fresh 查一次。
        if should_abort and should_abort():
            break
        if requires_face_detection(number, maker):
            cover_fs = uri_to_local_fs_path(cover_path, path_mappings)
            maybe_submit_video_focal(
                number,
                maker,
                candidate_path,
                cover_fs,
                db_path=repo.db_path,
                cover_path_uri=cover_path,
            )


def _scan_regular_source(
    *,
    directory: str,
    normalized_dir: str,
    scanner: VideoScanner,
    repo: VideoRepository,
    config: dict,
    min_size_mb: int,
    path_mappings: dict,
    should_abort: Optional[Callable[[], bool]],
) -> Generator[str, None, dict[str, Any]]:
    """Scan one writable source while preserving SSE and cancellation semantics."""
    stats = _empty_source_scan_stats()
    locale = get_config_locale(config)
    skip_message = _scan_root_skip_message(directory, normalized_dir, locale)
    if skip_message is not None:
        yield _sse_event({"type": "log", "level": "warn", "message": skip_message})
        return stats

    try:
        min_size_bytes = min_size_mb * 1024 * 1024
        video_extensions = get_video_extensions(config)
        # a5 Codex fix: 收集因 OSError/PermissionError 被跳過的路徑
        # （含 Windows 長路徑觸發的 OSError — 這些 entry 根本不會進 all_files）
        skipped_paths: dict[str, OSError] = {}
        all_files = fast_scan_directory(
            normalized_dir,
            video_extensions,
            min_size_bytes,
            on_skip=lambda path, error: skipped_paths.__setitem__(path, error),
        )

        if not all_files and not skipped_paths:
            yield _sse_event({
                "type": "log",
                "level": "info",
                "message": _runtime_text(
                    "scanner", "no_videos", locale, path=directory
                ),
            })
            return stats

        # a5: Windows 長路徑警告（gate 在呼叫端，不在 helper）
        if sys.platform == 'win32':
            stats["long_paths"].extend(_collect_long_paths(all_files))
            # 把因長度而失敗的 skipped 路徑也納入警告（filter >260 過濾非長路徑失敗）
            stats["long_paths"].extend(
                path for path in skipped_paths if len(path) > 260
            )

        yield _sse_event({
            "type": "log",
            "level": "info",
            "message": _runtime_text(
                "scanner",
                "files_found",
                locale,
                path=directory,
                count=len(all_files),
            ),
        })

        db_index = repo.get_mtime_index()
        needs_scan, current_paths, nfo_unchanged_paths = _collect_scan_refresh_sets(
            all_files,
            db_index,
            path_mappings,
        )

        # 清理已刪除的檔案（限定在此目錄下）。partial scan 只做 insert/update，
        # 不能 infer 刪除，否則讀取失敗會被誤判成檔案已刪除。
        if skipped_paths:
            yield _sse_event({
                "type": "log",
                "level": "warn",
                "message": _skipped_scan_warning(
                    directory, normalized_dir, skipped_paths, locale
                ),
            })
        else:
            normalized_dir_uri = to_file_uri(normalized_dir, path_mappings)
            deleted_paths = [
                path
                for path in db_index
                if (
                    is_path_under_dir(path, normalized_dir_uri)
                    and path not in current_paths
                )
            ]
            if deleted_paths:
                deleted_count = repo.delete_by_paths(deleted_paths)
                # feature/71 T8: deleted_paths 已是 DB URI，原樣失效縮圖。
                for path in deleted_paths:
                    thumbnail_cache.invalidate(path)
                stats["deleted"] = deleted_count
                yield _sse_event({
                    "type": "log",
                    "level": "info",
                    "message": _runtime_text(
                        "scanner",
                        "deleted_cleaned",
                        locale,
                        count=deleted_count,
                    ),
                })

        cache_hits = len(all_files) - len(needs_scan)
        scan_uris = [
            to_file_uri(file_info['path'], path_mappings)
            for file_info in needs_scan
        ]
        existing_by_uri = repo.get_by_paths(scan_uris)
        (
            videos_to_upsert,
            session_added_paths,
            cache_misses,
            scan_errors,
            scan_error_paths,
        ) = yield from _scan_changed_files(
            needs_scan,
            scanner,
            existing_by_uri,
            nfo_unchanged_paths,
            should_abort,
            locale,
        )

        if videos_to_upsert:
            inserted, updated = repo.upsert_batch(videos_to_upsert)
            stats["inserted"] = inserted
            stats["updated"] = updated

        _submit_focal_candidates(
            repo,
            current_paths,
            path_mappings,
            should_abort,
        )

        if scan_error_paths:
            failed_paths = set(scan_error_paths)
            scan_errors = len({
                index
                for index, group in enumerate(group_rows(
                    all_files,
                    fs_path_of=lambda file_info: file_info["path"],
                ))
                if any(
                    member["path"] in failed_paths
                    for member in group.members
                )
            })

        stats["scan_errors"] = scan_errors
        stats["session_added_paths"] = session_added_paths
        try:
            current_rows = repo.get_all()
            current_logical_count = len(
                _logical_groups_for_paths(
                    current_rows,
                    current_paths,
                    path_mappings,
                )
            )
        except Exception:
            logger.warning(
                "掃描來源後計算邏輯影片數失敗，退回檔案數：%s",
                directory,
                exc_info=True,
            )
            current_logical_count = len(all_files)
        logger.info(
            f"[Gallery] {directory}: {len(all_files)} 個檔案，快取命中 {cache_hits}"
        )
        yield _sse_event({
            "type": "log",
            "level": "info",
            "message": _runtime_text(
                "scanner",
                "source_done",
                locale,
                path=directory,
                count=current_logical_count,
                hits=cache_hits,
                misses=cache_misses,
            ),
        })
    except Exception:
        logger.exception("掃描資料夾失敗: %s", directory)
        stats["scan_errors"] += 1
        yield _sse_event({
            "type": "log",
            "level": "error",
            "message": _runtime_text(
                "scanner", "folder_scan_failed", locale
            ),
        })
    return stats


def generate_avlist(should_abort: Optional[Callable[[], bool]] = None) -> Generator[str, None, None]:
    """產生影片列表（SSE 串流）- 使用 SQLite 儲存"""

    locale = _active_locale()
    try:
        # 載入設定
        config = load_config()
        locale = _active_locale(config)
        gallery_config = config.get('gallery', {})

        directories = get_gallery_source_paths(gallery_config)
        output_dir = gallery_config.get('output_dir', '') or ''
        output_filename = gallery_config.get('output_filename', 'gallery_output.html')
        path_mappings = gallery_config.get('path_mappings', {})
        min_size_mb = gallery_config.get('min_size_mb', 0)

        # 預設顯示設定
        default_mode = gallery_config.get('default_mode', 'image')
        default_sort = gallery_config.get('default_sort', 'date')
        default_order = gallery_config.get('default_order', 'descending')
        items_per_page = gallery_config.get('items_per_page', 90)

        # 取得全域主題設定
        default_theme = config.get('general', {}).get('theme', 'light')

        if not directories:
            yield _sse_event({
                "type": "error",
                "message": _runtime_text(
                    "scanner", "no_directories", locale
                ),
            })
            return

        # 53b-T3: 確認 directories 有值才 emit 掃描開始通知
        _emit_notif("info", "notif.scanner_started", task_type="scanner_generate")
        logger.info(f"[Gallery] 開始生成，目錄數: {len(directories)}")

        # 確保輸出目錄存在（空值 → 資料根；相對／絕對值依 resolve_gallery_output_path）
        output_path = resolve_gallery_output_path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        html_path = output_path / output_filename
        cache_path = output_path / output_filename.replace('.html', '_cache.json')
        db_path = get_db_path()

        yield _sse_event({
            "type": "log",
            "level": "info",
            "message": _runtime_text(
                "scanner", "output_path", locale, path=html_path
            ),
        })

        # 檢查是否需要遷移 JSON cache 到 SQLite
        if cache_path.exists() and not db_path.exists():
            yield _sse_event({
                "type": "log",
                "level": "info",
                "message": _runtime_text(
                    "scanner", "migrating_cache", locale
                ),
            })
            migrate_result = migrate_json_to_sqlite(cache_path, db_path, delete_on_success=True)
            yield _sse_event({
                "type": "log",
                "level": "info",
                "message": _runtime_text(
                    "scanner",
                    "cache_migrated",
                    locale,
                    count=migrate_result['migrated'],
                ),
            })

        # 初始化資料庫
        init_db(db_path)
        repo = VideoRepository(db_path)

        yield _sse_event({
            "type": "log",
            "level": "info",
            "message": _runtime_text(
                "scanner",
                "db_count",
                locale,
                count=logical_video_count(repo.get_all(), path_mappings),
            ),
        })

        # 初始化掃描器
        scanner = VideoScanner(path_mappings=path_mappings, nfo_title_format=config.get('scraper', {}).get('nfo_title_format', '[{num}]{title}'))

        total_dirs = len(directories)
        total_inserted = 0
        total_updated = 0
        total_deleted = 0
        missing_nfo_count = 0
        scan_error_count = 0
        session_added_paths = []  # 追蹤本次新增/變更的影片路徑
        long_paths: list[str] = []  # a5: Windows 長路徑收集（只在 win32 填充）

        # TASK-88c-T2: readonly 來源生成摘要（跨來源累計，迴圈前初始化避免清零）
        readonly_summary = {
            "created": 0, "skipped": 0, "no_scrape": 0, "failed": 0,
            "no_output": 0, "sources": 0, "source_errors": 0,
            "unreachable": 0, "partial": 0, "pruned": 0,
        }

        for idx, src in enumerate(iter_gallery_sources(gallery_config), 1):
            # TASK-90b-T4: 逐來源中止檢查（每個來源處理之前），比照唯讀分支
            # T3 既有語意「這一個單位做完，下一個開始前停」。should_abort 可能
            # 為 None（向後相容），先短路判斷。
            if should_abort and should_abort():
                break

            directory = src.path
            logger.info(f"[Gallery] 掃描: {directory}")

            # TASK-88c-T2: readonly 來源分流（早於 normalize，UNC 主場景不被擋）
            if src.readonly:
                # TASK-89b-T5 / CD-89b-5: 可達性防呆補在 readonly 分流點（:366 的
                # os.path.exists 只在非 readonly 分支執行，readonly 分支需要等義入口
                # 檢查）。src.path 是 config 原始輸入，不套 reverse_path_mapping
                # （比照 :353/:96 既定作法，見 TASK-89b-T5 現況分析 #5）。
                reachable = os.path.exists(uri_to_fs_path(src.path))  # uri-no-reverse: native config path (src.path), no DB-mapped namespace
                # PR #93 五審四次 P2 (option C)：注入 fresh strm 映射 getter。config 是 :303
                # 一次載入的凍結快照；load_config() 無 lru_cache、每次讀 disk，故 getter 拿到
                # 的是「當下磁碟上的」映射 → 斷線尾巴那片也用當前映射。
                yield from _run_readonly_source(
                    src, config, repo, readonly_summary, reachable,
                    should_abort=should_abort,
                    strm_mappings_getter=lambda: load_config().get('scraper', {}).get('strm_path_mappings', {}),
                )
                continue

            # 轉換路徑格式 (Windows -> WSL)。directory 可能是 FS 路徑或 file:/// URI
            # （DirectoryConfig.path schema）。uri_to_fs_path 對 URI→FS、FS→FS 皆冪等，
            # 取代裸 normalize_path（後者對 URI 原樣通過 → os.path.exists 失敗 → 誤報
            # 「資料夾不存在」，非 readonly 的 URI 來源掃不到）。
            try:
                normalized_dir = uri_to_fs_path(directory)  # uri-no-reverse: native config path (DirectoryConfig.path), no DB-mapped namespace
            except ValueError:
                logger.exception("路徑轉換失敗: %s", directory)
                yield _sse_event({
                    "type": "log",
                    "level": "warn",
                    "message": _runtime_text(
                        "scanner", "path_convert_failed", locale
                    ),
                })
                continue

            yield _sse_event({
                "type": "progress",
                "status": _runtime_text(
                    "scanner", "scanning", locale, path=directory
                ),
                "current": idx,
                "total": total_dirs + 1  # +1 for generating
            })
            source_stats = yield from _scan_regular_source(
                directory=directory,
                normalized_dir=normalized_dir,
                scanner=scanner,
                repo=repo,
                config=config,
                min_size_mb=min_size_mb,
                path_mappings=path_mappings,
                should_abort=should_abort,
            )
            total_inserted += source_stats["inserted"]
            total_updated += source_stats["updated"]
            total_deleted += source_stats["deleted"]
            scan_error_count += source_stats["scan_errors"]
            session_added_paths.extend(source_stats["session_added_paths"])
            long_paths.extend(source_stats["long_paths"])

        # TASK-90b-T4 / PR#90b Codex P1: 尾段每個外顯副作用（HTML 檔、完成通知、
        # done event）之前各自 fresh 查一次 should_abort()，而非迴圈結束時單次
        # snapshot。單次 snapshot 會漏掉「迴圈已結束、尾段進行中才斷線」的 race：
        # HTMLGenerator.generate() 期間 client 才斷線時，snapshot 仍為 False，後面
        # 的完成通知與 done event 仍照跑 → 對已中止的掃描誤報 success。改為每個
        # 外顯副作用前重新查詢，把 tail-race 窗口收斂到單一 event.is_set() 呼叫。
        def _is_aborted() -> bool:
            return bool(should_abort and should_abort())

        # 建立「當前設定資料夾」URI 集合，用於過濾 DB 記錄
        # DB 保留所有歷史資料當 cache，但只輸出當前設定的資料夾
        configured_dir_uris = set()
        for p in get_gallery_source_paths(gallery_config):
            try:
                # coerce_to_file_uri：來源 path 可能已是 file:/// URI（含 readonly 剛
                # upsert 的列），已是 URI 就原樣回、FS 才轉，避免 to_file_uri 二次包成
                # file:///file:/// 把 readonly 生成的列全數過濾掉（PR#91 P2-D）。
                configured_dir_uris.add(coerce_to_file_uri(p, path_mappings))  # uri-no-reverse: coerce_to_file_uri forward URI build, D2 complement
            except ValueError:
                continue

        # 從 SQLite 取得影片，只保留當前設定資料夾底下的記錄
        all_db_videos = [v for v in repo.get_all()
                         if any(is_path_under_dir(v.path, uri) for uri in configured_dir_uris)]

        # The generated page can render without an NFO, but title writeback and
        # later metadata maintenance need one. Surface this before the user
        # discovers it while translating a title.
        all_db_groups = logical_video_groups(
            all_db_videos, path_mappings
        )
        missing_nfo_count = sum(
            1
            for group in all_db_groups
            if any(
                not _video_has_nfo(video, path_mappings)
                for video in group.members
            )
        )
        if missing_nfo_count > 0:
            yield _sse_event({
                "type": "log",
                "level": "warn",
                "message": _runtime_text(
                    "scanner",
                    "missing_nfo",
                    locale,
                    count=missing_nfo_count,
                ),
            })

        # 轉換為 VideoInfo 格式供 HTMLGenerator 使用
        all_videos = []
        for group in all_db_groups:
            v = group.members[0]
            info = VideoInfo(
                path=v.path,
                title=v.title,
                originaltitle=v.original_title,
                actor=','.join(v.actresses) if v.actresses else '',
                num=v.number or '',
                maker=v.maker,
                date=v.release_date,
                genre=','.join(v.tags) if v.tags else '',
                user_tags=list(v.user_tags or []),
                size=v.size_bytes,
                mtime=int(v.mtime * 10000000 + 116444736000000000) if v.mtime else 0,
                img=v.cover_path
            )
            all_videos.append(info)

        # 檢查本次新增影片是否需要 NFO 補全（建構相容的 cache 格式）
        session_update = {"count": 0, "paths": []}
        if session_added_paths:
            # 建立只包含本次新增影片的 session_cache（相容 check_cache_needs_update 格式）
            session_cache = {}
            for path in session_added_paths:
                video = repo.get_by_path(path)
                if video:
                    session_cache[path] = {
                        'nfo_mtime': video.nfo_mtime,
                        'info': {
                            'title': video.title,
                            'date': video.release_date,
                            'actor': ','.join(video.actresses) if video.actresses else '',
                            'genre': ','.join(video.tags) if video.tags else '',
                            'maker': video.maker,
                            'num': video.number or '',
                            'director': video.director or '',
                            'duration': video.duration,
                            'series': video.series or '',
                            'label': video.label or '',
                        }
                    }
            if session_cache:
                session_stats = check_cache_needs_update(session_cache)
                session_update_paths = set(session_stats["paths"])
                session_groups = _logical_groups_for_paths(
                    all_db_videos,
                    session_update_paths,
                    path_mappings,
                )
                session_items_by_path = {
                    item.get("path"): item
                    for item in session_stats.get("items", [])
                    if item.get("path")
                }
                grouped_session_items = []
                for _group, member_paths in session_groups:
                    member_items = [
                        session_items_by_path[path]
                        for path in member_paths
                        if path in session_items_by_path
                    ]
                    if member_items:
                        grouped_session_items.append({
                            **member_items[0],
                            "member_paths": member_paths,
                        })
                session_update = {
                    "count": len(session_groups),
                    "paths": [item["path"] for item in grouped_session_items],
                    "items": grouped_session_items,
                    "physical_paths": session_stats["paths"],
                }
                if session_update['count'] > 0:
                    yield _sse_event({
                        "type": "log",
                        "level": "warn",
                        "message": _runtime_text(
                            "scanner",
                            "new_videos_incomplete",
                            locale,
                            count=session_update['count'],
                        ),
                    })

        yield _sse_event({
            "type": "log",
            "level": "info",
            "message": _runtime_text(
                "scanner",
                "db_total",
                locale,
                count=logical_video_count(repo.get_all(), path_mappings),
            ),
        })

        # TASK-90b-T4: abort 時跳過 orphan 清理（全庫 pass，非本次掃描範圍新增
        # 的成本，abort 時執行拿不到「這次掃描結果更完整」的好處，純屬多做一次
        # 不必要的全庫查詢，見決策表）
        if not _is_aborted():
            # §b1 AC#2: sample_images 孤兒清理 pass（Scanner UI 主路徑覆蓋，共用 helper）
            try:
                cleaned = _run_sample_images_cleanup_pass(repo, path_mappings)
                if cleaned > 0:
                    yield _sse_event({
                        "type": "log",
                        "level": "info",
                        "message": _runtime_text(
                            "scanner",
                            "orphan_samples_cleaned",
                            locale,
                            count=cleaned,
                        ),
                    })
            except Exception as e:
                logger.warning("sample_images cleanup pass failed: %s: %s", type(e).__name__, e)
                # 失敗不中斷 scan 流程

        # TASK-90b-T4: abort 時跳過 HTML 產生（成本隨影片數線性成長，是浪費工的
        # 主源；client 已斷線不會有人看這份輸出，見決策表）與對應的「完成」
        # progress event（HTML 都不產生了，沒有對應的真實進度可回報）
        if not _is_aborted():
            # 產生 HTML
            yield _sse_event({
                "type": "progress",
                "status": _runtime_text(
                    "scanner", "generating_html", locale
                ),
                "current": total_dirs,
                "total": total_dirs + 1
            })

            generator = HTMLGenerator()
            generator.generate(
                all_videos,
                str(html_path),
                title="OpenAver Scanner",
                mode=default_mode,
                sort=default_sort,
                order=default_order,
                items_per_page=items_per_page,
                theme=default_theme,
                locale=locale,
            )

            yield _sse_event({
                "type": "progress",
                "status": _runtime_text("scanner", "done", locale),
                "current": total_dirs + 1,
                "total": total_dirs + 1
            })

        logger.info(f"[Gallery] 完成，新增 {total_inserted}，更新 {total_updated}，刪除 {total_deleted}")

        # TASK-88c-T2: readonly 生成摘要 log 行（僅有 readonly 活動時輸出）
        # TASK-89b-T6: unreachable/partial 納入活躍度判斷，否則全 unreachable 的
        # run 這行 log 完全不輸出，debug.log 事後排錯看不到這次唯讀掃描發生過什麼。
        if (readonly_summary["sources"] > 0 or readonly_summary["no_output"] > 0
                or readonly_summary["source_errors"] > 0 or readonly_summary["unreachable"] > 0
                or readonly_summary["partial"] > 0):
            logger.info(
                "唯讀生成完成: 新增 %d／略過 %d／刮不到 %d／失敗 %d／清除 %d"
                "（%d 個來源；%d 個未設輸出夾；%d 個來源錯誤；%d 個來源無法連線；%d 個來源部分讀取失敗）",
                readonly_summary["created"], readonly_summary["skipped"],
                readonly_summary["no_scrape"], readonly_summary["failed"], readonly_summary["pruned"],
                readonly_summary["sources"], readonly_summary["no_output"],
                readonly_summary["source_errors"], readonly_summary["unreachable"],
                readonly_summary["partial"],
            )

        # a5: 寫長路徑清單到 debug.log（helper 內部判斷空 list）
        _emit_long_path_warnings(logger, long_paths)

        # T3(40c) Codex fix: generate 後清空 jellyfin check 快取
        global _jellyfin_cache_result, _jellyfin_cache_time
        _jellyfin_cache_result = None
        _jellyfin_cache_time = 0

        # 53b-T3 / 88c-P2: 掃描完成通知
        # scan_error_count（一般掃描逐檔失敗）與 readonly source_errors（唯讀來源
        # 迴圈前整源拋錯）皆須讓完成通知走 warn，不可純 success（Codex P2：來源級
        # 失敗原本只增 source_errors，完成通知沒納入 → 仍報成功，誤導）。
        # 個別影片失敗（readonly failed，例如 NFO 寫入失敗）同樣須讓完成通知走
        # warn（PR#91 ②）。no_scrape 是「線上查無 metadata」的正常情況，不計入。
        # TASK-89b-T6（Codex Finding-2）：no_output/unreachable/partial 三者原本
        # 被 _accumulate_readonly/_yield_source_summary 安靜吸收，完成通知未讀
        # 它們 → 使用者看到 success，違反 spec §89b.3.3「警告並略過，不誤報成功」。
        # TASK-90b-T4 / PR#90b Codex P1+P2: abort 時不發 success/warn 完成通知（對
        # 已中止的掃描回報「完成」是明確誤報），但**必須**發一筆中性 terminal 通知
        # 與函式開頭無條件 emit 的 scanner_started 配對。通知中心是 append-only 的
        # 全域 deque（web/routers/notifications.py），不依 task_type 撤回或配對，只發
        # started 不發 terminal，會在通知抽屜永久殘留一筆看似未完成的「掃描開始」，
        # 使用者每中止一次就累積一筆錯的狀態（Codex P2）。此處 fresh 再查一次
        # should_abort()（Codex P1：涵蓋 HTML 產生期間才斷線的 tail-race）。
        _aborted = _is_aborted()

        try:
            _wl_removed = reconcile_wishlist()
        except Exception:
            logger.exception("wishlist 對帳失敗（掃描完成收尾）")
            _emit_notif("warn", "notif.wishlist_reconcile_failed", task_type="wishlist_reconcile")
            _wl_removed = []
        if _wl_removed:
            _emit_notif(
                "info", "notif.wishlist_auto_removed",
                message=format_wishlist_removed_message(_wl_removed, locale),
                task_type="wishlist_reconcile",
            )

        if _aborted:
            _emit_notif(
                "info", "notif.scanner_cancelled",
                task_type="scanner_generate",
            )
        else:
            _source_errors = readonly_summary["source_errors"]
            _readonly_failed = readonly_summary["failed"]
            _readonly_no_output = readonly_summary["no_output"]
            _readonly_unreachable = readonly_summary["unreachable"]
            _readonly_partial = readonly_summary["partial"]
            if (scan_error_count > 0 or _source_errors > 0 or _readonly_failed > 0
                    or _readonly_no_output > 0 or _readonly_unreachable > 0 or _readonly_partial > 0):
                _err_parts = []
                if scan_error_count > 0:
                    _err_parts.append(_runtime_text(
                        "notify",
                        "scanner_failed_videos",
                        locale,
                        count=scan_error_count,
                    ))
                if _source_errors > 0:
                    _err_parts.append(_runtime_text(
                        "notify",
                        "scanner_failed_sources",
                        locale,
                        count=_source_errors,
                    ))
                if _readonly_failed > 0:
                    _err_parts.append(_runtime_text(
                        "notify",
                        "scanner_failed_videos",
                        locale,
                        count=_readonly_failed,
                    ))
                if _readonly_no_output > 0:
                    _err_parts.append(_runtime_text(
                        "notify",
                        "scanner_no_output_sources",
                        locale,
                        count=_readonly_no_output,
                    ))
                if _readonly_unreachable > 0:
                    _err_parts.append(_runtime_text(
                        "notify",
                        "scanner_unreachable_sources",
                        locale,
                        count=_readonly_unreachable,
                    ))
                if _readonly_partial > 0:
                    _err_parts.append(_runtime_text(
                        "notify",
                        "scanner_partial_sources",
                        locale,
                        count=_readonly_partial,
                    ))
                _emit_notif(
                    "warn", "notif.scanner_done_with_errors",
                    message=_runtime_text(
                        "notify",
                        "scanner_done_with_errors",
                        locale,
                        count=len(all_videos),
                        details=_runtime_text(
                            "notify", "auto_part_join", locale
                        ).join(_err_parts),
                    ),
                    task_type="scanner_generate",
                )
            else:
                _emit_notif(
                    "success", "notif.scanner_done",
                    message=_runtime_text(
                        "notify",
                        "scanner_done",
                        locale,
                        count=len(all_videos),
                    ),
                    task_type="scanner_generate",
                )

            _schedule_ai_incremental()

            # TASK-90b-T4: abort 時跳過 done event——client 已斷線收不到，且
            # payload 的 output_path/video_count 語意上宣稱「已完成產生」，
            # HTML 根本沒產生會與實際狀態矛盾，見決策表。
            yield _sse_event({
                "type": "done",
                "video_count": len(all_videos),
                "output_path": str(html_path),
                "session_update": session_update,
                "missing_nfo": missing_nfo_count,
                "long_paths": long_paths,  # a5
                "stats": {
                    "inserted": total_inserted,
                    "updated": total_updated,
                    "deleted": total_deleted
                },
                "readonly_stats": readonly_summary  # TASK-88c-T2: 加法式新欄位
            })

    except Exception as e:
        logger.error("產生影片列表失敗: %s", e)
        # T3(40c) Codex fix: exception 路徑也清空快取（DB 可能已被修改）
        # global 已在 try 區塊宣告，此處直接賦值即可
        _jellyfin_cache_result = None
        _jellyfin_cache_time = 0
        # 53b-T3: 掃描失敗通知（不洩漏 str(e) 到前端）
        _emit_notif(
            "error", "notif.scanner_failed",
            message=_runtime_text("scanner", "scan_interrupted", locale),
            task_type="scanner_generate",
        )
        yield _sse_event({
            "type": "error",
            "message": _runtime_text(
                "scanner", "generate_failed", locale
            ),
        })


# TASK-90b-T2: 斷線偵測輪詢間隔（秒）。定案依據見 plan-90b.md CD-90b-5/6：
# spike 實測顯示 Starlette（釘版 starlette==1.3.1）對同步 generator 直接丟給
# StreamingResponse 時，client 斷線僅停止再呼叫 next()，並不會主動對 generator
# 呼叫 .close()（GeneratorExit 備案在此版本上不會被觸發，等 GC 亦不可靠、觀測
# 不到 timely 觸發）；故採方案 A：獨立 asyncio task 主動輪詢
# `request.is_disconnected()`，非搶 iterate_in_threadpool 的同一組 receive
# channel（該輪詢與 StreamingResponse 內部行為互不干擾，spike 已驗證）。
_DISCONNECT_POLL_INTERVAL_SEC = 0.5


async def _cancelable_sse_response(
    request: Request,
    generator_factory: Callable[[threading.Event], Generator[str, None, None]],
) -> StreamingResponse:
    """Wrap a synchronous SSE generator with explicit disconnect cancellation."""
    cancel_event = threading.Event()
    if not try_mark_generate_active(cancel_event):
        try:
            busy_locale = await asyncio.to_thread(
                lambda: get_config_locale(load_config())
            )
        except Exception:
            busy_locale = "zh-CN"
        return StreamingResponse(
            iter([_sse_event({
                "type": "error",
                "message": _runtime_text(
                    "scanner", "busy", busy_locale
                ),
            })]),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    async def _watch_disconnect() -> None:
        try:
            while not cancel_event.is_set():
                if await request.is_disconnected():
                    cancel_event.set()
                    return
                await asyncio.sleep(_DISCONNECT_POLL_INTERVAL_SEC)
        except asyncio.CancelledError:
            raise
        finally:
            mark_generate_done(cancel_event)

    watcher_task = asyncio.create_task(_watch_disconnect())

    async def _cleanup_watcher() -> None:
        mark_generate_done(cancel_event)
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass

    response = StreamingResponse(
        generator_factory(cancel_event),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    response.background = BackgroundTask(_cleanup_watcher)
    response.cancel_event = cancel_event
    response.watcher_task = watcher_task
    return response


@router.get("/generate")
async def generate(request: Request):
    """產生影片列表（SSE 串流回傳進度）

    TASK-90b-T2：加入斷線偵測機制。`cancel_event`（`threading.Event`，非
    `asyncio.Event`——T3 要讓背景 daemon thread 安全讀取）在偵測到 client
    斷線時被設置；本 task 尚未把它串進 `generate_avlist`/`produce_source`
    （那是 T3），此處只負責建立 + 正確設置 + 生命週期收尾。
    """
    cancel_event = threading.Event()
    # Finding 2 + PR #93 P1 雙向互斥：以 cancel_event 為唯一 token 登記「產生進行中」，
    # 讓設定頁切換媒體伺服器模式在 generate 仍跑時被擋。try_mark_generate_active 同時檢查
    # 反方向——若設定頁正在切換模式（purge 窗口中），回 False → 拒絕開始產生，避免背景
    # producer 讀到舊唯讀來源、把剛被 purge 的卡 _upsert 補回（切模式後殭屍卡）。
    if not try_mark_generate_active(cancel_event):
        locale = await asyncio.to_thread(_active_locale)

        async def _refuse_switching():
            yield _sse_event({
                "type": "error",
                "message": _runtime_text("scanner", "config_switching", locale),
            })
        return StreamingResponse(
            _refuse_switching(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    async def _watch_disconnect() -> None:
        try:
            while not cancel_event.is_set():
                if await request.is_disconnected():
                    cancel_event.set()
                    return
                await asyncio.sleep(_DISCONNECT_POLL_INTERVAL_SEC)
        except asyncio.CancelledError:
            # 正常完成路徑：外層 BackgroundTask 收尾時會 cancel 這個 task，
            # 屬預期流程，非錯誤。
            raise
        finally:
            # 兩條路徑皆會走到：斷線 → watcher return → finally；正常完成 →
            # _cleanup_watcher cancel → CancelledError → finally。故此處清 token
            # 可靠涵蓋 normal + disconnect，不會讓「產生中」旗標永久卡住（切換被永久擋）。
            mark_generate_done(cancel_event)

    watcher_task = asyncio.create_task(_watch_disconnect())

    async def _cleanup_watcher() -> None:
        # BackgroundTask：涵蓋「正常完成」路徑——Starlette 於 response 正常
        # 傳輸結束後 await 本 background，cancel 仍在輪詢的 watcher task，不留
        # 孤兒（CD-90b-5 追加 P2）。⚠️ 斷線路徑不靠這裡：starlette 1.3.1 在
        # send() 拋 OSError→ClientDisconnect 時會在 await background 之前就
        # 往上拋，本 background 不會被執行；但斷線路徑的 watcher 已自行偵測到
        # 斷線並 return（task 自然結束），故兩條路徑皆無 dangling task。
        # 正常完成路徑一定走到這裡：即使 watcher task 還沒真正跑過就被 cancel
        # （其 finally 因而不執行），這裡也保證清掉「產生中」token（idempotent），
        # 不讓正常完成後旗標殘留把 mode-switch 永久擋住。斷線路徑靠 watcher finally。
        mark_generate_done(cancel_event)
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass

    response = StreamingResponse(
        generate_avlist(should_abort=cancel_event.is_set),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
    response.background = BackgroundTask(_cleanup_watcher)
    # 測試用掛鉤（不影響 production 行為）：讓
    # tests/unit/test_scanner_generate_disconnect.py 可在不跑真 uvicorn 的
    # 情況下觀察 cancel_event / watcher_task 狀態。
    response.cancel_event = cancel_event
    response.watcher_task = watcher_task
    return response


@router.get("/stats")
def get_stats():
    """取得 Scanner 統計資訊（從 SQLite 讀取）"""
    try:
        db_path = get_db_path()

        if not db_path.exists():
            return {"success": True, "data": {"total": 0, "last_run": None, "last_added": None}}

        repo = VideoRepository(db_path)
        config = load_config()
        path_mappings = (
            config.get("gallery", {}).get("path_mappings", {})
        )
        total = logical_video_count(repo.get_all(), path_mappings)

        return {
            "success": True,
            "data": {
                "total": total,
                "last_run": None,  # SQLite 版本不追蹤 last_run
                "last_added": None,  # SQLite 版本不追蹤 last_added
                "last_total": total
            }
        }
    except Exception as e:
        logger.error("取得統計資訊失敗: %s", e)
        return {
            "success": False,
            "error": _runtime_text("scanner", "stats_failed", _active_locale()),
        }


@router.delete("/cache")
def clear_cache():  # ranker-invalidate-ok: (DELETE FROM videos only in docstring; actual deletion delegates to repo.clear_all() which already calls SimilarRankerCache.invalidate())
    """清除所有影片快取（DELETE FROM videos）"""
    try:
        db_path = get_db_path()

        if not db_path.exists():
            return {
                "success": True,
                "deleted": 0,
                "physical_deleted": 0,
            }

        repo = VideoRepository(db_path)
        config = load_config()
        path_mappings = (
            config.get("gallery", {}).get("path_mappings", {})
        )
        logical_deleted = logical_video_count(
            repo.get_all(),
            path_mappings,
        )
        deleted = repo.clear_all()
        # feature/71 T8: 清空整個縮圖快取目錄（CD-11 / spec 2.A.9）
        thumbnail_cache.clear_all()
        # T3(40c): 清空 jellyfin check 快取
        global _jellyfin_cache_result, _jellyfin_cache_time
        _jellyfin_cache_result = None
        _jellyfin_cache_time = 0
        return {
            "success": True,
            "deleted": logical_deleted,
            "physical_deleted": deleted,
        }
    except Exception as e:
        logger.error("清除快取失敗: %s", e)
        return {
            "success": False,
            "error": _runtime_text("scanner", "cache_clear_failed", _active_locale()),
        }


def _build_nfo_update_cache(all_videos, config) -> tuple:
    """建構 `check_cache_needs_update` 相容的 cache，**並濾掉唯讀來源的列**。

    唯讀零寫入（spec-143 不變式：唯讀 ＝ 一般掃描 ＋ 產物落輸出夾）：
    `update_videos_generator` 寫的是**來源影片旁**的 sidecar NFO
    （`core/nfo_updater.py` 的 `get_nfo_path_from_video` ＝ 影片路徑 `.with_suffix('.nfo')`），
    對唯讀來源就是寫回使用者叫我們別碰的那個資料夾——而唯讀列的 `nfo_mtime` 指的是
    **輸出夾**那份的 mtime、恆 > 0，不濾掉一定會入選。

    判準與 `web/routers/scraper.py` 的批次入口同一套：config 算一次前綴集、逐項純比對、零 I/O。
    **`/update-check` 與 `/update` 共用本 helper**——兩邊各抄一份唯讀判定必然漂移，
    而漂移的形狀是「按鈕說要更新 N 部、實際只更新 M 部」。

    回傳 ``(cache, skipped_readonly, path_mappings)``。
    """
    gallery_config = config.get('gallery', {})
    path_mappings = gallery_config.get('path_mappings', {})
    ro_prefixes = readonly_source_prefixes(gallery_config, path_mappings)
    writable_prefixes = writable_source_prefixes(gallery_config, path_mappings)

    cache = {}
    skipped_readonly = 0
    for v in all_videos:
        if ro_prefixes and is_path_readonly(
            coerce_to_file_uri(v.path, path_mappings), ro_prefixes, writable_prefixes
        ):
            skipped_readonly += 1
            continue
        cache[v.path] = {
            'nfo_mtime': v.nfo_mtime,
            'info': {
                'title': v.title,
                'date': v.release_date,
                'actor': ','.join(v.actresses) if v.actresses else '',
                'genre': ','.join(v.tags) if v.tags else '',
                'maker': v.maker,
                'num': v.number or '',
                'director': v.director or '',
                'duration': v.duration,
                'series': v.series or '',
                'label': v.label or '',
            }
        }
    return cache, skipped_readonly, path_mappings


def _logical_groups_for_paths(rows, included_paths, path_mappings) -> list:
    """Return complete logical groups touched by ``included_paths``.

    ``rows`` must be the complete row set so a filtered maintenance query
    (for example, only a ``cd2`` row) can still be resolved back to its
    ``cd1``/``cd2`` group.  The returned path lists contain only the rows that
    actually need work; other group members are retained as context by the
    group object.
    """
    wanted = set(included_paths)
    result = []
    for group in logical_video_groups(rows, path_mappings):
        member_paths = [
            member.path
            for member in group.members
            if member.path in wanted
        ]
        if member_paths:
            result.append((group, member_paths))
    return result


def _grouped_nfo_stats(all_videos, stats, path_mappings) -> dict:
    """Convert physical NFO-update rows to one display item per video group."""
    physical_by_path = {
        item["path"]: item
        for item in stats.get("items", [])
        if item.get("path")
    }
    logical_items = []
    for group, member_paths in _logical_groups_for_paths(
        all_videos,
        stats.get("paths", []),
        path_mappings,
    ):
        member_items = [
            physical_by_path[path]
            for path in member_paths
            if path in physical_by_path
        ]
        if not member_items:
            continue
        representative = member_items[0]
        missing = sorted({
            field
            for item in member_items
            for field in item.get("missing", [])
        })
        logical_items.append({
            **representative,
            "missing": missing,
            "member_paths": member_paths,
        })

    details = {
        field: sum(
            1
            for item in logical_items
            if field in item.get("missing", [])
        )
        for field in ("title", "date", "actor", "genre", "maker")
    }
    return {
        "need_update": len(logical_items),
        "paths": [item["path"] for item in logical_items],
        "physical_paths": list(stats.get("paths", [])),
        "items": logical_items,
        "details": {
            "no_title": details["title"],
            "no_date": details["date"],
            "no_actor": details["actor"],
            "no_genre": details["genre"],
            "no_maker": details["maker"],
        },
    }


def _logical_nfo_summary(update_stats, groups) -> dict:
    """Aggregate physical update results into logical video counts."""
    total = len(groups)
    failed_paths = {
        str(item.get("path") or "")
        for item in update_stats.get("failed_items", [])
        if item.get("path")
    }
    updated_paths = {
        str(path)
        for path in update_stats.get("updated_paths", [])
        if path
    }
    success = 0
    failed = 0
    skipped = 0
    logical_failed_items = []
    failed_physical_count = len(update_stats.get("failed_items", []))
    for _group, member_paths in groups:
        member_failed_items = [
            item
            for item in update_stats.get("failed_items", [])
            if item.get("path") in member_paths
        ]
        if any(path in failed_paths for path in member_paths):
            failed += 1
            representative = dict(member_failed_items[0])
            representative["member_paths"] = member_paths
            logical_failed_items.append(representative)
        elif any(path in updated_paths for path in member_paths):
            success += 1
        else:
            skipped += 1
    return {
        **update_stats,
        "total": total,
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "failed_items": logical_failed_items,
        "physical_failed_items": failed_physical_count,
    }


def _normalize_tag_source_summary(summary: dict, groups: list) -> dict:
    """Collapse physical tag-source results into logical-video results."""
    path_to_group = {}
    group_members = {
        index: member_paths
        for index, (_group, member_paths) in enumerate(groups)
    }
    for index, member_paths in group_members.items():
        for path in member_paths:
            path_to_group[path] = index

    items_by_group = {}
    for item in summary.get("items", []):
        group_index = path_to_group.get(item.get("path"))
        if group_index is not None:
            items_by_group.setdefault(group_index, []).append(item)

    failed_by_group = {}
    for item in summary.get("failed_items", []):
        group_index = path_to_group.get(item.get("path"))
        if group_index is not None:
            failed_by_group.setdefault(group_index, []).append(item)

    logical_items = []
    failed_items = []
    changed_numbers = []
    success_count = 0
    changed_count = 0
    unchanged_count = 0
    skipped_count = 0
    no_nfo_count = 0
    for group_index in range(len(groups)):
        member_paths = group_members[group_index]
        failed_members = failed_by_group.get(group_index, [])
        member_items = items_by_group.get(group_index, [])
        if failed_members:
            representative = {
                **failed_members[0],
                "member_paths": member_paths,
            }
            failed_items.append(representative)
            continue
        if not member_items:
            continue

        representative = {
            **member_items[0],
            "member_paths": member_paths,
        }
        if any(item.get("status") == "changed" for item in member_items):
            representative["status"] = "changed"
            changed_count += 1
            if representative.get("number"):
                changed_numbers.append(representative["number"])
        elif any(item.get("status") == "unchanged" for item in member_items):
            representative["status"] = "unchanged"
            unchanged_count += 1
        else:
            skipped_count += 1
        success_count += 1
        if any(not item.get("nfo_path") for item in member_items):
            no_nfo_count += 1
        logical_items.append(representative)

    summary.update({
        "total": len(groups),
        "success": success_count,
        "changed": changed_count,
        "unchanged": unchanged_count,
        "skipped": skipped_count,
        "failed": len(failed_items),
        "no_nfo": no_nfo_count,
        "items": logical_items,
        "failed_items": failed_items,
        "changed_numbers": list(dict.fromkeys(changed_numbers)),
    })
    return summary


def _validate_batch_source(
    source: str,
    config: dict,
    *,
    action: str | None = None,
    action_key: str | None = None,
    locale: str | None = None,
    allow_manual_only: frozenset[str] = _MAINTENANCE_MANUAL_SOURCES,
) -> Optional[str]:
    """Return a user-facing error for sources that cannot run in a batch."""
    locale = _active_locale(config) if locale is None else locale
    if action_key:
        action = _runtime_text("scanner", action_key, locale)
    action = action or ""
    if source == "auto":
        return None
    if source.startswith("custom:") and not any(
        isinstance(row, dict) and row.get("id") == source and row.get("enabled")
        for row in config.get("sources", [])
    ):
        return _runtime_text(
            "scanner", "batch_custom_unsupported", locale, action=action
        )
    if not validate_source_id(source):
        return _runtime_text("scanner", "batch_unknown_source", locale)
    if (
        source in {row.id for row in get_manual_only_sources()}
        and source not in allow_manual_only
    ):
        return _runtime_text(
            "scanner", "batch_cloudflare_unsupported", locale, action=action
        )
    source_row = next(
        (
            row
            for row in config.get("sources", [])
            if isinstance(row, dict) and row.get("id") == source
        ),
        None,
    )
    if (
        source_row
        and source_row.get("manual_only")
        and source not in allow_manual_only
    ):
        return _runtime_text(
            "scanner", "batch_cloudflare_unsupported", locale, action=action
        )
    # Manual-only sources stay out of automatic fan-out, but a source can be
    # explicitly selected for maintenance, independent of automatic scan toggles.
    if source in allow_manual_only:
        return None
    if not source_row or not source_row.get("enabled"):
        return _runtime_text("scanner", "batch_source_disabled", locale)
    return None


def _validate_batch_tag_source(
    source: str,
    config: dict,
    *,
    locale: str | None = None,
) -> Optional[str]:
    return _validate_batch_source(
        source,
        config,
        action_key="batch_action_tag",
        locale=locale,
        allow_manual_only=_TAG_SOURCE_MANUAL_ALLOWLIST,
    )


def _resolve_tag_update_nfo_path(
    video: Video,
    path_mappings: dict,
    readonly: bool,
) -> Optional[str]:
    """Resolve the NFO to rewrite, including readonly output directories."""
    if not readonly:
        writable_nfo = get_nfo_path_from_video(video.path, path_mappings)
        if writable_nfo:
            return writable_nfo

    if not video.output_dir:
        return None

    output_dir = Path(uri_to_local_fs_path(video.output_dir, path_mappings))
    if video.cover_path:
        cover_fs = uri_to_local_fs_path(video.cover_path, path_mappings)
        cover_nfo = Path(cover_base_stem(cover_fs) + ".nfo")
        if cover_nfo.is_file():
            return str(cover_nfo)

    try:
        candidates = sorted(
            path
            for path in output_dir.iterdir()
            if path.is_file() and path.suffix.casefold() == ".nfo"
        )
    except OSError:
        candidates = []
    if len(candidates) == 1:
        return str(candidates[0])
    return None


def _tag_diff(current_tags: list[str], proposed_tags: list[str]) -> dict:
    """Return a stable, case-insensitive tag diff for preview and task logs."""
    current_map = {str(tag).strip().casefold(): str(tag).strip() for tag in current_tags if str(tag).strip()}
    proposed_map = {str(tag).strip().casefold(): str(tag).strip() for tag in proposed_tags if str(tag).strip()}
    return {
        "added": [tag for key, tag in proposed_map.items() if key not in current_map],
        "removed": [tag for key, tag in current_map.items() if key not in proposed_map],
        "unchanged": len(current_map.keys() & proposed_map.keys()),
    }


def generate_tag_source_update(
    source: str,
    cancel_event: Optional[threading.Event] = None,
    *,
    dry_run: bool = False,
    numbers: Optional[set[str]] = None,
    backup: bool = False,
) -> Generator[str, None, None]:
    """Preview or replace only ordinary NFO/DB tags from one selected source."""
    locale = _active_locale()
    summary = {
        "mode": "preview" if dry_run else "update",
        "total": 0,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "changed": 0,
        "unchanged": 0,
        "no_nfo": 0,
        "backed_up": 0,
        "cancelled": False,
        "failed_items": [],
        "items": [],
        "changed_numbers": [],
    }
    try:
        config = load_config()
        locale = _active_locale(config)
        source_error = _validate_batch_tag_source(source, config, locale=locale)
        if source_error:
            yield _sse_event({"type": "error", "message": source_error})
            return

        db_path = get_db_path()
        if not db_path.exists():
            yield _sse_event({
                "type": "error",
                "message": _runtime_text(
                    "scanner", "db_missing", locale
                ),
            })
            return

        repo = VideoRepository(db_path)
        all_videos = repo.get_all()
        videos = [
            video for video in all_videos
            if video.number and (not numbers or video.number in numbers)
        ]
        gallery_config = config.get("gallery", {})
        path_mappings = gallery_config.get("path_mappings", {})
        logical_groups = _logical_groups_for_paths(
            all_videos,
            [video.path for video in videos],
            path_mappings,
        )
        path_to_group = {
            path: index
            for index, (_group, member_paths) in enumerate(logical_groups)
            for path in member_paths
        }
        summary["total"] = len(logical_groups)
        if not videos:
            yield _sse_event({
                "type": "done",
                "message": _runtime_text(
                    "scanner", "tag_source_none", locale
                ),
                "summary": summary,
            })
            return

        readonly_prefixes = readonly_source_prefixes(gallery_config, path_mappings)
        writable_prefixes = writable_source_prefixes(gallery_config, path_mappings)
        javbus_lang = get_javbus_lang()
        started_at = time.monotonic()
        seen_group_progress = set()

        for index, video in enumerate(videos, start=1):
            if cancel_event is not None and cancel_event.is_set():
                summary["cancelled"] = True
                break

            elapsed = max(time.monotonic() - started_at, 0.001)
            eta_seconds = round((elapsed / max(index - 1, 1)) * max(len(videos) - index + 1, 0))
            group_index = path_to_group.get(video.path)
            if group_index not in seen_group_progress:
                seen_group_progress.add(group_index)
                yield _sse_event({
                    "type": "progress",
                    "current": len(seen_group_progress),
                    "total": len(logical_groups),
                    "number": video.number,
                    "status": _runtime_text(
                        "scanner",
                        "tag_preview" if dry_run else "tag_update",
                        locale,
                        number=video.number,
                    ),
                    "success": summary["success"],
                    "failed": summary["failed"],
                    "skipped": summary["skipped"],
                    "changed": summary["changed"],
                    "eta_seconds": eta_seconds,
                })

            fetch_failed = False
            retried_after_cf = False
            while True:
                try:
                    metadata = search_jav(
                        video.number,
                        source=source,
                        javbus_lang=javbus_lang,
                        surface_access_errors=True,
                    )
                    break
                except CfChallengeRequired:
                    if retried_after_cf:
                        yield _sse_event({
                            "type": "error",
                            "message": _runtime_text(
                                "scanner",
                                "tag_source_cf_rejected",
                                locale,
                                source=source_display_name(source),
                            ),
                        })
                        return

                    transport = get_cf_transport()
                    origin = cf_handoff.CF_SITE_ORIGINS.get(source)
                    if transport is None or origin is None:
                        yield _sse_event({
                            "type": "error",
                            "message": _runtime_text(
                                "scanner",
                                "tag_source_cf_unavailable",
                                locale,
                                source=source_display_name(source),
                            ),
                        })
                        return
                    try:
                        transport.begin_solve(origin, source)
                    except Exception:
                        logger.exception(
                            "tag source CF begin_solve failed: source=%s",
                            source,
                        )
                        yield _sse_event({
                            "type": "error",
                            "message": _runtime_text(
                                "scanner",
                                "tag_source_cf_unavailable",
                                locale,
                                source=source_display_name(source),
                            ),
                        })
                        return

                    retried_after_cf = True
                    cf_status = _runtime_text(
                        "scanner",
                        "tag_source_cf_required",
                        locale,
                        source=source_display_name(source),
                    )
                    yield _sse_event({
                        "type": "progress",
                        "current": len(seen_group_progress),
                        "total": len(logical_groups),
                        "number": video.number,
                        "status": cf_status,
                        "success": summary["success"],
                        "failed": summary["failed"],
                        "skipped": summary["skipped"],
                        "changed": summary["changed"],
                    })
                    yield _sse_event({
                        "type": "log",
                        "level": "info",
                        "message": cf_status,
                    })

                    deadline = time.monotonic() + _TAG_SOURCE_CF_WAIT_SECONDS
                    ready = False
                    cf_error = ""
                    while time.monotonic() < deadline:
                        if cancel_event is not None and cancel_event.is_set():
                            summary["cancelled"] = True
                            break
                        try:
                            ready = bool(transport.is_ready(source))
                        except CfTransportUnavailable:
                            cf_error = "unavailable"
                            break
                        except Exception:
                            logger.warning(
                                "tag source CF readiness check failed: source=%s",
                                source,
                                exc_info=True,
                            )
                        if ready:
                            break
                        time.sleep(_TAG_SOURCE_CF_POLL_SECONDS)

                    if summary["cancelled"]:
                        break
                    if not ready:
                        key = (
                            "tag_source_cf_unavailable"
                            if cf_error == "unavailable"
                            else "tag_source_cf_timeout"
                        )
                        yield _sse_event({
                            "type": "error",
                            "message": _runtime_text(
                                "scanner",
                                key,
                                locale,
                                source=source_display_name(source),
                            ),
                        })
                        return

                    cf_ready_message = _runtime_text(
                        "scanner",
                        "tag_source_cf_ready",
                        locale,
                        source=source_display_name(source),
                    )
                    yield _sse_event({
                        "type": "log",
                        "level": "info",
                        "message": cf_ready_message,
                    })
                    continue
                except CfTransportUnavailable:
                    yield _sse_event({
                        "type": "error",
                        "message": _runtime_text(
                            "scanner",
                            "tag_source_cf_unavailable",
                            locale,
                            source=source_display_name(source),
                        ),
                    })
                    return
                except Exception as exc:
                    summary["failed"] += 1
                    summary["failed_items"].append({
                        "path": video.path,
                        "number": video.number,
                        "error": str(exc),
                    })
                    logger.warning(
                        "tag source update failed: source=%s number=%s error=%s",
                        source,
                        video.number,
                        exc,
                    )
                    yield _sse_event({
                        "type": "log",
                        "level": "error",
                        "message": _runtime_text(
                            "scanner",
                            "tag_source_fetch_failed",
                            locale,
                            number=video.number,
                            error=str(exc),
                        ),
                    })
                    fetch_failed = True
                    break

            if summary["cancelled"]:
                break
            if fetch_failed:
                continue

            if not metadata:
                summary["failed"] += 1
                summary["failed_items"].append({
                    "path": video.path,
                    "number": video.number,
                    "error": _runtime_text(
                        "scanner",
                        "tag_source_no_result",
                        locale,
                        number=video.number,
                    ),
                })
                yield _sse_event({
                    "type": "log",
                    "level": "warn",
                    "message": _runtime_text(
                        "scanner",
                        "tag_source_no_result",
                        locale,
                        number=video.number,
                    ),
                })
                continue

            raw_tags = metadata.get("tags") or []
            if isinstance(raw_tags, str):
                raw_tags = [raw_tags]
            source_tags = [
                str(tag).strip()
                for tag in raw_tags
                if tag is not None and str(tag).strip()
            ]
            if not source_tags:
                summary["skipped"] += 1
                summary["items"].append({
                    "path": video.path,
                    "number": video.number,
                    "status": "no_tags",
                    "current_tags": list(video.tags or []),
                    "proposed_tags": [],
                    "added": [],
                    "removed": [],
                })
                yield _sse_event({
                    "type": "log",
                    "level": "warn",
                    "message": _runtime_text(
                        "scanner",
                        "tag_source_no_tags",
                        locale,
                        number=video.number,
                    ),
                })
                continue

            video_fs_path = uri_to_local_fs_path(video.path, path_mappings)
            filename = os.path.basename(video_fs_path)
            has_subtitle = check_subtitle(filename) or bool(
                find_subtitle_files(video_fs_path)
            )
            tag_basis = list(source_tags)
            if has_subtitle:
                tag_basis.append("中文字幕")
            merged_tags = effective_tags(filename, tag_basis)
            readonly = bool(
                readonly_prefixes
                and is_path_readonly(
                    coerce_to_file_uri(video.path, path_mappings),
                    readonly_prefixes,
                    writable_prefixes,
                )
            )
            nfo_path = _resolve_tag_update_nfo_path(video, path_mappings, readonly)
            current_tags = read_nfo_tags(nfo_path) if nfo_path else list(video.tags or [])
            diff = _tag_diff(current_tags, merged_tags)
            changed = bool(diff["added"] or diff["removed"])
            item = {
                "path": video.path,
                "number": video.number,
                "nfo_path": nfo_path or "",
                "current_tags": current_tags,
                "proposed_tags": merged_tags,
                "added": diff["added"],
                "removed": diff["removed"],
                "status": "changed" if changed else "unchanged",
            }

            if dry_run:
                summary["success"] += 1
                summary["changed" if changed else "unchanged"] += 1
                if changed:
                    summary["changed_numbers"].append(video.number)
                if not nfo_path:
                    summary["no_nfo"] += 1
                summary["items"].append(item)
                yield _sse_event({
                    "type": "log",
                    "level": "info",
                    "message": _runtime_text(
                        "scanner",
                        "tag_source_changed" if changed else "tag_source_unchanged",
                        locale,
                        number=video.number,
                        added=len(diff['added']),
                        removed=len(diff['removed']),
                    ),
                })
                continue

            if nfo_path and backup:
                try:
                    backup_path = backup_nfo_file(nfo_path)
                    if backup_path:
                        summary["backed_up"] += 1
                except Exception as exc:
                    summary["failed"] += 1
                    summary["failed_items"].append({
                        "path": video.path,
                        "number": video.number,
                        "error": _runtime_text(
                            "scanner",
                            "tag_source_nfo_backup_failed",
                            locale,
                            number=video.number,
                            error=str(exc),
                        ),
                    })
                    yield _sse_event({
                        "type": "log",
                        "level": "error",
                        "message": _runtime_text(
                            "scanner",
                            "tag_source_nfo_backup_failed",
                            locale,
                            number=video.number,
                            error=str(exc),
                        ),
                    })
                    continue

            if nfo_path and not replace_nfo_tags(nfo_path, merged_tags):
                summary["failed"] += 1
                summary["failed_items"].append({
                    "path": video.path,
                    "number": video.number,
                    "error": _runtime_text(
                        "scanner",
                        "tag_source_nfo_failed",
                        locale,
                        number=video.number,
                    ),
                })
                yield _sse_event({
                    "type": "log",
                    "level": "error",
                    "message": _runtime_text(
                        "scanner",
                        "tag_source_nfo_failed",
                        locale,
                        number=video.number,
                    ),
                })
                continue

            try:
                db_changed = repo.update_tags_if_changed(video.path, merged_tags)
            except Exception as exc:
                summary["failed"] += 1
                summary["failed_items"].append({
                    "path": video.path,
                    "number": video.number,
                    "error": _runtime_text(
                        "scanner",
                        "tag_source_db_failed",
                        locale,
                        number=video.number,
                    ),
                })
                logger.warning(
                    "tag source update: database update failed for %s: %s",
                    video.path,
                    exc,
                )
                yield _sse_event({
                    "type": "log",
                    "level": "error",
                    "message": _runtime_text(
                        "scanner",
                        "tag_source_db_failed",
                        locale,
                        number=video.number,
                    ),
                })
                continue

            if nfo_path:
                try:
                    repo.update_titles(
                        video.path,
                        video.title,
                        video.original_title,
                        Path(nfo_path).stat().st_mtime,
                    )
                except Exception:
                    logger.warning(
                        "tag source update: failed to refresh nfo mtime for %s",
                        video.path,
                        exc_info=True,
                    )
            else:
                summary["no_nfo"] += 1

            summary["success"] += 1
            summary["changed" if changed else "unchanged"] += 1
            if changed:
                summary["changed_numbers"].append(video.number)
            summary["items"].append(item)
            yield _sse_event({
                "type": "log",
                "level": "info",
                "message": _runtime_text(
                    "scanner",
                    (
                        "tag_updated_db_only"
                        if not nfo_path
                        else "tag_updated_unchanged"
                        if not db_changed
                        else "tag_updated"
                    ),
                    locale,
                    number=video.number,
                    count=len(merged_tags),
                ),
            })

        _normalize_tag_source_summary(summary, logical_groups)

        if summary["cancelled"]:
            message = _runtime_text(
                "scanner",
                "tag_preview_cancelled" if dry_run else "tag_update_cancelled",
                locale,
            )
        elif dry_run:
            message = _runtime_text(
                "scanner",
                "tag_preview_done",
                locale,
                changed=summary['changed'],
                unchanged=summary['unchanged'],
                failed=summary['failed'],
                skipped=summary['skipped'],
            )
        else:
            message = _runtime_text(
                "scanner",
                "tag_update_done",
                locale,
                success=summary['success'],
                failed=summary['failed'],
                skipped=summary['skipped'],
                no_nfo=summary['no_nfo'],
            )
        yield _sse_event({
            "type": "done",
            "message": message,
            "summary": summary,
            "preview": dry_run,
        })
    except Exception:
        logger.exception("批量更换标签来源失败: source=%s", source)
        yield _sse_event({
            "type": "error",
            "message": _runtime_text(
                "scanner", "tag_source_failed", locale
            ),
        })
    finally:
        if cancel_event is not None:
            mark_generate_done(cancel_event)


@router.get("/update-check")
def check_update():
    """檢查需要更新的影片數量（從 SQLite 讀取）"""
    try:
        db_path = get_db_path()

        if not db_path.exists():
            return {"success": True, "data": {"need_update": 0}}

        repo = VideoRepository(db_path)
        all_videos = repo.get_all()

        config = load_config()
        cache, _skipped_readonly, path_mappings = _build_nfo_update_cache(
            all_videos,
            config,
        )

        stats = check_cache_needs_update(cache)
        grouped = _grouped_nfo_stats(
            all_videos,
            stats,
            path_mappings,
        )

        return {
            "success": True,
            "data": grouped,
        }
    except Exception as e:
        logger.error("檢查更新數量失敗: %s", e)
        return {
            "success": False,
            "error": _runtime_text(
                "scanner", "update_check_failed", _active_locale()
            ),
        }


def _video_has_nfo(video: Video, path_mappings: dict) -> bool:
    """Return whether a row has a usable NFO.

    Check the two real locations (source sidecar and output folder) whenever
    the video path is accessible. This catches stale ``nfo_mtime`` values and
    legacy ``.nfo.xml`` names. The DB signal remains the fallback for
    inaccessible/legacy rows (for example old cache entries).
    """
    try:
        video_path = uri_to_local_fs_path(video.path, path_mappings)
        video_path_accessible = os.path.isfile(video_path)
        if video.output_dir:
            output_dir = Path(
                uri_to_local_fs_path(video.output_dir, path_mappings)
            )
            if video_path_accessible and output_dir.is_dir():
                if any(
                    entry.is_file() and entry.name.lower().endswith(".nfo")
                    for entry in output_dir.iterdir()
                ):
                    return True
        if video_path_accessible:
            return bool(get_nfo_path_from_video(video.path, path_mappings))
    except (OSError, ValueError, TypeError):
        pass
    return (video.nfo_mtime or 0) > 0


def _candidate_number(video: Video) -> str:
    """Recover a usable number for maintenance rows with stale NULL values."""
    if video.number:
        return video.number
    filename = video.path.rstrip("/").rsplit("/", 1)[-1]
    return extract_number(filename) or extract_number(video.title or "") or ""


def _is_untranslated_title_candidate(
    video: Video,
    locale: str | None = None,
) -> bool:
    """Return whether a title is not in the active UI language."""
    title = (video.title or "").strip()
    return bool(
        title
        and title_needs_translation(
            title,
            locale or _active_locale(),
            proper_terms=video.actresses or (),
        )
    )


def _is_missing_sample_candidate(video: Video) -> bool:
    """A sample list is present only when it contains at least one usable URI."""
    samples = video.sample_images
    if not isinstance(samples, list):
        return True
    return not any(
        isinstance(url, str) and url.strip()
        for url in samples
    )


def _dedupe_multipart_sample_candidates(
    repo: VideoRepository,
    candidates: List[Video],
    path_mappings: dict,
) -> List[Video]:
    """Collapse complete multipart rows to one logical sample-backfill item.

    ``fetch_samples_endpoint`` writes one shared ``extrafanart`` directory and
    updates every member row.  Scheduling cd1 and cd2 independently would
    scrape/download the same work twice concurrently, so the queue and the
    missing-count preview both use the same representative-per-group rule.
    Resolution failures preserve the old one-row-per-candidate behaviour.
    """
    if len(candidates) < 2:
        return candidates
    try:
        groups = resolve_groups_bulk(
            repo,
            [video.path for video in candidates],
            path_mappings,
        )
    except Exception:
        logger.warning(
            "批次補齊劇照：分集分組失敗，保留逐列候選",
            exc_info=True,
        )
        return candidates

    seen_groups = set()
    deduped = []
    for video in candidates:
        group = groups.get(video.path)
        if group is not None and len(group.members) > 1:
            group_key = tuple(member.path for member in group.members)
            if group_key in seen_groups:
                continue
            seen_groups.add(group_key)
        deduped.append(video)
    return deduped


@router.get("/missing-check")
def check_missing():
    """Check missing NFO/cover plus the two explicit backfill queues."""
    try:
        db_path = get_db_path()

        if not db_path.exists():
            return {
                "success": True,
                "data": {
                    "missing_both": 0,
                    "missing_nfo": 0,
                    "missing_cover": 0,
                    "total_missing": 0,
                    "items": [],
                    "untranslated_titles": 0,
                    "missing_samples": 0,
                    "missing_plots": 0,
                    "untranslated_title_items": [],
                    "missing_sample_items": [],
                    "missing_plot_items": [],
                },
            }

        repo = VideoRepository(db_path)
        all_videos = repo.get_all()
        config = load_config()
        path_mappings = config.get("gallery", {}).get("path_mappings", {})
        locale = _active_locale(config)

        missing_both = 0
        missing_nfo = 0
        missing_cover = 0
        items = []
        untranslated_title_items = []
        missing_sample_items = []

        groups = list(logical_video_groups(all_videos, path_mappings))
        missing_plot_candidates = find_missing_plot_candidates(
            groups,
            config,
            path_mappings,
        )
        missing_plot_items = [
            {
                "file_path": candidate.file_path,
                "number": candidate.number,
                "title": candidate.title,
                "member_paths": list(candidate.member_paths),
            }
            for candidate in missing_plot_candidates
        ]

        for group in groups:
            members = group.members
            untranslated_members = [
                video
                for video in members
                if _is_untranslated_title_candidate(video, locale)
            ]
            if untranslated_members:
                title_candidate = untranslated_members[0]
                untranslated_title_items.append({
                    "file_path": title_candidate.path,
                    "number": _candidate_number(title_candidate),
                    "title": title_candidate.title,
                    "member_paths": [
                        video.path for video in untranslated_members
                    ],
                })

            sample_missing_members = [
                video
                for video in members
                if _is_missing_sample_candidate(video)
            ]
            if sample_missing_members:
                sample_candidate = next(
                    (
                        video
                        for video in sample_missing_members
                        if _candidate_number(video)
                    ),
                    sample_missing_members[0],
                )
                missing_sample_items.append({
                    "file_path": sample_candidate.path,
                    "number": _candidate_number(sample_candidate),
                    "title": sample_candidate.title,
                    "member_paths": [
                        video.path for video in sample_missing_members
                    ],
                })

            nfo_missing_members = []
            cover_missing_members = []
            for video in members:
                if not _video_has_nfo(video, path_mappings):
                    nfo_missing_members.append(video)
                has_cover = False
                if video.cover_path:
                    try:
                        has_cover = os.path.isfile(
                            uri_to_local_fs_path(
                                video.cover_path, path_mappings
                            )
                        )
                    except Exception:
                        has_cover = False
                if not has_cover:
                    cover_missing_members.append(video)

            if not nfo_missing_members and not cover_missing_members:
                continue

            repair_by_path = {
                video.path: video
                for video in [
                    *nfo_missing_members,
                    *cover_missing_members,
                ]
            }
            repair_members = list(repair_by_path.values())
            candidate = next(
                (
                    video
                    for video in repair_members
                    if _candidate_number(video)
                ),
                None,
            )
            if candidate is None:
                continue
            number = _candidate_number(candidate)
            item = {
                "file_path": candidate.path,
                "number": number,
                "member_paths": [
                    video.path for video in repair_members
                ],
            }
            if nfo_missing_members and cover_missing_members:
                missing_both += 1
                item["category"] = "both"
            elif nfo_missing_members:
                missing_nfo += 1
                item["category"] = "nfo"
            else:
                missing_cover += 1
                item["category"] = "cover"
            items.append(item)
        total_missing = missing_both + missing_nfo + missing_cover

        # Return complete lists; the frontend owns confirmation/display policy.
        return {
            "success": True,
            "data": {
                "missing_both": missing_both,
                "missing_nfo": missing_nfo,
                "missing_cover": missing_cover,
                "total_missing": total_missing,
                "items": items,
                "untranslated_titles": len(untranslated_title_items),
                "missing_samples": len(missing_sample_items),
                "missing_plots": len(missing_plot_items),
                "untranslated_title_items": untranslated_title_items,
                "missing_sample_items": missing_sample_items,
                "missing_plot_items": missing_plot_items,
            },
        }
    except Exception as e:
        logger.error("檢查維護缺口失敗: %s", e)
        return {
            "success": False,
            "error": _runtime_text(
                "scanner", "missing_check_failed", _active_locale()
            ),
        }


_TITLE_BACKFILL_CONCURRENCY = 4
_SAMPLE_BACKFILL_CONCURRENCY = 3
_PLOT_BACKFILL_CONCURRENCY = 3
_TITLE_ERROR_KEYS = {
    "not_found": "error_not_found",
    "title_empty": "error_title_empty",
    "no_nfo": "error_no_nfo",
    "nfo_ambiguous": "error_nfo_ambiguous",
    "nfo_unreadable": "error_nfo_unreadable",
    "storage_permission_required": "error_storage_permission_required",
    "nfo_write_failed": "error_nfo_write_failed",
    "db_write_failed": "error_db_write_failed",
    "invalid_path": "error_invalid_path",
    "translate_failed": "translation_failed",
    "translation_refused": "translation_refused",
    "translation_invalid": "translation_invalid",
    "translation_empty": "translation_empty",
    "write_failed": "write_failed",
}
_PLOT_ERROR_KEYS = {
    "missing_number": "missing_number",
    "not_found": "error_not_found",
    "no_summary": "error_no_summary",
    "search_failed": "error_search_failed",
    "no_nfo": "error_no_nfo",
    "nfo_unreadable": "error_nfo_unreadable",
    "nfo_write_failed": "error_nfo_write_failed",
    "storage_permission_required": "error_storage_permission_required",
    "db_write_failed": "error_db_write_failed",
    "translate_failed": "translation_failed",
    "translation_refused": "translation_refused",
    "translation_invalid": "translation_invalid",
    "translation_empty": "translation_empty",
    "already_filled": "already_filled",
    "write_failed": "error_nfo_write_failed",
    "internal_error": "error_internal",
    "cancelled": "cancelled",
}
_SAMPLE_ERROR_KEYS = {
    "missing_number": "missing_number",
    "internal_error": "error_internal",
    "output_root_missing": "error_output_root_missing",
    "samples_search_failed": "error_samples_search_failed",
    "no_sample_images": "error_no_sample_images",
    "db_write_failed": "error_db_write_failed",
    "sample_download_failed": "error_sample_download_failed",
    "storage_permission_required": "error_storage_permission_required",
    "sample_write_failed": "error_sample_write_failed",
    "multi_video_folder": "error_multi_video_folder",
    "cancelled": "cancelled",
}


def _localized_title_error(
    locale: str,
    error_code: str,
    fallback: str = "",
) -> str:
    key = _TITLE_ERROR_KEYS.get(error_code)
    if key:
        return _runtime_text("title", key, locale)
    return fallback or _runtime_text("title", "write_failed", locale)


def _title_translation_error_code(exc: TranslateError) -> str:
    """Keep refusal and malformed output distinct from transport failures."""
    return {
        "refused": "translation_refused",
        "invalid_response": "translation_invalid",
        "empty_response": "translation_empty",
    }.get(exc.kind, "translate_failed")


def _localized_sample_error(
    locale: str,
    error_code: str,
    fallback: str = "",
    *,
    number: str = "",
) -> str:
    key = _SAMPLE_ERROR_KEYS.get(error_code)
    if key:
        return _runtime_text(
            "samples",
            key,
            locale,
            number=number,
        )
    return fallback or _runtime_text("samples", "internal_error", locale)


def _localized_plot_error(
    locale: str,
    error_code: str,
    fallback: str = "",
    *,
    number: str = "",
) -> str:
    key = _PLOT_ERROR_KEYS.get(error_code)
    if key:
        return _runtime_text(
            "plots",
            key,
            locale,
            number=number,
        )
    return fallback or _runtime_text("plots", "error_internal", locale)


def _iter_title_translations(
    translate_service: Any,
    candidates: List[Video],
    cancel_event: threading.Event,
    concurrency: int = _TITLE_BACKFILL_CONCURRENCY,
    locale: str | None = None,
) -> Generator[tuple[Video, Optional[str], Optional[Exception]], None, None]:
    """Translate candidates concurrently and yield results as they finish."""
    loop = asyncio.new_event_loop()
    semaphore = asyncio.Semaphore(max(1, concurrency))
    pending: dict[asyncio.Task[str], tuple[int, Video]] = {}

    async def translate_one(video: Video) -> str:
        async with semaphore:
            if cancel_event.is_set():
                raise asyncio.CancelledError()
            result = await translate_service.translate_or_raise(
                video.title,
                {
                    "actors": video.actresses or [],
                    "number": _candidate_number(video),
                },
            )
            cleaned = normalize_translation_text(result)
            issue = translation_result_issue(
                video.title,
                cleaned,
                locale or _active_locale(),
                proper_terms=video.actresses or (),
            )
            if issue is not None:
                kind = "refused" if issue == "refusal" else "invalid_response"
                raise build_error(
                    "TitleBackfill",
                    kind,
                    None,
                    issue,
                    issue,
                )
            return cleaned

    async def drain_pending() -> None:
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    try:
        for order, video in enumerate(candidates):
            task = loop.create_task(translate_one(video))
            pending[task] = (order, video)

        while pending:
            if cancel_event.is_set():
                for task in pending:
                    task.cancel()
                loop.run_until_complete(drain_pending())
                pending.clear()
                return

            done, _ = loop.run_until_complete(
                asyncio.wait(
                    pending,
                    timeout=_DISCONNECT_POLL_INTERVAL_SEC,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            )
            for task in sorted(done, key=lambda item: pending[item][0]):
                _, video = pending.pop(task)
                try:
                    translated = task.result()
                except asyncio.CancelledError:
                    yield video, None, RuntimeError("translation task cancelled")
                except Exception as exc:
                    yield video, None, exc
                else:
                    yield video, str(translated or "").strip(), None
    finally:
        for task in pending:
            task.cancel()
        loop.run_until_complete(drain_pending())
        loop.close()


def _title_backfill_generator(cancel_event: threading.Event) -> Generator[str, None, None]:
    """Translate every title that is not in the active UI language."""
    locale = _active_locale()
    try:
        db_path = get_db_path()
        if not db_path.exists():
            yield _sse_event({
                "type": "error",
                "message": _runtime_text(
                    "title", "db_missing", locale
                ),
            })
            return

        config = load_config()
        locale = _active_locale(config)
        translate_config = config.get("translate", {})
        if not translate_config.get("enabled", False):
            yield _sse_event({
                "type": "error",
                "message": _runtime_text(
                    "title", "translate_disabled", locale
                ),
            })
            return
        from web.routers.showcase import TitleWritebackRequest, _apply_title_writeback
        from web.routers.translate import get_translate_service

        repo = VideoRepository(db_path)
        path_mappings = config.get("gallery", {}).get("path_mappings", {})
        candidate_rows = [
            video for video in repo.get_untranslated_title_candidates()
            if _is_untranslated_title_candidate(video, locale)
        ]
        candidates = []
        group_by_candidate_path = {}
        for group in resolve_logical_video_groups(
            repo,
            candidate_rows,
            path_mappings,
        ):
            candidate = next(
                (
                    member
                    for member in group.members
                    if _is_untranslated_title_candidate(member, locale)
                ),
                None,
            )
            if candidate is None:
                continue
            candidates.append(candidate)
            group_by_candidate_path[candidate.path] = group
        total = len(candidates)
        if total == 0:
            yield _sse_event({
                "type": "done",
                "message": _runtime_text("title", "none", locale),
                "cancelled": False,
                "summary": {
                    "success": 0,
                    "failed": 0,
                    "skipped": 0,
                    "failed_items": [],
                },
            })
            return

        try:
            translate_service = get_translate_service()
        except Exception:
            logger.exception("初始化批次標題翻譯服務失敗")
            yield _sse_event({
                "type": "error",
                "message": _runtime_text(
                    "title", "config_invalid", locale
                ),
            })
            return

        success_count = 0
        failed_count = 0
        skipped_count = 0
        failed_items = []

        yield _sse_event({
            "type": "log",
            "level": "info",
            "message": _runtime_text(
                "title",
                "start",
                locale,
                total=total,
                concurrency=_TITLE_BACKFILL_CONCURRENCY,
            ),
        })

        yield _sse_event({
            "type": "progress",
            "current": 0,
            "total": total,
            "number": "",
            "status": _runtime_text(
                "title",
                "status",
                locale,
                concurrency=_TITLE_BACKFILL_CONCURRENCY,
            ),
            "success": success_count,
            "failed": failed_count,
            "skipped": skipped_count,
        })

        processed_count = 0
        for video, translated, translation_error in _iter_title_translations(
            translate_service,
            candidates,
            cancel_event,
            locale=locale,
        ):
            number = _candidate_number(video)
            group = group_by_candidate_path.get(video.path)
            group_members = (
                group.members if group is not None else [video]
            )
            try:
                if translation_error is not None:
                    raise translation_error
                if not translated:
                    raise ValueError("empty translation")
                member_results = []
                result = None
                for member in group_members:
                    member_result = _apply_title_writeback(
                        repo,
                        member,
                        TitleWritebackRequest(
                            file_path=member.path,
                            title=translated,
                        ),
                        config,
                        path_mappings,
                    )
                    member_results.append((member, member_result))
                    if not member_result.get("success"):
                        result = dict(member_result)
                        result["failed_member_path"] = member.path
                        break
                if result is None:
                    result = next(
                        (
                            member_result
                            for member, member_result in member_results
                            if member.path == video.path
                        ),
                        member_results[0][1],
                    )
            except TranslateError as exc:
                logger.warning(
                    "批次補齊標題翻譯失敗: %s kind=%s status=%s",
                    video.path,
                    exc.kind,
                    exc.status,
                )
                error_code = _title_translation_error_code(exc)
                result = {
                    "success": False,
                    "error": error_code,
                    "message": _runtime_text(
                        "title",
                        _TITLE_ERROR_KEYS[error_code],
                        locale,
                    ),
                }
            except Exception:
                logger.exception("批次補齊標題失敗: %s", video.path)
                result = {
                    "success": False,
                    "error": "translate_failed",
                    "message": _runtime_text(
                        "title", "translation_failed", locale
                    ),
                }

            processed_count += 1
            status = _runtime_text(
                "title",
                "status_count",
                locale,
                current=processed_count,
                total=total,
                concurrency=_TITLE_BACKFILL_CONCURRENCY,
            )
            if result.get("success"):
                success_count += 1
                written_title = str(
                    result.get("title") or translated or ""
                ).strip()
                original_title = str(
                    result.get("original_title") or video.title or ""
                ).strip()
                yield _sse_event({
                    "type": "result-item",
                    "file_path": video.path,
                    "number": number,
                    "success": True,
                    "skipped": False,
                    "title": written_title,
                    "original_title": original_title,
                    "member_paths": [
                        member.path for member in group_members
                    ],
                    "updated_member_count": len(group_members),
                    "current": processed_count,
                    "total": total,
                    "status": status,
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "skipped_count": skipped_count,
                })
                yield _sse_event({
                    "type": "log",
                    "level": "info",
                    "message": _runtime_text(
                        "title",
                        "log",
                        locale,
                        current=processed_count,
                        total=total,
                        item=number or video.path,
                        original=original_title,
                        translated=written_title,
                    ),
                })
                continue

            failed_count += 1
            error_code = result.get("error") or "write_failed"
            error_message = _localized_title_error(
                locale,
                error_code,
                str(result.get("message") or ""),
            )
            failed_items.append({
                "path": video.path,
                "number": number,
                "error_code": error_code,
                "error": error_message,
            })
            yield _sse_event({
                "type": "result-item",
                "file_path": video.path,
                "number": number,
                "success": False,
                "skipped": False,
                "error_code": error_code,
                "error": error_message,
                "current": processed_count,
                "total": total,
                "status": status,
                "success_count": success_count,
                "failed_count": failed_count,
                "skipped_count": skipped_count,
            })

        if cancel_event.is_set():
            yield _sse_event({
                "type": "done",
                "message": _runtime_text(
                    "title", "cancelled", locale
                ),
                "cancelled": True,
                "summary": {
                    "success": success_count,
                    "failed": failed_count,
                    "skipped": skipped_count,
                    "failed_items": failed_items,
                },
            })
            return

        yield _sse_event({
            "type": "done",
            "message": _runtime_text(
                "title",
                "done",
                locale,
                success=success_count,
                failed=failed_count,
            ),
            "cancelled": False,
            "summary": {
                "success": success_count,
                "failed": failed_count,
                "skipped": skipped_count,
                "failed_items": failed_items,
            },
        })
    except Exception:
        logger.exception("批次補齊標題端點失敗")
        yield _sse_event({
            "type": "error",
            "message": _runtime_text(
                "title", "unexpected_error", locale
            ),
        })


def _sample_backfill_generator(
    cancel_event: threading.Event, source: str = "auto",
) -> Generator[str, None, None]:
    """Fetch samples only for rows whose stored sample-image list is empty."""
    locale = _active_locale()
    try:
        try:
            config = load_config()
        except Exception:
            logger.warning(
                "批次補齊劇照：讀取設定失敗，使用預設 locale",
                exc_info=True,
            )
            config = {}
        locale = _active_locale(config)
        source_error = _validate_batch_source(source, config, locale=locale)
        if source_error:
            yield _sse_event({"type": "error", "message": source_error})
            return
        db_path = get_db_path()
        if not db_path.exists():
            yield _sse_event({
                "type": "error",
                "message": _runtime_text(
                    "title", "db_missing", locale
                ),
            })
            return

        from web.routers.scraper import (
            FetchSamplesRequest,
            fetch_samples_for_backfill,
        )

        repo = VideoRepository(db_path)
        candidates = [
            video for video in repo.get_missing_sample_candidates()
            if _is_missing_sample_candidate(video)
        ]
        if len(candidates) > 1:
            path_mappings = (
                config.get("gallery", {})
                .get("path_mappings", {})
            )
            candidates = _dedupe_multipart_sample_candidates(
                repo,
                candidates,
                path_mappings,
            )
        total = len(candidates)
        if total == 0:
            yield _sse_event({
                "type": "done",
                "message": _runtime_text("samples", "none", locale),
                "cancelled": False,
                "summary": {
                    "success": 0,
                    "failed": 0,
                    "skipped": 0,
                    "failed_items": [],
                },
            })
            return

        success_count = 0
        failed_count = 0
        skipped_count = 0
        failed_items = []

        yield _sse_event({
            "type": "log",
            "level": "info",
            "message": _runtime_text(
                "samples",
                "start",
                locale,
                total=total,
                concurrency=_SAMPLE_BACKFILL_CONCURRENCY,
            ),
        })

        yield _sse_event({
            "type": "progress",
            "current": 0,
            "total": total,
            "number": "",
            "status": _runtime_text(
                "samples",
                "status",
                locale,
                concurrency=_SAMPLE_BACKFILL_CONCURRENCY,
            ),
            "success": success_count,
            "failed": failed_count,
            "skipped": skipped_count,
        })

        def fetch_one(video: Video) -> tuple[str, dict]:
            number = _candidate_number(video)
            if not number:
                return "", {
                    "success": False,
                    "error_code": "missing_number",
                    "message": _runtime_text(
                        "samples", "missing_number", locale
                    ),
                }

            try:
                result = fetch_samples_for_backfill(
                    FetchSamplesRequest(
                        file_path=video.path,
                        number=number,
                        source=source,
                    ),
                    cancel_event,
                )
            except Exception:
                logger.exception("批次補齊劇照失敗: %s", video.path)
                result = {
                    "success": False,
                    "error_code": "internal_error",
                    "message": _runtime_text(
                        "samples", "internal_error", locale
                    ),
                }
            if not isinstance(result, dict):
                result = {
                    "success": False,
                    "error_code": "internal_error",
                    "message": _runtime_text(
                        "samples", "internal_error", locale
                    ),
                }
            return number, result

        executor = ThreadPoolExecutor(
            max_workers=_SAMPLE_BACKFILL_CONCURRENCY,
            thread_name_prefix="sample-backfill",
        )
        futures = {
            executor.submit(fetch_one, video): video
            for video in candidates
        }
        processed_count = 0
        cancelled = False

        try:
            while futures:
                if cancel_event.is_set():
                    cancelled = True
                    break

                done, _ = futures_wait(
                    tuple(futures),
                    timeout=_DISCONNECT_POLL_INTERVAL_SEC,
                    return_when=FIRST_COMPLETED,
                )
                for future in done:
                    if cancel_event.is_set():
                        cancelled = True
                        break
                    video = futures.pop(future)
                    try:
                        number, result = future.result()
                    except Exception:
                        logger.exception("批次補齊劇照失敗: %s", video.path)
                        number = _candidate_number(video)
                        result = {
                            "success": False,
                            "error_code": "internal_error",
                            "message": _runtime_text(
                                "samples", "internal_error", locale
                            ),
                        }

                    if result.get("error_code") == "cancelled":
                        cancelled = True
                        break

                    processed_count += 1
                    status = _runtime_text(
                        "samples",
                        "status_count",
                        locale,
                        current=processed_count,
                        total=total,
                        concurrency=_SAMPLE_BACKFILL_CONCURRENCY,
                    )

                    if result.get("success"):
                        success_count += 1
                        downloaded = int(result.get("downloaded") or 0)
                        skipped_existing = int(
                            result.get("skipped_existing") or 0
                        )
                        extrafanart_on_disk = int(
                            result.get("extrafanart_on_disk") or 0
                        )
                        yield _sse_event({
                            "type": "result-item",
                            "file_path": video.path,
                            "number": number,
                            "success": True,
                            "skipped": False,
                            "downloaded": downloaded,
                            "skipped_existing": skipped_existing,
                            "extrafanart_on_disk": extrafanart_on_disk,
                            "current": processed_count,
                            "total": total,
                            "status": status,
                            "success_count": success_count,
                            "failed_count": failed_count,
                            "skipped_count": skipped_count,
                        })
                        yield _sse_event({
                            "type": "log",
                            "level": "info",
                            "message": _runtime_text(
                                "samples",
                                "result_log",
                                locale,
                                current=processed_count,
                                total=total,
                                number=number,
                                downloaded=downloaded,
                                existing=skipped_existing,
                                total_images=extrafanart_on_disk,
                            ),
                        })
                        continue

                    error_code = result.get("error_code") or "sample_fetch_failed"
                    error_message = _localized_sample_error(
                        locale,
                        error_code,
                        str(result.get("message") or ""),
                        number=number,
                    )
                    if error_code == "missing_number":
                        skipped_count += 1
                        yield _sse_event({
                            "type": "result-item",
                            "file_path": video.path,
                            "number": "",
                            "success": False,
                            "skipped": True,
                            "error_code": error_code,
                            "error": error_message,
                            "current": processed_count,
                            "total": total,
                            "status": status,
                            "success_count": success_count,
                            "failed_count": failed_count,
                            "skipped_count": skipped_count,
                        })
                        continue

                    failed_count += 1
                    failed_items.append({
                        "path": video.path,
                        "number": number,
                        "error": error_message,
                    })
                    yield _sse_event({
                        "type": "result-item",
                        "file_path": video.path,
                        "number": number,
                        "success": False,
                        "skipped": False,
                        "error_code": error_code,
                        "error": error_message,
                        "current": processed_count,
                        "total": total,
                        "status": status,
                        "success_count": success_count,
                        "failed_count": failed_count,
                        "skipped_count": skipped_count,
                    })
                if cancelled:
                    break
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        if cancelled:
            yield _sse_event({
                "type": "done",
                "message": _runtime_text(
                    "samples", "cancelled", locale
                ),
                "cancelled": True,
                "summary": {
                    "success": success_count,
                    "failed": failed_count,
                    "skipped": skipped_count,
                    "failed_items": failed_items,
                },
            })
            return

        yield _sse_event({
            "type": "done",
            "message": _runtime_text(
                "samples",
                "done",
                locale,
                success=success_count,
                failed=failed_count,
                skipped=skipped_count,
            ),
            "cancelled": False,
            "summary": {
                "success": success_count,
                "failed": failed_count,
                "skipped": skipped_count,
                "failed_items": failed_items,
            },
        })
    except Exception:
        logger.exception("批次補齊劇照端點失敗")
        yield _sse_event({
            "type": "error",
            "message": _runtime_text(
                "samples", "unexpected_error", locale
            ),
        })


def _plot_backfill_generator(
    cancel_event: threading.Event, source: str = "auto",
) -> Generator[str, None, None]:
    """Fetch and translate synopses only for existing NFOs with an empty plot."""
    locale = _active_locale()
    try:
        config = load_config()
        locale = _active_locale(config)
        source_error = _validate_batch_source(source, config, locale=locale)
        if source_error:
            yield _sse_event({"type": "error", "message": source_error})
            return
        db_path = get_db_path()
        if not db_path.exists():
            yield _sse_event({
                "type": "error",
                "message": _runtime_text(
                    "plots", "db_missing", locale
                ),
            })
            return
        if not config.get("translate", {}).get("enabled", False):
            yield _sse_event({
                "type": "error",
                "message": _runtime_text(
                    "plots", "translate_disabled", locale
                ),
            })
            return

        from web.routers.translate import get_translate_service

        try:
            translate_service = get_translate_service()
        except Exception:
            logger.exception("初始化批次简介翻译服务失败")
            yield _sse_event({
                "type": "error",
                "message": _runtime_text(
                    "plots", "config_invalid", locale
                ),
            })
            return

        repo = VideoRepository(db_path)
        path_mappings = (
            config.get("gallery", {}).get("path_mappings", {})
        )
        groups = list(
            logical_video_groups(repo.get_all(), path_mappings)
        )
        candidates = find_missing_plot_candidates(
            groups,
            config,
            path_mappings,
        )
        total = len(candidates)
        if total == 0:
            yield _sse_event({
                "type": "done",
                "message": _runtime_text("plots", "none", locale),
                "cancelled": False,
                "summary": {
                    "success": 0,
                    "failed": 0,
                    "skipped": 0,
                    "failed_items": [],
                },
            })
            return

        javbus_lang = get_javbus_lang()

        def process_one(candidate) -> dict:
            if cancel_event.is_set():
                return {
                    "success": False,
                    "skipped": True,
                    "error_code": "cancelled",
                }
            number = candidate.number or _candidate_number(
                Video(path=candidate.file_path, title=candidate.title)
            )
            if not number:
                return {
                    "success": False,
                    "skipped": True,
                    "error_code": "missing_number",
                }

            try:
                metadata = search_jav(
                    number,
                    source=source,
                    javbus_lang=javbus_lang,
                )
            except Exception:
                logger.warning(
                    "批次补简介搜索失败: %s",
                    candidate.file_path,
                    exc_info=True,
                )
                return {
                    "success": False,
                    "skipped": False,
                    "error_code": "search_failed",
                }
            if not metadata:
                return {
                    "success": False,
                    "skipped": False,
                    "error_code": "not_found",
                }

            source_plot = clean_summary_text(
                metadata.get("_summary")
                or metadata.get("summary")
                or ""
            )
            if not source_plot:
                return {
                    "success": False,
                    "skipped": False,
                    "error_code": "no_summary",
                }

            translated_plot = source_plot
            if plot_needs_translation(
                source_plot,
                locale,
                proper_terms=candidate.actors,
            ):
                try:
                    translated_plot = asyncio.run(
                        translate_service.translate_plot_or_raise(
                            source_plot,
                            {
                                "actors": list(candidate.actors),
                                "number": number,
                            },
                        )
                    )
                except TranslateError as exc:
                    error_code = _title_translation_error_code(exc)
                    return {
                        "success": False,
                        "skipped": False,
                        "error_code": error_code,
                    }
                except Exception:
                    logger.exception(
                        "批次补简介翻译失败: %s",
                        candidate.file_path,
                    )
                    return {
                        "success": False,
                        "skipped": False,
                        "error_code": "translate_failed",
                    }

            translated_plot = normalize_translation_text(
                translated_plot
            ).strip()
            if not translated_plot:
                return {
                    "success": False,
                    "skipped": False,
                    "error_code": "translation_empty",
                }

            updated_nfos = []
            write_error = ""
            for nfo_path, owner_paths in candidate.nfo_targets:
                if cancel_event.is_set():
                    break
                try:
                    changed = fill_empty_nfo_plot(
                        nfo_path,
                        new_plot=translated_plot,
                        new_original=source_plot,
                    )
                    if not changed:
                        continue
                    updated_nfos.append(nfo_path)
                    nfo_mtime = os.stat(nfo_path).st_mtime
                    for owner_path in owner_paths:
                        if not repo.update_nfo_mtime(
                            owner_path,
                            nfo_mtime,
                        ):
                            write_error = "db_write_failed"
                except AndroidStoragePermissionError:
                    write_error = "storage_permission_required"
                except NfoNotFoundError:
                    write_error = "no_nfo"
                except NfoParseError:
                    write_error = "nfo_unreadable"
                except Exception:
                    logger.warning(
                        "批次补简介写入 NFO 失败: %s",
                        nfo_path,
                        exc_info=True,
                    )
                    write_error = "nfo_write_failed"

            return {
                "success": bool(updated_nfos) and not write_error,
                "skipped": not updated_nfos and not write_error,
                "error_code": write_error or (
                    "" if updated_nfos else "already_filled"
                ),
                "updated_nfo_count": len(updated_nfos),
                "translated_plot": translated_plot,
                "source_plot": source_plot,
            }

        success_count = 0
        failed_count = 0
        skipped_count = 0
        failed_items = []

        yield _sse_event({
            "type": "log",
            "level": "info",
            "message": _runtime_text(
                "plots",
                "start",
                locale,
                total=total,
                concurrency=_PLOT_BACKFILL_CONCURRENCY,
            ),
        })
        yield _sse_event({
            "type": "progress",
            "current": 0,
            "total": total,
            "number": "",
            "status": _runtime_text(
                "plots",
                "status",
                locale,
                concurrency=_PLOT_BACKFILL_CONCURRENCY,
            ),
            "success": success_count,
            "failed": failed_count,
            "skipped": skipped_count,
        })

        executor = ThreadPoolExecutor(
            max_workers=_PLOT_BACKFILL_CONCURRENCY,
            thread_name_prefix="plot-backfill",
        )
        futures = {
            executor.submit(process_one, candidate): (index, candidate)
            for index, candidate in enumerate(candidates)
        }
        processed_count = 0
        cancelled = False

        try:
            while futures:
                if cancel_event.is_set():
                    cancelled = True
                    break
                done, _ = futures_wait(
                    tuple(futures),
                    timeout=_DISCONNECT_POLL_INTERVAL_SEC,
                    return_when=FIRST_COMPLETED,
                )
                ordered_done = sorted(
                    done,
                    key=lambda future: futures[future][0],
                )
                for future in ordered_done:
                    if cancel_event.is_set():
                        cancelled = True
                        break
                    _index, candidate = futures.pop(future)
                    try:
                        result = future.result()
                    except Exception:
                        logger.exception(
                            "批次补简介处理失败: %s",
                            candidate.file_path,
                        )
                        result = {
                            "success": False,
                            "skipped": False,
                            "error_code": "internal_error",
                        }

                    if result.get("error_code") == "cancelled":
                        cancelled = True
                        break

                    processed_count += 1
                    number = candidate.number
                    status = _runtime_text(
                        "plots",
                        "status_count",
                        locale,
                        current=processed_count,
                        total=total,
                        concurrency=_PLOT_BACKFILL_CONCURRENCY,
                    )
                    if result.get("success"):
                        success_count += 1
                        preview = re.sub(
                            r"\s+",
                            " ",
                            result.get("translated_plot") or "",
                        ).strip()[:180]
                        yield _sse_event({
                            "type": "result-item",
                            "file_path": candidate.file_path,
                            "number": number,
                            "success": True,
                            "skipped": False,
                            "updated_nfo_count": result.get(
                                "updated_nfo_count",
                                0,
                            ),
                            "preview": preview,
                            "member_paths": list(
                                candidate.member_paths
                            ),
                            "current": processed_count,
                            "total": total,
                            "status": status,
                            "success_count": success_count,
                            "failed_count": failed_count,
                            "skipped_count": skipped_count,
                        })
                        yield _sse_event({
                            "type": "log",
                            "level": "info",
                            "message": _runtime_text(
                                "plots",
                                "log",
                                locale,
                                current=processed_count,
                                total=total,
                                number=number or candidate.file_path,
                                preview=preview,
                            ),
                        })
                        continue

                    error_code = (
                        result.get("error_code")
                        or "internal_error"
                    )
                    error_message = _localized_plot_error(
                        locale,
                        error_code,
                        number=number,
                    )
                    if result.get("skipped"):
                        skipped_count += 1
                        yield _sse_event({
                            "type": "result-item",
                            "file_path": candidate.file_path,
                            "number": number,
                            "success": False,
                            "skipped": True,
                            "error_code": error_code,
                            "error": error_message,
                            "current": processed_count,
                            "total": total,
                            "status": status,
                            "success_count": success_count,
                            "failed_count": failed_count,
                            "skipped_count": skipped_count,
                        })
                        continue

                    failed_count += 1
                    failed_items.append({
                        "path": candidate.file_path,
                        "number": number,
                        "error_code": error_code,
                        "error": error_message,
                    })
                    yield _sse_event({
                        "type": "result-item",
                        "file_path": candidate.file_path,
                        "number": number,
                        "success": False,
                        "skipped": False,
                        "error_code": error_code,
                        "error": error_message,
                        "updated_nfo_count": result.get(
                            "updated_nfo_count",
                            0,
                        ),
                        "current": processed_count,
                        "total": total,
                        "status": status,
                        "success_count": success_count,
                        "failed_count": failed_count,
                        "skipped_count": skipped_count,
                    })
                if cancelled:
                    break
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        if cancelled or cancel_event.is_set():
            yield _sse_event({
                "type": "done",
                "message": _runtime_text(
                    "plots",
                    "cancelled",
                    locale,
                ),
                "cancelled": True,
                "summary": {
                    "success": success_count,
                    "failed": failed_count,
                    "skipped": skipped_count,
                    "failed_items": failed_items,
                },
            })
            return

        yield _sse_event({
            "type": "done",
            "message": _runtime_text(
                "plots",
                "done",
                locale,
                success=success_count,
                failed=failed_count,
                skipped=skipped_count,
            ),
            "cancelled": False,
            "summary": {
                "success": success_count,
                "failed": failed_count,
                "skipped": skipped_count,
                "failed_items": failed_items,
            },
        })
    except Exception:
        logger.exception("批次补简介端点失败")
        yield _sse_event({
            "type": "error",
            "message": _runtime_text(
                "plots",
                "unexpected_error",
                locale,
            ),
        })


@router.post("/backfill-titles")
async def backfill_titles(request: Request):
    """SSE: translate all titles that differ from the active UI language."""
    return await _cancelable_sse_response(request, _title_backfill_generator)


@router.post("/backfill-samples")
async def backfill_samples(request: Request, source: str = Query("auto", min_length=1)):
    """SSE: fetch samples only for rows whose sample list is empty."""
    return await _cancelable_sse_response(
        request, lambda cancel: _sample_backfill_generator(cancel, source=source),
    )


@router.post("/backfill-plots")
async def backfill_plots(request: Request, source: str = Query("auto", min_length=1)):
    """SSE: fetch and translate synopses for existing NFOs with empty plots."""
    return await _cancelable_sse_response(
        request, lambda cancel: _plot_backfill_generator(cancel, source=source),
    )


def _build_current_rename_plan(scope: str = "files") -> dict:
    db_path = get_db_path()
    if scope not in {"files", "folders"}:
        raise ValueError("invalid_rename_scope")
    if not db_path.exists():
        return {
            "plan_id": "",
            "generated_at": "",
            "summary": {
                "total": 0,
                "rename_videos": 0,
                "rename_files": 0,
                "conflicts": 0,
                "unchanged": 0,
                "skipped": 0,
                "missing": 0,
            },
            "items": [],
        }
    config = load_config()
    gallery = config.get("gallery", {})
    mappings = gallery.get("path_mappings", {}) or {}
    ro_prefixes = readonly_source_prefixes(gallery, mappings)
    writable = writable_source_prefixes(gallery, mappings)
    videos = []
    for video in VideoRepository(db_path).get_all():
        canonical = coerce_to_file_uri(video.path, mappings)
        if is_path_readonly(canonical, ro_prefixes, writable):
            continue
        videos.append(video)
    if scope == "folders":
        source_roots = []
        for source in get_gallery_source_paths(gallery):
            try:
                source_roots.append(
                    uri_to_fs_path(coerce_to_file_uri(source, mappings))
                )
            except Exception:
                logger.warning(
                    "rename folder source root is invalid: %s",
                    source,
                    exc_info=True,
                )
        return build_folder_rename_plan(
            videos,
            source_roots=source_roots,
            path_mappings=mappings,
        )
    return build_rename_plan(
        videos,
        path_mappings=mappings,
        config=config,
    )


def _remember_rename_plan(plan: dict) -> None:
    now = time.monotonic()
    expired = [
        plan_id
        for plan_id, (created_at, _plan) in _rename_plan_cache.items()
        if now - created_at > _RENAME_PLAN_TTL_SECONDS
    ]
    for plan_id in expired:
        _rename_plan_cache.pop(plan_id, None)
    plan_id = str(plan.get("plan_id") or "")
    if plan_id:
        _rename_plan_cache[plan_id] = (now, plan)
    while len(_rename_plan_cache) > 4:
        oldest = min(
            _rename_plan_cache,
            key=lambda key: _rename_plan_cache[key][0],
        )
        _rename_plan_cache.pop(oldest, None)


def _combined_rename_sources(config: dict) -> tuple[list[Any], list[str], dict]:
    gallery = config.get("gallery", {})
    mappings = gallery.get("path_mappings", {}) or {}
    ro_prefixes = readonly_source_prefixes(gallery, mappings)
    writable = writable_source_prefixes(gallery, mappings)
    videos = []
    for video in VideoRepository(get_db_path()).get_all():
        canonical = coerce_to_file_uri(video.path, mappings)
        if is_path_readonly(canonical, ro_prefixes, writable):
            continue
        videos.append(video)
    roots = []
    for source in get_gallery_source_paths(gallery):
        try:
            roots.append(
                uri_to_fs_path(coerce_to_file_uri(source, mappings))
            )
        except Exception:
            logger.warning(
                "rename source root is invalid: %s",
                source,
                exc_info=True,
            )
    return videos, roots, mappings


def generate_source_rename_preview(
    source: str,
    cancel_event: Optional[threading.Event] = None,
) -> Generator[str, None, None]:
    """Fetch titles from one selected source, then preview file+folder renames."""
    failed_items: list[dict[str, Any]] = []
    locale = _active_locale()
    try:
        config = load_config()
        locale = _active_locale(config)
        source_error = _validate_batch_source(
            source,
            config,
            action_key="batch_action_rename",
            locale=locale,
        )
        if source_error:
            yield _sse_event({"type": "error", "message": source_error})
            return

        db_path = get_db_path()
        if not db_path.exists():
            yield _sse_event({
                "type": "error",
                "message": _runtime_text("scanner", "db_missing", locale),
            })
            return

        videos, source_roots, mappings = _combined_rename_sources(config)
        videos = [video for video in videos if video.path]
        video_groups = logical_video_groups(videos, mappings)
        total = len(video_groups)
        if not videos:
            yield _sse_event({
                "type": "done",
                "message": _runtime_text(
                    "scanner", "source_rename_none", locale
                ),
                "plan": build_combined_rename_plan(
                    [],
                    source_id=source,
                    stem_overrides={},
                    source_roots=source_roots,
                    path_mappings=mappings,
                    config=config,
                ),
            })
            return

        javbus_lang = get_javbus_lang()
        title_cache: dict[str, Optional[str]] = {}
        title_errors: dict[str, str] = {}
        stem_overrides: dict[str, str] = {}
        logged_title_numbers: set[str] = set()
        failed_group_indices: set[int] = set()
        started_at = time.monotonic()
        cancelled = False

        for group_index, group in enumerate(video_groups, start=1):
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
            elapsed = max(time.monotonic() - started_at, 0.001)
            eta_seconds = round(
                (elapsed / max(group_index - 1, 1))
                * max(total - group_index + 1, 0)
            )
            representative = next(
                (
                    video
                    for video in group.members
                    if str(video.number or "").strip()
                ),
                group.members[0],
            )
            yield _sse_event({
                "type": "progress",
                "current": group_index,
                "total": total,
                "number": representative.number or "",
                "status": (
                    _runtime_text(
                        "scanner",
                        "source_rename_reading_title",
                        locale,
                        item=representative.number or representative.path,
                    )
                ),
                "failed": len(failed_group_indices),
                "eta_seconds": eta_seconds,
            })

            group_overrides: dict[str, str] = {}
            group_failures: list[dict[str, str]] = []
            group_cancelled = False
            for video in group.members:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    group_cancelled = True
                    break

                number = str(video.number or "").strip()
                if not number:
                    group_failures.append({
                        "path": video.path,
                        "number": "",
                        "error": _runtime_text(
                            "scanner",
                            "source_rename_missing_number",
                            locale,
                        ),
                    })
                    continue

                try:
                    if number not in title_cache:
                        if number in title_errors:
                            raise RuntimeError(title_errors[number])
                        try:
                            metadata = search_jav(
                                number,
                                source=source,
                                javbus_lang=javbus_lang,
                                surface_access_errors=True,
                            )
                        except Exception as exc:
                            title_errors[number] = str(exc)
                            raise
                        title_cache[number] = (
                            str(metadata.get("title") or "")
                            if metadata
                            else None
                        )
                    source_title = title_cache[number]
                    stem, normalized_number, reason = (
                        canonicalize_source_stem(
                            number,
                            source_title,
                            part_token=multipart_token(
                                Path(video.path).stem
                            ),
                        )
                    )
                    if not stem:
                        raise ValueError(
                            _runtime_text(
                                "scanner",
                                "source_rename_no_title",
                                locale,
                            )
                            if reason == "empty_title"
                            else reason
                        )
                    group_overrides[video.path] = stem
                    if number not in logged_title_numbers:
                        logged_title_numbers.add(number)
                        yield _sse_event({
                            "type": "log",
                            "level": "info",
                            "message": _runtime_text(
                                "scanner",
                                "source_rename_title_used",
                                locale,
                                number=normalized_number,
                                title=source_title,
                            ),
                        })
                except Exception as exc:
                    group_failures.append({
                        "path": video.path,
                        "number": number,
                        "error": str(exc),
                    })
                    yield _sse_event({
                        "type": "log",
                        "level": "warn",
                        "message": _runtime_text(
                            "scanner",
                            "source_rename_fetch_failed",
                            locale,
                            number=number,
                            error=str(exc),
                        ),
                    })

            if group_cancelled:
                break
            if group_failures:
                # Source-title fetch/rename is all-or-nothing per logical video,
                # so a failed part cannot leave the remaining parts half-renamed.
                failed_group_indices.add(group_index - 1)
                failed_items.extend(group_failures)
                continue
            stem_overrides.update(group_overrides)

        eligible = [
            video for video in videos
            if video.path in stem_overrides
        ]
        plan = build_combined_rename_plan(
            eligible,
            source_id=source,
            stem_overrides=stem_overrides,
            source_roots=source_roots,
            path_mappings=mappings,
            config=config,
            failed_items=failed_items,
        )
        plan["cancelled"] = cancelled
        plan["summary"]["cancelled"] = cancelled
        summary = plan["summary"]
        summary["failed"] = len(failed_group_indices)
        summary["physical_failed_items"] = len(failed_items)
        if (
            not cancelled
            and plan.get("plan_id")
            and (
                summary["rename_videos"]
                or summary["rename_files"]
                or summary["rename_folders"]
                or summary["updated_titles"]
            )
        ):
            _remember_rename_plan(plan)
        if cancelled:
            message = _runtime_text(
                "scanner", "source_rename_cancelled", locale
            )
        else:
            message = _runtime_text(
                "scanner",
                "source_rename_done",
                locale,
                videos=plan["summary"]["rename_videos"],
                folders=plan["summary"]["rename_folders"],
                titles=plan["summary"]["updated_titles"],
                failed=plan["summary"]["failed"],
                conflicts=plan["summary"]["conflicts"],
            )
        yield _sse_event({
            "type": "done",
            "message": message,
            "plan": plan,
            "preview": True,
        })
    except Exception:
        logger.exception("按来源统一命名预览失败: source=%s", source)
        yield _sse_event({
            "type": "error",
            "message": _runtime_text(
                "scanner", "source_rename_failed", locale
            ),
        })
    finally:
        if cancel_event is not None:
            mark_generate_done(cancel_event)


@router.get("/rename-preview")
def rename_preview(scope: str = Query("files")):
    """Preview filename or direct-child folder normalization without writes."""
    try:
        return {"success": True, "data": _build_current_rename_plan(scope)}
    except Exception as exc:
        logger.exception("建立檔名正規化預覽失敗")
        return {
            "success": False,
            "error": _runtime_text(
                "scanner", "rename_preview_failed", _active_locale()
            ),
        }


@router.post("/rename-execute")
def rename_execute(request: RenameExecuteRequest):
    """Execute a previously previewed plan and roll back on any failure."""
    if not _rename_execute_lock.acquire(blocking=False):
        return {
            "success": False,
            "error": "rename_already_running",
        }
    try:
        db_path = get_db_path()
        if request.scope == "combined":
            cached = _rename_plan_cache.pop(request.plan_id, None)
            if cached is None:
                return {
                    "success": False,
                    "error": "plan_expired",
                }
            created_at, plan = cached
            if time.monotonic() - created_at > _RENAME_PLAN_TTL_SECONDS:
                return {
                    "success": False,
                    "error": "plan_expired",
                }
            if plan.get("cancelled"):
                return {
                    "success": False,
                    "error": "plan_cancelled",
                }
            if plan["summary"]["conflicts"]:
                return {
                    "success": False,
                    "error": "plan_has_conflicts",
                }
            if not validate_combined_rename_plan(plan):
                return {
                    "success": False,
                    "error": "plan_changed",
                }
            result = execute_combined_rename_plan(
                plan,
                VideoRepository(db_path),
                manifest_dir=db_path.parent / "rename-manifests",
            )
            if result.get("success"):
                for item in plan["items"]:
                    if item["status"] != "ready":
                        continue
                    for video in item["videos"]:
                        try:
                            thumbnail_cache.invalidate(video["db_old_uri"])
                        except Exception:
                            logger.warning(
                                "combined rename thumbnail invalidate failed: %s",
                                video["db_old_uri"],
                                exc_info=True,
                            )
            return result

        plan = _build_current_rename_plan(request.scope)
        if not plan.get("plan_id") or plan["plan_id"] != request.plan_id:
            return {
                "success": False,
                "error": "plan_changed",
            }
        if plan["summary"]["conflicts"]:
            return {
                "success": False,
                "error": "plan_has_conflicts",
            }
        if request.scope == "folders":
            result = execute_folder_rename_plan(
                plan,
                VideoRepository(db_path),
                manifest_dir=db_path.parent / "rename-manifests",
            )
        else:
            result = execute_rename_plan(
                plan,
                VideoRepository(db_path),
                manifest_dir=db_path.parent / "rename-manifests",
            )
        if result.get("success"):
            for item in plan["items"]:
                if item["status"] == "ready":
                    old_uris = (
                        [
                            video["db_old_uri"]
                            for video in item.get("videos", [])
                        ]
                        if request.scope == "folders"
                        else [item["db_old_uri"]]
                    )
                    for old_uri in old_uris:
                        try:
                            thumbnail_cache.invalidate(old_uri)
                        except Exception:
                            logger.warning(
                                "rename thumbnail invalidate failed: %s",
                                old_uri,
                                exc_info=True,
                            )
        return result
    except Exception as exc:
        logger.exception("執行檔名正規化失敗")
        return {"success": False, "error": str(exc)}
    finally:
        _rename_execute_lock.release()


@router.get("/rename-source-preview")
async def preview_source_rename(
    request: Request,
    source: str = Query(..., min_length=1),
):
    """Fetch selected-source titles and preview combined file/folder renames."""
    return await _cancelable_sse_response(
        request,
        lambda cancel_event: generate_source_rename_preview(
            source,
            cancel_event,
        ),
    )


def generate_nfo_update(
    cancel_event: Optional[threading.Event] = None,
    selected_paths: Optional[list[str]] = None,
    backup: bool = False,
    source: str = "auto",
) -> Generator[str, None, None]:
    """NFO 更新生成器（SSE 串流）- 使用 SQLite"""

    locale = _active_locale()
    try:
        db_path = get_db_path()

        if not db_path.exists():
            yield _sse_event({
                "type": "error",
                "message": _runtime_text(
                    "scanner", "db_missing", locale
                ),
            })
            return

        repo = VideoRepository(db_path)
        all_videos = repo.get_all()

        if not all_videos:
            yield _sse_event({
                "type": "done",
                "message": _runtime_text(
                    "scanner", "no_video_data", locale
                ),
                "updated": 0,
            })
            return

        config = load_config()
        locale = _active_locale(config)
        source_error = _validate_batch_source(source, config, locale=locale)
        if source_error:
            yield _sse_event({"type": "error", "message": source_error})
            return
        cache, skipped_readonly, path_mappings = _build_nfo_update_cache(
            all_videos, config
        )
        if skipped_readonly:
            yield _sse_event({
                "type": "log",
                "level": "info",
                "message": _runtime_text(
                    "scanner",
                    "readonly_videos_skipped",
                    locale,
                    count=skipped_readonly,
                ),
            })

        # 檢查需要更新的影片
        stats = check_cache_needs_update(cache)
        if stats['need_update'] == 0:
            yield _sse_event({
                "type": "done",
                "message": _runtime_text(
                    "scanner", "nothing_to_update", locale
                ),
                "updated": 0,
            })
            return

        paths_to_update = list(stats["paths"])
        selected = set(selected_paths or [])
        groups = _logical_groups_for_paths(
            all_videos,
            paths_to_update,
            path_mappings,
        )
        if selected:
            groups = [
                (group, member_paths)
                for group, member_paths in groups
                if selected.intersection(member_paths)
            ]
        if not groups:
            yield _sse_event({
                "type": "done",
                "message": _runtime_text(
                    "scanner", "nfo_no_retry", locale
                ),
                "updated": 0,
                "summary": {
                    "total": 0,
                    "success": 0,
                    "failed": 0,
                    "skipped": 0,
                    "no_nfo": 0,
                    "no_metadata": 0,
                    "cancelled": False,
                    "failed_items": [],
                    "updated_paths": [],
                },
            })
            return

        # Feed every physical NFO through the updater, but expose one
        # progress row per logical video.  A multipart release must not look
        # like two different works in the scanner UI.
        grouped_paths = [
            path
            for _group, member_paths in groups
            for path in member_paths
        ]
        group_index_by_path = {
            path: index
            for index, (_group, member_paths) in enumerate(groups)
            for path in member_paths
        }
        group_index_by_position = {
            index: group_index_by_path[path]
            for index, path in enumerate(grouped_paths)
        }
        seen_group_progress = set()
        logical_total = len(groups)

        yield _sse_event({
            "type": "log",
            "level": "info",
            "message": _runtime_text(
                "scanner",
                "nfo_checking",
                locale,
                count=logical_total,
            ),
        })

        # 執行更新（path_mappings 沿用 _build_nfo_update_cache 算好的那份，不重讀 config）
        update_generator = update_videos_generator(
            cache,
            grouped_paths,
            path_mappings,
            should_abort=cancel_event.is_set if cancel_event is not None else None,
            backup=backup,
            source=source,
        )
        update_stats = None
        while True:
            try:
                msg = next(update_generator)
            except StopIteration as stop:
                update_stats = stop.value
                break
            if isinstance(msg, dict) and msg.get("type") == "progress":
                path = msg.get("path")
                group_index = group_index_by_path.get(path)
                if group_index is None:
                    group_index = group_index_by_position.get(
                        max(int(msg.get("current", 1)) - 1, 0)
                    )
                if group_index is None or group_index in seen_group_progress:
                    continue
                seen_group_progress.add(group_index)
                msg = {
                    **msg,
                    "current": group_index + 1,
                    "total": logical_total,
                }
            yield _sse_event(msg)

        update_stats = update_stats or {
            "total": logical_total,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "no_nfo": 0,
            "no_metadata": 0,
            "cancelled": False,
            "failed_items": [],
            "updated_paths": [],
        }
        update_stats = _logical_nfo_summary(update_stats, groups)
        updated_paths = list(update_stats.get("updated_paths") or [])
        if updated_paths:
            try:
                config = load_config()
                locale = _active_locale(config)
                scanner = VideoScanner(
                    path_mappings=path_mappings,
                    nfo_title_format=config.get("scraper", {}).get(
                        "nfo_title_format", "[{num}]{title}"
                    ),
                )
                refreshed_rows = []
                existing_by_uri = repo.get_by_paths(updated_paths)
                for path in updated_paths:
                    try:
                        info = scanner.scan_file(
                            uri_to_local_fs_path(path, path_mappings),
                            None,
                        )
                        video = Video.from_video_info(info)
                        existing = existing_by_uri.get(path)
                        if existing is not None:
                            video.preserve_missing_metadata(existing)
                        nfo_path = get_nfo_path_from_video(path, path_mappings)
                        if nfo_path:
                            video.nfo_mtime = os.stat(nfo_path).st_mtime
                        elif existing is not None:
                            video.nfo_mtime = existing.nfo_mtime
                        refreshed_rows.append(video)
                    except Exception:
                        logger.warning(
                            "NFO 更新後刷新資料庫失敗: %s",
                            path,
                            exc_info=True,
                        )
                if refreshed_rows:
                    repo.upsert_batch(refreshed_rows)
                    yield _sse_event({
                        "type": "log",
                        "level": "info",
                        "message": _runtime_text(
                            "scanner",
                            "nfo_rows_synced",
                            locale,
                            count=len(groups),
                        ),
                    })
            except Exception:
                logger.warning("NFO 更新後批次刷新資料庫失敗", exc_info=True)
        cancelled = bool(update_stats.get("cancelled"))
        yield _sse_event({
            "type": "done",
            "message": _runtime_text(
                "scanner",
                "nfo_cancelled" if cancelled else "nfo_done",
                locale,
                success=update_stats.get('success', 0),
                failed=update_stats.get('failed', 0),
                skipped=update_stats.get('skipped', 0),
            ),
            "updated": update_stats.get("success", 0),
            "summary": update_stats,
        })

    except Exception as e:
        logger.error("NFO 更新失敗: %s", e)
        yield _sse_event({
            "type": "error",
            "message": _runtime_text(
                "scanner", "nfo_failed", locale
            ),
        })


@router.get("/update")
async def run_update(
    request: Request,
    path: Optional[list[str]] = Query(default=None),
    backup: bool = Query(default=True),
    source: str = Query("auto", min_length=1),
):
    """執行 NFO 更新（SSE 串流回傳進度）"""
    return await _cancelable_sse_response(
        request,
        lambda cancel_event: generate_nfo_update(
            cancel_event,
            selected_paths=path,
            backup=backup,
            source=source,
        ),
    )


@router.get("/tag-source-update")
async def run_tag_source_update(
    request: Request,
    source: str = Query(..., min_length=1),
    numbers: Optional[str] = Query(default=None),
    backup: bool = Query(default=True),
):
    """Batch replace ordinary tags using one explicitly selected source."""
    selected_numbers = {
        value.strip() for value in (numbers or "").split(",") if value.strip()
    } or None
    return await _cancelable_sse_response(
        request,
        lambda cancel_event: generate_tag_source_update(
            source,
            cancel_event,
            numbers=selected_numbers,
            backup=backup,
        ),
    )


@router.get("/tag-source-preview")
async def preview_tag_source_update(
    request: Request,
    source: str = Query(..., min_length=1),
    numbers: Optional[str] = Query(default=None),
):
    """Preview tag changes without writing the database or NFO files."""
    selected_numbers = {
        value.strip() for value in (numbers or "").split(",") if value.strip()
    } or None
    return await _cancelable_sse_response(
        request,
        lambda cancel_event: generate_tag_source_update(
            source,
            cancel_event,
            dry_run=True,
            numbers=selected_numbers,
        ),
    )


@router.get("/view")
def view_list():
    """取得產生的 HTML 列表檔案（修改圖片路徑為 API 代理）"""
    try:
        config = load_config()
        locale = _active_locale(config)
        gallery_config = config.get('gallery', {})
        output_dir = gallery_config.get('output_dir', '') or ''
        output_filename = gallery_config.get('output_filename', 'gallery_output.html')

        html_path = resolve_gallery_output_path(output_dir) / output_filename

        if not html_path.exists():
            return HTMLResponse(
                content=(
                    f"<html><body><h1>{_runtime_text('scanner', 'view_missing_title', locale)}</h1>"
                    f"<p>{_runtime_text('scanner', 'view_missing_body', locale)}</p></body></html>"
                ),
                status_code=404
            )

        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 將 file:/// 圖片路徑替換為 API 代理路徑（只替換圖片，不替換影片）
        # file:///C:/path/to/image.jpg -> /api/gallery/image?path=C:/path/to/image.jpg
        import re
        from urllib.parse import quote

        # 圖片副檔名
        image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')

        def replace_file_url(match):
            file_path = match.group(1)
            # 只替換圖片路徑
            if file_path.lower().endswith(image_extensions):
                encoded_path = quote(file_path, safe='')
                return f'/api/gallery/image?path={encoded_path}'
            # 非圖片保持原樣
            return match.group(0)

        # 匹配 file:/// 後面直到引號的所有字元（包含空格和中文）
        content = re.sub(r'file:///([^"\'<>]+?)(?=["\'])', replace_file_url, content)

        return HTMLResponse(content=content)
    except Exception:
        logger.exception("view_list 讀取失敗")
        locale = _active_locale()
        return HTMLResponse(
            content=(
                f"<html><body><h1>{_runtime_text('scanner', 'view_error_title', locale)}</h1>"
                f"<p>{_runtime_text('scanner', 'view_error_body', locale)}</p></body></html>"
            ),
            status_code=500
        )


@router.get("/actress-stats")
def get_actress_stats(name: str = Query(..., description="女優名稱")):
    """查詢某名字的片數"""
    try:
        db_path = get_db_path()

        if not db_path.exists():
            return {"success": True, "data": {"count": 0}}

        repo = VideoRepository(db_path)
        config = load_config()
        path_mappings = (
            config.get("gallery", {}).get("path_mappings", {})
        )
        count = len(resolve_logical_video_groups(
            repo,
            repo.get_videos_by_actress(name),
            path_mappings,
        ))

        return {"success": True, "data": {"count": count}}
    except Exception as e:
        logger.error("查詢女優片數失敗: %s", e)
        return {
            "success": False,
            "error": _runtime_text(
                "scanner", "actress_stats_failed", _active_locale()
            ),
        }


# === Jellyfin 圖片批次補齊 ===

def check_jellyfin_images_needed(repo: VideoRepository, path_mappings: dict = None) -> dict:
    """檢查 DB 中有多少影片缺少 poster/fanart"""
    videos = repo.get_all()
    need_update = []
    for group in logical_video_groups(videos, path_mappings):
        group_items = []
        for video in group.members:
            if not video.cover_path:
                continue
            cover_fs = uri_to_local_fs_path(video.cover_path, path_mappings)
            if not os.path.exists(cover_fs):
                continue
            base_stem = cover_base_stem(cover_fs)
            poster = base_stem + '-poster.jpg'
            fanart = base_stem + '-fanart.jpg'
            if not os.path.exists(poster) or not os.path.exists(fanart):
                group_items.append({
                    'cover_path': cover_fs,
                    'base_stem': base_stem,
                    'number': video.number or '',
                    'maker': video.maker or '',
                    'path': video.path,
                })
        if group_items:
            item = dict(group_items[0])
            item["member_items"] = group_items
            item["member_paths"] = [
                group_item["path"]
                for group_item in group_items
            ]
            need_update.append(item)
    return {'need_update': len(need_update), 'items': need_update}


def generate_jellyfin_images_stream(
    cancel_event: Optional[threading.Event] = None,
) -> Generator[str, None, None]:
    """SSE 串流：批次為影片產生 poster + fanart"""
    global _jellyfin_cache_result, _jellyfin_cache_time

    locale = _active_locale()
    try:
        # Codex PR#123 P2：gate 必須排在 get_db_path() 之前——get_db_path() 內部會
        # mkdir 建立 output/ 資料夾（core/database/connection.py:15-22），是有副作用
        # 的磁碟操作。若先呼叫 get_db_path() 再判斷 gate，會導致「external_manager=
        # off 且資料庫不存在」（全新安裝／還沒產生過列表）這個情境下：gate 根本走
        # 不到，先建了 output/ 資料夾、又回傳 error 而非 spec-111 AC8 承諾的
        # done + updated:0（off 時零寫入），且與 _check_jellyfin_needed() 的順序
        # 不對稱。config 只讀一次，下面 path_mappings 沿用同一個 config。
        config = load_config()
        locale = _active_locale(config)
        external_manager = config.get('scraper', {}).get('external_manager', 'off')
        if external_manager not in STEM_IMAGE_MODES:
            _jellyfin_cache_result = None
            _jellyfin_cache_time = 0
            yield _sse_event({
                "type": "done",
                "message": _runtime_text(
                    "scanner", "jellyfin_nothing", locale
                ),
                "updated": 0,
            })
            return

        db_path = get_db_path()

        if not db_path.exists():
            yield _sse_event({
                "type": "error",
                "message": _runtime_text(
                    "scanner", "db_missing", locale
                ),
            })
            return

        repo = VideoRepository(db_path)
        path_mappings = config.get('gallery', {}).get('path_mappings', {})
        result = check_jellyfin_images_needed(repo, path_mappings)
        items = result['items']
        total = len(items)

        if total == 0:
            _jellyfin_cache_result = None
            _jellyfin_cache_time = 0
            yield _sse_event({
                "type": "done",
                "message": _runtime_text(
                    "scanner", "jellyfin_nothing", locale
                ),
                "updated": 0,
            })
            return

        yield _sse_event({
            "type": "log",
            "level": "info",
            "message": _runtime_text(
                "scanner", "jellyfin_start", locale, count=total
            ),
        })

        completed = 0
        failed = 0
        cancelled = False
        failed_items = []
        for i, item in enumerate(items, 1):
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
            # Codex PR#122 P2-b：開頭 gate 一次不夠——批次跑到一半使用者可能把
            # external_manager 切成 off（或非白名單），剩餘項目仍會繼續產生
            # poster/fanart，違反 AC8 的 TOCTOU 洞。每筆重讀成本可忽略（產一張圖
            # 含人臉偵測＋裁切＋寫檔，遠比讀一次 config 貴），故逐筆重讀而非只在
            # 進入迴圈前讀一次。命中就中止，沿用既有 done 事件形狀回報已完成筆數。
            current_config = load_config()
            current_external_manager = current_config.get('scraper', {}).get('external_manager', 'off')
            if current_external_manager not in STEM_IMAGE_MODES:
                cancelled = True
                break

            member_items = item.get("member_items") or [item]
            num = item['number']

            yield _sse_event({
                "type": "progress",
                "current": i,
                "total": total,
                "number": num,
                "status": _runtime_text(
                    "scanner",
                    "jellyfin_processing",
                    locale,
                    number=num,
                ),
                "success": completed,
                "failed": failed,
                "skipped": 0,
            })

            group_ok = True
            group_failed_items = []
            for member_item in member_items:
                member_num = member_item["number"]
                img_result = generate_jellyfin_images(
                    member_item["cover_path"],
                    member_item["base_stem"],
                    number=member_num,
                    maker=member_item["maker"],
                )

                if not img_result['fanart']:
                    yield _sse_event({
                        "type": "log",
                        "level": "warn",
                        "message": _runtime_text(
                            "scanner",
                            "jellyfin_fanart_failed",
                            locale,
                            number=member_num,
                        ),
                    })

                if img_result['poster']:
                    yield _sse_event({
                        "type": "log",
                        "level": "info",
                        "message": _runtime_text(
                            "scanner",
                            "jellyfin_poster_ok",
                            locale,
                            number=member_num,
                        ),
                    })
                else:
                    group_ok = False
                    group_failed_items.append({
                        "path": member_item.get("path", ""),
                        "number": member_num,
                        "error": _runtime_text(
                            "scanner",
                            "jellyfin_poster_failed",
                            locale,
                            number=member_num,
                        ),
                    })
                    yield _sse_event({
                        "type": "log",
                        "level": "warn",
                        "message": _runtime_text(
                            "scanner",
                            "jellyfin_poster_failed",
                            locale,
                            number=member_num,
                        ),
                    })

            if group_ok:
                completed += 1
            else:
                failed += 1
                representative = dict(group_failed_items[0])
                representative["member_paths"] = [
                    member_item.get("path", "")
                    for member_item in member_items
                ]
                representative["physical_failed_items"] = (
                    len(group_failed_items)
                )
                failed_items.append(representative)

        # T3(40c): 清空快取，讓下次 check 反映最新圖片狀態
        _jellyfin_cache_result = None
        _jellyfin_cache_time = 0
        yield _sse_event({
            "type": "done",
            "message": _runtime_text(
                "scanner",
                "jellyfin_cancelled" if cancelled else "jellyfin_done",
                locale,
                count=completed,
            ),
            "updated": completed,
            "summary": {
                "total": total,
                "success": completed,
                "failed": failed,
                "skipped": 0,
                "cancelled": cancelled,
                "failed_items": failed_items,
            },
        })

    except Exception as e:
        logger.error("產生 Jellyfin 圖片失敗: %s", e)
        yield _sse_event({
            "type": "error",
            "message": _runtime_text(
                "scanner", "jellyfin_failed", locale
            ),
        })


def _check_jellyfin_needed() -> dict | None:
    """Threadpool helper: gate → TTL 快取命中 → get_db_path + check DB existence +
    open repo + run jellyfin check.

    spec-111 CD-111-2 gate：external_manager 不在 STEM_IMAGE_MODES 白名單（含 off）時，
    直接回傳零項，不產生 -poster/-fanart（fail-closed 正向白名單，不用 != 'off'）。

    Codex PR#122 P2-a：gate **必須**排在 TTL 快取讀取之前——快取只是「省重算」的
    優化，不能繞過「off 時回零項」的產品邊界。時序漏洞（修前）：media-server 模式
    呼叫一次把快取寫成正數 → 60 秒內把設定切成 off → 再呼叫 → 舊實作在 async body
    先查快取命中直接回傳，根本不會進到這支 gate，回傳舊的非零值，違反 AC8。
    現在快取讀寫也併入本 helper（threadpool 內執行），async 端不再碰快取狀態。

    Returns None if DB does not exist (caller handles as need_update=0 early return).
    Returns the result dict (from cache or freshly computed) otherwise.
    """
    global _jellyfin_cache_result, _jellyfin_cache_time

    config = load_config()
    external_manager = config.get('scraper', {}).get('external_manager', 'off')
    if external_manager not in STEM_IMAGE_MODES:
        return {'need_update': 0, 'items': []}

    # T3(40c): TTL 快取命中（gate 通過之後才查，見上方 docstring）
    if _jellyfin_cache_result is not None and time.time() - _jellyfin_cache_time < 60:
        return _jellyfin_cache_result

    db_path = get_db_path()
    if not db_path.exists():
        return None
    repo = VideoRepository(db_path)
    path_mappings = config.get('gallery', {}).get('path_mappings', {})
    result = check_jellyfin_images_needed(repo, path_mappings)

    # T3(40c): 更新快取
    _jellyfin_cache_result = result
    _jellyfin_cache_time = time.time()

    return result


@router.get("/jellyfin-check")
async def jellyfin_image_check():
    """檢查多少影片需要補齊 Jellyfin 圖片"""
    try:
        result = await asyncio.to_thread(_check_jellyfin_needed)

        if result is None:
            return {"success": True, "data": {"need_update": 0, "items": []}}

        return {"success": True, "data": {"need_update": result['need_update'], "items": result['items']}}
    except Exception as e:
        logger.error("檢查 Jellyfin 圖片狀態失敗: %s", e)
        return {"success": False, "error": "檢查圖片狀態失敗"}


@router.get("/jellyfin-update")
async def jellyfin_image_update(request: Request):
    """批次產生 poster + fanart（SSE 串流回傳進度）"""
    return await _cancelable_sse_response(
        request,
        generate_jellyfin_images_stream,
    )


_MIME_MAP = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.webp': 'image/webp',
}


_REFERER_MAP = {
    'javbus.com': 'https://www.javbus.com/',
    'dmm.co.jp': 'https://www.dmm.co.jp/',
    'jav321.com': 'https://www.jav321.com/',
}

_MIN_IMAGE_SIZE = 1000  # bytes — 小於此視為無效（防空白/錯誤頁）


def _embed_cover(img_ref: str, path_mappings: dict = None) -> str:
    """將圖片 URL/路徑轉為 data URI。失敗時回傳原值。"""
    if not img_ref or img_ref.startswith('data:'):
        return img_ref

    try:
        if img_ref.startswith('file:///'):
            local_path = uri_to_local_fs_path(img_ref, path_mappings)
            data = Path(local_path).read_bytes()
        elif img_ref.startswith(('http://', 'https://')):
            headers = _EMBED_HEADERS.copy()
            for domain, referer in _REFERER_MAP.items():
                if domain in img_ref:
                    headers['Referer'] = referer
                    break

            resp = requests.get(img_ref, headers=headers, timeout=15, **proxy_kwargs('image', url=img_ref))
            if resp.status_code != 200:
                logger.warning('封面嵌入失敗 [HTTP %s] %s', resp.status_code, img_ref[:100])
                return img_ref
            if len(resp.content) < _MIN_IMAGE_SIZE:
                logger.warning('封面嵌入失敗 [內容過小 %d bytes] %s', len(resp.content), img_ref[:100])
                return img_ref
            data = resp.content
        else:
            return img_ref

        # MIME: HTTP 時優先用 Content-Type，其他 fallback 副檔名
        mime = 'image/jpeg'
        if img_ref.startswith(('http://', 'https://')):
            ct = resp.headers.get('Content-Type', '')
            if ct.startswith('image/'):
                mime = ct.split(';')[0].strip()
        if mime == 'image/jpeg':
            ext = Path(img_ref.split('?')[0]).suffix.lower()
            mime = _MIME_MAP.get(ext, 'image/jpeg')

        b64 = base64.b64encode(data).decode('ascii')
        return f'data:{mime};base64,{b64}'
    except Exception as e:
        logger.warning('封面嵌入失敗 [%s] %s', type(e).__name__, img_ref[:100])
        return img_ref


class GenerateFromIdsRequest(BaseModel):
    numbers: List[str]
    title: str = "Custom Gallery"
    mode: str = "image"
    sort: str = "date"
    embed_covers: bool = True


_VALID_MODES = {"image", "detail", "text"}
_VALID_SORTS = {"date", "num", "title"}


@router.post("/generate-from-ids", summary="番號列表產生自訂 Gallery HTML")
def generate_from_ids(body: GenerateFromIdsRequest):
    """
    根據番號列表產生自訂 Gallery HTML 頁面。

    - DB 有資料的番號直接組裝；DB 沒有的即時 scrape。
    - 輸出路徑：output/gallery_custom_{timestamp}.html

    回傳：
    ```json
    {
      "success": true,
      "html_path": "/abs/path/to/gallery_custom_20260331_120000.html",
      "video_count": 12,
      "missing": ["FAKE-999"]
    }
    ```
    """
    numbers = [n.strip() for n in body.numbers if isinstance(n, str) and n.strip()]
    config = load_config()
    locale = _active_locale(config)

    if not numbers:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": _runtime_text("scanner", "generate_ids_empty", locale),
            },
        )

    if len(numbers) > 100:
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": _runtime_text("scanner", "generate_ids_limit", locale),
            },
        )

    if body.mode not in _VALID_MODES:
        return JSONResponse(status_code=422, content={
            "success": False,
            "error": _runtime_text(
                "scanner",
                "generate_ids_mode",
                locale,
                values=", ".join(sorted(_VALID_MODES)),
            ),
        })

    if body.sort not in _VALID_SORTS:
        return JSONResponse(status_code=422, content={
            "success": False,
            "error": _runtime_text(
                "scanner",
                "generate_ids_sort",
                locale,
                values=", ".join(sorted(_VALID_SORTS)),
            ),
        })

    gallery_config = config.get('gallery', {})
    output_dir = gallery_config.get('output_dir', '') or ''
    theme = config.get('general', {}).get('theme', 'light')

    # 查 DB
    try:
        db_path = get_db_path()
        repo = VideoRepository(db_path)
        db_results = repo.get_by_numbers(numbers)
    except Exception as e:
        logger.error('generate_from_ids: DB 查詢失敗: %s', e)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": _runtime_text("scanner", "generate_ids_db_failed", locale),
            },
        )

    all_videos: List[VideoInfo] = []
    missing: List[str] = []

    for num in numbers:
        db_videos = db_results.get(num)
        if db_videos:
            v = db_videos[0]
            info = VideoInfo(
                path=v.path,
                title=v.title or '',
                originaltitle=v.original_title or '',
                actor=','.join(v.actresses) if v.actresses else '',
                num=v.number or num,
                maker=v.maker or '',
                date=v.release_date or '',
                genre=','.join(v.tags) if v.tags else '',
                size=v.size_bytes or 0,
                mtime=int(v.mtime * 10000000 + 116444736000000000) if v.mtime else 0,
                img=v.cover_path or ''
            )
            all_videos.append(info)
        else:
            # DB miss → 即時 scrape
            try:
                scrape_results = smart_search(num, limit=1, uncensored_mode=is_uncensored_mode_effective(config))
            except Exception as e:
                logger.error('generate_from_ids: scrape %s failed: %s', num, e)
                scrape_results = []

            if scrape_results:
                r = scrape_results[0]
                info = VideoInfo(
                    path='',
                    title=r.get('title', ''),
                    originaltitle=r.get('original_title', ''),
                    actor=','.join(r.get('actors', [])) if isinstance(r.get('actors'), list) else r.get('actors', ''),
                    num=r.get('number', num),
                    maker=r.get('maker', ''),
                    date=r.get('date', ''),
                    genre=','.join(r.get('tags', [])) if isinstance(r.get('tags'), list) else '',
                    size=0,
                    mtime=0,
                    img=r.get('cover', '') or r.get('cover_url', '')
                )
                all_videos.append(info)
            else:
                missing.append(num)

    # 封面嵌入（embed_covers=True 時將 img 轉為 data URI）
    embedded_count = 0
    embed_failed_count = 0
    if body.embed_covers:
        for info in all_videos:
            if info.img:
                original = info.img
                info.img = _embed_cover(info.img, gallery_config.get('path_mappings', {}))
                if info.img.startswith('data:'):
                    embedded_count += 1
                elif original:  # 有原圖但 embed 失敗
                    embed_failed_count += 1

    # 確保輸出目錄存在（空值 → 資料根；相對／絕對值依 resolve_gallery_output_path）
    output_path = resolve_gallery_output_path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    html_filename = f'gallery_custom_{timestamp}.html'
    html_path = output_path / html_filename

    try:
        generator = HTMLGenerator()
        generator.generate(
            all_videos,
            str(html_path),
            title=body.title,
            mode=body.mode,
            sort=body.sort,
            theme=theme,
        )
    except Exception as e:
        logger.error('generate_from_ids: HTML 產生失敗: %s', e)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": _runtime_text("scanner", "generate_ids_html_failed", locale),
            },
        )

    result = {
        "success": True,
        "html_path": str(html_path),
        "video_count": len(all_videos),
        "missing": missing,
    }
    if body.embed_covers:
        result["embedded_count"] = embedded_count
        result["embed_failed_count"] = embed_failed_count
    return result


def _is_windows() -> bool:
    return os.name == 'nt'


def _path_flavour():
    from pathlib import PurePosixPath, PureWindowsPath
    return PureWindowsPath if _is_windows() else PurePosixPath


def _compute_parent(path: str) -> Optional[str]:
    if not path:
        return None
    flavour = _path_flavour()
    p = flavour(path)
    if p.parent == p:
        return "" if _is_windows() else None
    return str(p.parent)


def _list_windows_drives() -> list[str]:
    try:
        if hasattr(os, "listdrives"):
            return list(os.listdrives())
    except (AttributeError, OSError):
        pass
    import string
    return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]


def _browse_start_dir(config: dict) -> str:
    if sys.platform == "android":
        shared_root = "/storage/emulated/0"
        if os.path.isdir(shared_root):
            return shared_root

    gallery_cfg = config.get('gallery') or {}
    sources = iter_gallery_sources(gallery_cfg)
    if sources:
        path_mappings = gallery_cfg.get('path_mappings', {})
        fs = uri_to_local_fs_path(sources[0].path, path_mappings)
        parent = str(Path(fs).parent)
        resolved = safe_realpath(parent, 'browse-dir')
        # isdir 為真還不夠：目錄存在但列不出來（traverse-only 權限、NAS 掛著但權限壞掉）
        # 會讓「第一次開彈窗」直接吃 403，而使用者沒有任何畫面可以導去別處自救。
        # 起點決議不得回 4xx —— 探一次 scandir，列不動就退回平台根。
        if os.path.isdir(resolved):
            try:
                with os.scandir(resolved):
                    pass
                return resolved
            except OSError:
                logger.warning("browse-dir: 起點列舉失敗，退回平台根 path=%s", resolved)
    return "" if _is_windows() else "/"


@router.get("/browse-dir")
def browse_dir(path: Optional[str] = Query(None), expand: Optional[str] = Query(None)):
    config = load_config()
    # path 省略 → 起點決議。空字串在兩個平台語意不同：Windows 的 "" 是虛擬磁碟機清單
    # 節點（從 C:\ 按上一層會走到這裡，必須保留），POSIX 沒有這個節點，"" 等同省略。
    if path is None or (path == "" and not _is_windows()):
        current_path = _browse_start_dir(config)
    else:
        current_path = path

    if current_path == "" and _is_windows():
        drives = _list_windows_drives()
        entries = [{"name": d, "path": d} for d in drives]
        entries.sort(key=lambda e: (e["name"].casefold(), e["name"]))
        result = {
            "current_path": "",
            "parent_path": None,
            "entries": entries,
        }
        if expand == "videos":
            result["files"] = []
        return result

    resolved_path = safe_realpath(current_path, "browse-dir")
    if not os.path.exists(resolved_path):
        return JSONResponse(status_code=404, content={"success": False, "error": "not_found"})
    if not os.path.isdir(resolved_path):
        return JSONResponse(status_code=400, content={"success": False, "error": "not_a_directory"})

    entries = []
    video_files = []
    video_exts = get_video_extensions(config) if expand == "videos" else set()

    try:
        with os.scandir(resolved_path) as it:
            for entry in it:
                try:
                    if entry.is_dir():
                        if is_nas_system_dir_name(entry.name):
                            continue
                        entries.append({"name": entry.name, "path": entry.path})
                    elif expand == "videos" and entry.is_file():
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext in video_exts:
                            video_files.append(entry.path)
                except OSError:
                    continue
    except (PermissionError, OSError):
        return JSONResponse(status_code=403, content={"success": False, "error": "permission_denied"})

    entries.sort(key=lambda e: (e["name"].casefold(), e["name"]))
    if expand == "videos":
        video_files.sort(key=lambda p: (os.path.basename(p).casefold(), p))

    parent_path = _compute_parent(resolved_path)
    result = {
        "current_path": resolved_path,
        "parent_path": parent_path,
        "entries": entries,
    }
    if expand == "videos":
        result["files"] = video_files
    return result
