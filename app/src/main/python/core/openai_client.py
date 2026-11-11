"""
OpenAI 相容 chat/completions 請求／解析／錯誤分類（OpenAI 翻譯唯一來源）。

不 import web.*、不 import core.translate_service。
失敗一律拋 TranslateError；log 只經 build_error。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from core.cloud_translate import (
    TranslateError,
    build_error,
    cloud_request,
    finalize_translation,
)
from core.logger import get_logger

TAG = "OpenAI"
_MAX_ATTEMPTS = 2
_DEFAULT_RETRY_DELAY = 0.8
_MAX_RETRY_DELAY = 8.0
logger = get_logger(__name__)

OPENAI_OFFICIAL_BASE_URL = "https://api.openai.com/v1"
OPENAI_NON_CHAT_TOKENS = (
    "embedding",
    "tts",
    "whisper",
    "audio",
    "transcribe",
    "realtime",
    "image",
    "dall-e",
    "moderation",
    "search",
    "codex",
)
_DATE_SUFFIX_RE = re.compile(r"-(?:\d{4}-\d{2}-\d{2}|\d{8})$")


def pick_official_models(models: list[tuple[str, int | None]]) -> list[str]:
    """Return chat-capable luna/terra/mini models without dated duplicates."""
    candidates: list[tuple[str, int | None]] = []
    for model_id_raw, created in models:
        model_id = (model_id_raw or "").lower()
        if not (
            any(token in model_id for token in ("luna", "terra", "mini"))
            and "nano" not in model_id
        ):
            continue
        if any(token in model_id for token in OPENAI_NON_CHAT_TOKENS):
            continue
        candidates.append((model_id_raw, created))

    ids_lower = {model_id.lower() for model_id, _ in candidates}
    filtered: list[tuple[str, int | None]] = []
    for model_id_raw, created in candidates:
        model_id = model_id_raw.lower()
        match = _DATE_SUFFIX_RE.search(model_id)
        if match is not None and model_id[: match.start()] in ids_lower:
            continue
        filtered.append((model_id_raw, created))

    filtered.sort(
        key=lambda item: (item[1] is None, -(item[1] or 0), item[0].lower())
    )
    return [model_id for model_id, _ in filtered]


def default_official_model(models: list[str]) -> str:
    """Prefer luna, then mini; return an empty string when neither exists."""
    for model_id in models:
        if "luna" in model_id.lower():
            return model_id
    for model_id in models:
        if "mini" in model_id.lower():
            return model_id
    return ""


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


def build_vision_payload(
    model: str,
    system: str,
    user_text: str,
    image_data_uri: str,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data_uri},
                    },
                ],
            },
        ],
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
    err_code = ""
    message = ""
    has_reasons = False
    try:
        body = resp.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            err_type = str(err.get("type") or "")
            err_code = str(err.get("code") or "")
            message = str(err.get("message") or "")
            meta = err.get("metadata")
            has_reasons = isinstance(meta, dict) and "reasons" in meta
    except Exception:
        err_type = ""
        err_code = ""
        message = getattr(resp, "reason_phrase", "") or ""

    if status == 401:
        return build_error(TAG, "auth_failed", status, err_type, message)
    if status == 403:
        lowered = message.lower()
        if has_reasons or "moderation" in lowered or "flagged" in lowered:
            return build_error(TAG, "blocked", status, err_type, message)
        return build_error(TAG, "forbidden", status, err_type, message)
    if status == 400 and (
        err_code == "content_policy_violation"
        or "safety system" in message.lower()
    ):
        return build_error(TAG, "blocked", status, err_type, message)
    if status == 404:
        return build_error(TAG, "not_found", status, err_type, message)
    if status in (429, 402):
        return build_error(TAG, "rate_limited", status, err_type, message)
    return build_error(TAG, "http_error", status, err_type, message)


def _retry_after_seconds(resp: httpx.Response) -> float:
    value = (resp.headers.get("retry-after") or "").strip()
    try:
        return min(max(float(value), 0.0), _MAX_RETRY_DELAY)
    except ValueError:
        return _DEFAULT_RETRY_DELAY


async def request_translation(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    *,
    timeout: float,
) -> str:
    """POST chat/completions with one bounded retry for transient failures."""
    last_error: TranslateError | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            resp = await cloud_request(
                TAG,
                "POST",
                base_url.rstrip("/") + "/chat/completions",
                headers=build_headers(api_key),
                timeout=timeout,
                json=build_translate_payload(model, prompt),
            )
            if resp.status_code == 429 or 500 <= resp.status_code <= 599:
                last_error = classify_http_error(resp)
                if attempt + 1 >= _MAX_ATTEMPTS:
                    raise last_error
                delay = _retry_after_seconds(resp)
                logger.warning(
                    "[OpenAI] transient status=%s; retrying in %.2fs",
                    resp.status_code,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
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
        except TranslateError as exc:
            last_error = exc
            if (
                attempt + 1 >= _MAX_ATTEMPTS
                or exc.kind not in ("connection_timeout", "connection_failed")
            ):
                raise
            logger.warning(
                "[OpenAI] transient failure=%s; retrying in %.2fs",
                exc.kind,
                _DEFAULT_RETRY_DELAY,
            )
            await asyncio.sleep(_DEFAULT_RETRY_DELAY)

    if last_error is not None:
        raise last_error
    raise build_error(TAG, "api_error", None, "", "translation retry exhausted")


async def request_vision(
    base_url: str,
    api_key: str,
    model: str,
    system: str,
    user_text: str,
    image_data_uri: str,
    *,
    timeout: float,
) -> str:
    """POST chat/completions with one image, preserving bounded retries."""
    last_error: TranslateError | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            resp = await cloud_request(
                TAG,
                "POST",
                base_url.rstrip("/") + "/chat/completions",
                headers=build_headers(api_key),
                timeout=timeout,
                json=build_vision_payload(
                    model, system, user_text, image_data_uri
                ),
            )
            if resp.status_code == 429 or 500 <= resp.status_code <= 599:
                last_error = classify_http_error(resp)
                if attempt + 1 >= _MAX_ATTEMPTS:
                    raise last_error
                await asyncio.sleep(_retry_after_seconds(resp))
                continue
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise classify_http_error(e.response) from None
            try:
                data = resp.json()
            except Exception as e:
                raise build_error(
                    TAG, "api_error", None, "", f"invalid JSON: {e}"
                ) from e
            if not isinstance(data, dict):
                raise build_error(
                    TAG,
                    "api_error",
                    None,
                    "",
                    "response is not a JSON object",
                )
            return extract_text(data)
        except TranslateError as exc:
            last_error = exc
            if (
                attempt + 1 >= _MAX_ATTEMPTS
                or exc.kind not in ("connection_timeout", "connection_failed")
            ):
                raise
            await asyncio.sleep(_DEFAULT_RETRY_DELAY)
    if last_error is not None:
        raise last_error
    raise build_error(TAG, "api_error", None, "", "vision retry exhausted")
