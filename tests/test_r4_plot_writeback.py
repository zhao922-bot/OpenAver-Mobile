from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from contextlib import contextmanager

import pytest

from core.database import Video, VideoRepository, init_db
from core.path_utils import to_file_uri
from core.plot_writeback import (
    PlotEmptyError,
    read_nfo_plots,
    rewrite_nfo_plot,
)
from core.title_writeback import NfoNotFoundError
from web.routers import showcase_plot


JAPANESE_PLOT = "日本語のあらすじ\n第二行 & 記号"
TRANSLATED_PLOT = "翻译后的简介\n第二行 & 符号"
RETRANSLATED_PLOT = "重新翻译后的简介"

SEED_NFO = f"""<?xml version='1.0' encoding='utf-8'?>
<movie>
  <title>ABC-123 タイトル</title>
  <plot>{JAPANESE_PLOT.replace("&", "&amp;")}</plot>
  <rating>7.5</rating>
  <website>https://example.invalid/?a=1&amp;b=2</website>
  <actor><name>女優A</name></actor>
  <actor><name>女優B</name></actor>
</movie>
"""


def _text(root: ET.Element, tag: str) -> str:
    return root.findtext(tag) or ""


def _other_children(root: ET.Element) -> list[tuple]:
    return [
        (child.tag, child.text, tuple(child.attrib.items()))
        for child in root
        if child.tag not in {"plot", "originalplot"}
    ]


def test_rewrite_nfo_plot_preserves_other_elements_and_supports_undo(tmp_path):
    nfo = tmp_path / "ABC-123.nfo"
    nfo.write_text(SEED_NFO, encoding="utf-8")
    before = ET.fromstring(SEED_NFO.encode("utf-8"))
    before_other = _other_children(before)

    rewrite_nfo_plot(
        nfo,
        new_plot=TRANSLATED_PLOT,
        new_original=JAPANESE_PLOT,
    )
    root = ET.fromstring(nfo.read_bytes())
    assert _text(root, "plot") == TRANSLATED_PLOT
    assert _text(root, "originalplot") == JAPANESE_PLOT
    assert _other_children(root) == before_other
    children = list(root)
    plot_index = next(i for i, child in enumerate(children) if child.tag == "plot")
    assert children[plot_index + 1].tag == "originalplot"

    rewrite_nfo_plot(
        nfo,
        new_plot=RETRANSLATED_PLOT,
        new_original=None,
    )
    root = ET.fromstring(nfo.read_bytes())
    assert _text(root, "plot") == RETRANSLATED_PLOT
    assert _text(root, "originalplot") == JAPANESE_PLOT

    rewrite_nfo_plot(
        nfo,
        new_plot=JAPANESE_PLOT,
        new_original="",
    )
    root = ET.fromstring(nfo.read_bytes())
    assert _text(root, "plot") == JAPANESE_PLOT
    assert root.find("originalplot") is None
    assert _other_children(root) == before_other


def test_read_nfo_plots_preserves_newlines_and_reports_empty_plot(tmp_path):
    nfo = tmp_path / "ABC-123.nfo"
    nfo.write_text(SEED_NFO, encoding="utf-8")
    plot, original = read_nfo_plots(nfo)
    assert plot == JAPANESE_PLOT
    assert original == ""

    empty = tmp_path / "EMPTY.nfo"
    empty.write_text("<movie><plot></plot></movie>", encoding="utf-8")
    with pytest.raises(PlotEmptyError):
        rewrite_nfo_plot(empty, new_plot=TRANSLATED_PLOT, new_original=None)


def test_rewrite_nfo_plot_uses_mobile_atomic_fallback(tmp_path, monkeypatch):
    nfo = tmp_path / "ABC-123.nfo"
    nfo.write_text(SEED_NFO, encoding="utf-8")
    seen = {}

    @contextmanager
    def capture(dest, **kwargs):
        seen["dest"] = str(dest)
        seen.update(kwargs)
        handle = io.BytesIO()
        yield handle
        nfo.write_bytes(handle.getvalue())

    monkeypatch.setattr(showcase_plot, "rewrite_nfo_plot", rewrite_nfo_plot)
    monkeypatch.setattr("core.plot_writeback.atomic_write", capture)

    rewrite_nfo_plot(nfo, new_plot=TRANSLATED_PLOT, new_original=None)

    assert seen["dest"] == str(nfo)
    assert seen["mode"] == "wb"
    assert seen["suffix"] == ".nfo.tmp"
    assert seen["mobile_fallback"] is True


def test_rewrite_nfo_plot_requires_existing_nfo(tmp_path):
    with pytest.raises(NfoNotFoundError):
        rewrite_nfo_plot(
            tmp_path / "missing.nfo",
            new_plot=TRANSLATED_PLOT,
            new_original=None,
        )


def test_target_original_handles_first_translate_and_undo():
    assert showcase_plot._target_original(
        None,
        JAPANESE_PLOT,
        "",
        TRANSLATED_PLOT,
    ) == JAPANESE_PLOT
    assert showcase_plot._target_original(
        None,
        TRANSLATED_PLOT,
        JAPANESE_PLOT,
        RETRANSLATED_PLOT,
    ) == JAPANESE_PLOT
    assert showcase_plot._target_original(
        "",
        TRANSLATED_PLOT,
        JAPANESE_PLOT,
        JAPANESE_PLOT,
    ) == ""


def _wire_plot_router(monkeypatch, db_path, library_dir, output_dir=None):
    library_uri = to_file_uri(str(library_dir))
    monkeypatch.setattr(showcase_plot, "get_db_path", lambda: db_path)
    monkeypatch.setattr(
        showcase_plot,
        "load_config",
        lambda: {"general": {"locale": "en"}},
    )
    monkeypatch.setattr(
        showcase_plot,
        "get_configured_gallery_dirs",
        lambda _config: ({library_uri}, {}),
    )
    if output_dir is None:
        monkeypatch.setattr(
            showcase_plot,
            "resolve_owning_output_root",
            lambda _path, _config: None,
        )
    else:
        monkeypatch.setattr(
            showcase_plot,
            "resolve_owning_output_root",
            lambda _path, _config: (None, None, to_file_uri(str(output_dir))),
        )


def test_plot_router_roundtrip_and_missing_nfo(monkeypatch, tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    video_path = library / "ABC-123.mp4"
    video_path.write_bytes(b"video")
    nfo_path = library / "ABC-123.nfo"
    nfo_path.write_text(SEED_NFO, encoding="utf-8")
    db_path = tmp_path / "openaver.db"
    init_db(db_path)
    video_uri = to_file_uri(str(video_path))
    VideoRepository(db_path).upsert(
        Video(
            path=video_uri,
            number="ABC-123",
            title="タイトル",
            nfo_mtime=nfo_path.stat().st_mtime,
        )
    )
    _wire_plot_router(monkeypatch, db_path, library)

    got = showcase_plot.get_video_plot(video_uri)
    assert got["success"] is True
    assert got["plot"] == JAPANESE_PLOT
    assert got["has_original"] is False

    saved = showcase_plot.write_video_plot(
        showcase_plot.PlotWritebackRequest(
            file_path=video_uri,
            plot=TRANSLATED_PLOT,
        )
    )
    assert saved["success"] is True
    assert saved["original_plot"] == JAPANESE_PLOT
    assert ET.fromstring(nfo_path.read_bytes()).findtext("plot") == TRANSLATED_PLOT
    assert VideoRepository(db_path).get_by_path(video_uri).nfo_mtime == pytest.approx(
        nfo_path.stat().st_mtime
    )

    nfo_path.unlink()
    missing = showcase_plot.get_video_plot(video_uri)
    assert missing["success"] is False
    assert missing["error"] == "no_nfo"


def test_plot_router_readonly_source_only_writes_output_nfo(monkeypatch, tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "output"
    source.mkdir()
    output.mkdir()
    video_path = source / "ABC-123.mp4"
    video_path.write_bytes(b"video")
    source_nfo = source / "ABC-123.nfo"
    output_nfo = output / "ABC-123.nfo"
    source_nfo.write_text(SEED_NFO, encoding="utf-8")
    output_nfo.write_text(SEED_NFO, encoding="utf-8")
    source_before = source_nfo.read_bytes()

    db_path = tmp_path / "openaver.db"
    init_db(db_path)
    video_uri = to_file_uri(str(video_path))
    VideoRepository(db_path).upsert(
        Video(
            path=video_uri,
            number="ABC-123",
            title="タイトル",
            nfo_mtime=output_nfo.stat().st_mtime,
            output_dir=to_file_uri(str(output)),
        )
    )
    _wire_plot_router(monkeypatch, db_path, source, output)

    saved = showcase_plot.write_video_plot(
        showcase_plot.PlotWritebackRequest(
            file_path=video_uri,
            plot=TRANSLATED_PLOT,
        )
    )

    assert saved["success"] is True
    assert source_nfo.read_bytes() == source_before
    assert ET.fromstring(output_nfo.read_bytes()).findtext("plot") == TRANSLATED_PLOT
