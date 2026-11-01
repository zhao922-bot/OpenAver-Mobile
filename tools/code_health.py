#!/usr/bin/env python3
"""Lightweight, dependency-free code health report for this repository.

The report is intentionally descriptive rather than a hard CI gate. It gives
each optimization round a stable way to compare file size, Python complexity,
CSS duplication, and upstream patch surface without adding a runtime package.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import warnings
from pathlib import Path
from typing import Any, Iterable


EXCLUDED_DIRS = {
    ".git",
    ".gradle",
    ".idea",
    "__pycache__",
    "build",
    "node_modules",
    "vendor",
}
SOURCE_SUFFIXES = {".py", ".js", ".css", ".java"}
SOURCE_ROOTS = ("app/src/main", "tests", "tools")
CSS_THEME = Path("app/src/main/python/web/static/css/theme.css")
CSS_BUNDLE = Path("app/src/main/python/web/static/css/tailwind.css")
BASE_TEMPLATE = Path("app/src/main/python/web/templates/base.html")
CSS_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.DOTALL)
CSS_LINK_RE = re.compile(r'<link[^>]+href="([^"]+\.css(?:\?[^"]*)?)"')


def _iter_files(root: Path) -> Iterable[Path]:
    scan_roots = [
        root / relative
        for relative in SOURCE_ROOTS
        if (root / relative).exists()
    ] or [root]
    for scan_root in scan_roots:
        for path in scan_root.rglob("*"):
            if not path.is_file():
                continue
            relative_parts = path.relative_to(root).parts
            if any(
                part in EXCLUDED_DIRS or part.startswith(".")
                for part in relative_parts
            ):
                continue
            yield path


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _python_raw_metrics(path: Path) -> dict[str, int]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    blank = sum(1 for line in lines if not line.strip())
    comments = sum(
        1 for line in lines if line.lstrip().startswith("#")
    )
    return {
        "loc": len(lines),
        "sloc": len(lines) - blank - comments,
        "comments": comments,
        "blank": blank,
    }


def _complexity_increment(node: ast.AST) -> int:
    if isinstance(
        node,
        (
            ast.If,
            ast.For,
            ast.AsyncFor,
            ast.While,
            ast.ExceptHandler,
            ast.IfExp,
            ast.Assert,
        ),
    ):
        return 1
    if isinstance(node, ast.BoolOp):
        return max(0, len(node.values) - 1)
    if isinstance(node, ast.comprehension):
        return 1 + len(node.ifs)
    if isinstance(node, ast.Match):
        return len(node.cases)
    return 0


def _function_complexity(node: ast.AST) -> int:
    return 1 + sum(_complexity_increment(child) for child in ast.walk(node))


def _python_complexity(path: Path, root: Path) -> list[dict[str, Any]]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, UnicodeError):
        return []
    result = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = getattr(node, "end_lineno", node.lineno)
        result.append({
            "file": str(path.relative_to(root)),
            "name": node.name,
            "line": node.lineno,
            "lines": max(1, end - node.lineno + 1),
            "complexity": _function_complexity(node),
        })
    return result


def _css_rules(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    rules: set[str] = set()
    for match in CSS_RULE_RE.finditer(text):
        selector = _normalize(match.group(1))
        if not selector or selector.startswith("@"):
            continue
        rules.add(f"{selector}{{{_normalize(match.group(2))}}}")
    return rules


def _linked_css(root: Path) -> set[str] | None:
    path = root / BASE_TEMPLATE
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        match.group(1).split("?", 1)[0]
        for match in CSS_LINK_RE.finditer(text)
    }


def _css_report(root: Path) -> dict[str, Any]:
    theme = root / CSS_THEME
    bundle = root / CSS_BUNDLE
    if not theme.is_file() or not bundle.is_file():
        return {
            "theme_rules": 0,
            "bundle_rules": 0,
            "exact_overlap": 0,
            "overlap_percent": 0.0,
            "loaded_theme_rules": 0,
            "loaded_bundle_rules": 0,
            "loaded_exact_overlap": 0,
            "loaded_overlap_percent": 0.0,
        }
    theme_rules = _css_rules(theme)
    bundle_rules = _css_rules(bundle)
    overlap = theme_rules & bundle_rules
    linked = _linked_css(root)
    loaded_theme = theme_rules if linked is None or "/static/css/theme.css" in linked else set()
    loaded_bundle = bundle_rules if linked is None or "/static/css/tailwind.css" in linked else set()
    loaded_overlap = loaded_theme & loaded_bundle
    return {
        "theme_rules": len(theme_rules),
        "bundle_rules": len(bundle_rules),
        "exact_overlap": len(overlap),
        "overlap_percent": round(
            100 * len(overlap) / max(len(theme_rules), 1), 1
        ),
        "loaded_theme_rules": len(loaded_theme),
        "loaded_bundle_rules": len(loaded_bundle),
        "loaded_exact_overlap": len(loaded_overlap),
        "loaded_overlap_percent": round(
            100 * len(loaded_overlap) / max(len(loaded_theme), 1), 1
        ),
    }


def _patch_report(root: Path) -> dict[str, Any]:
    manifest_path = root / "patches/manifest.json"
    if not manifest_path.is_file():
        return {"patches": 0, "files": 0}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"patches": 0, "files": 0}
    patches = manifest.get("patches", [])
    files = {
        file_name
        for patch in patches
        for file_name in patch.get("files", [])
    }
    return {"patches": len(patches), "files": len(files)}


def build_report(root: Path, top: int = 20) -> dict[str, Any]:
    extension_counts: dict[str, int] = {}
    extension_bytes: dict[str, int] = {}
    python_files: list[dict[str, Any]] = []
    functions: list[dict[str, Any]] = []
    largest: list[dict[str, Any]] = []

    for path in _iter_files(root):
        suffix = path.suffix.lower()
        if suffix not in SOURCE_SUFFIXES:
            continue
        size = path.stat().st_size
        extension_counts[suffix] = extension_counts.get(suffix, 0) + 1
        extension_bytes[suffix] = extension_bytes.get(suffix, 0) + size
        relative = str(path.relative_to(root))
        largest.append({"file": relative, "bytes": size})
        if suffix == ".py":
            raw = _python_raw_metrics(path)
            python_files.append({"file": relative, **raw})
            functions.extend(_python_complexity(path, root))

    largest = sorted(largest, key=lambda item: item["bytes"], reverse=True)[:top]
    functions = sorted(
        functions,
        key=lambda item: (item["complexity"], item["lines"]),
        reverse=True,
    )[:top]
    total_python_loc = sum(item["loc"] for item in python_files)
    total_python_sloc = sum(item["sloc"] for item in python_files)
    total_python_comments = sum(item["comments"] for item in python_files)
    python_files = sorted(
        python_files,
        key=lambda item: item["loc"],
        reverse=True,
    )[:top]

    return {
        "summary": {
            "source_files": sum(extension_counts.values()),
            "source_bytes": sum(extension_bytes.values()),
            "files_by_extension": extension_counts,
            "bytes_by_extension": extension_bytes,
            "python_loc": total_python_loc,
            "python_sloc": total_python_sloc,
            "python_comments": total_python_comments,
        },
        "largest_files": largest,
        "largest_python_files": python_files,
        "top_complexity": functions,
        "css": _css_report(root),
        "patches": _patch_report(root),
    }


def _print_text(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print("Code health")
    print(
        f"  source files: {summary['source_files']} "
        f"({summary['source_bytes']} bytes)"
    )
    print(
        f"  Python: LOC={summary['python_loc']} "
        f"SLOC={summary['python_sloc']} comments={summary['python_comments']}"
    )
    print("  largest files:")
    for item in report["largest_files"][:10]:
        print(f"    {item['bytes']:>9} {item['file']}")
    print("  highest complexity:")
    for item in report["top_complexity"][:10]:
        print(
            f"    {item['complexity']:>3} "
            f"{item['file']}:{item['line']} {item['name']}"
        )
    css = report["css"]
    print(
        "  CSS raw source overlap: "
        f"{css['exact_overlap']}/{css['theme_rules']} "
        f"({css['overlap_percent']}%)"
    )
    print(
        "  CSS loaded overlap: "
        f"{css['loaded_exact_overlap']}/{css['loaded_theme_rules']} "
        f"({css['loaded_overlap_percent']}%)"
    )
    patches = report["patches"]
    print(f"  upstream patches: {patches['patches']} files={patches['files']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args(argv)

    report = build_report(args.root.resolve(), top=max(1, args.top))
    if args.output:
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_text(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
