from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from core.metatube.probe import (
    METATUBE_KNOWN_FAILING,
    classify_provider,
    probe_all,
)
from core.metatube.state import MetatubeConnectionState
from core.scraper import search_jav
from core.scrapers.d2pass import D2PassScraper, is_d2pass_number
from core.scrapers.jav321 import JAV321Scraper
from core.scrapers.javdb import JavDBScraper
from core.scrapers.models import ScraperConfig


ROOT = Path(__file__).resolve().parents[1]
PYTHON_WEB = ROOT / "app/src/main/python/web"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _bare_scraper(scraper_type, source_name: str):
    scraper = object.__new__(scraper_type)
    scraper.config = ScraperConfig(delay=0)
    scraper.source_name = source_name
    return scraper


def _first_hit_card(**overrides):
    card = {
        "number": "ABC-123",
        "title": "FIRST",
        "actors": ["女優A"],
        "cover": "https://example.com/c.jpg",
        "date": "2024-01-01",
        "maker": "SOD",
        "series": "系列",
        "label": "LABEL",
        "tags": ["タグ1"],
        "sample_images": [],
        "duration": 120,
        "url": "https://example.com/ABC-123",
        "source": "dmm",
        "_mode": "exact",
    }
    card.update(overrides)
    return card


def _fanout_recorder(calls):
    def _rec(*_args, **_kwargs):
        calls.append(True)
        return []

    return _rec


@pytest.mark.parametrize("has_original_title", [False, True])
def test_first_hit_exact_stops_after_first_usable_source(has_original_title):
    card = _first_hit_card(
        **({"original_title": "ORIGINAL"} if has_original_title else {})
    )
    fanout_calls: list[bool] = []

    with (
        patch("core.scraper.smart_search", return_value=[card]),
        patch(
            "core.scraper.get_enabled_source_ids",
            side_effect=_fanout_recorder(fanout_calls),
        ),
        patch("core.scraper.is_uncensored_mode_effective", return_value=False),
        patch("core.scraper.load_config", return_value={}),
    ):
        result = search_jav("ABC-123", first_hit=True)

    assert result is not None
    assert result["title"] == "FIRST"
    assert "_mode" not in result
    assert result["original_title"] == (
        "ORIGINAL" if has_original_title else "FIRST"
    )
    assert fanout_calls == []


def test_first_hit_not_found_does_not_run_auto_fanout():
    fanout_calls: list[bool] = []

    with (
        patch("core.scraper.smart_search", return_value=[]),
        patch(
            "core.scraper.get_enabled_source_ids",
            side_effect=_fanout_recorder(fanout_calls),
        ),
        patch("core.scraper.is_uncensored_mode_effective", return_value=False),
        patch("core.scraper.load_config", return_value={}),
    ):
        assert search_jav("ABC-123", first_hit=True) is None

    assert fanout_calls == []


def test_first_hit_falls_back_for_partial_or_inapplicable_queries():
    fanout_calls: list[bool] = []

    with (
        patch(
            "core.scraper.smart_search",
            return_value=[_first_hit_card(_mode="partial", title="PARTIAL")],
        ),
        patch(
            "core.scraper.get_enabled_source_ids",
            side_effect=_fanout_recorder(fanout_calls),
        ),
        patch("core.scraper.is_uncensored_mode_effective", return_value=False),
        patch("core.scraper.load_config", return_value={}),
    ):
        assert search_jav("ABC-123", first_hit=True) is None

    assert len(fanout_calls) == 1


def test_enrich_dispatch_only_uses_first_hit_for_missing_nfo_categories():
    from web.routers.scraper import _enrich_dispatch

    assert _enrich_dispatch("fill_missing", "both") == ("refresh_full", True)
    assert _enrich_dispatch("fill_missing", "nfo") == ("refresh_full", True)
    assert _enrich_dispatch("fill_missing", "cover") == ("fill_missing", False)
    assert _enrich_dispatch("refresh_full", "nfo") == ("refresh_full", False)
    assert _enrich_dispatch("db_to_sidecar", "both") == ("db_to_sidecar", False)


def test_batch_router_preserves_first_hit_instead_of_prefetching_fanout():
    source = _read(PYTHON_WEB / "routers/scraper.py")

    assert 'if batch.mode == "refresh_full":' in source
    assert "mode=item_mode," in source
    assert "first_hit=item_first_hit," in source


def test_android_release_line_and_user_visible_version_are_aligned():
    gradle = _read(ROOT / "app/build.gradle")
    release_line = re.search(
        r'def openaverRelease = "(v0\.18\.17-r\d+)"', gradle
    )
    version_code = re.search(r"versionCode (\d+)", gradle)
    version_name = re.search(r'versionName "(0\.18\.17-r\d+)"', gradle)
    assert release_line is not None
    assert version_code is not None
    assert version_name is not None
    assert release_line.group(1) == f"v{version_name.group(1)}"
    assert int(version_code.group(1)) >= 18001

    for relative in (
        "values/strings.xml",
        "values-en/strings.xml",
        "values-ja/strings.xml",
        "values-zh/strings.xml",
        "values-zh-rTW/strings.xml",
    ):
        strings = _read(ROOT / "app/src/main/res" / relative)
        assert f"OpenAver Mobile {release_line.group(1)}" in strings
        assert "Upstream release %2$s" not in strings

    activity = _read(
        ROOT / "app/src/main/java/dev/openaver/mobile/MainActivity.java"
    )
    assert "cascadePath, BuildConfig.VERSION_NAME" in activity

    boot = _read(ROOT / "app/src/main/python/openaver_boot.py")
    assert "mobile_version: str = \"\"" in boot
    assert 'os.environ["OPENAVER_MOBILE_VERSION"] = mobile_version' in boot
    web_app = _read(ROOT / "app/src/main/python/web/app.py")
    assert 'os.environ.get("OPENAVER_MOBILE_VERSION", VERSION)' in web_app


def test_r1_library_manager_terms_replace_old_generator_labels():
    locale_root = ROOT / "app/src/main/python/locales"
    forbidden = {
        "zh_CN.json": ("列表生成", "Scanner"),
        "zh_TW.json": ("列表生成", "Scanner"),
        "ja.json": ("リスト生成", "Scanner"),
        "en.json": ("Open scanner", "List Generation page"),
    }
    for filename, terms in forbidden.items():
        payload = json.loads((locale_root / filename).read_text(encoding="utf-8"))
        text = json.dumps(payload, ensure_ascii=False)
        for term in terms:
            assert term not in text, f"{filename} still contains {term}"


def test_d2pass_number_gate_rejects_regular_numbers_without_requests(monkeypatch):
    accepted = {
        "011225_01",
        "070116-197",
        "120415_201",
        "082912_01",
        "122211_01",
        "051515-877",
    }
    rejected = {
        "IPZZ-943",
        "SSIS-001",
        "300MIUM-123",
        "FC2-123456",
        "HEYZO-1234",
        "N0762",
    }

    assert all(is_d2pass_number(number) for number in accepted)
    assert not any(is_d2pass_number(number) for number in rejected)

    scraper = _bare_scraper(D2PassScraper, "d2pass")
    scraper._session = None
    calls = {"json": 0, "html": 0}

    monkeypatch.setattr(
        scraper,
        "_fetch_json",
        lambda *_args, **_kwargs: calls.__setitem__("json", calls["json"] + 1),
    )
    monkeypatch.setattr(
        scraper,
        "_parse_caribbeancom_html",
        lambda *_args, **_kwargs: calls.__setitem__(
            "html", calls["html"] + 1
        ),
    )

    assert scraper.search("IPZZ-943") is None
    assert calls == {"json": 0, "html": 0}


def test_d2pass_number_gate_keeps_date_based_searches(monkeypatch):
    scraper = _bare_scraper(D2PassScraper, "d2pass")
    scraper._session = None
    calls = {"json": 0}

    def no_result(*_args, **_kwargs):
        calls["json"] += 1
        return None

    monkeypatch.setattr(scraper, "_fetch_json", no_result)
    monkeypatch.setattr(scraper, "_parse_caribbeancom_html", lambda *_a, **_k: None)

    assert scraper.search("011225_01") is None
    assert calls["json"] >= 1


def test_metatube_unknown_providers_stay_available_and_failures_skip_probe(
    monkeypatch,
):
    names = ["BRAND_NEW", "JAV321"]
    state = MetatubeConnectionState()
    generation = state.connect("http://metatube.invalid", "", names)

    def unexpected_client(*_args, **_kwargs):
        raise AssertionError("known/unknown providers must not be probed")

    monkeypatch.setattr(
        "core.metatube.probe.MetatubeHttpClient",
        unexpected_client,
    )

    result = probe_all(
        "http://metatube.invalid",
        "",
        state,
        names,
        generation=generation,
    )

    assert classify_provider("BRAND_NEW") == "unknown"
    assert classify_provider("JAV321") == "known_failing"
    assert "JAV321" in METATUBE_KNOWN_FAILING
    assert result == {"BRAND_NEW": True, "JAV321": False}
    assert state.is_available("metatube:BRAND_NEW") is True
    assert state.is_available("metatube:JAV321") is False


def test_jav321_removes_small_number_actor_tail_from_title(monkeypatch):
    detail_html = """
    <html><body>
      <a href="/video/sone-205">details</a>
      <h3>SONE-205 真のタイトル<small>女優名 / SONE-205</small></h3>
      <div class="col-md-3"><img src="https://pics.example/cover.jpg"></div>
      <div class="col-md-9"></div>
    </body></html>
    """
    monkeypatch.setattr(
        "core.scrapers.jav321.post_html",
        lambda *_args, **_kwargs: detail_html,
    )
    monkeypatch.setattr("core.scrapers.jav321.rate_limit", lambda *_a, **_k: None)

    scraper = _bare_scraper(JAV321Scraper, "jav321")
    scraper._proxy_kwargs = lambda: {}
    video = scraper.search("SONE-205")

    assert video is not None
    assert video.title == "真のタイトル"


def test_skip_format_check_is_limited_to_explicit_javdb(monkeypatch):
    api_calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(
        JavDBScraper,
        "search_via_api",
        lambda scraper, number: api_calls.append(
            (number, scraper.skip_format_check)
        ),
    )
    monkeypatch.setattr(JavDBScraper, "search_via_html", lambda *_a, **_k: None)

    assert (
        search_jav("MKD-S85", source="javdb", skip_format_check=True)
        is None
    )
    assert api_calls == [("MKD-S85", True)]

    api_calls.clear()
    assert search_jav("MKD-S85", source="javdb") is None
    assert api_calls == []

    with patch("core.scrapers.jav321.post_html") as post:
        assert (
            search_jav("SONE", source="jav321", skip_format_check=True)
            is None
        )
    post.assert_not_called()


def test_mobile_batch_search_uses_all_items_and_cancellation_generation():
    base = _read(PYTHON_WEB / "static/js/pages/search/state/base.js")
    batch = _read(PYTHON_WEB / "static/js/pages/search/state/batch.js")
    file_list = _read(PYTHON_WEB / "static/js/pages/search/state/file-list.js")
    search_flow = _read(
        PYTHON_WEB / "static/js/pages/search/state/search-flow.js"
    )
    rules = _read(
        PYTHON_WEB / "static/js/pages/search/batch-search-rules.js"
    )

    assert "batchSize" not in base
    assert "batchSize" not in batch
    assert "activePaths: []" in base
    assert "runId: 0" in base
    assert "const currentBatch = targetFiles;" in batch
    assert "const myRun = ++batch.runId;" in batch
    assert "const superseded = () => myRun !== batch.runId;" in batch
    assert "batch.activePaths.push(file.path);" in batch
    assert "batch.activePaths = batch.activePaths.filter" in batch
    assert "batch.runId = (batch.runId || 0) + 1;" in file_list
    assert search_flow.count("batchState.runId = (this.batchState.runId || 0) + 1;") >= 2
    assert "export function shouldAutoJump" in rules
    assert "currentPath === anchorPath" in rules


def test_enrich_estimate_and_skip_format_wiring_are_present():
    state_batch = _read(
        PYTHON_WEB / "static/js/pages/scanner/state-batch.js"
    )
    advanced = _read(
        PYTHON_WEB
        / "static/js/pages/search/state/advanced-picker.js"
    )
    search_ui = _read(PYTHON_WEB / "static/js/pages/search/ui.js")
    rescrape = _read(PYTHON_WEB / "static/js/shared/state-rescrape.js")

    assert "const SEC_NO_NFO = 1;" in state_batch
    assert "const SEC_COVER_ONLY = 10;" in state_batch
    assert "Math.ceil((noNfoCount * SEC_NO_NFO + coverOnlyCount * SEC_COVER_ONLY) / 60)" in state_batch
    assert "&skip_format_check=true" in advanced
    assert "&skip_format_check=true" in search_ui
    assert "skip_format_check: true" in rescrape
