from __future__ import annotations

import json
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from core import nfo_locator
from core.database import Video, VideoRepository, init_db
from core.multipart_group import logical_video_groups
from core.path_utils import to_file_uri
from core.plot_backfill import find_missing_plot_candidates
from core.plot_writeback import fill_empty_nfo_plot
from web.routers import scanner as scanner_router


JAPANESE_SUMMARY = (
    "これは最初の段落です。\n\n"
    "これは二番目の段落で、作品の内容を詳しく説明します。"
)
CHINESE_SUMMARY = "这是第一段。\n\n这是第二段，详细说明作品内容。"


def _drain_events(generator):
    events = []
    for raw in generator:
        if raw.startswith("data: "):
            events.append(json.loads(raw[6:].strip()))
    return events


def _configure_empty_output_root(monkeypatch):
    monkeypatch.setattr(
        nfo_locator,
        "resolve_owning_output_root",
        lambda _path, _config: None,
    )


def test_missing_plot_candidates_require_existing_nfo_and_empty_plot(
    tmp_path,
    monkeypatch,
):
    _configure_empty_output_root(monkeypatch)
    existing = tmp_path / "ABC-101.mp4"
    existing.write_bytes(b"video")
    (tmp_path / "ABC-101.nfo").write_text(
        "<movie><plot>已有简介</plot></movie>",
        encoding="utf-8",
    )
    empty = tmp_path / "ABC-102.mp4"
    empty.write_bytes(b"video")
    (tmp_path / "ABC-102.nfo").write_text(
        "<movie><plot> </plot></movie>",
        encoding="utf-8",
    )
    no_nfo = tmp_path / "ABC-103.mp4"
    no_nfo.write_bytes(b"video")

    rows = [
        Video(
            path=to_file_uri(str(existing)),
            number="ABC-101",
            title="Existing",
        ),
        Video(
            path=to_file_uri(str(empty)),
            number="ABC-102",
            title="Empty",
        ),
        Video(
            path=to_file_uri(str(no_nfo)),
            number="ABC-103",
            title="No NFO",
        ),
    ]

    candidates = find_missing_plot_candidates(
        logical_video_groups(rows, {}),
        {},
        {},
    )

    assert len(candidates) == 1
    assert candidates[0].number == "ABC-102"
    assert candidates[0].nfo_paths == (
        str(tmp_path / "ABC-102.nfo"),
    )


def test_fill_empty_nfo_plot_never_overwrites_existing_plot(tmp_path):
    nfo = tmp_path / "ABC-104.nfo"
    original = (
        "<?xml version='1.0' encoding='utf-8'?>"
        "<movie><title>Title</title><plot>已有简介</plot></movie>"
    )
    nfo.write_text(original, encoding="utf-8")

    changed = fill_empty_nfo_plot(
        nfo,
        new_plot="不应覆盖",
        new_original="来源简介",
    )

    assert changed is False
    root = ET.fromstring(nfo.read_bytes())
    assert root.findtext("plot") == "已有简介"
    assert root.find("originalplot") is None


def test_plot_backfill_fills_translated_plot_and_original_plot(
    tmp_path,
    monkeypatch,
):
    _configure_empty_output_root(monkeypatch)
    video_path = tmp_path / "ABC-105.mp4"
    video_path.write_bytes(b"video")
    nfo_path = tmp_path / "ABC-105.nfo"
    nfo_path.write_text(
        "<movie><title>ABC-105</title><plot /></movie>",
        encoding="utf-8",
    )
    db_path = tmp_path / "openaver.db"
    init_db(db_path)
    video_uri = to_file_uri(str(video_path))
    VideoRepository(db_path).upsert(
        Video(
            path=video_uri,
            number="ABC-105",
            title="日本語タイトル",
            nfo_mtime=0,
        )
    )

    class FakeService:
        async def translate_plot_or_raise(self, plot, context):
            assert plot == JAPANESE_SUMMARY
            assert context["number"] == "ABC-105"
            return CHINESE_SUMMARY

    monkeypatch.setattr(scanner_router, "get_db_path", lambda: db_path)
    monkeypatch.setattr(
        scanner_router,
        "load_config",
        lambda: {
            "general": {"locale": "zh-CN"},
            "translate": {"enabled": True},
            "gallery": {"path_mappings": {}},
        },
    )
    monkeypatch.setattr(scanner_router, "get_javbus_lang", lambda: "zh-tw")
    monkeypatch.setattr(
        scanner_router,
        "search_jav",
        lambda *_args, **_kwargs: {"_summary": JAPANESE_SUMMARY},
    )
    monkeypatch.setattr(
        "web.routers.translate.get_translate_service",
        lambda: FakeService(),
    )

    events = _drain_events(
        scanner_router._plot_backfill_generator(threading.Event())  # noqa: SLF001
    )

    root = ET.fromstring(nfo_path.read_bytes())
    assert root.findtext("plot") == CHINESE_SUMMARY
    assert root.findtext("originalplot") == JAPANESE_SUMMARY
    assert events[-1]["summary"]["success"] == 1
    assert events[-1]["summary"]["failed"] == 0
    result = next(
        event for event in events if event.get("type") == "result-item"
    )
    assert result["updated_nfo_count"] == 1
    assert result["preview"].startswith("这是第一段")
    assert VideoRepository(db_path).get_by_path(
        video_uri
    ).nfo_mtime == pytest.approx(nfo_path.stat().st_mtime)
    assert any(
        event.get("type") == "log"
        and "这是第一段" in event.get("message", "")
        for event in events
    )


def test_multipart_plot_backfill_is_one_item_and_fills_every_empty_nfo(
    tmp_path,
    monkeypatch,
):
    _configure_empty_output_root(monkeypatch)
    db_path = tmp_path / "openaver.db"
    init_db(db_path)
    repo = VideoRepository(db_path)
    video_uris = []
    nfo_paths = []
    for part in (1, 2):
        video_path = tmp_path / f"ABC-106-cd{part}.mp4"
        video_path.write_bytes(b"video")
        nfo_path = tmp_path / f"ABC-106-cd{part}.nfo"
        nfo_path.write_text("<movie><plot /></movie>", encoding="utf-8")
        video_uri = to_file_uri(str(video_path))
        video_uris.append(video_uri)
        nfo_paths.append(nfo_path)
        repo.upsert(
            Video(
                path=video_uri,
                number="ABC-106",
                title="日本語タイトル",
            )
        )

    calls = []

    class FakeService:
        async def translate_plot_or_raise(self, plot, _context):
            return CHINESE_SUMMARY

    def fake_search(number, **_kwargs):
        calls.append(number)
        return {"_summary": JAPANESE_SUMMARY}

    monkeypatch.setattr(scanner_router, "get_db_path", lambda: db_path)
    monkeypatch.setattr(
        scanner_router,
        "load_config",
        lambda: {
            "general": {"locale": "zh-CN"},
            "translate": {"enabled": True},
            "gallery": {"path_mappings": {}},
        },
    )
    monkeypatch.setattr(scanner_router, "get_javbus_lang", lambda: "zh-tw")
    monkeypatch.setattr(scanner_router, "search_jav", fake_search)
    monkeypatch.setattr(
        "web.routers.translate.get_translate_service",
        lambda: FakeService(),
    )

    events = _drain_events(
        scanner_router._plot_backfill_generator(threading.Event())  # noqa: SLF001
    )
    result_items = [
        event for event in events if event.get("type") == "result-item"
    ]

    assert calls == ["ABC-106"]
    assert len(result_items) == 1
    assert result_items[0]["updated_nfo_count"] == 2
    for nfo_path in nfo_paths:
        root = ET.fromstring(nfo_path.read_bytes())
        assert root.findtext("plot") == CHINESE_SUMMARY
        assert root.findtext("originalplot") == JAPANESE_SUMMARY


def test_plot_backfill_frontend_contract():
    root = Path(__file__).resolve().parents[1]
    template = (
        root
        / "app/src/main/python/web/templates/scanner.html"
    ).read_text(encoding="utf-8")
    state = (
        root
        / "app/src/main/python/web/static/js/pages/scanner/state-batch.js"
    ).read_text(encoding="utf-8")
    scanner = (
        root
        / "app/src/main/python/web/routers/scanner.py"
    ).read_text(encoding="utf-8")

    assert '@router.post("/backfill-plots")' in scanner
    assert "/api/gallery/backfill-plots" in state
    assert "runPlotBackfill()" in template
    assert "plotBackfillDrilldownPayload" in template
    assert "url: '/api/gallery/backfill-plots'" in state
    assert "taskKind: 'plot-backfill'" in state
