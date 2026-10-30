import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_WEB = ROOT / "app/src/main/python/web"
LOCALES = ROOT / "app/src/main/python/locales"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_mobile_help_uses_dedicated_template():
    app = read(PYTHON_WEB / "app.py")
    template = read(PYTHON_WEB / "templates/help_mobile.html")

    assert 'template_name = "help.html" if context.get("is_desktop") else "help_mobile.html"' in app
    assert 'id="mobile-help-start"' in template
    assert 'id="mobile-help-storage"' in template
    assert 'id="mobile-help-trouble"' in template
    assert "help.mobile.about_desc" in template
    assert "https://github.com/slive777/OpenAver" in template
    assert "https://github.com/zhao922-bot/OpenAver-Mobile" in template


def test_mobile_help_removes_desktop_only_actions():
    template = read(PYTHON_WEB / "templates/help_mobile.html")
    base = read(PYTHON_WEB / "templates/base.html")
    desktop_help = read(PYTHON_WEB / "templates/help.html")

    for forbidden in (
        "t.me/",
        "checkUpdate",
        "tutorial=restart",
        "help.hero.ai_instruction",
        "help.server_mode",
        "help.shortcuts",
    ):
        assert forbidden not in template
    assert "components/tutorial.js" not in base
    assert "components/tutorial.css" not in base
    assert "btn_tutorial" not in desktop_help


def test_mobile_help_locales_are_complete():
    required = {
        "page_title",
        "title",
        "title_line1",
        "title_line2",
        "subtitle",
        "action_scan",
        "action_browse",
        "start_title",
        "step1_title",
        "step2_title",
        "step3_title",
        "step4_title",
        "storage_title",
        "tasks_title",
        "trouble_title",
        "privacy_title",
        "about_title",
        "about_desc",
        "about_upstream",
        "about_mobile",
    }

    for path in sorted(LOCALES.glob("*.json")):
        data = json.loads(read(path))
        mobile = data["help"]["mobile"]
        assert required <= set(mobile), path.name
        assert mobile["about_upstream"], path.name
        assert mobile["about_mobile"], path.name


def test_mobile_help_uses_touch_sized_controls_and_accessible_disclosure():
    css = read(PYTHON_WEB / "static/css/pages/help-mobile.css")
    template = read(PYTHON_WEB / "templates/help_mobile.html")

    assert "min-height: 3rem;" in css
    assert ".mobile-help-panel summary" in css
    assert "min-height: 4.5rem;" in css
    assert "<details" in template
    assert "<summary>" in template
    assert "@media (prefers-reduced-motion: reduce)" in css
