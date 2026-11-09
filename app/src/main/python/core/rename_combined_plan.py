"""Combined filename/folder rename planning, execution, and validation."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.atomic_write import atomic_write
from core.media_io import delete_file
from core.multipart_group import group_rows
from core.nfo_utils import find_sidecar_nfos
from core.path_utils import to_file_uri, uri_to_fs_path
from core.rename_file_plan import build_rename_plan
from core.rename_names import (
    _fit_filename_stem,
    _path_key,
    _strip_multipart_token,
    multipart_token,
    source_title_body,
)
from core.rename_shared import (
    _apply_rename_updates,
    _create_directory,
    _delete_directory,
    _is_direct_child,
    _is_source_root,
    _move_file,
    _rebase_path,
    _rebase_path_list,
    _rename_directory,
    _rename_file,
    _write_manifest,
)
from core.scrapers.utils import extract_number, normalize_number_impl
from core.video_extensions import get_video_extensions


def _rewrite_nfo_titles(nfo_path, **kwargs) -> bytes:
    # Keep the heavier NFO/organizer imports out of module initialization.
    from core.title_writeback import rewrite_nfo_titles

    return rewrite_nfo_titles(nfo_path, **kwargs)


def _create_nfo_titles(nfo_path, **kwargs) -> bytes:
    # Keep the heavier NFO/organizer imports out of module initialization.
    from core.title_writeback import create_title_only_nfo

    return create_title_only_nfo(nfo_path, **kwargs)


def _nfo_title_format(config: dict | None) -> str:
    scraper_config = (config or {}).get("scraper", {})
    return str(
        scraper_config.get("nfo_title_format", "[{num}]{title}")
        if isinstance(scraper_config, dict)
        else "[{num}]{title}"
    )


def _find_nfo_for_video(video_path: str, number: str) -> Path | None:
    """Find the sidecar for an actual video after a platform path rewrite."""
    if not video_path:
        return None
    video = Path(video_path)
    exact = find_sidecar_nfos(video)
    if exact:
        return exact[0]

    normalized_number = normalize_number_impl(str(number or ""))
    try:
        entries = sorted(
            (
                Path(entry.path)
                for entry in os.scandir(video.parent)
                if entry.is_file(follow_symlinks=False)
                and Path(entry.name).suffix.lower() == ".nfo"
            ),
            key=lambda path: path.name.casefold(),
        )
    except OSError:
        return None
    if not entries:
        return None

    if normalized_number:
        numbered = [
            path
            for path in entries
            if (
                (candidate := extract_number(path.name))
                and normalize_number_impl(candidate) == normalized_number
            )
        ]
        if len(numbered) == 1:
            return numbered[0]
    if len(entries) == 1:
        return entries[0]
    return None


def _resolve_title_nfo_path(update: dict[str, Any]) -> Path:
    """Resolve the title sidecar without trusting a stale plan path."""
    video_path = str(update.get("new_video_path") or "")
    number = str(update.get("number") or "")
    if video_path:
        video = Path(video_path)
        found = _find_nfo_for_video(video_path, number)
        if found is not None:
            return found
        default = video.with_suffix(".nfo")
        if not default.is_dir():
            return default

    planned = Path(str(update.get("nfo_path_new") or ""))
    if planned.is_file():
        return planned
    if planned.is_dir():
        stem = planned.stem or "title"
        return planned.with_name(f"{stem}.openaver.nfo")
    return planned


def _same_number_videos(
    directory: Path,
    update: dict[str, Any],
) -> list[Path]:
    """Return files in *directory* that can be the planned video."""
    number = normalize_number_impl(str(update.get("number") or ""))
    if not number:
        return []
    extensions = get_video_extensions({})
    expected_size = int(update.get("expected_size") or 0)
    expected_token = multipart_token(
        Path(str(update.get("new_video_path") or "")).stem
    )
    candidates: list[Path] = []
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return []
    for entry in entries:
        try:
            if (
                not entry.is_file(follow_symlinks=False)
                or Path(entry.name).suffix.lower() not in extensions
            ):
                continue
            candidate_number = extract_number(entry.name)
            if (
                not candidate_number
                or normalize_number_impl(candidate_number) != number
            ):
                continue
            path = Path(entry.path)
            if expected_size and path.stat().st_size != expected_size:
                continue
            token = multipart_token(path.stem)
            if expected_token and token != expected_token:
                continue
            candidates.append(path)
        except OSError:
            continue
    return sorted(candidates, key=lambda path: path.name.casefold())


def _resolve_actual_video_path(update: dict[str, Any]) -> Path | None:
    """Recover a path normalized by Android after a successful rename."""
    planned = Path(str(update.get("new_video_path") or ""))
    if planned.is_file():
        return planned

    directories: list[Path] = []
    if planned.parent.is_dir():
        directories.append(planned.parent)
    folder_parent = planned.parent.parent
    number = normalize_number_impl(str(update.get("number") or ""))
    if folder_parent.is_dir() and number:
        try:
            for entry in os.scandir(folder_parent):
                if not entry.is_dir(follow_symlinks=False):
                    continue
                candidate_number = extract_number(entry.name)
                if (
                    candidate_number
                    and normalize_number_impl(candidate_number) == number
                ):
                    directories.append(Path(entry.path))
        except OSError:
            pass

    seen: set[str] = set()
    for directory in directories:
        key = _path_key(str(directory))
        if key in seen:
            continue
        seen.add(key)
        candidates = _same_number_videos(directory, update)
        exact = [
            path
            for path in candidates
            if path.name.casefold() == planned.name.casefold()
        ]
        if len(exact) == 1:
            return exact[0]
        if len(candidates) == 1:
            return candidates[0]
    return None


def _reconcile_video_update(
    update: dict[str, Any],
    path_mappings: dict,
) -> None:
    """Point database/sidecar updates at the file Android actually created."""
    planned = Path(str(update.get("new_video_path") or ""))
    actual = _resolve_actual_video_path(update)
    if actual is None:
        return
    if _path_key(str(actual)) == _path_key(str(planned)):
        return

    update["new_video_path"] = str(actual)
    update["db_new_uri"] = to_file_uri(str(actual), path_mappings)
    old_parent = planned.parent
    new_parent = actual.parent

    nfo_path = Path(str(update.get("nfo_path_new") or ""))
    if nfo_path and _path_key(str(nfo_path.parent)) == _path_key(
        str(old_parent)
    ):
        update["nfo_path_new"] = str(new_parent / nfo_path.name)

    cover_path = str(update.get("cover_path_new") or "")
    if cover_path:
        cover_fs = Path(uri_to_fs_path(cover_path))
        suffix = cover_fs.suffix
        candidate = actual.with_suffix(suffix) if suffix else actual
        if suffix and candidate.is_file():
            update["cover_path_new"] = to_file_uri(
                str(candidate),
                path_mappings,
            )
        elif _path_key(str(cover_fs.parent)) == _path_key(str(old_parent)):
            update["cover_path_new"] = to_file_uri(
                str(new_parent / cover_fs.name),
                path_mappings,
            )

    update["sample_images_new"] = _rebase_path_list(
        list(update.get("sample_images_new") or []),
        old_parent,
        new_parent,
        path_mappings,
    )


def _resolve_actual_folder_path(
    planned_folder: str,
    number: str,
) -> Path | None:
    planned = Path(planned_folder)
    if planned.is_dir():
        return planned
    normalized_number = normalize_number_impl(str(number or ""))
    if not normalized_number or not planned.parent.is_dir():
        return None
    candidates: list[Path] = []
    try:
        for entry in os.scandir(planned.parent):
            if not entry.is_dir(follow_symlinks=False):
                continue
            candidate_number = extract_number(entry.name)
            if (
                candidate_number
                and normalize_number_impl(candidate_number) == normalized_number
            ):
                candidates.append(Path(entry.path))
    except OSError:
        return None
    return candidates[0] if len(candidates) == 1 else None


def _combined_plan_id(items: list[dict[str, Any]], source_id: str) -> str:
    payload = []
    for item in sorted(items, key=lambda value: value["old_folder_path"].casefold()):
        if item["status"] != "ready":
            continue
        payload.append({
            "source": source_id,
            "folder_old": item["old_folder_path"],
            "folder_new": item["new_folder_path"],
            "folder_action": item.get("folder_action", "none"),
            "move_files": [
                {
                    "old": move["old_path"],
                    "after_rename": move["after_rename_path"],
                    "new": move["new_path"],
                }
                for move in item.get("move_files", [])
            ],
            "videos": [
                {
                    "old": video["db_old_uri"],
                    "new": video["db_new_uri"],
                    "operations": [
                        {
                            "old": operation["old_path"],
                            "new": operation["new_path"],
                            "size": operation["signature"].get("size"),
                        }
                        for operation in video["operations"]
                    ],
                    "title_old": video.get("title_old", ""),
                    "title_new": video.get("title_new", ""),
                    "original_title_old": video.get(
                        "original_title_old", ""
                    ),
                    "original_title_new": video.get(
                        "original_title_new", ""
                    ),
                    "title_update": bool(video.get("title_update")),
                    "number": video.get("number"),
                    "nfo_path_old": video.get("nfo_path_old", ""),
                    "nfo_path_new": video.get("nfo_path_new", ""),
                }
                for video in item["videos"]
            ],
        })
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _multipart_item_key(file_item: dict[str, Any]) -> tuple[str, int] | None:
    stem = Path(file_item["old_video_path"]).stem
    token = multipart_token(stem)
    if not token:
        return None
    base = re.sub(r"\s+", "", _strip_multipart_token(stem)).casefold()
    if not base:
        return None
    return base, int(token[-1])


def _group_file_plan_items(
    file_plan: dict[str, Any],
    roots: list[Path],
) -> list[list[dict[str, Any]]]:
    """Group file plan rows by folder, splitting source-root files."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for file_item in file_plan["items"]:
        folder = Path(file_item["old_video_path"]).parent
        grouped.setdefault(_path_key(str(folder)), []).append(file_item)

    groups: list[list[dict[str, Any]]] = []
    for group in grouped.values():
        folder = Path(group[0]["old_video_path"]).parent
        if _is_source_root(folder, roots):
            # Root-level videos normally become separate target folders. A
            # real multipart set is the exception: all parts must move into
            # one folder so the scanner can present them as a single card.
            multipart_buckets: dict[str, list[dict[str, Any]]] = {}
            ordered = sorted(
                group,
                key=lambda row: row["old_video_path"].casefold(),
            )
            for file_item in ordered:
                key = _multipart_item_key(file_item)
                if key is None:
                    groups.append([file_item])
                    continue
                multipart_buckets.setdefault(key[0], []).append(file_item)
            for bucket in multipart_buckets.values():
                part_numbers = [
                    key[1]
                    for key in (_multipart_item_key(item) for item in bucket)
                    if key is not None
                ]
                if (
                    len(bucket) >= 2
                    and len(part_numbers) == len(bucket)
                    and len(set(part_numbers)) == len(part_numbers)
                ):
                    groups.append(bucket)
                else:
                    groups.extend([item] for item in bucket)
        else:
            groups.append(
                sorted(
                    group,
                    key=lambda row: row["old_video_path"].casefold(),
                )
            )

    return sorted(
        groups,
        key=lambda rows: rows[0]["old_video_path"].casefold(),
    )


def _multipart_primary_index(
    file_items: list[dict[str, Any]],
) -> tuple[int, bool]:
    """Return the primary row index and whether the group is multipart."""
    multipart_members = [
        (index, key)
        for index, item in enumerate(file_items)
        if (key := _multipart_item_key(item)) is not None
    ]
    multipart_group = (
        len(file_items) >= 2
        and len(multipart_members) == len(file_items)
        and len({key[1] for _, key in multipart_members})
        == len(multipart_members)
    )
    if multipart_group:
        return (
            min(
                multipart_members,
                key=lambda entry: entry[1][1],
            )[0],
            True,
        )
    return 0, False


def _build_combined_item(
    file_items: list[dict[str, Any]],
    rows_by_uri: dict[str, Any],
    roots: list[Path],
    stem_overrides: dict[str, str],
    path_mappings: dict | None,
    nfo_title_format: str,
) -> dict[str, Any]:
    """Build one folder-level item from its source files."""
    folder = Path(file_items[0]["old_video_path"]).parent
    rows = [rows_by_uri[item["db_old_uri"]] for item in file_items]
    folder_number = extract_number(folder.name)
    primary_index, multipart_group = _multipart_primary_index(file_items)
    if not multipart_group:
        if folder_number:
            normalized_folder_number = normalize_number_impl(str(folder_number))
            for index, item in enumerate(file_items):
                if item.get("number") == normalized_folder_number:
                    primary_index = index
                    break
        else:
            primary_index = max(
                range(len(rows)),
                key=lambda index: int(getattr(rows[index], "size_bytes", 0) or 0),
            )

    primary = file_items[primary_index]
    primary_override = stem_overrides.get(primary["db_old_uri"], "")
    folder_stem_override = (
        _strip_multipart_token(primary_override)
        if multipart_group
        else primary_override
    )
    fitted_folder_stem = _fit_filename_stem(folder_stem_override, 0)
    root_level = _is_source_root(folder, roots)
    if root_level and fitted_folder_stem:
        folder_action = "create"
        new_folder = folder / fitted_folder_stem
    elif _is_direct_child(folder, roots) and fitted_folder_stem:
        candidate_folder = folder.with_name(fitted_folder_stem)
        if candidate_folder == folder:
            folder_action = "none"
            new_folder = folder
        else:
            folder_action = "rename"
            new_folder = candidate_folder
    else:
        folder_action = "none"
        new_folder = folder

    item: dict[str, Any] = {
        "old_folder_path": str(folder),
        "new_folder_path": str(new_folder),
        "old_name": folder.name,
        "new_name": new_folder.name,
        "folder_action": folder_action,
        "number": primary.get("number"),
        "source_title": primary_override,
        "move_files": [],
        "videos": [],
        "conflicts": [],
        "status": "unchanged",
        "reason": "unchanged",
    }

    for file_item, row in zip(file_items, rows, strict=True):
        final_video = new_folder / Path(file_item["new_video_path"]).name
        source_stem = (
            stem_overrides.get(file_item["db_old_uri"])
            or primary_override
        )
        source_title_new = source_title_body(
            source_stem,
            file_item.get("number") or primary.get("number"),
        )
        title_old = str(getattr(row, "title", "") or "")
        original_title_old = str(
            getattr(row, "original_title", "") or ""
        )
        # A non-empty original title persists a translated row. Unified naming
        # must not replace that user-visible translation with its source title.
        if title_old and original_title_old:
            title_new = title_old
            original_title_new = original_title_old
        else:
            title_new = source_title_new
            original_title_new = ""
        nfo_path_old = ""
        nfo_path_new = ""
        for associated in file_item.get("associated_files", []):
            old_path = Path(associated["old_path"])
            if old_path.suffix.lower() != ".nfo":
                continue
            nfo_path_old = str(old_path)
            nfo_path_new = str(
                new_folder / Path(associated["new_path"]).name
            )
            break
        nfo_create = bool(title_new and not nfo_path_old)
        if nfo_create:
            nfo_path_new = str(final_video.with_suffix(".nfo"))
        title_update = bool(
            title_new
            and (
                title_old != title_new
                or original_title_old != original_title_new
                or nfo_create
            )
        )
        cover_new = file_item.get("cover_path_new") or ""
        if cover_new and new_folder != folder:
            cover_new = _rebase_path(
                cover_new,
                folder,
                new_folder,
                path_mappings,
            )
        samples_old = [
            str(value)
            for value in (getattr(row, "sample_images", None) or [])
        ]
        if folder_action == "create":
            samples_new = samples_old
        else:
            samples_new = _rebase_path_list(
                samples_old,
                folder,
                new_folder,
                path_mappings,
            )
        if folder_action == "create":
            for associated in file_item.get("associated_files", []):
                after_rename = Path(associated["new_path"])
                item["move_files"].append({
                    "old_path": associated["old_path"],
                    "after_rename_path": str(after_rename),
                    "new_path": str(new_folder / after_rename.name),
                })
        item["videos"].append({
            "db_old_uri": file_item["db_old_uri"],
            "db_new_uri": to_file_uri(str(final_video), path_mappings),
            "old_video_path": file_item["old_video_path"],
            "new_video_path": str(final_video),
            "old_name": file_item["old_name"],
            "new_name": final_video.name,
            "number": file_item.get("number"),
            "cover_path_old": file_item.get("cover_path_old") or "",
            "cover_path_new": cover_new,
            "sample_images_old": samples_old,
            "sample_images_new": samples_new,
            "operations": file_item.get("operations") or [],
            "title_old": title_old,
            "title_new": title_new,
            "original_title_old": original_title_old,
            "original_title_new": original_title_new,
            "title_update": title_update,
            "nfo_path_old": nfo_path_old,
            "nfo_path_new": nfo_path_new,
            "nfo_create": nfo_create,
            "nfo_title_format": nfo_title_format,
            "actresses": list(getattr(row, "actresses", None) or []),
            "maker": str(getattr(row, "maker", "") or ""),
            "release_date": str(
                getattr(row, "release_date", "") or ""
            ),
            "nfo_mtime_old": float(
                getattr(row, "nfo_mtime", 0) or 0
            ),
            "expected_size": int(
                getattr(row, "size_bytes", 0) or 0
            ),
            "status": file_item["status"],
            "reason": file_item["reason"],
            "conflicts": list(file_item.get("conflicts") or []),
        })
        item["conflicts"].extend(file_item.get("conflicts") or [])

    file_states = {video["status"] for video in item["videos"]}
    folder_changed = folder_action != "none"
    has_file_changes = any(
        video["operations"]
        for video in item["videos"]
    )
    has_title_changes = any(
        video["title_update"]
        for video in item["videos"]
    )
    if "conflict" in file_states:
        item["status"] = "conflict"
        item["reason"] = "file_conflict"
    elif "missing" in file_states:
        item["status"] = "missing"
        item["reason"] = "source_not_found"
    elif "skipped" in file_states:
        item["status"] = "skipped"
        item["reason"] = "skipped"
    elif folder_changed or has_file_changes or has_title_changes:
        item["status"] = "ready"
        item["reason"] = "source_title"
    return item


def _mark_combined_conflicts(items: list[dict[str, Any]]) -> None:
    """Detect folder, move, and video target collisions in place."""
    source_folders = {
        _path_key(item["old_folder_path"])
        for item in items
    }
    folder_targets: dict[str, list[dict[str, Any]]] = {}
    video_targets: dict[str, list[dict[str, Any]]] = {}
    move_targets: dict[str, list[dict[str, Any]]] = {}
    nfo_targets: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        if item.get("folder_action") != "none":
            folder_targets.setdefault(
                _path_key(item["new_folder_path"]),
                [],
            ).append(item)
        for video in item["videos"]:
            video_targets.setdefault(
                _path_key(video["new_video_path"]),
                [],
            ).append(video)
            if video.get("nfo_create") and video.get("nfo_path_new"):
                nfo_targets.setdefault(
                    _path_key(video["nfo_path_new"]),
                    [],
                ).append(video)
        for move in item.get("move_files", []):
            move_targets.setdefault(
                _path_key(move["new_path"]),
                [],
            ).append(move)

    for item in items:
        if item["status"] in {"missing", "skipped"}:
            continue
        old_folder_key = _path_key(item["old_folder_path"])
        new_folder_key = _path_key(item["new_folder_path"])
        if (
            old_folder_key == new_folder_key
            and item["old_folder_path"] != item["new_folder_path"]
        ):
            item["conflicts"].append("case_only_folder_rename")
        target = Path(item["new_folder_path"])
        if (
            item["new_folder_path"] != item["old_folder_path"]
            and target.exists()
            and new_folder_key not in source_folders
        ):
            item["conflicts"].append(
                f"folder_target_exists:{item['new_name']}"
            )
        if len(folder_targets.get(new_folder_key, [])) > 1:
            item["conflicts"].append(
                f"duplicate_folder_target:{item['new_name']}"
            )
        for move in item.get("move_files", []):
            if len(move_targets.get(_path_key(move["new_path"]), [])) > 1:
                item["conflicts"].append(
                    f"duplicate_move_target:{Path(move['new_path']).name}"
                )
        for video in item["videos"]:
            if len(video_targets.get(_path_key(video["new_video_path"]), [])) > 1:
                item["conflicts"].append(
                    f"duplicate_video_target:{video['new_name']}"
                )
            if video.get("nfo_create") and video.get("nfo_path_new"):
                nfo_target = Path(video["nfo_path_new"])
                if nfo_target.exists():
                    item["conflicts"].append(
                        f"nfo_target_exists:{nfo_target.name}"
                    )
                if len(nfo_targets.get(_path_key(str(nfo_target)), [])) > 1:
                    item["conflicts"].append(
                        f"duplicate_nfo_target:{nfo_target.name}"
                    )
        if item["conflicts"]:
            item["status"] = "conflict"
            item["reason"] = sorted(set(item["conflicts"]))[0]
        item["conflicts"] = sorted(set(item["conflicts"]))


def _combined_plan_summary(
    items: list[dict[str, Any]],
    failed_items: list[dict[str, Any]],
) -> dict[str, Any]:
    ready = [item for item in items if item["status"] == "ready"]
    conflicts = [item for item in items if item["status"] == "conflict"]
    unchanged = [item for item in items if item["status"] == "unchanged"]
    skipped = [item for item in items if item["status"] == "skipped"]
    missing = [item for item in items if item["status"] == "missing"]
    ready_videos = [
        video
        for item in ready
        for video in item["videos"]
    ]
    renamed_videos = [
        video
        for video in ready_videos
        if video["old_name"] != video["new_name"]
    ]
    title_videos = [
        video
        for video in ready_videos
        if video.get("title_update")
    ]

    def logical_count(videos: list[dict[str, Any]]) -> int:
        return len(group_rows(
            videos,
            fs_path_of=lambda video: video["old_video_path"],
        ))

    ready_logical_videos = logical_count(ready_videos)
    renamed_logical_videos = logical_count(renamed_videos)
    title_logical_videos = logical_count(title_videos)
    return {
        # User-facing "video" fields count complete multipart groups once.
        # Explicit physical/file fields remain available for execution details.
        "total": ready_logical_videos + len(failed_items),
        "groups": len(items),
        "rename_videos": renamed_logical_videos,
        "rename_files": sum(
            len(video["operations"])
            for video in ready_videos
        ),
        "rename_folders": sum(
            1
            for item in ready
            if item.get("folder_action") != "none"
        ),
        "updated_titles": title_logical_videos,
        "logical_videos": ready_logical_videos,
        "physical_ready_videos": len(ready_videos),
        "updated_videos": len(ready_videos),
        "conflicts": len(conflicts),
        "failed": len(failed_items),
        "unchanged": len(unchanged),
        "skipped": len(skipped),
        "missing": len(missing),
    }


def build_combined_rename_plan(
    videos: list[Any],
    *,
    source_id: str,
    stem_overrides: dict[str, str],
    source_roots: list[str],
    path_mappings: dict | None = None,
    config: dict | None = None,
    failed_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Combine source-titled file and direct-child folder normalization."""
    rows_by_uri = {
        str(getattr(video, "path", "") or ""): video
        for video in videos
    }
    file_plan = build_rename_plan(
        videos,
        path_mappings=path_mappings,
        config=config,
        stem_overrides=stem_overrides,
    )
    roots = [Path(uri_to_fs_path(str(root))) for root in source_roots if root]
    groups = _group_file_plan_items(file_plan, roots)
    title_format = _nfo_title_format(config)
    items = [
        _build_combined_item(
            file_items,
            rows_by_uri,
            roots,
            stem_overrides,
            path_mappings,
            title_format,
        )
        for file_items in groups
    ]
    _mark_combined_conflicts(items)

    failed_items = list(failed_items or [])
    return {
        "plan_id": _combined_plan_id(items, source_id),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source_id,
        "path_mappings": dict(path_mappings or {}),
        "summary": _combined_plan_summary(items, failed_items),
        "failed_items": failed_items,
        "items": items,
    }


def execute_combined_rename_plan(
    plan: dict[str, Any],
    repo,
    *,
    manifest_dir: Path,
    file_rename_fn: Callable[[str, str], None] = _rename_file,
    folder_rename_fn: Callable[[str, str], None] = _rename_directory,
    folder_create_fn: Callable[[str], None] = _create_directory,
    file_move_fn: Callable[[str, str], None] = _move_file,
    folder_delete_fn: Callable[[str], None] = _delete_directory,
    nfo_rewrite_fn: Callable[..., bytes] = _rewrite_nfo_titles,
    nfo_create_fn: Callable[..., bytes] = _create_nfo_titles,
    nfo_delete_fn: Callable[[str], None] = delete_file,
) -> dict[str, Any]:
    """Apply a combined file/folder plan and roll everything back on failure."""
    if plan.get("summary", {}).get("conflicts", 0):
        raise ValueError("plan_has_conflicts")

    items = [item for item in plan.get("items", []) if item["status"] == "ready"]
    path_mappings = dict(plan.get("path_mappings") or {})
    manifest = _write_manifest(manifest_dir, {
        **plan,
        "rename_kind": "combined",
        "execution_status": "started",
    })
    completed_files: list[tuple[str, str]] = []
    completed_moves: list[tuple[str, str]] = []
    completed_creates: list[str] = []
    completed_folders: list[tuple[str, str]] = []
    completed_db: list[tuple[str, str]] = []
    completed_covers: list[tuple[str, str, str]] = []
    completed_samples: list[tuple[str, list[str], list[str]]] = []
    completed_titles: list[tuple[str, str, str, float, str]] = []
    completed_nfo: list[tuple[str, bytes]] = []
    created_nfo: list[str] = []
    db_updates: list[dict[str, Any]] = []

    try:
        for item in items:
            for video in item["videos"]:
                for operation in video["operations"]:
                    try:
                        file_rename_fn(
                            operation["old_path"],
                            operation["new_path"],
                        )
                    except Exception as exc:
                        raise RuntimeError(
                            f"{operation['old_name']} -> {operation['new_name']}: {exc}"
                        ) from exc
                    completed_files.append(
                        (operation["old_path"], operation["new_path"])
                    )
            folder_action = item.get("folder_action", "none")
            if folder_action == "create":
                try:
                    folder_create_fn(item["new_folder_path"])
                except Exception as exc:
                    raise RuntimeError(
                        f"create {item['new_name']}: {exc}"
                    ) from exc
                completed_creates.append(item["new_folder_path"])
                for move in item.get("move_files", []):
                    try:
                        file_move_fn(
                            move["after_rename_path"],
                            move["new_path"],
                        )
                    except Exception as exc:
                        raise RuntimeError(
                            f"{Path(move['after_rename_path']).name} -> "
                            f"{Path(move['new_path']).name}: {exc}"
                        ) from exc
                    completed_moves.append(
                        (move["after_rename_path"], move["new_path"])
                    )
            elif folder_action == "rename":
                try:
                    folder_rename_fn(
                        item["old_folder_path"],
                        item["new_folder_path"],
                    )
                except Exception as exc:
                    raise RuntimeError(
                        f"{item['old_name']} -> {item['new_name']}: {exc}"
                    ) from exc
                completed_folders.append(
                    (
                        item["old_folder_path"],
                        str(
                            _resolve_actual_folder_path(
                                item["new_folder_path"],
                                str(item.get("number") or ""),
                            )
                            or item["new_folder_path"]
                        ),
                    )
                )

            for video in item["videos"]:
                update = {
                    "db_old_uri": video["db_old_uri"],
                    "db_new_uri": video["db_new_uri"],
                    "cover_path_old": video["cover_path_old"],
                    "cover_path_new": video["cover_path_new"],
                    "sample_images_old": video["sample_images_old"],
                    "sample_images_new": video["sample_images_new"],
                    "title_old": video.get("title_old", ""),
                    "title_new": video.get("title_new", ""),
                    "original_title_old": video.get(
                        "original_title_old", ""
                    ),
                    "original_title_new": video.get(
                        "original_title_new", ""
                    ),
                    "title_update": bool(video.get("title_update")),
                    "number": video.get("number"),
                    "new_video_path": video.get("new_video_path", ""),
                    "nfo_path_old": video.get("nfo_path_old", ""),
                    "nfo_path_new": video.get("nfo_path_new", ""),
                    "nfo_create": bool(video.get("nfo_create")),
                    "nfo_title_format": video.get(
                        "nfo_title_format",
                        "[{num}]{title}",
                    ),
                    "actresses": list(video.get("actresses") or []),
                    "maker": video.get("maker", ""),
                    "release_date": video.get("release_date", ""),
                    "nfo_mtime_old": float(
                        video.get("nfo_mtime_old") or 0
                    ),
                    "expected_size": int(video.get("expected_size") or 0),
                }
                _reconcile_video_update(update, path_mappings)
                db_updates.append(update)

        for update in db_updates:
            if not update.get("title_update"):
                continue
            new_video_path = str(update.get("new_video_path") or "")
            if not new_video_path:
                continue
            path = _resolve_title_nfo_path(update)
            nfo_path = str(path)
            update["nfo_path_new"] = nfo_path
            nfo_kwargs = {
                "number": str(update.get("number") or ""),
                "title_body": update.get("title_new", ""),
                "original_title": update.get("original_title_new", ""),
                "actors": update.get("actresses") or [],
                "maker": update.get("maker", ""),
                "date": update.get("release_date", ""),
                "nfo_title_format": update.get(
                    "nfo_title_format",
                    "[{num}]{title}",
                ),
            }
            if path.is_file():
                # A plan can predate a folder-rename-sidecar discovery. Rewrite
                # the real file and preserve its metadata instead of failing.
                update["nfo_create"] = False
                original_bytes = path.read_bytes()
                completed_nfo.append((nfo_path, original_bytes))
                try:
                    nfo_rewrite_fn(nfo_path, **nfo_kwargs)
                except Exception as exc:
                    raise RuntimeError(
                        f"nfo_title_write_failed:{nfo_path}:{exc}"
                    ) from exc
            else:
                # Missing sidecars are repaired instead of aborting the whole
                # rename. Track before writing so partial output is rolled back.
                update["nfo_create"] = True
                created_nfo.append(nfo_path)
                try:
                    nfo_create_fn(nfo_path, **nfo_kwargs)
                except Exception as exc:
                    raise RuntimeError(
                        f"nfo_title_create_failed:{nfo_path}:{exc}"
                    ) from exc
            try:
                update["nfo_mtime_new"] = float(path.stat().st_mtime)
            except OSError:
                resolved = _find_nfo_for_video(
                    new_video_path,
                    str(update.get("number") or ""),
                )
                if resolved is not None:
                    path = resolved
                    nfo_path = str(path)
                    update["nfo_path_new"] = nfo_path
                    update["nfo_mtime_new"] = float(path.stat().st_mtime)
                else:
                    update["nfo_mtime_new"] = float(
                        update.get("nfo_mtime_old") or 0
                    )
            update["nfo_mtime_update"] = True

        _apply_rename_updates(
            repo,
            db_updates,
            completed_db,
            completed_covers,
            completed_samples,
            completed_titles,
        )
    except Exception as exc:
        rollback_errors: list[str] = []
        restored_nfo_mtimes: dict[str, float] = {}
        for nfo_path in reversed(created_nfo):
            try:
                nfo_delete_fn(nfo_path)
            except Exception as rollback_exc:
                rollback_errors.append(
                    f"nfo_create:{nfo_path}:{rollback_exc}"
                )
        for nfo_path, original_bytes in reversed(completed_nfo):
            try:
                with atomic_write(
                    nfo_path,
                    mode="wb",
                    suffix=".nfo.rollback.tmp",
                    mobile_fallback=True,
                ) as handle:
                    handle.write(original_bytes)
                restored_nfo_mtimes[nfo_path] = float(
                    Path(nfo_path).stat().st_mtime
                )
            except Exception as rollback_exc:
                rollback_errors.append(
                    f"nfo:{nfo_path}:{rollback_exc}"
                )
        for (
            db_path,
            old_title,
            old_original_title,
            old_nfo_mtime,
            nfo_path,
        ) in reversed(completed_titles):
            try:
                if not repo.update_titles(
                    db_path,
                    old_title,
                    old_original_title,
                    restored_nfo_mtimes.get(nfo_path, old_nfo_mtime),
                ):
                    rollback_errors.append(f"title:{db_path}")
            except Exception as rollback_exc:
                rollback_errors.append(
                    f"title:{db_path}:{rollback_exc}"
                )
        for db_path, old_samples, new_samples in reversed(completed_samples):
            try:
                if not repo.update_sample_images(db_path, old_samples):
                    rollback_errors.append(f"samples:{db_path}")
            except Exception as rollback_exc:
                rollback_errors.append(f"samples:{db_path}:{rollback_exc}")
        for db_path, old_cover, new_cover in reversed(completed_covers):
            try:
                if not repo.update_cover_path_preserve_focal(
                    db_path, old_cover, new_cover
                ):
                    rollback_errors.append(f"cover:{db_path}")
            except Exception as rollback_exc:
                rollback_errors.append(f"cover:{db_path}:{rollback_exc}")
        for old_uri, new_uri in reversed(completed_db):
            try:
                if not repo.repath_path_only(new_uri, old_uri):
                    rollback_errors.append(f"db:{new_uri}")
            except Exception as rollback_exc:
                rollback_errors.append(f"db:{new_uri}:{rollback_exc}")
        for source, target in reversed(completed_moves):
            try:
                file_move_fn(target, source)
            except Exception as rollback_exc:
                rollback_errors.append(f"move:{target}:{rollback_exc}")
        for target in reversed(completed_creates):
            try:
                folder_delete_fn(target)
            except Exception as rollback_exc:
                rollback_errors.append(f"folder_create:{target}:{rollback_exc}")
        for source, target in reversed(completed_folders):
            try:
                folder_rename_fn(target, source)
            except Exception as rollback_exc:
                rollback_errors.append(f"folder:{target}:{rollback_exc}")
        for source, target in reversed(completed_files):
            try:
                file_rename_fn(target, source)
            except Exception as rollback_exc:
                rollback_errors.append(f"file:{target}:{rollback_exc}")
        manifest.write_text(
            json.dumps({
                **plan,
                "rename_kind": "combined",
                "execution_status": "rolled_back",
                "error": str(exc),
                "rollback_errors": rollback_errors,
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {
            "success": False,
            "error": str(exc),
            "rollback_ok": not rollback_errors,
            "rollback_errors": rollback_errors,
            "manifest_path": str(manifest),
        }

    manifest.write_text(
        json.dumps({
            **plan,
            "rename_kind": "combined",
            "execution_status": "completed",
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "success": True,
        "renamed_files": len(completed_files),
        "renamed_folders": len(completed_folders) + len(completed_creates),
        "created_folders": len(completed_creates),
        "moved_files": len(completed_moves),
        # These values feed user-visible completion summaries. A complete
        # multipart release is one video even when several rows were written.
        "updated_videos": plan["summary"].get("logical_videos", 0),
        "updated_titles": plan["summary"].get("updated_titles", 0),
        "physical_updated_videos": sum(
            1
            for update in db_updates
            if (
                update["db_old_uri"] != update["db_new_uri"]
                or update.get("title_update")
                or update.get(
                    "cover_update",
                    update["cover_path_old"] != update["cover_path_new"],
                )
                or update.get(
                    "samples_update",
                    update["sample_images_old"]
                    != update["sample_images_new"],
                )
            )
        ),
        "physical_updated_titles": len(completed_titles),
        "rewritten_nfos": len(completed_nfo),
        "created_nfos": len(created_nfo),
        "manifest_path": str(manifest),
    }


def validate_combined_rename_plan(plan: dict[str, Any]) -> bool:
    """Recheck cached source-plan file state immediately before execution."""
    if plan.get("summary", {}).get("conflicts", 0):
        return False
    items = [
        item for item in plan.get("items", [])
        if item.get("status") == "ready"
    ]
    file_sources = {
        _path_key(operation["old_path"])
        for item in items
        for video in item.get("videos", [])
        for operation in video.get("operations", [])
    }
    folder_sources = {
        _path_key(item["old_folder_path"])
        for item in items
        if item.get("folder_action") == "rename"
    }
    try:
        for item in items:
            for video in item.get("videos", []):
                if not Path(video["old_video_path"]).is_file():
                    return False
                if (
                    video.get("title_update")
                    and video.get("nfo_path_old")
                    and not Path(video["nfo_path_old"]).is_file()
                ):
                    return False
                if (
                    video.get("nfo_create")
                    and video.get("nfo_path_new")
                    and Path(video["nfo_path_new"]).exists()
                ):
                    return False
                for operation in video.get("operations", []):
                    source = Path(operation["old_path"])
                    target = Path(operation["new_path"])
                    if not source.is_file():
                        return False
                    expected_size = operation.get("signature", {}).get("size")
                    if expected_size is not None and source.stat().st_size != expected_size:
                        return False
                    if (
                        target.exists()
                        and _path_key(str(target)) not in file_sources
                    ):
                        return False
            folder_action = item.get("folder_action", "none")
            if folder_action in {"create", "rename"}:
                source = Path(item["old_folder_path"])
                target = Path(item["new_folder_path"])
                if not source.is_dir():
                    return False
                if folder_action == "rename" and (
                    target.exists()
                    and _path_key(str(target)) not in folder_sources
                ):
                    return False
                if folder_action == "create" and target.exists():
                    return False
            for move in item.get("move_files", []):
                if not Path(move["old_path"]).is_file():
                    return False
                if Path(move["new_path"]).exists():
                    return False
    except OSError:
        return False
    return True
