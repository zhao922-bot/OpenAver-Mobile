"""自訂來源重刮預覽／確認共用：五結果映射與失敗分類（同一份，不得兩份）。"""
from core.scraper import (
    access_error_info, fetch_custom_by_detail_url, internal_nfo_carriers,
    search_custom_versions, source_display_name,
)
from core.scrapers.errors import (
    CustomSourceRefused, SourceBlocked, SourceParseEmpty, SourceUnreachable,
)
from core.i18n import get_config_locale, t
from web.routers._custom_gate import reason_text, refusal_for # noqa: PLC2701 — 卡片指定的 web 內部底線模組（165-T7b），同 router 層共用 gate 句表，尚未升格為公開名


def classify_custom_failure(exc: Exception, source: str) -> dict:
    """抓取例外 → 結構化失敗 dict；其餘 RuntimeError 併入「連不到」。"""
    if isinstance(exc, CustomSourceRefused):
        return {"success": False, "custom_error": "refused", "custom_reason": exc.reason, "source": source}
    if isinstance(exc, SourceParseEmpty):
        return {"success": False, "custom_error": "parse_empty", "source": source}
    if isinstance(exc, SourceBlocked):
        return {"success": False, "access_error": "refused", "source": source}
    return {"success": False, "access_error": "unreachable", "source": source}


def parse_empty_text(source: str, locale: str | None = None) -> str:
    locale = locale or get_config_locale()
    return t(
        "runtime.source.custom_parse_empty",
        locale=locale,
        name=source_display_name(source),
    )


def failure_text(
    exc: Exception,
    source: str,
    locale: str | None = None,
) -> str:
    locale = locale or get_config_locale()
    if isinstance(exc, CustomSourceRefused):
        return reason_text(exc.reason, locale)
    if isinstance(exc, SourceParseEmpty):
        return parse_empty_text(source, locale)
    return access_error_info(
        exc if isinstance(exc, SourceBlocked) else SourceUnreachable(),
        source,
        locale=locale,
    )["message"]


def preview_custom(
    source: str,
    number: str,
    locale: str | None = None,
) -> dict:
    locale = locale or get_config_locale()
    refused = refusal_for(source, number, locale)
    if refused:
        return {"success": False, "custom_error": "refused", "custom_reason": refused[0], "error": refused[1]}
    from core.custom_source.service import call_bounded  # lazy：AC-165-8
    try:
        versions = call_bounded(lambda: search_custom_versions(source, number))
    except RuntimeError as exc:
        return classify_custom_failure(exc, source)
    if not versions:
        return {"success": False, "custom_error": "not_found", "source": source}
    if len(versions) == 1:
        return {"success": True, **versions[0]}
    return {"success": True, "candidates": versions}


def custom_candidate_data(
    source: str,
    detail_url: str,
    number: str,
    locale: str | None = None,
):
    """確認用預抓：回 (scraper_data, error_response)，不 raise（形狀同 javlib 版）。"""
    locale = locale or get_config_locale()
    from core.custom_source.service import call_bounded  # lazy：AC-165-8
    try:
        video = call_bounded(lambda: fetch_custom_by_detail_url(source, detail_url, number))
    except RuntimeError as exc:
        return None, {
            **classify_custom_failure(exc, source),
            "error": failure_text(exc, source, locale),
        }
    if video is None:
        return None, {
            "success": False,
            "error": t(
                "runtime.api.custom_version_missing", locale=locale
            ),
        }
    data = video.to_legacy_dict()
    data.update(internal_nfo_carriers(video))
    return data, None
