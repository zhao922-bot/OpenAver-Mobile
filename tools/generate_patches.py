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
from pathlib import Path


UPSTREAM_RELEASE = "v0.17.18"
UPSTREAM_COMMIT = "af0d99741e63e71980773c9ade04c473407a60b7"

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
            "core/focal/subprocess_runner.py",
        ),
    ),
    (
        "004-network-and-scraper-fallbacks.patch",
        (
            "core/custom_source/fetch.py",
            "core/custom_source/schema.py",
            "core/proxy_policy.py",
            "core/scrapers/actress/avbase.py",
            "core/scrapers/javdb.py",
            "core/scrapers/models.py",
        ),
    ),
    (
        "005-android-file-writeback.patch",
        (
            "core/enricher.py",
            "core/gallery_scanner.py",
            "core/nfo_utils.py",
            "core/organizer.py",
            "core/source_config.py",
            "core/title_writeback.py",
        ),
    ),
    (
        "006-mobile-web-routers.patch",
        (
            "web/routers/capabilities.py",
            "web/routers/scanner.py",
            "web/routers/scraper.py",
            "web/routers/showcase.py",
        ),
    ),
    (
        "007-mobile-ui-and-localization.patch",
        (
            "core/config.py",
            "locales/en.json",
            "locales/ja.json",
            "locales/zh_CN.json",
            "locales/zh_TW.json",
            "web/config.default.json",
            "web/static/css/pages/showcase/05-lightbox.css",
            "web/static/css/pages/showcase/06-responsive-and-lists.css",
            "web/static/js/components/mobile-back.js",
            "web/static/js/pages/settings/state-config.js",
            "web/static/js/pages/showcase/state-actress.js",
            "web/static/js/pages/showcase/state-lightbox-translate.js",
            "web/static/js/pages/showcase/state-lightbox.js",
            "web/templates/base.html",
            "web/templates/showcase.html",
        ),
    ),
    (
        "008-mobile-loopback-auth.patch",
        ("mobile_auth.py",),
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
    if left.suffix.lower() in TEXT_SUFFIXES:
        return normalize_lines(left) == normalize_lines(right)
    return left.read_bytes() == right.read_bytes()


def patch_for_file(upstream_root: Path, source_root: Path, rel: str) -> str:
    old_path = upstream_root / rel
    new_path = source_root / rel
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
