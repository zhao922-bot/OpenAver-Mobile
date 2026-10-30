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


def test_atomic_write_uses_mobile_bridge_for_text_nfo(tmp_path, monkeypatch):
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
        target,
        mode="w",
        encoding="utf-8",
        suffix=".nfo.tmp",
        mobile_fallback=True,
    ) as handle:
        handle.write("<movie><title>标题</title></movie>")

    assert captured == {
        "path": str(target),
        "data": "<movie><title>标题</title></movie>".encode("utf-8"),
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


def test_atomic_write_uses_mobile_bridge_when_replace_is_denied(
    tmp_path, monkeypatch
):
    target = tmp_path / "ABC-123.nfo"
    captured = {}

    def fail_replace(_source, _destination):
        raise PermissionError("simulated Android rename denial")

    monkeypatch.setattr(atomic_write_module.os, "replace", fail_replace)
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
    assert list(tmp_path.glob("*.tmp")) == []


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


def test_generate_nfo_uses_mobile_bridge_for_text_write(
    tmp_path, monkeypatch
):
    from core import android_storage, organizer

    captured = {}
    output_path = tmp_path / "ABC-123.nfo"

    def fail_mkstemp(**_kwargs):
        raise PermissionError("simulated Android SD-card denial")

    monkeypatch.setattr(atomic_write_module.tempfile, "mkstemp", fail_mkstemp)
    monkeypatch.setattr(android_storage, "has_access", lambda _path: True)
    monkeypatch.setattr(
        android_storage,
        "write_bytes",
        lambda path, data: captured.update(path=path, data=data),
    )

    assert organizer.generate_nfo(
        number="ABC-123",
        title="新标题",
        original_title="original",
        output_path=str(output_path),
    )

    assert captured["path"] == str(output_path)
    assert "<title>[ABC-123]新标题</title>".encode("utf-8") in captured["data"]


def test_update_nfo_file_uses_mobile_bridge(tmp_path, monkeypatch):
    from core import android_storage
    from core.nfo_updater import update_nfo_file

    nfo = tmp_path / "ABC-123.nfo"
    nfo.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<movie><title>Existing</title><num>ABC-123</num></movie>",
        encoding="utf-8",
    )
    captured = {}

    def fail_mkstemp(**_kwargs):
        raise PermissionError("simulated Android SD-card denial")

    monkeypatch.setattr(atomic_write_module.tempfile, "mkstemp", fail_mkstemp)
    monkeypatch.setattr(android_storage, "has_access", lambda _path: True)
    monkeypatch.setattr(
        android_storage,
        "write_bytes",
        lambda path, data: captured.update(path=path, data=data),
    )

    updated, changes = update_nfo_file(
        str(nfo),
        {"tags": ["痴女", "巨乳"], "maker": "Maker"},
        {"title": "Existing", "genre": "", "maker": ""},
    )

    assert updated is True
    assert "tags(2)" in changes
    assert captured["path"] == str(nfo)
    assert b"<tag>\xe7\x97\xb4\xe5\xa5\xb3</tag>" in captured["data"]
    assert b"<genre>\xe5\xb7\xa8\xe4\xb9\xb3</genre>" in captured["data"]


def test_update_nfo_user_tags_uses_mobile_bridge(tmp_path, monkeypatch):
    from core import android_storage
    from core.nfo_updater import update_nfo_user_tags

    nfo = tmp_path / "ABC-123.nfo"
    nfo.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<movie><title>Keep</title><user_tag>old</user_tag></movie>",
        encoding="utf-8",
    )
    captured = {}

    def fail_mkstemp(**_kwargs):
        raise PermissionError("simulated Android SD-card denial")

    monkeypatch.setattr(atomic_write_module.tempfile, "mkstemp", fail_mkstemp)
    monkeypatch.setattr(android_storage, "has_access", lambda _path: True)
    monkeypatch.setattr(
        android_storage,
        "write_bytes",
        lambda path, data: captured.update(path=path, data=data),
    )

    assert update_nfo_user_tags(str(nfo), ["收藏", "★5"])

    assert captured["path"] == str(nfo)
    assert b"<title>Keep</title>" in captured["data"]
    assert b"<user_tag>\xe6\x94\xb6\xe8\x97\x8f</user_tag>" in captured["data"]
    assert b"<user_tag>old</user_tag>" not in captured["data"]


def test_replace_nfo_tags_preserves_other_nodes(tmp_path):
    from core.nfo_updater import replace_nfo_tags

    nfo = tmp_path / "ABC-123.nfo"
    nfo.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<movie><title>Keep</title><tag>old</tag><genre>old</genre>"
        "<plot>keep plot</plot><user_tag>mine</user_tag></movie>",
        encoding="utf-8",
    )

    assert replace_nfo_tags(str(nfo), ["痴女", "巨乳", "痴女"])

    text = nfo.read_text(encoding="utf-8")
    assert text.count("<tag>痴女</tag>") == 1
    assert text.count("<genre>巨乳</genre>") == 1
    assert "<tag>old</tag>" not in text
    assert "<genre>old</genre>" not in text
    assert "<title>Keep</title>" in text
    assert "<plot>keep plot</plot>" in text
    assert "<user_tag>mine</user_tag>" in text


def test_get_nfo_path_from_video_accepts_uppercase_extension(tmp_path):
    from core.nfo_updater import get_nfo_path_from_video

    video = tmp_path / "ABC-123.mp4"
    video.write_bytes(b"video")
    nfo = tmp_path / "ABC-123.NFO"
    nfo.write_text("<movie />", encoding="utf-8")

    assert get_nfo_path_from_video(str(video)) == str(nfo)
