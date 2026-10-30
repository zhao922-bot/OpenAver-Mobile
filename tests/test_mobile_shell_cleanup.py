from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_android_settings_guard_desktop_only_controls():
    template = (
        ROOT
        / "app/src/main/python/web/templates/settings.html"
    ).read_text(encoding="utf-8")

    assert 'data-is-android="{{ \'true\' if is_android else \'false\' }}"' in template
    assert "{% if not is_android %}" in template
    assert "C:\\Program Files\\DAUM\\PotPlayer" in template
    assert "{% if not is_android %}" in template


def test_android_video_launcher_uses_native_scheme():
    script = (
        ROOT
        / "app/src/main/python/web/static/js/shared/video-player.js"
    ).read_text(encoding="utf-8")
    activity = (
        ROOT
        / "app/src/main/java/dev/openaver/mobile/MainActivity.java"
    ).read_text(encoding="utf-8")
    player = (
        ROOT
        / "app/src/main/java/dev/openaver/mobile/ExternalPlayer.java"
    ).read_text(encoding="utf-8")

    assert "OpenAverMobile" in script
    assert "openaver-player://play?path=" in script
    assert '"openaver-player".equals(scheme)' in activity
    assert "Intent.createChooser" in player
    assert "FLAG_GRANT_READ_URI_PERMISSION" in player


def test_mobile_scanner_hides_redundant_page_header():
    css = (
        ROOT
        / "app/src/main/python/web/static/css/pages/scanner.css"
    ).read_text(encoding="utf-8")

    mobile_block = css.split("@media (max-width: 520px)", 1)[1]
    assert ".avlist-header" in mobile_block
    assert "display: none" in mobile_block


def test_mobile_settings_hides_duplicate_title_bar():
    css = (
        ROOT
        / "app/src/main/python/web/static/css/pages/settings.css"
    ).read_text(encoding="utf-8")

    assert ".settings-header-left" in css
    assert "position: static;" in css
    assert "background: transparent;" in css
    assert "justify-content: center;" in css
