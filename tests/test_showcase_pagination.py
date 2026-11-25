from __future__ import annotations

import json
from types import SimpleNamespace

from core.database import connection
from core.database.alias import AliasRepository
from core.database.video import Video, VideoRepository
from core.path_utils import to_file_uri
from web.routers import showcase as showcase_router


def _request():
    return SimpleNamespace(headers={})


def _prepare_repo(tmp_path):
    gallery_dir = tmp_path / "gallery"
    outside_dir = tmp_path / "outside"
    gallery_dir.mkdir()
    outside_dir.mkdir()
    db_path = tmp_path / "openaver.db"
    connection._clear_db_init_cache()
    connection.init_db(db_path)
    repo = VideoRepository(db_path)
    repo.upsert_batch([
        Video(
            path=to_file_uri(str(gallery_dir / "A-001.mp4")),
            number="A-001",
            title="First",
            release_date="2024-01-01",
        ),
        Video(
            path=to_file_uri(str(gallery_dir / "B-002.mp4")),
            number="B-002",
            title="Second",
            release_date="2024-02-01",
        ),
        Video(
            path=to_file_uri(str(outside_dir / "C-003.mp4")),
            number="C-003",
            title="Outside",
            release_date="2024-03-01",
        ),
    ])
    return db_path, gallery_dir


def _prepare_route(tmp_path, monkeypatch):
    db_path, gallery_dir = _prepare_repo(tmp_path)
    monkeypatch.setattr(showcase_router, "get_db_path", lambda: db_path)
    monkeypatch.setattr(showcase_router, "init_db", lambda _db_path=None: None)
    monkeypatch.setattr(
        showcase_router,
        "load_config",
        lambda: {
            "gallery": {
                "directories": [{"path": str(gallery_dir)}],
                "path_mappings": {},
            },
            "thumbnail_cache_enabled": False,
        },
    )
    monkeypatch.setattr(showcase_router, "get_showcase_revision", lambda: 1)
    monkeypatch.setattr(
        showcase_router,
        "compute_db_fingerprint",
        lambda _db_path: ("test",),
    )
    return db_path, gallery_dir


def test_showcase_sql_scope_filter_excludes_outside_rows(tmp_path, monkeypatch):
    _prepare_route(tmp_path, monkeypatch)

    response = showcase_router.get_videos(
        _request(),
        page=1,
        per_page=0,
        sort="date",
        order="desc",
        paged=False,
    )
    data = json.loads(response.body)

    assert response.status_code == 200
    assert data["success"] is True
    assert data["total"] == 2
    assert [video["number"] for video in data["videos"]] == ["A-001", "B-002"]


def test_showcase_server_pagination_returns_global_total_and_page(tmp_path, monkeypatch):
    _prepare_route(tmp_path, monkeypatch)

    response = showcase_router.get_videos(
        _request(),
        page=2,
        per_page=1,
        sort="date",
        order="asc",
        paged=True,
    )
    data = json.loads(response.body)

    assert response.status_code == 200
    assert data["paged"] is True
    assert data["total"] == 2
    assert data["page"] == 2
    assert data["per_page"] == 1
    assert data["total_pages"] == 2
    assert [video["number"] for video in data["videos"]] == ["B-002"]


def test_showcase_actress_filter_resolves_aliases_before_paging(tmp_path, monkeypatch):
    db_path, gallery_dir = _prepare_route(tmp_path, monkeypatch)
    repo = VideoRepository(db_path)
    repo.upsert_batch([
        Video(
            path=to_file_uri(str(gallery_dir / "C-003.mp4")),
            number="C-003",
            title="Alias Match",
            actresses=["Old Name"],
            release_date="2024-03-01",
        ),
        Video(
            path=to_file_uri(str(gallery_dir / "D-004.mp4")),
            number="D-004",
            title="Other Actress",
            actresses=["Other"],
            release_date="2024-04-01",
        ),
        Video(
            path=to_file_uri(str(gallery_dir / "E-005.mp4")),
            number="E-005",
            title="Alias Match Two",
            actresses=["Old Name"],
            release_date="2024-05-01",
        ),
    ])
    AliasRepository(db_path).add("New Name", ["Old Name"])

    response = showcase_router.get_videos(
        _request(),
        page=1,
        per_page=0,
        sort="date",
        order="desc",
        paged=False,
        actress="Old Name",
    )
    data = json.loads(response.body)

    assert response.status_code == 200
    assert data["success"] is True
    assert data["actress_filter"] == "Old Name"
    assert data["total"] == 2
    assert [video["number"] for video in data["videos"]] == ["C-003", "E-005"]

    paged_response = showcase_router.get_videos(
        _request(),
        page=2,
        per_page=1,
        sort="num",
        order="asc",
        paged=True,
        actress="Old Name",
    )
    paged_data = json.loads(paged_response.body)

    assert paged_response.status_code == 200
    assert paged_data["paged"] is True
    assert paged_data["total"] == 2
    assert paged_data["page"] == 2
    assert [video["number"] for video in paged_data["videos"]] == ["E-005"]


def test_showcase_sort_is_stable_for_equal_primary_keys():
    def group(path):
        return SimpleNamespace(
            members=[
                SimpleNamespace(
                    path=path,
                    release_date="2024-01-01",
                )
            ]
        )

    groups = [group("first"), group("second"), group("third")]

    assert [
        item.members[0].path
        for item in showcase_router._sort_groups(groups, "date", "asc")
    ] == ["first", "second", "third"]
    assert [
        item.members[0].path
        for item in showcase_router._sort_groups(groups, "date", "desc")
    ] == ["first", "second", "third"]


def test_showcase_pagination_reuses_in_memory_group_cache_and_invalidates_on_db_write(
    tmp_path,
    monkeypatch,
):
    db_path, gallery_dir = _prepare_route(tmp_path, monkeypatch)
    showcase_router._clear_showcase_groups_cache()

    calls = 0
    original_get_showcase_browse_rows = VideoRepository.get_showcase_browse_rows

    def counting_get_showcase_browse_rows(self, configured_dir_uris, actress_names=None):
        nonlocal calls
        calls += 1
        return original_get_showcase_browse_rows(self, configured_dir_uris, actress_names)

    monkeypatch.setattr(VideoRepository, "get_showcase_browse_rows", counting_get_showcase_browse_rows)
    monkeypatch.setattr(
        showcase_router,
        "_DEFAULT_GET_SHOWCASE_BROWSE_ROWS",
        counting_get_showcase_browse_rows,
    )

    page_1 = json.loads(
        showcase_router.get_videos(
            _request(),
            page=1,
            per_page=1,
            sort="date",
            order="asc",
            paged=True,
        ).body
    )
    page_2 = json.loads(
        showcase_router.get_videos(
            _request(),
            page=2,
            per_page=1,
            sort="num",
            order="desc",
            paged=True,
        ).body
    )

    assert calls == 1
    assert [v["number"] for v in page_1["videos"]] == ["A-001"]
    assert [v["number"] for v in page_2["videos"]] == ["A-001"]

    VideoRepository(db_path).upsert(
        Video(
            path=to_file_uri(str(gallery_dir / "D-004.mp4")),
            number="D-004",
            title="Fourth",
            release_date="2024-04-01",
        )
    )

    refreshed = json.loads(
        showcase_router.get_videos(
            _request(),
            page=1,
            per_page=1,
            sort="date",
            order="desc",
            paged=True,
        ).body
    )
    assert calls == 2
    assert refreshed["total"] == 3
    assert [v["number"] for v in refreshed["videos"]] == ["D-004"]


def test_serialize_video_evaluates_title_language_once_per_video(monkeypatch):
    calls = 0
    original_fn = showcase_router.title_needs_translation

    def counting_title_needs_translation(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_fn(*args, **kwargs)

    monkeypatch.setattr(
        showcase_router,
        "title_needs_translation",
        counting_title_needs_translation,
    )

    video = Video(
        path="file:///library/A-001.mp4",
        number="A-001",
        title="これは日本語のタイトルです",
        nfo_mtime=100.0,
    )
    serialized = showcase_router._serialize_video(video, {}, False, "zh-CN")

    assert calls == 1
    assert serialized["can_translate"] is True
    assert serialized["needs_translate"] is True


def test_shared_etag_helper_and_scanner_extras_delegation(tmp_path, monkeypatch):
    from web.routers import insights as insights_router
    from web.routers import scanner as scanner_router

    assert showcase_router._etag_matches is insights_router._etag_matches
    assert showcase_router._etag_matches('W/"abc", "def"', '"abc"') is True
    assert showcase_router._etag_matches('"xyz"', '"abc"') is False

    sub_dir = tmp_path / "Movies"
    sub_dir.mkdir()
    monkeypatch.setattr(
        scanner_router,
        "load_config",
        lambda: {"gallery": {"directories": [], "path_mappings": {}}},
    )
    result = scanner_router.browse_dir(path=str(tmp_path), expand=None)
    assert [entry["name"] for entry in result["entries"]] == ["Movies"]


