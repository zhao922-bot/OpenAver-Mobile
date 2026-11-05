from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHOWCASE_JS = ROOT / "app/src/main/python/web/static/js/pages/showcase"


def test_actress_shortcut_fetches_a_server_filtered_subset():
    videos = (SHOWCASE_JS / "state-videos.js").read_text(encoding="utf-8")
    actress = (SHOWCASE_JS / "state-actress.js").read_text(encoding="utf-8")

    assert "params.set('actress', requestedActress)" in videos
    assert "_fullVideosLoaded = !isPaged && !confirmedActress" in videos
    assert "async _fetchActressFilteredVideos(actressName)" in videos
    assert "await this._fetchActressFilteredVideos(actressName)" in actress


def test_actress_shortcut_does_not_fall_back_to_the_full_list_first():
    actress = (SHOWCASE_JS / "state-actress.js").read_text(encoding="utf-8")
    start = actress.index("async searchActressFilms")
    end = actress.index("// 49a-T3:", start)
    body = actress[start:end]

    assert "this.search = actressName" not in body
    assert "this._animateFilter()" not in body
