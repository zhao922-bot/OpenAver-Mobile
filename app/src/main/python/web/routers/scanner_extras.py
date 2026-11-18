"""
Scanner auxiliary endpoints & helpers extracted from web/routers/scanner.py:
- HTML gallery view proxy (/api/gallery/view)
- Custom Gallery HTML generation from IDs (/api/gallery/generate-from-ids)
- Server directory browser (/api/gallery/browse-dir)
"""

from __future__ import annotations

import base64
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

import requests
from fastapi import Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from core.config import iter_gallery_sources, load_config
from core.data_root import resolve_gallery_output_path
from core.database import VideoRepository, get_db_path
from core.gallery_generator import HTMLGenerator
from core.gallery_scanner import VideoInfo, is_nas_system_dir_name
from core.i18n import get_config_locale, t as i18n_t
from core.logger import get_logger
from core.organizer import HEADERS as _EMBED_HEADERS
from core.path_utils import uri_to_local_fs_path
from core.proxy_policy import proxy_kwargs
from core.scraper import smart_search
from core.source_settings import is_uncensored_mode_effective
from core.video_extensions import get_video_extensions
from web.routers.gallery_media import safe_realpath

logger = get_logger(__name__)

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

_VALID_MODES = {"image", "detail", "text"}
_VALID_SORTS = {"date", "num", "title"}


class GenerateFromIdsRequest(BaseModel):
    numbers: List[str]
    title: str = "Custom Gallery"
    mode: str = "image"
    sort: str = "date"
    embed_covers: bool = True


def _scanner_attr(name: str, default):
    scanner_mod = sys.modules.get("web.routers.scanner")
    return getattr(scanner_mod, name, default) if scanner_mod is not None else default


def _runtime_text(section: str, key: str, locale: str, **params) -> str:
    return i18n_t(f"runtime.{section}.{key}", locale=locale, **params)


def _active_locale(config: dict | None = None) -> str:
    try:
        return get_config_locale(config)
    except Exception:
        return "zh-CN"


def view_list():
    """取得產生的 HTML 列表檔案（修改圖片路徑為 API 代理）"""
    load_cfg = _scanner_attr("load_config", load_config)
    resolve_out = _scanner_attr("resolve_gallery_output_path", resolve_gallery_output_path)
    try:
        config = load_cfg()
        locale = _active_locale(config)
        gallery_config = config.get('gallery', {})
        output_dir = gallery_config.get('output_dir', '') or ''
        output_filename = gallery_config.get('output_filename', 'gallery_output.html')

        html_path = resolve_out(output_dir) / output_filename

        if not html_path.exists():
            return HTMLResponse(
                content=(
                    f"<html><body><h1>{_runtime_text('scanner', 'view_missing_title', locale)}</h1>"
                    f"<p>{_runtime_text('scanner', 'view_missing_body', locale)}</p></body></html>"
                ),
                status_code=404,
            )

        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')

        def replace_file_url(match):
            file_path = match.group(1)
            if file_path.lower().endswith(image_extensions):
                encoded_path = quote(file_path, safe='')
                return f'/api/gallery/image?path={encoded_path}'
            return match.group(0)

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
            status_code=500,
        )


def _embed_cover(img_ref: str, path_mappings: dict = None) -> str:
    """將圖片 URL/路徑轉為 data URI。失敗時回傳原值。"""
    if not img_ref or img_ref.startswith('data:'):
        return img_ref

    req_mod = _scanner_attr("requests", requests)
    proxy_fn = _scanner_attr("proxy_kwargs", proxy_kwargs)
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

            resp = req_mod.get(img_ref, headers=headers, timeout=15, **proxy_fn('image', url=img_ref))
            if resp.status_code != 200:
                logger.warning('封面嵌入失敗 [HTTP %s] %s', resp.status_code, img_ref[:100])
                return img_ref
            if len(resp.content) < _MIN_IMAGE_SIZE:
                logger.warning('封面嵌入失敗 [內容過小 %d bytes] %s', len(resp.content), img_ref[:100])
                return img_ref
            data = resp.content
        else:
            return img_ref

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


def generate_from_ids(body: GenerateFromIdsRequest):
    """根據番號列表產生自訂 Gallery HTML 頁面。"""
    load_cfg = _scanner_attr("load_config", load_config)
    db_path_fn = _scanner_attr("get_db_path", get_db_path)
    repo_cls = _scanner_attr("VideoRepository", VideoRepository)
    search_fn = _scanner_attr("smart_search", smart_search)
    uncensored_fn = _scanner_attr("is_uncensored_mode_effective", is_uncensored_mode_effective)
    embed_fn = _scanner_attr("_embed_cover", _embed_cover)
    resolve_out = _scanner_attr("resolve_gallery_output_path", resolve_gallery_output_path)
    generator_cls = _scanner_attr("HTMLGenerator", HTMLGenerator)

    numbers = [n.strip() for n in body.numbers if isinstance(n, str) and n.strip()]
    config = load_cfg()
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

    try:
        db_path = db_path_fn()
        repo = repo_cls(db_path)
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
                img=v.cover_path or '',
            )
            all_videos.append(info)
        else:
            try:
                scrape_results = search_fn(num, limit=1, uncensored_mode=uncensored_fn(config))
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
                    img=r.get('cover', '') or r.get('cover_url', ''),
                )
                all_videos.append(info)
            else:
                missing.append(num)

    embedded_count = 0
    embed_failed_count = 0
    if body.embed_covers:
        for info in all_videos:
            if info.img:
                original = info.img
                info.img = embed_fn(info.img, gallery_config.get('path_mappings', {}))
                if info.img.startswith('data:'):
                    embedded_count += 1
                elif original:
                    embed_failed_count += 1

    output_path = resolve_out(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    html_filename = f'gallery_custom_{timestamp}.html'
    html_path = output_path / html_filename

    try:
        generator = generator_cls()
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
    is_win = _scanner_attr("_is_windows", _is_windows)
    return PureWindowsPath if is_win() else PurePosixPath


def _compute_parent(path: str) -> Optional[str]:
    if not path:
        return None
    flavour_fn = _scanner_attr("_path_flavour", _path_flavour)
    is_win = _scanner_attr("_is_windows", _is_windows)
    flavour = flavour_fn()
    p = flavour(path)
    if p.parent == p:
        return "" if is_win() else None
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

    realpath_fn = _scanner_attr("safe_realpath", safe_realpath)
    is_win = _scanner_attr("_is_windows", _is_windows)
    gallery_cfg = config.get('gallery') or {}
    sources = iter_gallery_sources(gallery_cfg)
    if sources:
        path_mappings = gallery_cfg.get('path_mappings', {})
        fs = uri_to_local_fs_path(sources[0].path, path_mappings)
        parent = str(Path(fs).parent)
        resolved = realpath_fn(parent, 'browse-dir')
        if os.path.isdir(resolved):
            try:
                with os.scandir(resolved):
                    pass
                return resolved
            except OSError:
                logger.warning("browse-dir: 起點列舉失敗，退回平台根 path=%s", resolved)
    return "" if is_win() else "/"


def browse_dir(path: Optional[str] = Query(None), expand: Optional[str] = Query(None)):
    load_cfg = _scanner_attr("load_config", load_config)
    is_win = _scanner_attr("_is_windows", _is_windows)
    start_dir_fn = _scanner_attr("_browse_start_dir", _browse_start_dir)
    list_drives_fn = _scanner_attr("_list_windows_drives", _list_windows_drives)
    realpath_fn = _scanner_attr("safe_realpath", safe_realpath)
    parent_fn = _scanner_attr("_compute_parent", _compute_parent)

    config = load_cfg()
    if path is None or (path == "" and not is_win()):
        current_path = start_dir_fn(config)
    else:
        current_path = path

    if current_path == "" and is_win():
        drives = list_drives_fn()
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

    resolved_path = realpath_fn(current_path, "browse-dir")
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

    parent_path = parent_fn(resolved_path)
    result = {
        "current_path": resolved_path,
        "parent_path": parent_path,
        "entries": entries,
    }
    if expand == "videos":
        result["files"] = video_files
    return result
