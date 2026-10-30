import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_WEB = ROOT / "app/src/main/python/web"
LOCALES = ROOT / "app/src/main/python/locales"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_donut_legend_explains_rings_and_main_studio_rule():
    template = read(PYTHON_WEB / "templates/insights.html")

    for key in (
        "insights.donut.legend_inner",
        "insights.donut.legend_outer",
        "insights.donut.legend_unknown",
        "insights.donut.legend_rule",
    ):
        assert key in template


def test_deep_dive_has_mobile_safe_structure():
    template = read(PYTHON_WEB / "templates/insights.html")
    css = read(PYTHON_WEB / "static/css/pages/insights.css")
    state = read(PYTHON_WEB / "static/js/pages/insights/state.js")

    assert "insights.gantt.subtitle" in template
    assert "insights.gantt.scroll_hint" in template
    assert "ganttAxisLabel(col, ganttAxis)" in template
    assert "insights.solo.subtitle" in template
    assert "--gantt-cell-track: 2rem;" in css
    assert "grid-template-columns: 1fr;" in css
    assert "grid-template-areas:" in css
    assert "var(--gantt-cell-track)" in state
    assert "ganttAxisLabel(value, axis)" in state


def test_deep_dive_locales_are_complete():
    required_donut = {
        "legend_inner",
        "legend_outer",
        "legend_unknown",
        "legend_rule",
    }

    for path in sorted(LOCALES.glob("*.json")):
        data = json.loads(read(path))
        insights = data["insights"]
        assert required_donut <= set(insights["donut"]), path.name
        assert insights["gantt"]["subtitle"], path.name
        assert insights["gantt"]["scroll_hint"], path.name
        assert insights["solo"]["subtitle"], path.name


def test_gantt_dots_use_actual_maker_colors():
    aggregate = read(PYTHON_WEB / "static/js/pages/insights/aggregate.js")
    charts = read(PYTHON_WEB / "static/js/pages/insights/charts.js")
    template = read(PYTHON_WEB / "templates/insights.html")
    css = read(PYTHON_WEB / "static/css/pages/insights.css")

    assert "function dominantNamedMaker(films)" in aggregate
    assert "maker: dominant.maker" in aggregate
    assert "function fallbackMakerColor(name)" in charts
    assert "return fallbackMakerColor(name);" in charts
    assert "_makerColorRegistry" in charts
    assert "setMakerColorSlots(slots, getRecords());" in read(
        PYTHON_WEB / "static/js/pages/insights/state.js"
    )
    assert "--insights-maker-16:" in css
    assert "--gantt-cell-color:" in template
    assert "background: var(--gantt-cell-color, var(--text-muted));" in css
