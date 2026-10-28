"""
Claude (Anthropic) API 路由 - 提供模型查詢和翻譯測試功能

端點：
- POST /api/claude/models - 查詢可用 Haiku／Sonnet 列表
- POST /api/claude/test   - 翻譯測試
"""

from __future__ import annotations

import asyncio
from typing import List

from fastapi import APIRouter
from pydantic import BaseModel

from core.anthropic_client import (
    DEFAULT_CLAUDE_MODEL,
    AnthropicError,
    list_models,
    pick_translate_models,
    request_translation,
)
from core.cloud_translate import settings_error_key
from core.config import load_config
from core.logger import get_logger
from core.secret_fields import read_secret, resolve_secret
from core.translate_service import build_cloud_translate_prompt

logger = get_logger(__name__)

router = APIRouter(prefix="/api/claude", tags=["claude"])

class ModelsRequest(BaseModel):
    api_key: str = ""


class ModelsResponse(BaseModel):
    success: bool
    models: List[str] = []
    latest_haiku: str = ""
    default_model: str = ""
    error: str = ""


class TestTranslateRequest(BaseModel):
    api_key: str = ""
    model: str = ""


class TestTranslateResponse(BaseModel):
    success: bool
    translation: str = ""
    error: str = ""


def _resolve_claude_key(request_key: str, config: dict) -> str:
    return resolve_secret(request_key, read_secret(config, "translate.claude.api_key"))


@router.post("/models", response_model=ModelsResponse)
async def fetch_claude_models(request: ModelsRequest):
    """查詢 Anthropic 可用模型，過濾／排序後回 Haiku／Sonnet 清單。"""
    default_model = DEFAULT_CLAUDE_MODEL
    config = await asyncio.to_thread(load_config)
    key = _resolve_claude_key(request.api_key, config)

    if not key:
        return ModelsResponse(
            success=False,
            default_model=default_model,
            error="missing_key",
        )

    try:
        data = await list_models(key, timeout=10)
        models = pick_translate_models(data)
        latest_haiku = next((m for m in models if "haiku" in m.lower()), "")
        return ModelsResponse(
            success=True,
            models=models,
            latest_haiku=latest_haiku,
            default_model=default_model,
        )
    except AnthropicError as e:
        return ModelsResponse(
            success=False,
            default_model=default_model,
            error=settings_error_key(e.kind),
        )
    except Exception:
        logger.error("[Claude] 查詢模型列表失敗", exc_info=True)
        return ModelsResponse(
            success=False,
            default_model=default_model,
            error="http_error",
        )


@router.post("/test", response_model=TestTranslateResponse)
async def test_claude_translate(request: TestTranslateRequest):
    """測試 Anthropic 翻譯；與真翻譯共用 request_translation 路徑。"""
    if not request.model.strip():
        return TestTranslateResponse(success=False, error="missing_model")

    config = await asyncio.to_thread(load_config)
    key = _resolve_claude_key(request.api_key, config)

    if not key:
        return TestTranslateResponse(success=False, error="missing_key")

    locale = config.get("general", {}).get("locale", "zh-TW")
    if locale == "ja":
        return TestTranslateResponse(success=True, translation="ja_skip")

    test_title = "新人女優デビュー"
    prompt = build_cloud_translate_prompt(test_title, locale)

    try:
        translation = await request_translation(
            key, request.model, prompt, timeout=15
        )
        return TestTranslateResponse(success=True, translation=translation)
    except AnthropicError as e:
        return TestTranslateResponse(
            success=False,
            error=settings_error_key(e.kind),
        )
    except Exception:
        logger.error("[Claude] 測試翻譯失敗", exc_info=True)
        return TestTranslateResponse(success=False, error="translate_failed")
