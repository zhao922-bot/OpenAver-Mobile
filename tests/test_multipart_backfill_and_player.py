from __future__ import annotations

import json
import threading
from pathlib import Path

from core.database import Video
from core.enrich_contract import EnrichResult
from core import enricher as enricher_router
from core.enricher import ExtrafanartResult
from core.multipart_group import VideoGroup
from core.path_utils import to_file_uri
from web.routers import gallery_media
from web.routers import scanner as scanner_router
from web.routers import scraper as scraper_router
from web.routers import showcase as showcase_router


def _drain_events(generator):
    events = []
    while True:
        try:
            raw = next(generator)
        except StopIteration:
            return events
        if raw.startswith("data: "):
            events.append(json.loads(raw[6:].strip()))


def _video(path: Path, number: str = "ABC-123") -> Video:
    return Video(
        path=to_file_uri(str(path)),
        number=number,
        title=number,
        sample_images=[],
    )


class _FolderRepo:
    def __init__(self, rows, db_path=None):
        self.rows = rows
        self.updates = []

    def count_videos_in_folder(self, _prefix):
        return len(self.rows)

    def get_by_folder_uri_prefix(self, _prefix):
        return list(self.rows)

    def get_missing_sample_candidates(self):
        return list(self.rows)

    def update_sample_images(self, path, sample_images):
        self.updates.append((path, list(sample_images)))
        return True


def test_fetch_samples_allows_complete_multipart_group(tmp_path, monkeypatch):
    folder = tmp_path / "movie"
    folder.mkdir()
    cd1 = _video(folder / "ABC-123-cd1.mp4")
    cd2 = _video(folder / "ABC-123-cd2.mp4")
    repo = _FolderRepo([cd1, cd2])
    captured = {}

    def fake_detailed(**kwargs):
        captured.update(kwargs)
        return (
            EnrichResult(
                success=True,
                nfo_written=False,
                cover_written=False,
                extrafanart_written=2,
                fields_filled=[],
                source_used="test",
                error=None,
            ),
            {
                "downloaded": 2,
                "skipped_existing": 0,
                "extrafanart_on_disk": 2,
                "download_failed": 0,
            },
        )

    monkeypatch.setattr(scraper_router, "load_config", lambda: {
        "gallery": {"path_mappings": {}},
    })
    monkeypatch.setattr(scraper_router, "resolve_owning_output_root", lambda *_a, **_k: None)
    monkeypatch.setattr(scraper_router, "VideoRepository", lambda *_a, **_k: repo)
    monkeypatch.setattr(scraper_router, "fetch_samples_only_detailed", fake_detailed)

    result = scraper_router.fetch_samples_endpoint(
        scraper_router.FetchSamplesRequest(
            file_path=cd1.path,
            number=cd1.number,
        )
    )

    assert result["success"] is True
    assert captured["related_db_paths"] == [cd2.path]


def test_fetch_samples_rejects_unrelated_videos_in_same_folder(
    tmp_path,
    monkeypatch,
):
    folder = tmp_path / "mixed"
    folder.mkdir()
    first = _video(folder / "ABC-123.mp4", "ABC-123")
    second = _video(folder / "XYZ-456.mp4", "XYZ-456")
    repo = _FolderRepo([first, second])
    called = False

    def fake_detailed(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("unrelated folder must be rejected")

    monkeypatch.setattr(scraper_router, "load_config", lambda: {
        "gallery": {"path_mappings": {}},
    })
    monkeypatch.setattr(scraper_router, "resolve_owning_output_root", lambda *_a, **_k: None)
    monkeypatch.setattr(scraper_router, "VideoRepository", lambda *_a, **_k: repo)
    monkeypatch.setattr(scraper_router, "fetch_samples_only_detailed", fake_detailed)

    result = scraper_router.fetch_samples_endpoint(
        scraper_router.FetchSamplesRequest(
            file_path=first.path,
            number=first.number,
        )
    )

    assert called is False
    assert result["error_code"] == "multi_video_folder"
    assert result["count"] == 2


def test_fetch_samples_rejects_group_mixed_with_unrelated_video(
    tmp_path,
    monkeypatch,
):
    folder = tmp_path / "mixed-group"
    folder.mkdir()
    cd1 = _video(folder / "ABC-123-cd1.mp4")
    cd2 = _video(folder / "ABC-123-cd2.mp4")
    unrelated = _video(folder / "XYZ-456.mp4", "XYZ-456")
    repo = _FolderRepo([cd1, cd2, unrelated])

    monkeypatch.setattr(scraper_router, "load_config", lambda: {
        "gallery": {"path_mappings": {}},
    })
    monkeypatch.setattr(scraper_router, "resolve_owning_output_root", lambda *_a, **_k: None)
    monkeypatch.setattr(scraper_router, "VideoRepository", lambda *_a, **_k: repo)

    result = scraper_router.fetch_samples_endpoint(
        scraper_router.FetchSamplesRequest(
            file_path=cd1.path,
            number=cd1.number,
        )
    )

    assert result["error_code"] == "multi_video_folder"
    assert result["count"] == 3


def test_fetch_samples_only_updates_every_group_member(tmp_path, monkeypatch):
    cd1_path = tmp_path / "ABC-123-cd1.mp4"
    cd2_path = tmp_path / "ABC-123-cd2.mp4"
    cd1_path.write_bytes(b"video")
    cd2_path.write_bytes(b"video")
    cd1_uri = to_file_uri(str(cd1_path))
    cd2_uri = to_file_uri(str(cd2_path))
    sample_uri = to_file_uri(str(tmp_path / "extrafanart" / "fanart1.jpg"))
    repo = _FolderRepo([])

    monkeypatch.setattr(enricher_router, "search_jav", lambda *_a, **_k: {
        "source": "test",
        "sample_images": ["https://example.test/fanart1.jpg"],
        "preview_sample_images": [],
        "url": "https://example.test/ABC-123",
    })
    monkeypatch.setattr(
        enricher_router,
        "_write_extrafanart",
        lambda *_a, **_k: ExtrafanartResult(
            uris=[sample_uri],
            downloaded=1,
            skipped_existing=0,
            requested=1,
            failed=0,
        ),
    )
    monkeypatch.setattr(enricher_router, "VideoRepository", lambda *_a, **_k: repo)

    result, diagnostics = enricher_router.fetch_samples_only_detailed(
        file_path=cd1_uri,
        number="ABC-123",
        related_db_paths=[cd2_uri],
    )

    assert result.success is True
    assert diagnostics["downloaded"] == 1
    assert repo.updates == [
        (cd1_uri, [sample_uri]),
        (cd2_uri, [sample_uri]),
    ]


def test_sample_backfill_deduplicates_complete_multipart_group(
    tmp_path,
    monkeypatch,
):
    folder = tmp_path / "movie"
    folder.mkdir()
    cd1 = _video(folder / "ABC-123-cd1.mp4")
    cd2 = _video(folder / "ABC-123-cd2.mp4")
    repo = _FolderRepo([cd1, cd2])
    db_path = tmp_path / "db.sqlite"
    db_path.write_bytes(b"")
    fetched = []

    def fake_fetch(req, _cancel_event):
        fetched.append(req.file_path)
        return {
            "success": True,
            "downloaded": 2,
            "skipped_existing": 0,
            "extrafanart_on_disk": 2,
        }

    monkeypatch.setattr(scanner_router, "get_db_path", lambda: db_path)
    monkeypatch.setattr(scanner_router, "VideoRepository", lambda *_a, **_k: repo)
    monkeypatch.setattr(scanner_router, "load_config", lambda: {
        "gallery": {"path_mappings": {}},
    })
    monkeypatch.setattr(
        "web.routers.scraper.fetch_samples_for_backfill",
        fake_fetch,
    )

    events = _drain_events(
        scanner_router._sample_backfill_generator(threading.Event())  # noqa: SLF001
    )

    assert fetched == [cd1.path]
    progress = [
        event for event in events
        if event.get("type") == "progress"
    ][0]
    assert progress["total"] == 1
    assert events[-1]["summary"]["success"] == 1


def test_missing_check_counts_multipart_group_once(tmp_path, monkeypatch):
    folder = tmp_path / "movie"
    folder.mkdir()
    cd1 = _video(folder / "ABC-123-cd1.mp4")
    cd2 = _video(folder / "ABC-123-cd2.mp4")
    db_path = tmp_path / "db.sqlite"
    db_path.write_bytes(b"")

    class MissingCheckRepo(_FolderRepo):
        def get_all(self):
            return list(self.rows)

    repo = MissingCheckRepo([cd1, cd2])
    monkeypatch.setattr(scanner_router, "get_db_path", lambda: db_path)
    monkeypatch.setattr(scanner_router, "VideoRepository", lambda *_a, **_k: repo)
    monkeypatch.setattr(scanner_router, "load_config", lambda: {
        "gallery": {"path_mappings": {}},
    })
    monkeypatch.setattr(scanner_router, "_video_has_nfo", lambda *_a, **_k: True)

    result = scanner_router.check_missing()

    assert result["success"] is True
    assert result["data"]["missing_samples"] == 1
    assert [item["file_path"] for item in result["data"]["missing_sample_items"]] == [
        cd1.path
    ]


def test_showcase_group_serializes_part_paths():
    cd1 = Video(
        path="file:///library/ABC-123-cd1.mp4",
        number="ABC-123",
        title="Title",
        size_bytes=10,
    )
    cd2 = Video(
        path="file:///library/ABC-123-cd2.mp4",
        number="ABC-123",
        title="Title",
        size_bytes=20,
    )

    payload = showcase_router._serialize_group(  # noqa: SLF001
        VideoGroup(members=[cd1, cd2], part_tokens=["cd1", "cd2"]),
        {},
    )

    assert payload["part_tokens"] == ["cd1", "cd2"]
    assert payload["part_paths"] == [cd1.path, cd2.path]


def test_web_player_can_start_at_any_multipart_part(tmp_path, monkeypatch):
    cd1 = Video(
        path="file:///library/ABC-123-cd1.mp4",
        number="ABC-123",
        title="Title",
    )
    cd2 = Video(
        path="file:///library/ABC-123-cd2.mp4",
        number="ABC-123",
        title="Title",
    )
    group = VideoGroup(members=[cd1, cd2], part_tokens=["cd1", "cd2"])
    db_path = tmp_path / "db.sqlite"
    db_path.write_bytes(b"")

    class PlayerRepo:
        def __init__(self, _db_path):
            pass

        def get_by_path(self, path):
            return cd1 if path == cd1.path else cd2 if path == cd2.path else None

    monkeypatch.setattr(gallery_media, "get_db_path", lambda: db_path)
    monkeypatch.setattr(gallery_media, "VideoRepository", PlayerRepo)
    monkeypatch.setattr(gallery_media, "load_config", lambda: {
        "general": {"locale": "zh-CN"},
        "gallery": {"path_mappings": {}},
    })
    monkeypatch.setattr(gallery_media, "resolve_group", lambda *_a, **_k: group)

    response = gallery_media.video_player(path=cd2.path, part=None)
    html = response.body.decode("utf-8")

    assert 'data-start-index="1"' in html
    assert 'id="oa-player-parts"' in html
    assert 'data-part-tokens="[&quot;cd1&quot;,&quot;cd2&quot;]"' in html
    assert "/api/gallery/video?path=file%3A%2F%2F%2Flibrary%2FABC-123-cd2.mp4" in html
