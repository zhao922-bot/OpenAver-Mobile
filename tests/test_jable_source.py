from __future__ import annotations

import pytest

from core.cf_handoff import CF_SITE_NETLOCS, CF_SITE_ORIGINS
from core.cf_transport import CfChallengeRequired
from core.scrapers.jable import JABLE_ORIGIN, JableScraper, parse_detail
from core.source_config import get_manual_only_sources
from core.source_probe import MANUAL_ONLY_IDS, scraper_class_for


DETAIL_HTML = """
<!doctype html>
<html>
<head>
  <title>SSIS-448 Fixture Title - Jable.TV</title>
  <meta property="og:title" content="SSIS-448 Fixture Title">
  <meta property="og:image" content="https://assets-cdn.jable.tv/contents/videos_screenshots/52000/52882/preview.jpg">
  <meta name="description" content="Fixture summary">
</head>
<body>
  <div class="info-header">
    <h4>SSIS-448 Fixture Title</h4>
    <span class="inactive-color">2.4M views 2024-05-01</span>
    <div class="models">
      <a class="model" href="/models/actor-one/"><span class="placeholder rounded-circle" title="Actor One"></span></a>
      <a class="model" href="/models/actor-two/"><img class="avatar rounded-circle" title="Actor Two"></a>
    </div>
  </div>
  <video poster="https://assets-cdn.jable.tv/contents/videos_screenshots/52000/52882/preview.jpg"></video>
  <span class="duration">2:05:00</span>
  <h5 class="tags"><a href="/tags/tag-a/">Tag A</a><a href="/tags/tag-b/">Tag B</a></h5>
  <div class="recommendations">
    <a href="/videos/other-001/">
      <img data-src="https://assets-cdn.jable.tv/contents/videos_screenshots/53000/53882/320x180/1.jpg">
    </a>
  </div>
</body>
</html>
"""


def test_parse_detail_extracts_jable_metadata():
    fields = parse_detail(
        DETAIL_HTML,
        "SSIS-448",
        "https://jable.tv/videos/ssis-448/",
    )

    assert fields is not None
    assert fields["title"] == "Fixture Title"
    assert fields["date"] == "2024-05-01"
    assert fields["duration"] == 125
    assert fields["actresses"] == ["Actor One", "Actor Two"]
    assert fields["tags"] == ["Tag A", "Tag B"]
    assert fields["summary"] == "Fixture summary"
    assert fields["cover_url"].endswith("/preview.jpg")
    assert fields["sample_images"] == []


def test_parse_detail_does_not_treat_recommendation_images_as_samples():
    html = DETAIL_HTML.replace(
        "</body>",
        """
        <img src="https://assets-cdn.jable.tv/assets/images/logo.png">
        <img src="https://assets-cdn.jable.tv/contents/models/32/actress.jpg">
        <img data-src="//assets-cdn.jable.tv/contents/videos_screenshots/54000/54882/320x180/1.jpg">
        </body>""",
    )

    fields = parse_detail(html, "SSIS-448", "https://jable.tv/videos/ssis-448/")

    assert fields is not None
    assert fields["sample_images"] == []


def test_parse_detail_ignores_navigation_tags_when_video_tags_exist():
    html = DETAIL_HTML.replace(
        "</body>",
        """
        <nav class="site-tags">
          <a href="/tags/cosplay/">Cosplay</a>
          <a href="/tags/stockings/">Stockings</a>
        </nav>
        <section class="video-info">
          <h5 class="tags">
            <a class="cat" href="/categories/chinese-subtitle/">Chinese subtitle</a>
            <a href="/tags/video-tag/">Video Tag</a>
          </h5>
        </section>
        </body>""",
    )

    fields = parse_detail(html, "SSIS-448", "https://jable.tv/videos/ssis-448/")

    assert fields is not None
    assert fields["tags"] == ["Chinese subtitle", "Video Tag"]


def test_parse_detail_detects_cloudflare_challenge():
    html = "<html><head><title>Just a moment...</title></head><body></body></html>"

    with pytest.raises(CfChallengeRequired):
        parse_detail(html, "SSIS-448", "https://jable.tv/videos/ssis-448/")


def test_parse_detail_returns_none_for_real_404():
    html = "<html><head><title>404 Not Found - Jable.TV</title></head><body></body></html>"

    assert parse_detail(html, "SSIS-448", "https://jable.tv/videos/ssis-448/") is None


def test_search_uses_jable_cf_transport(monkeypatch):
    calls: list[tuple[str, str]] = []

    class FakeTransport:
        def fetch(self, url: str, cache_key: str) -> str:
            calls.append((url, cache_key))
            return DETAIL_HTML

    monkeypatch.setattr(
        "core.scrapers.jable.get_cf_transport",
        lambda: FakeTransport(),
    )

    video = JableScraper().search("ssis448")

    assert video is not None
    assert video.source == "jable"
    assert video.number == "SSIS-448"
    assert video.title == "Fixture Title"
    assert calls == [("https://jable.tv/videos/ssis-448/", "jable")]


def test_jable_is_registered_as_manual_cloudflare_source():
    manual = {source.id: source for source in get_manual_only_sources()}

    assert "jable" in MANUAL_ONLY_IDS
    assert manual["jable"].manual_only is True
    assert manual["jable"].is_censored is True
    assert manual["jable"].display_name_key == "Jable"
    assert scraper_class_for("jable") is JableScraper
    assert CF_SITE_ORIGINS["jable"] == JABLE_ORIGIN
    assert "jable.tv" in CF_SITE_NETLOCS["jable"]
