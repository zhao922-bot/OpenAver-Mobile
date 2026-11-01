from pathlib import Path

from core.gallery_scanner import fast_scan_directory


def test_fast_scan_directory_honors_recursive_flag(tmp_path):
    root_video = tmp_path / "ROOT-001.mp4"
    nested_dir = tmp_path / "nested"
    nested_dir.mkdir()
    nested_video = nested_dir / "NEST-001.mp4"
    root_video.write_bytes(b"root")
    nested_video.write_bytes(b"nested")

    recursive = fast_scan_directory(str(tmp_path), {".mp4"})
    flat = fast_scan_directory(
        str(tmp_path),
        {".mp4"},
        recursive=False,
    )

    assert {Path(item["path"]).name for item in recursive} == {
        root_video.name,
        nested_video.name,
    }
    assert {Path(item["path"]).name for item in flat} == {root_video.name}
