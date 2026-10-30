from __future__ import annotations

import errno
from pathlib import Path

import pytest

from core import atomic_write as atomic_write_module
from core.atomic_write import atomic_write
from core.nfo_utils import find_sidecar_nfos
from core.title_writeback import rewrite_nfo_titles


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


def test_atomic_write_uses_mobile_bridge_after_permission_error(
    tmp_path, monkeypatch
):
    target = tmp_path / "ABC-123.nfo"
    captured = {}

    def fail_mkstemp(**_kwargs):
        raise PermissionError("simulated Android SD-card denial")

    monkeypatch.setattr(atomic_write_module.tempfile, "mkstemp", fail_mkstemp)
    from core import android_storage

    monkeypatch.setattr(android_storage, "has_access", lambda _path: True)
    monkeypatch.setattr(
        android_storage,
        "write_bytes",
        lambda path, data: captured.update(path=path, data=data),
    )

    with atomic_write(
        target, mode="wb", suffix=".nfo.tmp", mobile_fallback=True
    ) as handle:
        handle.write(b"replacement")

    assert captured == {
        "path": str(target),
        "data": b"replacement",
    }


def test_atomic_write_requires_tree_when_mobile_fallback_is_unauthorized(
    tmp_path, monkeypatch
):
    target = tmp_path / "ABC-123.nfo"

    def fail_mkstemp(**_kwargs):
        raise PermissionError("simulated Android SD-card denial")

    monkeypatch.setattr(atomic_write_module.tempfile, "mkstemp", fail_mkstemp)
    from core import android_storage

    monkeypatch.setattr(android_storage, "has_access", lambda _path: False)

    with pytest.raises(android_storage.AndroidStoragePermissionError):
        with atomic_write(
            target, mode="wb", suffix=".nfo.tmp", mobile_fallback=True
        ) as handle:
            handle.write(b"replacement")


def test_atomic_write_does_not_hide_disk_full_with_saf_fallback(
    tmp_path, monkeypatch
):
    target = tmp_path / "ABC-123.nfo"

    def fail_mkstemp(**_kwargs):
        raise OSError(errno.ENOSPC, "simulated disk full")

    monkeypatch.setattr(atomic_write_module.tempfile, "mkstemp", fail_mkstemp)
    from core import android_storage

    monkeypatch.setattr(android_storage, "has_access", lambda _path: True)

    with pytest.raises(OSError, match="simulated disk full"):
        with atomic_write(
            target, mode="wb", suffix=".nfo.tmp", mobile_fallback=True
        ) as handle:
            handle.write(b"replacement")


def test_rewrite_nfo_titles_changes_title_and_preserves_other_nodes(tmp_path):
    nfo = tmp_path / "ABC-123.nfo"
    nfo.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<movie><num>ABC-123</num><title>old</title>"
        "<originaltitle>original</originaltitle><plot>keep me</plot></movie>",
        encoding="utf-8",
    )

    rewrite_nfo_titles(
        nfo,
        number="ABC-123",
        title_body="新标题 & 特殊字符",
        original_title="original",
        actors=[],
        maker="Maker",
        date="2026-10-30",
        nfo_title_format="[{num}]{title}",
    )

    text = nfo.read_text(encoding="utf-8")
    assert "[ABC-123]新标题 &amp; 特殊字符" in text
    assert "<plot>keep me</plot>" in text
