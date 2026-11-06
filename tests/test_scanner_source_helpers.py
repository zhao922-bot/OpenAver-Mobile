from __future__ import annotations

from types import SimpleNamespace

from web.routers import scanner as scanner_module


def _drain_generator(generator):
    events = []
    while True:
        try:
            events.append(next(generator))
        except StopIteration as stopped:
            return events, stopped.value


class _FakeRepo:
    db_path = ":memory:"

    def __init__(self):
        self.deleted_paths = []
        self.upserted = []

    def get_mtime_index(self):
        return {}

    def get_by_paths(self, paths):
        return {}

    def upsert_batch(self, videos):
        self.upserted.extend(videos)
        return len(videos), 0

    def delete_by_paths(self, paths):
        self.deleted_paths.extend(paths)
        return len(paths)

    def get_empty_focal_candidates(self, paths):
        return []


def test_scan_regular_source_returns_counters_and_upserts(tmp_path, monkeypatch):
    video = tmp_path / "ABC-123.mp4"
    video.write_bytes(b"video")
    repo = _FakeRepo()
    scanner = SimpleNamespace(
        scan_file=lambda path, _: {"path": path, "title": "Example"}
    )
    monkeypatch.setattr(
        scanner_module,
        "fast_scan_directory",
        lambda *args, **kwargs: [{
            "path": str(video),
            "mtime": 10,
            "nfo_mtime": 0,
        }],
    )
    monkeypatch.setattr(
        scanner_module,
        "get_video_extensions",
        lambda config: {".mp4"},
    )
    monkeypatch.setattr(
        scanner_module,
        "scan_entry_needs_refresh",
        lambda db_entry, file_info, mappings: True,
    )
    monkeypatch.setattr(
        scanner_module.Video,
        "from_video_info",
        lambda info: SimpleNamespace(
            path=scanner_module.to_file_uri(info["path"], {}),
            mtime=0,
            nfo_mtime=0,
        ),
    )

    events, stats = _drain_generator(
        scanner_module._scan_regular_source(
            directory=str(tmp_path),
            normalized_dir=str(tmp_path),
            scanner=scanner,
            repo=repo,
            config={},
            min_size_mb=0,
            path_mappings={},
            should_abort=None,
        )
    )

    assert stats["inserted"] == 1
    assert stats["updated"] == 0
    assert stats["deleted"] == 0
    assert stats["scan_errors"] == 0
    assert stats["session_added_paths"] == [
        scanner_module.to_file_uri(str(video), {})
    ]
    assert len(repo.upserted) == 1
    assert any("ABC-123.mp4" in event for event in events)


def test_partial_scan_skips_deletion_detection(tmp_path, monkeypatch):
    repo = _FakeRepo()
    blocked = tmp_path / "blocked.mp4"

    def fake_fast_scan(_root, _extensions, _min_size, on_skip):
        on_skip(str(blocked), PermissionError("denied"))
        return []

    monkeypatch.setattr(
        scanner_module,
        "fast_scan_directory",
        fake_fast_scan,
    )
    monkeypatch.setattr(
        scanner_module,
        "get_video_extensions",
        lambda config: {".mp4"},
    )

    events, stats = _drain_generator(
        scanner_module._scan_regular_source(
            directory=str(tmp_path),
            normalized_dir=str(tmp_path),
            scanner=SimpleNamespace(),
            repo=repo,
            config={},
            min_size_mb=0,
            path_mappings={},
            should_abort=None,
        )
    )

    assert repo.deleted_paths == []
    assert stats["deleted"] == 0
    assert any("跳过删除检测" in event for event in events)


def test_submit_focal_candidates_respects_abort(monkeypatch):
    class Repo:
        db_path = ":memory:"

        def get_empty_focal_candidates(self, paths):
            return [
                ("file:///a.mp4", "ABC-123", "Maker", "file:///a.jpg"),
                ("file:///b.mp4", "ABC-124", "Maker", "file:///b.jpg"),
            ]

    calls = []
    monkeypatch.setattr(
        scanner_module,
        "requires_face_detection",
        lambda number, maker: True,
    )
    monkeypatch.setattr(
        scanner_module,
        "maybe_submit_video_focal",
        lambda *args, **kwargs: calls.append(args),
    )

    scanner_module._submit_focal_candidates(
        Repo(),
        {"file:///a.mp4", "file:///b.mp4"},
        {},
        should_abort=lambda: len(calls) >= 1,
    )

    assert len(calls) == 1
