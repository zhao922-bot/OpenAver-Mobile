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

    assert "var previousCoverState = new Map();" in state
    assert "previous.coverUrl === String(v.cover_url || '')" in state
    assert "v._imgLoaded = !!v.cover_url && sameCover" in state
    assert "v._coverRequested = index < 8" in state
    assert "|| (!!previous && previous.requested)" in state
    assert '<template x-if="video._coverRequested && video.cover_url">' in template
    assert 'x-intersect.margin.300px="video._coverRequested = true"' in template
    assert (
        'x-intersect:leave.margin.900px="video._coverRequested = false; '
        'video._imgLoaded = false"'
    ) in template
    assert 'decoding="async"' in template
    video_img = template.split('<template x-if="video._coverRequested && video.cover_url">', 1)[1].split('</template>', 1)[0]
    assert ':loading=' not in video_img
    assert "if ($el.complete && $el.naturalWidth > 0)" in video_img


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
    assert 'x-intersect.margin.300px="actress._photoRequested = true"' in template
    assert (
        'x-intersect:leave.margin.900px="actress._photoRequested = false"'
    ) in template
    actress_img = template.split('<template x-if="actress.photo_url && actress._photoRequested">', 1)[1].split('</template>', 1)[0]
    assert 'loading="lazy"' not in actress_img


def test_showcase_cover_errors_retry_once():
    state = (
        ROOT
        / "app/src/main/python/web/static/js/pages/showcase/state-base.js"
    ).read_text(encoding="utf-8")

    assert "video._coverRetryCount = retryCount + 1" in state
    assert "video.cover_url + separator + '_retry='" in state


def test_showcase_cover_refresh_remounts_image_window():
    lightbox = (
        ROOT
        / "app/src/main/python/web/static/js/pages/showcase/state-lightbox.js"
    ).read_text(encoding="utf-8")

    assert "video._coverRequested = true;" in lightbox
    assert "video._coverRetryCount = 0;" in lightbox
