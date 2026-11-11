from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
JS_TESTS = sorted((ROOT / "tests" / "js").glob("*.test.mjs"))


def test_r2_javascript_regressions():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    assert JS_TESTS, "r2 JavaScript tests are missing"
    result = subprocess.run(
        [node, "--test", *map(str, JS_TESTS)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
