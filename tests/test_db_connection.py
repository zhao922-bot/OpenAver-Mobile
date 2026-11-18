from __future__ import annotations

from core.database import Video, connection
from core.database.video import VideoRepository


def test_init_db_is_idempotent_per_database_path(tmp_path, monkeypatch):
    db_path = tmp_path / "openaver.db"
    connection._clear_db_init_cache()
    connection.init_db(db_path)

    calls = 0
    original_get_connection = connection.get_connection

    def counting_get_connection(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_get_connection(*args, **kwargs)

    monkeypatch.setattr(connection, "get_connection", counting_get_connection)

    connection.init_db(db_path)
    assert calls == 0

    connection.init_db(db_path, force=True)
    assert calls == 1


def test_get_all_reuses_one_connection_for_rows_and_columns(tmp_path, monkeypatch):
    db_path = tmp_path / "openaver.db"
    connection._clear_db_init_cache()
    connection.init_db(db_path)
    repo = VideoRepository(db_path)

    calls = 0
    original_get_connection = repo._get_connection

    def counting_get_connection():
        nonlocal calls
        calls += 1
        return original_get_connection()

    monkeypatch.setattr(repo, "_get_connection", counting_get_connection)

    assert repo.get_all() == []
    assert calls == 1


def test_apply_rename_batch_updates_path_cover_and_samples_in_one_connection(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "openaver.db"
    connection._clear_db_init_cache()
    connection.init_db(db_path)
    repo = VideoRepository(db_path)
    repo.upsert(Video(
        path="file:///old/video.mp4",
        title="舊標題",
        original_title="舊原文",
        cover_path="file:///old/video.jpg",
        sample_images=["file:///old/sample.jpg"],
        nfo_mtime=1,
    ))

    calls = 0
    original_get_connection = repo._get_connection

    def counting_get_connection():
        nonlocal calls
        calls += 1
        return original_get_connection()

    monkeypatch.setattr(repo, "_get_connection", counting_get_connection)

    assert repo.apply_rename_batch([{
        "db_old_uri": "file:///old/video.mp4",
        "db_new_uri": "file:///new/video.mp4",
        "cover_path_old": "file:///old/video.jpg",
        "cover_path_new": "file:///new/video.jpg",
        "sample_images_old": ["file:///old/sample.jpg"],
        "sample_images_new": ["file:///new/sample.jpg"],
        "title_old": "舊標題",
        "title_new": "新しいタイトル",
        "original_title_old": "舊原文",
        "original_title_new": "",
        "title_update": True,
        "nfo_mtime_update": True,
        "nfo_mtime_new": 42.5,
    }]) is True
    assert calls == 1

    renamed = repo.get_by_path("file:///new/video.mp4")
    assert renamed is not None
    assert renamed.cover_path == "file:///new/video.jpg"
    assert renamed.sample_images == ["file:///new/sample.jpg"]
    assert renamed.title == "新しいタイトル"
    assert renamed.original_title == ""
    assert renamed.nfo_mtime == 42.5
    assert repo.get_by_path("file:///old/video.mp4") is None


def test_apply_rename_batch_rolls_back_on_target_collision(tmp_path):
    db_path = tmp_path / "openaver.db"
    connection._clear_db_init_cache()
    connection.init_db(db_path)
    repo = VideoRepository(db_path)
    repo.upsert(Video(path="file:///library/old.mp4"))
    repo.upsert(Video(path="file:///library/taken.mp4"))

    assert repo.apply_rename_batch([{
        "db_old_uri": "file:///library/old.mp4",
        "db_new_uri": "file:///library/taken.mp4",
    }]) is False

    assert repo.get_by_path("file:///library/old.mp4") is not None
    assert repo.get_by_path("file:///library/taken.mp4") is not None


def test_repath_reuses_single_connection_for_update_and_collision_merge(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "openaver.db"
    connection._clear_db_init_cache()
    connection.init_db(db_path)
    repo = VideoRepository(db_path)
    repo.upsert(
        Video(
            path="file:///library/old.mp4",
            number="A-001",
            user_tags=["tag-old"],
        )
    )
    repo.set_user_rating("file:///library/old.mp4", 1)

    calls = 0
    original_get_connection = repo._get_connection

    def counting_get_connection():
        nonlocal calls
        calls += 1
        return original_get_connection()

    monkeypatch.setattr(repo, "_get_connection", counting_get_connection)

    repo.repath(
        "file:///library/old.mp4",
        "file:///library/new.mp4",
        Video(
            path="file:///library/new.mp4",
            number="A-001",
            user_tags=["tag-new"],
        ),
    )
    assert calls == 1
    moved = repo.get_by_path("file:///library/new.mp4")
    assert moved is not None
    assert moved.user_tags == ["tag-old", "tag-new"]
    assert moved.user_rating == 1

    # Prepare collision merge (branch 3)
    repo.upsert(
        Video(
            path="file:///library/source.mp4",
            number="A-001",
            user_tags=["tag-src"],
        )
    )
    calls = 0
    repo.repath(
        "file:///library/source.mp4",
        "file:///library/new.mp4",
        Video(
            path="file:///library/new.mp4",
            number="A-001",
            user_tags=["tag-incoming"],
        ),
    )
    assert calls == 1
    merged = repo.get_by_path("file:///library/new.mp4")
    assert merged is not None
    assert merged.user_tags == ["tag-src", "tag-old", "tag-new", "tag-incoming"]
    assert repo.get_by_path("file:///library/source.mp4") is None


def test_get_connection_skips_redundant_wal_pragma_after_initialization(tmp_path):
    db_path = tmp_path / "openaver.db"
    connection._clear_db_init_cache()
    connection.init_db(db_path)

    conn = connection.get_connection(db_path)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
        assert connection._wal_file_key(db_path) in connection._wal_enabled_files
    finally:
        conn.close()


