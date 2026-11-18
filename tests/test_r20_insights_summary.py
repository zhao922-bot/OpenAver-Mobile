import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_WEB = ROOT / "app/src/main/python/web"
LOCALES = ROOT / "app/src/main/python/locales"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_insights_brand_tile_is_removed():
    template = read(PYTHON_WEB / "templates/insights.html")

    assert "insights-brand-card" not in template
    assert "insights-brand-row" not in template
    assert template.count('class="card"') >= 4


def test_insights_summary_has_four_compact_mobile_tiles():
    template = read(PYTHON_WEB / "templates/insights.html")
    css = read(PYTHON_WEB / "static/css/pages/insights.css")

    assert 'class="row1 insights-summary-bar"' in template
    assert template.count("insights-summary-label") == 4
    assert "grid-template-columns: repeat(4, minmax(0, 1fr));" in css
    assert "min-height: 64px;" in css
    assert ".insights-container .insights-tile-sub" in css
    assert "display: none;" in css


def test_insights_summary_locales_are_complete():
    required = {"videos", "year", "actress", "maker"}

    for path in sorted(LOCALES.glob("*.json")):
        data = json.loads(read(path))
        assert required <= set(data["insights"]["summary"]), path.name


def test_insights_snapshot_uses_lightweight_projection_and_caches_by_etag(
    tmp_path,
    monkeypatch,
):
    from types import SimpleNamespace
    from core.database import connection
    from core.database.video import Video, VideoRepository
    from core.path_utils import to_file_uri
    from web.routers import insights as insights_router

    gallery_dir = tmp_path / "gallery"
    gallery_dir.mkdir()
    db_path = tmp_path / "openaver.db"
    connection._clear_db_init_cache()
    connection.init_db(db_path)
    repo = VideoRepository(db_path)
    repo.upsert(
        Video(
            path=to_file_uri(str(gallery_dir / "A-001.mp4")),
            number="A-001",
            release_date="2024-05-10",
            duration=120,
            actresses=["Actress A"],
            maker="Studio A",
            tags=["Tag 1"],
            sample_images=["file:///unused/sample1.jpg"],
        )
    )

    monkeypatch.setattr(insights_router, "get_db_path", lambda: db_path)
    monkeypatch.setattr(insights_router, "init_db", lambda _db=None: None)
    monkeypatch.setattr(
        insights_router,
        "load_config",
        lambda: {
            "gallery": {
                "directories": [{"path": str(gallery_dir)}],
                "path_mappings": {},
            }
        },
    )
    insights_router._clear_insights_snapshot_cache()

    calls = 0
    original_get_insights_rows = VideoRepository.get_insights_rows

    def counting_get_insights_rows(self, configured_dir_uris=None):
        nonlocal calls
        calls += 1
        return original_get_insights_rows(self, configured_dir_uris)

    monkeypatch.setattr(
        VideoRepository,
        "get_insights_rows",
        counting_get_insights_rows,
    )
    monkeypatch.setattr(
        insights_router,
        "_DEFAULT_GET_INSIGHTS_ROWS",
        counting_get_insights_rows,
    )
    monkeypatch.setattr(
        VideoRepository,
        "get_all",
        lambda _self: (_ for _ in ()).throw(
            AssertionError("get_all() should not be called by insights snapshot")
        ),
    )

    req = SimpleNamespace(headers={})
    resp_1 = insights_router.get_insights_snapshot(req)
    resp_2 = insights_router.get_insights_snapshot(req)

    body_1 = json.loads(resp_1.body)
    body_2 = json.loads(resp_2.body)
    assert calls == 1
    assert body_1 == body_2
    assert body_1["logicalTitles"] == 1
    assert body_1["records"][0]["year"] == 2024
    assert body_1["records"][0]["maker"] == "Studio A"

