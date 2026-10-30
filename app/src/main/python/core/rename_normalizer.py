"""Safe, preview-first normalization of video filenames and local sidecars."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core import android_storage
from core.path_utils import to_file_uri, uri_to_fs_path
from core.scrapers.utils import extract_number, normalize_number_impl
from core.video_extensions import get_video_extensions


SIDECAR_EXTENSIONS = frozenset({
    ".nfo", ".jpg", ".jpeg", ".png", ".webp",
    ".srt", ".ass", ".ssa", ".vtt", ".strm",
})
SIDECAR_SEPARATORS = frozenset(" .-_[(【")
LEADING_SEPARATORS = " \t\u3000-_＿－"
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
MAX_COMPONENT_BYTES = 255
TRUNCATION_MARKER = "..."


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path)).casefold()


def _number_pattern(number: str) -> re.Pattern[str]:
    escaped = re.escape(number)
    flexible = escaped.replace(r"\-", r"[\s_-]*")
    return re.compile(
        rf"(?<![A-Za-z0-9]){flexible}(?![0-9])",
        re.IGNORECASE,
    )


def canonicalize_stem(stem: str, number_hint: str | None = None) -> tuple[str, str | None, str]:
    """Return (new_stem, number, reason). The original title body is preserved."""
    number = extract_number(stem) or number_hint
    if number:
        number = normalize_number_impl(str(number))
    if not number:
        return stem, None, "no_number"

    match = _number_pattern(number).search(stem)
    if match is None:
        return stem, number, "number_not_located"

    title = stem[match.end():].lstrip(LEADING_SEPARATORS)
    canonical = number if not title else f"{number} {title}"
    if canonical.endswith(TRUNCATION_MARKER):
        # Preserve the safety marker so a preview that truncated a name is
        # stable when the user opens it again.
        canonical = (
            canonical[:-len(TRUNCATION_MARKER)].rstrip(" .")
            + TRUNCATION_MARKER
        )
    else:
        canonical = canonical.rstrip(" .")
    if not canonical:
        return stem, number, "empty_name"
    if canonical == stem:
        return stem, number, "unchanged"
    return canonical, number, "rename"


def _sidecar_matches(old_stem: str, name: str) -> bool:
    if not name.startswith(old_stem):
        return False
    if name == old_stem:
        return False
    return name[len(old_stem)] in SIDECAR_SEPARATORS


def _operation_kind(name: str, video_extensions: set[str]) -> str:
    suffix = Path(name).suffix.lower()
    if suffix == ".nfo":
        return "nfo"
    if suffix == ".srt" or suffix == ".ass" or suffix == ".ssa" or suffix == ".vtt":
        return "subtitle"
    if suffix in IMAGE_EXTENSIONS:
        lower = name.lower()
        if "-poster." in lower:
            return "poster"
        if "-fanart." in lower:
            return "fanart"
        return "cover"
    if suffix == ".strm":
        return "strm"
    if suffix in video_extensions:
        return "video"
    return "sidecar"


def _stat_signature(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _utf8_len(value: str) -> int:
    return len(value.encode("utf-8"))


def _truncate_utf8(value: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    used = 0
    output = []
    for character in value:
        size = len(character.encode("utf-8"))
        if used + size > max_bytes:
            break
        output.append(character)
        used += size
    return "".join(output)


def _fit_filename_stem(
    stem: str,
    suffix_bytes: int,
    *,
    max_name_bytes: int = MAX_COMPONENT_BYTES,
) -> str | None:
    """Fit a shared stem while keeping the number and a visible ellipsis."""
    budget = max_name_bytes - suffix_bytes
    if _utf8_len(stem) <= budget:
        return stem
    prefix_match = re.match(r"^([A-Z0-9]+(?:-[A-Z0-9]+)* )", stem, re.IGNORECASE)
    prefix = prefix_match.group(1) if prefix_match else ""
    body = stem[len(prefix):]
    marker_bytes = len(TRUNCATION_MARKER.encode("ascii"))
    body_budget = budget - _utf8_len(prefix) - marker_bytes
    if body_budget < 0:
        return None
    body = _truncate_utf8(body, body_budget).rstrip(" .-_")
    return f"{prefix}{body}{TRUNCATION_MARKER}"


def _sidecar_suffix(name: str, stems: list[str]) -> str | None:
    for stem in sorted(set(stems), key=_utf8_len, reverse=True):
        if _sidecar_matches(stem, name):
            return name[len(stem):]
    lower = name.lower()
    for marker in ("-poster.", "-fanart."):
        position = lower.rfind(marker)
        if position >= 0:
            return name[position:]
    suffix = Path(name).suffix
    if suffix.lower() in IMAGE_EXTENSIONS | {".nfo", ".strm"}:
        return suffix
    subtitle = re.search(
        r"(?:\.[A-Za-z0-9_-]{2,10})*\.(?:srt|ass|ssa|vtt)$",
        name,
        re.IGNORECASE,
    )
    return subtitle.group(0) if subtitle else None


def _find_repair_video(
    expected_path: Path,
    number: str | None,
    video_extensions: set[str],
) -> Path | None:
    """Find a unique same-number video when MTP/FUSE truncated its filename."""
    if not number:
        return None
    try:
        if not expected_path.parent.is_dir():
            return None
    except OSError:
        return None
    normalized = normalize_number_impl(str(number))
    matches = []
    try:
        children = expected_path.parent.iterdir()
        for child in children:
            if not child.is_file() or child.suffix.lower() not in video_extensions:
                continue
            candidate_number = extract_number(child.name)
            if candidate_number and normalize_number_impl(candidate_number) == normalized:
                matches.append(child)
    except OSError:
        return None
    return matches[0] if len(matches) == 1 else None


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


def build_rename_plan(
    videos: list[Any],
    *,
    path_mappings: dict | None = None,
    config: dict | None = None,
) -> dict[str, Any]:
    """Build a deterministic preview without modifying files or the database."""
    video_extensions = get_video_extensions(config or {})
    items: list[dict[str, Any]] = []

    for video in videos:
        old_uri = str(getattr(video, "path", "") or "")
        if not old_uri:
            continue
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
                items.append(item)
                continue
            source_path = recovered
            repaired_source = True
            item["old_video_path"] = str(source_path)
            item["new_video_path"] = str(source_path)
            item["old_name"] = source_path.name
            item["new_name"] = source_path.name
            item["recovered_missing_source"] = True

        new_stem, number, reason = canonicalize_stem(
            expected_path.stem if repaired_source else source_path.stem,
            number_hint,
        )
        item["number"] = number
        if reason == "no_number":
            item["status"] = "skipped"
            item["reason"] = reason
            items.append(item)
            continue
        if reason == "number_not_located":
            item["status"] = "conflict"
            item["reason"] = reason
            item["conflicts"].append(reason)
            items.append(item)
            continue
        if reason == "empty_name":
            item["status"] = "conflict"
            item["reason"] = reason
            item["conflicts"].append(reason)
            items.append(item)
            continue
        try:
            children = sorted(
                source_path.parent.iterdir(),
                key=lambda path: path.name.casefold(),
            )
        except OSError as exc:
            item["status"] = "conflict"
            item["reason"] = "list_directory_failed"
            item["conflicts"].append(str(exc))
            items.append(item)
            continue

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
            items.append(item)
            continue

        max_suffix_bytes = max(_utf8_len(suffix) for _, suffix in selected)
        fitted_stem = _fit_filename_stem(new_stem, max_suffix_bytes)
        if fitted_stem is None:
            item["status"] = "conflict"
            item["reason"] = "target_name_too_long"
            item["conflicts"].append("target_name_too_long")
            items.append(item)
            continue

        new_path = source_path.with_name(fitted_stem + source_path.suffix)
        item["new_video_path"] = str(new_path)
        item["new_name"] = new_path.name
        item["db_new_uri"] = to_file_uri(str(new_path), path_mappings)

        operations: list[dict[str, Any]] = []
        for child, suffix in selected:
            target_name = fitted_stem + suffix
            kind = _operation_kind(child.name, video_extensions)
            if repaired_source and kind == "cover":
                # MTP/FUSE may have truncated both the video and its primary
                # cover, while the database still contains the original full
                # name. Point it at the repaired on-device cover even though
                # the stored path never matched the truncated source.
                item["cover_path_new"] = to_file_uri(
                    str(child.with_name(target_name)), path_mappings
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
                        operation["new_path"], path_mappings
                    )

        operations.sort(key=lambda op: (op["kind"] != "video", op["old_name"].casefold()))
        item["operations"] = operations
        if not operations and not repaired_source:
            if reason == "unchanged" and fitted_stem == source_path.stem:
                item["status"] = "unchanged"
                item["reason"] = "unchanged"
            else:
                item["status"] = "conflict"
                item["reason"] = "no_operations"
                item["conflicts"].append("no_operations")
        else:
            item["status"] = "ready"
            item["reason"] = "repair_and_rename" if repaired_source else "rename"
        items.append(item)

    source_keys = {
        _path_key(op["old_path"])
        for item in items
        for op in item["operations"]
    }
    target_to_items: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        for op in item["operations"]:
            target_to_items.setdefault(_path_key(op["new_path"]), []).append(item)

    for item in items:
        for op in item["operations"]:
            old_key = _path_key(op["old_path"])
            new_key = _path_key(op["new_path"])
            target = Path(op["new_path"])
            if old_key == new_key and op["old_path"] != op["new_path"]:
                item["conflicts"].append("case_only_rename")
            if target.exists() and new_key not in source_keys:
                item["conflicts"].append(f"target_exists:{op['new_name']}")
            if new_key in source_keys and new_key != old_key:
                item["conflicts"].append(f"target_is_another_source:{op['new_name']}")
            if len(target_to_items[new_key]) > 1:
                item["conflicts"].append(f"duplicate_target:{op['new_name']}")
        if item["conflicts"]:
            item["status"] = "conflict"
            item["reason"] = item["conflicts"][0]
        item["conflicts"] = sorted(set(item["conflicts"]))

    ready = [item for item in items if item["status"] == "ready"]
    conflicts = [item for item in items if item["status"] == "conflict"]
    unchanged = [item for item in items if item["status"] == "unchanged"]
    skipped = [item for item in items if item["status"] == "skipped"]
    missing = [item for item in items if item["status"] == "missing"]
    return {
        "plan_id": _plan_id(items),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(items),
            "rename_videos": len(ready),
            "rename_files": sum(len(item["operations"]) for item in ready),
            "conflicts": len(conflicts),
            "unchanged": len(unchanged),
            "skipped": len(skipped),
            "missing": len(missing),
        },
        "items": items,
    }


def _rename_file(source: str, target: str) -> None:
    if source == target:
        return
    source_path = Path(source)
    target_path = Path(target)
    if not source_path.is_file():
        raise FileNotFoundError(source)
    if target_path.exists():
        raise FileExistsError(target)
    android_storage.rename(source, target)


def _write_manifest(manifest_dir: Path, plan: dict[str, Any]) -> Path:
    manifest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = manifest_dir / f"rename-{stamp}-{plan['plan_id'][:12]}.json"
    path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def execute_rename_plan(
    plan: dict[str, Any],
    repo,
    *,
    manifest_dir: Path,
    rename_fn: Callable[[str, str], None] = _rename_file,
) -> dict[str, Any]:
    """Apply a ready plan and roll files/database paths back on failure."""
    if plan.get("summary", {}).get("conflicts", 0):
        raise ValueError("plan_has_conflicts")

    items = [item for item in plan.get("items", []) if item["status"] == "ready"]
    manifest = _write_manifest(manifest_dir, {
        **plan,
        "execution_status": "started",
    })
    completed_files: list[tuple[str, str]] = []
    completed_db: list[tuple[str, str]] = []
    completed_covers: list[tuple[str, str, str]] = []

    try:
        for item in items:
            for operation in item["operations"]:
                try:
                    rename_fn(operation["old_path"], operation["new_path"])
                except Exception as exc:
                    raise RuntimeError(
                        f"{operation['old_name']} -> {operation['new_name']}: {exc}"
                    ) from exc
                completed_files.append((operation["old_path"], operation["new_path"]))

            if item["db_old_uri"] != item["db_new_uri"]:
                if not repo.repath_path_only(item["db_old_uri"], item["db_new_uri"]):
                    raise RuntimeError("database_path_update_failed")
                completed_db.append((item["db_old_uri"], item["db_new_uri"]))

            old_cover = item.get("cover_path_old") or ""
            new_cover = item.get("cover_path_new") or ""
            if old_cover and old_cover != new_cover:
                if not repo.update_cover_path_preserve_focal(
                    item["db_new_uri"], new_cover, old_cover
                ):
                    raise RuntimeError("database_cover_update_failed")
                completed_covers.append((item["db_new_uri"], old_cover, new_cover))
    except Exception as exc:
        rollback_errors: list[str] = []
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
        for source, target in reversed(completed_files):
            try:
                rename_fn(target, source)
            except Exception as rollback_exc:
                rollback_errors.append(f"file:{target}:{rollback_exc}")
        manifest.write_text(
            json.dumps({
                **plan,
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
            "execution_status": "completed",
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "success": True,
        "renamed_videos": len(items),
        "renamed_files": len(completed_files),
        "manifest_path": str(manifest),
    }


def _relative_path_under(path: str, directory: str) -> Path | None:
    """Return a relative path when *path* is inside *directory*."""
    path_abs = os.path.abspath(path)
    directory_abs = os.path.abspath(directory)
    key = os.path.normcase(path_abs).casefold()
    directory_key = os.path.normcase(directory_abs).casefold().rstrip(os.sep)
    if key == directory_key:
        return Path(".")
    if not key.startswith(directory_key + os.sep):
        return None
    return Path(os.path.relpath(path_abs, directory_abs))


def _rebase_path(value: str, old_dir: Path, new_dir: Path, mappings: dict | None) -> str:
    if not value:
        return value
    fs_path = uri_to_fs_path(value)
    relative = _relative_path_under(fs_path, str(old_dir))
    if relative is None:
        return value
    return to_file_uri(str(new_dir / relative), mappings)


def _rebase_path_list(
    values: list[str],
    old_dir: Path,
    new_dir: Path,
    mappings: dict | None,
) -> list[str]:
    return [_rebase_path(value, old_dir, new_dir, mappings) for value in values]


def _is_direct_child(path: Path, roots: list[Path]) -> bool:
    return any(_path_key(str(path.parent)) == _path_key(str(root)) for root in roots)


def _folder_plan_id(items: list[dict[str, Any]]) -> str:
    payload = []
    for item in sorted(items, key=lambda value: value["old_folder_path"].casefold()):
        if item["status"] != "ready":
            continue
        payload.append({
            "old": item["old_folder_path"],
            "new": item["new_folder_path"],
            "videos": [
                {
                    "old": video["db_old_uri"],
                    "new": video["db_new_uri"],
                    "cover_old": video["cover_path_old"],
                    "cover_new": video["cover_path_new"],
                    "samples_old": video["sample_images_old"],
                    "samples_new": video["sample_images_new"],
                }
                for video in item["videos"]
            ],
        })
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_folder_rename_plan(
    videos: list[Any],
    *,
    source_roots: list[str],
    path_mappings: dict | None = None,
) -> dict[str, Any]:
    """Build a preview for direct child folders under configured source roots."""
    roots = [Path(uri_to_fs_path(str(root))) for root in source_roots if root]
    grouped: dict[str, dict[str, Any]] = {}
    for video in videos:
        old_uri = str(getattr(video, "path", "") or "")
        if not old_uri:
            continue
        old_path = Path(uri_to_fs_path(old_uri))
        folder = old_path.parent
        if not _is_direct_child(folder, roots):
            continue
        entry = grouped.setdefault(
            _path_key(str(folder)),
            {"folder": folder, "videos": []},
        )
        entry["videos"].append(video)

    items: list[dict[str, Any]] = []
    for entry in sorted(
        grouped.values(),
        key=lambda value: value["folder"].name.casefold(),
    ):
        folder = entry["folder"]
        rows = entry["videos"]
        item: dict[str, Any] = {
            "old_folder_path": str(folder),
            "new_folder_path": str(folder),
            "old_name": folder.name,
            "new_name": folder.name,
            "number": None,
            "videos": [],
            "conflicts": [],
            "status": "unchanged",
            "reason": "unchanged",
        }
        if not folder.is_dir():
            item["status"] = "missing"
            item["reason"] = "source_not_found"
            items.append(item)
            continue

        hint = next(
            (
                str(getattr(row, "number", "") or "")
                for row in rows
                if getattr(row, "number", None)
            ),
            None,
        )
        new_stem, number, reason = canonicalize_stem(folder.name, hint)
        item["number"] = number
        if reason == "no_number":
            item["status"] = "skipped"
            item["reason"] = reason
            items.append(item)
            continue
        if reason in {"number_not_located", "empty_name"}:
            item["status"] = "conflict"
            item["reason"] = reason
            item["conflicts"].append(reason)
            items.append(item)
            continue
        if reason == "unchanged":
            items.append(item)
            continue

        fitted_stem = _fit_filename_stem(new_stem, 0)
        if fitted_stem is None:
            item["status"] = "conflict"
            item["reason"] = "target_name_too_long"
            item["conflicts"].append("target_name_too_long")
            items.append(item)
            continue
        new_folder = folder.with_name(fitted_stem)
        item["new_folder_path"] = str(new_folder)
        item["new_name"] = new_folder.name
        for row in rows:
            old_uri = str(getattr(row, "path", "") or "")
            old_video = Path(uri_to_fs_path(old_uri))
            relative = _relative_path_under(str(old_video), str(folder))
            if relative is None:
                item["conflicts"].append("video_outside_folder")
                continue
            new_video = new_folder / relative
            cover_old = str(getattr(row, "cover_path", "") or "")
            samples_old = [
                str(value) for value in (getattr(row, "sample_images", None) or [])
            ]
            item["videos"].append({
                "db_old_uri": old_uri,
                "db_new_uri": to_file_uri(str(new_video), path_mappings),
                "cover_path_old": cover_old,
                "cover_path_new": _rebase_path(
                    cover_old, folder, new_folder, path_mappings
                ),
                "sample_images_old": samples_old,
                "sample_images_new": _rebase_path_list(
                    samples_old, folder, new_folder, path_mappings
                ),
            })
        if not item["videos"]:
            item["status"] = "conflict"
            item["reason"] = item["conflicts"][0] if item["conflicts"] else "no_videos"
            item["conflicts"].append(item["reason"])
        else:
            item["status"] = "ready"
            item["reason"] = "rename"
        items.append(item)

    source_keys = {
        _path_key(item["old_folder_path"])
        for item in items
        if item["status"] == "ready"
    }
    target_to_items: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        if item["status"] != "ready":
            continue
        target_key = _path_key(item["new_folder_path"])
        target_to_items.setdefault(target_key, []).append(item)

    for item in items:
        if item["status"] != "ready":
            continue
        old_key = _path_key(item["old_folder_path"])
        new_key = _path_key(item["new_folder_path"])
        target = Path(item["new_folder_path"])
        if old_key == new_key and item["old_folder_path"] != item["new_folder_path"]:
            item["conflicts"].append("case_only_rename")
        if target.exists() and new_key not in source_keys:
            item["conflicts"].append(f"target_exists:{item['new_name']}")
        if new_key in source_keys and new_key != old_key:
            item["conflicts"].append(f"target_is_another_source:{item['new_name']}")
        if len(target_to_items.get(new_key, [])) > 1:
            item["conflicts"].append(f"duplicate_target:{item['new_name']}")
        if item["conflicts"]:
            item["status"] = "conflict"
            item["reason"] = item["conflicts"][0]
        item["conflicts"] = sorted(set(item["conflicts"]))

    ready = [item for item in items if item["status"] == "ready"]
    conflicts = [item for item in items if item["status"] == "conflict"]
    unchanged = [item for item in items if item["status"] == "unchanged"]
    skipped = [item for item in items if item["status"] == "skipped"]
    missing = [item for item in items if item["status"] == "missing"]
    return {
        "plan_id": _folder_plan_id(items),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(items),
            "rename_folders": len(ready),
            "rename_videos": sum(len(item["videos"]) for item in ready),
            "rename_files": len(ready),
            "conflicts": len(conflicts),
            "unchanged": len(unchanged),
            "skipped": len(skipped),
            "missing": len(missing),
        },
        "items": items,
    }


def _rename_directory(source: str, target: str) -> None:
    if source == target:
        return
    source_path = Path(source)
    target_path = Path(target)
    if not source_path.is_dir():
        raise FileNotFoundError(source)
    if target_path.exists():
        raise FileExistsError(target)
    android_storage.rename(source, target)


def execute_folder_rename_plan(
    plan: dict[str, Any],
    repo,
    *,
    manifest_dir: Path,
    rename_fn: Callable[[str, str], None] = _rename_directory,
) -> dict[str, Any]:
    """Apply a ready folder plan and roll back files and database paths."""
    if plan.get("summary", {}).get("conflicts", 0):
        raise ValueError("plan_has_conflicts")

    items = [item for item in plan.get("items", []) if item["status"] == "ready"]
    manifest = _write_manifest(manifest_dir, {
        **plan,
        "rename_kind": "folders",
        "execution_status": "started",
    })
    completed_folders: list[tuple[str, str]] = []
    completed_db: list[tuple[str, str]] = []
    completed_covers: list[tuple[str, str, str]] = []
    completed_samples: list[tuple[str, list[str], list[str]]] = []

    try:
        for item in items:
            try:
                rename_fn(item["old_folder_path"], item["new_folder_path"])
            except Exception as exc:
                raise RuntimeError(
                    f"{item['old_name']} -> {item['new_name']}: {exc}"
                ) from exc
            completed_folders.append(
                (item["old_folder_path"], item["new_folder_path"])
            )
            for video in item["videos"]:
                if not repo.repath_path_only(
                    video["db_old_uri"], video["db_new_uri"]
                ):
                    raise RuntimeError("database_path_update_failed")
                completed_db.append((video["db_old_uri"], video["db_new_uri"]))

                old_cover = video["cover_path_old"]
                new_cover = video["cover_path_new"]
                if old_cover != new_cover:
                    if not repo.update_cover_path_preserve_focal(
                        video["db_new_uri"], new_cover, old_cover
                    ):
                        raise RuntimeError("database_cover_update_failed")
                    completed_covers.append(
                        (video["db_new_uri"], old_cover, new_cover)
                    )

                old_samples = video["sample_images_old"]
                new_samples = video["sample_images_new"]
                if old_samples != new_samples:
                    if not repo.update_sample_images(
                        video["db_new_uri"], new_samples
                    ):
                        raise RuntimeError("database_samples_update_failed")
                    completed_samples.append(
                        (video["db_new_uri"], old_samples, new_samples)
                    )
    except Exception as exc:
        rollback_errors: list[str] = []
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
        for source, target in reversed(completed_folders):
            try:
                rename_fn(target, source)
            except Exception as rollback_exc:
                rollback_errors.append(f"folder:{target}:{rollback_exc}")
        manifest.write_text(
            json.dumps({
                **plan,
                "rename_kind": "folders",
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
            "rename_kind": "folders",
            "execution_status": "completed",
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "success": True,
        "renamed_folders": len(completed_folders),
        "updated_videos": len(completed_db),
        "manifest_path": str(manifest),
    }
