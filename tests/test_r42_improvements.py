from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import zipfile
from pathlib import Path

import pytest

from core.database import Video
from core.enricher import SampleBackfillCancelled
from core import enricher as enricher_router
from core.path_utils import to_file_uri
from web.routers import database_backup
from web.routers import scanner as scanner_router
from web.routers import search as search_router


def _video(path: Path, number: str = "ABC-123") -> Video:
    return Video(
        path=to_file_uri(str(path)),
        number=number,
        title=number,
    )


def test_local_status_serializes_real_multipart_playback(tmp_path):
    folder = tmp_path / "movie"
    cd1 = _video(folder / "ABC-123-cd1.mp4")
    cd2 = _video(folder / "ABC-123-cd2.mp4")

    payload = search_router._serialize_local_status(  # noqa: SLF001
        [cd1, cd2],
        {},
    )

    assert payload["exists"] is True
    assert payload["count"] == 2
    assert payload["playback"]["path"] == cd1.path
    assert payload["playback"]["paths"] == [cd1.path, cd2.path]
    assert payload["playback"]["part_tokens"] == ["cd1", "cd2"]
    assert payload["groups"][0]["paths"] == [cd1.path, cd2.path]


def test_extrafanart_cancel_checkpoint_stops_before_db_update(
    tmp_path,
    monkeypatch,
):
    video_path = tmp_path / "ABC-123.mp4"
    video_path.write_bytes(b"video")
    cancel_event = threading.Event()
    downloaded = []

    def fake_download(url, dest, **_kwargs):
        downloaded.append((url, dest))
        cancel_event.set()
        return True

    monkeypatch.setattr(enricher_router, "download_image", fake_download)

    with pytest.raises(SampleBackfillCancelled):
        enricher_router._write_extrafanart(  # noqa: SLF001
            str(video_path),
            ["https://example.test/fanart1.jpg"],
            write_extrafanart=True,
            cancel_event=cancel_event,
        )

    assert len(downloaded) == 1


def test_sample_backfill_cancel_returns_done_without_waiting(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "db.sqlite"
    db_path.write_bytes(b"")
    video = _video(tmp_path / "ABC-123.mp4")
    started = threading.Event()
    release = threading.Event()
    cancel_event = threading.Event()

    class Repo:
        def get_missing_sample_candidates(self):
            return [video]

    def slow_fetch(_req, worker_cancel_event):
        started.set()
        worker_cancel_event.wait(3)
        release.set()
        return {
            "success": False,
            "error_code": "cancelled",
            "message": "cancelled",
        }

    monkeypatch.setattr(scanner_router, "get_db_path", lambda: db_path)
    monkeypatch.setattr(scanner_router, "VideoRepository", lambda *_a, **_k: Repo())
    monkeypatch.setattr(scanner_router, "load_config", lambda: {
        "gallery": {"path_mappings": {}},
    })
    monkeypatch.setattr(
        "web.routers.scraper.fetch_samples_for_backfill",
        slow_fetch,
    )

    generator = scanner_router._sample_backfill_generator(cancel_event)  # noqa: SLF001
    next(generator)
    next(generator)

    cancel_event.set()
    started_at = time.monotonic()
    events = []
    while True:
        try:
            raw = next(generator)
        except StopIteration:
            break
        if raw.startswith("data: "):
            events.append(json.loads(raw[6:].strip()))
    elapsed = time.monotonic() - started_at

    assert elapsed < 1.0
    assert events[-1]["type"] == "done"
    assert events[-1]["cancelled"] is True
    assert release.wait(3.0) or started.wait(0.1)


def test_cancelled_worker_result_is_not_counted_as_failure(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "db.sqlite"
    db_path.write_bytes(b"")
    video = _video(tmp_path / "ABC-123.mp4")

    class Repo:
        def get_missing_sample_candidates(self):
            return [video]

    def cancelled_fetch(_req, worker_cancel_event):
        worker_cancel_event.set()
        return {
            "success": False,
            "error_code": "cancelled",
            "message": "cancelled",
        }

    monkeypatch.setattr(scanner_router, "get_db_path", lambda: db_path)
    monkeypatch.setattr(scanner_router, "VideoRepository", lambda *_a, **_k: Repo())
    monkeypatch.setattr(scanner_router, "load_config", lambda: {
        "gallery": {"path_mappings": {}},
    })
    monkeypatch.setattr(
        "web.routers.scraper.fetch_samples_for_backfill",
        cancelled_fetch,
    )

    generator = scanner_router._sample_backfill_generator(threading.Event())  # noqa: SLF001
    next(generator)
    next(generator)

    events = []
    while True:
        try:
            raw = next(generator)
        except StopIteration:
            break
        if raw.startswith("data: "):
            events.append(json.loads(raw[6:].strip()))

    assert events[-1]["type"] == "done"
    assert events[-1]["cancelled"] is True
    assert events[-1]["summary"]["failed"] == 0
    assert events[-1]["summary"]["failed_items"] == []


def test_database_snapshot_and_zip_are_consistent(tmp_path):
    db_path = tmp_path / "openaver.db"
    connection = sqlite3.connect(str(db_path))
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE videos (id INTEGER PRIMARY KEY, title TEXT)")
    connection.execute("INSERT INTO videos (title) VALUES ('one')")
    connection.commit()

    snapshot_path = tmp_path / "snapshot.db"
    database_backup.create_database_snapshot(db_path, snapshot_path)
    connection.close()

    snapshot = sqlite3.connect(str(snapshot_path))
    try:
        assert snapshot.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert snapshot.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 1
    finally:
        snapshot.close()

    zip_path = tmp_path / "backup.zip"
    database_backup.write_database_backup_zip(db_path, zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        assert set(archive.namelist()) == {"openaver.db", "manifest.json"}
        manifest = json.loads(archive.read("manifest.json"))
        db_bytes = archive.read("openaver.db")
    assert manifest["format"] == "openaver-mobile-database-backup"
    assert manifest["database_sha256"] == hashlib.sha256(db_bytes).hexdigest()
