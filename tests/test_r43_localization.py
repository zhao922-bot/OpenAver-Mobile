from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

try:
    import opencc
except ImportError:  # pragma: no cover
    opencc = None

from core.gallery_generator import HTMLGenerator, _GALLERY_LABELS
from core.gallery_scanner import VideoInfo
from core.enricher import enrich_single, fetch_samples_only_detailed
from core.i18n import (
    FALLBACK_LOCALE,
    SUPPORTED_LOCALES,
    normalize_locale,
    t,
)
from core.readonly_producer import ProduceOutcome
from web.routers.scanner import _outcome_to_sse


LOCALES_DIR = Path(__file__).resolve().parents[1] / "app" / "src" / "main" / "python" / "locales"
ANDROID_RES_DIR = Path(__file__).resolve().parents[1] / "app" / "src" / "main" / "res"

# These strings intentionally document literal filename/format tokens rather
# than declaring interpolation parameters.
LITERAL_PLACEHOLDER_KEYS = {
    "settings.scraper.external_manager_off_hint",
    "settings.scraper.external_manager_jellyfin_hint",
    "settings.scraper.external_manager_emby_hint",
    "settings.scraper.external_manager_kodi_hint",
    "help.scanner.multiversion_intro",
    "help.scanner.jellyfin_enable",
}


def _flatten(value, prefix: str = "") -> dict[str, str]:
    if not isinstance(value, dict):
        return {prefix: value}
    result = {}
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        result.update(_flatten(child, path))
    return result


def _load_locales() -> dict[str, dict[str, str]]:
    return {
        path.stem: _flatten(json.loads(path.read_text(encoding="utf-8")))
        for path in LOCALES_DIR.glob("*.json")
    }


def test_locale_files_have_identical_keys_and_placeholders():
    locales = _load_locales()
    assert set(locales) == {"en", "ja", "zh_CN", "zh_TW"}

    base_keys = set(locales["zh_CN"])
    for name, messages in locales.items():
        assert set(messages) == base_keys, f"{name} has key drift"

    base = locales["zh_CN"]
    for name, messages in locales.items():
        for key, value in messages.items():
            if key in LITERAL_PLACEHOLDER_KEYS:
                continue
            assert set(re.findall(r"\{(\w+)\}", value)) == set(
                re.findall(r"\{(\w+)\}", base[key])
            ), f"placeholder drift: {name}:{key}"


def test_locale_fallback_is_simplified_chinese():
    assert FALLBACK_LOCALE == "zh-CN"
    assert normalize_locale(None) == "zh-CN"
    assert normalize_locale("fr") == "zh-CN"
    assert t("runtime.translate.disabled", None) == "翻译功能未启用"
    assert t("runtime.translate.disabled", "fr") == "翻译功能未启用"


def test_simplified_chinese_contains_no_traditional_characters():
    assert opencc is not None, (
        "opencc 未安装，这条守门测试无法执行。"
        "请运行 pip install -r requirements-test.txt"
    )
    converter = opencc.OpenCC("t2s")
    messages = _load_locales()["zh_CN"]
    changed = {
        key: value
        for key, value in messages.items()
        if isinstance(value, str) and converter.convert(value) != value
    }
    assert changed == {}


def test_traditional_chinese_contains_no_simplified_characters():
    assert opencc is not None, (
        "opencc 未安装，这条守门测试无法执行。"
        "请运行 pip install -r requirements-test.txt"
    )
    converter = opencc.OpenCC("s2t")
    messages = _load_locales()["zh_TW"]
    # These characters are valid in Traditional Chinese but are also the
    # simplified-form keys OpenCC's character-level s2t conversion rewrites to
    # unrelated variants (只 -> 隻, 干 -> 幹, 游 -> 遊, 床 -> 牀, etc.).
    valid_variants = "只吃干游床台才"
    protected = {
        ord(char): chr(0xE000 + index)
        for index, char in enumerate(valid_variants)
    }
    changed = {
        key: value
        for key, value in messages.items()
        if isinstance(value, str)
        and converter.convert(value.translate(protected)) != value.translate(protected)
    }
    assert changed == {}


def test_traditional_chinese_avoids_known_opencc_overconversions():
    messages = _load_locales()["zh_TW"]
    text = "\n".join(value for value in messages.values() if isinstance(value, str))
    for term in ("隻影響", "喫", "幹擾", "遊標", "圖牀", "纔有"):
        assert term not in text


def test_android_native_strings_cover_all_ui_locales():
    locale_dirs = {
        "zh-CN": "values-zh",
        "zh-TW": "values-zh-rTW",
        "ja": "values-ja",
        "en": "values-en",
    }
    messages = {}
    for locale, dirname in locale_dirs.items():
        root = ET.parse(ANDROID_RES_DIR / dirname / "strings.xml").getroot()
        messages[locale] = {
            node.attrib["name"]: node.text or ""
            for node in root.findall("string")
        }

    base_keys = set(messages["zh-CN"])
    for locale, strings in messages.items():
        assert set(strings) == base_keys, f"Android string drift: {locale}"
        for key, value in strings.items():
            assert set(re.findall(r"%\d+\$[sd]", value)) == set(
                re.findall(r"%\d+\$[sd]", messages["zh-CN"][key])
            ), f"Android placeholder drift: {locale}:{key}"


def test_gallery_html_uses_the_selected_locale(tmp_path):
    generator = HTMLGenerator()
    video = VideoInfo(
        path="file:///video.mp4",
        title="ABC-123 Title",
        num="ABC-123",
    )

    for locale in SUPPORTED_LOCALES:
        output = tmp_path / f"gallery-{locale}.html"
        generator.generate([video], str(output), locale=locale)
        content = output.read_text(encoding="utf-8")
        labels = _GALLERY_LABELS[locale]
        assert f'<html lang="{locale}"' in content
        assert labels["search_placeholder"] in content
        assert labels["table_title"] in content
        assert labels["next_page"] in content


def test_frontend_does_not_hardcode_traditional_locale_for_dates():
    web_root = Path(__file__).resolve().parents[1] / "app" / "src" / "main" / "python" / "web"
    offenders = []
    for path in web_root.rglob("*"):
        if path.suffix not in {".js", ".html"}:
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"toLocale(?:String|DateString)\(\s*['\"]zh-TW['\"]", text):
            offenders.append(str(path.relative_to(web_root)))
    assert offenders == []


def test_enrichment_errors_follow_the_selected_locale(tmp_path):
    missing = str(tmp_path / "missing.mp4")
    for locale in SUPPORTED_LOCALES:
        result = enrich_single(
            file_path=missing,
            number="ABC-123",
            locale=locale,
        )
        assert result.error == t("runtime.samples.error_file_not_found", locale)

        sample_result, _ = fetch_samples_only_detailed(
            file_path=missing,
            number="ABC-123",
            locale=locale,
        )
        assert sample_result.error == t(
            "runtime.samples.error_file_not_found", locale
        )


def test_scanner_failure_log_does_not_leak_producer_chinese():
    for locale in SUPPORTED_LOCALES:
        event = _outcome_to_sse(
            ProduceOutcome(
                source_uri="file:///video.mp4",
                status="failed",
                number="ABC-123",
                error="生成失敗",
            ),
            locale,
        )
        assert event["message"].endswith(
            t(
                "runtime.scanner.outcome_error_suffix",
                locale,
                error=t("runtime.scanner.generate_failed", locale),
            )
        )
