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
from core.config import get_configured_gallery_dirs, load_config
from core.database import VideoRepository, get_db_path, init_db
from core.i18n import get_config_locale, t as i18n_t
from core.logger import get_logger
from core.nfo_stat import nfo_mtime_or_none
from core.nfo_locator import locate_nfo_for_video
from core.path_utils import is_path_under_dir
from core.plot_writeback import (
    PlotEmptyError,
    read_nfo_plots,
    rewrite_nfo_plot,
)
from core.title_writeback import NfoNotFoundError, NfoParseError, strip_illegal_xml_chars

logger = get_logger(__name__)

router = APIRouter(prefix="/api/showcase", tags=["showcase"])


class PlotWritebackRequest(BaseModel):
    file_path: str
    plot: str
    original_plot: Optional[str] = None


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
        if not current_plot:
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
        if (
            _norm(new_plot) == _norm(current_plot)
            and _norm(new_original) == _norm(current_original)
        ):
            return {
                "success": True,
                "plot": current_plot,
                "original_plot": current_original,
                "has_original": bool(current_original),
                "unchanged": True,
            }

        try:
            rewrite_nfo_plot(
                nfo_path,
                new_plot=new_plot,
                new_original=new_original,
            )
        except (NfoNotFoundError, FileNotFoundError):
            return _fail("no_nfo", locale)
        except PlotEmptyError:
            return _fail("plot_empty", locale)
        except NfoParseError:
            return _fail("nfo_unreadable", locale)
        except AndroidStoragePermissionError:
            return _fail("storage_permission_required", locale)
        except AndroidStorageWriteError:
            logger.exception("[plot] Android NFO write failed")
            return _fail("nfo_write_failed", locale)
        except OSError:
            logger.exception("[plot] NFO write failed")
            return _fail("nfo_write_failed", locale)

        new_mtime = nfo_mtime_or_none(Path(nfo_path))
        if new_mtime is None:
            new_mtime = video.nfo_mtime
        try:
            updated = repo.update_nfo_mtime(video.path, new_mtime)
        except Exception:
            logger.exception("[plot] DB mtime update failed")
            return _fail("db_write_failed", locale)
        if not updated:
            return _fail("not_found", locale)
        return {
            "success": True,
            "plot": new_plot,
            "original_plot": new_original,
            "has_original": bool(new_original),
            "unchanged": False,
        }
    except ValueError:
        return _fail("invalid_path", locale)
    except Exception:
        logger.exception("[plot] POST failed")
        return _fail("nfo_write_failed", locale)
