from __future__ import annotations

import httpx

from core import openai_client, translate_service
from core.translate_service import OpenAICompatibleTranslateService


def test_official_model_picker_filters_non_chat_and_dated_duplicates():
    models = [
        ("gpt-4o-mini-2024-07-18", 1),
        ("gpt-4o-mini", 2),
        ("text-embedding-3-mini", 3),
        ("gpt-4o-mini-tts", 4),
        ("chatgpt-luna", 5),
        ("gpt-terra", 6),
        ("gpt-4o-mini-nano", 7),
    ]

    picked = openai_client.pick_official_models(models)

    assert picked == ["gpt-terra", "chatgpt-luna", "gpt-4o-mini"]
    assert openai_client.default_official_model(picked) == "chatgpt-luna"


def test_official_model_picker_prefers_luna_then_mini():
    assert openai_client.default_official_model(
        ["gpt-terra", "gpt-4o-mini", "chatgpt-luna"]
    ) == "chatgpt-luna"
    assert openai_client.default_official_model(
        ["gpt-terra", "gpt-4o-mini"]
    ) == "gpt-4o-mini"
    assert openai_client.default_official_model(["gpt-terra"]) == ""


def test_official_translate_factory_uses_fixed_endpoint():
    service = translate_service.create_translate_service(
        {
            "provider": "openai_official",
            "openai_official": {"api_key": "sk-test", "model": "chatgpt-luna"},
        }
    )

    assert isinstance(service, OpenAICompatibleTranslateService)
    assert service.base_url == openai_client.OPENAI_OFFICIAL_BASE_URL
    assert service.base_url == "https://api.openai.com/v1"
    assert service.api_key == "sk-test"
    assert service.model == "chatgpt-luna"


def test_content_policy_400_is_classified_as_blocked():
    response = httpx.Response(
        400,
        json={
            "error": {
                "type": "invalid_request_error",
                "code": "content_policy_violation",
                "message": "The safety system rejected this request.",
            }
        },
    )

    error = openai_client.classify_http_error(response)

    assert error.kind == "blocked"
    assert error.status == 400
