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
        cover_path="file:///old/video.jpg",
        sample_images=["file:///old/sample.jpg"],
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
    }]) is True
    assert calls == 1

    renamed = repo.get_by_path("file:///new/video.mp4")
    assert renamed is not None
    assert renamed.cover_path == "file:///new/video.jpg"
    assert renamed.sample_images == ["file:///new/sample.jpg"]
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
