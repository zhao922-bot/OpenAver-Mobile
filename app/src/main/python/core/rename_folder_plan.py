"""Folder rename planning and execution."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.path_utils import to_file_uri, uri_to_fs_path
from core.rename_names import (
    _fit_filename_stem,
    _path_key,
    canonicalize_stem,
)
from core.rename_shared import (
    _is_direct_child,
    _rebase_path,
    _rebase_path_list,
    _relative_path_under,
    _rename_directory,
    _write_manifest,
)


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
