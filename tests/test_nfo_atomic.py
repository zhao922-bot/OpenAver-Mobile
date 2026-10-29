from __future__ import annotations

from pathlib import Path

import pytest

from core import atomic_write as atomic_write_module
from core.atomic_write import atomic_write
from core.nfo_utils import find_sidecar_nfos


def test_find_sidecar_nfos_matches_extension_case_insensitively(tmp_path):
    video = tmp_path / "ABC-123.mp4"
    video.write_bytes(b"video")
    upper = tmp_path / "ABC-123.NFO"
    upper.write_text("<movie />", encoding="utf-8")

    assert find_sidecar_nfos(video) == [upper]


def test_atomic_write_replaces_target_only_after_success(tmp_path, monkeypatch):
    target = tmp_path / "ABC-123.nfo"
    target.write_text("original", encoding="utf-8")
    real_replace = atomic_write_module.os.replace

    def fail_replace(source, destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(atomic_write_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        with atomic_write(target, mode="w", encoding="utf-8") as handle:
            handle.write("replacement")

    assert target.read_text(encoding="utf-8") == "original"
    assert list(target.parent.glob("*.tmp")) == []

    monkeypatch.setattr(atomic_write_module.os, "replace", real_replace)
    with atomic_write(target, mode="w", encoding="utf-8") as handle:
        handle.write("replacement")
    assert target.read_text(encoding="utf-8") == "replacement"
