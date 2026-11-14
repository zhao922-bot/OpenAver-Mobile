from __future__ import annotations

import json

from core.database import Video
from core.cf_transport import CfChallengeRequired
from core.path_utils import to_file_uri
from web.routers import scanner as scanner_router


def _sse_payloads(events):
    return [
        json.loads(event.removeprefix("data: ").strip())
        for event in events
    ]


def test_batch_tag_source_update_replaces_tags_and_nfo(
    tmp_path, monkeypatch
):
    video_file = tmp_path / "ABC-123-C.mp4"
    video_file.write_bytes(b"video")
    nfo = tmp_path / "ABC-123-C.nfo"
    nfo.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<movie><title>Keep</title><tag>old</tag><genre>old</genre>"
        "<plot>keep plot</plot><user_tag>mine</user_tag></movie>",
        encoding="utf-8",
    )
    video = Video(
        path=to_file_uri(str(video_file)),
        number="ABC-123",
        title="Keep",
        original_title="Original",
    )
    (tmp_path / "db.sqlite").write_bytes(b"")
    calls = {}

    class FakeRepo:
        def __init__(self, _db_path):
            pass

        def get_all(self):
            return [video]

        def update_tags_if_changed(self, path, tags):
            calls["tags_path"] = path
            calls["tags"] = tags
            return True

        def update_titles(self, path, title, original_title, nfo_mtime):
            calls["mtime_path"] = path
            calls["nfo_mtime"] = nfo_mtime
            return True

    monkeypatch.setattr(
        scanner_router,
        "load_config",
        lambda: {
            "sources": [
                {"id": "javbus", "enabled": True, "manual_only": False}
            ],
            "gallery": {},
        },
    )
    monkeypatch.setattr(scanner_router, "get_db_path", lambda: tmp_path / "db.sqlite")
    monkeypatch.setattr(scanner_router, "VideoRepository", FakeRepo)
    monkeypatch.setattr(scanner_router, "get_javbus_lang", lambda: "zh-tw")
    monkeypatch.setattr(
        scanner_router,
        "search_jav",
        lambda *_args, **_kwargs: {"tags": ["痴女", "巨乳"]},
    )
    monkeypatch.setattr(
        scanner_router,
        "readonly_source_prefixes",
        lambda *_args, **_kwargs: set(),
    )
    monkeypatch.setattr(
        scanner_router,
        "writable_source_prefixes",
        lambda *_args, **_kwargs: set(),
    )

    events = _sse_payloads(
        scanner_router.generate_tag_source_update("javbus")
    )

    assert events[-1]["type"] == "done"
    assert events[-1]["summary"]["success"] == 1
    assert events[-1]["summary"]["changed_numbers"] == ["ABC-123"]
    assert calls["tags_path"] == video.path
    assert calls["tags"] == ["痴女", "巨乳", "中文字幕"]
    assert calls["nfo_mtime"] > 0

    text = nfo.read_text(encoding="utf-8")
    assert "<tag>痴女</tag>" in text
    assert "<tag>old</tag>" not in text
    assert "<user_tag>mine</user_tag>" in text
    assert "<plot>keep plot</plot>" in text


def test_batch_tag_source_accepts_manual_only_source():
    error = scanner_router._validate_batch_tag_source(  # noqa: SLF001
        "javlibrary",
        {
            "sources": [
                {"id": "javlibrary", "enabled": True, "manual_only": True}
            ]
        },
    )

    assert error is None


def test_batch_tag_source_accepts_jable_manual_only_source():
    error = scanner_router._validate_batch_tag_source(  # noqa: SLF001
        "jable",
        {
            "sources": [
                {"id": "jable", "enabled": False, "manual_only": True}
            ]
        },
    )

    assert error is None


def test_batch_tag_source_accepts_known_manual_only_source_without_config_row():
    error = scanner_router._validate_batch_tag_source(  # noqa: SLF001
        "javlibrary",
        {"sources": []},
    )

    assert error is None


def test_batch_tag_source_rejects_disabled_source():
    error = scanner_router._validate_batch_tag_source(  # noqa: SLF001
        "javbus",
        {
            "sources": [
                {"id": "javbus", "enabled": False, "manual_only": False}
            ]
        },
    )

    assert error is not None
    assert "未启用" in error


def test_batch_tag_source_rejects_custom_source():
    error = scanner_router._validate_batch_tag_source(  # noqa: SLF001
        "custom:demo",
        {},
    )

    assert error is not None
    assert "自定义" in error


def test_batch_tag_source_preserves_sidecar_subtitle_tag(
    tmp_path, monkeypatch
):
    video_file = tmp_path / "ABC-123.mp4"
    video_file.write_bytes(b"video")
    (tmp_path / "ABC-123.chs.srt").write_text("subtitle", encoding="utf-8")
    nfo = tmp_path / "ABC-123.nfo"
    nfo.write_text(
        '<?xml version="1.0" encoding="utf-8"?><movie><title>Keep</title></movie>',
        encoding="utf-8",
    )
    video = Video(
        path=to_file_uri(str(video_file)),
        number="ABC-123",
        title="Keep",
        original_title="",
    )
    (tmp_path / "db.sqlite").write_bytes(b"")
    calls = {}

    class FakeRepo:
        def __init__(self, _db_path):
            pass

        def get_all(self):
            return [video]

        def update_tags_if_changed(self, path, tags):
            calls["tags"] = tags
            return True

        def update_titles(self, *_args):
            return True

    monkeypatch.setattr(
        scanner_router,
        "load_config",
        lambda: {
            "sources": [
                {"id": "javbus", "enabled": True, "manual_only": False}
            ],
            "gallery": {},
        },
    )
    monkeypatch.setattr(scanner_router, "get_db_path", lambda: tmp_path / "db.sqlite")
    monkeypatch.setattr(scanner_router, "VideoRepository", FakeRepo)
    monkeypatch.setattr(scanner_router, "get_javbus_lang", lambda: "zh-tw")
    monkeypatch.setattr(
        scanner_router,
        "search_jav",
        lambda *_args, **_kwargs: {"tags": ["剧情"]},
    )
    monkeypatch.setattr(
        scanner_router,
        "readonly_source_prefixes",
        lambda *_args, **_kwargs: set(),
    )
    monkeypatch.setattr(
        scanner_router,
        "writable_source_prefixes",
        lambda *_args, **_kwargs: set(),
    )

    events = _sse_payloads(
        scanner_router.generate_tag_source_update("javbus")
    )

    assert events[-1]["type"] == "done"
    assert calls["tags"] == ["剧情", "中文字幕"]


def test_batch_tag_source_preview_does_not_write(tmp_path, monkeypatch):
    video_file = tmp_path / "ABC-124.mp4"
    video_file.write_bytes(b"video")
    nfo = tmp_path / "ABC-124.nfo"
    original_nfo = (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<movie><title>Keep</title><tag>old</tag><genre>old</genre></movie>"
    )
    nfo.write_text(original_nfo, encoding="utf-8")
    video = Video(
        path=to_file_uri(str(video_file)),
        number="ABC-124",
        title="Keep",
        original_title="",
        tags=["old"],
    )
    (tmp_path / "db.sqlite").write_bytes(b"")

    class FakeRepo:
        def __init__(self, _db_path):
            pass

        def get_all(self):
            return [video]

        def update_tags_if_changed(self, *_args):
            raise AssertionError("preview must not update the database")

        def update_titles(self, *_args):
            raise AssertionError("preview must not update NFO mtime")

    monkeypatch.setattr(
        scanner_router,
        "load_config",
        lambda: {
            "sources": [
                {"id": "javbus", "enabled": True, "manual_only": False}
            ],
            "gallery": {},
        },
    )
    monkeypatch.setattr(scanner_router, "get_db_path", lambda: tmp_path / "db.sqlite")
    monkeypatch.setattr(scanner_router, "VideoRepository", FakeRepo)
    monkeypatch.setattr(scanner_router, "get_javbus_lang", lambda: "zh-tw")
    monkeypatch.setattr(
        scanner_router,
        "search_jav",
        lambda *_args, **_kwargs: {"tags": ["new", "drama"]},
    )
    monkeypatch.setattr(
        scanner_router,
        "readonly_source_prefixes",
        lambda *_args, **_kwargs: set(),
    )
    monkeypatch.setattr(
        scanner_router,
        "writable_source_prefixes",
        lambda *_args, **_kwargs: set(),
    )

    events = _sse_payloads(
        scanner_router.generate_tag_source_update("javbus", dry_run=True)
    )

    assert events[-1]["type"] == "done"
    assert events[-1]["preview"] is True
    assert events[-1]["summary"]["changed"] == 1
    assert events[-1]["summary"]["items"][0]["added"] == ["new", "drama"]
    assert events[-1]["summary"]["items"][0]["removed"] == ["old"]
    assert nfo.read_text(encoding="utf-8") == original_nfo
    assert not (tmp_path / "ABC-124.nfo.openaver-backup").exists()


def test_batch_tag_source_update_ignores_old_backup_option(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.responses import StreamingResponse
    video_file = tmp_path / "ABC-125.mp4"
    video_file.write_bytes(b"video")
    nfo = tmp_path / "ABC-125.nfo"
    original_nfo = (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<movie><title>Keep</title><tag>old</tag><genre>old</genre></movie>"
    )
    nfo.write_text(original_nfo, encoding="utf-8")
    video = Video(
        path=to_file_uri(str(video_file)),
        number="ABC-125",
        title="Keep",
        original_title="",
        tags=["old"],
    )
    (tmp_path / "db.sqlite").write_bytes(b"")

    class FakeRepo:
        def __init__(self, _db_path):
            pass

        def get_all(self):
            return [video]

        def update_tags_if_changed(self, _path, _tags):
            return True

        def update_titles(self, *_args):
            return True

    monkeypatch.setattr(
        scanner_router,
        "load_config",
        lambda: {
            "sources": [
                {"id": "javbus", "enabled": True, "manual_only": False}
            ],
            "gallery": {},
        },
    )
    monkeypatch.setattr(scanner_router, "get_db_path", lambda: tmp_path / "db.sqlite")
    monkeypatch.setattr(scanner_router, "VideoRepository", FakeRepo)
    monkeypatch.setattr(scanner_router, "get_javbus_lang", lambda: "zh-tw")
    monkeypatch.setattr(
        scanner_router,
        "search_jav",
        lambda *_args, **_kwargs: {"tags": ["new"]},
    )
    monkeypatch.setattr(
        scanner_router,
        "readonly_source_prefixes",
        lambda *_args, **_kwargs: set(),
    )
    monkeypatch.setattr(
        scanner_router,
        "writable_source_prefixes",
        lambda *_args, **_kwargs: set(),
    )

    backup = tmp_path / "ABC-125.nfo.openaver-backup"
    backup.write_text('User backup must be left alone', encoding='utf-8')

    async def stream(request, generate):
        import threading
        return StreamingResponse(generate(threading.Event()), media_type='text/event-stream')

    monkeypatch.setattr(scanner_router, '_cancelable_sse_response', stream)
    app = FastAPI()
    app.include_router(scanner_router.router)
    with TestClient(app) as client:
        response = client.get('/api/gallery/tag-source-update?source=javbus&backup=true')
    assert response.status_code == 200
    events = _sse_payloads(response.text.strip().split('\n\n'))
    assert events[-1]['summary']['success'] == 1
    assert backup.read_text(encoding='utf-8') == 'User backup must be left alone'
    backup.unlink()
    with TestClient(app) as client:
        response = client.get('/api/gallery/tag-source-update?source=javbus')
    assert response.status_code == 200
    assert not backup.exists()
    assert "<tag>new</tag>" in nfo.read_text(encoding="utf-8")


def test_batch_tag_source_jable_waits_for_cf_and_retries(
    tmp_path, monkeypatch
):
    video_file = tmp_path / "ABC-126.mp4"
    video_file.write_bytes(b"video")
    nfo = tmp_path / "ABC-126.nfo"
    nfo.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<movie><title>Keep</title><tag>old</tag></movie>",
        encoding="utf-8",
    )
    video = Video(
        path=to_file_uri(str(video_file)),
        number="ABC-126",
        title="Keep",
        original_title="",
        tags=["old"],
    )
    (tmp_path / "db.sqlite").write_bytes(b"")
    calls = {"search": 0, "begin": [], "ready": 0}

    class FakeRepo:
        def __init__(self, _db_path):
            pass

        def get_all(self):
            return [video]

        def update_tags_if_changed(self, _path, _tags):
            return True

        def update_titles(self, *_args):
            return True

    class FakeTransport:
        def begin_solve(self, origin, key):
            calls["begin"].append((origin, key))

        def is_ready(self, key):
            calls["ready"] += 1
            assert key == "jable"
            return True

    def fake_search(*_args, **_kwargs):
        calls["search"] += 1
        if calls["search"] == 1:
            raise CfChallengeRequired("verification required")
        return {"tags": ["new", "drama"]}

    monkeypatch.setattr(
        scanner_router,
        "load_config",
        lambda: {
            "sources": [
                {"id": "jable", "enabled": False, "manual_only": True}
            ],
            "gallery": {},
        },
    )
    monkeypatch.setattr(scanner_router, "get_db_path", lambda: tmp_path / "db.sqlite")
    monkeypatch.setattr(scanner_router, "VideoRepository", FakeRepo)
    monkeypatch.setattr(scanner_router, "get_javbus_lang", lambda: "zh-tw")
    monkeypatch.setattr(scanner_router, "search_jav", fake_search)
    monkeypatch.setattr(
        scanner_router, "get_cf_transport", lambda: FakeTransport()
    )
    monkeypatch.setattr(
        scanner_router,
        "readonly_source_prefixes",
        lambda *_args, **_kwargs: set(),
    )
    monkeypatch.setattr(
        scanner_router,
        "writable_source_prefixes",
        lambda *_args, **_kwargs: set(),
    )

    events = _sse_payloads(
        scanner_router.generate_tag_source_update("jable")
    )

    assert calls["search"] == 2
    assert calls["begin"] == [("https://jable.tv/", "jable")]
    assert calls["ready"] == 1
    assert any(event["type"] == "progress" for event in events)
    assert events[-1]["type"] == "done"
    assert events[-1]["summary"]["success"] == 1
    assert "<tag>new</tag>" in nfo.read_text(encoding="utf-8")
