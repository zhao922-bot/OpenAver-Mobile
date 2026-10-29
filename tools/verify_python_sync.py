#!/usr/bin/env python3
"""Verify that current Android Python equals upstream plus the patch set."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from prepare_python_tree import (
    copy_tree,
    normalize_text_files,
    normalized_file_bytes,
)

def iter_payload(root: Path):
    for path in root.rglob("*"):
        if (
            not path.is_file()
            or "__pycache__" in path.parts
            or ".git" in path.parts
            or path.suffix == ".pyc"
        ):
            continue
        if "__tests__" in path.parts:
            continue
        yield path.relative_to(root).as_posix(), path


def verify_upstream_checkout(upstream: Path, patch_root: Path) -> None:
    manifest_path = patch_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest.get("commit")
    if not expected:
        raise RuntimeError(f"{manifest_path} does not declare an upstream commit")
    if not (upstream / ".git").exists():
        return
    actual = subprocess.run(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if actual != expected:
        raise RuntimeError(
            f"upstream checkout is {actual}, but patches require {expected}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    args = parser.parse_args()

    upstream = args.upstream_root.resolve()
    source = args.source_root.resolve()
    patch_root = source.parents[3] / "patches"
    try:
        verify_upstream_checkout(upstream, patch_root)
    except Exception as exc:
        print(f"python sync verification FAILED: {exc}")
        return 1

    with tempfile.TemporaryDirectory(prefix="openaver-sync-") as temp_name:
        temp = Path(temp_name)
        copy_tree(upstream, temp)
        normalize_text_files(temp)
        subprocess.run(["git", "init", "-q"], cwd=temp, check=True)
        for patch in sorted(patch_root.glob("*.patch")):
            subprocess.run(
                [
                    "git",
                    "-c",
                    "core.autocrlf=false",
                    "apply",
                    "--whitespace=nowarn",
                    str(patch),
                ],
                cwd=temp,
                check=True,
            )

        expected = dict(iter_payload(source))
        actual = dict(iter_payload(temp))
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        different = sorted(
            rel
            for rel in set(expected) & set(actual)
            if hashlib.sha256(normalized_file_bytes(expected[rel])).digest()
            != hashlib.sha256(normalized_file_bytes(actual[rel])).digest()
        )
        if missing or extra or different:
            print("python sync verification FAILED")
            if missing:
                print("missing:", missing)
            if extra:
                print("extra:", extra)
            if different:
                print("different:", different)
                for rel in different:
                    left = expected[rel]
                    right = actual[rel]
                    print(
                        "detail:",
                        rel,
                        left.stat().st_size,
                        right.stat().st_size,
                        hashlib.sha256(normalized_file_bytes(left)).hexdigest()[:16],
                        hashlib.sha256(normalized_file_bytes(right)).hexdigest()[:16],
                    )
            return 1
        print(
            f"python sync verification OK: {len(expected)} files "
            "match upstream + patches"
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
