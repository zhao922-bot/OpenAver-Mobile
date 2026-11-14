from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "tools/verify_python_payload.py"


@pytest.mark.parametrize("extra,valid", [
    ({}, True),
    ({"output/config.json": b'{"test": true}'}, False),
    ({"output/": b""}, False),
    ({"logs/debug.log": b"test log"}, False),
    ({"web/config.json": b'{"test": true}'}, False),
])
def test_python_payload_excludes_runtime_data(tmp_path, extra, valid):
    archive = tmp_path / "app.imy"
    entries = {
        "openaver_boot.pyc": b"test bytecode",
        "web/config.default.json": b"{}",
        "web/templates/settings.html": b"<html></html>",
        **extra,
    }
    with zipfile.ZipFile(archive, "w") as output:
        for name, contents in entries.items():
            output.writestr(name, contents)
    result = subprocess.run(
        [sys.executable, str(VERIFIER), "--archive", str(archive)],
        capture_output=True, text=True,
    )
    if valid:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0
        assert "Runtime files" in result.stdout + result.stderr
