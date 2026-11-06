from __future__ import annotations

import json
import os
import time
import warnings

from core import config as config_module
from core.config import AppConfig
from core.source_config import SourceConfig


def test_load_config_unlocked_runs_every_migration_stage(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "avlist": {
                "directories": ["/videos"],
                "min_size_kb": 2048,
                "output_dir": "output",
            },
            "translate": {
                "ollama_url": "http://localhost:11434/",
                "ollama_model": "legacy-model",
                "auto_progressive": True,
            },
            "scraper": {
                "folder_format": "{maker}/{actor}",
            },
            "search": {
                "primary_source": "dmm",
                "proxy_url": "direct",
            },
            "advanced_search_enabled": True,
            "sources": [{"id": 123}],
        }),
        encoding="utf-8",
    )
    saved = []
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)
    monkeypatch.setattr(
        config_module,
        "_save_config_unlocked",
        lambda raw_config: saved.append(raw_config),
    )

    result = config_module._load_config_unlocked()

    assert saved == [result]
    assert "avlist" not in result
    assert result["gallery"]["directories"] == [{
        "path": "/videos",
        "readonly": False,
        "output_path": "",
    }]
    assert result["gallery"]["min_size_mb"] == 2
    assert result["gallery"]["output_dir"] == ""
    assert result["translate"]["ollama"] == {
        "url": "http://localhost:11434",
        "model": "legacy-model",
    }
    assert "auto_progressive" not in result["translate"]
    assert result["scraper"]["folder_layers"] == ["{maker}", "{actor}"]
    assert result["search"]["proxy_scope"] == "dmm"
    assert result["search"]["proxy_url"] == ""
    assert "primary_source" not in result["search"]
    assert "advanced_search_enabled" not in result
    assert result["sources_bak"] == [{"id": 123}]
    assert result["thumbnail_cache_enabled"] is False
    assert result["general"]["close_action"] == "ask"
    assert result["focal_device"]["disabled"] is False


def test_sources_migration_appends_manual_only_sources(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "sources": [],
            "search": {},
            "general": {},
            "scraper": {},
            "source_links": {},
            "thumbnail_cache_enabled": False,
            "focal_device": {},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)
    monkeypatch.setattr(
        config_module,
        "_save_config_unlocked",
        lambda raw_config: None,
    )

    result = config_module._load_config_unlocked()
    source_ids = {source["id"] for source in result["sources"]}

    assert result["sources_bak"] == []
    assert "javlibrary" in source_ids
    assert "fc-javten" in source_ids


def test_source_config_model_dump_includes_is_censored():
    """model_dump() must preserve the computed field contract on v1 and v2."""
    source = SourceConfig(
        id="dmm",
        type="builtin",
        display_name_key="DMM",
    )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert source.dict()["is_censored"] is True
    assert source.model_dump()["is_censored"] is True


def test_app_config_model_dump_includes_nested_is_censored():
    """Nested source serialization must preserve the computed field contract."""
    sources = AppConfig().model_dump()["sources"]

    assert sources
    assert all("is_censored" in source for source in sources)
    assert next(source for source in sources if source["id"] == "dmm")["is_censored"] is True


def test_add_computed_source_fields_handles_legacy_config():
    """GET /api/config must expose is_censored for old stored entries."""
    config = {
        "sources": [
            {
                "id": "dmm",
                "type": "builtin",
                "enabled": True,
                "order": 0,
                "config": {},
            },
            {
                "id": "javbus",
                "type": "builtin",
                "enabled": True,
                "order": 1,
                "config": {},
            },
        ]
    }

    result = config_module.add_computed_source_fields(config)

    assert result is config
    assert result["sources"][0]["is_censored"] is True
    assert result["sources"][1]["is_censored"] is True


def test_legacy_source_rebuild_derives_requires_proxy():
    legacy_source = {
        "id": "dmm",
        "type": "builtin",
        "display_name_key": "DMM",
        "enabled": True,
        "order": 0,
        "config": {},
        "is_beta": False,
        "manual_only": False,
    }

    rebuilt = SourceConfig.model_validate(legacy_source)

    assert rebuilt.requires_proxy is True


def test_load_config_uses_cached_snapshot_and_invalidates_on_file_change(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"marker": "first", "sources": [], "search": {}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)

    calls = 0
    original_loader = config_module._load_config_unlocked

    def counting_loader():
        nonlocal calls
        calls += 1
        return original_loader()

    monkeypatch.setattr(config_module, "_load_config_unlocked", counting_loader)

    first = config_module.load_config()
    first["marker"] = "caller-mutated"
    second = config_module.load_config()

    assert calls == 1
    assert second["marker"] == "first"

    config_path.write_text(
        json.dumps({"marker": "second", "sources": [], "search": {}}),
        encoding="utf-8",
    )
    future = time.time() + 1
    os.utime(config_path, (future, future))

    third = config_module.load_config()
    assert calls == 2
    assert third["marker"] == "second"


def test_save_config_updates_cached_snapshot(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"marker": "before", "sources": [], "search": {}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)

    config = config_module.load_config()
    config["marker"] = "after"
    config_module.save_config(config)

    monkeypatch.setattr(
        config_module,
        "_load_config_unlocked",
        lambda: (_ for _ in ()).throw(AssertionError("cache miss")),
    )

    assert config_module.load_config()["marker"] == "after"
