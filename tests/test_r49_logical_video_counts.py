from __future__ import annotations

import json
import threading
from types import SimpleNamespace

from core.database import Video
from core.multipart_group import (
    logical_video_count,
    resolve_logical_video_groups,
)
from core.path_utils import to_file_uri
from web.routers import scanner as scanner_router
from web.routers import search as search_router


def _video(
    path: str,
    *,
    row_id: int | None = None,
    number: str = "ABC-123",
    title: str = "日本語タイトル",
    actresses: list[str] | None = None,
    sample_images: list[str] | None = None,
) -> Video:
    return Video(
        id=row_id,
        path=path,
        number=number,
        title=title,
        actresses=actresses or [],
        sample_images=sample_images or [],
    )


def _drain_events(generator):
    events = []
    while True:
        try:
            raw = next(generator)
        except StopIteration:
            return events
        if raw.startswith("data: "):
            events.append(json.loads(raw[6:].strip()))


def test_logical_video_count_covers_complete_incomplete_and_conflicting_parts(
    tmp_path,
):
    folder = tmp_path / "library"
    rows = [
        _video(str(folder / "ABC-123-cd1.mp4")),
        _video(str(folder / "ABC-123-cd2.mp4")),
        _video(str(folder / "XYZ-456.mp4"), number="XYZ-456"),
        _video(str(folder / "DEF-789.mp4"), number="DEF-789"),
        _video(str(folder / "DEF-789-cd2.mp4"), number="DEF-789"),
        _video(str(folder / "GHI-012-cd1.mp4"), number="GHI-012"),
        _video(str(folder / "GHI-012-pt1.mp4"), number="GHI-012"),
    ]
    for video in rows:
        video.path = to_file_uri(video.path)

    assert logical_video_count(rows, {}) == 6


def test_filtered_candidate_resolves_to_complete_logical_group(tmp_path):
    cd1 = _video(to_file_uri(str(tmp_path / "ABC-123-cd1.mp4")))
    cd2 = _video(to_file_uri(str(tmp_path / "ABC-123-cd2.mp4")))
    other = _video(
        to_file_uri(str(tmp_path / "XYZ-456.mp4")),
        number="XYZ-456",
    )

    class FolderRepo:
        def get_by_folder_uri_prefix(self, _prefix):
            return [cd1, cd2, other]

    groups = resolve_logical_video_groups(
        FolderRepo(),
        [cd2, other],
        {},
    )

    assert [[member.path for member in group.members] for group in groups] == [
        [cd1.path, cd2.path],
        [other.path],
    ]


def test_scanner_stats_counts_complete_parts_as_one(tmp_path, monkeypatch):
    cd1 = _video(to_file_uri(str(tmp_path / "ABC-123-cd1.mp4")))
    cd2 = _video(to_file_uri(str(tmp_path / "ABC-123-cd2.mp4")))
    db_path = tmp_path / "openaver.db"
    db_path.write_bytes(b"")

    class FakeRepo:
        def __init__(self, _db_path):
            pass

        def get_all(self):
            return [cd1, cd2]

    monkeypatch.setattr(scanner_router, "get_db_path", lambda: db_path)
    monkeypatch.setattr(scanner_router, "VideoRepository", FakeRepo)
    monkeypatch.setattr(
        scanner_router,
        "load_config",
        lambda: {"gallery": {"path_mappings": {}}},
    )

    result = scanner_router.get_stats()

    assert result["success"] is True
    assert result["data"]["total"] == 1
    assert result["data"]["last_total"] == 1


def test_missing_check_and_title_queues_count_one_logical_video(
    tmp_path,
    monkeypatch,
):
    cd1 = _video(to_file_uri(str(tmp_path / "ABC-123-cd1.mp4")))
    cd2 = _video(to_file_uri(str(tmp_path / "ABC-123-cd2.mp4")))
    db_path = tmp_path / "openaver.db"
    db_path.write_bytes(b"")

    class FakeRepo:
        def __init__(self, _db_path):
            pass

        def get_all(self):
            return [cd1, cd2]

    monkeypatch.setattr(scanner_router, "get_db_path", lambda: db_path)
    monkeypatch.setattr(scanner_router, "VideoRepository", FakeRepo)
    monkeypatch.setattr(
        scanner_router,
        "load_config",
        lambda: {
            "general": {"locale": "zh-CN"},
            "gallery": {"path_mappings": {}},
        },
    )
    monkeypatch.setattr(
        scanner_router,
        "_video_has_nfo",
        lambda *_args, **_kwargs: False,
    )

    result = scanner_router.check_missing()
    data = result["data"]

    assert data["missing_both"] == 1
    assert data["total_missing"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["member_paths"] == [cd1.path, cd2.path]
    assert data["untranslated_titles"] == 1
    assert data["untranslated_title_items"][0]["member_paths"] == [
        cd1.path,
        cd2.path,
    ]
    assert data["missing_samples"] == 1
    assert data["missing_sample_items"][0]["member_paths"] == [
        cd1.path,
        cd2.path,
    ]


def test_title_backfill_translates_once_and_writes_every_part(
    tmp_path,
    monkeypatch,
):
    cd1 = _video(to_file_uri(str(tmp_path / "ABC-123-cd1.mp4")))
    cd2 = _video(to_file_uri(str(tmp_path / "ABC-123-cd2.mp4")))
    db_path = tmp_path / "openaver.db"
    db_path.write_bytes(b"")
    translated_titles = []
    written_paths = []

    class FakeRepo:
        def __init__(self, _db_path):
            pass

        def get_untranslated_title_candidates(self):
            return [cd1, cd2]

        def get_by_folder_uri_prefix(self, _prefix):
            return [cd1, cd2]

    class FakeService:
        async def translate_or_raise(self, title, _context):
            translated_titles.append(title)
            return "中文标题"

    def fake_writeback(_repo, video, request, _config, _path_mappings):
        written_paths.append(video.path)
        return {
            "success": True,
            "title": request.title,
            "original_title": video.title,
        }

    monkeypatch.setattr(scanner_router, "get_db_path", lambda: db_path)
    monkeypatch.setattr(scanner_router, "VideoRepository", FakeRepo)
    monkeypatch.setattr(
        scanner_router,
        "load_config",
        lambda: {
            "translate": {"enabled": True},
            "general": {"locale": "zh-CN"},
            "gallery": {"path_mappings": {}},
        },
    )
    monkeypatch.setattr(
        "web.routers.translate.get_translate_service",
        lambda: FakeService(),
    )
    monkeypatch.setattr(
        "web.routers.showcase._apply_title_writeback",
        fake_writeback,
    )

    events = _drain_events(
        scanner_router._title_backfill_generator(threading.Event())  # noqa: SLF001
    )

    assert translated_titles == [cd1.title]
    assert written_paths == [cd1.path, cd2.path]
    result_items = [
        event for event in events if event.get("type") == "result-item"
    ]
    assert len(result_items) == 1
    assert result_items[0]["updated_member_count"] == 2
    assert result_items[0]["member_paths"] == [cd1.path, cd2.path]
    assert events[-1]["summary"]["success"] == 1


def test_actress_stats_count_complete_parts_as_one(tmp_path, monkeypatch):
    cd1 = _video(
        to_file_uri(str(tmp_path / "ABC-123-cd1.mp4")),
        actresses=["Alice"],
    )
    cd2 = _video(
        to_file_uri(str(tmp_path / "ABC-123-cd2.mp4")),
        actresses=["Alice"],
    )
    other = _video(
        to_file_uri(str(tmp_path / "XYZ-456.mp4")),
        number="XYZ-456",
        actresses=["Alice"],
    )
    db_path = tmp_path / "openaver.db"
    db_path.write_bytes(b"")

    class FakeRepo:
        def __init__(self, _db_path):
            pass

        def get_videos_by_actress(self, _name):
            return [cd1, cd2, other]

        def get_by_folder_uri_prefix(self, _prefix):
            return [cd1, cd2, other]

    monkeypatch.setattr(scanner_router, "get_db_path", lambda: db_path)
    monkeypatch.setattr(scanner_router, "VideoRepository", FakeRepo)
    monkeypatch.setattr(
        scanner_router,
        "load_config",
        lambda: {"gallery": {"path_mappings": {}}},
    )

    result = scanner_router.get_actress_stats("Alice")

    assert result["success"] is True
    assert result["data"]["count"] == 2


def test_actress_library_counts_complete_parts_as_one(monkeypatch):
    import core.database.actress_library as actress_library

    cd1 = _video(
        to_file_uri("/library/ABC-123-cd1.mp4"),
        row_id=1,
        actresses=["Alice"],
    )
    cd2 = _video(
        to_file_uri("/library/ABC-123-cd2.mp4"),
        row_id=2,
        actresses=["Alice"],
    )

    class FakeActressRepo:
        def get_video_actress_pairs(self):
            return [(1, "Alice"), (2, "Alice")]

        def get_all(self):
            return [SimpleNamespace(name="Alice")]

    class FakeVideoRepo:
        def get_all(self):
            return [cd1, cd2]

    class FakeAliasRepo:
        def get_all(self):
            return [SimpleNamespace(primary_name="Alice", aliases=[])]

    monkeypatch.setattr(
        actress_library, "ActressRepository", FakeActressRepo
    )
    monkeypatch.setattr(actress_library, "VideoRepository", FakeVideoRepo)
    monkeypatch.setattr(actress_library, "AliasRepository", FakeAliasRepo)
    monkeypatch.setattr(
        actress_library,
        "load_config",
        lambda: {"gallery": {"path_mappings": {}}},
    )

    result = actress_library.get_library_actresses()

    assert len(result) == 1
    assert result[0]["video_count"] == 1


def test_search_local_status_reports_logical_count(tmp_path):
    cd1 = _video(to_file_uri(str(tmp_path / "ABC-123-cd1.mp4")))
    cd2 = _video(to_file_uri(str(tmp_path / "ABC-123-cd2.mp4")))

    result = search_router._serialize_local_status(  # noqa: SLF001
        [cd1, cd2],
        {},
    )

    assert result["count"] == 1
    assert len(result["groups"]) == 1
    assert result["groups"][0]["paths"] == [cd1.path, cd2.path]


def test_clear_cache_reports_logical_video_count(tmp_path, monkeypatch):
    cd1 = _video(to_file_uri(str(tmp_path / "ABC-123-cd1.mp4")))
    cd2 = _video(to_file_uri(str(tmp_path / "ABC-123-cd2.mp4")))
    db_path = tmp_path / "openaver.db"
    db_path.write_bytes(b"")

    class FakeRepo:
        def __init__(self, _db_path):
            pass

        def get_all(self):
            return [cd1, cd2]

        def clear_all(self):
            return 2

    monkeypatch.setattr(scanner_router, "get_db_path", lambda: db_path)
    monkeypatch.setattr(scanner_router, "VideoRepository", FakeRepo)
    monkeypatch.setattr(
        scanner_router,
        "load_config",
        lambda: {"gallery": {"path_mappings": {}}},
    )
    monkeypatch.setattr(
        scanner_router.thumbnail_cache,
        "clear_all",
        lambda: None,
    )

    result = scanner_router.clear_cache()

    assert result["success"] is True
    assert result["deleted"] == 1
    assert result["physical_deleted"] == 2


def test_nfo_helpers_aggregate_multipart_progress_and_failures(tmp_path):
    cd1 = _video(to_file_uri(str(tmp_path / "ABC-123-cd1.mp4")))
    cd2 = _video(to_file_uri(str(tmp_path / "ABC-123-cd2.mp4")))
    all_videos = [cd1, cd2]
    physical_stats = {
        "paths": [cd1.path, cd2.path],
        "items": [
            {
                "path": cd1.path,
                "number": "ABC-123",
                "missing": ["title"],
            },
            {
                "path": cd2.path,
                "number": "ABC-123",
                "missing": ["date"],
            },
        ],
    }

    grouped = scanner_router._grouped_nfo_stats(  # noqa: SLF001
        all_videos,
        physical_stats,
        {},
    )
    groups = scanner_router._logical_groups_for_paths(  # noqa: SLF001
        all_videos,
        physical_stats["paths"],
        {},
    )
    summary = scanner_router._logical_nfo_summary(  # noqa: SLF001
        {
            "failed_items": [
                {"path": cd1.path, "error": "one"},
                {"path": cd2.path, "error": "two"},
            ],
            "updated_paths": [],
        },
        groups,
    )

    assert grouped["need_update"] == 1
    assert grouped["paths"] == [cd1.path]
    assert grouped["physical_paths"] == [cd1.path, cd2.path]
    assert grouped["items"][0]["missing"] == ["date", "title"]
    assert summary["total"] == 1
    assert summary["failed"] == 1
    assert summary["physical_failed_items"] == 2
    assert len(summary["failed_items"]) == 1
    assert summary["failed_items"][0]["member_paths"] == [
        cd1.path,
        cd2.path,
    ]


def test_jellyfin_check_counts_multipart_as_one(tmp_path):
    cover1 = tmp_path / "ABC-123-cd1.jpg"
    cover2 = tmp_path / "ABC-123-cd2.jpg"
    cover1.write_bytes(b"cover1")
    cover2.write_bytes(b"cover2")
    cd1 = _video(to_file_uri(str(tmp_path / "ABC-123-cd1.mp4")))
    cd2 = _video(to_file_uri(str(tmp_path / "ABC-123-cd2.mp4")))
    cd1.cover_path = to_file_uri(str(cover1))
    cd2.cover_path = to_file_uri(str(cover2))

    class FakeRepo:
        def get_all(self):
            return [cd1, cd2]

    result = scanner_router.check_jellyfin_images_needed(  # noqa: SLF001
        FakeRepo(),
        {},
    )

    assert result["need_update"] == 1
    assert len(result["items"]) == 1
    assert len(result["items"][0]["member_items"]) == 2
    assert result["items"][0]["member_paths"] == [cd1.path, cd2.path]
