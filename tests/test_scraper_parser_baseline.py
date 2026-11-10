from __future__ import annotations

import re
from pathlib import Path

from core.custom_source.extract import extract_fields
from core.custom_source.schema import Field
from core.scrapers.dmm import DMMScraper
from core.scrapers.fc2_javten import FC2JavtenScraper
from core.scrapers.fc2_official import FC2OfficialScraper
from core.scrapers.heyzo import HEYZOScraper
from core.scrapers.models import ScraperConfig


FIXTURES = Path(__file__).parent / "fixtures" / "scrapers"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class _Response:
    def __init__(self, body: str, status_code: int = 200):
        self.content = body.encode("utf-8")
        self.status_code = status_code


def _bare_scraper(scraper_type, source_name: str):
    scraper = object.__new__(scraper_type)
    scraper.config = ScraperConfig(delay=0)
    scraper.source_name = source_name
    return scraper


def test_fc2_official_fixture_baseline():
    scraper = _bare_scraper(FC2OfficialScraper, "fc2")

    class FakeSession:
        def get(self, url: str, timeout: int):
            return _Response(_fixture("fc2_official.html"))

    scraper._session = FakeSession()

    video = scraper.search("FC2-PPV-1234567")

    assert video is not None
    assert video.number == "FC2-1234567"
    assert video.title == "Fixture FC2 Title"
    assert [actress.name for actress in video.actresses] == ["Fixture FC2 Seller"]
    assert video.date == "2024-05-01"
    assert video.maker == "Fixture FC2 Seller"
    assert video.cover_url == "https://cdn.example.test/fc2-cover.jpg"
    assert video.tags == ["Tag A", "Tag B"]
    assert video.sample_images == [
        "https://cdn.example.test/fc2-sample-1.jpg",
        "https://cdn.example.test/fc2-sample-2.jpg",
    ]
    assert video.rating == 4.5


def test_fc2_javten_fixture_baseline(monkeypatch):
    html = _fixture("fc2_javten.html")

    class FakeTransport:
        def navigate_and_settle(self, url: str, cache_key: str) -> str:
            assert url == "https://javten.com/search?kw=7654321"
            assert cache_key == "fc-javten"
            return "https://javten.com/video/123/id7654321/fixture"

        def fetch(self, url: str, cache_key: str) -> str:
            assert url == "https://javten.com/video/123/id7654321/fixture"
            assert cache_key == "fc-javten"
            return html

    monkeypatch.setattr(
        "core.scrapers.fc2_javten.get_cf_transport",
        lambda: FakeTransport(),
    )

    video = _bare_scraper(FC2JavtenScraper, "fc-javten").search("FC2-PPV-7654321")

    assert video is not None
    assert video.number == "FC2-7654321"
    assert video.title == "Fixture Javten Title"
    assert [actress.name for actress in video.actresses] == ["Fixture Javten Seller"]
    assert video.date == ""
    assert video.maker == "Fixture Javten Seller"
    assert video.cover_url == "https://cdn.example.test/javten-cover.jpg"
    assert video.tags == ["Tag A", "Tag B"]
    assert video.sample_images == [
        "https://cdn.example.test/javten-sample-1.jpg",
        "https://cdn.example.test/javten-sample-2.jpg",
    ]
    assert video.summary == "Fixture javten outline details."
    assert video.rating == 4.2


def test_heyzo_fixture_baseline():
    scraper = _bare_scraper(HEYZOScraper, "heyzo")

    class FakeSession:
        def get(self, url: str, timeout: int):
            assert url == "https://en.heyzo.com/moviepages/0783/index.html"
            return _Response(_fixture("heyzo_en.html"))

    scraper._session = FakeSession()

    video = scraper.search("HEYZO-0783")

    assert video is not None
    assert video.number == "HEYZO-0783"
    assert video.title == "Fixture HEYZO Title"
    assert [actress.name for actress in video.actresses] == [
        "Actress One",
        "Actress Two",
    ]
    assert video.date == "2024-06-01"
    assert video.maker == "HEYZO"
    assert video.cover_url == "https://cdn.example.test/heyzo-cover.jpg"
    assert video.tags == ["Tag A", "Tag B"]
    assert video.series == "Fixture Series"
    assert video.duration == 83
    assert video.sample_images == [
        "https://en.heyzo.com/contents/gallery/001.jpg",
        "https://en.heyzo.com/contents/gallery/002.jpg",
    ]
    assert video.summary == "Fixture HEYZO summary."
    assert video.rating == 4.25
    assert video.votes == 8


def test_dmm_json_ld_tags_fixture_baseline():
    scraper = _bare_scraper(DMMScraper, "dmm")

    class FakeSession:
        def get(self, url: str, timeout: int, cookies: dict):
            assert url.endswith("/cid=fixture001/")
            assert cookies == {"age_check_done": "1"}
            return _Response(_fixture("dmm_tags.html"))

    scraper._session = FakeSession()

    assert scraper._fetch_tags_from_html("fixture001") == [
        "DMM Genre A",
        "DMM Genre B",
    ]


def test_dmm_html_tags_fallback_fixture_baseline():
    scraper = _bare_scraper(DMMScraper, "dmm")

    class FakeSession:
        def get(self, url: str, timeout: int, cookies: dict):
            return _Response(_fixture("dmm_tags_fallback.html"))

    scraper._session = FakeSession()

    assert scraper._fetch_tags_from_html("fixture002") == [
        "Fallback Genre A",
        "Fallback Genre B",
    ]


def test_custom_source_fixture_baseline():
    fields = (
        Field("title", "css", "h1.title", None, False, ()),
        Field("cover", "css", "a.cover", "href", False, ()),
        Field("sample_images", "css", "a.sample", "href", True, ()),
        Field("tags", "css", ".tag", None, True, ()),
        Field("actors", "css", ".actress", None, True, ()),
        Field("date", "css", "time.date", None, False, ()),
        Field("duration", "css", ".duration", None, False, ()),
        Field("summary", "meta", "description", None, False, ()),
        Field("rating", "jsonld", "VideoObject.ratingValue", None, False, ()),
    )

    result = extract_fields(
        _fixture("custom_source.html"),
        "https://custom.example.test/video/ABC-123",
        fields,
    )

    assert result == {
        "title": "Fixture Custom Title",
        "cover": "https://custom.example.test/images/cover.jpg",
        "sample_images": [
            "https://custom.example.test/images/sample-1.jpg",
            "https://custom.example.test/images/sample-2.jpg",
        ],
        "tags": ["Tag A", "Tag B"],
        "actors": ["Actor One", "Actor Two"],
        "date": "2024-07-02",
        "duration": 90,
        "summary": "Fixture custom source summary.",
        "rating": "4.6",
    }


def test_runtime_and_build_do_not_depend_on_lxml():
    runtime_root = PROJECT_ROOT / "app" / "src" / "main" / "python"
    for path in runtime_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert re.search(r"(?m)^\s*(?:from|import)\s+lxml\b", source) is None, path
        assert re.search(
            r"BeautifulSoup\([^\n]*?[\"']lxml[\"']", source
        ) is None, path

    assert "lxml==" not in (PROJECT_ROOT / "app" / "build.gradle").read_text(
        encoding="utf-8"
    )
    assert "lxml==" not in (PROJECT_ROOT / "requirements-test.txt").read_text(
        encoding="utf-8"
    )
