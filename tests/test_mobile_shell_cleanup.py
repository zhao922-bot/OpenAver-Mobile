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
    assert "position: static;" not in css
    assert "justify-content: center;" in css


def test_mobile_settings_keeps_appearance_bar_sticky_and_uses_manual_save():
    css = (
        ROOT
        / "app/src/main/python/web/static/css/pages/settings.css"
    ).read_text(encoding="utf-8")
    base = (
        ROOT
        / "app/src/main/python/web/templates/base.html"
    ).read_text(encoding="utf-8")
    state = (
        ROOT
        / "app/src/main/python/web/static/js/pages/settings/state-config.js"
    ).read_text(encoding="utf-8")
    settings = (
        ROOT
        / "app/src/main/python/web/templates/settings.html"
    ).read_text(encoding="utf-8")

    mobile_block = css.split("@media (max-width: 768px)", 1)[1]
    assert "position: sticky;" in mobile_block
    assert "top: var(--mobile-topbar-height);" in mobile_block
    assert "settings-mobile-save" in css
    assert "#settings-components .save-btn-wrapper" in mobile_block
    assert "display: none;" in mobile_block
    assert "getElementById('settings-components')" in base
    assert "fontSize: 'md'" in state
    assert "setFontSize(size)" in state
    assert 'form="settingsForm"' in settings
    assert "settings-mobile-save" in settings
    assert "form.fontSize === s.k" in settings
    assert "previousFontSize" in state
    assert "locale: (window.__locale || 'zh-CN')" in state
    assert "font_size: this.form.fontSize" in state
    assert "locale: this.form.locale" in state
    assert "this.saveConfig()" not in state
    assert "_sourceSnapshot()" in state
    assert "JSON.stringify(this._sourceSnapshot())" in state
    assert "available: s.available" not in state.split("_sourceSnapshot()", 1)[1].split("},", 1)[0]
    assert "prevMetatubeEnabled" in state
    assert "await this.metatubeDisconnect();" in state
    assert "onMetatubeEnabledChange" not in state
    assert "onMetatubeEnabledChange" not in settings
    assert "focalAutoEnabled: true" in state
    assert "config.focal_device?.disabled !== true" in state
    assert "_saveFocalDeviceDisabled" in state
    assert "setFocalDeviceDisabled($event)" not in settings


def test_mobile_settings_appearance_bar_stays_compact_at_large_font_sizes():
    css = (
        ROOT
        / "app/src/main/python/web/static/css/pages/settings.css"
    ).read_text(encoding="utf-8")
    settings = (
        ROOT
        / "app/src/main/python/web/templates/settings.html"
    ).read_text(encoding="utf-8")

    assert "settings-appearance-controls" in settings
    assert "settings-appearance-controls" in css
    assert "{xs:'11px',sm:'12px',md:'14px',lg:'16px',xl:'18px'}" in settings
    assert "window.Alpine.$data(document.documentElement)" in (
        ROOT
        / "app/src/main/python/web/static/js/pages/settings/state-config.js"
    ).read_text(encoding="utf-8")
    assert "flex: 0 0 34px;" in css
    assert "width: 34px;" in css
    assert "height: 40px;" in css
    assert "flex-wrap: nowrap;" in css


def test_mobile_sources_toolbar_keeps_probe_aligned_with_batch_actions():
    css = (
        ROOT
        / "app/src/main/python/web/static/css/pages/settings.css"
    ).read_text(encoding="utf-8")
    settings = (
        ROOT
        / "app/src/main/python/web/templates/settings.html"
    ).read_text(encoding="utf-8")

    assert "settings-sources-batchbar-meta" in settings
    assert "settings-sources-batchbar-meta" in css
    assert "margin-left: auto;" in css
    assert "flex: 1 0 100%;" in css
    assert "justify-content: flex-start;" in css
    assert "min-height: 38px;" in css


def test_cloudflare_webviews_are_created_lazily():
    transport = (
        ROOT
        / "app/src/main/java/dev/openaver/mobile/AndroidCfTransport.java"
    ).read_text(encoding="utf-8")
    activity = (
        ROOT
        / "app/src/main/java/dev/openaver/mobile/MainActivity.java"
    ).read_text(encoding="utf-8")

    assert "sites.put(SITE_JAVLIBRARY, createSiteView" not in transport
    assert 'sites.put("fc-javten", createSiteView' not in transport
    assert "private SiteView requireSite" in transport
    assert "SITE_CREATE_TIMEOUT_MS" in transport
    assert activity.index('openLocalPath("/scanner");') < activity.index(
        "startCfShell();",
        activity.index("applyLocalAuthCookie"),
    )


def test_webview_renderer_death_is_handled_without_killing_the_app():
    activity = (
        ROOT
        / "app/src/main/java/dev/openaver/mobile/MainActivity.java"
    ).read_text(encoding="utf-8")
    transport = (
        ROOT
        / "app/src/main/java/dev/openaver/mobile/AndroidCfTransport.java"
    ).read_text(encoding="utf-8")

    assert "public boolean onRenderProcessGone(" in activity
    assert "recoverWebView(view, detail);" in activity
    assert "webView = new WebView(this);" in activity
    assert "deadView.destroy();" in activity
    assert "return true;" in activity

    assert "public boolean onRenderProcessGone(" in transport
    assert "destroySite(this, true)" in transport
    assert "failPendingFetches(message)" in transport


def test_showcase_uses_server_page_with_full_fetch_fallback():
    state = (
        ROOT
        / "app/src/main/python/web/static/js/pages/showcase/state-videos.js"
    ).read_text(encoding="utf-8")
    base_state = (
        ROOT
        / "app/src/main/python/web/static/js/pages/showcase/state-base.js"
    ).read_text(encoding="utf-8")
    lightbox = (
        ROOT
        / "app/src/main/python/web/static/js/pages/showcase/state-lightbox.js"
    ).read_text(encoding="utf-8")

    assert "params.set('paged', 'true')" in state
    assert "async _ensureFullVideos()" in state
    assert "if (this._serverPaged && !this._fullVideosLoaded" in state
    assert "SHOWCASE_MAX_SERVER_PAGE_SIZE = 500" in base_state
    assert "all: this._shouldLoadAllVideosForInitialFetch()" in base_state
    assert "_shouldLoadAllVideosForInitialFetch() {" in state
    assert "SHOWCASE_MAX_SERVER_PAGE_SIZE" in state
    assert "new AbortController()" in state
    assert "requestId !== this._videoFetchGeneration" in state
    assert "serverPage.forEach(_recomputeCardActorAges)" in state
    assert "this._videoFetchAbort?.abort();" in base_state
    assert "async openLightbox(index)" in lightbox
    assert "await this._ensureFullVideos();" in lightbox


def test_heavy_motion_assets_are_page_gated():
    base = (
        ROOT
        / "app/src/main/python/web/templates/base.html"
    ).read_text(encoding="utf-8")

    assert "{% set uses_gsap = page in" in base
    assert "{% if uses_motion_plugins %}" in base
    assert "{% if uses_ghost_fly %}" in base
    assert "{% if uses_burst_picker %}" in base
    assert "{% if page == 'insights' %}" in base


def test_lightweight_motion_pages_share_runtime_without_heavy_plugins():
    base = (
        ROOT
        / "app/src/main/python/web/templates/base.html"
    ).read_text(encoding="utf-8")

    runtime_block = base.split("{% if uses_gsap %}", 1)[1].split("{% endif %}", 1)[0]
    plugin_block = base.split("{% if uses_motion_plugins %}", 1)[1].split("{% endif %}", 1)[0]

    assert "/static/vendor/gsap/gsap.min.js" in runtime_block
    assert "/static/vendor/gsap/CustomEase.min.js" in runtime_block
    assert "/static/vendor/gsap/Flip.min.js" not in runtime_block
    assert "/static/vendor/gsap/Flip.min.js" in plugin_block
    assert "/static/vendor/gsap/Physics2DPlugin.min.js" in plugin_block
    assert "/static/vendor/gsap/CustomBounce.min.js" in plugin_block
    assert "/static/vendor/gsap/DrawSVGPlugin.min.js" in plugin_block
    assert "{% if uses_gsap %}\n    <!-- Motion Adapter" in base
