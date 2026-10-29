#!/usr/bin/env python3
"""Copy the clean upstream subset used by the Android payload."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


PAYLOAD_ROOTS = ("core", "web", "locales")
PAYLOAD_ROOT_FILES = (
    "LICENSE",
    "dmm_prefix_table.json",
    "maker_mapping.json",
)
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".svg",
    ".txt",
}


def ignored(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix == ".pyc" or "__tests__" in path.parts


def copy_tree(source: Path, destination: Path) -> None:
    for root_name in PAYLOAD_ROOTS:
        source_root = source / root_name
        target_root = destination / root_name
        if not source_root.is_dir():
            raise FileNotFoundError(f"upstream payload directory missing: {source_root}")
        for source_file in source_root.rglob("*"):
            if not source_file.is_file() or ignored(source_file):
                continue
            target_file = target_root / source_file.relative_to(source_root)
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)

    for rel in PAYLOAD_ROOT_FILES:
        source_file = source / rel
        if not source_file.is_file():
            raise FileNotFoundError(f"upstream payload file missing: {source_file}")
        shutil.copy2(source_file, destination / rel)


def patched_relative_files(patch_dir: Path) -> set[str]:
    manifest_path = patch_dir / "manifest.json"
    if not manifest_path.is_file():
        return set()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        rel
        for item in manifest.get("patches", [])
        for rel in item.get("files", [])
    }


def normalize_text_files(root: Path, only: set[str] | None = None) -> None:
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        if only is not None and rel not in only:
            continue
        data = path.read_bytes()
        normalized = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        if normalized and not normalized.endswith(b"\n"):
            normalized += b"\n"
        if normalized != data:
            path.write_bytes(normalized)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing output root instead of refusing to overwrite it",
    )
    parser.add_argument(
        "--patch-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "patches",
        help="patch directory whose manifest identifies files needing LF normalization",
    )
    args = parser.parse_args()

    upstream = args.upstream_root.resolve()
    destination = args.output_root.resolve()
    if destination.exists():
        empty_directory = destination.is_dir() and not any(destination.iterdir())
        if not args.force and not empty_directory:
            raise SystemExit(
                f"output root exists: {destination}; pass --force to replace it"
            )
        if not empty_directory:
            shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    copy_tree(upstream, destination)
    normalize_text_files(destination, patched_relative_files(args.patch_dir.resolve()))
    print(f"prepared clean Android Python payload at {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
