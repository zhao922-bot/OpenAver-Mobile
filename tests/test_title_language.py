from __future__ import annotations

import asyncio

from core import translate_service
from core.title_language import (
    title_matches_target_language,
    title_needs_translation,
)


def test_chinese_target_rejects_the_other_script():
    assert title_matches_target_language("这是简体标题", "zh-CN") is True
    assert title_matches_target_language("這是繁體標題", "zh-CN") is False
    assert title_matches_target_language("這是繁體標題", "zh-TW") is True
    assert title_matches_target_language("这是简体标题", "zh-TW") is False


def test_japanese_target_requires_japanese_script():
    assert title_matches_target_language("これは日本語です", "ja") is True
    assert title_matches_target_language("中文标题", "ja") is False
    assert title_matches_target_language("English title", "ja") is False


def test_english_target_rejects_cjk_and_accepts_latin():
    assert title_matches_target_language("An English Title", "en") is True
    assert title_matches_target_language("日本語のタイトル", "en") is False
    assert title_matches_target_language("繁體中文標題", "en") is False


def test_translation_need_follows_the_active_locale():
    assert title_needs_translation("これは日本語です", "zh-CN") is True
    assert title_needs_translation("这是简体标题", "zh-CN") is False
    assert title_needs_translation("這是繁體標題", "zh-CN") is True
    assert title_needs_translation("English title", "en") is False
    assert title_needs_translation("これは日本語です", "en") is True


def test_all_four_locales_use_the_same_target_language_policy():
    cases = {
        "zh-CN": {
            "这是简体标题": False,
            "這是繁體標題": True,
            "これは日本語です": True,
            "English title": True,
        },
        "zh-TW": {
            "这是简体标题": True,
            "這是繁體標題": False,
            "これは日本語です": True,
            "English title": True,
        },
        "en": {
            "这是简体标题": True,
            "這是繁體標題": True,
            "これは日本語です": True,
            "English title": False,
        },
        "ja": {
            "这是简体标题": True,
            "這是繁體標題": True,
            "これは日本語です": False,
            "English title": True,
        },
    }
    for locale, titles in cases.items():
        for title, expected in titles.items():
            assert title_needs_translation(title, locale) is expected


def test_japanese_translation_prompt_has_a_real_provider_path(monkeypatch):
    calls = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "message": {
                    "content": "日本語に翻訳したタイトル",
                }
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json):
            calls["url"] = url
            calls["json"] = json
            return FakeResponse()

    monkeypatch.setattr(translate_service.httpx, "AsyncClient", FakeClient)
    service = translate_service.OllamaTranslateService(
        {"url": "http://localhost:11434", "model": "test"},
        "ja",
    )

    result = asyncio.run(service.translate_or_raise("English title"))

    assert result == "日本語に翻訳したタイトル"
    assert calls["url"].endswith("/api/chat")
    assert "日本語" in calls["json"]["messages"][0]["content"]
