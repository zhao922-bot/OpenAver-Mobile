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
