from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from core import atomic_write as atomic_write_module
from core import enricher
from core import android_storage
from core import organizer
from core import readonly_assets
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

    def deny_mkstemp(**_kwargs):
        raise PermissionError("simulated SD-card denial")

    monkeypatch.setattr(
        atomic_write_module.tempfile, "mkstemp", deny_mkstemp
    )
    monkeypatch.setattr(
        android_storage, "has_access", lambda _path: False
    )

    with pytest.raises(AndroidStoragePermissionError):
        organizer._write_image_payload(  # noqa: SLF001
            str(destination), b"image"
        )


def test_write_nfo_reports_generate_failure(monkeypatch):
    monkeypatch.setattr(organizer, "generate_nfo", lambda **_kwargs: False)

    written = enricher._write_nfo(  # noqa: SLF001
        "/storage/SD/JAV/ABC-123.mp4",
        "ABC-123",
        {"title": "标题"},
        write_nfo=True,
        overwrite_existing=True,
        has_subtitle=False,
        user_tags=[],
    )

    assert written is False


def test_crop_to_poster_writes_jpeg_through_shared_payload(
    tmp_path, monkeypatch
):
    source = tmp_path / "ABC-123.jpg"
    destination = tmp_path / "ABC-123-poster.jpg"
    Image.new("RGB", (800, 538), "white").save(source, "JPEG")
    captured = {}

    monkeypatch.setattr(
        organizer,
        "_write_image_payload",
        lambda path, payload: captured.update(path=path, payload=payload),
    )

    assert organizer.crop_to_poster(str(source), str(destination))
    assert captured["path"] == str(destination)
    assert captured["payload"].startswith(b"\xff\xd8")
    with Image.open(BytesIO(captured["payload"])) as poster:
        assert poster.size == (379, 538)


def test_crop_to_poster_copies_portrait_through_shared_file_bridge(
    tmp_path, monkeypatch
):
    source = tmp_path / "ABC-123.jpg"
    destination = tmp_path / "ABC-123-poster.jpg"
    Image.new("RGB", (400, 600), "white").save(source, "JPEG")
    captured = {}

    monkeypatch.setattr(
        organizer,
        "_copy_file_with_mobile_fallback",
        lambda src, dst: captured.update(src=src, dst=dst),
    )

    assert organizer.crop_to_poster(str(source), str(destination))
    assert captured == {"src": str(source), "dst": str(destination)}


def test_generate_jellyfin_images_fanart_uses_saf_payload(
    tmp_path, monkeypatch
):
    cover = tmp_path / "ABC-123.jpg"
    Image.new("RGB", (400, 600), "white").save(cover, "JPEG")
    base_stem = str(tmp_path / "ABC-123")
    captured = {}

    def deny_copy(_src, _dst):
        raise PermissionError("simulated SD-card denial")

    monkeypatch.setattr(organizer.shutil, "copy2", deny_copy)
    monkeypatch.setattr(
        organizer,
        "_write_image_payload",
        lambda path, payload: captured.update(path=path, payload=payload),
    )
    monkeypatch.setattr(organizer, "crop_to_poster", lambda *_args, **_kwargs: True)

    result = organizer.generate_jellyfin_images(str(cover), base_stem)

    assert result["fanart"] is True
    assert result["poster"] is True
    assert captured == {
        "path": base_stem + "-fanart.jpg",
        "payload": cover.read_bytes(),
    }


def test_readonly_cover_and_sidecar_copies_use_shared_file_bridge(
    tmp_path, monkeypatch
):
    cover = tmp_path / "source.jpg"
    cover.write_bytes(b"cover")
    sidecar = tmp_path / "source-poster.jpg"
    sidecar.write_bytes(b"curator-poster")
    calls = []

    monkeypatch.setattr(
        readonly_assets,
        "_copy_file_with_mobile_fallback",
        lambda src, dst: calls.append((src, dst)),
    )

    assert readonly_assets._write_cover_copy(  # noqa: SLF001
        str(cover), str(tmp_path / "output.jpg")
    )
    assert readonly_assets._copy_curator_sidecar(  # noqa: SLF001
        str(sidecar), str(tmp_path / "output-poster.jpg"), "poster"
    )

    assert calls == [
        (str(cover), str(tmp_path / "output.jpg")),
        (str(sidecar), str(tmp_path / "output-poster.jpg")),
    ]
