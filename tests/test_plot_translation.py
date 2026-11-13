from __future__ import annotations

import asyncio

from core import anthropic_client, translate_service
from core.title_language import (
    plot_needs_translation,
    plot_translation_result_issue,
)


SOURCE = (
    "これは最初の段落です。\n\n"
    "これは二番目の段落で、作品の内容を詳しく説明します。"
)


def test_plot_validation_allows_paragraphs_and_rejects_failures():
    translated = "这是第一段。\n\n这是第二段，详细说明作品内容。"
    refusal = "抱歉，我无法协助翻译这段内容。"

    assert plot_needs_translation(SOURCE, "zh-CN") is True
    assert plot_needs_translation(translated, "zh-CN") is False
    assert plot_translation_result_issue(
        SOURCE,
        translated,
        "zh-CN",
    ) is None
    assert plot_translation_result_issue(
        SOURCE,
        refusal,
        "zh-CN",
    ) == "refusal"
    assert plot_translation_result_issue(
        SOURCE,
        SOURCE,
        "zh-CN",
    ) == "source_echo"
    assert plot_translation_result_issue(
        SOURCE,
        "This is an English synopsis.",
        "zh-CN",
    ) == "wrong_target_language"


def test_plot_prompts_require_complete_translation_without_title_cap():
    for locale in ("zh-CN", "zh-TW", "en", "ja", "ko"):
        prompt = translate_service.build_cloud_plot_translate_prompt(
            SOURCE,
            locale,
        )
        system, ollama_prompt = (
            translate_service.build_ollama_plot_prompts(SOURCE, locale)
        )
        lang = translate_service.LANGUAGE_PROMPTS[locale]

        assert lang["plot_instruction"] in prompt
        assert lang["plot_rules"] in prompt
        assert lang["plot_ollama_system"] in system
        assert lang["plot_label"] in ollama_prompt
        assert SOURCE in prompt
        assert SOURCE in ollama_prompt
        assert "50" not in lang["plot_rules"]
        assert "80" not in lang["plot_rules"]


def test_ollama_plot_translation_uses_full_synopsis_token_budget(monkeypatch):
    calls = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "message": {
                    "content": "这是第一段。\n\n这是第二段，详细说明作品内容。"
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

    monkeypatch.setattr(
        translate_service.httpx,
        "AsyncClient",
        FakeClient,
    )
    service = translate_service.OllamaTranslateService(
        {"url": "http://localhost:11434", "model": "test"},
        "zh-CN",
    )

    result = asyncio.run(
        service.translate_plot_or_raise(SOURCE, {"number": "ABC-107"})
    )

    assert result.startswith("这是第一段")
    assert calls["url"].endswith("/api/chat")
    assert calls["json"]["options"]["num_predict"] == (
        translate_service.PLOT_MAX_TOKENS
    )
    assert SOURCE in calls["json"]["messages"][1]["content"]


def test_claude_plot_translation_uses_extended_output_budget():
    payload = anthropic_client.build_translate_payload(
        "test-model",
        "translate this",
        max_tokens=translate_service.PLOT_MAX_TOKENS,
    )

    assert payload["max_tokens"] == translate_service.PLOT_MAX_TOKENS
    assert payload["max_tokens"] > anthropic_client.MAX_TOKENS
