from __future__ import annotations

import json
import threading

from core.database import Video, VideoRepository, init_db
from core.path_utils import to_file_uri
from web.routers import scanner as scanner_router


def _drain_events(generator):
    events = []
    while True:
        try:
            raw = next(generator)
        except StopIteration:
            return events
        if not raw.startswith("data: "):
            continue
        events.append(json.loads(raw[6:].strip()))


def test_title_backfill_candidate_requires_japanese_and_no_saved_original():
    assert scanner_router._is_untranslated_title_candidate(  # noqa: SLF001
        Video(path="file:///a.mp4", title="これは未翻訳です", original_title="")
    ) is True
    assert scanner_router._is_untranslated_title_candidate(  # noqa: SLF001
        Video(path="file:///b.mp4", title="これは処理済みです", original_title="已翻译")
    ) is False
    assert scanner_router._is_untranslated_title_candidate(  # noqa: SLF001
        Video(path="file:///c.mp4", title="English title", original_title="")
    ) is False
    assert scanner_router._is_untranslated_title_candidate(  # noqa: SLF001
        Video(path="file:///d.mp4", title="", original_title="")
    ) is False


def test_sample_backfill_candidate_requires_a_usable_stored_image():
    assert scanner_router._is_missing_sample_candidate(  # noqa: SLF001
        Video(path="file:///a.mp4", sample_images=[])
    ) is True
    assert scanner_router._is_missing_sample_candidate(  # noqa: SLF001
        Video(path="file:///b.mp4", sample_images=[""])
    ) is True
    assert scanner_router._is_missing_sample_candidate(  # noqa: SLF001
        Video(path="file:///c.mp4", sample_images=["file:///fanart1.jpg"])
    ) is False


def test_repository_backfill_queries_filter_at_storage_boundary(tmp_path):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    repo = VideoRepository(db_path)
    repo.upsert(Video(
        path="file:///A.mp4",
        number="A-1",
        title="これは未翻訳です",
        original_title="",
        sample_images=[],
    ))
    repo.upsert(Video(
        path="file:///B.mp4",
        number="B-1",
        title="これは処理済みです",
        original_title="已翻译",
        sample_images=["file:///fanart1.jpg"],
    ))
    repo.upsert(Video(
        path="file:///C.mp4",
        number="C-1",
        title="English title",
        original_title="",
        sample_images=[],
    ))

    assert [
        video.path for video in repo.get_untranslated_title_candidates()
    ] == ["file:///A.mp4", "file:///C.mp4"]
    assert [
        video.path for video in repo.get_missing_sample_candidates()
    ] == ["file:///A.mp4", "file:///C.mp4"]


def test_missing_check_reports_backfill_queues_even_when_nfo_and_cover_exist(
    tmp_path,
    monkeypatch,
):
    video_file = tmp_path / "ABC-201.mp4"
    video_file.write_bytes(b"video")
    nfo_file = tmp_path / "ABC-201.nfo"
    nfo_file.write_text("<movie />", encoding="utf-8")
    cover_file = tmp_path / "ABC-201.jpg"
    cover_file.write_bytes(b"cover")
    row = Video(
        path=to_file_uri(str(video_file)),
        number="ABC-201",
        title="未翻訳のタイトル",
        original_title="",
        nfo_mtime=1,
        cover_path=to_file_uri(str(cover_file)),
        sample_images=[],
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
    data = result["data"]
    assert data["total_missing"] == 0
    assert data["untranslated_titles"] == 1
    assert data["missing_samples"] == 1
    assert data["untranslated_title_items"][0]["number"] == "ABC-201"
    assert data["missing_sample_items"][0]["file_path"] == row.path


def test_title_backfill_generator_processes_only_missing_candidates(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "db.sqlite"
    db_path.write_bytes(b"")
    candidates = [
        Video(
            path="file:///ABC-202.mp4",
            number="ABC-202",
            title="これは未翻訳です",
        ),
        Video(
            path="file:///ABC-203.mp4",
            number="ABC-203",
            title="これは処理済みです",
            original_title="已翻译",
        ),
        Video(
            path="file:///ABC-204.mp4",
            number="ABC-204",
            title="English title",
        ),
    ]
    translated_paths = []

    class FakeRepo:
        def __init__(self, _db_path):
            pass

        def get_untranslated_title_candidates(self):
            return candidates

    class FakeService:
        async def translate_or_raise(self, title, context):
            assert title == "これは未翻訳です"
            return "这是未翻译"

    def fake_writeback(_repo, video, req, _config, _path_mappings):
        translated_paths.append(video.path)
        return {
            "success": True,
            "title": req.title,
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

    assert translated_paths == ["file:///ABC-202.mp4"]
    done = events[-1]
    assert done["type"] == "done"
    assert done["summary"]["success"] == 1
    assert done["summary"]["failed"] == 0


def test_sample_backfill_generator_skips_rows_with_existing_samples(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "db.sqlite"
    db_path.write_bytes(b"")
    missing = Video(
        path="file:///ABC-205.mp4",
        number="ABC-205",
        title="Missing samples",
        sample_images=[],
    )
    present = Video(
        path="file:///ABC-206.mp4",
        number="ABC-206",
        title="Has samples",
        sample_images=["file:///extrafanart/fanart1.jpg"],
    )
    fetched_paths = []

    class FakeRepo:
        def __init__(self, _db_path):
            pass

        def get_missing_sample_candidates(self):
            return [missing, present]

    def fake_fetch(req):
        fetched_paths.append(req.file_path)
        return {
            "success": True,
            "downloaded": 2,
            "skipped_existing": 0,
            "extrafanart_on_disk": 2,
        }

    monkeypatch.setattr(scanner_router, "get_db_path", lambda: db_path)
    monkeypatch.setattr(scanner_router, "VideoRepository", FakeRepo)
    monkeypatch.setattr(
        "web.routers.scraper.fetch_samples_endpoint",
        fake_fetch,
    )

    events = _drain_events(
        scanner_router._sample_backfill_generator(threading.Event())  # noqa: SLF001
    )

    assert fetched_paths == ["file:///ABC-205.mp4"]
    done = events[-1]
    assert done["type"] == "done"
    assert done["summary"]["success"] == 1
    assert done["summary"]["failed"] == 0
