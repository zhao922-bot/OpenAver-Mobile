from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "app" / "src" / "main" / "python" / "web"
LOCALES = ROOT / "app" / "src" / "main" / "python" / "locales"


def _flatten(value, prefix: str = "") -> dict[str, str]:
    if not isinstance(value, dict):
        return {prefix: value}
    result = {}
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        result.update(_flatten(child, path))
    return result


def test_r4_locales_cover_new_image_and_plot_ui():
    expected = {
        "search.image.btn_title",
        "search.image.privacy_title",
        "search.image.privacy_body",
        "search.image.no_candidates",
        "search.image.match.frame",
        "search.image.in_library",
        "showcase.lightbox.plot_tooltip",
        "showcase.lightbox.plot_unavailable",
        "showcase.lightbox.plot_already_target",
        "settings.translate.openai_official",
        "settings.translate.openai_official_hint",
        "settings.status.openai_official_auth_failed",
    }
    for path in LOCALES.glob("*.json"):
        keys = set(_flatten(json.loads(path.read_text(encoding="utf-8"))))
        assert expected <= keys, path.name


def test_r4_templates_and_page_entrypoints_load_new_features():
    search = (WEB / "templates" / "search.html").read_text(encoding="utf-8")
    showcase = (WEB / "templates" / "showcase.html").read_text(encoding="utf-8")
    search_main = (WEB / "static" / "js" / "pages" / "search" / "main.js").read_text(
        encoding="utf-8"
    )
    showcase_main = (
        WEB / "static" / "js" / "pages" / "showcase" / "main.js"
    ).read_text(encoding="utf-8")

    assert "imgSearchPickFile()" in search
    assert "search.image.privacy_body" in search
    assert "searchStateImageSearch" in search_main
    assert "lbPlotToggle()" in showcase
    assert "stateLightboxPlot" in showcase_main


def test_r4_plot_api_is_registered_in_the_app():
    app_source = (WEB / "app.py").read_text(encoding="utf-8")
    assert "from web.routers import image_search as image_search_router" in app_source
    assert "from web.routers import showcase_plot as showcase_plot_router" in app_source
    assert "app.include_router(image_search_router.router)" in app_source
    assert "app.include_router(showcase_plot_router.router)" in app_source


def test_r4_plot_load_updates_the_reactive_view_not_the_raw_seed_object():
    state_source = (
        WEB
        / "static"
        / "js"
        / "pages"
        / "showcase"
        / "state-lightbox-plot.js"
    ).read_text(encoding="utf-8")
    load_source = state_source.split("async _lbPlotLoad()", 1)[1].split(
        "lbPlotToggleOriginal()", 1
    )[0]

    assert "applyPlotLoadResult(this._lbPlotView, ok, data)" in state_source
    assert "view.loading = false" not in load_source
