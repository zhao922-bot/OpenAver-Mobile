from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "app/src/main/python/web"
LOCALES = ROOT / "app/src/main/python/locales"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def leaves(value: dict, prefix: str = "") -> set[str]:
    result: set[str] = set()
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            result.update(leaves(child, path))
        else:
            result.add(path)
    return result


def test_settings_has_independent_naming_and_ai_panels():
    template = read(WEB / "templates/settings.html")
    main = read(WEB / "static/js/pages/settings/main.js")
    macro = WEB / "templates/_macros/ai_backfill_controls.html"

    for section in ("sec-search", "sec-naming", "sec-gallery", "sec-ai", "sec-system"):
        assert f'id="{section}"' in template
    for panel in ("sources", "naming", "gallery", "ai", "system"):
        assert f'data-settings-panel="{panel}"' in template

    assert 'id="aiPanelTranslate"' in template
    assert 'id="aiPanelSimilar"' in template
    assert 'id="aiPanelFaces"' in template
    assert 'id="aiTabTags"' not in template
    assert 'x-data="aiTagsPanel"' not in template
    assert 'copyAssistantPrompt' not in template
    assert 'settings-form-row--proxy' not in template
    assert 'metatubeEnableToggle' not in template
    assert 'settings-sources-section3' not in template
    assert macro.is_file()

    assert "aiServicesCard" in main
    assert "aiSimilarPanel" in main
    assert "aiFacesPanel" in main
    assert "aiTagsPanel" not in main


def test_ai_config_is_loaded_saved_and_tags_are_preserved():
    state = read(WEB / "static/js/pages/settings/state-config.js")

    for field in (
        "aiSimilarEnabled",
        "aiSimilarUrl",
        "aiSimilarApiKey",
        "aiSimilarModel",
        "aiFacesEnabled",
        "aiFacesUrl",
        "aiFacesApiKey",
        "aiFacesModel",
    ):
        assert state.count(field) >= 2

    assert "config.ai_services?.image_similar" in state
    assert "config.ai_services?.faces" in state
    assert "tags: { ...(config.ai_services?.tags || {}) }" in state


def test_ai_locales_are_complete_and_mobile_omits_tags():
    locale_leaves: dict[str, set[str]] = {}
    for path in LOCALES.glob("*.json"):
        data = json.loads(read(path))
        ai = data["settings"]["ai"]
        assert {"backfill", "faces", "similar", "title", "tab_translate"} <= set(ai)
        assert "tags" not in ai
        assert "tab_tags" not in ai
        locale_leaves[path.name] = leaves(data)

    baseline = locale_leaves["en.json"]
    assert all(value == baseline for value in locale_leaves.values())


def test_mobile_settings_layout_and_background_tasks_are_stable():
    css = read(WEB / "static/css/pages/settings.css")
    keepalive = read(WEB / "static/js/shared/task-keepalive.js")
    backfill = read(WEB / "static/js/pages/settings/ai-backfill-controls.js")

    assert "grid-template-columns: repeat(5, minmax(0, 1fr))" in css
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in css
    appearance = css[
        css.index("#settings-components[data-is-android=\"true\"] .settings-appearance-controls"):
        css.index("/* quick-toggle-row", css.index("#settings-components[data-is-android=\"true\"] .settings-appearance-controls"))
    ]
    assert "width: 100%;" in appearance
    assert "justify-content: center;" in appearance
    font_button = css[
        css.index("#settings-components .settings-header-actions .font-size-btn"):
        css.index("#settings-components .settings-header-actions .settings-locale-toggle")
    ]
    assert "flex: 0 0 34px;" in font_button
    font_button_base = css[
        css.index(".font-size-btn {"):
        css.index(".font-size-btn:hover")
    ]
    assert "align-items: center;" in font_button_base
    assert "justify-content: center;" in font_button_base
    assert "overflow-x: auto" not in css[css.index(".settings-tabs {"):css.index(".settings-tab {")]
    assert "pagehide" not in keepalive
    assert "owners" in keepalive
    assert "syncTaskKeepAlive" in backfill
    assert "ai-backfill:${adapter.tab}" in backfill


def test_mobile_naming_toggles_are_inside_the_naming_card():
    template = read(WEB / "templates/settings.html")
    start = template.index('<section id="sec-naming"')
    end = template.index("</section><!-- /sec-naming -->", start)
    naming = template[start:end]

    assert "settings-quick-toggle-row--embedded" in naming
    assert "form.downloadSampleImages" in naming
    assert "form.thumbnailCacheEnabled" in naming


def test_mobile_ai_faces_copy_uses_phone_wording():
    expected = {
        "en.json": "this phone's processing-power limits",
        "ja.json": "この端末の処理能力",
        "ko.json": "휴대폰의 컴퓨팅 제한",
        "zh_CN.json": "手机的算力限制",
        "zh_TW.json": "手機的算力限制",
    }
    banned = {
        "en.json": "this computer's processing-power limits",
        "ja.json": "このパソコンの処理能力",
        "ko.json": "이 컴퓨터의 컴퓨팅 제한",
        "zh_CN.json": "这台电脑的算力限制",
        "zh_TW.json": "這台電腦的算力限制",
    }

    for name, phrase in expected.items():
        text = json.loads(read(LOCALES / name))["settings"]["ai"]["faces"]["empty_desc"]
        assert phrase in text
        assert banned[name] not in text


def test_mobile_inbox_example_uses_android_storage_path():
    for path in LOCALES.glob("*.json"):
        text = json.loads(read(path))["settings"]["search"]["favorite_folder_example_prefix"]
        assert "/sdcard/Download" in text
        assert "C:\\Users\\" not in text
