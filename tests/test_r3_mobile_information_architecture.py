from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "app/src/main/python/web"
LOCALES = ROOT / "app/src/main/python/locales"
ANDROID = ROOT / "app/src/main"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_settings_exposes_five_panels_without_splitting_the_form():
    template = read(WEB / "templates/settings.html")
    state = read(WEB / "static/js/pages/settings/state-config.js")
    helper = read(WEB / "static/js/pages/settings/settings-tabs.js")

    assert template.count('<form id="settingsForm"') == 1
    form_start = template.index('<form id="settingsForm"')
    form_end = template.index("</form>", form_start)
    for panel in ("sources", "naming", "gallery", "ai", "system"):
        assert f'data-settings-panel="{panel}"' in template
        assert f"'{panel}'" in helper
    for field in (
        'id="translateProvider"',
        'id="filenameFormat"',
        'id="avlistSort"',
        'id="defaultPage"',
    ):
        position = template.index(field)
        assert form_start < position < form_end

    assert "resolveSettingsTab" in state
    assert "selectSettingsTab" in state
    assert "revealInvalidSettingsTab" in state
    assert "localStorage" in helper


def test_help_has_three_tabs_and_mobile_route_aliases():
    template = read(WEB / "templates/help_mobile.html")
    script = read(WEB / "static/js/pages/help/help-tabs.js")
    css = read(WEB / "static/css/pages/help-mobile.css")

    for tab in ("library", "organize", "manual"):
        assert f'data-help-tab="{tab}"' in template
        assert f'data-help-panel="{tab}"' in template
    assert "/static/js/pages/help/help-tabs.js" in template
    assert "organize: 'organize'" in script
    assert "raw.startsWith('mobile-help-')" in script
    assert ".mobile-help-tab-panel[hidden]" in css
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in css


def test_tutorial_uses_four_mobile_flow_steps():
    tutorial = read(WEB / "static/js/components/tutorial.js")
    base = read(WEB / "templates/base.html")
    scanner = read(WEB / "templates/scanner.html")

    assert "tutorial.step" not in tutorial
    for step in range(1, 5):
        assert f"tutorial.flow.s{step}_" in tutorial
    assert "#mobileMenuButton" in tutorial
    assert "/help#organize" in tutorial
    assert (
        '<script type="module" src="/static/js/components/tutorial.js"></script>'
        in base
    )
    assert (
        '<link href="/static/css/components/tutorial.css" rel="stylesheet">'
        in scanner
    )


def test_korean_locale_and_android_resources_are_complete():
    locale_data = {}
    for path in LOCALES.glob("*.json"):
        locale_data[path.stem] = json.loads(read(path))

    assert set(locale_data) == {"en", "ja", "ko", "zh_CN", "zh_TW"}
    for data in locale_data.values():
        assert data["common"]["locale"]["ko"] == "한"
        assert data["settings"]["tabs"]["naming"]
        assert set(data["help"]["tabs"]) == {"library", "organize", "manual"}
        assert set(data["tutorial"]["flow"]) >= {
            "s1_title",
            "s1_content",
            "s2_title",
            "s2_content",
            "s3_title",
            "s3_content",
            "s4_title",
            "s4_content",
            "s4_more",
            "s4_more_link",
        }

    base = ET.parse(ANDROID / "res/values-zh/strings.xml").getroot()
    korean = ET.parse(ANDROID / "res/values-ko/strings.xml").getroot()
    assert {node.attrib["name"] for node in korean.findall("string")} == {
        node.attrib["name"] for node in base.findall("string")
    }
    assert '"ko"' in read(ANDROID / "java/dev/openaver/mobile/MainActivity.java")
