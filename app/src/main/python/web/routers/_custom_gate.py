"""自訂來源路由層 gate 轉譯：reason 碼 → 當前介面語言的說明（不重寫判斷）。"""
from typing import Optional, Tuple

from core.scraper import normalize_number
from core.source_config import validate_source_id
from core.i18n import get_config_locale, t

REASON_KEYS = {
    "not_loaded": "custom_not_loaded",
    "load_failed": "custom_load_failed",
    "verifying": "custom_verifying",
    "unverified": "custom_unverified",
    "failed": "custom_failed",
    "disabled": "custom_disabled",
    "pattern_mismatch": "custom_pattern_mismatch",
}


def reason_text(reason: str, locale: str | None = None) -> str:
    locale = locale or get_config_locale()
    key = REASON_KEYS.get(reason, REASON_KEYS["not_loaded"])
    return t(f"runtime.source.{key}", locale=locale)


def refusal_for(
    source: str,
    number: str,
    locale: str | None = None,
) -> Optional[Tuple[str, str]]:
    """custom:<id> 沒過 gate → (reason, 句)；可用 → None。"""
    locale = locale or get_config_locale()
    if not validate_source_id(source):
        return "not_loaded", reason_text("not_loaded", locale)
    from core.custom_source import gate  # lazy：AC-165-8
    result = gate.check_usable(source.split(":", 1)[1], normalize_number(number))
    if result.ok:
        return None
    return result.reason, reason_text(result.reason, locale)
