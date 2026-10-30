from __future__ import annotations

import json

from core.database import Video
from core.path_utils import to_file_uri
from web.routers import scanner as scanner_router


def _events(stream):
    for chunk in stream:
        assert chunk.startswith("data: ")
        yield json.loads(chunk[6:].strip())


def test_source_rename_preview_uses_selected_source_title(tmp_path, monkeypatch):
    db_path = tmp_path / "db.sqlite"
    db_path.touch()
    root = tmp_path / "library"
    folder = root / "ABC123 舊名稱"
    folder.mkdir(parents=True)
    video = folder / "ABC123 舊名稱.mp4"
    nfo = folder / "ABC123 舊名稱.nfo"
    cover = folder / "ABC123 舊名稱.jpg"
    for path in (video, nfo, cover):
        path.write_bytes(path.name.encode("utf-8"))

    row = Video(
        path=to_file_uri(str(video)),
        number="ABC-123",
        title="舊標題",
        cover_path=to_file_uri(str(cover)),
    )
    config = {
        "general": {"locale": "zh-CN"},
        "sources": [{
            "id": "javbus",
            "type": "builtin",
            "enabled": True,
            "manual_only": False,
            "order": 0,
        }],
        "gallery": {
            "directories": [str(root)],
            "path_mappings": {},
        },
    }

    class FakeRepo:
        def __init__(self, _path):
            pass

        def get_all(self):
            return [row]

    monkeypatch.setattr(scanner_router, "load_config", lambda: config)
    monkeypatch.setattr(scanner_router, "get_db_path", lambda: db_path)
    monkeypatch.setattr(scanner_router, "VideoRepository", FakeRepo)
    monkeypatch.setattr(scanner_router, "get_javbus_lang", lambda: "zh-tw")
    monkeypatch.setattr(
        scanner_router,
        "search_jav",
        lambda number, **kwargs: {
            "title": "ABC-123 來源新標題",
            "source": "javbus",
        },
    )
    scanner_router._rename_plan_cache.clear()

    events = list(_events(
        scanner_router.generate_source_rename_preview("javbus")
    ))
    done = next(event for event in events if event["type"] == "done")
    plan = done["plan"]
    item = plan["items"][0]

    assert plan["source"] == "javbus"
    assert plan["summary"]["conflicts"] == 0
    assert plan["summary"]["failed"] == 0
    assert item["new_name"] == "ABC-123 來源新標題"
    assert item["videos"][0]["new_name"] == "ABC-123 來源新標題.mp4"
    assert plan["plan_id"] in scanner_router._rename_plan_cache


def test_source_rename_preview_reports_source_failures(tmp_path, monkeypatch):
    db_path = tmp_path / "db.sqlite"
    db_path.touch()
    root = tmp_path / "library"
    folder = root / "ABC123 舊名稱"
    folder.mkdir(parents=True)
    video = folder / "ABC123 舊名稱.mp4"
    video.write_bytes(b"video")
    row = Video(
        path=to_file_uri(str(video)),
        number="ABC-123",
        title="舊標題",
    )
    config = {
        "sources": [{
            "id": "javbus",
            "type": "builtin",
            "enabled": True,
            "manual_only": False,
            "order": 0,
        }],
        "gallery": {
            "directories": [str(root)],
            "path_mappings": {},
        },
    }

    class FakeRepo:
        def __init__(self, _path):
            pass

        def get_all(self):
            return [row]

    monkeypatch.setattr(scanner_router, "load_config", lambda: config)
    monkeypatch.setattr(scanner_router, "get_db_path", lambda: db_path)
    monkeypatch.setattr(scanner_router, "VideoRepository", FakeRepo)
    monkeypatch.setattr(scanner_router, "get_javbus_lang", lambda: "zh-tw")

    def fail_search(_number, **_kwargs):
        raise OSError("source offline")

    monkeypatch.setattr(scanner_router, "search_jav", fail_search)
    scanner_router._rename_plan_cache.clear()

    events = list(_events(
        scanner_router.generate_source_rename_preview("javbus")
    ))
    done = next(event for event in events if event["type"] == "done")
    plan = done["plan"]

    assert plan["summary"]["failed"] == 1
    assert plan["failed_items"][0]["number"] == "ABC-123"
    assert plan["items"] == []
    assert not plan["plan_id"] in scanner_router._rename_plan_cache
