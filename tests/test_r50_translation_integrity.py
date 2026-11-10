from __future__ import annotations

import asyncio

import pytest

from core import openai_client, translate_service
from core.cloud_translate import TranslateError


def test_openai_service_retries_a_model_refusal_once(monkeypatch):
    replies = iter([
        "抱歉，我无法协助翻译这个标题。",
        "这是严格重试后的正常译文",
    ])
    calls = []

    async def fake_request(base_url, api_key, model, prompt, *, timeout):
        calls.append(prompt)
        return next(replies)

    monkeypatch.setattr(openai_client, "request_translation", fake_request)
    service = translate_service.OpenAICompatibleTranslateService(
        {"base_url": "https://example.invalid/v1", "model": "test"},
        "zh-CN",
    )

    result = asyncio.run(service.translate_or_raise("日本語のタイトル"))

    assert result == "这是严格重试后的正常译文"
    assert len(calls) == 2
    assert calls[1] != calls[0]


def test_openai_service_does_not_return_a_second_refusal(monkeypatch):
    async def fake_request(base_url, api_key, model, prompt, *, timeout):
        return "抱歉，我无法协助翻译这个标题。"

    monkeypatch.setattr(openai_client, "request_translation", fake_request)
    service = translate_service.OpenAICompatibleTranslateService(
        {"base_url": "https://example.invalid/v1", "model": "test"},
        "zh-CN",
    )

    with pytest.raises(TranslateError) as raised:
        asyncio.run(service.translate_or_raise("日本語のタイトル"))

    assert raised.value.kind == "refused"


def test_openai_service_rejects_policy_refusal_after_retry(monkeypatch):
    refusal = (
        "抱歉，该标题涉及校园师生性内容，可能涉及未成年人，无法处理；"
        "其他标题欢迎再询。"
    )

    async def fake_request(base_url, api_key, model, prompt, *, timeout):
        return refusal

    monkeypatch.setattr(openai_client, "request_translation", fake_request)
    service = translate_service.OpenAICompatibleTranslateService(
        {"base_url": "https://example.invalid/v1", "model": "test"},
        "zh-CN",
    )

    with pytest.raises(TranslateError) as raised:
        asyncio.run(
            service.translate_or_raise(
                "あの美術の先生が僕らのチ○ポをこんなに下品に"
                "しゃぶってくれるなんて夢みたいだ 明里つむぎ"
            )
        )

    assert raised.value.kind == "refused"
    assert raised.value.error_type == "refusal"


def test_openai_validation_ignores_actor_proper_terms_from_context(monkeypatch):
    translated = (
        "这是一个正常的简体中文标题，包含较长的日语演员专名"
        "とても長い日本語の俳優名です"
    )

    async def fake_request(base_url, api_key, model, prompt, *, timeout):
        return translated

    monkeypatch.setattr(openai_client, "request_translation", fake_request)
    service = translate_service.OpenAICompatibleTranslateService(
        {"base_url": "https://example.invalid/v1", "model": "test"},
        "zh-CN",
    )

    result = asyncio.run(
        service.translate_or_raise(
            "日本語のタイトル",
            {"actors": ["とても長い日本語の俳優名です"]},
        )
    )

    assert result == translated


def test_openai_transport_retries_one_timeout(monkeypatch):
    calls = 0

    class Response:
        status_code = 200
        headers = {}

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {
                "choices": [
                    {
                        "message": {"content": "这是重试成功后的译文"},
                        "finish_reason": "stop",
                    }
                ]
            }

    async def fake_cloud_request(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TranslateError(
                "connection_timeout",
                None,
                "ReadTimeout",
                "simulated timeout",
            )
        return Response()

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(openai_client, "cloud_request", fake_cloud_request)
    monkeypatch.setattr(openai_client.asyncio, "sleep", no_sleep)

    result = asyncio.run(
        openai_client.request_translation(
            "https://example.invalid/v1",
            "key",
            "model",
            "prompt",
            timeout=1,
        )
    )

    assert result == "这是重试成功后的译文"
    assert calls == 2


def test_openai_transport_retries_rate_limit(monkeypatch):
    calls = 0

    class Response:
        headers = {"retry-after": "0"}

        def __init__(self, status_code, data=None):
            self.status_code = status_code
            self._data = data or {}

        @staticmethod
        def raise_for_status():
            return None

        def json(self):
            return self._data

    async def fake_cloud_request(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return Response(
                429,
                {"error": {"type": "rate_limit_error", "message": "slow down"}},
            )
        return Response(
            200,
            {
                "choices": [
                    {
                        "message": {"content": "这是限流重试后的译文"},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(openai_client, "cloud_request", fake_cloud_request)
    monkeypatch.setattr(openai_client.asyncio, "sleep", no_sleep)

    result = asyncio.run(
        openai_client.request_translation(
            "https://example.invalid/v1",
            "key",
            "model",
            "prompt",
            timeout=1,
        )
    )

    assert result == "这是限流重试后的译文"
    assert calls == 2
