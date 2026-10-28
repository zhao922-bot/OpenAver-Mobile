"""
DB In-flow Upsert Helper

Search 頁整理完成後，條件式將影片寫入 DB（in-flow upsert）。
僅在檔案路徑落在 Scanner 追蹤目錄範圍內時執行。
"""
from __future__ import annotations

from pathlib import Path

from core.config import load_config, get_gallery_source_paths
from core.database import Video, VideoRepository
from core.gallery_scanner import VideoScanner
from core.logger import get_logger
from core.nfo_stat import NFO_MTIME_ON_UPSERT, nfo_mtime_or_none
from core.path_utils import to_file_uri
from core.settings_link import find_matched_directory

logger = get_logger(__name__)


def _reraise_stat_error(e: OSError) -> None:
    """S2's on_error callback: let a stat failure propagate to the existing
    `except OSError` in `try_inflow_upsert`, which already logs the warning
    below — re-raising avoids duplicating that message in the callback
    (Opus BLOCKER fix, plan-113b v8: `.exists()` restored, primitive only
    takes over the `.stat()` call itself).
    """
    raise e


def try_inflow_upsert(
    target_file_path: str,
    old_file_path: str | None = None,
) -> str:
    """
    條件式 in-flow upsert（B1 擴充版）。

    Args:
        target_file_path: 整理後影片的完整 FS 路徑字串（非 file:// URI）
        old_file_path: 整理前原始 FS 路徑（optional）；提供時觸發 repath 邏輯，
                       讓 DB 中舊路徑那筆原地 UPDATE 為新路徑，保留 id/created_at/user_tags。

    Returns:
        "synced"     — 成功寫入 DB
        "not_linked" — 不在 Scanner directories 範圍內（靜默 skip）
        "failed"     — 發生例外 / scan-fail 保卡（整理本身不受影響）
    """
    try:
        config = load_config()
        gallery_cfg = config.get("gallery", {})
        path_mappings: dict | None = gallery_cfg.get("path_mappings") or None

        # 步驟 2.5：算 old_uri（禁止手拼 file:///，依 CLAUDE.md 路徑規則）
        # to_file_uri 內部已處理 Windows/WSL/Linux 各路徑格式，不可再套 normalize_path
        # （guard: test_no_normalize_before_to_file_uri 禁止此疊加模式）
        old_uri: str | None = None
        if old_file_path:
            old_uri = to_file_uri(old_file_path, path_mappings)

        # 步驟 1：確認檔案在 Scanner 追蹤範圍內
        matched = find_matched_directory(target_file_path, get_gallery_source_paths(gallery_cfg), path_mappings)
        if matched is None:
            logger.debug(
                "try_inflow_upsert: %r 不在任何 Scanner directory，skip",
                target_file_path,
            )
            return "not_linked"

        # 步驟 2：掃描影片資訊（傳 path_mappings → canonical path 與 Scanner 一致）
        scanner = VideoScanner(path_mappings=path_mappings, nfo_title_format=config.get('scraper', {}).get('nfo_title_format', '[{num}]{title}'))
        video_info = scanner.scan_file(target_file_path)

        if not video_info:
            logger.debug(
                "try_inflow_upsert: scan_file 回空值，%r",
                target_file_path,
            )
            # scan-fail 保卡（B1 finding #2）：
            # 若舊 row 存在，UPDATE-path-only 保住卡（保留舊 metadata），回 "failed"。
            # 若無舊 row，沿用既有 "not_linked" 行為。
            if old_uri:
                repo = VideoRepository()
                if repo.get_by_path(old_uri):
                    new_uri_fallback = to_file_uri(target_file_path, path_mappings)
                    repo.repath_path_only(old_uri, new_uri_fallback)
                    logger.info(
                        "try_inflow_upsert: scan-fail 保卡 — 舊路徑 %r → %r",
                        old_uri,
                        new_uri_fallback,
                    )
                    return "failed"
            return "not_linked"

        # 步驟 3：repath（含 upsert 降級）
        repo = VideoRepository()
        video = Video.from_video_info(video_info)

        # 步驟 2.9：從磁碟 NFO 回填權威 nfo_mtime（鏡射目錄掃描 scanner.py:510 既有作法）。
        # Video.from_video_info 寫死 nfo_mtime=0.0（VideoInfo 無此欄位）；in-flow 路徑
        # 需自行 stat 剛整理好的 NFO，否則 showcase 會誤判該片缺 NFO（🔍 icon）。
        # 只在 NFO 實際存在時才寫入真 st_mtime；不存在（如使用者關閉 NFO 寫入、
        # 或 NFO 被手動刪除）維持 0，誠實回報無 NFO。stat() 失敗保卡不拋例外。
        _NFO_MTIME_POLICY = NFO_MTIME_ON_UPSERT
        try:
            nfo_path = Path(target_file_path).with_suffix('.nfo')
            if nfo_path.exists():
                video.nfo_mtime = nfo_mtime_or_none(nfo_path, on_error=_reraise_stat_error)
        except OSError:
            logger.warning(
                "try_inflow_upsert: stat NFO 失敗，%r，nfo_mtime 維持 0",
                target_file_path,
            )

        new_uri = video.path  # scan_file 寫入 Video.path 即 canonical new_uri
        repo.repath(old_uri, new_uri, video)

        logger.info(
            "try_inflow_upsert: %r 已寫入 DB（matched dir=%r, old_uri=%r）",
            target_file_path,
            matched,
            old_uri,
        )
        return "synced"

    except Exception:
        logger.exception(
            "try_inflow_upsert: %r 發生例外，DB 寫入失敗（整理結果不受影響）",
            target_file_path,
        )
        return "failed"
