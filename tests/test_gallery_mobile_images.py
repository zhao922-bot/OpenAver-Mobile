from __future__ import annotations

from core.gallery_generator import HTMLGenerator
from core.gallery_scanner import VideoInfo


def test_generated_gallery_resolves_file_images_and_includes_user_tags(tmp_path):
    output = tmp_path / "gallery.html"
    generator = HTMLGenerator()
    generator.generate(
        [
            VideoInfo(
                path="file:///video.mp4",
                title="ABC-123 Title",
                num="ABC-123",
                genre="Tag A",
                img="file:////storage/emulated/0/video.jpg",
                user_tags=["User tag"],
            )
        ],
        str(output),
    )

    html = output.read_text(encoding="utf-8")
    assert "function resolveImageSrc" in html
    assert "/api/gallery/image?path=" in html
    assert 'utags:"User tag"' in html
