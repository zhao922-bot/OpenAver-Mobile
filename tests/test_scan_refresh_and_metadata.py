from __future__ import annotations

from core.database.video import MtimeIndexEntry, Video
from core.gallery_scanner import scan_entry_needs_refresh
from core.path_utils import to_file_uri
from web.routers import scanner as scanner_router


def _file_info(path, *, mtime=1.0, nfo_mtime=2.0, samples=0):
    return {
        "path": str(path),
        "mtime": mtime,
        "nfo_mtime": nfo_mtime,
        "sample_image_count": samples,
    }


def test_scan_refresh_detects_incomplete_metadata_and_missing_cover(tmp_path):
    video = tmp_path / "ABC-123.mp4"
    video.write_bytes(b"video")
    cover = tmp_path / "ABC-123.jpg"

    info = _file_info(video)
    entry = MtimeIndexEntry(
        mtime=1.0,
        nfo_mtime=2.0,
        sample_count=0,
        cover_path=to_file_uri(str(cover)),
        metadata_complete=False,
    )
    assert scan_entry_needs_refresh(entry, info) is True

    cover.write_bytes(b"jpeg")
    entry = entry._replace(metadata_complete=True)
    assert scan_entry_needs_refresh(entry, info) is False

    cover.unlink()
    assert scan_entry_needs_refresh(entry, info) is True


def test_preserve_missing_metadata_keeps_richer_database_values():
    scanned = Video(
        path="file:///video.mp4",
        number=None,
        title="",
        actresses=[],
        tags=[],
        maker="",
        release_date="",
        cover_path="",
        duration=None,
    )
    existing = Video(
        path="file:///video.mp4",
        number="ABC-123",
        title="Existing title",
        original_title="Original",
        actresses=["Actor A"],
        tags=["Tag A"],
        maker="Maker",
        release_date="2024-01-01",
        cover_path="file:///cover.jpg",
        duration=120,
    )

    scanned.preserve_missing_metadata(existing)

    assert scanned.number == "ABC-123"
    assert scanned.title == "Existing title"
    assert scanned.original_title == "Original"
    assert scanned.actresses == ["Actor A"]
    assert scanned.tags == ["Tag A"]
    assert scanned.maker == "Maker"
    assert scanned.release_date == "2024-01-01"
    assert scanned.cover_path == "file:///cover.jpg"
    assert scanned.duration == 120


def test_unchanged_nfo_rescan_keeps_nonempty_database_metadata():
    scanned = Video(
        path="file:///video.mp4",
        title="Old NFO title",
        tags=["old nfo tag"],
        cover_path="",
    )
    existing = Video(
        path="file:///video.mp4",
        title="Updated title",
        tags=["updated tag"],
        cover_path="file:///cover.jpg",
    )

    scanned.preserve_existing_metadata(existing)

    assert scanned.title == "Updated title"
    assert scanned.tags == ["updated tag"]
    assert scanned.cover_path == "file:///cover.jpg"


def test_unchanged_nfo_rescan_keeps_newly_discovered_cover():
    scanned = Video(path="file:///video.mp4", cover_path="file:///new-cover.jpg")
    existing = Video(path="file:///video.mp4", cover_path="file:///stale-cover.jpg")

    scanned.preserve_existing_metadata(existing)

    assert scanned.cover_path == "file:///new-cover.jpg"


def test_missing_check_treats_stale_cover_path_as_missing(tmp_path, monkeypatch):
    video_file = tmp_path / "ABC-124.mp4"
    video_file.write_bytes(b"video")
    missing_cover = tmp_path / "ABC-124.jpg"
    nfo_file = tmp_path / "ABC-124.nfo"
    nfo_file.write_text("<movie />", encoding="utf-8")
    row = Video(
        path=to_file_uri(str(video_file)),
        number="ABC-124",
        title="Title",
        nfo_mtime=1,
        cover_path=to_file_uri(str(missing_cover)),
    )

    class FakeRepo:
        def __init__(self, _db_path):
            pass

        def get_all(self):
            return [row]

    monkeypatch.setattr(scanner_router, "get_db_path", lambda: tmp_path / "db.sqlite")
    monkeypatch.setattr(scanner_router, "VideoRepository", FakeRepo)
    monkeypatch.setattr(
        scanner_router,
        "load_config",
        lambda: {"gallery": {"path_mappings": {}}},
    )
    (tmp_path / "db.sqlite").write_bytes(b"")

    result = scanner_router.check_missing()

    assert result["success"] is True
    assert result["data"]["missing_cover"] == 1


def test_missing_check_ignores_stale_nfo_mtime_when_file_is_absent(
    tmp_path,
    monkeypatch,
):
    video_file = tmp_path / "ABC-126.mp4"
    video_file.write_bytes(b"video")
    cover_file = tmp_path / "ABC-126.jpg"
    cover_file.write_bytes(b"cover")
    row = Video(
        path=to_file_uri(str(video_file)),
        number="ABC-126",
        title="Title",
        nfo_mtime=1,
        cover_path=to_file_uri(str(cover_file)),
    )

    class FakeRepo:
        def __init__(self, _db_path):
            pass

        def get_all(self):
            return [row]

    db_path = tmp_path / "db.sqlite"
    db_path.write_bytes(b"")
    monkeypatch.setattr(scanner_router, "get_db_path", lambda: db_path)
    monkeypatch.setattr(scanner_router, "VideoRepository", FakeRepo)
    monkeypatch.setattr(
        scanner_router,
        "load_config",
        lambda: {"gallery": {"path_mappings": {}}},
    )

    result = scanner_router.check_missing()

    assert result["success"] is True
    assert result["data"]["missing_nfo"] == 1
    assert result["data"]["missing_both"] == 0
