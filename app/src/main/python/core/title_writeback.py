"""title_writeback.py — 就地改寫 NFO 的標題相關元素（TASK-172-T1，CD-172-4）。

只改 <title>／<originaltitle>／（已存在才同步的）<sorttitle>／<openaver_title_record>，
其餘元素原樣保留。顯示標題計算全部委派 core.nfo_title_format.build_display_title。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import os
from pathlib import Path

from core.android_storage import (
    AndroidStoragePermissionError,
    AndroidStorageWriteError,
)
from core.atomic_write import atomic_write
from core.nfo_read import nfo_first_text
from core.nfo_stat import nfo_mtime_or_none
from core.nfo_title_format import build_display_title
from core.nfo_updater import set_element_text
from core.nfo_utils import find_sidecar_nfos, sanitize_nfo_bytes
from core.organizer import _strip_illegal_xml_chars
from core.path_utils import is_path_under_dir, uri_to_local_fs_path
from core.readonly_paths import resolve_owning_output_root

# 公開別名：路由層寫 DB 前用同一支淨化函式（NFO 與 DB 同值）
strip_illegal_xml_chars = _strip_illegal_xml_chars

_DEFAULT_FORMAT = '[{num}]{title}'


class NfoNotFoundError(Exception):
    """NFO 檔案不存在。"""


class NfoParseError(Exception):
    """NFO 內容無法解析成 XML（sanitize 後仍失敗）。"""


def rewrite_nfo_titles(
    nfo_path,
    *,
    number,
    title_body,
    original_title,
    actors,
    maker,
    date,
    nfo_title_format,
) -> bytes:
    """改寫 NFO 的標題元素並回傳寫出的 bytes。

    NFO 不存在 → NfoNotFoundError；XML 無法解析 → NfoParseError（檔案不動）；
    讀／寫的 OSError 不包裝、原樣往外拋。
    """
    path = Path(nfo_path)
    if not path.exists():
        raise NfoNotFoundError(str(nfo_path))

    # sink 淨化（NFO-CTRL-01）：先淨化、後算顯示標題（與 generate_nfo 同序）
    number = _strip_illegal_xml_chars(number)
    title_body = _strip_illegal_xml_chars(title_body)
    original_title = _strip_illegal_xml_chars(original_title)
    maker = _strip_illegal_xml_chars(maker)
    date = _strip_illegal_xml_chars(date)
    actors = [_strip_illegal_xml_chars(a) for a in (actors or [])]

    raw = path.read_bytes()
    raw = sanitize_nfo_bytes(raw)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise NfoParseError(str(e)) from e

    display_title, body = build_display_title(
        number, title_body, original_title, actors, maker, date, nfo_title_format,
    )

    if number and not nfo_first_text(root, ("num", "id")):
        set_element_text(root, "num", number, after_tag="title")
    set_element_text(root, "title", display_title, after_tag="num")
    set_element_text(root, "originaltitle", original_title, after_tag="title")
    if root.find("sorttitle") is not None:
        root.find("sorttitle").text = display_title

    for old in list(root.findall("openaver_title_record")):
        root.remove(old)
    if nfo_title_format != _DEFAULT_FORMAT:
        rec = ET.SubElement(root, "openaver_title_record")
        ET.SubElement(rec, "written").text = display_title
        ET.SubElement(rec, "body").text = body

    out = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    # Android／外接儲存上的直接 write_bytes 若中途失敗會把原 NFO 截斷。
    # 同目錄暫存 + replace 讓失敗時原檔保持不變。
    with atomic_write(
        path, mode="wb", suffix=".nfo.tmp", mobile_fallback=True
    ) as fh:
        fh.write(out)
    return out


def create_title_only_nfo(
    nfo_path,
    *,
    number,
    title_body,
    original_title,
    actors,
    maker,
    date,
    nfo_title_format,
) -> bytes:
    """Create a minimal sidecar with title-related fields only.

    This is used by the combined rename flow when a video has no NFO yet.
    It intentionally does not emit the full metadata set produced by
    ``generate_nfo``: only the number needed to resolve the display title,
    the title, the original title, and the title-preservation record (when a
    custom title format is configured).
    """
    path = Path(nfo_path)
    if path.exists():
        raise FileExistsError(str(nfo_path))

    number = _strip_illegal_xml_chars(number)
    title_body = _strip_illegal_xml_chars(title_body)
    original_title = _strip_illegal_xml_chars(original_title)
    maker = _strip_illegal_xml_chars(maker)
    date = _strip_illegal_xml_chars(date)
    actors = [_strip_illegal_xml_chars(a) for a in (actors or [])]

    display_title, body = build_display_title(
        number, title_body, original_title, actors, maker, date, nfo_title_format,
    )

    root = ET.Element("movie")
    if number:
        ET.SubElement(root, "num").text = number
    ET.SubElement(root, "title").text = display_title
    ET.SubElement(root, "originaltitle").text = original_title
    if nfo_title_format != _DEFAULT_FORMAT:
        record = ET.SubElement(root, "openaver_title_record")
        ET.SubElement(record, "written").text = display_title
        ET.SubElement(record, "body").text = body

    out = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    with atomic_write(
        path, mode="wb", suffix=".nfo.tmp", mobile_fallback=True
    ) as fh:
        fh.write(out)
    return out


def _locate_readonly_nfo(video, path_mappings: dict, output_uri: str):
    if not video.output_dir:
        return None, "no_nfo"
    if not output_uri or not is_path_under_dir(video.output_dir, output_uri):
        return None, "no_nfo"
    out_fs = Path(uri_to_local_fs_path(video.output_dir, path_mappings))
    video_fs = Path(uri_to_local_fs_path(video.path, path_mappings))
    try:
        exact = find_sidecar_nfos(out_fs / video_fs.name)
        if exact:
            return str(exact[0]), None
        with os.scandir(out_fs) as it:
            nfo_files = sorted(
                entry.path
                for entry in it
                if entry.name.lower().endswith(".nfo") and entry.is_file()
            )
    except FileNotFoundError:
        return None, "no_nfo"
    except OSError:
        return None, "nfo_unreadable"
    if len(nfo_files) > 1:
        return None, "nfo_ambiguous"
    if not nfo_files:
        return None, "no_nfo"
    return nfo_files[0], None


def _locate_nfo(video, config: dict, path_mappings: dict):
    owning = resolve_owning_output_root(video.path, config)
    if owning is not None:
        return _locate_readonly_nfo(video, path_mappings, owning[2])
    candidates = find_sidecar_nfos(
        uri_to_local_fs_path(video.path, path_mappings)
    )
    if not candidates:
        return None, "no_nfo"
    if len(candidates) > 1:
        return None, "nfo_ambiguous"
    return str(candidates[0]), None


def _target_nfo_path(video, config: dict, path_mappings: dict):
    owning = resolve_owning_output_root(video.path, config)
    if owning is not None:
        if not video.output_dir:
            return None
        output_dir = Path(
            uri_to_local_fs_path(video.output_dir, path_mappings)
        )
        video_fs = Path(uri_to_local_fs_path(video.path, path_mappings))
        return output_dir / f"{video_fs.stem}.nfo"
    return Path(
        uri_to_local_fs_path(video.path, path_mappings)
    ).with_suffix(".nfo")


def apply_title_writeback(
    repo,
    video,
    title: str,
    original_title: str | None,
    config: dict,
    path_mappings: dict,
) -> dict:
    """Write one translated title to the sidecar and DB.

    The function is deliberately limited to title fields. It never replaces
    existing plot, tags, artwork references, or user tags.
    """
    fmt = (config.get("scraper") or {}).get(
        "nfo_title_format", _DEFAULT_FORMAT
    )
    clean_title = strip_illegal_xml_chars(title).strip()
    if not clean_title:
        return {"success": False, "error": "title_empty"}
    display_title, body = build_display_title(
        video.number or "",
        clean_title,
        "",
        video.actresses,
        video.maker,
        video.release_date,
        fmt,
    )
    if not body:
        return {"success": False, "error": "title_empty"}
    new_original = strip_illegal_xml_chars(
        original_title
        if original_title is not None
        else (video.original_title or video.title)
    )

    nfo_path, locate_error = _locate_nfo(video, config, path_mappings)
    try:
        if nfo_path is None:
            if locate_error not in ("no_nfo",):
                return {"success": False, "error": locate_error}
            target = _target_nfo_path(video, config, path_mappings)
            if target is None:
                return {"success": False, "error": "no_nfo"}
            create_title_only_nfo(
                target,
                number=video.number or "",
                title_body=body,
                original_title=new_original,
                actors=video.actresses,
                maker=video.maker,
                date=video.release_date,
                nfo_title_format=fmt,
            )
            nfo_path = str(target)
        else:
            rewrite_nfo_titles(
                nfo_path,
                number=video.number or "",
                title_body=body,
                original_title=new_original,
                actors=video.actresses,
                maker=video.maker,
                date=video.release_date,
                nfo_title_format=fmt,
            )
    except NfoNotFoundError:
        return {"success": False, "error": "no_nfo"}
    except NfoParseError:
        return {"success": False, "error": "nfo_unreadable"}
    except FileExistsError:
        return {"success": False, "error": "nfo_write_failed"}
    except AndroidStoragePermissionError:
        return {
            "success": False,
            "error": "storage_permission_required",
        }
    except (AndroidStorageWriteError, OSError):
        return {"success": False, "error": "nfo_write_failed"}

    new_mtime = nfo_mtime_or_none(Path(nfo_path))
    if new_mtime is None:
        new_mtime = video.nfo_mtime
    try:
        written = repo.update_titles(
            video.path, body, new_original, new_mtime
        )
    except Exception:
        return {"success": False, "error": "db_write_failed"}
    if not written:
        return {"success": False, "error": "not_found"}
    return {
        "success": True,
        "title": body,
        "original_title": new_original,
        "nfo_updated": True,
    }
