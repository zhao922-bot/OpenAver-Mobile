"""Lightbox plot API: read and translate NFO plot text on demand."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from core.android_storage import (
    AndroidStoragePermissionError,
    AndroidStorageWriteError,
)
from core.cf_transport import CfChallengeRequired, CfTransportUnavailable
from core.config import get_configured_gallery_dirs, load_config
from core.database import VideoRepository, get_db_path, init_db
from core.i18n import get_config_locale, t as i18n_t
from core.logger import get_logger
from core.nfo_stat import nfo_mtime_or_none
from core.nfo_locator import locate_nfo_for_video
from core.path_utils import is_path_under_dir
from core.plot_backfill import candidate_number, clean_summary_text
from core.plot_writeback import (
    PlotEmptyError,
    read_nfo_plots,
    rewrite_nfo_plot,
)
from core.scraper import (
    access_error_info,
    get_javbus_lang,
    search_jav,
    source_display_name,
)
from core.scrapers.errors import (
    CustomSourceRefused,
    SourceBlocked,
    SourceParseEmpty,
    SourceUnreachable,
)
from core.source_config import validate_source_id
from core.title_writeback import NfoNotFoundError, NfoParseError, strip_illegal_xml_chars

logger = get_logger(__name__)

router = APIRouter(prefix="/api/showcase", tags=["showcase"])


class PlotWritebackRequest(BaseModel):
    file_path: str
    plot: str
    original_plot: Optional[str] = None
    allow_empty_existing: bool = False


class PlotRefetchRequest(BaseModel):
    file_path: str
    source: str = "auto"


_ERROR_KEYS = {
    "not_found": "not_found",
    "plot_empty": "title_empty",
    "no_nfo": "no_nfo",
    "nfo_ambiguous": "nfo_ambiguous",
    "nfo_unreadable": "nfo_unreadable",
    "storage_permission_required": "storage_permission_required",
    "nfo_write_failed": "nfo_write_failed",
    "db_write_failed": "db_write_failed",
    "invalid_path": "invalid_path",
}


def _locale(config: dict | None = None) -> str:
    try:
        return get_config_locale(config)
    except Exception:
        return "zh-CN"


def _fail(code: str, locale: str | None = None) -> dict:
    locale = locale or _locale()
    key = _ERROR_KEYS.get(code, "nfo_write_failed")
    return {
        "success": False,
        "error": code,
        "message": i18n_t(f"runtime.title.error_{key}", locale=locale),
    }


def _refetch_fail(code: str, msg_key: str, locale: str | None = None) -> dict:
    locale = locale or _locale()
    return {
        "success": False,
        "error": code,
        "message": i18n_t(f"showcase.lightbox.{msg_key}", locale=locale),
    }


def _persist_nfo_plot(
    repo,
    video,
    nfo_path: str,
    *,
    current_plot: str,
    current_original: str,
    new_plot: str,
    new_original: str,
    locale: str,
    allow_empty_existing: bool = False,
) -> tuple[Optional[dict], Optional[dict]]:
    if (
        bool(current_plot)
        and _norm(new_plot) == _norm(current_plot)
        and _norm(new_original) == _norm(current_original)
    ):
        return {
            "success": True,
            "plot": current_plot,
            "original_plot": current_original,
            "has_original": bool(current_original),
            "unchanged": True,
        }, None

    try:
        rewrite_nfo_plot(
            nfo_path,
            new_plot=new_plot,
            new_original=new_original,
            allow_empty_existing=allow_empty_existing,
        )
    except (NfoNotFoundError, FileNotFoundError):
        return None, _fail("no_nfo", locale)
    except PlotEmptyError:
        return None, _fail("plot_empty", locale)
    except NfoParseError:
        return None, _fail("nfo_unreadable", locale)
    except AndroidStoragePermissionError:
        return None, _fail("storage_permission_required", locale)
    except AndroidStorageWriteError:
        logger.exception("[plot] Android NFO write failed")
        return None, _fail("nfo_write_failed", locale)
    except OSError:
        logger.exception("[plot] NFO write failed")
        return None, _fail("nfo_write_failed", locale)

    new_mtime = nfo_mtime_or_none(Path(nfo_path))
    if new_mtime is None:
        new_mtime = video.nfo_mtime
    try:
        updated = repo.update_nfo_mtime(video.path, new_mtime)
    except Exception:
        logger.exception("[plot] DB mtime update failed")
        return None, _fail("db_write_failed", locale)
    if not updated:
        return None, _fail("not_found", locale)
    return {
        "success": True,
        "plot": new_plot,
        "original_plot": new_original,
        "has_original": bool(new_original),
        "unchanged": False,
    }, None


def _norm(text: str) -> str:
    return " ".join(text.split())


def _load_video(file_path: str):
    config = load_config()
    locale = _locale(config)
    db_path = get_db_path()
    if not db_path.exists():
        return None, None, None, _fail("not_found", locale)
    init_db(db_path)
    repo = VideoRepository(db_path)
    video = repo.get_by_path(file_path)
    if video is None:
        return None, None, None, _fail("not_found", locale)
    configured_uris, path_mappings = get_configured_gallery_dirs(config)
    if not any(is_path_under_dir(video.path, uri) for uri in configured_uris):
        return None, None, None, _fail("not_found", locale)
    return repo, video, (config, path_mappings, locale), None


def _locate_nfo(video, config: dict, path_mappings: dict):
    return locate_nfo_for_video(video, config, path_mappings)


def _read_plots(nfo_path: str, locale: str):
    try:
        plot, original = read_nfo_plots(nfo_path)
    except (NfoNotFoundError, FileNotFoundError):
        return None, None, _fail("no_nfo", locale)
    except NfoParseError:
        return None, None, _fail("nfo_unreadable", locale)
    except OSError:
        return None, None, _fail("nfo_unreadable", locale)
    return plot, original, None


def _target_original(
    requested: Optional[str],
    current_plot: str,
    current_original: str,
    new_plot: str,
) -> str:
    if requested is not None:
        return requested
    if _norm(new_plot) == _norm(current_plot):
        return current_original
    return current_original or current_plot


@router.get("/video/plot")
def get_video_plot(file_path: str = Query(...)):
    """Read ``<plot>`` only when the user opens the lightbox panel."""
    try:
        repo, video, context, error = _load_video(file_path)
        if error is not None:
            return error
        config, path_mappings, locale = context
        nfo_path, locate_error = _locate_nfo(video, config, path_mappings)
        if nfo_path is None:
            return _fail(locate_error, locale)
        plot, original, error = _read_plots(nfo_path, locale)
        if error is not None:
            return error
        if not plot:
            return _fail("plot_empty", locale)
        return {
            "success": True,
            "plot": plot,
            "original_plot": original,
            "has_original": bool(original),
        }
    except ValueError:
        return _fail("invalid_path")
    except Exception:
        logger.exception("[plot] GET failed")
        return _fail("nfo_unreadable")


@router.post("/video/plot")
def write_video_plot(req: PlotWritebackRequest):
    """Write translated plot text back to NFO and refresh cached mtime."""
    locale = _locale()
    try:
        repo, video, context, error = _load_video(req.file_path)
        if error is not None:
            return error
        config, path_mappings, locale = context
        nfo_path, locate_error = _locate_nfo(video, config, path_mappings)
        if nfo_path is None:
            return _fail(locate_error, locale)

        current_plot, current_original, error = _read_plots(nfo_path, locale)
        if error is not None:
            return error
        if not current_plot and not req.allow_empty_existing:
            return _fail("plot_empty", locale)

        new_plot = strip_illegal_xml_chars(req.plot)
        if not new_plot.strip():
            return _fail("plot_empty", locale)
        requested_original = (
            strip_illegal_xml_chars(req.original_plot)
            if req.original_plot is not None
            else None
        )
        new_original = _target_original(
            requested_original,
            current_plot,
            current_original,
            new_plot,
        )
        result, persist_error = _persist_nfo_plot(
            repo,
            video,
            nfo_path,
            current_plot=current_plot,
            current_original=current_original,
            new_plot=new_plot,
            new_original=new_original,
            locale=locale,
            allow_empty_existing=req.allow_empty_existing,
        )
        if persist_error is not None:
            return persist_error
        return result
    except ValueError:
        return _fail("invalid_path", locale)
    except Exception:
        logger.exception("[plot] POST failed")
        return _fail("nfo_write_failed", locale)


@router.post("/video/plot/refetch")
def refetch_video_plot(req: PlotRefetchRequest):
    """Re-fetch video synopsis from scraper and persist to NFO."""
    locale = _locale()
    try:
        repo, video, context, error = _load_video(req.file_path)
        if error is not None:
            return error
        config, path_mappings, locale = context
        nfo_path, locate_error = _locate_nfo(video, config, path_mappings)
        if nfo_path is None:
            return _fail(locate_error, locale)

        current_plot, current_original, error = _read_plots(nfo_path, locale)
        if error is not None:
            return error

        source = (req.source or "auto").strip() or "auto"
        if not validate_source_id(source):
            return _refetch_fail("invalid_source", "plot_refetch_failed", locale)

        number = candidate_number(video)
        if not number:
            return _refetch_fail("missing_number", "plot_refetch_missing_number", locale)

        try:
            metadata = search_jav(
                number,
                source=source,
                javbus_lang=get_javbus_lang(),
                surface_access_errors=(source != "auto"),
            )
        except (CfChallengeRequired, CfTransportUnavailable, SourceBlocked, SourceUnreachable) as exc:
            info = access_error_info(exc, source, locale=locale)
            code = "search_blocked" if info.get("access_error") == "blocked" else "search_unreachable"
            return {
                "success": False,
                "error": code,
                "message": info.get("message") or i18n_t("showcase.lightbox.plot_refetch_failed", locale=locale),
            }
        except SourceParseEmpty:
            return _refetch_fail("no_summary", "plot_refetch_not_found", locale)
        except CustomSourceRefused as exc:
            return {
                "success": False,
                "error": "search_blocked",
                "message": str(exc) or i18n_t("showcase.lightbox.plot_refetch_failed", locale=locale),
            }
        except Exception:
            logger.warning("[plot] refetch search failed: %s (%s)", video.path, source, exc_info=True)
            return _refetch_fail("search_failed", "plot_refetch_failed", locale)

        if not metadata:
            return _refetch_fail("no_summary", "plot_refetch_not_found", locale)

        source_plot = clean_summary_text(
            metadata.get("_summary") or metadata.get("summary") or ""
        )
        source_plot = strip_illegal_xml_chars(source_plot).strip()
        if not source_plot:
            return _refetch_fail("no_summary", "plot_refetch_not_found", locale)

        result, persist_error = _persist_nfo_plot(
            repo,
            video,
            nfo_path,
            current_plot=current_plot,
            current_original=current_original,
            new_plot=source_plot,
            new_original="",
            locale=locale,
            allow_empty_existing=True,
        )
        if persist_error is not None:
            return persist_error

        actual_source = str(metadata.get("source") or ("" if source == "auto" else source)).strip()
        source_label = source_display_name(actual_source) if actual_source else ""
        return {
            **result,
            "source": actual_source,
            "source_label": source_label,
        }
    except ValueError:
        return _fail("invalid_path", locale)
    except Exception:
        logger.exception("[plot] refetch failed")
        return _fail("nfo_write_failed", locale)
