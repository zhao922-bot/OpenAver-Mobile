"""
OpenAI 相容 chat/completions 請求／解析／錯誤分類（OpenAI 翻譯唯一來源）。

不 import web.*、不 import core.translate_service。
失敗一律拋 TranslateError；log 只經 build_error。
"""

from __future__ import annotations

from typing import Any

import httpx

from core.cloud_translate import (
    TranslateError,
    build_error,
    cloud_request,
    finalize_translation,
)

TAG = "OpenAI"


def build_headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = (api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def build_translate_payload(model: str, prompt: str) -> dict[str, Any]:
    # 刻意不送任何生成參數（上限／溫度／思考）
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }


def extract_text(data: dict) -> str:
    """判定順序見 CD-171-4（先中先贏）；成功回非空譯文，失敗拋 TranslateError。"""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise build_error(TAG, "api_error", None, "", "response missing choices")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        message = {}

    finish_reason = choice.get("finish_reason")
    if finish_reason in ("content_filter", "refusal"):
        raise build_error(TAG, "blocked", None, str(finish_reason), f"finish_reason={finish_reason}")
    if message.get("refusal"):
        raise build_error(TAG, "blocked", None, "refusal", "message.refusal present")
    if finish_reason == "length":
        raise build_error(TAG, "truncated", None, "length", "finish_reason=length")
    if finish_reason not in (None, "", "stop"):
        # fail-closed：未知終止原因（error／insufficient_system_resource…）帶部分內容不得當成功
        raise build_error(TAG, "truncated", None, str(finish_reason), f"finish_reason={finish_reason}")

    content = message.get("content")
    text = content.strip() if isinstance(content, str) else ""
    if not text:
        raise build_error(TAG, "empty_response", None, "", "empty text content")
    return finalize_translation(TAG, text)


def classify_http_error(resp: httpx.Response) -> TranslateError:
    """依狀態碼與 error 欄位分類；非 JSON 本體仍回 TranslateError。"""
    status = resp.status_code
    err_type = ""
    message = ""
    has_reasons = False
    try:
        body = resp.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            err_type = str(err.get("type") or "")
            message = str(err.get("message") or "")
            meta = err.get("metadata")
            has_reasons = isinstance(meta, dict) and "reasons" in meta
    except Exception:
        err_type = ""
        message = getattr(resp, "reason_phrase", "") or ""

    if status == 401:
        return build_error(TAG, "auth_failed", status, err_type, message)
    if status == 403:
        lowered = message.lower()
        if has_reasons or "moderation" in lowered or "flagged" in lowered:
            return build_error(TAG, "blocked", status, err_type, message)
        return build_error(TAG, "forbidden", status, err_type, message)
    if status == 404:
        return build_error(TAG, "not_found", status, err_type, message)
    if status in (429, 402):
        return build_error(TAG, "rate_limited", status, err_type, message)
    return build_error(TAG, "http_error", status, err_type, message)


async def request_translation(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    *,
    timeout: float,
) -> str:
    """POST <base_url>/chat/completions；成功回非空 str，失敗拋 TranslateError。"""
    resp = await cloud_request(
        TAG,
        "POST",
        base_url.rstrip("/") + "/chat/completions",
        headers=build_headers(api_key),
        timeout=timeout,
        json=build_translate_payload(model, prompt),
    )
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise classify_http_error(e.response) from None

    try:
        data = resp.json()
    except Exception as e:
        raise build_error(TAG, "api_error", None, "", f"invalid JSON: {e}") from e
    if not isinstance(data, dict):
        raise build_error(TAG, "api_error", None, "", "response is not a JSON object")
    return extract_text(data)
