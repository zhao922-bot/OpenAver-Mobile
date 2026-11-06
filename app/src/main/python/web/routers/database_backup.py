"""Consistent SQLite snapshot export for OpenAver Mobile."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from core.database import get_connection, get_db_path
from core.i18n import get_config_locale, t as i18n_t
from core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/database", tags=["database"])

_BACKUP_FORMAT_VERSION = 1


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
        logger.warning("database export cleanup failed: %s", path, exc_info=True)


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
            "format": "openaver-mobile-database-backup",
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
