from __future__ import annotations

from pathlib import Path

import pytest

from core import enricher
from core import android_storage
from core import organizer
from core.android_storage import AndroidStoragePermissionError


def test_extrafanart_reports_per_image_download_reason(tmp_path, monkeypatch):
    video = tmp_path / "ABC-123.mp4"
    video.write_bytes(b"video")

    def fail_download(_url, _dest, referer="", diagnostics=None):
        diagnostics.update({
            "attempts": [{
                "reason": "http_error",
                "host": "example.invalid",
                "http_status": 404,
            }],
        })
        return False

    monkeypatch.setattr(enricher, "download_image", fail_download)

    result = enricher._write_extrafanart(  # noqa: SLF001
        str(video),
        ["https://example.invalid/fanart.jpg"],
        write_extrafanart=True,
        path_mappings={},
        base_url="https://example.invalid/detail",
    )

    assert result.failed == 1
    assert result.errors == ({
        "index": 1,
        "reason": "http_error",
        "host": "example.invalid",
        "http_status": 404,
    },)


def test_extrafanart_deduplicates_repeated_urls(tmp_path, monkeypatch):
    video = tmp_path / "ABC-123.mp4"
    video.write_bytes(b"video")
    calls = []

    def successful_download(url, dest, referer="", diagnostics=None):
        calls.append(url)
        Path(dest).write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 64)
        diagnostics.update({
            "attempts": [{"reason": "success", "success": True}],
        })
        return True

    monkeypatch.setattr(enricher, "download_image", successful_download)

    result = enricher._write_extrafanart(  # noqa: SLF001
        str(video),
        [
            "https://example.invalid/fanart.jpg",
            "https://example.invalid/fanart.jpg",
        ],
        write_extrafanart=True,
        path_mappings={},
    )

    assert calls == ["https://example.invalid/fanart.jpg"]
    assert result.downloaded == 1
    assert len(result.uris) == 1
    assert result.uris[0].endswith("/extrafanart/fanart1.jpg")


def test_extrafanart_preserves_storage_permission_error(tmp_path, monkeypatch):
    video = tmp_path / "ABC-123.mp4"
    video.write_bytes(b"video")

    def denied_download(_url, _dest, referer="", diagnostics=None):
        raise AndroidStoragePermissionError("storage_tree_not_authorized")

    monkeypatch.setattr(enricher, "download_image", denied_download)

    with pytest.raises(AndroidStoragePermissionError):
        enricher._write_extrafanart(  # noqa: SLF001
            str(video),
            ["https://example.invalid/fanart.jpg"],
            write_extrafanart=True,
            path_mappings={},
        )


def test_download_image_preserves_storage_permission_error(
    tmp_path, monkeypatch
):
    destination = tmp_path / "fanart.jpg"

    def deny_open(*_args, **_kwargs):
        raise PermissionError("simulated SD-card denial")

    monkeypatch.setattr("builtins.open", deny_open)
    monkeypatch.setattr(
        android_storage, "has_access", lambda _path: False
    )

    with pytest.raises(AndroidStoragePermissionError):
        organizer._write_image_payload(  # noqa: SLF001
            str(destination), b"image"
        )
