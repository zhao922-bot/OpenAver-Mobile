from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.ai_services import post_ingest, tagging
from core.ai_services.tagging_vocab import merged
from core import auto_organize
from core.user_tags_write import ApplyResult
from core.path_utils import to_file_uri
from web.routers import scraper as scraper_router


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "app/src/main/python"
WEB = PYTHON / "web"
LOCALES = PYTHON / "locales"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def leaves(value: dict, prefix: str = "") -> dict[str, str]:
    result: dict[str, str] = {}
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            result.update(leaves(child, path))
        else:
            result[path] = str(child)
    return result


def row(
    title: str,
    *,
    number: str = "ABC-123",
    cover_path: str = "file:///tmp/cover.jpg",
    maker: str = "S1",
):
    return SimpleNamespace(
        path="file:///tmp/ABC-123.mp4",
        number=number,
        title=title,
        original_title=title,
        actresses=["Actor"],
        maker=maker,
        cover_path=cover_path,
        nfo_mtime=1.0,
    )


def test_post_ingest_decisions_follow_switches_and_target_language():
    japanese = row("日本語のタイトル")
    traditional = row("這是繁體中文標題")
    english = row("An English title")
    cfg = {
        "translate": {"enabled": True},
        "ai_services": {
            "image_similar": {"enabled": True},
            "tags": {"enabled": True},
        },
        "general": {"locale": "zh-CN"},
    }

    plan = post_ingest.decide(
        cfg,
        japanese,
        skip_faces=True,
        index_ready=True,
        cover_exists=True,
    )
    assert plan.translate.run is True
    assert plan.similar.run is True
    assert plan.faces.reason == "own_trigger"
    assert plan.tags.run is True

    plan = post_ingest.decide(
        {**cfg, "general": {"locale": "zh-CN"}},
        traditional,
        skip_faces=True,
        index_ready=True,
        cover_exists=True,
    )
    assert plan.translate.run is True

    plan = post_ingest.decide(
        {**cfg, "general": {"locale": "en"}},
        english,
        skip_faces=True,
        index_ready=True,
        cover_exists=True,
        tags_already_processed=True,
    )
    assert plan.translate.run is False
    assert plan.translate.reason == "title_in_target_language"
    assert plan.tags.run is False
    assert plan.tags.reason == "already_tagged"


def test_post_ingest_is_fail_open(monkeypatch):
    monkeypatch.setattr(
        post_ingest,
        "load_config",
        lambda: (_ for _ in ()).throw(RuntimeError("config unavailable")),
    )

    post_ingest.run_after_ingest(
        "file:///tmp/ABC-123.mp4",
        route="test",
        skip_faces=True,
    )


def test_enrich_hook_only_runs_for_real_rescrape(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def capture(uri, **kwargs):
        calls.append((uri, kwargs))

    monkeypatch.setattr(post_ingest, "run_after_ingest", capture)
    uri = "file:///tmp/ABC-123.mp4"

    fill = scraper_router.EnrichRequest(
        file_path=uri,
        number="ABC-123",
        mode="fill_missing",
    )
    scraper_router._post_ingest_after_enrich(fill, uri, True)
    assert calls == []

    refresh = scraper_router.EnrichRequest(
        file_path=uri,
        number="ABC-123",
        mode="refresh_full",
        overwrite_existing=True,
        preserve_title=True,
    )
    scraper_router._post_ingest_after_enrich(refresh, uri, True)
    assert calls == [
        (
            uri,
            {
                "route": "enrich_rescrape",
                "skip_faces": True,
                "skip_translate": True,
            },
        )
    ]

    calls.clear()
    scraper_router._post_ingest_after_enrich(
        fill,
        uri,
        True,
        readonly_action="rescrape",
    )
    assert calls[0][1]["route"] == "readonly_rescrape"


def test_scrape_hook_requires_synced_database(monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        post_ingest,
        "run_after_ingest",
        lambda uri, **kwargs: calls.append((uri, kwargs)),
    )

    scraper_router._post_ingest_after_scrape(
        "/tmp/ABC-123.mp4",
        "not_linked",
        {},
    )
    assert calls == []

    scraper_router._post_ingest_after_scrape(
        "/tmp/ABC-123.mp4",
        "synced",
        {},
    )
    assert calls[0][0] == to_file_uri("/tmp/ABC-123.mp4", {})
    assert calls[0][1] == {"route": "scrape_single", "skip_faces": True}


def test_auto_organize_hook_only_after_database_sync(monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        post_ingest,
        "run_after_ingest",
        lambda uri, **kwargs: calls.append((uri, kwargs)),
    )

    auto_organize._post_ingest_after_organize(
        "not_linked",
        "/tmp/ABC-123.mp4",
        {},
    )
    assert calls == []

    auto_organize._post_ingest_after_organize(
        "synced",
        "/tmp/ABC-123.mp4",
        {},
    )
    assert calls[0][0] == to_file_uri("/tmp/ABC-123.mp4", {})
    assert calls[0][1] == {
        "route": "auto_organize",
        "skip_faces": False,
        "notify": True,
    }


def test_vision_test_prepared_shape_is_valid():
    vocab = list(merged())
    tag = vocab[0].model_name

    async def fake_vision(_conn, _system, _user, _image):
        return json.dumps({"tags": [{"tag": tag, "confidence": "high"}]})

    result = asyncio.run(
        tagging.run_vision_test(
            object(),
            vocab,
            "data:image/jpeg;base64,AA==",
            vision_fn=fake_vision,
        )
    )

    assert result["ok"] is True
    assert result["tags"] == [vocab[0].name]


def test_multipart_group_calls_vision_once_and_writes_every_member(monkeypatch):
    members = (
        SimpleNamespace(path="file:///tmp/ABC-123-cd1.mp4"),
        SimpleNamespace(path="file:///tmp/ABC-123-cd2.mp4"),
    )
    prepared = tagging._Prepared(
        cfg={"gallery": {"path_mappings": {}}},
        repo=object(),
        conn=object(),
        poster_uri="data:image/jpeg;base64,AA==",
        vocab=list(merged()),
        members=members,
        local_fs_paths=("/tmp/ABC-123-cd1.mp4", "/tmp/ABC-123-cd2.mp4"),
    )
    tag = prepared.vocab[0].model_name
    vision_calls = 0
    writes = []

    async def fake_vision(_conn, _system, _user, _image):
        nonlocal vision_calls
        vision_calls += 1
        return json.dumps({"tags": [tag]})

    def fake_apply(_repo, file_path, local_fs_path, _cfg, **kwargs):
        writes.append((file_path, local_fs_path, kwargs["ai_tagged"]))
        return ApplyResult(
            ok=True,
            user_tags=[prepared.vocab[0].name],
            added=[prepared.vocab[0].name],
        )

    monkeypatch.setattr(tagging, "_prepare", lambda *_args, **_kwargs: prepared)
    monkeypatch.setattr(tagging, "apply_user_tags", fake_apply)
    monkeypatch.setattr(tagging.tags_state, "observe_success", lambda: None)

    outcome = asyncio.run(
        tagging.tag_video(
            members[0].path,
            config=prepared.cfg,
            vision_fn=fake_vision,
        )
    )

    assert vision_calls == 1
    assert writes == [
        (members[0].path, prepared.local_fs_paths[0], True),
        (members[1].path, prepared.local_fs_paths[1], True),
    ]
    assert outcome.added == [prepared.vocab[0].name]


def test_disabled_tags_stop_before_any_model_setup(monkeypatch):
    monkeypatch.setattr(
        tagging,
        "resolve_vision_conn",
        lambda _cfg: pytest.fail("vision connection must not be resolved"),
    )

    with pytest.raises(tagging.TaggingFailure) as caught:
        tagging._prepare(
            "file:///tmp/ABC-123.mp4",
            {"ai_services": {"tags": {"enabled": False}}},
        )

    assert caught.value.reason == "disabled"


def test_ai_tag_ui_contracts_are_wired():
    settings = read(WEB / "templates/settings.html")
    settings_main = read(WEB / "static/js/pages/settings/main.js")
    state_config = read(WEB / "static/js/pages/settings/state-config.js")
    showcase = read(WEB / "templates/showcase.html")
    showcase_main = read(WEB / "static/js/pages/showcase/main.js")

    assert 'id="aiTabTags"' in settings
    assert 'id="aiPanelTags"' in settings
    assert "aiTagsPanel" in settings_main
    assert "this.form.aiTagsEnabled" in state_config
    assert "enabled: this.form.aiTagsEnabled" in state_config
    assert "window.__SHOWCASE_AI_TAGS__" in showcase
    assert "lbAiTag()" in showcase
    assert "stateLightboxAiTags" in showcase_main


def test_ai_tag_locale_subtrees_have_identical_keys_and_placeholders():
    locale_data = {
        path.name: leaves(json.loads(read(path)))
        for path in sorted(LOCALES.glob("*.json"))
    }
    prefixes = (
        "settings.ai.tags.",
        "showcase.lightbox.ai_tags_",
        "notif.ai_tags_",
    )
    filtered = {
        name: {
            key: value
            for key, value in values.items()
            if key.startswith(prefixes)
        }
        for name, values in locale_data.items()
    }
    baseline_name = "en.json"
    baseline = filtered[baseline_name]
    assert baseline

    for name, values in filtered.items():
        assert set(values) == set(baseline)
        for key in baseline:
            expected = sorted(re.findall(r"\{[^{}]+\}", baseline[key]))
            actual = sorted(re.findall(r"\{[^{}]+\}", values[key]))
            assert actual == expected, f"{name}:{key}"
