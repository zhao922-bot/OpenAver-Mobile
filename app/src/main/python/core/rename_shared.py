"""Shared filesystem helpers for rename plan execution."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core import android_storage
from core.path_utils import to_file_uri, uri_to_fs_path
from core.rename_names import _path_key


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


def _is_source_root(path: Path, roots: list[Path]) -> bool:
    return any(_path_key(str(path)) == _path_key(str(root)) for root in roots)


def _create_directory(target: str) -> None:
    target_path = Path(target)
    try:
        target_path.mkdir(parents=False, exist_ok=False)
        return
    except OSError as exc:
        if not android_storage.is_access_error(exc):
            raise
        direct_error = exc
    try:
        android_storage.mkdirs(target)
    except Exception as exc:
        raise exc from direct_error


def _move_file(source: str, target: str) -> None:
    android_storage.move(source, target)


def _delete_directory(target: str) -> None:
    target_path = Path(target)
    try:
        target_path.rmdir()
        return
    except OSError as exc:
        if not android_storage.is_access_error(exc):
            raise
        direct_error = exc
    try:
        android_storage.delete(target)
    except Exception as exc:
        raise exc from direct_error


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


def _apply_rename_updates(
    repo,
    updates: list[dict[str, Any]],
    completed_db: list[tuple[str, str]],
    completed_covers: list[tuple[str, str, str]],
    completed_samples: list[tuple[str, list[str], list[str]]],
) -> None:
    """Apply collected DB updates, preferring one repository transaction."""
    if not updates:
        return

    batch_apply = getattr(repo, "apply_rename_batch", None)
    if callable(batch_apply):
        if not batch_apply(updates):
            raise RuntimeError("database_update_failed")
        for update in updates:
            old_uri = str(update.get("db_old_uri") or "")
            new_uri = str(update.get("db_new_uri") or "")
            if old_uri != new_uri:
                completed_db.append((old_uri, new_uri))
            old_cover = str(update.get("cover_path_old") or "")
            new_cover = str(update.get("cover_path_new") or "")
            if update.get("cover_update", old_cover != new_cover):
                completed_covers.append((new_uri, old_cover, new_cover))
            old_samples = list(update.get("sample_images_old") or [])
            new_samples = list(update.get("sample_images_new") or [])
            if update.get("samples_update", old_samples != new_samples):
                completed_samples.append((new_uri, old_samples, new_samples))
        return

    for update in updates:
        old_uri = str(update.get("db_old_uri") or "")
        new_uri = str(update.get("db_new_uri") or "")
        if old_uri != new_uri:
            if not repo.repath_path_only(old_uri, new_uri):
                raise RuntimeError("database_path_update_failed")
            completed_db.append((old_uri, new_uri))

        old_cover = str(update.get("cover_path_old") or "")
        new_cover = str(update.get("cover_path_new") or "")
        if update.get("cover_update", old_cover != new_cover):
            if not repo.update_cover_path_preserve_focal(
                new_uri,
                new_cover,
                old_cover,
            ):
                raise RuntimeError("database_cover_update_failed")
            completed_covers.append((new_uri, old_cover, new_cover))

        old_samples = list(update.get("sample_images_old") or [])
        new_samples = list(update.get("sample_images_new") or [])
        if update.get("samples_update", old_samples != new_samples):
            if not repo.update_sample_images(new_uri, new_samples):
                raise RuntimeError("database_samples_update_failed")
            completed_samples.append((new_uri, old_samples, new_samples))
