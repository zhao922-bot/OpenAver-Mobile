from __future__ import annotations

import json
import os
from pathlib import Path

from core.database import Video
from core.path_utils import to_file_uri
from core.rename_normalizer import (
    build_combined_rename_plan,
    build_folder_rename_plan,
    build_rename_plan,
    canonicalize_source_stem,
    canonicalize_stem,
    execute_combined_rename_plan,
    execute_folder_rename_plan,
    execute_rename_plan,
    validate_combined_rename_plan,
)

ROOT = Path(__file__).resolve().parents[1]


class FakeRepo:
    def __init__(self):
        self.paths: set[str] = set()
        self.cover_updates: list[tuple[str, str, str]] = []
        self.sample_updates: list[tuple[str, list[str]]] = []
        self.repath_calls: list[tuple[str, str]] = []

    def repath_path_only(self, old_uri: str, new_uri: str) -> bool:
        self.repath_calls.append((old_uri, new_uri))
        if new_uri in self.paths:
            return False
        self.paths.discard(old_uri)
        self.paths.add(new_uri)
        return True

    def update_cover_path_preserve_focal(
        self, path: str, new_cover: str, old_cover: str
    ) -> bool:
        self.cover_updates.append((path, new_cover, old_cover))
        return True

    def update_sample_images(self, path: str, sample_images: list[str]) -> bool:
        self.sample_updates.append((path, sample_images))
        return True


def test_canonicalize_stem_inserts_space_without_changing_title():
    assert canonicalize_stem("ABC123標題")[0] == "ABC-123 標題"
    assert canonicalize_stem("ABC_123 - 標題")[0] == "ABC-123 標題"
    assert canonicalize_stem("ABC-123標題")[0] == "ABC-123 標題"
    assert canonicalize_stem("ABC-123 標題")[0] == "ABC-123 標題"
    assert canonicalize_stem("ABC-123 標題...") == (
        "ABC-123 標題...",
        "ABC-123",
        "unchanged",
    )


def test_canonicalize_source_stem_sanitizes_and_removes_duplicate_number():
    assert canonicalize_source_stem(
        "ABC-123",
        "ABC-123 新標題 / 第二段：完結?",
    ) == (
        "ABC-123 新標題 ／ 第二段：完結？",
        "ABC-123",
        "source_title",
    )
    assert canonicalize_source_stem("ABC-123", "  ") == (
        None,
        "ABC-123",
        "empty_title",
    )


def test_preview_renames_video_and_sidecars_but_not_folder_or_key(tmp_path):
    folder = tmp_path / "ABC123 原始資料夾"
    folder.mkdir()
    video = folder / "ABC123標題.mp4"
    nfo = folder / "ABC123標題.nfo"
    cover = folder / "ABC123標題.jpg"
    poster = folder / "ABC123標題-poster.jpg"
    fanart = folder / "ABC123標題-fanart.jpg"
    subtitle = folder / "ABC123標題.chs.srt"
    aes_key = folder / "aes.key"
    extrafanart = folder / "extrafanart"
    extrafanart.mkdir()
    extra = extrafanart / "fanart1.jpg"
    for path in (video, nfo, cover, poster, fanart, subtitle, aes_key, extra):
        path.write_bytes(path.name.encode("utf-8"))

    row = Video(
        path=to_file_uri(str(video)),
        number=None,
        cover_path=to_file_uri(str(cover)),
    )
    plan = build_rename_plan([row], config={})
    item = plan["items"][0]

    assert plan["summary"]["rename_videos"] == 1
    assert plan["summary"]["conflicts"] == 0
    assert item["new_name"] == "ABC-123 標題.mp4"
    assert item["cover_path_new"] == to_file_uri(
        str(folder / "ABC-123 標題.jpg")
    )
    renamed_names = {op["old_name"]: op["new_name"] for op in item["operations"]}
    assert renamed_names == {
        "ABC123標題.mp4": "ABC-123 標題.mp4",
        "ABC123標題.nfo": "ABC-123 標題.nfo",
        "ABC123標題.jpg": "ABC-123 標題.jpg",
        "ABC123標題-poster.jpg": "ABC-123 標題-poster.jpg",
        "ABC123標題-fanart.jpg": "ABC-123 標題-fanart.jpg",
        "ABC123標題.chs.srt": "ABC-123 標題.chs.srt",
    }
    assert "aes.key" not in renamed_names
    assert "fanart1.jpg" not in renamed_names
    assert folder.exists()


def test_preview_rejects_target_conflict(tmp_path):
    source = tmp_path / "ABC123標題.mp4"
    target = tmp_path / "ABC-123 標題.mp4"
    source.write_bytes(b"source")
    target.write_bytes(b"existing")

    plan = build_rename_plan(
        [Video(path=to_file_uri(str(source)), number="ABC-123")],
        config={},
    )

    assert plan["summary"]["rename_videos"] == 0
    assert plan["summary"]["conflicts"] == 1
    assert any(
        conflict.startswith("target_exists:")
        for conflict in plan["items"][0]["conflicts"]
    )


def test_file_plan_id_ignores_external_storage_mtime_churn(tmp_path):
    video = tmp_path / "ABC123標題.mp4"
    video.write_bytes(b"video")
    row = Video(path=to_file_uri(str(video)), number="ABC-123")

    first = build_rename_plan([row], config={})
    stat = video.stat()
    os.utime(video, ns=(stat.st_atime_ns, stat.st_mtime_ns + 9_000_000))
    second = build_rename_plan([row], config={})

    assert first["plan_id"] == second["plan_id"]


def test_preview_repairs_missing_path_and_fits_android_name_limit(tmp_path):
    expected_stem = "ABC-123 " + ("長" * 100)
    expected_video = tmp_path / f"{expected_stem}.mp4"
    actual_stem = "ABC-123 " + ("長" * 60)
    actual_video = tmp_path / f"{actual_stem}.mp4"
    actual_cover = tmp_path / f"{actual_stem}.jpg"
    actual_nfo = tmp_path / f"{actual_stem}.nfo"
    actual_poster = tmp_path / f"{actual_stem}-poster.jpg"
    actual_fanart = tmp_path / f"{actual_stem}-fanart.jpg"
    for path in (
        actual_video,
        actual_cover,
        actual_nfo,
        actual_poster,
        actual_fanart,
    ):
        path.write_bytes(path.name.encode("utf-8"))

    row = Video(
        path=to_file_uri(str(expected_video)),
        number="ABC-123",
        cover_path=to_file_uri(str(actual_cover)),
    )
    plan = build_rename_plan([row], config={})
    item = plan["items"][0]

    assert plan["summary"]["missing"] == 0
    assert plan["summary"]["rename_videos"] == 1
    assert item["recovered_missing_source"] is True
    assert item["old_name"] == actual_video.name
    assert item["reason"] == "repair_and_rename"
    assert len(item["operations"]) == 5
    assert all(len(op["new_name"].encode("utf-8")) <= 255 for op in item["operations"])
    target_stem = item["new_name"][:-len(actual_video.suffix)]
    assert target_stem.endswith("...")
    assert item["cover_path_new"].endswith(
        Path(target_stem + actual_cover.suffix).name
    )


def test_preview_treats_enametoolong_database_path_as_missing(
    tmp_path,
    monkeypatch,
):
    expected_video = tmp_path / f"ABC-123 {'長' * 100}.mp4"
    actual_video = tmp_path / f"ABC-123 {'長' * 60}.mp4"
    actual_video.write_bytes(b"video")
    original_is_file = Path.is_file

    def guarded_is_file(path, *args, **kwargs):
        if path == expected_video:
            raise OSError(36, "File name too long")
        return original_is_file(path, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", guarded_is_file)
    plan = build_rename_plan(
        [Video(path=to_file_uri(str(expected_video)), number="ABC-123")],
        config={},
    )

    assert plan["summary"]["missing"] == 0
    assert plan["items"][0]["status"] == "ready"
    assert plan["items"][0]["recovered_missing_source"] is True


def test_preview_repairs_truncated_cover_when_database_has_full_name(tmp_path):
    expected_stem = "ABC-123 " + ("長" * 100)
    expected_video = tmp_path / f"{expected_stem}.mp4"
    expected_cover = tmp_path / f"{expected_stem}.jpg"
    actual_stem = "ABC-123 " + ("長" * 60)
    actual_video = tmp_path / f"{actual_stem}.mp4"
    actual_cover = tmp_path / f"{actual_stem}.jpg"
    for path in (actual_video, actual_cover):
        path.write_bytes(path.name.encode("utf-8"))

    plan = build_rename_plan(
        [Video(
            path=to_file_uri(str(expected_video)),
            number="ABC-123",
            cover_path=to_file_uri(str(expected_cover)),
        )],
        config={},
    )
    item = plan["items"][0]

    assert item["status"] == "ready"
    assert item["recovered_missing_source"] is True
    assert item["cover_path_old"] == to_file_uri(str(expected_cover))
    assert item["cover_path_new"] == to_file_uri(
        str(tmp_path / (Path(item["new_name"]).stem + ".jpg"))
    )


def test_preserved_truncation_marker_is_idempotent(tmp_path):
    stem = "ABC-123 " + ("長" * 60) + "..."
    video = tmp_path / f"{stem}.mp4"
    cover = tmp_path / f"{stem}.jpg"
    for path in (video, cover):
        path.write_bytes(path.name.encode("utf-8"))

    plan = build_rename_plan(
        [Video(
            path=to_file_uri(str(video)),
            number="ABC-123",
            cover_path=to_file_uri(str(cover)),
        )],
        config={},
    )
    item = plan["items"][0]

    assert plan["summary"]["rename_videos"] == 0
    assert plan["summary"]["conflicts"] == 0
    assert item["status"] == "unchanged"
    assert item["new_name"] == video.name


def test_execute_repairs_truncated_file_when_database_already_has_target_path(tmp_path):
    expected_stem = "ABC-123 " + ("長" * 60)
    expected_video = tmp_path / f"{expected_stem}.mp4"
    actual_stem = "ABC-123 " + ("長" * 50)
    actual_video = tmp_path / f"{actual_stem}.mp4"
    actual_video.write_bytes(b"video")
    target_uri = to_file_uri(str(expected_video))
    plan = build_rename_plan(
        [Video(path=target_uri, number="ABC-123")],
        config={},
    )
    item = plan["items"][0]

    repo = FakeRepo()
    repo.paths.add(target_uri)
    result = execute_rename_plan(
        plan,
        repo,
        manifest_dir=tmp_path / "manifests",
    )

    assert item["db_old_uri"] == item["db_new_uri"] == target_uri
    assert result["success"] is True
    assert expected_video.is_file()
    assert not actual_video.exists()
    assert repo.repath_calls == []


def test_execute_renames_files_and_updates_database_paths(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    video = folder / "ABC123標題.mp4"
    nfo = folder / "ABC123標題.nfo"
    cover = folder / "ABC123標題.jpg"
    for path in (video, nfo, cover):
        path.write_bytes(path.name.encode("utf-8"))

    old_uri = to_file_uri(str(video))
    old_cover_uri = to_file_uri(str(cover))
    plan = build_rename_plan(
        [Video(path=old_uri, number="ABC-123", cover_path=old_cover_uri)],
        config={},
    )
    repo = FakeRepo()
    repo.paths.add(old_uri)

    result = execute_rename_plan(
        plan,
        repo,
        manifest_dir=tmp_path / "manifests",
    )

    assert result["success"] is True
    assert (folder / "ABC-123 標題.mp4").read_bytes()
    assert (folder / "ABC-123 標題.nfo").read_bytes()
    assert (folder / "ABC-123 標題.jpg").read_bytes()
    assert not video.exists()
    assert to_file_uri(str(folder / "ABC-123 標題.mp4")) in repo.paths
    assert repo.cover_updates == [(
        to_file_uri(str(folder / "ABC-123 標題.mp4")),
        to_file_uri(str(folder / "ABC-123 標題.jpg")),
        old_cover_uri,
    )]
    assert Path(result["manifest_path"]).is_file()


def test_execute_rolls_back_when_database_update_fails(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    video = folder / "ABC123標題.mp4"
    video.write_bytes(b"video")
    plan = build_rename_plan(
        [Video(path=to_file_uri(str(video)), number="ABC-123")],
        config={},
    )

    class FailingRepo(FakeRepo):
        def repath_path_only(self, old_uri: str, new_uri: str) -> bool:
            return False

    result = execute_rename_plan(
        plan,
        FailingRepo(),
        manifest_dir=tmp_path / "manifests",
    )

    assert result["success"] is False
    assert result["rollback_ok"] is True
    assert video.is_file()
    assert not (folder / "ABC-123 標題.mp4").exists()


def test_folder_preview_rebases_video_cover_and_sample_paths(tmp_path):
    source = tmp_path / "library"
    folder = source / "ABC123標題"
    folder.mkdir(parents=True)
    video = folder / "ABC123標題.mp4"
    cover = folder / "ABC123標題.jpg"
    sample = folder / "extrafanart" / "fanart1.jpg"
    sample.parent.mkdir()
    for path in (video, cover, sample):
        path.write_bytes(path.name.encode("utf-8"))

    row = Video(
        path=to_file_uri(str(video)),
        number="ABC-123",
        cover_path=to_file_uri(str(cover)),
        sample_images=[to_file_uri(str(sample))],
    )
    plan = build_folder_rename_plan(
        [row],
        source_roots=[str(source)],
        path_mappings={},
    )
    item = plan["items"][0]

    assert plan["summary"]["rename_folders"] == 1
    assert plan["summary"]["rename_videos"] == 1
    assert item["new_name"] == "ABC-123 標題"
    assert item["videos"][0]["db_new_uri"] == to_file_uri(
        str(source / "ABC-123 標題" / "ABC123標題.mp4")
    )
    assert item["videos"][0]["cover_path_new"] == to_file_uri(
        str(source / "ABC-123 標題" / "ABC123標題.jpg")
    )
    assert item["videos"][0]["sample_images_new"] == [
        to_file_uri(str(source / "ABC-123 標題" / "extrafanart" / "fanart1.jpg"))
    ]


def test_execute_folder_rename_updates_database_paths_without_renaming_files(tmp_path):
    source = tmp_path / "library"
    folder = source / "ABC123標題"
    folder.mkdir(parents=True)
    video = folder / "ABC123標題.mp4"
    cover = folder / "ABC123標題.jpg"
    sample = folder / "extrafanart" / "fanart1.jpg"
    sample.parent.mkdir()
    for path in (video, cover, sample):
        path.write_bytes(path.name.encode("utf-8"))

    old_uri = to_file_uri(str(video))
    old_cover_uri = to_file_uri(str(cover))
    old_sample_uri = to_file_uri(str(sample))
    plan = build_folder_rename_plan(
        [Video(
            path=old_uri,
            number="ABC-123",
            cover_path=old_cover_uri,
            sample_images=[old_sample_uri],
        )],
        source_roots=[str(source)],
        path_mappings={},
    )
    repo = FakeRepo()
    repo.paths.add(old_uri)

    result = execute_folder_rename_plan(
        plan,
        repo,
        manifest_dir=tmp_path / "manifests",
    )

    new_folder = source / "ABC-123 標題"
    new_uri = to_file_uri(str(new_folder / "ABC123標題.mp4"))
    assert result["success"] is True
    assert result["renamed_folders"] == 1
    assert new_folder.is_dir()
    assert (new_folder / "ABC123標題.mp4").is_file()
    assert not (new_folder / "ABC-123 標題.mp4").exists()
    assert new_uri in repo.paths
    assert repo.cover_updates == [(
        new_uri,
        to_file_uri(str(new_folder / "ABC123標題.jpg")),
        old_cover_uri,
    )]
    assert repo.sample_updates == [(
        new_uri,
        [to_file_uri(str(new_folder / "extrafanart" / "fanart1.jpg"))],
    )]
    assert Path(result["manifest_path"]).is_file()


def test_combined_plan_renames_files_and_folder_from_source_title(tmp_path):
    source = tmp_path / "library"
    folder = source / "ABC123 舊名稱"
    sample = folder / "extrafanart" / "fanart1.jpg"
    sample.parent.mkdir(parents=True)
    video = folder / "ABC123 舊名稱.mp4"
    nfo = folder / "ABC123 舊名稱.nfo"
    cover = folder / "ABC123 舊名稱.jpg"
    poster = folder / "ABC123 舊名稱-poster.jpg"
    for path in (video, nfo, cover, poster, sample):
        path.write_bytes(path.name.encode("utf-8"))

    old_uri = to_file_uri(str(video))
    old_cover_uri = to_file_uri(str(cover))
    old_sample_uri = to_file_uri(str(sample))
    row = Video(
        path=old_uri,
        number="ABC-123",
        cover_path=old_cover_uri,
        sample_images=[old_sample_uri],
        size_bytes=video.stat().st_size,
    )
    plan = build_combined_rename_plan(
        [row],
        source_id="javbus",
        stem_overrides={old_uri: "ABC-123 來源新標題"},
        source_roots=[str(source)],
        path_mappings={},
        config={},
    )
    item = plan["items"][0]

    assert plan["summary"]["conflicts"] == 0
    assert plan["summary"]["rename_folders"] == 1
    assert plan["summary"]["rename_videos"] == 1
    assert item["new_name"] == "ABC-123 來源新標題"
    new_folder = source / "ABC-123 來源新標題"
    assert item["videos"][0]["db_new_uri"] == to_file_uri(
        str(new_folder / "ABC-123 來源新標題.mp4")
    )
    assert item["videos"][0]["cover_path_new"] == to_file_uri(
        str(new_folder / "ABC-123 來源新標題.jpg")
    )
    assert item["videos"][0]["sample_images_new"] == [
        to_file_uri(str(new_folder / "extrafanart" / "fanart1.jpg"))
    ]
    assert validate_combined_rename_plan(plan) is True

    repo = FakeRepo()
    repo.paths.add(old_uri)
    result = execute_combined_rename_plan(
        plan,
        repo,
        manifest_dir=tmp_path / "manifests",
    )

    assert result["success"] is True
    assert new_folder.is_dir()
    assert (new_folder / "ABC-123 來源新標題.mp4").is_file()
    assert (new_folder / "ABC-123 來源新標題.nfo").is_file()
    assert (new_folder / "ABC-123 來源新標題.jpg").is_file()
    assert (new_folder / "ABC-123 來源新標題-poster.jpg").is_file()
    assert (new_folder / "extrafanart" / "fanart1.jpg").is_file()
    assert not folder.exists()
    assert to_file_uri(str(new_folder / "ABC-123 來源新標題.mp4")) in repo.paths
    assert repo.cover_updates == [(
        to_file_uri(str(new_folder / "ABC-123 來源新標題.mp4")),
        to_file_uri(str(new_folder / "ABC-123 來源新標題.jpg")),
        old_cover_uri,
    )]
    assert repo.sample_updates == [(
        to_file_uri(str(new_folder / "ABC-123 來源新標題.mp4")),
        [to_file_uri(str(new_folder / "extrafanart" / "fanart1.jpg"))],
    )]


def test_combined_plan_validation_detects_changed_source_size(tmp_path):
    source = tmp_path / "library"
    folder = source / "ABC123 舊名稱"
    folder.mkdir(parents=True)
    video = folder / "ABC123 舊名稱.mp4"
    video.write_bytes(b"video")
    old_uri = to_file_uri(str(video))
    plan = build_combined_rename_plan(
        [Video(path=old_uri, number="ABC-123")],
        source_id="javbus",
        stem_overrides={old_uri: "ABC-123 來源新標題"},
        source_roots=[str(source)],
        path_mappings={},
        config={},
    )

    video.write_bytes(b"changed after preview")

    assert validate_combined_rename_plan(plan) is False


def test_combined_execute_rolls_back_files_when_folder_rename_fails(tmp_path):
    source = tmp_path / "library"
    folder = source / "ABC123 舊名稱"
    folder.mkdir(parents=True)
    video = folder / "ABC123 舊名稱.mp4"
    nfo = folder / "ABC123 舊名稱.nfo"
    cover = folder / "ABC123 舊名稱.jpg"
    for path in (video, nfo, cover):
        path.write_bytes(path.name.encode("utf-8"))
    old_uri = to_file_uri(str(video))
    plan = build_combined_rename_plan(
        [Video(
            path=old_uri,
            number="ABC-123",
            cover_path=to_file_uri(str(cover)),
        )],
        source_id="javbus",
        stem_overrides={old_uri: "ABC-123 來源新標題"},
        source_roots=[str(source)],
        path_mappings={},
        config={},
    )
    repo = FakeRepo()
    repo.paths.add(old_uri)

    def fail_folder_rename(_source, _target):
        raise OSError("folder rename failed")

    result = execute_combined_rename_plan(
        plan,
        repo,
        manifest_dir=tmp_path / "manifests",
        folder_rename_fn=fail_folder_rename,
    )

    assert result["success"] is False
    assert result["rollback_ok"] is True
    assert folder.is_dir()
    assert video.is_file()
    assert nfo.is_file()
    assert cover.is_file()
    assert not (folder / "ABC-123 來源新標題.mp4").exists()
    assert repo.paths == {old_uri}
    assert repo.cover_updates == []


def test_folder_execute_rolls_back_when_database_update_fails(tmp_path):
    source = tmp_path / "library"
    folder = source / "ABC123標題"
    folder.mkdir(parents=True)
    video = folder / "ABC123標題.mp4"
    video.write_bytes(b"video")
    plan = build_folder_rename_plan(
        [Video(path=to_file_uri(str(video)), number="ABC-123")],
        source_roots=[str(source)],
        path_mappings={},
    )

    class FailingRepo(FakeRepo):
        def repath_path_only(self, old_uri: str, new_uri: str) -> bool:
            return False

    result = execute_folder_rename_plan(
        plan,
        FailingRepo(),
        manifest_dir=tmp_path / "manifests",
    )

    assert result["success"] is False
    assert result["rollback_ok"] is True
    assert folder.is_dir()
    assert not (source / "ABC-123 標題").exists()


def test_rename_locales_cover_preview_and_execution_states():
    required = {
        "row_title",
        "row_hint",
        "source_row_title",
        "source_row_hint",
        "source_select_label",
        "source_preview_btn",
        "source_previewing",
        "source_modal_title",
        "source_modal_intro",
        "source_used",
        "source_failed",
        "source_execute_btn",
        "source_execute_success",
        "preview_done",
        "plan_expired",
        "folder_row_title",
        "folder_row_hint",
        "preview_btn",
        "preview_loading",
        "folder_preview_btn",
        "folder_preview_loading",
        "modal_title",
        "folder_modal_title",
        "summary_videos",
        "summary_folders",
        "summary_files",
        "summary_conflicts",
        "modal_intro",
        "folder_modal_intro",
        "modal_note",
        "folder_related_videos",
        "conflict_title",
        "no_changes",
        "folder_no_changes",
        "copy_btn",
        "execute_btn",
        "folder_execute_btn",
        "executing_btn",
        "folder_executing_btn",
        "execute_success",
        "folder_execute_success",
        "plan_changed",
        "execute_rolled_back",
        "execute_rolled_back_detail",
    }
    for path in sorted((ROOT / "app/src/main/python/locales").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert required <= set(data["scanner"]["rename"]), path.name
        assert "aes.key" not in data["scanner"]["rename"]["modal_intro"], path.name
