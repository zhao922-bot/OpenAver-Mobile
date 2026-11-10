"""Jable.tv scraper backed by the shared Cloudflare transport."""
from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup

from core.cf_transport import (
    CfChallengeRequired,
    CfTransportUnavailable,
    get_cf_transport,
)
from core.scrapers.base import BaseScraper
from core.scrapers.models import Actress, Video
from core.scrapers.utils import strip_number_prefix
from core.source_probe import (
    VERIFIER_PROBE_HEADERS,
    ProbePlan,
    ProbeTarget,
)


BASE_URL = "https://jable.tv"
JABLE_ORIGIN = f"{BASE_URL}/"
JABLE_ALLOWED_NETLOCS = frozenset({"jable.tv", "www.jable.tv"})

_DATE_RE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
_DURATION_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?::(\d{2}))?(?!\d)")


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").split()).strip()


def _meta_content(soup: BeautifulSoup, *, property_name: str = "", name: str = "") -> str:
    if property_name:
        node = soup.select_one(f'meta[property="{property_name}"]')
        if node and node.get("content"):
            return _clean_text(node.get("content"))
    if name:
        node = soup.select_one(f'meta[name="{name}"]')
        if node and node.get("content"):
            return _clean_text(node.get("content"))
    return ""


def _page_title(soup: BeautifulSoup) -> str:
    node = soup.find("title")
    return _clean_text(node.get_text(" ", strip=True) if node else "")


def _is_cf_challenge(title: str, html: str) -> bool:
    title_lc = title.lower()
    if "just a moment" in title_lc or "attention required" in title_lc:
        return True
    lower = html.lower()
    return (
        "cf-mitigated" in lower
        or "cf-turnstile-response" in lower
        or "challenge-platform" in lower
    )


def _raise_if_cf(soup: BeautifulSoup, html: str) -> None:
    if _is_cf_challenge(_page_title(soup), html):
        raise CfChallengeRequired("Jable Cloudflare verification is required")


def _normalise_image_url(value: str) -> str:
    value = (value or "").strip()
    if value.startswith("//"):
        return f"https:{value}"
    if value.startswith("/"):
        return f"{BASE_URL}{value}"
    return value


def _extract_actresses(soup: BeautifulSoup) -> list[str]:
    scope = (
        soup.select_one(".info-header")
        or soup.select_one(".video-info")
        or soup.select_one(".header-left")
        or soup
    )
    out: list[str] = []
    seen: set[str] = set()
    selectors = (
        "a.model",
        ".models a",
        "a[href*='/models/']",
    )
    for selector in selectors:
        for node in scope.select(selector):
            image = node.find("img", title=True)
            placeholder = node.find(attrs={"title": True})
            name = _clean_text(
                node.get("title")
                or (image.get("title") if image else "")
                or (placeholder.get("title") if placeholder else "")
                or node.get_text(" ", strip=True)
            )
            if not name or name in seen:
                continue
            seen.add(name)
            out.append(name)
        if out:
            break
    return out


def _extract_tags(soup: BeautifulSoup) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    selectors = (
        "h5.tags a",
        ".tags a",
        ".video-tags a",
        "a[href*='/tags/']",
        "a[href*='/categories/']",
    )

    # Prefer the video information block. Page-wide /tags/ links also occur in
    # site navigation and recommendations, so they must not be a first resort.
    scopes = [
        soup.select_one(".video-info"),
        soup.select_one(".info-header"),
        soup.select_one(".header-left"),
    ]
    for scope in (node for node in scopes if node is not None):
        for selector in selectors:
            for node in scope.select(selector):
                tag = _clean_text(node.get_text(" ", strip=True))
                if not tag or tag in seen:
                    continue
                seen.add(tag)
                out.append(tag)
            if out:
                return out

    # Some Jable layouts place the tag heading outside the info block.
    for node in soup.select("h5.tags a"):
        tag = _clean_text(node.get_text(" ", strip=True))
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def _extract_date(soup: BeautifulSoup) -> str:
    scope = (
        soup.select_one(".info-header")
        or soup.select_one(".video-info")
        or soup.select_one(".header-left")
        or soup
    )
    match = _DATE_RE.search(scope.get_text(" ", strip=True))
    return match.group(1) if match else ""


def _extract_duration_minutes(soup: BeautifulSoup) -> Optional[int]:
    for selector in (
        ".duration",
        ".video-duration",
        ".info-header .duration",
        ".info-header span.label",
    ):
        node = soup.select_one(selector)
        if not node:
            continue
        match = _DURATION_RE.search(node.get_text(" ", strip=True))
        if not match:
            continue
        first, second, third = match.groups()
        if third is None:
            minutes = int(first)
        else:
            minutes = int(first) * 60 + int(second)
        if minutes > 0:
            return minutes
    return None


def parse_detail(html: str, number: str, detail_url: str) -> Optional[dict]:
    """Parse a Jable detail page.

    Returns ``None`` for a genuine 404 page. Cloudflare interstitials raise
    ``CfChallengeRequired`` so the caller can open the verification window.
    """
    soup = BeautifulSoup(html, "html.parser")
    _raise_if_cf(soup, html)

    page_title = _page_title(soup)
    if "404" in page_title.lower() and not soup.select_one(".info-header, .video-info"):
        return None

    title_node = soup.select_one(
        ".info-header h4, .video-info h4, .header-left h4"
    )
    raw_title = (
        _meta_content(soup, property_name="og:title")
        or _clean_text(title_node.get_text(" ", strip=True) if title_node else "")
        or page_title.removesuffix(" - Jable.TV").removesuffix(" - Jable.tv")
    )
    title = strip_number_prefix(_clean_text(raw_title), number)

    poster = soup.select_one("video[poster]")
    cover_url = (
        _meta_content(soup, property_name="og:image")
        or _normalise_image_url(poster.get("poster", "") if poster else "")
    )

    if not title and not cover_url:
        return None

    description_node = soup.select_one(".description, .video-description")
    summary = (
        _clean_text(
            description_node.get_text(" ", strip=True) if description_node else ""
        )
        or _meta_content(soup, property_name="og:description")
        or _meta_content(soup, name="description")
    )

    return {
        "number": number,
        "title": title,
        "cover_url": cover_url,
        "date": _extract_date(soup),
        "duration": _extract_duration_minutes(soup),
        "actresses": _extract_actresses(soup),
        "tags": _extract_tags(soup),
        "summary": summary,
        # Jable exposes only a poster and player-scrubbing storyboards. The page
        # has no screenshot gallery, so treating other CDN images as samples
        # would capture recommendation covers, logos, and actress avatars.
        "sample_images": [],
        "detail_url": detail_url,
    }


class JableScraper(BaseScraper):
    """Exact-number Jable scraper using the Android/desktop CF transport."""

    SAMPLE_NUMBER = "SSIS-001"

    def _get_source_name(self) -> str:
        return "jable"

    def probe_plan(self, timeout):
        session = self._new_session()

        def send():
            return session.get(
                JABLE_ORIGIN,
                headers=VERIFIER_PROBE_HEADERS,
                timeout=timeout,
                stream=True,
            )

        return ProbePlan(
            [ProbeTarget("jable.tv", send, cf_challenge_ok=True)]
        )

    def search(self, number: str) -> Optional[Video]:
        transport = get_cf_transport()
        if transport is None:
            raise CfTransportUnavailable(
                "Jable scraper requires the Cloudflare verification transport"
            )

        number = self.normalize_number(number)
        if not self.validate_number(number):
            raise ValueError(f"Invalid number format: {number}")

        slug = number.lower()
        detail_url = f"{BASE_URL}/videos/{slug}/"
        html = transport.fetch(detail_url, cache_key="jable")
        fields = parse_detail(html, number, detail_url)
        if fields is None:
            return None

        return Video(
            number=number,
            title=fields["title"],
            actresses=[
                Actress(name=name) for name in fields["actresses"] if name.strip()
            ],
            date=fields["date"],
            cover_url=fields["cover_url"],
            tags=fields["tags"],
            source="jable",
            detail_url=fields["detail_url"],
            duration=fields["duration"],
            sample_images=fields["sample_images"],
            summary=fields["summary"],
        )

    def search_by_keyword(self, keyword: str, limit: int = 20) -> list[Video]:
        """Jable is exposed as an exact-number, manual-only source."""
        return []
