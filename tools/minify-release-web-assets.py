#!/usr/bin/env python3
"""Minify first-party web assets inside the generated release app.imy."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from copy import copy
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HELPER = ROOT / "tools" / "echarts-build" / "minify-entrypoints.mjs"
ASSET_PREFIXES = ("web/static/js/", "web/static/css/")
ASSET_SUFFIXES = (".js", ".css")


def is_minifiable_entry(name: str) -> bool:
    """Return whether a zip entry is a first-party JS or CSS asset."""
    return (
        not name.endswith("/")
        and name.startswith(ASSET_PREFIXES)
        and name.endswith(ASSET_SUFFIXES)
        and not name.startswith("web/static/vendor/")
    )


def _safe_member_path(root: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe archive member: {name}")
    destination = root.joinpath(*relative.parts)
    resolved_root = root.resolve()
    if not destination.resolve().is_relative_to(resolved_root):
        raise ValueError(f"archive member escapes root: {name}")
    return destination


def apply_replacements(
    archive: Path,
    replacements: Mapping[str, bytes],
) -> tuple[int, int, int]:
    """Atomically rebuild an archive, keeping only smaller replacements."""
    archive = archive.resolve()
    if not archive.is_file():
        raise FileNotFoundError(archive)
    invalid = [name for name in replacements if not is_minifiable_entry(name)]
    if invalid:
        raise ValueError(f"replacement targets a non-minifiable entry: {invalid[0]}")

    replaced = 0
    before_bytes = 0
    after_bytes = 0
    temporary_name: str | None = None
    try:
        with zipfile.ZipFile(archive, "r") as source_zip:
            names = set(source_zip.namelist())
            missing = [name for name in replacements if name not in names]
            if missing:
                raise KeyError(f"archive member is missing: {missing[0]}")

            with tempfile.NamedTemporaryFile(
                dir=archive.parent,
                prefix=f".{archive.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name

            with zipfile.ZipFile(
                temporary_name,
                "w",
                compression=zipfile.ZIP_DEFLATED,
            ) as target_zip:
                for info in source_zip.infolist():
                    original = b"" if info.is_dir() else source_zip.read(info)
                    output = original
                    replacement = replacements.get(info.filename)
                    if (
                        replacement is not None
                        and len(replacement) < len(original)
                    ):
                        output = replacement
                        replaced += 1
                        before_bytes += len(original)
                        after_bytes += len(replacement)
                    target_info = copy(info)
                    target_zip.writestr(target_info, output)

        with zipfile.ZipFile(temporary_name, "r") as rebuilt:
            bad_member = rebuilt.testzip()
            if bad_member:
                raise zipfile.BadZipFile(f"rebuilt archive is corrupt at {bad_member}")
        os.replace(temporary_name, archive)
        temporary_name = None
        return replaced, before_bytes, after_bytes
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _extract_candidates(
    archive: Path,
    input_root: Path,
) -> tuple[list[str], dict[str, bytes]]:
    entries: list[str] = []
    originals: dict[str, bytes] = {}
    with zipfile.ZipFile(archive, "r") as source_zip:
        for info in source_zip.infolist():
            if info.is_dir() or not is_minifiable_entry(info.filename):
                continue
            data = source_zip.read(info)
            destination = _safe_member_path(input_root, info.filename)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            entries.append(info.filename)
            originals[info.filename] = data
    return entries, originals


def _run_esbuild(
    node: str,
    helper: Path,
    input_root: Path,
    manifest: Path,
    output_root: Path,
) -> None:
    subprocess.run(
        [
            node,
            str(helper),
            str(input_root),
            str(manifest),
            str(output_root),
        ],
        cwd=ROOT,
        check=True,
    )


def minify_archive(
    archive: Path,
    *,
    node: str = "node",
    helper: Path = DEFAULT_HELPER,
) -> tuple[int, int, int, int]:
    """Minify first-party JS/CSS entries and atomically replace the archive."""
    archive = archive.resolve()
    helper = helper.resolve()
    if not helper.is_file():
        raise FileNotFoundError(helper)

    with tempfile.TemporaryDirectory(
        dir=archive.parent,
        prefix=f".{archive.stem}-minify-",
    ) as temporary:
        work_root = Path(temporary)
        input_root = work_root / "input"
        output_root = work_root / "output"
        input_root.mkdir()
        output_root.mkdir()
        entries, originals = _extract_candidates(archive, input_root)
        if not entries:
            raise RuntimeError("no first-party JS/CSS entries found in app.imy")

        manifest = work_root / "entries.json"
        manifest.write_text(
            json.dumps(entries, ensure_ascii=False),
            encoding="utf-8",
        )
        _run_esbuild(node, helper, input_root, manifest, output_root)

        replacements: dict[str, bytes] = {}
        for name in entries:
            output = _safe_member_path(output_root, name)
            if not output.is_file():
                raise FileNotFoundError(f"esbuild did not produce {name}")
            replacements[name] = output.read_bytes()

        replaced, before_bytes, after_bytes = apply_replacements(
            archive,
            replacements,
        )
        return len(entries), replaced, before_bytes, after_bytes


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Minify first-party JS/CSS in a generated app.imy",
    )
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--node", default="node")
    parser.add_argument("--helper", type=Path, default=DEFAULT_HELPER)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        candidates, replaced, before_bytes, after_bytes = minify_archive(
            args.archive,
            node=args.node,
            helper=args.helper,
        )
    except (FileNotFoundError, KeyError, RuntimeError, ValueError, zipfile.BadZipFile):
        print(f"release asset minification failed: {sys.exc_info()[1]}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(
            f"release asset minification failed: esbuild exited {exc.returncode}",
            file=sys.stderr,
        )
        return 1

    print(
        "release asset minification: "
        f"{candidates} candidates, {replaced} replaced, "
        f"{before_bytes} -> {after_bytes} raw bytes "
        f"({before_bytes - after_bytes} saved)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
