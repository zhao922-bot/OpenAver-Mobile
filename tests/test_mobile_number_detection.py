from __future__ import annotations

from pathlib import Path

from core.database import Video
from core.gallery_scanner import VideoScanner
from core.path_utils import to_file_uri
from web.routers import scanner as scanner_router


ROOT = Path(__file__).resolve().parents[1]


NEW_FILENAMES = (
    "DASS-092對無防備讓人看見黑褲襪的大姊巨臀推倒中出的我美谷朱里.mp4",
    "SSIS-465超對我性癖好我的超天菜的苗條美人教師美艷的黑絲襪和美腿緊夾&被用滿滿的足技無數次射精了星宮一花.mp4",
    "SSIS-469和青梅竹馬交往但其實女友姐姐一直都很喜歡我狂亂無內褲誘惑小宵虎南.mp4",
)


def test_video_scanner_accepts_cjk_text_directly_after_number():
    scanner = VideoScanner()

    assert scanner.find_num_from_filename(NEW_FILENAMES[0]) == "DASS-092"
    assert scanner.find_num_from_filename(NEW_FILENAMES[1]) == "SSIS-465"
    assert scanner.find_num_from_filename(NEW_FILENAMES[2]) == "SSIS-469"


def test_missing_check_recovers_number_from_existing_cjk_filename(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "openaver.db"
    db_path.touch()
    rows = [
        Video(
            path=f"file:///storage/5C43-83CA/JAV/folder/{name}",
            number=None,
            nfo_mtime=0,
            cover_path="",
            output_dir="",
            scrape_attempted_at=0,
        )
        for name in NEW_FILENAMES
    ]

    class FakeRepo:
        def __init__(self, _path):
            pass

        def get_all(self):
            return rows

    monkeypatch.setattr(scanner_router, "get_db_path", lambda: db_path)
    monkeypatch.setattr(scanner_router, "VideoRepository", FakeRepo)
    monkeypatch.setattr(
        scanner_router,
        "load_config",
        lambda: {"gallery": {"path_mappings": {}}},
    )

    result = scanner_router.check_missing()

    assert result["success"] is True
    data = result["data"]
    assert data["missing_both"] == 3
    assert data["missing_nfo"] == 0
    assert data["missing_cover"] == 0
    assert [item["number"] for item in data["items"]] == [
        "DASS-092",
        "SSIS-465",
        "SSIS-469",
    ]


def test_missing_results_expand_maintenance_for_visibility():
    batch = (
        ROOT / "app/src/main/python/web/static/js/pages/scanner/state-batch.js"
    ).read_text(encoding="utf-8")

    assert "this.maintenanceExpanded = true;" in batch


def test_missing_check_reports_nfo_after_a_failed_enrich_attempt(
    tmp_path,
    monkeypatch,
):
    video_file = tmp_path / "ABC-125.mp4"
    video_file.write_bytes(b"video")
    cover_file = tmp_path / "ABC-125.jpg"
    cover_file.write_bytes(b"cover")
    row = Video(
        path=to_file_uri(str(video_file)),
        number="ABC-125",
        title="Title",
        nfo_mtime=0,
        cover_path=to_file_uri(str(cover_file)),
        scrape_attempted_at=123,
    )

    class FakeRepo:
        def __init__(self, _path):
            pass

        def get_all(self):
            return [row]

    db_path = tmp_path / "openaver.db"
    db_path.touch()
    monkeypatch.setattr(scanner_router, "get_db_path", lambda: db_path)
    monkeypatch.setattr(scanner_router, "VideoRepository", FakeRepo)
    monkeypatch.setattr(
        scanner_router,
        "load_config",
        lambda: {"gallery": {"path_mappings": {}}},
    )

    result = scanner_router.check_missing()

    assert result["success"] is True
    assert result["data"]["missing_nfo"] == 1
    assert result["data"]["missing_both"] == 0
    assert result["data"]["items"][0]["category"] == "nfo"
