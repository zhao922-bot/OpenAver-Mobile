from __future__ import annotations

from pathlib import Path

from core.path_utils import to_file_uri
from core.database import Video
from web.routers import showcase as showcase_router


def test_any_nonempty_title_is_available_for_manual_translation():
    assert showcase_router._can_manual_translate(  # noqa: SLF001
        "English title only", "", 0
    ) is True


def test_title_with_saved_original_uses_original_row_action():
    assert showcase_router._can_manual_translate(  # noqa: SLF001
        "中文标题", "Original title", 1
    ) is False


def test_title_translation_without_nfo_creates_nfo_and_saves_database(tmp_path):
    video_file = tmp_path / "ABC-123.mp4"
    video_file.write_bytes(b"video")
    video = Video(
        path=to_file_uri(str(video_file)),
        number="ABC-123",
        title="日本語タイトル",
    )
    calls = {}

    class FakeRepo:
        def update_titles(self, path, title, original_title, nfo_mtime):
            calls["path"] = path
            calls["title"] = title
            calls["original_title"] = original_title
            calls["nfo_mtime"] = nfo_mtime
            return True

    request = showcase_router.TitleWritebackRequest(
        file_path=video.path,
        title="中文标题",
    )

    result = showcase_router._apply_title_writeback(  # noqa: SLF001
        FakeRepo(),
        video,
        request,
        {"scraper": {"nfo_title_format": "[{num}]{title}"}},
        {},
    )

    assert result["success"] is True
    assert result["nfo_created"] is True
    assert result["nfo_updated"] is True
    assert calls["path"] == video.path
    assert "中文标题" in calls["title"]
    assert calls["original_title"] == "日本語タイトル"
    assert calls["nfo_mtime"] > 0

    nfo_path = Path(str(video_file.with_suffix(".nfo")))
    assert nfo_path.is_file()
    nfo_text = nfo_path.read_text(encoding="utf-8")
    assert "中文标题" in nfo_text
    assert "日本語タイトル" in nfo_text


def test_readonly_title_writeback_prefers_video_matching_nfo(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    video = Video(
        path=to_file_uri(str(tmp_path / "source" / "ABC-123.mp4")),
        output_dir=to_file_uri(str(output_dir)),
        number="ABC-123",
        title="日本語タイトル",
    )
    expected = output_dir / "ABC-123.nfo"
    other = output_dir / "OTHER-999.nfo"
    expected.write_text("<movie />", encoding="utf-8")
    other.write_text("<movie />", encoding="utf-8")

    found, error = showcase_router._locate_readonly_nfo(  # noqa: SLF001
        video,
        {},
        video.output_dir,
    )

    assert error is None
    assert found == str(expected)
