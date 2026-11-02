from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_showcase_video_covers_use_a_bounded_image_window():
    state = (
        ROOT
        / "app/src/main/python/web/static/js/pages/showcase/state-videos.js"
    ).read_text(encoding="utf-8")
    template = (
        ROOT
        / "app/src/main/python/web/templates/showcase.html"
    ).read_text(encoding="utf-8")

    assert "v._coverRequested = index < 8" in state
    assert "SHOWCASE_MOBILE_GRID_PAGE_SIZE = 45" in (
        ROOT
        / "app/src/main/python/web/static/js/pages/showcase/state-base.js"
    ).read_text(encoding="utf-8")
    assert "this.perPage = Math.min(this.perPage, SHOWCASE_MOBILE_GRID_PAGE_SIZE)" in (
        ROOT
        / "app/src/main/python/web/static/js/pages/showcase/state-base.js"
    ).read_text(encoding="utf-8")
    assert '<template x-if="video._coverRequested && video.cover_url">' in template
    assert 'x-intersect.margin.900px="video._coverRequested = true"' in template
    assert (
        'x-intersect:leave.margin.2400px="video._coverRequested = false; '
        'video._imgLoaded = false"'
    ) in template
    assert 'decoding="async"' in template


def test_showcase_actress_photos_share_the_image_window():
    state = (
        ROOT
        / "app/src/main/python/web/static/js/pages/showcase/state-actress.js"
    ).read_text(encoding="utf-8")
    template = (
        ROOT
        / "app/src/main/python/web/templates/showcase.html"
    ).read_text(encoding="utf-8")

    assert "actress._photoRequested = index < 8" in state
    assert '<template x-if="actress.photo_url && actress._photoRequested">' in template
    assert 'x-intersect.margin.900px="actress._photoRequested = true"' in template
    assert (
        'x-intersect:leave.margin.2400px="actress._photoRequested = false"'
    ) in template
