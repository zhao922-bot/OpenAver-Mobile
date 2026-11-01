"""Execution and rollback for single-video rename plans."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from core.rename_shared import _rename_file, _write_manifest


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
