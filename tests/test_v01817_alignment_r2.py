from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from core import cover_upload, readonly_assets, readonly_paths
from core.cover_attributes import effective_tags, manifest_payload
from core.database import (
    Actress,
    ActressRepository,
    AliasRepository,
    Video,
    VideoRepository,
    init_db,
)
from core.database import actress_library, connection
from core.database.actress_library import get_favorite_actress_stats
from core.enricher import enrich_single
from core.gallery_scanner import VideoScanner
from core.organizer import organize_file
from core.path_utils import to_file_uri
from core.recent_actresses import search_recent_actresses
from core.recent_rules import FavStat, RecentRow, rank_recent, select_recent
from core.scrapers.actress import graphis_pool
from core.scrapers.actress.graphis_pool import (
    candidate_id,
    is_collectible_url,
    match_entries,
    parse_exclude,
    select_next,
)
from core.search_providers.dmm import ActorsPage
from core.search_providers.types import (
    Enriched,
    EntityRef,
    Kind,
    MakerSearchResult,
    WorkItem,
)
from web.routers import cover_badges as cover_badges_router
from web.routers import actress as actress_router
from web.routers import scraper as scraper_router


NOW = 1_800_000_000.0
DAY = 86400.0


def _jpeg(size=(40, 60), color=(200, 10, 10)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


def _oversized_png() -> bytes:
    buf = BytesIO()
    Image.new("1", (8000, 8000), 1).save(buf, format="PNG")
    return buf.getvalue()


def _db(tmp_path, monkeypatch):
    db_path = tmp_path / "openaver.db"
    init_db(db_path, force=True)
    monkeypatch.setattr(connection, "get_db_path", lambda: db_path)
    return db_path


def _organizer_config(**overrides):
    cfg = {
        "create_folder": True,
        "folder_layers": [],
        "folder_format": "{num}",
        "filename_format": "{num} {title}",
        "nfo_title_format": "{title}",
        "download_cover": False,
        "create_nfo": True,
        "max_title_length": 100,
        "max_filename_length": 120,
        "suffix_keywords": [],
        "external_manager": "off",
    }
    cfg.update(overrides)
    return cfg


def _manual_metadata(*, number="ABC-123", title="手動標題"):
    return {
        "number": number,
        "title": title,
        "translated_title": "中文標題",
        "actors": [],
        "tags": [],
        "maker": "",
        "date": "",
        "cover": "",
        "url": "",
        "manual_entry": True,
    }


def test_cover_upload_validation_and_token_trust_boundary(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setattr(cover_upload, "get_data_root", lambda: root)

    assert cover_upload.validate_and_normalize_cover(b"not an image" * 20)[1][0] == 415
    assert cover_upload.validate_and_normalize_cover(_oversized_png())[1][0] == 413

    png = BytesIO()
    Image.new("RGB", (40, 60), (1, 2, 3)).save(png, format="PNG")
    normalized, err = cover_upload.validate_and_normalize_cover(png.getvalue())
    assert err is None
    assert Image.open(BytesIO(normalized)).format == "JPEG"

    jpeg = _jpeg()
    token = cover_upload.store_cover(jpeg)
    assert re.fullmatch(r"[0-9a-f]{32}", token)
    stored = cover_upload.resolve_cover_token(token)
    assert stored is not None
    assert Path(stored).read_bytes() == jpeg

    for bad in (
        "../secret",
        "A" * 32,
        token + "\n",
        token[:-1],
        None,
        123,
    ):
        assert cover_upload.resolve_cover_token(bad) is None


def test_cover_upload_api_and_expiry_fail_closed(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setattr(cover_upload, "get_data_root", lambda: root)
    monkeypatch.setattr(scraper_router, "get_config_locale", lambda: "zh-CN")
    app = FastAPI()
    app.include_router(scraper_router.router)

    with TestClient(app) as client:
        bad = client.post(
            "/api/scrape-cover/upload",
            files={"file": ("cover.jpg", b"plain text", "image/jpeg")},
        )
        assert bad.status_code == 415

        good = client.post(
            "/api/scrape-cover/upload",
            files={"file": ("cover.jpg", _jpeg(), "image/jpeg")},
        )
        assert good.status_code == 200
        body = good.json()
        assert body["url"].endswith(body["token"])

        served = client.get(body["url"])
        assert served.status_code == 200
        assert served.headers["cache-control"] == "no-store"
        assert served.content == _jpeg()

        expired = client.get("/api/scrape-cover/" + "f" * 32)
        assert expired.status_code == 404


def test_manual_upload_survives_organize_and_generates_title_nfo(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "videos"
    root.mkdir()
    video = root / "ABC-123-U.ltx.mp4"
    video.write_bytes(b"video")
    uploaded = tmp_path / "uploaded.jpg"
    jpeg = _jpeg()
    uploaded.write_bytes(jpeg)

    metadata = _manual_metadata()
    result = organize_file(
        str(video),
        metadata,
        _organizer_config(),
        uploaded_cover=str(uploaded),
    )

    assert result["success"] is True
    assert result["title_source"] == "translated"
    assert Path(result["cover_path"]).read_bytes() == jpeg
    nfo = Path(result["nfo_path"]).read_text(encoding="utf-8")
    assert "中文標題" in nfo
    assert "<tag>無碼破解</tag>" in nfo
    assert "<tag>LTX</tag>" in nfo
    assert set(metadata["tags"]) >= {"無碼破解", "LTX"}


def test_ltx_is_applied_across_scanner_enricher_readonly_and_manifest(
    tmp_path,
    monkeypatch,
):
    _db(tmp_path, monkeypatch)
    filename = "ABC-123-U.ltx.mp4"

    scan_path = tmp_path / filename
    scan_path.write_bytes(b"video")
    scanned = VideoScanner().scan_file(str(scan_path))
    assert set(filter(None, scanned.genre.split(","))) >= {"無碼破解", "LTX"}

    enrich_path = tmp_path / f"enrich-{filename}"
    enrich_path.write_bytes(b"video")
    scraper_data = {
        "number": "ABC-123",
        "title": "source title",
        "actors": [],
        "tags": [],
        "maker": "",
        "date": "",
        "cover": "",
        "url": "",
        "sample_images": [],
    }
    enriched = enrich_single(
        file_path=str(enrich_path),
        number="ABC-123",
        mode="fill_missing",
        write_nfo=True,
        write_cover=False,
        scraper_data=scraper_data,
    )
    assert enriched.success is True
    enrich_nfo = enrich_path.with_suffix(".nfo").read_text(encoding="utf-8")
    assert "<tag>無碼破解</tag>" in enrich_nfo
    assert "<tag>LTX</tag>" in enrich_nfo

    source = tmp_path / filename
    movie_dir = tmp_path / "readonly-output"
    readonly_meta = {
        "number": "ABC-123",
        "title": "source title",
        "actors": [],
        "tags": [],
        "maker": "",
        "date": "",
        "cover": "",
        "url": "",
        "sample_images": [],
    }
    readonly_cfg = {
        "filename_format": "{num} {title}",
        "max_filename_length": 80,
        "max_title_length": 50,
        "suffix_keywords": [],
        "external_manager": "off",
        "download_sample_images": False,
    }
    formatted = readonly_paths._format_data(readonly_meta, str(source), readonly_cfg)
    readonly_assets._write_movie_assets(
        str(movie_dir),
        readonly_meta,
        formatted,
        str(source),
        readonly_cfg,
        cover_strategy=("none",),
    )
    readonly_nfo = next(movie_dir.glob("*.nfo")).read_text(encoding="utf-8")
    assert "<tag>無碼破解</tag>" in readonly_nfo
    assert "<tag>LTX</tag>" in readonly_nfo

    manifest = cover_badges_router.get_manifest()
    rules = {rule["id"]: rule for rule in manifest}
    assert rules["ltx"]["supersedes"] == ["cracked"]
    assert "LTX" in effective_tags(filename, [])
    assert "無碼破解" in effective_tags(filename, [])
    assert any(rule["id"] == "ltx" for rule in manifest_payload())


def test_graphis_candidate_rules_and_caches(monkeypatch):
    base = "https://data.graphis.ne.jp/free/model/"
    assert match_entries(
        [("a_miru", "miru"), ("b_emi", "桃瀬えみる")],
        {"miru"},
    ) == ["a_miru"]
    assert is_collectible_url(f"{base}E1/prof.jpg", "E1")
    assert is_collectible_url(f"{base}E1/photo/001/pic.jpg", "E1")
    assert not is_collectible_url(f"{base}E1/video/01/movs.jpg", "E1")
    assert not is_collectible_url(f"{base}E2/photo/001/pic.jpg", "E1")

    pool = [f"{base}e/photo/{i:03d}/pic.jpg" for i in range(1, 7)]
    first = select_next(pool, set(), 2)
    exclude = {candidate_id(url) for url in first}
    second = select_next(pool, exclude, 2)
    assert len(first) == len(second) == 2
    assert not exclude & {candidate_id(url) for url in second}
    assert parse_exclude(f"{next(iter(exclude))},bad,aaaaaaaa") == {
        next(iter(exclude)),
        "aaaaaaaa",
    }

    graphis_pool._SEARCH_CACHE.clear()
    graphis_pool._ENTRY_CACHE.clear()
    monkeypatch.setattr(
        graphis_pool,
        "_search_entries",
        lambda query, timeout: [("a", "miru"), ("b", "miru")],
    )
    monkeypatch.setattr(
        graphis_pool,
        "_fetch_entry_photos",
        lambda entry_id, timeout: [
            f"{base}{entry_id}/prof.jpg",
            f"{base}{entry_id}/photo/001/pic.jpg",
        ],
    )
    monkeypatch.setattr(
        graphis_pool,
        "_names_for",
        lambda person_key, query_name: {"miru"},
    )
    picked = graphis_pool.graphis_candidates(
        "miru",
        "miru",
        "local_crop",
        set(),
        rng=__import__("random").Random(1),
    )
    assert len(picked) == 6
    assert len(set(picked)) == 6


def test_photo_candidate_stream_prioritizes_two_graphis_and_deduplicates(monkeypatch):
    base = "https://data.graphis.ne.jp/free/model/e/photo"
    graphis_urls = [f"{base}/{i:03d}/pic.jpg" for i in range(1, 7)]
    monkeypatch.setattr(
        actress_router,
        "_load_actress",
        lambda _name: (
            None,
            SimpleNamespace(name="A", photo_source="local_crop"),
        ),
    )
    monkeypatch.setattr(
        actress_router,
        "graphis_candidates",
        lambda *_args, **_kwargs: graphis_urls,
    )
    monkeypatch.setattr(
        actress_router,
        "_fetch_single_source",
        lambda _name, source: f"https://example.com/{source}.jpg",
    )
    monkeypatch.setattr(
        actress_router,
        "_get_random_videos_with_covers",
        lambda _name, _count, _exclude: [
            SimpleNamespace(
                path="file:///video/ABC-123.mp4",
                cover_path="file:///video/ABC-123.jpg",
            )
        ],
    )

    async def collect():
        response = await actress_router.list_photo_candidates("A", 0, "")
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    body = asyncio.run(collect())
    candidates = [
        json.loads(line[6:])
        for line in body.splitlines()
        if line.startswith("data: ") and '"total"' not in line
    ]
    assert len(candidates) == 6
    assert len({item["id"] for item in candidates}) == 6
    assert sum(item["source"] == "graphis" for item in candidates) >= 2
    assert sum(item["source"] in {"gfriends", "wiki", "xcity"} for item in candidates) <= 3
    assert any(item["source"] == "local_crop" for item in candidates)


def test_recent_score_counts_complete_multipart_group_once(tmp_path, monkeypatch):
    db_path = _db(tmp_path, monkeypatch)
    repo = ActressRepository(db_path)
    repo.save(Actress(name="A"))
    VideoRepository(db_path).upsert(
        Video(
            path=to_file_uri(str(tmp_path / "ABC-123-cd1.mp4")),
            number="ABC-123",
            title="part 1",
            actresses=["A"],
            mtime=NOW - 10 * DAY,
        )
    )
    VideoRepository(db_path).upsert(
        Video(
            path=to_file_uri(str(tmp_path / "ABC-123-cd2.mp4")),
            number="ABC-123",
            title="part 2",
            actresses=["A"],
            mtime=NOW - 10 * DAY,
        )
    )
    VideoRepository(db_path).upsert(
        Video(
            path=to_file_uri(str(tmp_path / "XYZ-456.mp4")),
            number="XYZ-456",
            title="other",
            actresses=["A"],
            mtime=NOW - 120 * DAY,
        )
    )

    monkeypatch.setattr(
        actress_library,
        "VideoRepository",
        lambda: VideoRepository(db_path),
    )
    monkeypatch.setattr(
        actress_library,
        "load_config",
        lambda: {"gallery": {"path_mappings": {}}},
    )

    stats = get_favorite_actress_stats(now=NOW)
    expected = 0.5 ** (10 / 120) + 0.5
    assert stats["A"].video_count == 2
    assert stats["A"].score == pytest.approx(expected)


def test_recent_filter_rules_and_ranking():
    now = datetime(2026, 10, 29, tzinfo=timezone(timedelta(hours=9)))

    def row(cid, days=1, actors=1, upcoming=False, when="auto"):
        release = now - timedelta(days=days) if when == "auto" else when
        return RecentRow(cid, release, upcoming, actors)

    kept, cutoff = select_recent(
        [
            row("future", -200, upcoming=True),
            row("missing", when=None, upcoming=True),
            row("old", 200),
            row("edge", 90),
            row("too_many", 2, actors=5),
        ],
        now,
        set(),
    )
    assert [item.content_id for item in kept] == ["future", "missing", "edge"]
    assert cutoff is False

    values = [
        FavStat("top", 1, 10.0),
        FavStat("tie-high", 8, 5.0),
        FavStat("tie-low", 2, 5.0),
        FavStat("zero", 99, 0.0),
    ]
    assert [item.name for item in rank_recent(values, 3)] == [
        "top",
        "tie-high",
        "tie-low",
    ]


class _RecentProvider:
    def __init__(self, known, pages=(), fail_page=None, fail_resolve=False):
        self.known = set(known)
        self.pages = list(pages)
        self.fail_page = fail_page
        self.fail_resolve = fail_resolve
        self.calls = []

    def resolve(self, kind, name):
        if self.fail_resolve:
            raise RuntimeError("unreachable")
        if name not in self.known:
            return None
        return EntityRef(Kind.ACTOR, f"{name}-id", name)

    def list_actors_page(self, refs, window, now, seen):
        self.calls.append(([ref.label for ref in refs], window.offset))
        if self.fail_page == len(self.calls):
            raise RuntimeError("unreachable")
        return self.pages[len(self.calls) - 1]

    def enrich(self, item, ref=None):
        return Enriched({"number": item.number}, None)


def _recent_page(numbers, raw=None, has_next=False, cutoff=True):
    items = [WorkItem(number, "title", "", "", None, "dmm") for number in numbers]
    return ActorsPage(items, len(items) if raw is None else raw, has_next, cutoff)


def test_recent_actress_search_error_codes_and_pagination():
    stats = {
        f"a{i:02d}": FavStat(f"a{i:02d}", 3, 20.0 - i)
        for i in range(12)
    }

    empty = search_recent_actresses(
        now=datetime(2026, 10, 29, tzinfo=timezone.utc),
        provider=_RecentProvider(set()),
        stats=stats,
    )
    assert empty == MakerSearchResult([], False, "recent_region_empty")

    none = search_recent_actresses(
        now=datetime(2026, 10, 29, tzinfo=timezone.utc),
        provider=_RecentProvider(set(stats), [_recent_page([], raw=3)]),
        stats=stats,
    )
    assert none == MakerSearchResult([], False, "recent_none")

    provider = _RecentProvider(
        set(stats),
        [
            _recent_page(["A-1"], has_next=True, cutoff=False),
            _recent_page(["B-1"]),
        ],
    )
    found = search_recent_actresses(
        now=datetime(2026, 10, 29, tzinfo=timezone.utc),
        provider=provider,
        stats=stats,
    )
    assert found.error_code is None
    assert [card["number"] for card in found.results] == ["A-1", "B-1"]
    assert [offset for _, offset in provider.calls] == [0, 100]


def test_scrape_single_consumes_uploaded_token_only_after_success(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "data"
    monkeypatch.setattr(cover_upload, "get_data_root", lambda: root)
    token = cover_upload.store_cover(_jpeg())
    video = tmp_path / "ABC-123.mp4"
    video.write_bytes(b"video")

    monkeypatch.setattr(
        scraper_router,
        "load_config",
        lambda: {
            "general": {"locale": "zh-CN"},
            "scraper": _organizer_config(download_cover=False),
            "gallery": {},
        },
    )
    monkeypatch.setattr(scraper_router, "get_config_locale", lambda _cfg=None: "zh-CN")
    monkeypatch.setattr(scraper_router, "_readonly_source_error", lambda _path: None)
    monkeypatch.setattr(
        scraper_router,
        "organize_file",
        lambda *_args, **_kwargs: {
            "success": True,
            "new_filename": str(tmp_path / "ABC-123" / "ABC-123 title.mp4"),
        },
    )
    monkeypatch.setattr(
        scraper_router,
        "try_inflow_upsert",
        lambda *_args, **_kwargs: "not_linked",
    )
    monkeypatch.setattr(
        scraper_router.organize_failures,
        "clear_on_success",
        lambda _number: None,
    )

    body = scraper_router.scrape_single(
        scraper_router.ScrapeRequest(
            file_path=str(video),
            number="ABC-123",
            metadata=_manual_metadata(),
            cover_upload_token=token,
        )
    )
    assert body["success"] is True
    assert cover_upload.resolve_cover_token(token) is None


def test_mobile_user_tag_link_is_wired_to_metadata_search():
    template = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "src"
        / "main"
        / "python"
        / "web"
        / "templates"
        / "showcase.html"
    ).read_text(encoding="utf-8")
    assert "searchFromMetadata(tag, 'tag')" in template
