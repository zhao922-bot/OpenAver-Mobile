from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from core.database import Video, connection
from core.database.video import VideoRepository
from web.routers import database_backup


def _initialize_database(path: Path, video_path: str) -> None:
    connection._clear_db_init_cache()
    connection.init_db(path)
    VideoRepository(path).upsert(Video(path=video_path))


def _make_backup(source_db: Path, zip_path: Path) -> None:
    database_backup.write_database_backup_zip(source_db, zip_path)


def _upload(path: Path, filename: str = "backup.zip") -> UploadFile:
    return UploadFile(
        io.BytesIO(path.read_bytes()),
        filename=filename,
        headers=Headers({"content-type": "application/zip"}),
    )


def _patch_live_database(monkeypatch, path: Path) -> None:
    monkeypatch.setattr(database_backup, "get_db_path", lambda: path)
    monkeypatch.setattr(connection, "get_db_path", lambda: path)
    monkeypatch.setattr(database_backup, "is_generate_in_progress", lambda: False)


def test_database_import_replaces_live_database_and_keeps_backup(
    tmp_path,
    monkeypatch,
):
    source_db = tmp_path / "source.db"
    live_db = tmp_path / "openaver.db"
    backup_zip = tmp_path / "backup.zip"
    _initialize_database(source_db, "file:///library/source.mp4")
    _initialize_database(live_db, "file:///library/live.mp4")
    _make_backup(source_db, backup_zip)
    _patch_live_database(monkeypatch, live_db)

    result = database_backup.import_database(_upload(backup_zip))

    assert result["ok"] is True
    assert result["backup"].startswith("openaver.db.bak-")
    assert (tmp_path / result["backup"]).exists()
    repo = VideoRepository(live_db)
    assert repo.get_by_path("file:///library/source.mp4") is not None
    assert repo.get_by_path("file:///library/live.mp4") is None


def test_database_import_rejects_hash_mismatch_without_touching_live_db(
    tmp_path,
    monkeypatch,
):
    source_db = tmp_path / "source.db"
    live_db = tmp_path / "openaver.db"
    valid_zip = tmp_path / "valid.zip"
    tampered_zip = tmp_path / "tampered.zip"
    _initialize_database(source_db, "file:///library/source.mp4")
    _initialize_database(live_db, "file:///library/live.mp4")
    _make_backup(source_db, valid_zip)

    with zipfile.ZipFile(valid_zip) as source, zipfile.ZipFile(
        tampered_zip,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as target:
        for name in source.namelist():
            payload = source.read(name)
            if name == "manifest.json":
                manifest = json.loads(payload)
                manifest["database_sha256"] = "0" * 64
                payload = json.dumps(manifest).encode("utf-8")
            target.writestr(name, payload)

    _patch_live_database(monkeypatch, live_db)
    with pytest.raises(HTTPException) as error:
        database_backup.import_database(_upload(tampered_zip))

    assert error.value.status_code == 422
    assert VideoRepository(live_db).get_by_path("file:///library/live.mp4") is not None


def test_database_import_rejects_non_zip(tmp_path, monkeypatch):
    live_db = tmp_path / "openaver.db"
    upload_path = tmp_path / "not-a-zip.zip"
    upload_path.write_bytes(b"not a zip archive")
    _initialize_database(live_db, "file:///library/live.mp4")
    _patch_live_database(monkeypatch, live_db)

    with pytest.raises(HTTPException) as error:
        database_backup.import_database(_upload(upload_path))

    assert error.value.status_code == 422
    assert VideoRepository(live_db).get_by_path("file:///library/live.mp4") is not None


def test_database_import_rejects_path_traversal(tmp_path, monkeypatch):
    live_db = tmp_path / "openaver.db"
    upload_path = tmp_path / "traversal.zip"
    _initialize_database(live_db, "file:///library/live.mp4")
    with zipfile.ZipFile(upload_path, "w") as archive:
        archive.writestr("manifest.json", "{}")
        archive.writestr("../../evil.db", b"not sqlite")
    _patch_live_database(monkeypatch, live_db)

    with pytest.raises(HTTPException) as error:
        database_backup.import_database(_upload(upload_path))

    assert error.value.status_code == 422
    assert VideoRepository(live_db).get_by_path("file:///library/live.mp4") is not None


def test_database_import_rejects_active_task(tmp_path, monkeypatch):
    live_db = tmp_path / "openaver.db"
    upload_path = tmp_path / "empty.zip"
    upload_path.write_bytes(b"")
    _patch_live_database(monkeypatch, live_db)
    monkeypatch.setattr(database_backup, "is_generate_in_progress", lambda: True)

    with pytest.raises(HTTPException) as error:
        database_backup.import_database(_upload(upload_path))

    assert error.value.status_code == 409
