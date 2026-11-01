from __future__ import annotations

import os

from core import organizer


def test_compute_organize_paths_preserves_suffix_vr_and_part_tokens(tmp_path):
    target_dir, filename_base, target_path = organizer._compute_organize_paths(
        str(tmp_path),
        ".mp4",
        {
            "create_folder": True,
            "folder_layers": ["{maker}", "{actor}"],
            "filename_format": "{num} {title} {suffix}",
            "max_filename_length": 80,
        },
        {
            "number": "ABC-123",
            "title": "Example",
            "actors": ["Actor"],
            "maker": "Maker",
            "date": "2026-01-01",
            "suffix": "-4k",
        },
        "_VR",
        "-cd2",
    )

    assert target_dir == os.path.join(str(tmp_path), "Maker", "Actor")
    assert filename_base.endswith("-4k_VR-cd2")
    assert target_path == os.path.join(target_dir, filename_base + ".mp4")


def test_collect_folder_fallbacks_reports_missing_values():
    fallbacks = organizer._collect_folder_fallbacks(
        {
            "create_folder": True,
            "folder_layers": ["{actor}", "{maker}", "{date}", "{title}"],
        },
        {
            "actors": [],
            "maker": "",
            "date": "",
            "title": "",
        },
    )

    assert fallbacks == ["女優", "片商", "日期", "標題"]
