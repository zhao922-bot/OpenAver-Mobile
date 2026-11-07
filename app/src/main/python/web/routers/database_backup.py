"""Consistent SQLite snapshot export for OpenAver Mobile."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from core.database import get_connection, get_db_path, init_db
from core.database.connection import _clear_db_init_cache
from core.generate_state import is_generate_in_progress
from core.i18n import get_config_locale, t as i18n_t
from core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/database", tags=["database"])

_BACKUP_FORMAT = "openaver-mobile-database-backup"
_BACKUP_FORMAT_VERSION = 1
_BACKUP_MAX_BYTES = 256 * 1024 * 1024
_MANIFEST_MAX_BYTES = 1024 * 1024
_KEEP_BACKUPS = 3
_ALLOWED_BACKUP_FILES = frozenset({"manifest.json", "openaver.db"})
_REQUIRED_TABLES = frozenset({
    "videos",
    "actresses",
    "actress_aliases",
    "tag_aliases",
    "wishlist",
    "notifications",
    "organize_failures",
    "maker_javbus_map",
    "app_meta",
})


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_unlink(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        logger.warning("database file cleanup failed: %s", path, exc_info=True)


def _import_error(status_code: int, message_key: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=i18n_t(message_key, locale=get_config_locale()),
    )


def _safe_zip_name(raw_name: str) -> str:
    normalized = raw_name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or "\x00" in normalized
        or path.is_absolute()
        or re.match(r"^[A-Za-z]:", normalized)
        or ".." in path.parts
    ):
        raise _import_error(422, "runtime.database.import_invalid_zip")
    return normalized


def _extract_backup(zip_path: Path, dest_dir: Path) -> tuple[Path, dict]:
    """Extract only the database and manifest, rejecting unsafe ZIP layouts."""
    selected: dict[str, zipfile.ZipInfo] = {}
    declared_total = 0
    try:
        with zipfile.ZipFile(zip_path) as archive:
            for info in archive.infolist():
                name = _safe_zip_name(info.filename)
                if name in selected:
                    raise _import_error(422, "runtime.database.import_invalid_zip")
                if info.is_dir() or name not in _ALLOWED_BACKUP_FILES:
                    raise _import_error(422, "runtime.database.import_invalid_zip")
                if info.flag_bits & 0x1:
                    raise _import_error(422, "runtime.database.import_invalid_zip")
                if info.file_size < 0:
                    raise _import_error(422, "runtime.database.import_invalid_zip")
                declared_total += info.file_size
                if declared_total > _BACKUP_MAX_BYTES:
                    raise _import_error(413, "runtime.database.import_too_large")
                if name == "manifest.json" and info.file_size > _MANIFEST_MAX_BYTES:
                    raise _import_error(422, "runtime.database.import_invalid_manifest")
                selected[name] = info

            if set(selected) != _ALLOWED_BACKUP_FILES:
                raise _import_error(422, "runtime.database.import_invalid_zip")

            written_total = 0
            for name in _ALLOWED_BACKUP_FILES:
                target = dest_dir / name
                with archive.open(selected[name]) as source, target.open("wb") as output:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        written_total += len(chunk)
                        if written_total > _BACKUP_MAX_BYTES:
                            raise _import_error(413, "runtime.database.import_too_large")
                        output.write(chunk)

            manifest_path = dest_dir / "manifest.json"
            if manifest_path.stat().st_size > _MANIFEST_MAX_BYTES:
                raise _import_error(422, "runtime.database.import_invalid_manifest")
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                raise _import_error(422, "runtime.database.import_invalid_manifest") from None
    except HTTPException:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile):
        raise _import_error(422, "runtime.database.import_invalid_zip") from None

    if not isinstance(manifest, dict):
        raise _import_error(422, "runtime.database.import_invalid_manifest")
    if manifest.get("format") != _BACKUP_FORMAT:
        raise _import_error(422, "runtime.database.import_invalid_manifest")
    version = manifest.get("format_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise _import_error(422, "runtime.database.import_invalid_manifest")
    if version < 1 or version > _BACKUP_FORMAT_VERSION:
        raise _import_error(422, "runtime.database.import_version_unsupported")
    if manifest.get("database_file") != "openaver.db":
        raise _import_error(422, "runtime.database.import_invalid_manifest")

    db_path = dest_dir / "openaver.db"
    expected_size = manifest.get("database_size")
    if (
        isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or expected_size != db_path.stat().st_size
    ):
        raise _import_error(422, "runtime.database.import_invalid_manifest")
    expected_hash = manifest.get("database_sha256")
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash):
        raise _import_error(422, "runtime.database.import_invalid_manifest")
    if _sha256_file(db_path) != expected_hash.lower():
        raise _import_error(422, "runtime.database.import_hash_mismatch")

    created_at = manifest.get("created_at")
    if not isinstance(created_at, str):
        manifest["created_at"] = ""
    return db_path, manifest


def _validate_snapshot(db_path: Path, manifest: dict) -> None:
    """Validate a snapshot without touching the live database."""
    expected_hash = manifest.get("database_sha256")
    if not isinstance(expected_hash, str):
        raise _import_error(422, "runtime.database.import_invalid_manifest")
    if _sha256_file(db_path) != expected_hash.lower():
        raise _import_error(422, "runtime.database.import_hash_mismatch")

    try:
        connection = sqlite3.connect(str(db_path))
        try:
            integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        finally:
            connection.close()
    except sqlite3.DatabaseError:
        raise _import_error(422, "runtime.database.import_integrity_failed") from None

    if integrity_rows != [("ok",)]:
        raise _import_error(422, "runtime.database.import_integrity_failed")
    if not _REQUIRED_TABLES.issubset(tables):
        raise _import_error(422, "runtime.database.import_missing_tables")


def _delete_sqlite_sidecars(db_path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        _safe_unlink(f"{db_path}{suffix}")


def _prune_database_backups(db_path: Path) -> None:
    backups = sorted(
        db_path.parent.glob(f"{db_path.name}.bak-*"),
        key=lambda path: path.name,
        reverse=True,
    )
    for stale in backups[_KEEP_BACKUPS:]:
        _safe_unlink(str(stale))


def _restore_snapshot(db_path: Path, new_db: Path) -> str | None:
    """Back up the live database, then atomically install the validated snapshot."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path: Path | None = None
    replacement_started = False

    try:
        if db_path.exists():
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
            backup_path = db_path.with_name(f"{db_path.name}.bak-{stamp}-{time.time_ns()}")
            create_database_snapshot(db_path, backup_path)

        _clear_db_init_cache()
        _delete_sqlite_sidecars(db_path)
        replacement_started = True
        os.replace(new_db, db_path)
        init_db(force=True)
    except Exception:
        logger.exception("database restore failed")
        if replacement_started:
            _clear_db_init_cache()
            _delete_sqlite_sidecars(db_path)
            if backup_path is not None and backup_path.exists():
                try:
                    os.replace(backup_path, db_path)
                    init_db(force=True)
                except Exception:
                    logger.exception("database rollback failed")
        raise

    _prune_database_backups(db_path)
    return backup_path.name if backup_path is not None else None


def create_database_snapshot(db_path: Path, snapshot_path: Path) -> None:
    """Create a transactionally consistent snapshot, including WAL contents."""
    source = get_connection(db_path)
    try:
        source.execute("VACUUM INTO ?", (str(snapshot_path),))
    finally:
        source.close()

    snapshot = sqlite3.connect(str(snapshot_path))
    try:
        integrity = snapshot.execute("PRAGMA integrity_check").fetchone()
    finally:
        snapshot.close()
    if not integrity or integrity[0] != "ok":
        raise RuntimeError(f"database snapshot integrity check failed: {integrity!r}")


def write_database_backup_zip(db_path: Path, zip_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="openaver-db-export-") as temp_dir:
        snapshot_path = Path(temp_dir) / "openaver.db"
        create_database_snapshot(db_path, snapshot_path)
        manifest = {
            "format": _BACKUP_FORMAT,
            "format_version": _BACKUP_FORMAT_VERSION,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "database_file": snapshot_path.name,
            "database_size": snapshot_path.stat().st_size,
            "database_sha256": _sha256_file(snapshot_path),
        }
        with zipfile.ZipFile(
            zip_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            archive.write(snapshot_path, arcname="openaver.db")
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )


@router.post("/import")
def import_database(file: UploadFile = File(...)) -> dict:
    """Restore a previously exported database after strict validation."""
    if is_generate_in_progress():
        raise _import_error(409, "runtime.database.import_task_running")

    db_path = get_db_path()
    temp_dir = Path(
        tempfile.mkdtemp(
            prefix="openaver-db-import-",
            dir=str(db_path.parent),
        )
    )
    upload_path = temp_dir / "upload.zip"
    try:
        if file.size is not None and file.size > _BACKUP_MAX_BYTES:
            raise _import_error(413, "runtime.database.import_too_large")

        written = 0
        with upload_path.open("wb") as output:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > _BACKUP_MAX_BYTES:
                    raise _import_error(413, "runtime.database.import_too_large")
                output.write(chunk)
        if written == 0:
            raise _import_error(422, "runtime.database.import_invalid_zip")

        new_db, manifest = _extract_backup(upload_path, temp_dir)
        _validate_snapshot(new_db, manifest)
        if is_generate_in_progress():
            raise _import_error(409, "runtime.database.import_task_running")

        backup_name = _restore_snapshot(db_path, new_db)
        logger.info(
            "database restored from %s (backup=%s)",
            manifest.get("created_at") or "unknown",
            backup_name or "none",
        )
        return {
            "ok": True,
            "restored_from": manifest.get("created_at") or "",
            "backup": backup_name,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("database import failed")
        raise _import_error(500, "runtime.database.import_failed") from None
    finally:
        try:
            file.file.close()
        except OSError:
            pass
        shutil.rmtree(temp_dir, ignore_errors=True)


@router.get("/export")
def export_database() -> FileResponse:
    """Download a consistent database snapshot as a ZIP archive."""
    db_path = get_db_path()
    if not db_path.exists():
        raise HTTPException(
            status_code=404,
            detail=i18n_t(
                "runtime.database.missing",
                locale=get_config_locale(),
            ),
        )

    descriptor, temp_name = tempfile.mkstemp(
        prefix="openaver-db-export-",
        suffix=".zip",
    )
    os.close(descriptor)
    zip_path = Path(temp_name)
    try:
        write_database_backup_zip(db_path, zip_path)
    except Exception:
        _safe_unlink(str(zip_path))
        logger.exception("database export failed")
        raise HTTPException(
            status_code=500,
            detail=i18n_t(
                "runtime.database.export_failed",
                locale=get_config_locale(),
            ),
        ) from None

    filename = time.strftime(
        "openaver-database-%Y%m%d-%H%M%S.zip",
        time.localtime(),
    )
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename,
        headers={"Cache-Control": "no-store"},
        background=BackgroundTask(_safe_unlink, str(zip_path)),
    )
