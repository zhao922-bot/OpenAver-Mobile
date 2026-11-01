"""Preview planning for normalizing individual video filenames."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.path_utils import to_file_uri, uri_to_fs_path
from core.rename_names import (
    SIDECAR_EXTENSIONS,
    _find_repair_video,
    _fit_filename_stem,
    _operation_kind,
    _path_key,
    _sidecar_matches,
    _sidecar_suffix,
    _utf8_len,
    canonicalize_stem,
)
from core.scrapers.utils import extract_number, normalize_number_impl
from core.video_extensions import get_video_extensions


def _stat_signature(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _plan_id(items: list[dict[str, Any]]) -> str:
    payload = []
    for item in sorted(items, key=lambda value: value["old_video_path"].casefold()):
        if item["status"] != "ready":
            continue
        payload.append({
            "old": item["old_video_path"],
            "new": item["new_video_path"],
            "db_old": item["db_old_uri"],
            "db_new": item["db_new_uri"],
            "ops": [
                {
                    "old": op["old_path"],
                    "new": op["new_path"],
                    # Android external-storage clients can expose volatile
                    # submicrosecond mtime values. Size and path are sufficient
                    # to detect a changed plan; rename itself still rejects a
                    # missing source or an existing target.
                    "size": op["signature"].get("size"),
                }
                for op in item["operations"]
            ],
        })
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _plan_rename_item(
    video: Any,
    video_extensions: set[str],
    path_mappings: dict | None,
    stem_overrides: dict[str, str] | None,
) -> dict[str, Any] | None:
    """Build the preview item for one database row."""
    old_uri = str(getattr(video, "path", "") or "")
    if not old_uri:
        return None
    expected_path = Path(uri_to_fs_path(old_uri))
    source_path = expected_path
    number_hint = getattr(video, "number", None)
    item: dict[str, Any] = {
        "db_old_uri": old_uri,
        "db_new_uri": old_uri,
        "old_video_path": str(source_path),
        "new_video_path": str(source_path),
        "old_name": source_path.name,
        "new_name": source_path.name,
        "number": number_hint,
        "cover_path_old": str(getattr(video, "cover_path", "") or ""),
        "cover_path_new": str(getattr(video, "cover_path", "") or ""),
        "operations": [],
        "associated_files": [],
        "conflicts": [],
        "status": "unchanged",
        "reason": "unchanged",
        "recovered_missing_source": False,
    }

    repaired_source = False
    try:
        source_exists = source_path.is_file()
    except OSError:
        # Linux returns ENAMETOOLONG here for the exact path that Android
        # may expose through a truncated sibling instead.
        source_exists = False
    if not source_exists:
        number_hint = extract_number(expected_path.name) or number_hint
        recovered = _find_repair_video(
            expected_path,
            str(number_hint) if number_hint else None,
            video_extensions,
        )
        if recovered is None:
            item["status"] = "missing"
            item["reason"] = "source_not_found"
            return item
        source_path = recovered
        repaired_source = True
        item["old_video_path"] = str(source_path)
        item["new_video_path"] = str(source_path)
        item["old_name"] = source_path.name
        item["new_name"] = source_path.name
        item["recovered_missing_source"] = True

    override_stem = (stem_overrides or {}).get(old_uri)
    if override_stem:
        new_stem = override_stem
        number = (
            normalize_number_impl(str(number_hint))
            if number_hint
            else extract_number(override_stem)
        )
        reason = "source_title"
    else:
        new_stem, number, reason = canonicalize_stem(
            expected_path.stem if repaired_source else source_path.stem,
            number_hint,
        )
    item["number"] = number
    if reason == "no_number":
        item["status"] = "skipped"
        item["reason"] = reason
        return item
    if reason == "number_not_located":
        item["status"] = "conflict"
        item["reason"] = reason
        item["conflicts"].append(reason)
        return item
    if reason == "empty_name":
        item["status"] = "conflict"
        item["reason"] = reason
        item["conflicts"].append(reason)
        return item

    try:
        children = sorted(
            source_path.parent.iterdir(),
            key=lambda path: path.name.casefold(),
        )
    except OSError as exc:
        item["status"] = "conflict"
        item["reason"] = "list_directory_failed"
        item["conflicts"].append(str(exc))
        return item

    source_stem = source_path.stem
    selected: list[tuple[Path, str]] = []
    for child in children:
        if not child.is_file():
            continue
        extension = child.suffix.lower()
        is_current_video = _path_key(str(child)) == _path_key(str(source_path))
        if not is_current_video:
            if extension in video_extensions:
                continue
            if extension not in SIDECAR_EXTENSIONS:
                continue
            matches_source = _sidecar_matches(source_stem, child.name)
            matches_repair = (
                repaired_source
                and number
                and extract_number(child.name) == number
            )
            if not matches_source and not matches_repair:
                continue
        suffix = (
            source_path.suffix
            if is_current_video
            else _sidecar_suffix(
                child.name,
                [source_stem, expected_path.stem, new_stem],
            )
        )
        if suffix is None:
            continue
        selected.append((child, suffix))

    if not selected:
        item["status"] = "conflict"
        item["reason"] = "no_operations"
        item["conflicts"].append("no_operations")
        return item

    max_suffix_bytes = max(_utf8_len(suffix) for _, suffix in selected)
    fitted_stem = _fit_filename_stem(new_stem, max_suffix_bytes)
    if fitted_stem is None:
        item["status"] = "conflict"
        item["reason"] = "target_name_too_long"
        item["conflicts"].append("target_name_too_long")
        return item

    new_path = source_path.with_name(fitted_stem + source_path.suffix)
    item["new_video_path"] = str(new_path)
    item["new_name"] = new_path.name
    item["db_new_uri"] = to_file_uri(str(new_path), path_mappings)
    item["associated_files"] = [
        {
            "old_path": str(child),
            "new_path": str(child.with_name(fitted_stem + suffix)),
        }
        for child, suffix in selected
    ]

    operations: list[dict[str, Any]] = []
    for child, suffix in selected:
        target_name = fitted_stem + suffix
        kind = _operation_kind(child.name, video_extensions)
        if repaired_source and kind == "cover":
            # MTP/FUSE may have truncated both the video and its primary
            # cover, while the database still contains the original full
            # name. Point it at the repaired on-device cover even though the
            # stored path never matched the truncated source.
            item["cover_path_new"] = to_file_uri(
                str(child.with_name(target_name)),
                path_mappings,
            )
        if str(child) == str(child.with_name(target_name)):
            continue
        operation = {
            "old_path": str(child),
            "new_path": str(child.with_name(target_name)),
            "old_name": child.name,
            "new_name": target_name,
            "kind": kind,
            "signature": _stat_signature(child),
        }
        operations.append(operation)

        if str(child) == str(source_path):
            continue
        old_cover = item["cover_path_old"]
        if old_cover:
            cover_fs = uri_to_fs_path(old_cover)
            if _path_key(cover_fs) == _path_key(str(child)):
                item["cover_path_new"] = to_file_uri(
                    operation["new_path"],
                    path_mappings,
                )

    operations.sort(
        key=lambda op: (op["kind"] != "video", op["old_name"].casefold())
    )
    item["operations"] = operations
    if not operations and not repaired_source:
        if fitted_stem == source_path.stem:
            item["status"] = "unchanged"
            item["reason"] = "unchanged"
        else:
            item["status"] = "conflict"
            item["reason"] = "no_operations"
            item["conflicts"].append("no_operations")
    else:
        item["status"] = "ready"
        item["reason"] = "repair_and_rename" if repaired_source else "rename"
    return item


def _mark_rename_conflicts(items: list[dict[str, Any]]) -> None:
    """Detect case-only, existing-target, and duplicate-target conflicts."""
    source_keys = {
        _path_key(op["old_path"])
        for item in items
        for op in item["operations"]
    }
    target_to_items: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        for op in item["operations"]:
            target_to_items.setdefault(
                _path_key(op["new_path"]),
                [],
            ).append(item)

    for item in items:
        for op in item["operations"]:
            old_key = _path_key(op["old_path"])
            new_key = _path_key(op["new_path"])
            target = Path(op["new_path"])
            if old_key == new_key and op["old_path"] != op["new_path"]:
                item["conflicts"].append("case_only_rename")
            if target.exists() and new_key not in source_keys:
                item["conflicts"].append(
                    f"target_exists:{op['new_name']}"
                )
            if new_key in source_keys and new_key != old_key:
                item["conflicts"].append(
                    f"target_is_another_source:{op['new_name']}"
                )
            if len(target_to_items[new_key]) > 1:
                item["conflicts"].append(
                    f"duplicate_target:{op['new_name']}"
                )
        if item["conflicts"]:
            item["status"] = "conflict"
            item["reason"] = item["conflicts"][0]
        item["conflicts"] = sorted(set(item["conflicts"]))


def _rename_plan_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    ready = [item for item in items if item["status"] == "ready"]
    conflicts = [item for item in items if item["status"] == "conflict"]
    unchanged = [item for item in items if item["status"] == "unchanged"]
    skipped = [item for item in items if item["status"] == "skipped"]
    missing = [item for item in items if item["status"] == "missing"]
    return {
        "total": len(items),
        "rename_videos": len(ready),
        "rename_files": sum(len(item["operations"]) for item in ready),
        "conflicts": len(conflicts),
        "unchanged": len(unchanged),
        "skipped": len(skipped),
        "missing": len(missing),
    }


def build_rename_plan(
    videos: list[Any],
    *,
    path_mappings: dict | None = None,
    config: dict | None = None,
    stem_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a deterministic preview without modifying files or the database."""
    video_extensions = get_video_extensions(config or {})
    items: list[dict[str, Any]] = []

    for video in videos:
        item = _plan_rename_item(
            video,
            video_extensions,
            path_mappings,
            stem_overrides,
        )
        if item is not None:
            items.append(item)

    _mark_rename_conflicts(items)
    return {
        "plan_id": _plan_id(items),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": _rename_plan_summary(items),
        "items": items,
    }
