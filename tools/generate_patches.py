#!/usr/bin/env python3
"""Generate the Android port patch set from a clean upstream checkout.

The Android app embeds a deliberately small subset of the upstream OpenAver
tree.  This generator keeps that subset reproducible: every file changed by
the port belongs to exactly one numbered patch, and files under upstream
``__tests__`` directories are not part of the Android payload.
"""

from __future__ import annotations

import argparse
import difflib
import json
import subprocess
from pathlib import Path


UPSTREAM_RELEASE = "v0.17.18"
UPSTREAM_COMMIT = "af0d99741e63e71980773c9ade04c473407a60b7"

DEMO_SUBSYSTEM_FILES = (
    "web/routers/motion_lab.py",
    "web/static/css/pages/design-system.css",
    "web/static/img/demo/cawd-441.jpg",
    "web/static/img/demo/fc2-1723984.jpg",
    "web/static/img/demo/ipzz-001.jpg",
    "web/static/img/demo/mide-974.jpg",
    "web/static/img/demo/sone-103.jpg",
    "web/static/img/picker-demo/cand-1.jpg",
    "web/static/img/picker-demo/cand-2.jpg",
    "web/static/img/picker-demo/cand-3.jpg",
    "web/static/img/picker-demo/cand-4.jpg",
    "web/static/img/picker-demo/cover.jpg",
    "web/static/img/showcase/sc-1.jpg",
    "web/static/img/showcase/sc-2.jpg",
    "web/static/img/showcase/sc-3.jpg",
    "web/static/img/showcase/sc-4.jpg",
    "web/static/img/showcase/sc-5.jpg",
    "web/static/img/showcase/sc-6.jpg",
    "web/static/img/showcase/sc-7.jpg",
    "web/static/img/showcase/sc-8.jpg",
    "web/static/img/showcase/sc-9.jpg",
    "web/static/img/showcase/sc-10.jpg",
    "web/static/img/showcase/sc-11.jpg",
    "web/static/img/showcase/sc-12.jpg",
    "web/static/img/showcase/sc-13.jpg",
    "web/static/img/showcase/sc-14.jpg",
    "web/static/img/showcase/sc-15.jpg",
    "web/static/img/showcase/sc-16.jpg",
    "web/static/img/showcase/sc-17.jpg",
    "web/static/img/showcase/sc-18.jpg",
    "web/static/img/showcase/sc-19.jpg",
    "web/static/img/showcase/sc-20.jpg",
    "web/static/js/pages/motion-lab-state.js",
    "web/static/js/pages/motion-lab.js",
    "web/static/js/pages/motion-lab/constellation-host.js",
    "web/templates/design-system.html",
    "web/templates/design_system/gallery-components.html",
    "web/templates/design_system/page-compositions.html",
    "web/templates/design_system/page-states.html",
    "web/templates/design_system/settings-components.html",
    "web/templates/motion_lab.html",
)

GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "001-pydantic-v1-compat.patch",
        ("pydantic_v1_compat.py",),
    ),
    (
        "002-mobile-bootstrap.patch",
        (
            "openaver_boot.py",
            "web/app.py",
            "web/compression.py",
        ),
    ),
    (
        "003-android-native-focal.patch",
        (
            "core/focal/detector.py",
            "core/focal/device_state.py",
            "core/focal/subprocess_runner.py",
            "core/focal/pigo.py",
            "core/focal/worker.py",
            "core/focal_trigger.py",
        ),
    ),
    (
        "004-network-and-scraper-fallbacks.patch",
        (
            "core/cf_handoff.py",
            "core/custom_source/fetch.py",
            "core/custom_source/schema.py",
            "core/metatube/probe.py",
            "core/proxy_policy.py",
            "core/scrapers/__init__.py",
            "core/scrapers/actress/avbase.py",
            "core/scrapers/d2pass.py",
            "core/scrapers/jable.py",
            "core/scrapers/jav321.py",
            "core/scrapers/javdb.py",
            "core/scrapers/models.py",
            "core/scrapers/utils.py",
            "core/search_providers/dmm.py",
            "core/source_probe.py",
        ),
    ),
    (
        "005-android-file-writeback.patch",
        (
            "core/avscan/__init__.py",
            "core/avscan/client.py",
            "core/avscan/gate.py",
            "core/avscan/image_prep.py",
            "core/avscan/rules.py",
            "core/android_storage.py",
            "core/atomic_write.py",
            "core/cover_attributes.py",
            "core/cover_upload.py",
            "core/database/actress.py",
            "core/database/actress_library.py",
            "core/database/connection.py",
            "core/database/video.py",
            "core/database/version_tracker.py",
            "core/enricher.py",
            "core/gallery_generator.py",
            "core/gallery_scanner.py",
            "core/media_io.py",
            "core/multipart_group.py",
            "core/multipart_tokens.py",
            "core/nfo_locator.py",
            "core/nfo_utils.py",
            "core/nfo_updater.py",
            "core/organizer.py",
            "core/plot_backfill.py",
            "core/plot_writeback.py",
            "core/recent_actresses.py",
            "core/recent_rules.py",
            "core/readonly_assets.py",
            "core/rename_combined_plan.py",
            "core/rename_file_execution.py",
            "core/rename_file_plan.py",
            "core/rename_folder_plan.py",
            "core/rename_names.py",
            "core/rename_normalizer.py",
            "core/rename_shared.py",
            "core/scrapers/actress/graphis_pool.py",
            "core/source_config.py",
            "core/thumbnail_cache.py",
            "core/title_language.py",
            "core/title_language_data.py",
            "core/title_writeback.py",
        ),
    ),
    (
        "006-mobile-web-routers.patch",
        (
            "web/routers/capabilities.py",
            "web/routers/config.py",
            "web/routers/cover_badges.py",
            "web/routers/database_backup.py",
            "web/routers/gallery_media.py",
            "web/routers/image_search.py",
            "web/routers/insights.py",
            "web/routers/scanner.py",
            "web/routers/scraper.py",
            "web/routers/search.py",
            "web/routers/showcase.py",
            "web/routers/showcase_plot.py",
            "web/routers/translate.py",
        ),
    ),
    (
        "007-mobile-ui-and-localization.patch",
        (
            "core/auto_organize.py",
            "core/cloud_translate.py",
            "core/config.py",
            "core/i18n.py",
            "core/nfo_title_format.py",
            "core/openai_client.py",
            "core/readonly_producer.py",
            "core/scraper.py",
            "core/translate_service.py",
            "core/wishlist_reconcile.py",
            "locales/en.json",
            "locales/ja.json",
            "locales/ko.json",
            "locales/zh_CN.json",
            "locales/zh_TW.json",
            "web/auto_organize_scheduler.py",
            "web/config.default.json",
            "web/routers/_custom_gate.py",
            "web/routers/_custom_preview.py",
            "web/routers/access.py",
            "web/routers/actress.py",
            "web/routers/actress_alias.py",
            "web/routers/claude_translate.py",
            "web/routers/gemini.py",
            "web/routers/openai_translate.py",
            "web/routers/tag_alias.py",
            "web/routers/tags.py",
            "web/routers/wishlist.py",
            "web/static/css/input.css",
            "web/static/css/tailwind.css",
            "web/static/css/theme.css",
            "web/static/css/components/mobile-ui.css",
            "web/static/css/pages/help-mobile.css",
            "web/static/css/pages/insights.css",
            "web/static/css/pages/showcase/05-lightbox.css",
            "web/static/css/pages/showcase/06-responsive-and-lists.css",
            "web/static/css/pages/showcase/08-remainder.css",
            "web/static/css/pages/scanner.css",
            "web/static/css/pages/search.css",
            "web/static/css/pages/settings.css",
            "web/static/js/components/mobile-back.js",
            "web/static/js/components/auto-organize-panel.js",
            "web/static/js/components/number-drilldown.js",
            "web/static/js/components/page-lifecycle.js",
            "web/static/js/components/toast-store.js",
            "web/static/js/pages/insights/aggregate.js",
            "web/static/js/pages/insights/charts.js",
            "web/static/js/pages/insights/state.js",
            "web/static/js/pages/help/help-tabs.js",
            "web/static/js/pages/player.js",
            "web/static/js/pages/scanner/state-scan.js",
            "web/static/js/pages/scanner/state-batch.js",
            "web/static/js/pages/search/batch-search-rules.js",
            "web/static/js/pages/search/blank-card-rules.js",
            "web/static/js/pages/search/file.js",
            "web/static/js/pages/search/image-search-rules.js",
            "web/static/js/pages/search/state/image-search.js",
            "web/static/js/pages/search/state/advanced-picker.js",
            "web/static/js/pages/search/state/batch.js",
            "web/static/js/pages/search/state/blank-card.js",
            "web/static/js/pages/search/state/maker-latest.js",
            "web/static/js/pages/search/state/navigation.js",
            "web/static/js/pages/search/state/persistence.js",
            "web/static/js/pages/search/state/search-flow.js",
            "web/static/js/pages/search/ui.js",
            "web/static/js/pages/settings/state-config.js",
            "web/static/js/pages/settings/state-database.js",
            "web/static/js/pages/settings/state-providers.js",
            "web/static/js/pages/settings/settings-tabs.js",
            "web/static/js/pages/settings/main.js",
            "web/static/js/pages/showcase/state-actress.js",
            "web/static/js/pages/showcase/lb-plot-logic.js",
            "web/static/js/pages/showcase/state-lightbox-plot.js",
            "web/static/js/pages/showcase/state-lightbox-translate.js",
            "web/static/js/pages/showcase/state-lightbox.js",
            "web/static/js/pages/showcase/state-lightbox-picker.js",
            "web/static/js/pages/showcase/state-videos.js",
            "web/static/js/pages/showcase/state-base.js",
            "web/static/js/pages/showcase/main.js",
            "web/static/js/shared/ui-state.js",
            "web/static/js/shared/cover-badges.js",
            "web/static/js/shared/digits-only-search.js",
            "web/static/js/shared/picker-seen.js",
            "web/static/js/shared/state-toast.js",
            "web/static/js/shared/task-keepalive.js",
            "web/static/js/shared/video-player.js",
            "web/templates/_macros/ui_state.html",
            "web/templates/base.html",
            "web/templates/help_mobile.html",
            "web/templates/insights.html",
            "web/templates/scanner.html",
            "web/templates/search.html",
            "web/templates/settings.html",
            "web/templates/showcase.html",
        ),
    ),
    (
        "008-mobile-loopback-auth.patch",
        ("mobile_auth.py",),
    ),
    (
        "009-remove-demo-subsystem.patch",
        DEMO_SUBSYSTEM_FILES,
    ),
    (
        "010-woff2-only-icons.patch",
        (
            "web/static/vendor/bootstrap-icons/bootstrap-icons.css",
            "web/static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff",
        ),
    ),
    (
        "011-echarts-insights-bundle.patch",
        (
            "web/static/vendor/echarts/echarts.min.js",
            "web/static/vendor/manifest.json",
        ),
    ),
    (
        "012-bs4-html-parser.patch",
        (
            "core/custom_source/extract.py",
            "core/scrapers/dmm.py",
            "core/scrapers/fc2_javten.py",
            "core/scrapers/fc2_official.py",
            "core/scrapers/heyzo.py",
        ),
    ),
    (
        "013-remove-desktop-runtime-and-pages.patch",
        (
            "core/README.md",
            "core/cf_transport.py",
            "core/client_connect.py",
            "core/client_settings.py",
            "core/client_sources.py",
            "core/path_translate.py",
            "core/platform_info.py",
            "core/self_update.py",
            "web/routers/cf_mobile.py",
            "web/routers/cf_shell.py",
            "web/routers/client.py",
            "web/routers/diagnostics.py",
            "web/shell_identity.py",
            "web/static/css/components/fluent-materials.css",
            "web/static/css/pages/connect.css",
            "web/static/js/components/tutorial.js",
            "web/static/js/pages/connect/connect-logic.js",
            "web/static/js/pages/connect/main.js",
            "web/static/js/pages/help.js",
            "web/static/js/pages/scanner/main.js",
            "web/static/js/pages/search/main.js",
            "web/static/js/pages/search/state/base.js",
            "web/static/js/pages/search/state/file-list.js",
            "web/static/js/pages/search/state/result-card.js",
            "web/static/js/pages/settings/local-machine.js",
            "web/static/js/pages/settings/state-ui.js",
            "web/static/js/shared/bridge-notify.js",
            "web/static/js/shared/clipboard.js",
            "web/static/js/shared/conn-state.js",
            "web/static/js/shared/open-local.js",
            "web/static/js/shared/shell-client.js",
            "web/static/js/shared/shell-notice.js",
            "web/static/js/shared/shell-reload.js",
            "web/static/js/shared/state-rescrape.js",
            "web/templates/_advanced_search_bootstrap.html",
            "web/templates/access_gate.html",
            "web/templates/connect.html",
            "web/templates/help.html",
            "web/templates/scraper.html",
            "web/templates/updater.html",
        ),
    ),
    (
        "014-mobile-ai-services.patch",
        (
            "core/anthropic_client.py",
            "core/ai_services/__init__.py",
            "core/ai_services/backfill_state.py",
            "core/ai_services/embedding_cache.py",
            "core/ai_services/embeddings.py",
            "core/ai_services/faces.py",
            "core/ai_services/faces_config.py",
            "core/ai_services/faces_detect.py",
            "core/ai_services/faces_recompute.py",
            "core/ai_services/faces_state.py",
            "core/ai_services/image_prep.py",
            "core/ai_services/job_shell.py",
            "core/ai_services/samples.py",
            "core/ai_services/similar_index.py",
            "core/ai_services/similar_state.py",
            "core/ai_services/post_ingest.py",
            "core/ai_services/tagging.py",
            "core/ai_services/tagging_aliases.py",
            "core/ai_services/tagging_vocab.json",
            "core/ai_services/tagging_vocab.py",
            "core/ai_services/tags_backfill.py",
            "core/ai_services/tags_backfill_policy.py",
            "core/ai_services/tags_state.py",
            "core/ai_services/vision_chat.py",
            "core/database/__init__.py",
            "core/database/embeddings.py",
            "core/gemini_client.py",
            "core/secret_fields.py",
            "core/similar/canonicalize.py",
            "core/similar/ranker.py",
            "core/user_tags_write.py",
            "web/routers/ai_services.py",
            "web/routers/ai_tags.py",
            "web/routers/similar.py",
            "web/static/js/pages/settings/ai-backfill-controls.js",
            "web/static/js/pages/settings/ai-backfill-logic.js",
            "web/static/js/pages/settings/ai-faces-logic.js",
            "web/static/js/pages/settings/ai-faces-panel.js",
            "web/static/js/pages/settings/ai-services-card.js",
            "web/static/js/pages/settings/ai-similar-logic.js",
            "web/static/js/pages/settings/ai-similar-panel.js",
            "web/static/js/pages/settings/ai-tags-logic.js",
            "web/static/js/pages/settings/ai-tags-panel.js",
            "web/static/js/pages/showcase/lb-ai-tags-logic.js",
            "web/static/js/pages/showcase/state-lightbox-ai-tags.js",
            "web/templates/_macros/ai_backfill_controls.html",
        ),
    ),
)

PAYLOAD_ROOTS = ("core", "web", "locales")
PAYLOAD_ROOT_FILES = (
    "LICENSE",
    "dmm_prefix_table.json",
    "maker_mapping.json",
    "mobile_auth.py",
    "openaver_boot.py",
    "pydantic_v1_compat.py",
)
TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".svg",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
BINARY_SUFFIXES = {
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".png",
    ".webp",
    ".woff",
    ".woff2",
}


def normalize_lines(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.splitlines(keepends=True)
    if text and (not lines or not lines[-1].endswith("\n")):
        lines[-1:] = [lines[-1] + "\n"]
    return lines


def iter_payload(root: Path, include_unknown_root_files: bool = False):
    for root_name in PAYLOAD_ROOTS:
        for path in (root / root_name).rglob("*"):
            if (
                path.is_file()
                and "__pycache__" not in path.parts
                and "__tests__" not in path.parts
                and path.suffix != ".pyc"
            ):
                yield path.relative_to(root).as_posix()
    if include_unknown_root_files:
        root_files = (
            path
            for path in root.iterdir()
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
        )
    else:
        root_files = (root / rel for rel in PAYLOAD_ROOT_FILES)
    for path in root_files:
        if path.is_file():
            yield path.relative_to(root).as_posix()


def files_equal(left: Path, right: Path) -> bool:
    if left.suffix.lower() in TEXT_SUFFIXES or left.name == "LICENSE":
        return normalize_lines(left) == normalize_lines(right)
    return left.read_bytes() == right.read_bytes()


def patch_for_file(upstream_root: Path, source_root: Path, rel: str) -> str:
    old_path = upstream_root / rel
    new_path = source_root / rel
    if (
        old_path.is_file()
        and not new_path.is_file()
        and Path(rel).suffix.lower() in BINARY_SUFFIXES
    ):
        result = subprocess.run(
            ["git", "diff", "--no-index", "--binary", "--", rel, "/dev/null"],
            cwd=upstream_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 1:
            raise RuntimeError(
                f"unable to generate binary deletion patch for {rel}: "
                f"{result.stderr.strip()}"
            )
        return result.stdout

    old_lines = normalize_lines(old_path) if old_path.is_file() else []
    new_lines = normalize_lines(new_path) if new_path.is_file() else []
    if not old_path.is_file() and not new_path.is_file():
        raise FileNotFoundError(f"neither upstream nor source contains {rel}")

    old_name = "a/" + rel if old_path.is_file() else "/dev/null"
    new_name = "b/" + rel if new_path.is_file() else "/dev/null"
    return "".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=old_name,
            tofile=new_name,
            n=3,
            lineterm="\n",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    upstream_root = args.upstream_root.resolve()
    source_root = args.source_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    assigned: set[str] = set()
    manifest: list[dict[str, object]] = []
    for patch_name, files in GROUPS:
        chunks: list[str] = []
        for rel in files:
            if rel in assigned:
                raise ValueError(f"file assigned to more than one patch: {rel}")
            assigned.add(rel)
            diff = patch_for_file(upstream_root, source_root, rel)
            if diff:
                chunks.append(diff)
        if not chunks:
            raise ValueError(f"patch has no changes: {patch_name}")
        (output_dir / patch_name).write_text("".join(chunks), encoding="utf-8", newline="\n")
        manifest.append({"patch": patch_name, "files": list(files)})

    # Detect changed or added payload files outside an intentional group.
    # Upstream-only tests and docs are excluded from the Android payload.
    changed: set[str] = set()
    for rel in sorted(
        set(iter_payload(upstream_root))
        | set(iter_payload(source_root, include_unknown_root_files=True))
    ):
        old = upstream_root / rel
        new = source_root / rel
        if not old.is_file() or not new.is_file():
            changed.add(rel)
        elif not files_equal(old, new):
            changed.add(rel)
    unassigned = changed - assigned
    if unassigned:
        raise ValueError(f"unassigned changed files: {sorted(unassigned)}")

    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "upstream": UPSTREAM_RELEASE,
                "commit": UPSTREAM_COMMIT,
                "patches": manifest,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {len(manifest)} patches to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
