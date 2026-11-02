from __future__ import annotations

from core.database import connection
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
