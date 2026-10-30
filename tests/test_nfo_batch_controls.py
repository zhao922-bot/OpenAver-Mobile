from __future__ import annotations

from core.nfo_updater import update_videos_generator


def _cache_entry(number: str) -> dict:
    return {
        "nfo_mtime": 1,
        "info": {
            "title": "",
            "date": "2024-01-01",
            "actor": "Actor",
            "genre": "Genre",
            "maker": "Maker",
            "num": number,
            "director": "Director",
            "duration": 120,
            "series": "",
            "label": "",
        },
    }


def test_nfo_update_backs_up_before_fill(tmp_path, monkeypatch):
    video = tmp_path / "ABC-126.mp4"
    video.write_bytes(b"video")
    nfo = tmp_path / "ABC-126.nfo"
    original = (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<movie><title></title><premiered>2024-01-01</premiered>"
        "<actor><name>Actor</name></actor><genre>Genre</genre>"
        "<studio>Maker</studio><director>Director</director>"
        "<runtime>120</runtime></movie>"
    )
    nfo.write_text(original, encoding="utf-8")

    monkeypatch.setattr(
        "core.nfo_updater.search_jav",
        lambda _number: {"title": "Filled title"},
    )

    generator = update_videos_generator(
        {str(video): _cache_entry("ABC-126")},
        [str(video)],
        backup=True,
    )
    events = []
    while True:
        try:
            events.append(next(generator))
        except StopIteration as stop:
            stats = stop.value
            break

    backup = tmp_path / "ABC-126.nfo.openaver-backup"
    assert stats["success"] == 1
    assert stats["backed_up"] == 1
    assert backup.read_text(encoding="utf-8") == original
    assert "<title>Filled title</title>" in nfo.read_text(encoding="utf-8")


def test_nfo_update_cancels_before_next_item(tmp_path):
    video = tmp_path / "ABC-127.mp4"
    video.write_bytes(b"video")
    (tmp_path / "ABC-127.nfo").write_text(
        '<?xml version="1.0" encoding="utf-8"?><movie><title></title></movie>',
        encoding="utf-8",
    )

    generator = update_videos_generator(
        {str(video): _cache_entry("ABC-127")},
        [str(video)],
        should_abort=lambda: True,
    )
    try:
        next(generator)
    except StopIteration as stop:
        stats = stop.value
    else:
        raise AssertionError("cancelled generator should stop before yielding")
    assert stats["cancelled"] is True
    assert stats["success"] == 0
