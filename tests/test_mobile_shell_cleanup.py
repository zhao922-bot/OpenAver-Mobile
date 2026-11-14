import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_android_settings_have_no_desktop_only_controls():
    template = (
        ROOT
        / "app/src/main/python/web/templates/settings.html"
    ).read_text(encoding="utf-8")
    state = (
        ROOT
        / "app/src/main/python/web/static/js/pages/settings/state-config.js"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "{% if not is_android %}",
        "C:\\Program Files\\DAUM\\PotPlayer",
        "shell-client",
        "local-machine",
        "localMachineState",
        "shellMode",
        "serverModeConfirmOpen",
    ):
        assert forbidden not in template
    for forbidden in (
        "@/shared/shell-client.js",
        "@/settings/local-machine.js",
        "localMachineState",
        "shellMode",
        "window.pywebview",
    ):
        assert forbidden not in state


def test_desktop_shell_routes_and_pages_are_removed():
    app = (
        ROOT
        / "app/src/main/python/web/app.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "from web.routers import client",
        "from web.routers import cf_shell",
        "client_router.router",
        "cf_shell_router.router",
        '@app.get("/connect")',
        '@app.get("/updater")',
        '@app.get("/scraper")',
        "/api/check-update",
        "/api/install-context",
        "/api/trigger-update",
    ):
        assert forbidden not in app

    for relative in (
        "web/routers/client.py",
        "web/routers/cf_shell.py",
        "web/templates/connect.html",
        "web/templates/help.html",
        "web/templates/updater.html",
        "web/templates/scraper.html",
        "web/static/js/pages/help.js",
        "web/static/js/pages/connect/main.js",
        "web/static/js/pages/connect/connect-logic.js",
        "web/static/css/pages/connect.css",
        "web/static/js/shared/shell-client.js",
        "web/static/js/shared/shell-notice.js",
        "web/static/js/shared/shell-reload.js",
        "web/static/js/shared/conn-state.js",
        "web/static/js/shared/bridge-notify.js",
        "web/static/js/pages/settings/local-machine.js",
        "core/client_connect.py",
        "core/client_settings.py",
        "core/client_sources.py",
        "core/path_translate.py",
        "core/self_update.py",
    ):
        assert not (ROOT / "app/src/main/python" / relative).exists(), relative

    assert not (
        ROOT / "app/src/main/java/dev/openaver/mobile/ServerProbe.java"
    ).exists()
    assert not (
        ROOT / "app/src/main/java/dev/openaver/mobile/CfShellAgent.java"
    ).exists()
    assert (
        ROOT / "app/src/main/python/web/routers/cf_mobile.py"
    ).exists()
    assert "web.routers import cf_mobile" in app
    assert (
        ROOT / "app/src/main/java/dev/openaver/mobile/CfMobileAgent.java"
    ).exists()


def test_patch_generator_records_desktop_removals():
    generator = (
        ROOT / "tools/generate_patches.py"
    ).read_text(encoding="utf-8")

    assert "013-remove-desktop-runtime-and-pages.patch" in generator
    for relative in (
        "core/client_connect.py",
        "core/client_settings.py",
        "core/client_sources.py",
        "core/path_translate.py",
        "core/self_update.py",
        "web/routers/client.py",
        "web/routers/cf_shell.py",
        "web/templates/connect.html",
        "web/templates/help.html",
        "web/templates/scraper.html",
        "web/templates/updater.html",
        "web/static/js/pages/connect/main.js",
        "web/static/js/pages/help.js",
        "web/static/js/pages/settings/local-machine.js",
        "web/static/js/shared/shell-client.js",
        "web/static/js/shared/shell-notice.js",
        "web/static/js/shared/shell-reload.js",
        "web/static/js/shared/conn-state.js",
        "web/static/js/shared/bridge-notify.js",
    ):
        assert f'"{relative}"' in generator


def test_pages_do_not_load_desktop_shell_assets_or_shell_state():
    base = (
        ROOT
        / "app/src/main/python/web/templates/base.html"
    ).read_text(encoding="utf-8")
    bootstrap = (
        ROOT
        / "app/src/main/python/web/templates/_advanced_search_bootstrap.html"
    ).read_text(encoding="utf-8")
    rescrape = (
        ROOT
        / "app/src/main/python/web/static/js/shared/state-rescrape.js"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "shell-notice.js",
        "shell-reload.js",
        "conn-state.js",
        "@/connect/",
        "nav-link--conn",
        "oa_shell",
        "oa_mode",
    ):
        assert forbidden not in base
    assert "in_shell" not in bootstrap
    assert "inShell" not in rescrape


def test_no_untracked_pywebview_residue_in_mobile_web_or_java():
    roots = (
        ROOT / "app/src/main/python/web",
        ROOT / "app/src/main/java",
    )
    forbidden = (
        "pywebview",
        "shell-client",
        "local-machine",
        "shell-notice",
        "shell-reload",
        "conn-state",
    )
    findings = []
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or "vendor" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            lowered = text.lower()
            for needle in forbidden:
                if needle in lowered:
                    findings.append(f"{path.relative_to(ROOT)}: {needle}")
    assert findings == []


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


def test_single_video_offers_builtin_player_choice():
    player = (
        ROOT
        / "app/src/main/java/dev/openaver/mobile/ExternalPlayer.java"
    ).read_text(encoding="utf-8")

    assert "showPlayerChoice(activity, selectedPart, fallback);" in player
    assert "R.string.play_with_external_player" in player
    assert "R.string.play_in_builtin_player" in player
    assert "fallback.open(part.path, part.number);" in player


def test_native_dialogs_use_the_open_aver_theme():
    activity = (
        ROOT
        / "app/src/main/java/dev/openaver/mobile/MainActivity.java"
    ).read_text(encoding="utf-8")
    player = (
        ROOT
        / "app/src/main/java/dev/openaver/mobile/ExternalPlayer.java"
    ).read_text(encoding="utf-8")
    themes = (
        ROOT
        / "app/src/main/res/values/themes.xml"
    ).read_text(encoding="utf-8")

    assert "Theme.OpenAverMobile.Dialog" in themes
    assert activity.count("NativeUiTheme.dialogStyle(MainActivity.this)") == 3
    assert player.count("NativeUiTheme.dialogStyle(activity)") == 3
    assert "android.R.style.Theme_Material_Dialog_Alert" not in activity
    assert "android.R.style.Theme_Material_Dialog_Alert" not in player


def test_android_tasks_use_foreground_keepalive_and_do_not_pause_webview():
    service = (
        ROOT
        / "app/src/main/java/dev/openaver/mobile/TaskKeepAliveService.java"
    ).read_text(encoding="utf-8")
    activity = (
        ROOT
        / "app/src/main/java/dev/openaver/mobile/MainActivity.java"
    ).read_text(encoding="utf-8")
    manifest = (
        ROOT
        / "app/src/main/AndroidManifest.xml"
    ).read_text(encoding="utf-8")
    keepalive = (
        ROOT
        / "app/src/main/python/web/static/js/shared/task-keepalive.js"
    ).read_text(encoding="utf-8")
    scanner = (
        ROOT
        / "app/src/main/python/web/static/js/pages/scanner/state-scan.js"
    ).read_text(encoding="utf-8")
    base = (
        ROOT
        / "app/src/main/python/web/templates/base.html"
    ).read_text(encoding="utf-8")

    assert service.index("startForeground(NOTIFICATION_ID, buildNotification());") < (
        service.index("running = true;")
    )
    assert "return START_NOT_STICKY;" in service
    assert "running = false;" in service
    assert "TaskKeepAliveService.isRunning()" in activity
    assert "if (webView != null && !TaskKeepAliveService.isRunning())" in activity
    assert '"openaver-task".equals(scheme)' in activity
    assert 'android.permission.FOREGROUND_SERVICE' in manifest
    assert 'android.permission.POST_NOTIFICATIONS' in manifest
    assert 'android:name=".TaskKeepAliveService"' in manifest
    assert 'android:foregroundServiceType="dataSync"' in manifest
    assert "window.__openaverTaskKeepAlive" in keepalive
    assert service.index("createNotificationChannel(context);") < (
        service.index("startNow(context);")
    )
    assert "EXTRA_LABEL" not in service
    assert 'getQueryParameter("label")' not in activity
    assert "requestPermissions(" not in service
    assert "openaver-task://start" in keepalive
    assert "window.__openaverTaskKeepAlive.start()" in scanner
    assert "window.__openaverTaskKeepAlive.stop()" in scanner
    assert "/static/js/shared/task-keepalive.js" in base


def test_database_restore_is_available_in_android_settings():
    settings = (
        ROOT
        / "app/src/main/python/web/templates/settings.html"
    ).read_text(encoding="utf-8")
    main = (
        ROOT
        / "app/src/main/python/web/static/js/pages/settings/main.js"
    ).read_text(encoding="utf-8")
    state = (
        ROOT
        / "app/src/main/python/web/static/js/pages/settings/state-database.js"
    ).read_text(encoding="utf-8")

    assert "settings.system.database_restore_label" in settings
    assert 'accept=".zip,application/zip"' in settings
    assert "restoreDatabase($event)" in settings
    assert "stateDatabase()" in main
    assert "fetch('/api/database/import'" in state
    assert "window.confirm" in state


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
    assert "gap: clamp(8px, 3vw, 14px);" in css
    assert "width: fit-content;" in css
    assert "margin-inline: auto;" in css
    assert "justify-self: center;" in css
    assert "display: grid;" in css
    assert "grid-template-columns: 2.5rem max-content 2.5rem;" in css
    assert "justify-items: center;" in css
    assert "settings-appearance-controls .settings-locale-toggle" in css
    assert "settings-appearance-controls .font-size-control" in css
    assert "height: 48px;" in css
    assert "settings-appearance-controls .settings-theme-toggle" in css
    assert (
        settings.index('class="settings-locale-toggle"')
        < settings.index('class="font-size-control"')
        < settings.index('class="settings-theme-toggle"')
    )


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
        "startCfMobile();",
        activity.index("applyLocalAuthCookie"),
    )


def test_cloudflare_transport_passes_http_404_pages_to_scrapers():
    transport = (
        ROOT
        / "app/src/main/java/dev/openaver/mobile/AndroidCfTransport.java"
    ).read_text(encoding="utf-8")

    assert "if (status >= 500)" in transport
    assert "if (status >= 400)" not in transport
    assert "Jable returns 404" in transport


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


def test_demo_subsystem_is_not_shipped():
    app = (
        ROOT
        / "app/src/main/python/web/app.py"
    ).read_text(encoding="utf-8")
    patch_generator = (
        ROOT
        / "tools/generate_patches.py"
    ).read_text(encoding="utf-8")

    assert "/design-system" not in app
    assert "motion_lab" not in app
    assert not (
        ROOT / "app/src/main/python/web/routers/motion_lab.py"
    ).exists()
    assert not (
        ROOT / "app/src/main/python/web/templates/motion_lab.html"
    ).exists()
    assert not (
        ROOT / "app/src/main/python/web/templates/design-system.html"
    ).exists()
    assert not (
        ROOT / "app/src/main/python/web/static/css/pages/design-system.css"
    ).exists()
    assert not (
        ROOT / "app/src/main/python/web/static/js/pages/motion-lab.js"
    ).exists()
    assert not (
        ROOT / "app/src/main/python/web/static/js/pages/motion-lab-state.js"
    ).exists()
    assert not (
        ROOT / "app/src/main/python/web/static/img/showcase"
    ).exists()
    assert not (
        ROOT / "app/src/main/python/web/static/img/picker-demo"
    ).exists()
    assert not (
        ROOT / "app/src/main/python/web/static/img/demo"
    ).exists()
    assert "009-remove-demo-subsystem.patch" in patch_generator
    for relative in (
        "web/routers/motion_lab.py",
        "web/static/css/pages/design-system.css",
        "web/static/img/showcase/sc-1.jpg",
        "web/static/js/pages/motion-lab.js",
        "web/templates/design-system.html",
        "web/templates/motion_lab.html",
    ):
        assert f'"{relative}"' in patch_generator


def test_bootstrap_icons_are_woff2_only():
    css = (
        ROOT
        / "app/src/main/python/web/static/vendor/bootstrap-icons/bootstrap-icons.css"
    ).read_text(encoding="utf-8")
    manifest = (
        ROOT
        / "app/src/main/python/web/static/vendor/manifest.json"
    ).read_text(encoding="utf-8")
    patch_generator = (
        ROOT
        / "tools/generate_patches.py"
    ).read_text(encoding="utf-8")

    assert "bootstrap-icons.woff2" in css
    assert "bootstrap-icons.woff?" not in css
    assert not (
        ROOT
        / "app/src/main/python/web/static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff"
    ).exists()
    assert "bootstrap-icons/fonts/bootstrap-icons.woff\"" not in manifest
    assert "010-woff2-only-icons.patch" in patch_generator


def test_echarts_insights_bundle_is_reduced_and_reproducible():
    bundle = (
        ROOT
        / "app/src/main/python/web/static/vendor/echarts/echarts.min.js"
    )
    bundle_bytes = bundle.read_bytes()
    bundle_text = bundle_bytes.decode("utf-8")
    manifest = json.loads(
        (
            ROOT
            / "app/src/main/python/web/static/vendor/manifest.json"
        ).read_text(encoding="utf-8")
    )
    entry = (
        ROOT
        / "tools/echarts-build/src/insights-entry.js"
    ).read_text(encoding="utf-8")
    package = json.loads(
        (
            ROOT
            / "tools/echarts-build/package.json"
        ).read_text(encoding="utf-8")
    )
    patch_generator = (
        ROOT
        / "tools/generate_patches.py"
    ).read_text(encoding="utf-8")
    echarts = next(
        item
        for item in manifest["vendor"]
        if item["path"] == "web/static/vendor/echarts/echarts.min.js"
    )

    assert len(bundle_bytes) < 650_000
    assert bundle_text.startswith("/*! ECharts 6.1.0")
    assert hashlib.sha256(bundle_bytes).hexdigest() == echarts["local_sha256"]
    assert package["devDependencies"]["echarts"] == "6.1.0"
    for module in (
        "BarChart",
        "PieChart",
        "TreemapChart",
        "TooltipComponent",
        "UniversalTransition",
        "CanvasRenderer",
    ):
        assert module in entry
    assert "011-echarts-insights-bundle.patch" in patch_generator


def test_release_web_assets_are_minified_without_touching_sources(tmp_path):
    script_path = ROOT / "tools/minify-release-web-assets.py"
    spec = importlib.util.spec_from_file_location(
        "minify_release_web_assets",
        script_path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    build_gradle = (ROOT / "app/build.gradle").read_text(encoding="utf-8")
    base = (
        ROOT
        / "app/src/main/python/web/templates/base.html"
    ).read_text(encoding="utf-8")
    tailwind = (
        ROOT
        / "app/src/main/python/web/static/css/tailwind.css"
    ).read_text(encoding="utf-8")

    assert 'tasks.register("minifyReleaseWebAssets")' in build_gradle
    assert 'dependsOn tasks.named("generateReleasePythonBuildAssets")' in build_gradle
    assert 'if (task.name == "mergeReleaseAssets")' in build_gradle
    assert "task.dependsOn(minifyReleaseWebAssets)" in build_gradle
    assert "tools/minify-release-web-assets.py" in build_gradle
    assert "minifyDebug" not in build_gradle
    assert "npm ci --prefix tools/echarts-build" in (
        ROOT / ".github/workflows/build.yml"
    ).read_text(encoding="utf-8")
    assert "npm ci --prefix tools/echarts-build" in (
        ROOT / ".github/workflows/release.yml"
    ).read_text(encoding="utf-8")

    assert module.is_minifiable_entry("web/static/js/app.js")
    assert module.is_minifiable_entry("web/static/css/pages/home.css")
    assert not module.is_minifiable_entry("web/static/vendor/alpine/alpine.min.js")
    assert not module.is_minifiable_entry("web/templates/base.html")
    assert not module.is_minifiable_entry("core/app.py")
    assert "@tailwind" not in tailwind
    assert base.count('src="/static/vendor/alpine/alpine.min.js"') == 1
    assert base.count('src="/static/vendor/gsap/gsap.min.js"') == 1
    assert base.count('href="/static/vendor/bootstrap-icons/bootstrap-icons.css"') == 1

    archive = tmp_path / "app.imy"
    original = {
        "web/static/js/app.js": b"function longName() { return 1; }\n",
        "web/static/css/app.css": b".example { color: red; }\n",
        "web/static/vendor/alpine/alpine.min.js": b"vendor-script",
        "core/app.py": b"print('source')",
    }
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for name, data in original.items():
            output.writestr(name, data)

    replacements = {
        "web/static/js/app.js": b"function longName(){return 1}",
        "web/static/css/app.css": b".example{color:red}",
        "web/static/vendor/alpine/alpine.min.js": b"vendor",
    }
    with pytest.raises(ValueError):
        module.apply_replacements(archive, replacements)
    assert archive.read_bytes().startswith(b"PK")

    replacements.pop("web/static/vendor/alpine/alpine.min.js")
    replaced, before_bytes, after_bytes = module.apply_replacements(
        archive,
        replacements,
    )
    assert replaced == 2
    assert before_bytes > after_bytes
    with zipfile.ZipFile(archive, "r") as rewritten:
        assert rewritten.read("web/static/js/app.js") == replacements[
            "web/static/js/app.js"
        ]
        assert rewritten.read("web/static/css/app.css") == replacements[
            "web/static/css/app.css"
        ]
        assert (
            rewritten.read("web/static/vendor/alpine/alpine.min.js")
            == original["web/static/vendor/alpine/alpine.min.js"]
        )
        assert rewritten.read("core/app.py") == original["core/app.py"]
        assert rewritten.testzip() is None


def test_android_scanner_layout_keeps_localized_paths_and_actions_visible():
    scanner = (
        ROOT
        / "app/src/main/python/web/templates/scanner.html"
    ).read_text(encoding="utf-8")
    mobile_css = (
        ROOT
        / "app/src/main/python/web/static/css/components/mobile-ui.css"
    ).read_text(encoding="utf-8")

    assert 'id="scannerPage"' in scanner
    assert '[data-is-android="true"] #scannerPage .folder-item {' in mobile_css
    assert 'grid-template-areas:\n      "readonly icon remove"\n      "path path path";' in mobile_css
    assert "word-break: normal;" in mobile_css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in mobile_css
    assert "grid-column: 1 / -1;" in mobile_css


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


def test_alpine_i18n_fallbacks_escape_json_for_double_quoted_attributes():
    base = (
        ROOT
        / "app/src/main/python/web/templates/base.html"
    ).read_text(encoding="utf-8")

    for line in base.splitlines():
        if "window.t ? window.t(" in line and "|tojson" in line:
            assert "|tojson|forceescape" in line
