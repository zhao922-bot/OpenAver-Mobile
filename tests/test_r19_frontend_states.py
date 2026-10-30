import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_WEB = ROOT / "app/src/main/python/web"
LOCALES = ROOT / "app/src/main/python/locales"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_shared_ui_state_covers_required_states():
    script = read(PYTHON_WEB / "static/js/shared/ui-state.js")

    for state in (
        "loading",
        "empty",
        "offline",
        "timeout",
        "permissionRequired",
        "partialSuccess",
        "unreachable",
        "error",
    ):
        assert state in script

    assert "copyError" in script
    assert "diagnostics" in script
    assert "sourceReasonLabel" in script


def test_error_card_has_required_sections_and_actions():
    macro = read(PYTHON_WEB / "templates/_macros/ui_state.html")

    assert "ui_state.what_happened" in macro
    assert "ui_state.scope_label" in macro
    assert "ui_state.suggestion_label" in macro
    assert "ui_state.details" in macro
    assert "ui_state.copy_log" in macro
    assert "OpenAverUIState.copyError" in macro


def test_primary_pages_use_shared_state_components():
    for page in ("showcase.html", "search.html", "scanner.html", "settings.html"):
        template = read(PYTHON_WEB / "templates" / page)
        assert "from '_macros/ui_state.html' import" in template
        assert "state_toast()" in template

    showcase = read(PYTHON_WEB / "templates/showcase.html")
    search = read(PYTHON_WEB / "templates/search.html")
    scanner = read(PYTHON_WEB / "templates/scanner.html")
    settings = read(PYTHON_WEB / "templates/settings.html")

    assert "state_error_card(" in showcase
    assert "state_error_card(" in search
    assert "state_error_card(" in scanner
    assert "state_error_card(" in settings
    assert "ui-source-status" in showcase
    assert "ui-partial-banner" in search
    assert "ui-task-summary" in scanner
    assert "scanner-generate-inline" in scanner
    assert "_configError" in settings


def test_mobile_touch_targets_and_title_clamps_are_declared():
    css = read(PYTHON_WEB / "static/css/components/mobile-ui.css")

    assert "--ui-touch-target: 48px" in css
    assert "min-height: var(--ui-touch-target)" in css
    assert "-webkit-line-clamp: 2" in css
    assert "-webkit-line-clamp: 3" in css
    assert "--spotlight-left-slot: 7rem" in css
    assert "--spotlight-right-slot: 3.5rem" in css
    assert '[data-action-units="2"]' in css
    assert "margin-inline: 0" in css
    assert ".player-title" in css
    assert ".ui-state-card__actions" in css
    assert "prefers-reduced-motion" in css


def test_search_mobile_layout_does_not_overflow_and_uses_short_placeholder():
    css = read(PYTHON_WEB / "static/css/components/mobile-ui.css")
    template = read(PYTHON_WEB / "templates/search.html")

    assert ".result-area > .ui-state-card" in css
    assert "flex: 0 0 100%" in css
    assert "max-width: 100%" in css
    assert "data-action-units" in template
    assert "search.placeholder.query_mobile" in template

    for locale in LOCALES.glob("*.json"):
        data = json.loads(read(locale))
        assert data["search"]["placeholder"]["query_mobile"], locale.name


def test_back_navigation_consumes_page_layers_before_history():
    script = read(PYTHON_WEB / "static/js/components/mobile-back.js")

    assert "sampleGalleryOpen" in script
    assert "lightboxOpen" in script
    assert "switchToSearchList" in script
    assert "page.displayMode = 'grid'" in script
    assert "page.clearAll()" in script
    assert "return true only when this call consumed one visible layer" in script


def test_floating_handle_snaps_and_respects_safe_inset():
    activity = read(ROOT / "app/src/main/java/dev/openaver/mobile/MainActivity.java")
    layout = read(ROOT / "app/src/main/res/layout/activity_main.xml")

    assert "MENU_HANDLE_IDLE_MS" in activity
    assert "MENU_HANDLE_VERTICAL_SAFE_INSET_DP" in activity
    assert "snapMenuHandleToEdge" in activity
    assert "scheduleMenuHandleCollapse" in activity
    assert "translationX" in activity
    assert "TouchDelegate" in activity
    assert "bg_edge_handle_left" in activity
    assert 'android:layout_width="34dp"' in layout
    assert 'android:layout_height="64dp"' in layout


def test_ui_state_locales_are_complete_and_duplicate_free():
    required = {
        "what_happened",
        "scope_label",
        "suggestion_label",
        "details",
        "copy_log",
        "error_title",
        "partial_title",
        "offline",
        "state",
    }

    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    for path in sorted(LOCALES.glob("*.json")):
        data = json.loads(read(path), object_pairs_hook=no_duplicates)
        assert "ui_state" in data, path.name
        assert required <= set(data["ui_state"]), path.name


def test_r19_assets_are_part_of_python_patch_payload():
    generator = read(ROOT / "tools/generate_patches.py")

    for relative in (
        "web/static/css/components/mobile-ui.css",
        "web/static/js/shared/ui-state.js",
        "web/templates/_macros/ui_state.html",
        "web/static/js/components/toast-store.js",
        "web/static/js/pages/showcase/state-base.js",
    ):
        assert f'"{relative}"' in generator
