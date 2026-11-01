import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_code_health_report_collects_core_metrics(tmp_path):
    python_file = tmp_path / "app/src/main/python/example.py"
    python_file.parent.mkdir(parents=True)
    python_file.write_text(
        "def choose(value):\n"
        "    if value and value > 1:\n"
        "        return 1\n"
        "    return 0\n",
        encoding="utf-8",
    )
    theme = tmp_path / "app/src/main/python/web/static/css/theme.css"
    theme.parent.mkdir(parents=True)
    theme.write_text(".button { color: red; }\n", encoding="utf-8")
    bundle = theme.with_name("tailwind.css")
    bundle.write_text(
        ".button { color: red; }\n.extra { display: block; }\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "patches/manifest.json"
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps({"patches": [{"files": ["example.py"]}]}),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/code_health.py"),
            "--root",
            str(tmp_path),
            "--json",
            "--top",
            "5",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    report = json.loads(result.stdout)

    assert report["summary"]["files_by_extension"][".py"] == 1
    assert report["summary"]["files_by_extension"][".css"] == 2
    assert report["top_complexity"][0]["name"] == "choose"
    assert report["top_complexity"][0]["complexity"] >= 2
    assert report["css"]["exact_overlap"] == 1
    assert report["css"]["overlap_percent"] == 100.0
    assert report["css"]["loaded_exact_overlap"] == 1
    assert report["css"]["loaded_overlap_percent"] == 100.0
    assert report["patches"] == {"patches": 1, "files": 1}


def test_code_health_separates_raw_css_overlap_from_loaded_overlap(tmp_path):
    theme = tmp_path / "app/src/main/python/web/static/css/theme.css"
    theme.parent.mkdir(parents=True)
    theme.write_text(".button { color: red; }\n", encoding="utf-8")
    theme.with_name("tailwind.css").write_text(
        ".button { color: red; }\n.extra { display: block; }\n",
        encoding="utf-8",
    )
    base = tmp_path / "app/src/main/python/web/templates/base.html"
    base.parent.mkdir(parents=True)
    base.write_text(
        '<link href="/static/css/tailwind.css?v=1" rel="stylesheet">\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/code_health.py"),
            "--root",
            str(tmp_path),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    report = json.loads(result.stdout)

    assert report["css"]["exact_overlap"] == 1
    assert report["css"]["overlap_percent"] == 100.0
    assert report["css"]["loaded_theme_rules"] == 0
    assert report["css"]["loaded_exact_overlap"] == 0
    assert report["css"]["loaded_overlap_percent"] == 0.0


def test_repository_loaded_css_overlap_stays_below_five_percent():
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/code_health.py"),
            "--root",
            str(ROOT),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    report = json.loads(result.stdout)

    assert report["css"]["loaded_overlap_percent"] < 5.0
